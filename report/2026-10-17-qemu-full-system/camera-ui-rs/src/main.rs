//! Sony ILCE-7CM2 (α7C II) QEMU 原固件 —— 机身控制原型（eframe/egui，跨平台）
//!
//! 原型阶段 / 接真实后端的接口约定
//! ==============================
//!
//! 统一出口为 `App::emit(Event)`，当前实现仅写入右侧日志面板并打印到 stdout。
//! 接真实后端时在 `emit` 内追加 HTTP 调用即可，事件 JSON 形状不变：
//!
//!     POST /api/input  (QEMU 输入桥接服务)
//!     Content-Type: application/json
//!
//!     按键: {"kind":"key","key":"MENU"}        // MENU/ENTER/UP/DOWN/LEFT/RIGHT/
//!                                              // AF_ON/FN/C1/C2/PLAY/DELETE/REC/SHUTTER/STILL/MOVIE/SQ
//!     拨轮: {"kind":"dial","dial":"front","step":1}   // dial: front|rear|rear_top, step: ±1
//!     模式: {"kind":"mode","value":"M"}               // M/S/A/P/AUTO/1/2/3
//!
//! 按键通道（已实测，run-yt1coo35）：经队列 0x5503e0 注入 32 字节 InfraInputEvent。
//! MENU=0x1ab 打开菜单（0x346 + 0x2c9），DOWN=0x30 移动选择，ENTER=0x1ac 进入子菜单（0x2ca）。
//! UP=0x3 / LEFT=0x15 / RIGHT=0x1af / DELETE=0x1f8 尚未实测，界面标空心点并且不下发。
//! 其余控件均未验证（空心灰点），原型阶段点击仅记录事件。
//!
//! LCD 画面：--frame 指定的 PNG（默认官方 run-00ukkyz7 的 NO CARD 拍摄界面），
//! 后续可替换为按帧轮询/流式刷新的真实 LCD 帧。

mod firmware_dev;
mod lcd_wakeup;

use std::time::{Instant, SystemTime, UNIX_EPOCH};

use eframe::egui::{self, Align2, Color32, FontFamily, FontId, Pos2, Rect, Sense, Stroke, Vec2};
use egui::epaint::{Mesh, Vertex, WHITE_UV};

/// 本帧各控件的屏幕矩形；`hit` 写入，`dump_controls` 换算成虚拟坐标导出。
static CONTROL_RECTS: std::sync::Mutex<Vec<(String, Rect)>> = std::sync::Mutex::new(Vec::new());
static LAYOUT_CHECKED: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
static MANAGER_CLOSE: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

/// 虚拟画布尺寸（对应参考图 native-controls.png 的 1060x830 去掉 GTK 标题栏）
const VW: f32 = 1060.0;
const VH: f32 = 800.0;

const MODES: [&str; 8] = ["M", "1", "2", "3", "AUTO", "P", "A", "S"]; // 顺时针，自正上方

fn reset_idle_reason(runtime: &std::path::Path) -> Option<String> {
    let analysis = runtime.join("analysis");
    let lock = analysis.join(".run.lock");
    if analysis.is_symlink() || lock.is_symlink() {
        return Some("重置路径包含符号链接，后端不会执行".into());
    }
    if !lock.symlink_metadata().map(|m| m.file_type().is_file()).unwrap_or(false) {
        return Some("缺少普通 runtime 锁文件，后端不会执行".into());
    }
    if analysis.join(".config-transaction.json").symlink_metadata().is_ok() {
        return Some("有未完成的配置事务，请先执行 config-state.py --recover".into());
    }
    match std::fs::File::open(lock).and_then(|file| {
        file.try_lock().map_err(std::io::Error::other)
    }) {
        Ok(()) => None,
        Err(error) => Some(format!("所属 runtime 正在运行/构建，或锁不可用：{error}")),
    }
}

fn reset_output_with_marker(output: std::io::Result<std::process::Output>, marker: &[u8]) -> String {
    match output {
        Ok(result) if result.status.success()
            && result.stdout.starts_with(marker) =>
                format!("reset 完成 · {}", String::from_utf8_lossy(&result.stdout).trim()),
        Ok(result) if result.status.success() => "reset 未确认：后端没有完成回执".into(),
        Ok(result) => {
            let error = String::from_utf8_lossy(&result.stderr);
            if error.contains("workspace configuration generation changed") {
                "配置代已变化；本次未重置，请重新预览后确认".into()
            } else if error.contains("durability unknown") {
                "重置提交状态不确定；请重新读取当前配置，不要直接重试".into()
            } else {
                format!("reset 失败 rc={:?} · {}", result.status.code(), error.lines().last().unwrap_or("无错误回执"))
            }
        }
        Err(error) => format!("无法执行 reset · {error}"),
    }
}

fn reset_output(output: std::io::Result<std::process::Output>) -> String {
    reset_output_with_marker(output, b"CONFIG_RESET_APPLIED ")
}

fn workspace_preview(output: std::io::Result<std::process::Output>) -> Result<String, String> {
    let output = output.map_err(|error| format!("无法读取配置：{error}"))?;
    if !output.status.success() {
        return Err(format!("配置预览失败：{}", String::from_utf8_lossy(&output.stderr).trim()));
    }
    let text = String::from_utf8(output.stdout).map_err(|_| "配置预览不是 UTF-8".to_string())?;
    if text.trim() == "WORKSPACE_CONFIG_EMPTY" {
        return Err("当前工作目录暂无已保存配置，无需重置".into());
    }
    let words: Vec<_> = text.split_whitespace().collect();
    if words.len() != 3 || words[0] != "WORKSPACE_CONFIG_PREVIEW"
        || !matches!(words[2], "backup" | "reset")
        || words[1].len() != 68 || !words[1].starts_with("gen-")
        || !words[1].as_bytes()[4..].iter().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(c)) {
        return Err("配置预览缺少有效的当前代回执".into());
    }
    Ok(words[1].to_string())
}

enum ResetReply {
    Preview(Result<String, String>),
    Applied(String),
}

fn layout_signature(controls: &[(String, Rect)]) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut hash = std::collections::hash_map::DefaultHasher::new();
    for (name, rect) in controls {
        name.hash(&mut hash);
        for value in [rect.min.x, rect.min.y, rect.max.x, rect.max.y] {
            value.to_bits().hash(&mut hash);
        }
    }
    hash.finish()
}

// ---------------------------------------------------------------- 事件

#[derive(Clone, Copy, Debug)]
enum Event {
    Key(&'static str),
    Dial { dial: &'static str, step: i32 },
    Mode(&'static str),
}

impl Event {
    fn json(&self) -> String {
        match *self {
            Event::Key(k) => format!("{{\"kind\":\"key\",\"key\":\"{k}\"}}"),
            Event::Dial { dial, step } => {
                format!("{{\"kind\":\"dial\",\"dial\":\"{dial}\",\"step\":{step}}}")
            }
            Event::Mode(v) => format!("{{\"kind\":\"mode\",\"value\":\"{v}\"}}"),
        }
    }
}

#[cfg(test)]
fn hex32(bytes: &[u8; 32]) -> String {
    let mut out = String::with_capacity(64);
    for byte in bytes {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

/// Key -> original raw code. Mapping evidence and functional acceptance are
/// separate: some entries have only static contracts so far.
fn key_code(label: &str) -> Option<u32> {
    Some(match label {
        "MENU" => 0x1ab,       // opens the menu        -> screens 0x346 + 0x2c9
        "UP" => 0x3,           // repaints the menu
        "DOWN" => 0x30,        // moves the selection
        "LEFT" => 0x15,        // -> screen 0x2c8
        "RIGHT" => 0x1af,      // -> back to 0x2c9
        "ENTER" => 0x1ac,      // enters a submenu      -> screen 0x2ca
        "PLAY" => 0x1f7,       // playback              -> screens 0x344 + 0x44d
        "C1" => 0x66,          // -> shooting + 0x341
        "REC" => 0x1f0,        // movie record          -> screen 0x33a
        "DELETE" => 0x1f8,
        "FN" => 0x7095,
        "AF_ON" => 0x0f000004,
        // Shutter and power are ordinary entries in the body's raw->UIBIZ key
        // table (appFw file offset 0x3704b98, 1120 x {u32 raw, u32 uibiz}):
        //   0x1f1 -> 0x1d UIBIZ_KEY_TACT_LOCK  (half press / AF-AE lock)
        //   0xa7  -> 0x0f UIBIZ_KEY_TACT_CAP   (full press; independently
        //                      corroborated by the live chain
        //                      0xa7 -> 0xf -> 0x2070000 EVENT_INPUT_TACT_CAP_ON)
        //   0x02  -> 0x01 UIBIZ_KEY_TACT_POWER (0x01 -> 0x00 SLIKEY_POWER is the
        //                      weaker alternative; only 0x01 has a real dispatch
        //                      branch at 0x17923f4)
        "SHUTTER_HALF" => 0x1f1,
        "SHUTTER" => 0xa7,
        "POWER" => 0x02,
        _ => return None,
    })
}

/// Dial -> (one raw code, signed-status quantum), from the original converter.
/// Negative rotation is a separate event, never a key release.
fn dial_codes(dial: &str) -> Option<(u32, i32)> {
    Some(match dial {
        "front" => (0x1000001c,22),
        "rear" => (0x10000016,30),
        "rear_top" => (0x10000013,1024),
        "dpad_ring" => (0x1000001d,24),
        _ => return None,
    })
}

#[cfg(test)]
fn input_record(code: u32, status: i32, previous: i32) -> [u8;32] {
    let mut record=[0u8;32];
    record[0..4].copy_from_slice(&code.to_le_bytes());
    record[8..12].copy_from_slice(&status.to_le_bytes());
    record[12..16].copy_from_slice(&previous.to_le_bytes());
    record[24..28].copy_from_slice(&1u32.to_le_bytes());
    record
}

fn input_command(code:u32,status:i32) -> String {
    format!("/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 {:#x} 0 1",status as u32)
}

fn input_delivery_confirmed(output: &str) -> bool {
    let uart_complete = output.lines().any(|line|
        line.starts_with("MENU_DIAG_COMMAND_DONE_") && line.trim_end().ends_with(":0"));
    let uart_sent = output.lines().any(|line|
        (line.starts_with("INJECT_KEY_SEND ") || line.starts_with("INJECT_EVENT_SEND "))
        && line.trim_end().ends_with("result=0"));
    (uart_complete && uart_sent) || output.lines().any(|line| {
        let fields: Vec<_> = line.split_whitespace().collect();
        fields.len() == 6 && fields[0] == "LOW_INPUT_DONE" && fields[1] == "profile=mailbox-v1"
            && fields[2].strip_prefix("seq=").and_then(|value| value.parse::<u64>().ok()).is_some_and(|n| n > 0)
            && fields[3] == "rc=0" && matches!(fields[4], "op=1" | "op=2" | "op=3" | "op=4" | "op=5")
            && fields[5] == "original_queue=0x807a0020"
    })
}

fn position_key(label:&str) -> Option<i32> {
    match label {"STILL"=>Some(1),"MOVIE"=>Some(2),"SQ"=>Some(3),_=>None}
}

fn mode_position(label:&str) -> Option<i32> {
    match label {"AUTO"=>Some(1),"P"=>Some(3),"A"=>Some(5),"S"=>Some(4),"M"=>Some(6),
        "1"=>Some(7),"2"=>Some(0x13),"3"=>Some(0x14),_=>None}
}

fn now_hms() -> String {
    let d = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    let s = d.as_secs();
    format!(
        "{:02}:{:02}:{:02}.{:03}",
        (s / 3600) % 24,
        (s / 60) % 60,
        s % 60,
        d.subsec_millis()
    )
}

// ---------------------------------------------------------------- 坐标变换

/// 虚拟坐标 → 屏幕坐标（等比缩放居中）
#[derive(Clone, Copy)]
struct X {
    o: Pos2,
    s: f32,
}

impl X {
    fn p(&self, x: f32, y: f32) -> Pos2 {
        Pos2::new(self.o.x + x * self.s, self.o.y + y * self.s)
    }
    fn r(&self, x: f32, y: f32, w: f32, h: f32) -> Rect {
        Rect::from_min_size(self.p(x, y), Vec2::new(w * self.s, h * self.s))
    }
    fn u(&self, v: f32) -> f32 {
        v * self.s
    }
}

// ---------------------------------------------------------------- 绘制工具

fn lerp(a: Color32, b: Color32, t: f32) -> Color32 {
    let f = |x: u8, y: u8| (x as f32 + (y as f32 - x as f32) * t) as u8;
    Color32::from_rgba_unmultiplied(f(a.r(), b.r()), f(a.g(), b.g()), f(a.b(), b.b()), f(a.a(), b.a()))
}

fn rgb(r: u8, g: u8, b: u8) -> Color32 {
    Color32::from_rgb(r, g, b)
}

/// 圆角矩形轮廓点（顺时针）
fn rounded_outline(r: Rect, rad: f32, seg: usize) -> Vec<Pos2> {
    let rad = rad.min(r.width() / 2.0).min(r.height() / 2.0).max(0.0);
    let corners = [
        (r.right() - rad, r.top() + rad, -90.0f32, 0.0),
        (r.right() - rad, r.bottom() - rad, 0.0, 90.0),
        (r.left() + rad, r.bottom() - rad, 90.0, 180.0),
        (r.left() + rad, r.top() + rad, 180.0, 270.0),
    ];
    let mut pts = Vec::with_capacity((seg + 1) * 4);
    for (cx, cy, a0, a1) in corners {
        for i in 0..=seg {
            let a = (a0 + (a1 - a0) * i as f32 / seg as f32).to_radians();
            pts.push(Pos2::new(cx + rad * a.cos(), cy + rad * a.sin()));
        }
    }
    pts
}

/// 三角扇 mesh（凸多边形填充，顶点可各自带色 → 渐变）
fn fan_mesh(center: Pos2, cc: Color32, ring: &[(Pos2, Color32)]) -> Mesh {
    let mut m = Mesh::default();
    m.vertices.push(Vertex { pos: center, uv: WHITE_UV, color: cc });
    for &(p, c) in ring {
        m.vertices.push(Vertex { pos: p, uv: WHITE_UV, color: c });
    }
    let n = ring.len() as u32;
    for i in 0..n {
        m.indices.extend_from_slice(&[0, 1 + i, 1 + (i + 1) % n]);
    }
    m
}

/// 竖向线性渐变圆角矩形
fn vgrad(p: &egui::Painter, r: Rect, rad: f32, top: Color32, bottom: Color32) {
    let pts = rounded_outline(r, rad, 8);
    let ring: Vec<(Pos2, Color32)> = pts
        .iter()
        .map(|q| (*q, lerp(top, bottom, ((q.y - r.top()) / r.height()).clamp(0.0, 1.0))))
        .collect();
    let cc = lerp(top, bottom, 0.5);
    p.add(egui::Shape::mesh(fan_mesh(r.center(), cc, &ring)));
}

/// 径向渐变圆（light_center → edge）
fn rgrad_circle(p: &egui::Painter, c: Pos2, r: f32, inner: Color32, outer: Color32, seg: usize) {
    let ring: Vec<(Pos2, Color32)> = (0..seg)
        .map(|i| {
            let a = i as f32 / seg as f32 * std::f32::consts::TAU;
            (Pos2::new(c.x + r * a.cos(), c.y + r * a.sin()), outer)
        })
        .collect();
    p.add(egui::Shape::mesh(fan_mesh(c, inner, &ring)));
}

fn stroke_outline(p: &egui::Painter, pts: &[Pos2], w: f32, color: Color32) {
    let mut v = pts.to_vec();
    if let Some(&first) = pts.first() {
        v.push(first);
    }
    p.add(egui::Shape::line(v, Stroke::new(w, color)));
}

/// 假投影：偏移半透明圆角矩形
fn shadow(p: &egui::Painter, r: Rect, rad: f32) {
    let r2 = r.translate(Vec2::new(0.0, 2.0));
    p.rect_filled(r2, rad, Color32::from_rgba_unmultiplied(0, 0, 0, 90));
}

fn text(
    p: &egui::Painter,
    x: X,
    vx: f32,
    vy: f32,
    size: f32,
    s: &str,
    color: Color32,
    align: Align2,
    bold: bool,
) {
    let fam = if bold {
        FontFamily::Name("cjk-bold".into())
    } else {
        FontFamily::Proportional
    };
    p.text(x.p(vx, vy), align, s, FontId::new(size * x.s, fam), color);
}

/// 就绪标记：实心绿点=已动态验证；空心灰点=未验证
fn ready_dot(p: &egui::Painter, c: Pos2, r: f32, verified: bool) {
    if verified {
        p.circle_filled(c, r, rgb(0x35, 0xd0, 0x6a));
        p.circle_stroke(c, r, Stroke::new(1.0, rgb(0x1a, 0x5a, 0x30)));
    } else {
        p.circle_stroke(c, r, Stroke::new(1.4, rgb(0x8b, 0x8d, 0x91)));
    }
}

// ---------------------------------------------------------------- App

struct App {
    log: Vec<String>,
    frame_tex: Option<egui::TextureHandle>,
    frame_size: Vec2,
    frame_missing: Option<String>,
    seg: usize,      // 0 照片 1 录像 2 S&Q
    mode_idx: usize, // 模式拨盘当前档
    /// When set, the LCD polls this file and re-uploads the texture on change.
    /// That file is written by the runner's QMP screendump; without it the LCD
    /// would be a still image, which is the one thing it must not pretend to be.
    live_path: Option<String>,
    lcd_wakeup: Option<lcd_wakeup::LcdWakeup>,
    live_seen: Option<std::time::SystemTime>,
    live_frames: u64,
    /// Last time a new frame actually arrived, so a frozen producer is visible
    /// instead of being mistaken for a quiet scene.
    live_last: Option<std::time::Instant>,
    live_content_last: Option<std::time::Instant>,
    /// Hash of the last frame *content*. The producer rewrites the file every tick
    /// even when nothing changed, so mtime alone would report motion that is not there.
    live_hash: u64,
    /// Directory the runner polls for `*.cmd`. Dropping a command file there is
    /// the only supported way to reach the guest: it goes through the runner's own
    /// serial channel, so nothing else touches QEMU.
    input_dir: Option<String>,
    next_request: u64,
    sent: u64,
    pending: Vec<(std::path::PathBuf, Instant)>,
    request_prefix: String,
    /// Outer ring: left and right clicks each produce one encoder step.
    ring_turns: i32,
    power_on: bool,
    /// Destructive actions are never one click: the scope has to be read first.
    reset_dialog: bool,
    reset_message: Option<String>,
    reset_job: Option<std::sync::mpsc::Receiver<ResetReply>>,
    usb_job: Option<std::sync::mpsc::Receiver<String>>,
    usb_message: Option<String>,
    firmware_panel: firmware_dev::FirmwareDevPanel,
    firmware_open: bool,
    reset_generation: Option<String>,
    close_after_reset: bool,
}

impl Drop for App {
    fn drop(&mut self) {
        drop(self.lcd_wakeup.take());
    }
}

impl App {
    fn new(
        cc: &eframe::CreationContext,
        frame_path: Option<String>,
        live_path: Option<String>,
        input_dir: Option<String>,
    ) -> Self {
        install_cjk_fonts(&cc.egui_ctx);

        let static_preview = frame_path.is_some() && live_path.is_none();
        let path = if live_path.is_some() { None } else { resolve_frame_path(frame_path) };
        let (frame_tex, frame_size, frame_missing) = match path.as_deref().map(load_png) {
            Some(Some(img)) => {
                let size = Vec2::new(img.width() as f32, img.height() as f32);
                let tex =
                    cc.egui_ctx
                        .load_texture("lcd-frame", img, egui::TextureOptions::LINEAR);
                (Some(tex), size, None)
            }
            _ => (
                None,
                Vec2::ZERO,
                Some(path.unwrap_or_else(|| if live_path.is_some() { "等待虚拟机的第一帧".into() }
                    else { "未连接画面：请通过启动器连接；静态预览须显式 --frame".into() })),
            ),
        };

        let mut app = Self {
            log: Vec::new(),
            frame_tex,
            frame_size,
            frame_missing,
            seg: 0,
            mode_idx: 0,
            live_path,
            lcd_wakeup: None,
            live_seen: None,
            live_frames: 0,
            live_last: None,
            live_content_last: None,
            live_hash: 0,
            input_dir,
            next_request: 0,
            sent: 0,
            pending: Vec::new(),
            request_prefix: format!("{}-{}", std::process::id(),
                SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_nanos()),
            ring_turns: 0,
            power_on: false,
            reset_dialog: false,
            reset_message: None,
            reset_job: None,
            usb_job: None,
            usb_message: None,
            firmware_panel: firmware_dev::FirmwareDevPanel::new(
                std::env::var("CAMUI_FIRMWARE_CONTEXT").unwrap_or_default(),
                std::env::var("CAMUI_FIRMWARE_PYTHON").unwrap_or_else(|_| "python3".into()),
                std::env::var("CAMUI_FIRMWARE_BACKEND").unwrap_or_else(|_| "firmware-development.py".into())),
            firmware_open: false,
            reset_generation: None,
            close_after_reset: false,
        };
        match app.live_path.as_deref() {
            Some(path) => app.log_line(&format!("画面来源：轮询 {path}")),
            None => app.log_line(if static_preview { "画面来源：静态预览（--frame）" } else { "画面通道未接：请通过 run-camera.py 启动" }),
        }
        if let Some(path) = app.live_path.as_deref() {
            match lcd_wakeup::LcdWakeup::new(std::path::Path::new(path), cc.egui_ctx.clone()) {
                Ok(worker) => app.lcd_wakeup = Some(worker),
                Err(error) => {
                    let message = format!("LCD 文件变化唤醒线程启动失败：{error}；继续使用 16ms 轮询");
                    eprintln!("{message}");
                    app.log_line(&message);
                }
            }
        }
        match app.input_dir.as_deref() {
            Some(dir) => app.log_line(&format!("按键通道：{dir}（经 runner 串口下发）")),
            None => app.log_line("按键通道：未接（未指定 --input-dir）"),
        }
        app
    }

    /// Re-upload the LCD texture when the live frame file changes.
    fn poll_live(&mut self, ctx: &egui::Context) {
        let Some(path) = self.live_path.clone() else {
            return;
        };
        // Ask for the next frame unconditionally. Requesting only on change deadlocks:
        // egui stops calling ui() while idle, so the change is never observed.
        ctx.request_repaint_after(std::time::Duration::from_millis(16));
        let Ok(meta) = std::fs::metadata(&path) else {
            return;
        };
        let Ok(modified) = meta.modified() else {
            return;
        };
        if self.live_seen == Some(modified) {
            return;
        }
        let Ok(bytes) = std::fs::read(&path) else {
            return;
        };
        // Cheap content hash: the producer rewrites identical bytes when the
        // emulated screen is idle, and counting those as frames would be a lie.
        let mut hash = 0xcbf29ce484222325u64;
        for byte in &bytes {
            hash = (hash ^ *byte as u64).wrapping_mul(0x100000001b3);
        }
        if hash == self.live_hash {
            self.live_seen = Some(modified);
            self.live_last = Some(Instant::now());
            return;
        }
        let Some(img) = image::load_from_memory(&bytes).ok().map(|i| i.to_rgba8()) else {
            return;
        };
        let img = egui::ColorImage::from_rgba_unmultiplied(
            [img.width() as usize, img.height() as usize],
            &img,
        );
        // Commit only a decoded frame. A partial file must be retried.
        self.live_seen = Some(modified);
        self.live_hash = hash;
        self.live_content_last = Some(Instant::now());
        self.frame_size = Vec2::new(img.width() as f32, img.height() as f32);
        match self.frame_tex.as_mut() {
            Some(tex) => tex.set(img, egui::TextureOptions::LINEAR),
            None => {
                self.frame_tex =
                    Some(ctx.load_texture("lcd-frame", img, egui::TextureOptions::LINEAR));
            }
        }
        self.frame_missing = None;
        self.live_frames += 1;
        self.live_last = Some(std::time::Instant::now());
    }

    /// 统一事件出口（原型：写日志面板 + stdout）
    fn emit(&mut self, ev: Event) {
        let line = format!("{}  {}", now_hms(), ev.json());
        println!("{line}");
        self.log.push(line);
        self.dispatch(&ev);
    }

    /// Turn a UI event into the 32-byte InfraInputEvent the firmware expects and
    /// hand it to the runner through the input queue directory.
    ///
    /// Known static mappings may be sent, but their firmware effect still needs
    /// acceptance. Unknown controls remain explicit errors rather than guesses.
    fn dispatch(&mut self, ev: &Event) {
        let Some(dir) = self.input_dir.clone() else {
            return;
        };
        match ev {
            Event::Key(k) => {
                if let Some(status)=position_key(k) {
                    self.send_one(&dir,0x71c9,status,0);
                    return;
                }
                if *k=="SHUTTER" {
                    self.send_shutter(&dir);
                    return;
                }
                let Some(code) = key_code(k) else {
                    self.log.push(format!("{}  {} 未验证，未下发", now_hms(), k));
                    return;
                };
                self.send_key(&dir, code);
            }
            Event::Dial { dial, step } => {
                let Some((code, quantum)) = dial_codes(dial) else {
                    self.log
                        .push(format!("{}  {} 未验证，未下发", now_hms(), dial));
                    return;
                };
                if *step!=0 {
                    self.send_one(&dir, code, quantum*step.signum(), 0);
                }
            }
            Event::Mode(v) => {
                if let Some(status)=mode_position(v) { self.send_one(&dir,0x7025,status,0); }
                else { self.log_line("未知模式档位，未下发"); }
            }
        }
    }

    /// 两段式快门：半按 → 全按 → 松全按 → 松半按。
    ///
    /// 真机上 AF/AE 锁在半按阶段完成、曝光在松全按时触发，所以只发一个 CAP 边沿
    /// 不是等价建模；这里按真实顺序走完四步（步间 50 ms）。
    fn send_shutter(&mut self, dir: &str) {
        let steps=[(0x1f1u32,1i32),(0xa7,1),(0xa7,0),(0x1f1,0)];
        let mut command=String::new();
        for (index,(code,status)) in steps.iter().enumerate() {
            command.push_str(&format!("{}; step{index}=$?; sleep 0.05; ",input_command(*code,*status)));
        }
        command.push_str("test \"$step0\" = 0 && test \"$step1\" = 0 && test \"$step2\" = 0 && test \"$step3\" = 0\n");
        if let Err(error) = self.queue_command(dir, &command) {
            self.log_line(&format!("快门未送出：{error}"));
        }
    }

    fn send_key(&mut self, dir: &str, code: u32) {
        let command = format!("{}; pressed=$?; sleep 0.05; {}; released=$?; test \"$pressed\" = 0 && test \"$released\" = 0\n",
            input_command(code,1), input_command(code,0));
        if let Err(error) = self.queue_command(dir, &command) {
            self.log_line(&format!("按键未送出：{error}"));
        }
    }

    fn send_one(&mut self, dir: &str, code: u32, status: i32, _prev: i32) {
        if let Err(error) = self.queue_command(dir,&(input_command(code,status)+"\n")) {
            self.log_line(&format!("按键未送出：{error}"));
        }
    }

    fn queue_command(&mut self, dir: &str, command: &str) -> std::io::Result<()> {
        self.next_request += 1;
        let name = format!("{}-{:06}.cmd", self.request_prefix, self.next_request);
        let path = std::path::Path::new(dir).join(name);
        let temporary = path.with_extension("tmp");
        std::fs::write(&temporary, command)?;
        std::fs::rename(temporary, &path)?;
        self.pending.push((path.with_extension("out"), Instant::now()));
        self.sent += 1;
        Ok(())
    }

    fn poll_replies(&mut self) {
        let mut messages = Vec::new();
        self.pending.retain(|(path, at)| {
            if let Ok(output) = std::fs::read_to_string(path) {
                messages.push(if input_delivery_confirmed(&output) {
                    "guest 已执行投递（固件响应另行核验）".to_string()
                } else { format!("按键失败：{}", output.chars().take(180).collect::<String>()) });
                return false;
            }
            if at.elapsed().as_secs() > 35 {
                messages.push("按键回执超时：后端未完成，请检查运行状态".to_string());
                return false;
            }
            true
        });
        for message in messages { self.log_line(&message); }
    }

    fn log_line(&mut self, msg: &str) {
        self.log.push(format!("{}  {}", now_hms(), msg));
    }

    fn handle_keys(&mut self, ctx: &egui::Context) {
        let mut evs: Vec<Event> = Vec::new();
        let mut clear = false;
        ctx.input(|i| {
            for (key, ev) in [
                (egui::Key::ArrowUp, Event::Key("UP")),
                (egui::Key::ArrowDown, Event::Key("DOWN")),
                (egui::Key::ArrowLeft, Event::Key("LEFT")),
                (egui::Key::ArrowRight, Event::Key("RIGHT")),
                (egui::Key::Enter, Event::Key("ENTER")),
                (egui::Key::M, Event::Key("MENU")),
                (egui::Key::Delete, Event::Key("DELETE")),
                (egui::Key::PageUp, Event::Dial { dial: "rear", step: 1 }),
                (egui::Key::PageDown, Event::Dial { dial: "rear", step: -1 }),
            ] {
                if i.key_pressed(key) {
                    evs.push(ev);
                }
            }
            if i.key_pressed(egui::Key::Escape) {
                clear = true;
            }
        });
        for ev in evs {
            self.emit(ev);
        }
        if clear {
            self.log.clear();
        }
    }

    /// Register a rect that came from a normal egui widget, so the acceptance
    /// script sees it next to the hand-drawn camera controls.
    fn record(id: &str, rect: Rect) {
        if let Ok(mut slot) = CONTROL_RECTS.lock() {
            slot.push((id.to_string(), rect));
        }
    }

    fn reset_unavailable(&self) -> Option<String> {
        if self.close_after_reset || MANAGER_CLOSE.load(std::sync::atomic::Ordering::Relaxed) {
            return Some("正在关闭配置管理窗口".into());
        }
        if self.reset_job.is_some() {
            return Some("正在重置；请等待完成".into());
        }
        let Ok(runtime) = std::env::var("CAMUI_RESET_RUNTIME") else {
            return Some("未配置重置后端或所属 runtime，未执行任何清除".into());
        };
        let workspace = std::env::var("CAMUI_CONFIG_WORKSPACE").ok();
        let script = std::env::var(if workspace.is_some() { "CAMUI_WORKSPACE_CONFIG_SCRIPT" } else { "CAMUI_RESET_SCRIPT" });
        let Ok(script) = script else { return Some("未配置重置后端".into()); };
        if !std::path::Path::new(&script).is_file() {
            return Some("重置后端不存在".into());
        }
        if let Some(reason) = reset_idle_reason(std::path::Path::new(&runtime)) {
            return Some(reason);
        }
        if let Some(workspace) = workspace {
            let state = std::path::Path::new(&workspace).join(".a7c2");
            let lock = state.join("config.lock");
            if state.is_symlink() || lock.is_symlink()
                || !lock.symlink_metadata().map(|m| m.file_type().is_file()).unwrap_or(false) {
                return Some("工作目录配置锁不可用".into());
            }
            if let Err(error) = std::fs::File::open(lock).and_then(|f| f.try_lock().map_err(std::io::Error::other)) {
                return Some(format!("工作目录正在运行或保存：{error}"));
            }
        }
        None
    }

    fn open_reset_dialog(&mut self) {
        if self.reset_dialog {
            return;
        }
        if let Some(reason) = self.reset_unavailable() {
            self.reset_message = Some(reason);
            return;
        }
        let Ok(workspace) = std::env::var("CAMUI_CONFIG_WORKSPACE") else {
            self.reset_dialog = true;
            return;
        };
        let (Ok(script), Ok(runtime)) = (std::env::var("CAMUI_WORKSPACE_CONFIG_SCRIPT"),
                                        std::env::var("CAMUI_RESET_RUNTIME")) else { return; };
        let (sender, receiver) = std::sync::mpsc::channel();
        self.reset_job = Some(receiver);
        self.reset_generation = None;
        self.reset_message = Some("正在核对当前工作目录配置…".into());
        std::thread::spawn(move || {
            let output = std::process::Command::new("python3")
                .env("PYTHON_COLORS", "0")
                .args(["-B", &script, "--workspace", &workspace, "--runtime", &runtime, "--preview"]).output();
            let _ = sender.send(ResetReply::Preview(workspace_preview(output)));
        });
    }

    /// The backend reacquires the same lock after this advisory UI check.
    fn perform_reset(&mut self) {
        if let Some(reason) = self.reset_unavailable() {
            self.reset_message = Some(reason);
            return;
        }
        let workspace = std::env::var("CAMUI_CONFIG_WORKSPACE").ok();
        let (Ok(script), Ok(runtime)) = (
            std::env::var(if workspace.is_some() { "CAMUI_WORKSPACE_CONFIG_SCRIPT" } else { "CAMUI_RESET_SCRIPT" }),
            std::env::var("CAMUI_RESET_RUNTIME"),
        ) else {
            self.reset_message =
                Some("未配置 CAMUI_RESET_SCRIPT / CAMUI_RESET_RUNTIME，未执行任何清除".into());
            return;
        };
        let (sender, receiver) = std::sync::mpsc::channel();
        let generation = self.reset_generation.take();
        if workspace.is_some() && generation.is_none() {
            self.reset_message = Some("当前配置尚未预览，未执行重置".into());
            return;
        }
        self.reset_job = Some(receiver);
        self.reset_message = Some("正在重置本机派生状态…".into());
        std::thread::spawn(move || {
            let message = if let Some(workspace) = workspace {
                let output = std::process::Command::new("python3")
                    .env("PYTHON_COLORS", "0")
                    .args(["-B", &script, "--workspace", &workspace, "--runtime", &runtime,
                           "--reset", "--expected-generation", generation.as_deref().unwrap(),
                           "--confirm", "reset"]).output();
                reset_output_with_marker(output, b"WORKSPACE_CONFIG_RESET ")
            } else {
                let output = std::process::Command::new("python3")
                    .env("PYTHON_COLORS", "0")
                    .args(["-B", &script, "--runtime", &runtime, "--apply", "--confirm", "reset"]).output();
                reset_output(output)
            };
            let _ = sender.send(ResetReply::Applied(message));
        });
    }

    fn computer_usb(&mut self, operation: &'static str) {
        if self.usb_job.is_some() { return; }
        let (Ok(tool), Ok(run)) = (std::env::var("CAMUI_USB_CONTROL"), std::env::var("CAMUI_USB_RUN")) else {
            self.usb_message = Some("本次运行未启用相机 USB 设备端，未连接本机电脑".into());
            return;
        };
        let (sender, receiver) = std::sync::mpsc::channel();
        self.usb_job = Some(receiver);
        self.usb_message = Some("正在处理 USB 连接…".into());
        std::thread::spawn(move || {
            let result = std::process::Command::new("python3")
                .args(["-B", &tool, "--run-dir", &run, operation, "--human"])
                .output();
            let message = match result {
                Ok(output) => {
                    let text = String::from_utf8_lossy(&output.stdout).trim().to_owned();
                    if text.is_empty() { format!("USB 操作未完成：{}", String::from_utf8_lossy(&output.stderr).trim()) }
                    else { text }
                }
                Err(error) => format!("USB 后端调用失败：{error}"),
            };
            let _ = sender.send(message);
        });
    }

    fn poll_usb(&mut self) {
        let message = match self.usb_job.as_ref().map(|job| job.try_recv()) {
            Some(Ok(message)) => Some(message),
            Some(Err(std::sync::mpsc::TryRecvError::Disconnected)) => Some("USB 后台通道已关闭，连接状态未确认".into()),
            _ => None,
        };
        if let Some(message) = message {
            self.usb_job = None;
            self.log_line(&message);
            self.usb_message = Some(message);
        }
    }

    fn poll_reset(&mut self) {
        let message = match self.reset_job.as_ref().map(|job| job.try_recv()) {
            Some(Ok(reply)) => Some(reply),
            Some(Err(std::sync::mpsc::TryRecvError::Disconnected)) =>
                Some(ResetReply::Applied("reset 状态未知：后台通道已关闭，请检查后端记录".into())),
            _ => None,
        };
        if let Some(reply) = message {
            self.reset_job = None;
            let message = match reply {
                ResetReply::Preview(Ok(generation)) => {
                    self.reset_generation = Some(generation);
                    self.reset_dialog = true;
                    self.reset_message = None;
                    return;
                }
                ResetReply::Preview(Err(error)) => error,
                ResetReply::Applied(message) => message,
            };
            self.log.push(message.clone());
            println!("CAMUI_RESET_RESULT {}", message.replace('\n', " "));
            self.reset_message = Some(message);
        }
    }

    /// Confirm dialog: the scope is spelled out, and the destructive button comes
    /// only after it.
    fn draw_reset_dialog(&mut self, ui: &mut egui::Ui) {
        egui::Frame::NONE
            .fill(rgb(0x2a, 0x22, 0x22))
            .inner_margin(egui::Margin::symmetric(8, 6))
            .show(ui, |ui| {
                ui.label(
                    egui::RichText::new("销毁并重新初始化（仅本机派生状态）")
                        .strong()
                        .size(12.0)
                        .color(rgb(0xe0, 0x5a, 0x4a)),
                );
                let workspace = std::env::var("CAMUI_CONFIG_WORKSPACE").ok();
                let scope = if let Some(workspace) = workspace {
                    format!("工作目录：{workspace}\n将当前配置选择重置为默认，下次启动重新初始化。\n保留：SD、bodydata、overwrite、历史配置代和运行记录。\n仅在相机停止后执行；配置代变化会拒绝操作。")
                } else {
                    "将清除：已发布配置代、/setting 上的 Backup 对、runs/*，并重打 initramfs。\n不会触碰：bodydata/、overwrite/、SD/ 与仓库外的官方资产。\n要求所属 VM 已停止；锁被活进程持有时后端会拒绝。".into()
                };
                ui.label(
                    egui::RichText::new(
                        scope,
                    )
                    .size(11.0),
                );
                ui.horizontal(|ui| {
                    let reason = self.reset_unavailable();
                    let confirm = ui.add_enabled(reason.is_none(), egui::Button::new("确认销毁"));
                    Self::record("reset_confirm", confirm.rect);
                    if confirm.clicked() {
                        self.reset_dialog = false;
                        self.perform_reset();
                    }
                    if let Some(reason) = reason {
                        confirm.on_disabled_hover_text(reason);
                    }
                    let cancel = ui.button("取消");
                    Self::record("reset_cancel", cancel.rect);
                    if cancel.clicked() {
                        self.reset_dialog = false;
                        self.reset_generation = None;
                    }
                });
            });
    }

    /// 命中测试 + 按下态
    fn hit(ui: &egui::Ui, id: &str, rect: Rect) -> egui::Response {
        // Recorded per frame so the acceptance script can click controls by name
        // instead of duplicating hand-copied layout coordinates.
        if let Ok(mut slot) = CONTROL_RECTS.lock() {
            slot.push((id.to_string(), rect));
        }
        ui.interact(rect, egui::Id::new(id), Sense::click())
    }

    /// 一次性的布局自检：两个导出交互矩形不允许互相覆盖。
    ///
    /// 覆盖会让 egui 把点击交给后注册（在上面）的控件。曾经的实测后果：模式盘
    /// 的 AUTO 档落在三段选择器上沿内，点 AUTO 注入的是 0x71c9/status=2（MOVIE），
    /// 于是 0x7025 永远收不到——表面像"AUTO 档固件没反应"，实际是布局重压。
    fn check_layout_once() {
        use std::sync::atomic::Ordering;
        let Ok(slot) = CONTROL_RECTS.lock() else {
            return;
        };
        if slot.len() < 19 {
            return;
        }
        let signature = layout_signature(&slot);
        if LAYOUT_CHECKED.swap(signature, Ordering::Relaxed) == signature {
            return;
        }
        for i in 0..slot.len() {
            for j in (i + 1)..slot.len() {
                let (a, b) = (slot[i].1, slot[j].1);
                let w = a.max.x.min(b.max.x) - a.min.x.max(b.min.x);
                let h = a.max.y.min(b.max.y) - a.min.y.max(b.min.y);
                if w > 0.5 && h > 0.5 {
                    println!(
                        "CAMUI_LAYOUT_OVERLAP {} {} area={:.0}",
                        slot[i].0,
                        slot[j].0,
                        w * h
                    );
                }
            }
        }
    }

    /// 导出本帧控件中心（虚拟坐标，与验收脚本的 ox/oy/scale 同一空间）
    fn dump_controls(o: Pos2, s: f32) {
        let Ok(path) = std::env::var("CAMUI_CONTROLS_PATH") else {
            return;
        };
        let Ok(slot) = CONTROL_RECTS.lock() else {
            return;
        };
        let mut out = String::from("{\n");
        for (index, (name, rect)) in slot.iter().enumerate() {
            if index > 0 {
                out.push_str(",\n");
            }
            let cx = (rect.center().x - o.x) / s;
            let cy = (rect.center().y - o.y) / s;
            out.push_str(&format!("  {name:?}: [{cx:.2}, {cy:.2}]"));
        }
        out.push_str("\n}\n");
        let _ = std::fs::write(&path, out);
    }
}

impl eframe::App for App {
    // eframe 0.37 hands us the root Ui directly (no Context-level panels).
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        self.poll_live(ui.ctx());
        self.poll_replies();
        self.poll_reset();
        self.poll_usb();
        self.firmware_panel.poll();
        ui.ctx().request_repaint_after(std::time::Duration::from_millis(16));
        if ui.ctx().input(|i| i.viewport().close_requested())
            || MANAGER_CLOSE.load(std::sync::atomic::Ordering::Relaxed) {
            self.close_after_reset = true;
        }
        if self.close_after_reset {
            ui.ctx().send_viewport_cmd(if self.reset_job.is_some() {
                egui::ViewportCommand::CancelClose
            } else { egui::ViewportCommand::Close });
        } else if self.reset_job.is_none() && !self.reset_dialog {
            self.handle_keys(ui.ctx());
        }

        let full = ui.available_rect_before_wrap();
        let painter = ui.painter_at(full);

        // Log strip on the right, camera filling the rest.
        const LOG_W: f32 = 330.0;
        let split = (full.right() - LOG_W).max(full.left() + 200.0);
        let cam_rect = Rect::from_min_max(full.min, Pos2::new(split, full.bottom()));
        let log_rect = Rect::from_min_max(Pos2::new(split, full.top()), full.max);

        painter.rect_filled(log_rect, 0.0, rgb(0x17, 0x18, 0x1a));
        painter.rect_filled(cam_rect, 0.0, rgb(0x24, 0x25, 0x28));

        let s = (cam_rect.width() / VW)
            .min(cam_rect.height() / VH)
            .max(0.05);
        let size = Vec2::new(VW * s, VH * s);
        let o = Pos2::new(
            cam_rect.center().x - size.x / 2.0,
            cam_rect.center().y - size.y / 2.0,
        );
        if let Ok(mut slot) = CONTROL_RECTS.lock() {
            slot.clear();
        }
        self.draw_camera(ui, &painter, X { o, s });

        // ---- log panel, drawn with the child ui so ScrollArea works ----
        let mut log_ui = ui.new_child(
            egui::UiBuilder::new()
                .max_rect(log_rect.shrink2(Vec2::new(10.0, 8.0)))
                .layout(egui::Layout::top_down(egui::Align::Min)),
        );
        let header = match (&self.live_path, self.live_last) {
            (Some(_), Some(at)) => {
                let age = at.elapsed().as_secs_f32();
                if age > 2.0 {
                    format!(
                        "画面通道停更 · {:.1}s 未收到文件更新", age
                    )
                } else {
                    format!(
                        "画面通道在线 · 更新龄 {:.1}s · 内容变化 {} 次 · 已投递 {} 条 · 待回执 {} 条",
                        age, self.live_frames, self.sent, self.pending.len()
                    )
                }
            }
            (Some(_), None) => "画面实时 · 等待第一帧…".to_string(),
            (None, _) => "画面未连接实时后端（--frame 仅用于静态预览）".to_string(),
        };
        let frozen = self
            .live_last
            .map(|at| at.elapsed().as_secs_f32() > 2.0)
            .unwrap_or(false);
        log_ui.label(
            egui::RichText::new(header)
                .color(if frozen { rgb(0xe0, 0x5a, 0x4a) } else { rgb(0xe6, 0xc1, 0x5a) })
                .strong()
                .size(13.0),
        );
        log_ui.separator();
        log_ui.horizontal_wrapped(|ui| {
            // The Wi-Fi backend is not ready: the address and its accessors are
            // verified but the name binding, the initialisation and the RF control
            // path are not, so this stays disabled instead of showing a fake state.
            let wifi = ui.add_enabled(false, egui::Button::new("Wi-Fi 开关"));
            Self::record("wifi_toggle", wifi.rect);
            wifi.on_disabled_hover_text(
                "后端未就绪：RW 0x7ea8af8 的 getter/setter 已核，但名称绑定、初始化与射频控制链未闭合",
            );
            let development = ui.button("固件开发…");
            Self::record("firmware_development", development.rect);
            if development.clicked() { self.firmware_open = true; }
            let computer = ui.add_enabled(self.usb_job.is_none() && self.input_dir.is_some(), egui::Button::new("连接电脑"));
            Self::record("usb_connect", computer.rect);
            if computer.clicked() { self.computer_usb("connect"); }
            let disconnect = ui.add_enabled(self.usb_job.is_none() && self.input_dir.is_some(), egui::Button::new("断开电脑"));
            Self::record("usb_disconnect", disconnect.rect);
            if disconnect.clicked() { self.computer_usb("disconnect"); }
            let reason = self.reset_unavailable();
            let reset = ui.add_enabled(reason.is_none(), egui::Button::new("销毁并重新初始化…"));
            Self::record("reset_open", reset.rect);
            if reset.clicked() {
                self.open_reset_dialog();
            }
            if let Some(reason) = reason {
                reset.on_disabled_hover_text(reason);
            }
        });
        if let Some(message) = self.usb_message.clone() {
            log_ui.label(egui::RichText::new(message).size(11.0).color(rgb(0xe0, 0x9a, 0x4a)));
        }
        if let Some(message) = self.reset_message.clone() {
            log_ui.label(
                egui::RichText::new(message)
                    .size(11.0)
                    .color(rgb(0xe0, 0x9a, 0x4a)),
            );
        }
        if self.reset_dialog {
            self.draw_reset_dialog(&mut log_ui);
        }
        let mut area = log_ui;
        egui::ScrollArea::vertical()
            .stick_to_bottom(true)
            .auto_shrink([false, false])
            .show(&mut area, |ui| {
                let n = self.log.len();
                for (i, line) in self.log.iter().enumerate() {
                    let latest = i + 1 == n;
                    let body = egui::RichText::new(line)
                        .monospace()
                        .size(11.0)
                        .color(if latest { rgb(0xd8, 0xf0, 0xc0) } else { rgb(0xcf, 0xd1, 0xd4) });
                    if latest {
                        egui::Frame::NONE
                            .fill(rgb(0x3a, 0x4a, 0x2a))
                            .inner_margin(egui::Margin::symmetric(4, 2))
                            .show(ui, |ui| {
                                ui.label(body);
                            });
                    } else {
                        ui.label(body);
                    }
                }
            });
        // Dumped after the panel so the log-panel controls (reset, Wi-Fi) are in the
        // same map the acceptance script clicks by name.
        Self::check_layout_once();
        Self::dump_controls(o, s);
        if self.firmware_open {
            let context = ui.ctx().clone();
            egui::Window::new("固件开发")
                .open(&mut self.firmware_open)
                .default_width(680.0).default_height(540.0)
                .show(&context, |ui| self.firmware_panel.show(&context, ui));
        }
    }
}

// ---------------------------------------------------------------- 相机绘制

impl App {
    fn draw_camera(&mut self, ui: &egui::Ui, p: &egui::Painter, x: X) {
        let mut pending: Vec<Event> = Vec::new();

        // ============ 顶盖（浅银渐变） ============
        let deck = x.r(8.0, 6.0, 1044.0, 190.0);
        vgrad(p, deck, x.u(22.0), rgb(0xef, 0xef, 0xef), rgb(0xcf, 0xcf, 0xcf));
        stroke_outline(p, &rounded_outline(deck, x.u(22.0), 8), 1.0, rgb(0xb5, 0xb5, 0xb5));
        // 顶部高光细线
        p.line_segment(
            [x.p(30.0, 8.0), x.p(1030.0, 8.0)],
            Stroke::new(1.0, Color32::from_rgba_unmultiplied(255, 255, 255, 200)),
        );

        // SONY / α7C II
        text(p, x, 64.0, 62.0, 30.0, "SONY", rgb(0x3c, 0x40, 0x43), Align2::LEFT_CENTER, true);
        text(p, x, 64.0, 118.0, 24.0, "α7C II", rgb(0x4a, 0x4e, 0x52), Align2::LEFT_CENTER, false);

        // EVF 取景器凸起
        let evf = x.r(440.0, 52.0, 122.0, 108.0);
        shadow(p, evf, x.u(10.0));
        vgrad(p, evf, x.u(10.0), rgb(0x4a, 0x4d, 0x52), rgb(0x2c, 0x2e, 0x33));
        stroke_outline(p, &rounded_outline(evf, x.u(10.0), 6), 1.0, rgb(0x1c, 0x1d, 0x20));
        let lens = x.r(466.0, 78.0, 70.0, 56.0);
        vgrad(p, lens, x.u(6.0), rgb(0x6b, 0x70, 0x76), rgb(0x23, 0x25, 0x29));
        stroke_outline(p, &rounded_outline(lens, x.u(6.0), 6), 1.0, rgb(0x14, 0x15, 0x18));
        // 镜片高光
        p.circle_filled(x.p(484.0, 92.0), x.u(5.0), Color32::from_rgba_unmultiplied(200, 220, 235, 70));

        // ---- 前拨轮 < > ----
        text(p, x, 872.0, 26.0, 13.0, "前拨轮", rgb(0x4a, 0x4d, 0x52), Align2::LEFT_CENTER, true);
        for (i, (sym, step)) in [("<", -1), (">", 1)].into_iter().enumerate() {
            let r = x.r(906.0 + i as f32 * 52.0, 34.0, 44.0, 30.0);
            let resp = Self::hit(ui, &format!("front_dial_{i}"), r);
            let down = resp.is_pointer_button_down_on();
            draw_dark_key(p, x, r, sym, down);
            ready_dot(p, r.right_bottom() + Vec2::new(-x.u(6.0), -x.u(5.0)), x.u(3.5), false);
            if resp.clicked() {
                pending.push(Event::Dial { dial: "front", step });
            }
        }

        // ---- 模式拨盘 ----
        self.draw_mode_dial(ui, p, x, &mut pending);

        // ---- REC 红色圆环 ----
        let rec_c = x.p(878.0, 96.0);
        let rec_r = x.u(24.0);
        let rec_rect = Rect::from_center_size(rec_c, Vec2::splat(rec_r * 2.0));
        let resp = Self::hit(ui, "rec", rec_rect);
        let down = resp.is_pointer_button_down_on();
        let (outer, inner) = if down {
            (rgb(0x8e, 0x14, 0x14), rgb(0x7a, 0x10, 0x10))
        } else {
            (rgb(0x8e, 0x14, 0x14), rgb(0xc0, 0x39, 0x2b))
        };
        rgrad_circle(p, rec_c, rec_r, rgb(0xd9, 0x5a, 0x4a), outer, 32);
        rgrad_circle(p, rec_c, rec_r * 0.68, if down { rgb(0x6a, 0x12, 0x12) } else { rgb(0xa8, 0x28, 0x20) }, inner, 32);
        if !down {
            p.circle_filled(rec_c + Vec2::new(-x.u(6.0), -x.u(8.0)), x.u(4.0), Color32::from_rgba_unmultiplied(255, 255, 255, 90));
        }
        ready_dot(p, rec_c + Vec2::new(rec_r * 0.55, rec_r * 0.75), x.u(3.5), false);
        text(p, x, 878.0, 138.0, 11.0, "REC", rgb(0x4a, 0x4d, 0x52), Align2::CENTER_CENTER, true);
        if resp.clicked() {
            pending.push(Event::Key("REC"));
        }

        // ---- 银色快门 ----
        let sh_c = x.p(958.0, 96.0);
        let sh_r = x.u(30.0);
        let resp = Self::hit(ui, "shutter", Rect::from_center_size(sh_c, Vec2::splat(sh_r * 2.0)));
        let down = resp.is_pointer_button_down_on();
        rgrad_circle(
            p,
            sh_c + if down { Vec2::new(0.0, x.u(1.5)) } else { Vec2::ZERO },
            sh_r,
            if down { rgb(0xc8, 0xc8, 0xc8) } else { rgb(0xf4, 0xf4, 0xf4) },
            if down { rgb(0x8a, 0x8a, 0x8a) } else { rgb(0xa9, 0xa9, 0xa9) },
            36,
        );
        p.circle_stroke(sh_c, sh_r, Stroke::new(1.2, rgb(0x7a, 0x7a, 0x7a)));
        if !down {
            p.circle_filled(sh_c + Vec2::new(-x.u(8.0), -x.u(10.0)), x.u(5.0), Color32::from_rgba_unmultiplied(255, 255, 255, 120));
        }
        ready_dot(p, sh_c + Vec2::new(sh_r * 0.6, sh_r * 0.72), x.u(3.5), false);
        if resp.clicked() {
            pending.push(Event::Key("SHUTTER"));
        }

        // ---- 电源开关：OFF / ON 竖排，可点击 ----
        let pw = x.r(1008.0, 46.0, 22.0, 80.0);
        let pw_resp = Self::hit(ui, "power", pw);
        // 滑轨
        vgrad(p, pw, x.u(9.0), rgb(0xcf, 0xcf, 0xce), rgb(0xa8, 0xa8, 0xa7));
        stroke_outline(p, &rounded_outline(pw, x.u(9.0), 6), 1.0, rgb(0x8a, 0x8a, 0x89));
        // 滑块
        let knob_y = if self.power_on { pw.top() + x.u(9.0) } else { pw.bottom() - x.u(9.0) };
        let knob = Rect::from_center_size(
            Pos2::new(pw.center().x, knob_y),
            Vec2::new(pw.width() - x.u(4.0), x.u(34.0)),
        );
        vgrad(
            p,
            knob,
            x.u(6.0),
            if self.power_on { rgb(0x6c, 0x8f, 0x6a) } else { rgb(0x46, 0x47, 0x4a) },
            if self.power_on { rgb(0x46, 0x66, 0x46) } else { rgb(0x2c, 0x2d, 0x30) },
        );
        stroke_outline(p, &rounded_outline(knob, x.u(6.0), 6), 1.0, rgb(0x28, 0x2a, 0x28));
        let (off_c, on_c) = if self.power_on {
            (rgb(0x5c, 0x60, 0x63), rgb(0xf0, 0xf6, 0xee))
        } else {
            (rgb(0xf0, 0xf0, 0xf0), rgb(0x5c, 0x60, 0x63))
        };
        text(p, x, 992.0, 62.0, 11.0, "OFF", off_c, Align2::RIGHT_CENTER, true);
        text(p, x, 992.0, 112.0, 11.0, "ON", on_c, Align2::RIGHT_CENTER, true);
        ready_dot(p, pw.right_top() + Vec2::new(-x.u(4.0), x.u(4.0)), x.u(3.0), false);
        if pw_resp.clicked() {
            pending.push(Event::Key("POWER"));
        }

        // ---- REC/快门下方 < > ----
        for (i, (sym, step)) in [("<", -1), (">", 1)].into_iter().enumerate() {
            let r = x.r(866.0 + i as f32 * 56.0, 142.0, 46.0, 30.0);
            let resp = Self::hit(ui, &format!("reartop_dial_{i}"), r);
            let down = resp.is_pointer_button_down_on();
            draw_dark_key(p, x, r, sym, down);
            ready_dot(p, r.right_bottom() + Vec2::new(-x.u(6.0), -x.u(5.0)), x.u(3.5), false);
            if resp.clicked() {
                pending.push(Event::Dial { dial: "rear_top", step });
            }
        }

        // ---- 照片 录像 S&Q 三段选择器 ----
        let seg_r = x.r(630.0, 150.0, 216.0, 36.0);
        let resp_all = [
            ("seg_still", "照片", "STILL"),
            ("seg_movie", "录像", "MOVIE"),
            ("seg_sq", "S&Q", "SQ"),
        ];
        vgrad(p, seg_r, x.u(18.0), rgb(0xe6, 0xe6, 0xe6), rgb(0xd0, 0xd0, 0xd0));
        stroke_outline(p, &rounded_outline(seg_r, x.u(18.0), 8), 1.0, rgb(0x9a, 0x9a, 0x9a));
        let sw = seg_r.width() / 3.0;
        for (i, (id, label, key)) in resp_all.into_iter().enumerate() {
            let r = Rect::from_min_size(
                Pos2::new(seg_r.left() + sw * i as f32, seg_r.top()),
                Vec2::new(sw, seg_r.height()),
            );
            let resp = Self::hit(ui, id, r);
            let active = i == self.seg;
            if active || resp.is_pointer_button_down_on() {
                let rr = r.shrink(x.u(3.0));
                vgrad(p, rr, x.u(14.0), rgb(0xfd, 0xfd, 0xfd), rgb(0xc6, 0xc6, 0xc6));
                stroke_outline(p, &rounded_outline(rr, x.u(14.0), 6), 1.0, rgb(0x8a, 0x8a, 0x8a));
            }
            text(p, x, 630.0 + 36.0 + i as f32 * 72.0, 168.0, 13.0, label, rgb(0x3f, 0x41, 0x45), Align2::CENTER_CENTER, true);
            if resp.clicked() {
                self.seg = i;
                pending.push(Event::Key(key));
            }
        }
        ready_dot(p, x.p(852.0, 182.0), x.u(3.5), false);

        // ============ 机身中部深色横条 ============
        let strip = x.r(8.0, 202.0, 1044.0, 60.0);
        vgrad(p, strip, x.u(4.0), rgb(0x46, 0x47, 0x4b), rgb(0x2f, 0x2f, 0x2f));
        stroke_outline(p, &rounded_outline(strip, x.u(4.0), 2), 1.0, rgb(0x22, 0x23, 0x26));
        p.line_segment(
            [x.p(12.0, 203.5), x.p(1048.0, 203.5)],
            Stroke::new(1.0, Color32::from_rgba_unmultiplied(255, 255, 255, 18)),
        );

        // 握把/前部凸起
        let grip = x.r(14.0, 206.0, 226.0, 52.0);
        vgrad(p, grip, x.u(20.0), rgb(0x3d, 0x3e, 0x42), rgb(0x2a, 0x2b, 0x2e));
        stroke_outline(p, &rounded_outline(grip, x.u(20.0), 8), 1.0, rgb(0x1d, 0x1e, 0x21));

        // 卡口小圆点
        p.circle_filled(x.p(298.0, 232.0), x.u(11.0), rgb(0x16, 0x16, 0x18));
        p.circle_stroke(x.p(298.0, 232.0), x.u(11.0), Stroke::new(1.5, rgb(0x50, 0x50, 0x53)));

        // MENU 胶囊键（已验证）
        let menu_r = x.r(576.0, 212.0, 94.0, 40.0);
        let resp = Self::hit(ui, "menu", menu_r);
        let down = resp.is_pointer_button_down_on();
        draw_round_key(p, x, menu_r, x.u(20.0), "MENU", 15.0, down);
        ready_dot(p, menu_r.right_bottom() + Vec2::new(-x.u(9.0), -x.u(6.0)), x.u(3.5), true);
        if resp.clicked() {
            pending.push(Event::Key("MENU"));
        }

        // C1 圆键
        let c1_c = x.p(726.0, 232.0);
        let c1_r = x.u(20.0);
        let resp = Self::hit(ui, "c1", Rect::from_center_size(c1_c, Vec2::splat(c1_r * 2.0)));
        let down = resp.is_pointer_button_down_on();
        draw_circle_key(p, x, c1_c, c1_r, "C1", 14.0, down);
        ready_dot(p, c1_c + Vec2::new(c1_r * 0.62, c1_r * 0.72), x.u(3.5), false);
        if resp.clicked() {
            pending.push(Event::Key("C1"));
        }

        // 后拨轮 < >
        for (i, (sym, step)) in [("<", -1), (">", 1)].into_iter().enumerate() {
            let r = x.r(766.0 + i as f32 * 56.0, 214.0, 46.0, 36.0);
            let resp = Self::hit(ui, &format!("rear_dial_{i}"), r);
            let down = resp.is_pointer_button_down_on();
            draw_dark_key(p, x, r, sym, down);
            ready_dot(p, r.right_bottom() + Vec2::new(-x.u(6.0), -x.u(5.0)), x.u(3.5), false);
            if resp.clicked() {
                pending.push(Event::Dial { dial: "rear", step });
            }
        }
        text(p, x, 815.0, 258.0, 10.0, "后拨轮", rgb(0x9a, 0x9b, 0x9e), Align2::CENTER_CENTER, false);

        // ============ 机身主体 ============
        let body = x.r(8.0, 268.0, 1044.0, 474.0);
        vgrad(p, body, x.u(16.0), rgb(0x3e, 0x3f, 0x43), rgb(0x33, 0x33, 0x36));
        stroke_outline(p, &rounded_outline(body, x.u(16.0), 8), 1.0, rgb(0x24, 0x25, 0x27));

        // ---- LCD 内凹 ----
        let bezel = x.r(36.0, 286.0, 676.0, 438.0);
        shadow(p, bezel, x.u(12.0));
        vgrad(p, bezel, x.u(12.0), rgb(0x19, 0x1a, 0x1c), rgb(0x26, 0x27, 0x2a));
        stroke_outline(p, &rounded_outline(bezel, x.u(12.0), 8), 1.2, rgb(0x0e, 0x0f, 0x11));
        // 内阴影（内圈深色描边叠加）
        let inner_edge = bezel.shrink(x.u(3.0));
        stroke_outline(p, &rounded_outline(inner_edge, x.u(10.0), 8), x.u(3.0), Color32::from_rgba_unmultiplied(0, 0, 0, 130));
        let lcd = bezel.shrink(x.u(16.0));
        p.rect_filled(lcd, x.u(4.0), Color32::BLACK);
        if let Some(tex) = &self.frame_tex {
            // 按比例 contain 居中
            let scale = (lcd.width() / self.frame_size.x).min(lcd.height() / self.frame_size.y);
            let sz = self.frame_size * scale;
            let img_r = Rect::from_center_size(lcd.center(), sz);
            p.image(
                tex.id(),
                img_r,
                Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0)),
                Color32::WHITE,
            );
            // 轻微内发光
            stroke_outline(p, &rounded_outline(img_r, x.u(2.0), 4), x.u(1.5), Color32::from_rgba_unmultiplied(120, 180, 140, 36));
            // 角标 F · run-00ukkyz7
            let badge_text = if self.live_path.is_some() { "F · QEMU" } else { "静态预览" };
            let badge_w = x.u(118.0);
            let badge_r = Rect::from_min_size(
                Pos2::new(img_r.right() - badge_w - x.u(8.0), img_r.bottom() - x.u(24.0)),
                Vec2::new(badge_w, x.u(18.0)),
            );
            p.rect_filled(badge_r, x.u(5.0), Color32::from_rgba_unmultiplied(10, 10, 12, 150));
            p.text(
                badge_r.center(),
                Align2::CENTER_CENTER,
                badge_text,
                FontId::monospace(x.u(11.0)),
                Color32::from_rgba_unmultiplied(235, 235, 235, 230),
            );
        } else {
            let msg = format!(
                "帧文件缺失\n{}",
                self.frame_missing.as_deref().unwrap_or("unknown")
            );
            p.text(
                lcd.center(),
                Align2::CENTER_CENTER,
                msg,
                FontId::proportional(x.u(14.0)),
                rgb(0x9a, 0x9a, 0x9a),
            );
        }

        // ---- 右侧操作区 ----
        // AF-ON
        let af_c = x.p(838.0, 336.0);
        let af_r = x.u(33.0);
        let resp = Self::hit(ui, "af_on", Rect::from_center_size(af_c, Vec2::splat(af_r * 2.0)));
        draw_circle_key(p, x, af_c, af_r, "AF-ON", 13.0, resp.is_pointer_button_down_on());
        ready_dot(p, af_c + Vec2::new(af_r * 0.66, af_r * 0.7), x.u(3.5), false);
        if resp.clicked() {
            pending.push(Event::Key("AF_ON"));
        }

        // Fn
        let fn_c = x.p(838.0, 412.0);
        let resp = Self::hit(ui, "fn", Rect::from_center_size(fn_c, Vec2::splat(af_r * 2.0)));
        draw_circle_key(p, x, fn_c, af_r, "Fn", 14.0, resp.is_pointer_button_down_on());
        ready_dot(p, fn_c + Vec2::new(af_r * 0.66, af_r * 0.7), x.u(3.5), false);
        if resp.clicked() {
            pending.push(Event::Key("FN"));
        }

        text(p, x, 838.0, 456.0, 11.0, "DISP", rgb(0xc9, 0xc9, 0xcb), Align2::CENTER_CENTER, true);

        // ---- 大方向盘 ----
        self.draw_wheel(ui, p, x, &mut pending);
        text(p, x, 1008.0, 586.0, 12.0, "ISO", rgb(0xc9, 0xc9, 0xcb), Align2::LEFT_CENTER, true);

        // ---- C2 / 播放 ----
        // y=724：方向盘交互方框下沿到 700（圆心 586 + 2.15r），播放/删除键上沿必须在其下，
        // 否则两个导出的交互矩形会重叠（实测 wheel↔play / wheel↔delete 各 131 平方像素）。
        text(p, x, 838.0, 690.0, 12.0, "C2", rgb(0xc9, 0xc9, 0xcb), Align2::CENTER_CENTER, true);
        let play_c = x.p(838.0, 724.0);
        let play_r = x.u(21.0);
        let resp = Self::hit(ui, "play", Rect::from_center_size(play_c, Vec2::splat(play_r * 2.0)));
        draw_circle_key(p, x, play_c, play_r, "", 12.0, resp.is_pointer_button_down_on());
        // 播放三角（矢量）
        let t = x.u(7.0);
        p.add(egui::Shape::convex_polygon(
            vec![
                play_c + Vec2::new(-t * 0.6, -t),
                play_c + Vec2::new(-t * 0.6, t),
                play_c + Vec2::new(t, 0.0),
            ],
            rgb(0xe0, 0xe0, 0xe2),
            Stroke::NONE,
        ));
        ready_dot(p, play_c + Vec2::new(play_r * 0.66, play_r * 0.72), x.u(3.5), false);
        if resp.clicked() {
            pending.push(Event::Key("PLAY"));
        }

        // ---- 删除（垃圾桶矢量图标） ----
        let del_c = x.p(950.0, 724.0);
        let resp = Self::hit(ui, "delete", Rect::from_center_size(del_c, Vec2::splat(play_r * 2.0)));
        draw_circle_key(p, x, del_c, play_r, "", 12.0, resp.is_pointer_button_down_on());
        let ic = rgb(0xe0, 0xe0, 0xe2);
        let (iw, ih) = (x.u(11.0), x.u(12.0));
        let can = Rect::from_center_size(del_c + Vec2::new(0.0, x.u(1.5)), Vec2::new(iw, ih));
        p.rect_stroke(can, x.u(1.5), Stroke::new(x.u(1.4), ic), egui::StrokeKind::Inside);
        p.line_segment(
            [del_c + Vec2::new(-iw * 0.75, -ih * 0.62), del_c + Vec2::new(iw * 0.75, -ih * 0.62)],
            Stroke::new(x.u(1.6), ic),
        );
        p.line_segment(
            [del_c + Vec2::new(-iw * 0.25, -ih * 0.85), del_c + Vec2::new(iw * 0.25, -ih * 0.85)],
            Stroke::new(x.u(1.6), ic),
        );
        ready_dot(p, del_c + Vec2::new(play_r * 0.66, play_r * 0.72), x.u(3.5), false);
        if resp.clicked() {
            pending.push(Event::Key("DELETE"));
        }

        // ============ 底部状态条（浅色） ============
        let bar = x.r(0.0, 748.0, 1060.0, 52.0);
        p.rect_filled(bar, 0.0, rgb(0xd8, 0xd8, 0xd8));
        p.line_segment([x.p(0.0, 749.0), x.p(1060.0, 749.0)], Stroke::new(1.0, rgb(0xa8, 0xa8, 0xa8)));
        text(
            p, x, 20.0, 766.0, 12.0,
            "菜单实验：方向 / Enter / M / Delete · 拨盘 PageUp/PageDown · Esc 清空日志",
            rgb(0x3a, 0x3b, 0x3e), Align2::LEFT_CENTER, false,
        );
        text(
            p, x, 20.0, 786.0, 11.0,
            "实心点=已有响应样本；空心点=功能待验。已知映射会投递；未实现项会明确提示。",
            rgb(0x5f, 0x60, 0x63), Align2::LEFT_CENTER, false,
        );

        for ev in pending {
            self.emit(ev);
        }
    }

    /// 圆形模式拨盘：刻度 + 盘面 + 点击选档
    fn draw_mode_dial(&mut self, ui: &egui::Ui, p: &egui::Painter, x: X, pending: &mut Vec<Event>) {
        // 圆心/半径受下方三段选择器（y≥150）约束：交互矩形必须止于 150 之上，
        // 否则 AUTO 档（正下方）的点击会被选择器抢走。r*2.0 恰好是圆的外接方框。
        let c = x.p(742.0, 86.0);
        let r = x.u(62.0);
        let resp = Self::hit(ui, "mode_dial", Rect::from_center_size(c, Vec2::splat(r * 2.0)));
        let down = resp.is_pointer_button_down_on();

        shadow(p, Rect::from_center_size(c, Vec2::splat(r * 2.0)), r);
        rgrad_circle(p, c, r, rgb(0xf5, 0xf5, 0xf5), rgb(0xa8, 0xa8, 0xa8), 48);
        p.circle_stroke(c, r, Stroke::new(1.2, rgb(0x73, 0x73, 0x73)));
        if down {
            p.circle_filled(c, r, Color32::from_rgba_unmultiplied(0, 0, 0, 18));
        }

        // 外圈刻度线
        for i in 0..72 {
            let a = i as f32 * 5.0_f32;
            let ar = a.to_radians();
            let long = i % 9 == 0;
            let r1 = r - x.u(if long { 8.0 } else { 4.5 });
            let q1 = c + Vec2::new(r1 * ar.sin(), -r1 * ar.cos());
            let q2 = c + Vec2::new((r - x.u(1.5)) * ar.sin(), -(r - x.u(1.5)) * ar.cos());
            p.line_segment([q1, q2], Stroke::new(x.u(if long { 1.2 } else { 0.7 }), rgb(0x6b, 0x6b, 0x6b)));
        }

        // 8 档刻度字
        for (i, m) in MODES.iter().enumerate() {
            let ar = (i as f32 * 45.0).to_radians();
            let rr = r * 0.72;
            let q = c + Vec2::new(rr * ar.sin(), -rr * ar.cos());
            let color = if i == self.mode_idx { rgb(0xc0, 0x39, 0x2b) } else { rgb(0x40, 0x42, 0x45) };
            p.text(
                q,
                Align2::CENTER_CENTER,
                *m,
                FontId::new(x.u(if m.len() > 1 { 11.0 } else { 14.0 }), FontFamily::Name("cjk-bold".into())),
                color,
            );
        }
        // 中央小圆 + 未就绪
        rgrad_circle(p, c, r * 0.30, rgb(0xe8, 0xe8, 0xe8), rgb(0xbc, 0xbc, 0xbc), 24);
        p.circle_stroke(c, r * 0.30, Stroke::new(1.0, rgb(0x8f, 0x8f, 0x8f)));
        p.text(
            c,
            Align2::CENTER_CENTER,
            "未就绪",
            FontId::proportional(x.u(10.0)),
            rgb(0x73, 0x74, 0x76),
        );
        ready_dot(p, c + Vec2::new(r * 0.5, r * 0.62), x.u(3.5), false);

        if resp.clicked() {
            if let Some(pos) = resp.interact_pointer_pos() {
                let d = pos - c;
                if d.length() > x.u(12.0) {
                    let ang = d.x.atan2(-d.y).to_degrees().rem_euclid(360.0);
                    let idx = ((ang + 22.5) / 45.0) as usize % 8;
                    self.mode_idx = idx;
                    pending.push(Event::Mode(MODES[idx]));
                }
            }
        }
    }

    /// 大方向盘：四向 + 中央 ENTER + 外圈虚线刻度（已验证键组）
    fn draw_wheel(&mut self, ui: &egui::Ui, p: &egui::Painter, x: X, pending: &mut Vec<Event>) {
        let c = x.p(880.0, 586.0);
        let r = x.u(106.0);
        let resp = Self::hit(ui, "wheel", Rect::from_center_size(c, Vec2::splat(r * 2.15)))
            .on_hover_text("外圈左半圈/右半圈：各转一格；内侧：方向键和确认");

        // 当前按下区域（用于视觉反馈）
        let mut active: Option<&'static str> = None;
        if resp.is_pointer_button_down_on() {
            if let Some(pos) = resp.interact_pointer_pos() {
                active = wheel_region(pos - c, r);
            }
        }

        // Outer ring: left/right clicks, distinct from the four direction keys.
        let ring_in = r * 0.99;
        let ring_out = r * 1.10;
        if resp.clicked() {
            if let Some(pos) = resp.interact_pointer_pos() {
                let d=pos-c;
                if d.length()>=ring_in && d.length()<=ring_out {
                    let step=if d.x<0.0 {-1} else {1};
                    self.ring_turns+=step;
                    pending.push(Event::Dial {dial:"dpad_ring",step});
                }
            }
        }

        // 底盘
        shadow(p, Rect::from_center_size(c, Vec2::splat(r * 1.9)), r);
        rgrad_circle(p, c, r * 0.97, rgb(0x3c, 0x3d, 0x41), rgb(0x22, 0x23, 0x26), 48);
        // 转盘环带：比底盘亮一档，明确"这一圈可以转"
        let band_mid = ring_in + (ring_out - ring_in) * 0.5;
        p.circle_stroke(c, band_mid, Stroke::new(ring_out - ring_in, rgb(0x4a, 0x4c, 0x52)));
        p.circle_stroke(c, ring_in, Stroke::new(x.u(1.0), rgb(0x1c, 0x1d, 0x20)));
        p.circle_stroke(c, ring_out, Stroke::new(x.u(1.0), rgb(0x16, 0x17, 0x1a)));
        // 环带上的细密刻度
        for i in 0..48 {
            let a = i as f32 / 48.0 * std::f32::consts::TAU;
            let r0 = band_mid - (ring_out - ring_in) * 0.34;
            let r1 = band_mid + (ring_out - ring_in) * 0.34;
            let q0 = c + Vec2::new(r0 * a.cos(), r0 * a.sin());
            let q1 = c + Vec2::new(r1 * a.cos(), r1 * a.sin());
            p.line_segment([q0, q1], Stroke::new(x.u(0.7), rgb(0x6b, 0x6e, 0x74)));
        }
        // 环带上的指示点：随累计旋转移动
        {
            // 指示点沿上半环左右滑动，直观显示转动方向与累计量
            let span = (self.ring_turns as f32 * 6.0).clamp(-70.0, 70.0);
            let a = (-90.0 + span).to_radians();
            let dot = c + Vec2::new(band_mid * a.cos(), band_mid * a.sin());
            p.circle_filled(dot, x.u(4.5), rgb(0xc0, 0x39, 0x2b));
            p.circle_stroke(dot, x.u(4.5), Stroke::new(x.u(1.0), rgb(0x7a, 0x22, 0x18)));
            text(p, x, 880.0, 470.0, 10.0, &format!("{}", self.ring_turns),
                 rgb(0xc9, 0xc9, 0xcb), Align2::CENTER_CENTER, true);
        }

        // 外圈虚线刻度（细密）
        let n_dash = 60;
        for i in (0..n_dash).step_by(2) {
            let a0 = i as f32 / n_dash as f32 * std::f32::consts::TAU;
            let a1 = (i as f32 + 0.55) / n_dash as f32 * std::f32::consts::TAU;
            let pts: Vec<Pos2> = (0..=4)
                .map(|k| {
                    let a = a0 + (a1 - a0) * k as f32 / 4.0;
                    c + Vec2::new(r * 1.0 * a.cos(), r * 1.0 * a.sin())
                })
                .collect();
            p.add(egui::Shape::line(pts, Stroke::new(x.u(1.0), rgb(0x8c, 0x8d, 0x90))));
        }

        // 四向扇形键
        let dirs = [("UP", 0.0f32), ("RIGHT", 90.0), ("DOWN", 180.0), ("LEFT", 270.0)];
        let r_out = r * 0.86;
        let r_in = r * 0.40;
        for (name, deg) in dirs {
            let pressed = active == Some(name);
            let (ci, co) = if pressed {
                (rgb(0x1c, 0x1d, 0x20), rgb(0x14, 0x15, 0x17))
            } else {
                (rgb(0x54, 0x56, 0x5b), rgb(0x2b, 0x2c, 0x30))
            };
            let a0 = (deg - 38.0).to_radians();
            let a1 = (deg + 38.0).to_radians();
            let mut pts: Vec<Pos2> = (0..=10)
                .map(|k| {
                    let a = a0 + (a1 - a0) * k as f32 / 10.0;
                    // 屏幕坐标：0° = 正上方，顺时针
                    c + Vec2::new(r_out * a.sin(), -r_out * a.cos())
                })
                .collect();
            for k in (0..=10).rev() {
                let a = a0 + (a1 - a0) * k as f32 / 10.0;
                pts.push(c + Vec2::new(r_in * a.sin(), -r_in * a.cos()));
            }
            let centroid = c + Vec2::new(
                (r_in + r_out) / 2.0 * deg.to_radians().sin(),
                -(r_in + r_out) / 2.0 * deg.to_radians().cos(),
            );
            let ring: Vec<(Pos2, Color32)> = pts
                .iter()
                .map(|q| {
                    let t = ((*q - centroid).length() / (r_out - r_in).max(1.0)).clamp(0.0, 1.0);
                    (*q, lerp(ci, co, t))
                })
                .collect();
            p.add(egui::Shape::mesh(fan_mesh(centroid, ci, &ring)));
            stroke_outline(p, &pts, 1.0, rgb(0x10, 0x10, 0x11));
            // 三角箭头
            let am = deg.to_radians();
            let tpos = c + Vec2::new(r_out * 0.70 * am.sin(), -r_out * 0.70 * am.cos());
            let s7 = x.u(7.0);
            let (ux, uy) = (am.sin(), -am.cos());
            let (px, py) = (am.cos(), am.sin());
            p.add(egui::Shape::convex_polygon(
                vec![
                    tpos + Vec2::new(ux * s7, uy * s7),
                    tpos + Vec2::new(-ux * s7 * 0.5 + px * s7 * 0.8, -uy * s7 * 0.5 + py * s7 * 0.8),
                    tpos + Vec2::new(-ux * s7 * 0.5 - px * s7 * 0.8, -uy * s7 * 0.5 - py * s7 * 0.8),
                ],
                rgb(0xd2, 0xd2, 0xd4),
                Stroke::NONE,
            ));
        }

        // 中央 ENTER
        let er = r * 0.34;
        let pressed = active == Some("ENTER");
        rgrad_circle(
            p,
            c,
            er,
            if pressed { rgb(0x26, 0x27, 0x2a) } else { rgb(0x5c, 0x5e, 0x63) },
            if pressed { rgb(0x18, 0x19, 0x1c) } else { rgb(0x30, 0x31, 0x35) },
            32,
        );
        p.circle_stroke(c, er, Stroke::new(1.2, rgb(0x10, 0x10, 0x11)));
        p.text(
            c,
            Align2::CENTER_CENTER,
            "ENTER",
            FontId::new(x.u(12.0), FontFamily::Name("cjk-bold".into())),
            rgb(0xe0, 0xe0, 0xe2),
        );
        // 已验证实心绿点（ENTER + 四向）
        ready_dot(p, c + Vec2::new(0.0, r * 1.06), x.u(4.0), true);

        if resp.clicked() {
            if let Some(pos) = resp.interact_pointer_pos() {
                if let Some(region) = wheel_region(pos - c, r) {
                    pending.push(Event::Key(region));
                }
            }
        }
    }
}

/// 方向盘命中：d 为相对中心的位移（屏幕坐标）
fn wheel_region(d: Vec2, r: f32) -> Option<&'static str> {
    if d.length() < r * 0.36 {
        return Some("ENTER");
    }
    // Outside 0.94r the band belongs to the rotary dial, not to the direction keys.
    if d.length() > r * 0.94 {
        return None;
    }
    let ang = d.x.atan2(-d.y).to_degrees().rem_euclid(360.0);
    Some(match ((ang + 45.0) / 90.0) as usize % 4 {
        0 => "UP",
        1 => "RIGHT",
        2 => "DOWN",
        _ => "LEFT",
    })
}

/// 深色小圆角键（< > 拨轮键）
fn draw_dark_key(p: &egui::Painter, x: X, r: Rect, label: &str, down: bool) {
    let rr = if down { r.translate(Vec2::new(0.0, x.u(1.0))) } else { r };
    if !down {
        shadow(p, r, x.u(8.0));
    }
    vgrad(p, rr, x.u(8.0), if down { rgb(0x2a, 0x2b, 0x2e) } else { rgb(0x3c, 0x3d, 0x41) }, rgb(0x26, 0x27, 0x2a));
    stroke_outline(p, &rounded_outline(rr, x.u(8.0), 4), 1.0, rgb(0x16, 0x17, 0x1a));
    p.text(
        rr.center(),
        Align2::CENTER_CENTER,
        label,
        FontId::new(x.u(15.0), FontFamily::Name("cjk-bold".into())),
        rgb(0xdd, 0xdd, 0xdd),
    );
}

/// 深色圆角键（MENU 胶囊等）
fn draw_round_key(p: &egui::Painter, x: X, r: Rect, rad: f32, label: &str, size: f32, down: bool) {
    let rr = if down { r.translate(Vec2::new(0.0, x.u(1.5))) } else { r };
    if !down {
        shadow(p, r, rad);
    }
    let (t, b) = if down {
        (rgb(0x33, 0x34, 0x38), rgb(0x26, 0x27, 0x2a))
    } else {
        (rgb(0x54, 0x56, 0x5b), rgb(0x2b, 0x2c, 0x30))
    };
    vgrad(p, rr, rad, t, b);
    stroke_outline(p, &rounded_outline(rr, rad, 8), 1.0, rgb(0x1b, 0x1c, 0x1f));
    if !down {
        p.line_segment(
            [rr.left_top() + Vec2::new(rad * 0.6, x.u(1.5)), rr.right_top() + Vec2::new(-rad * 0.6, x.u(1.5))],
            Stroke::new(1.0, Color32::from_rgba_unmultiplied(255, 255, 255, 45)),
        );
    }
    p.text(
        rr.center(),
        Align2::CENTER_CENTER,
        label,
        FontId::new(x.u(size), FontFamily::Name("cjk-bold".into())),
        rgb(0xe8, 0xe8, 0xe8),
    );
}

/// 圆形按钮（C1/AF-ON/Fn/播放/删除）
fn draw_circle_key(p: &egui::Painter, x: X, c: Pos2, r: f32, label: &str, size: f32, down: bool) {
    let cc = if down { c + Vec2::new(0.0, x.u(1.5)) } else { c };
    if !down {
        shadow(p, Rect::from_center_size(c, Vec2::splat(r * 2.0)), r);
    }
    let (i, o) = if down {
        (rgb(0x30, 0x31, 0x35), rgb(0x22, 0x23, 0x26))
    } else {
        (rgb(0x54, 0x56, 0x5b), rgb(0x2b, 0x2c, 0x30))
    };
    rgrad_circle(p, cc, r, i, o, 32);
    p.circle_stroke(cc, r, Stroke::new(1.2, rgb(0x1b, 0x1c, 0x1f)));
    if !down {
        p.circle_filled(cc + Vec2::new(-r * 0.3, -r * 0.38), r * 0.18, Color32::from_rgba_unmultiplied(255, 255, 255, 40));
    }
    if !label.is_empty() {
        p.text(
            cc,
            Align2::CENTER_CENTER,
            label,
            FontId::new(x.u(size), FontFamily::Name("cjk-bold".into())),
            rgb(0xe8, 0xe8, 0xe8),
        );
    }
}

// ---------------------------------------------------------------- 字体与图像

/// egui 默认字体不含 CJK，从系统加载中文字体（找不到则退化为方块，不 panic）
fn install_cjk_fonts(ctx: &egui::Context) {
    const REGULAR: &[&str] = &[
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/wenquanyi/wqy-microhei-lite/wqy-microhei-lite.ttc",
        "/usr/share/fonts/wenquanyi/wqy-microhei/wqy-microhei.ttc",
        "/usr/share/fonts/adobe-source-han-sans/SourceHanSansCN-Regular.otf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
    ];
    const BOLD: &[&str] = &[
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ];
    let mut fonts = egui::FontDefinitions::default();
    let mut loaded = false;
    for path in REGULAR {
        if let Ok(bytes) = std::fs::read(path) {
            fonts
                .font_data
                .insert("cjk".into(), egui::FontData::from_owned(bytes).into());
            fonts
                .families
                .entry(FontFamily::Proportional)
                .or_default()
                .push("cjk".into());
            fonts
                .families
                .entry(FontFamily::Monospace)
                .or_default()
                .push("cjk".into());
            loaded = true;
            break;
        }
    }
    for path in BOLD {
        if let Ok(bytes) = std::fs::read(path) {
            fonts
                .font_data
                .insert("cjk-bold".into(), egui::FontData::from_owned(bytes).into());
            fonts
                .families
                .entry(FontFamily::Name("cjk-bold".into()))
                .or_default()
                .push("cjk-bold".into());
            break;
        }
    }
    if loaded {
        ctx.set_fonts(fonts);
    } else {
        eprintln!("警告：未找到系统 CJK 字体，中文将显示为方块");
    }
}

fn load_png(path: &str) -> Option<egui::ColorImage> {
    let bytes = std::fs::read(path).ok()?;
    let img = image::load_from_memory(&bytes).ok()?.to_rgba8();
    let (w, h) = (img.width() as usize, img.height() as usize);
    Some(egui::ColorImage::from_rgba_unmultiplied([w, h], &img))
}

/// Historical screenshots are preview-only and must be selected explicitly.
fn resolve_frame_path(arg: Option<String>) -> Option<String> {
    arg
}

// ---------------------------------------------------------------- main

fn self_test() {
    // 无人值守：模拟 3 次点击事件打到 stdout，退出码 0 即通过
    let evs = [
        Event::Key("MENU"),
        Event::Dial { dial: "rear", step: 1 },
        Event::Mode("M"),
    ];
    for ev in evs {
        println!("{}  {}", now_hms(), ev.json());
    }
    println!("self-test OK");
}

#[cfg(all(test, unix))]
mod reset_contract_tests {
    use super::*;
    use std::io::BufRead;
    use std::os::unix::process::ExitStatusExt;

    #[test]
    fn workspace_preview_requires_the_exact_token_and_known_state() {
        let output = |text: String| Ok(std::process::Output {
            status: std::process::ExitStatus::from_raw(0), stdout: text.into_bytes(), stderr: Vec::new(),
        });
        let token = format!("gen-{}", "a".repeat(64));
        assert_eq!(workspace_preview(output(format!("WORKSPACE_CONFIG_PREVIEW {token} backup\n"))).unwrap(), token);
        for text in ["WORKSPACE_CONFIG_EMPTY".to_string(),
                     "WORKSPACE_CONFIG_PREVIEW gen-short backup".to_string(),
                     format!("WORKSPACE_CONFIG_PREVIEW {token} unknown"),
                     format!("WORKSPACE_CONFIG_PREVIEW {token} reset extra"),
                     format!("CONFIG_RESET_APPLIED {token}")] {
            assert!(workspace_preview(output(text)).is_err());
        }
    }

    #[test]
    fn layout_diagnostics_recheck_dialog_expansion_and_position_changes() {
        let rect = Rect::from_min_size(Pos2::new(0.0, 0.0), Vec2::new(10.0, 10.0));
        let original = vec![("reset_open".into(), rect)];
        let moved = vec![("reset_open".into(), rect.translate(Vec2::new(1.0, 0.0)))];
        let mut expanded = original.clone();
        expanded.push(("reset_confirm".into(), rect));
        assert_ne!(layout_signature(&original), layout_signature(&moved));
        assert_ne!(layout_signature(&original), layout_signature(&expanded));
        assert_eq!(layout_signature(&original), layout_signature(&original));
    }

    #[test]
    fn reset_success_needs_both_exit_status_and_completion_receipt() {
        let output = |status, text: &[u8]| Ok(std::process::Output {
            status: std::process::ExitStatus::from_raw(status),
            stdout: text.to_vec(), stderr: b"failure".to_vec(),
        });
        assert!(reset_output(output(0, b"CONFIG_RESET_APPLIED /owned/record\n")).starts_with("reset 完成"));
        assert!(reset_output(output(0, b"not a receipt")).starts_with("reset 未确认"));
        assert!(reset_output(output(256, b"CONFIG_RESET_APPLIED /owned/record\n")).starts_with("reset 失败"));
    }

    #[test]
    fn ui_observes_the_python_runner_flock_and_recovers_after_release() {
        let root = std::env::temp_dir().join(format!("camui-lock-{}-{}", std::process::id(),
            SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
        std::fs::create_dir_all(root.join("analysis")).unwrap();
        let path = root.join("analysis/.run.lock");
        std::fs::File::create(&path).unwrap();
        assert!(reset_idle_reason(&root).is_none());
        let mut child = std::process::Command::new("python3")
            .args(["-B", "-c", "import fcntl,sys; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); sys.stdin.read()"])
            .arg(&path).stdin(std::process::Stdio::piped()).stdout(std::process::Stdio::piped())
            .spawn().unwrap();
        let mut ready = String::new();
        std::io::BufReader::new(child.stdout.take().unwrap()).read_line(&mut ready).unwrap();
        assert_eq!(ready.trim(), "locked");
        assert!(reset_idle_reason(&root).is_some());
        drop(child.stdin.take());
        assert!(child.wait().unwrap().success());
        assert!(reset_idle_reason(&root).is_none());
        std::fs::write(root.join("analysis/.config-transaction.json"), b"pending").unwrap();
        assert!(reset_idle_reason(&root).unwrap().contains("未完成的配置事务"));
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[cfg(test)]
mod input_contract_tests {
    use super::*;

    #[test]
    fn delivery_receipts_keep_uart_and_mailbox_contracts_separate() {
        let mailbox = "LOW_INPUT_DONE profile=mailbox-v1 seq=7 rc=0 op=2 original_queue=0x807a0020\n";
        assert!(input_delivery_confirmed(mailbox));
        assert!(input_delivery_confirmed("INJECT_KEY_SEND seq=1 result=0\nMENU_DIAG_COMMAND_DONE_owned:0\n"));
        for invalid in [mailbox.replace("rc=0", "rc=1"), mailbox.replace("seq=7", "seq=0"),
                        mailbox.replace("op=2", "op=9"), mailbox.replace("0x807a0020", "0x807a0021"),
                        mailbox.replace("mailbox-v1", "unknown"), format!("{mailbox}suffix").replace('\n', " ")] {
            assert!(!input_delivery_confirmed(&invalid), "{invalid}");
        }
        assert!(!input_delivery_confirmed("MENU_DIAG_COMMAND_DONE_owned:0\n"));
        assert!(!input_delivery_confirmed("INJECT_KEY_SEND seq=1 result=0\n"));
    }

    #[test]
    fn menu_packet_matches_observed_callback_bytes() {
        assert_eq!(hex32(&input_record(0x1ab,1,0)),
            "ab01000000000000010000000000000000000000000000000100000000000000");
    }

    #[test]
    fn negative_ring_step_is_signed_status_not_another_key() {
        let (code,quantum)=dial_codes("dpad_ring").unwrap();
        assert_eq!(hex32(&input_record(code,-quantum,0)),
            "1d00001000000000e8ffffff0000000000000000000000000100000000000000");
    }

    #[test]
    fn shutter_and_power_use_the_body_raw_key_table() {
        // Values from appFw's raw->UIBIZ table at file offset 0x3704b98; the same
        // table independently reproduces 12 already-accepted injections.
        assert_eq!(key_code("SHUTTER_HALF"),Some(0x1f1));
        assert_eq!(key_code("SHUTTER"),Some(0xa7));
        assert_eq!(key_code("POWER"),Some(0x02));
        // Still no invented code for inputs we have not traced.
        assert_eq!(key_code("SENSOR"),None);
        assert_eq!(key_code("LENS"),None);
    }

    #[test]
    fn pp_positions_use_original_noncontiguous_status_domain() {
        assert_eq!(mode_position("P"),Some(3));
        assert_eq!(mode_position("A"),Some(5));
        assert_eq!(mode_position("S"),Some(4));
        assert_eq!(mode_position("2"),Some(0x13));
        assert_eq!(position_key("STILL"),Some(1));
        assert_eq!(position_key("SQ"),Some(3));
    }

    #[test]
    fn raw_negative_rotation_survives_unsigned_cli_parse() {
        assert_eq!(input_command(0x1000001d,-24),
            "/simulation/inject-key 0x807a0020 0x92840747 0x1000001d 0 0xffffffe8 0 1");
    }
}

fn main() -> eframe::Result<()> {
    let mut frame_arg: Option<String> = None;
    let mut live_arg: Option<String> = None;
    let mut input_arg: Option<String> = None;
    let mut managed = false;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--managed-close-on-eof" => managed = true,
            "--self-test" => {
                self_test();
                return Ok(());
            }
            "--frame" => frame_arg = args.next(),
            _ if a.starts_with("--frame=") => frame_arg = Some(a["--frame=".len()..].into()),
            "--input-dir" => input_arg = args.next(),
            _ if a.starts_with("--input-dir=") => input_arg = Some(a["--input-dir=".len()..].into()),
            "--live" => live_arg = args.next(),
            _ if a.starts_with("--live=") => live_arg = Some(a["--live=".len()..].into()),
            _ => eprintln!("未知参数：{a}"),
        }
    }

    if managed {
        std::thread::spawn(|| {
            let _ = std::io::copy(&mut std::io::stdin().lock(), &mut std::io::sink());
            MANAGER_CLOSE.store(true, std::sync::atomic::Ordering::Relaxed);
        });
    }

    let mut options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("ILCE-7CM2 · QEMU 机身控制原型")
            .with_inner_size([1420.0, 880.0])
            .with_min_inner_size([900.0, 640.0]),
        ..Default::default()
    };
    if live_arg.is_some() {
        options.renderer = eframe::Renderer::Glow;
        options.glow_options.vsync = false;
    }
    eframe::run_native(
        "camera-ui-rs",
        options,
        Box::new(move |cc| {
            Ok(Box::new(App::new(
                cc,
                frame_arg.clone(),
                live_arg.clone(),
                input_arg.clone(),
            )))
        }),
    )
}
