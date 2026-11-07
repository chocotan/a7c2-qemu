//! Explicit-instance firmware development panel. Uses the application's egui
//! fonts/theme and std only. See 2026-11-06-firmware-development-ui/DESIGN.md.
use eframe::egui;
use std::collections::BTreeMap;
use std::path::{Component, Path, PathBuf};
use std::process::Command;
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::time::Duration;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum FirmwareDevTab {
    #[default]
    Files,
    Boot,
    Update,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DevAction {
    Status,
    FileTest,
    WorkspaceOverwrite,
    Connect,
    Disconnect,
    Jiritsu,
    Cold,
    Hot,
    Sequence,
    ValidatePackage,
    PrepareSd,
    Update,
}

impl DevAction {
    fn argument(self) -> &'static str {
        match self {
            Self::Status => "status",
            Self::FileTest => "file-test",
            Self::WorkspaceOverwrite => "workspace-overwrite",
            Self::Connect => "connect",
            Self::Disconnect => "disconnect",
            Self::Jiritsu => "jiritsu",
            Self::Cold => "cold",
            Self::Hot => "hot",
            Self::Sequence => "sequence",
            Self::ValidatePackage => "validate-package",
            Self::PrepareSd => "prepare-sd",
            Self::Update => "update",
        }
    }

    fn uses_package(self) -> bool {
        matches!(self, Self::ValidatePackage | Self::PrepareSd | Self::Update)
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum JobPhase {
    #[default]
    Idle,
    Running,
    ObservationPaused,
}

#[derive(Clone, Debug)]
pub struct DevResult {
    pub action: String,
    pub status: String,
    pub message: String,
    pub fields: BTreeMap<String, String>,
}

impl DevResult {
    pub fn field(&self, key: &str) -> &str {
        self.fields.get(key).map(String::as_str).unwrap_or("")
    }
}

fn decode_value(value: &str) -> Result<String, String> {
    let mut bytes = Vec::with_capacity(value.len());
    let mut input = value.bytes();
    while let Some(byte) = input.next() {
        if byte == b'%' {
            let a = input.next().and_then(|c| (c as char).to_digit(16));
            let b = input.next().and_then(|c| (c as char).to_digit(16));
            match (a, b) {
                (Some(a), Some(b)) => bytes.push((a * 16 + b) as u8),
                _ => return Err("后端回执百分号编码不完整".into()),
            }
        } else if byte.is_ascii() && !byte.is_ascii_control() {
            bytes.push(byte);
        } else {
            return Err("后端回执必须使用百分号编码".into());
        }
    }
    let result = String::from_utf8(bytes).map_err(|_| "后端回执不是 UTF-8".to_string())?;
    if result
        .chars()
        .any(|c| c.is_control() && c != '\n' && c != '\t')
    {
        return Err("后端回执含控制字符".into());
    }
    Ok(result)
}

fn parse_reply(text: &str, action: DevAction, code: Option<i32>) -> Result<DevResult, String> {
    if text.len() > 64 * 1024 {
        return Err("后端回执超过 64 KiB".into());
    }
    let mut lines = text.trim_end_matches(['\n', '\r']).lines();
    if lines.next() != Some("FIRMWARE_DEV_V1") {
        return Err("后端没有返回固件开发协议头".into());
    }
    let mut fields = BTreeMap::new();
    let mut ended = false;
    for line in lines {
        if ended {
            return Err("后端回执结束后出现额外内容".into());
        }
        if line == "END" {
            ended = true;
            continue;
        }
        let (key, value) = line.split_once('=').ok_or("后端回执字段格式错误")?;
        if key.is_empty() || !key.bytes().all(|c| c.is_ascii_lowercase() || c == b'_') {
            return Err("后端回执字段名无效".into());
        }
        if fields.insert(key.into(), decode_value(value)?).is_some() {
            return Err("后端回执字段重复".into());
        }
    }
    if !ended || fields.get("action").map(String::as_str) != Some(action.argument()) {
        return Err("后端回执不完整或动作不一致".into());
    }
    let status = fields.get("status").ok_or("后端回执缺少状态")?.clone();
    if !matches!(
        status.as_str(),
        "ready" | "planned" | "completed" | "blocked" | "failed"
    ) {
        return Err("后端返回未知状态".into());
    }
    let accepted = matches!(status.as_str(), "ready" | "planned" | "completed");
    if (accepted && code != Some(0)) || (!accepted && code != Some(2)) {
        return Err(format!("后端退出码与回执不一致：{code:?} / {status}"));
    }
    let message = fields.get("message").ok_or("后端回执缺少说明")?.clone();
    Ok(DevResult {
        action: action.argument().into(),
        status,
        message,
        fields,
    })
}

fn absolute_input(value: &str) -> Result<PathBuf, String> {
    let path = PathBuf::from(value);
    if value.is_empty()
        || value.chars().any(char::is_control)
        || !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir))
    {
        return Err("请输入不含控制字符或 .. 的绝对路径".into());
    }
    Ok(path)
}

fn command_arguments(
    backend: &Path,
    context: &str,
    package: &str,
    action: DevAction,
    virtual_dev_update: bool,
) -> Result<Vec<std::ffi::OsString>, String> {
    if !backend.is_absolute()
        || backend.file_name().and_then(|s| s.to_str()) != Some("firmware-development.py")
    {
        return Err("固件开发后端必须指向固定的 firmware-development.py".into());
    }
    let context = absolute_input(context)?;
    let mut args = vec![
        "-B".into(),
        backend.as_os_str().into(),
        action.argument().into(),
        "--context".into(),
        context.into_os_string(),
        "--human".into(),
    ];
    if action.uses_package() {
        args.push("--package".into());
        args.push(absolute_input(package)?.into_os_string());
        args.push("--profile".into());
        args.push(if virtual_dev_update {
            "virtual-dev".into()
        } else {
            "official".into()
        });
        if virtual_dev_update {
            args.push("--virtual-dev-update".into());
        }
    }
    Ok(args)
}

pub struct FirmwareDevPanel {
    pub selected_tab: FirmwareDevTab,
    pub context_path: String,
    pub package_path: String,
    pub virtual_dev_update: bool,
    pub phase: JobPhase,
    pub status: String,
    pub results: Vec<DevResult>,
    pub current: BTreeMap<String, String>,
    python: PathBuf,
    backend: PathBuf,
    job: Option<Receiver<Result<DevResult, String>>>,
    active_action: Option<DevAction>,
    initialized: bool,
}

impl FirmwareDevPanel {
    /// The main application supplies its explicit private context, interpreter,
    /// and installed backend path. No discovery of disks, VMs or other runs.
    pub fn new(
        context: impl Into<String>,
        python: impl Into<PathBuf>,
        backend: impl Into<PathBuf>,
    ) -> Self {
        Self {
            selected_tab: FirmwareDevTab::Files,
            context_path: context.into(),
            package_path: String::new(),
            virtual_dev_update: false,
            phase: JobPhase::Idle,
            status: "等待读取当前实例".into(),
            results: Vec::new(),
            current: BTreeMap::new(),
            python: python.into(),
            backend: backend.into(),
            job: None,
            active_action: None,
            initialized: false,
        }
    }

    pub fn busy(&self) -> bool {
        self.job.is_some()
    }

    /// Stops observation only. The worker keeps the receipt channel, and owned
    /// VM shutdown/flush stays with its controller. No child.kill or signals.
    pub fn cancel_observation(&mut self) {
        if self.busy() {
            self.phase = JobPhase::ObservationPaused;
            self.status = "已取消前台观察；后端继续保存记录，等待所属控制器正常收尾".into();
        }
    }

    fn start_worker<F>(&mut self, ctx: &egui::Context, action: DevAction, work: F)
    where
        F: FnOnce() -> Result<DevResult, String> + Send + 'static,
    {
        if self.busy() {
            return;
        }
        let (sender, receiver) = mpsc::sync_channel(1);
        let repaint = ctx.clone();
        match std::thread::Builder::new()
            .name("firmware-development".into())
            .spawn(move || {
                let result = work();
                let _ = sender.send(result);
                repaint.request_repaint();
            }) {
            Ok(_) => {
                self.job = Some(receiver);
                self.active_action = Some(action);
                self.phase = JobPhase::Running;
                self.status = format!("正在执行 {}…", action.argument());
            }
            Err(error) => self.status = format!("无法创建后台任务：{error}"),
        }
    }

    pub fn start_action(&mut self, ctx: &egui::Context, action: DevAction) {
        if self.busy() {
            return;
        }
        let args = match command_arguments(
            &self.backend,
            &self.context_path,
            &self.package_path,
            action,
            self.virtual_dev_update,
        ) {
            Ok(args) => args,
            Err(message) => {
                self.status = message;
                return;
            }
        };
        let python = self.python.clone();
        self.start_worker(ctx, action, move || {
            let output = Command::new(python)
                .args(args)
                .output()
                .map_err(|e| format!("无法启动固件开发后端：{e}"))?;
            let stdout = std::str::from_utf8(&output.stdout)
                .map_err(|_| "后端输出不是 UTF-8".to_string())?;
            parse_reply(stdout, action, output.status.code()).map_err(|e| {
                let stderr: String = String::from_utf8_lossy(&output.stderr)
                    .chars()
                    .take(1000)
                    .collect();
                format!("{e} · {stderr}")
            })
        });
    }

    /// Nonblocking even while a VM/crypto process is running. Returns whether a
    /// terminal receipt arrived this frame, including after observation cancel.
    pub fn poll(&mut self) -> bool {
        let received = match self.job.as_ref().map(Receiver::try_recv) {
            None | Some(Err(TryRecvError::Empty)) => return false,
            Some(Err(TryRecvError::Disconnected)) => {
                Err("后台任务通道已关闭；执行状态未确认，保留原任务记录".into())
            }
            Some(Ok(result)) => result,
        };
        let action = self.active_action.take().unwrap_or(DevAction::Status);
        self.job = None;
        self.phase = JobPhase::Idle;
        let result = match received {
            Ok(result) => result,
            Err(message) => DevResult {
                action: action.argument().into(),
                status: "failed".into(),
                message,
                fields: BTreeMap::new(),
            },
        };
        self.status = format!("{} · {}", result.status, result.message);
        // Actual AP/WBI/persistence are only reported by backend status; a path
        // selection or successful process spawn cannot update these indicators.
        for key in [
            "instance",
            "generation",
            "disk",
            "ap_sha",
            "wbi",
            "changed_persistent",
            "runtime",
            "workspace",
        ] {
            if let Some(value) = result.fields.get(key) {
                self.current.insert(key.into(), value.clone());
            }
        }
        self.results.push(result);
        if self.results.len() > 32 {
            self.results.remove(0); // All records remain in the backend's run directory.
        }
        true
    }

    fn indicator(&self, key: &str) -> &str {
        self.current
            .get(key)
            .filter(|s| !s.is_empty())
            .map(String::as_str)
            .unwrap_or("未观测")
    }

    fn button(&mut self, ctx: &egui::Context, ui: &mut egui::Ui, label: &str, action: DevAction) {
        if ui
            .add_enabled(!self.busy(), egui::Button::new(label))
            .clicked()
        {
            self.start_action(ctx, action);
        }
    }

    /// Content for the main application's independent “固件开发” Window/SidePanel.
    /// All widgets inherit egui fonts, focus rendering, colors and text scaling.
    pub fn show(&mut self, ctx: &egui::Context, ui: &mut egui::Ui) {
        self.poll();
        if !self.initialized {
            self.initialized = true;
            if !self.context_path.is_empty() {
                self.start_action(ctx, DevAction::Status);
            }
        }
        if self.busy() {
            ctx.request_repaint_after(Duration::from_millis(100));
        }
        ui.heading("固件开发");
        ui.label("同一持久虚拟磁盘 · 默认官方固件 · 原 source 保持只读");
        ui.add_space(8.0);
        egui::Grid::new("firmware-dev-current")
            .num_columns(2)
            .spacing([12.0, 6.0])
            .show(ui, |ui| {
                for (label, key) in [
                    ("当前磁盘实例", "instance"),
                    ("实例代", "generation"),
                    ("实际运行 AP SHA", "ap_sha"),
                    ("WBI 状态", "wbi"),
                    ("持久改动", "changed_persistent"),
                ] {
                    ui.label(label);
                    ui.label(self.indicator(key));
                    ui.end_row();
                }
            });
        ui.collapsing("实例路径与来源", |ui| {
            ui.label("主界面提供的私有上下文 JSON");
            ui.add_enabled(
                !self.busy(),
                egui::TextEdit::singleline(&mut self.context_path).desired_width(f32::INFINITY),
            );
            for (label, key) in [
                ("磁盘", "disk"),
                ("Runtime", "runtime"),
                ("工作目录", "workspace"),
            ] {
                ui.label(format!("{label}：{}", self.indicator(key)));
            }
            self.button(ctx, ui, "刷新当前实例", DevAction::Status);
        });
        ui.separator();
        ui.horizontal_wrapped(|ui| {
            ui.selectable_value(&mut self.selected_tab, FirmwareDevTab::Files, "文件测试");
            ui.selectable_value(&mut self.selected_tab, FirmwareDevTab::Boot, "启动测试");
            ui.selectable_value(&mut self.selected_tab, FirmwareDevTab::Update, "升级包测试");
        });
        ui.add_space(8.0);
        match self.selected_tab {
            FirmwareDevTab::Files => {
                ui.strong("修改现有 root / appFw 后直接测试");
                ui.label("沿用工作目录 overwrite 和“连接电脑 + jiritsu”入口。两条路线都写入顶部同一实例，重启后保留。");
                ui.horizontal_wrapped(|ui| {
                    self.button(
                        ctx,
                        ui,
                        "应用工作目录 overwrite",
                        DevAction::WorkspaceOverwrite,
                    );
                    self.button(ctx, ui, "测试当前文件", DevAction::FileTest);
                });
                ui.add_space(8.0);
                ui.horizontal_wrapped(|ui| {
                    self.button(ctx, ui, "连接电脑", DevAction::Connect);
                    self.button(ctx, ui, "jiritsu 认证 / root", DevAction::Jiritsu);
                    self.button(ctx, ui, "断开电脑", DevAction::Disconnect);
                });
                ui.label("实际写入、摘要读回及原 AP 消费由所属后端记录。");
            }
            FirmwareDevTab::Boot => {
                ui.strong("开发后启动验证");
                ui.label("冷启动执行原 init 再进入系统 runtime。组合测试使用 QEMU RAM 保存/恢复；未验证 Sony WBI 或物理热启动。");
                ui.horizontal_wrapped(|ui| {
                    self.button(ctx, ui, "真实冷启动测试", DevAction::Cold);
                    self.button(ctx, ui, "热启动测试", DevAction::Hot);
                    self.button(ctx, ui, "冷启动 → 热启动", DevAction::Sequence);
                });
                ui.label(
                    "独立热启动需要本次已运行的相机状态与匹配的验证记录；可用性由当前实例后端检查，阻塞原因和测试记录会保留。",
                );
            }
            FirmwareDevTab::Update => {
                ui.strong("BODYDATA 系统更新");
                ui.label("BODYDATA.DAT 绝对路径");
                ui.add_enabled(
                    !self.busy(),
                    egui::TextEdit::singleline(&mut self.package_path).desired_width(f32::INFINITY),
                );
                ui.add_enabled(
                    !self.busy(),
                    egui::Checkbox::new(&mut self.virtual_dev_update, "虚拟开发更新：跳过签名验证"),
                );
                if self.virtual_dev_update {
                    ui.label("签名绕过仅传给当前本地虚拟设备的 BODYDATA 流程；CRC 与实例绑定仍必须通过。");
                } else {
                    ui.label("官方模式：要求有效签名、UFU/FDAT CRC 与解密块校验。");
                }
                ui.horizontal_wrapped(|ui| {
                    self.button(ctx, ui, "校验升级包", DevAction::ValidatePackage);
                    self.button(ctx, ui, "准备虚拟 SD", DevAction::PrepareSd);
                    self.button(ctx, ui, "系统更新测试", DevAction::Update);
                });
                ui.label("系统更新使用原 guest SD receiver / updater，目标仍是顶部同一持久磁盘。");
            }
        }
        ui.add_space(8.0);
        ui.separator();
        ui.horizontal_wrapped(|ui| {
            if self.phase == JobPhase::Running {
                ui.spinner();
            }
            if self.phase == JobPhase::ObservationPaused {
                ui.strong("观察已取消 · 后端仍运行");
            }
            if ui
                .add_enabled(
                    self.phase == JobPhase::Running,
                    egui::Button::new("取消观察"),
                )
                .clicked()
            {
                self.cancel_observation();
            }
            if ui
                .add_enabled(
                    self.phase == JobPhase::ObservationPaused,
                    egui::Button::new("继续观察"),
                )
                .clicked()
            {
                self.phase = JobPhase::Running;
                self.status = "继续等待所属控制器回执…".into();
            }
        });
        ui.label(&self.status);
        ui.collapsing(
            format!("测试记录（最近 {} 条）", self.results.len()),
            |ui| {
                egui::ScrollArea::vertical()
                    .max_height(220.0)
                    .show(ui, |ui| {
                        for (index, result) in self.results.iter().enumerate().rev() {
                            ui.push_id(index, |ui| {
                                ui.collapsing(
                                    format!(
                                        "{} · {} · {}",
                                        result.action,
                                        result.status,
                                        result.field("job_id")
                                    ),
                                    |ui| {
                                        ui.label(&result.message);
                                        for key in [
                                            "blocked_code",
                                            "run_id",
                                            "generation",
                                            "result_path",
                                            "first_error_path",
                                        ] {
                                            if !result.field(key).is_empty() {
                                                ui.label(format!("{key}：{}", result.field(key)));
                                            }
                                        }
                                        ui.horizontal_wrapped(|ui| {
                                            if !result.field("first_error_path").is_empty()
                                                && ui.button("打开首错").clicked()
                                            {
                                                open_local_path(result.field("first_error_path"));
                                            }
                                            if !result.field("record_dir").is_empty()
                                                && ui.button("打开测试记录目录").clicked()
                                            {
                                                open_local_path(result.field("record_dir"));
                                            }
                                        });
                                    },
                                );
                            });
                        }
                    });
            },
        );
    }
}

fn open_local_path(value: &str) {
    let Ok(path) = absolute_input(value) else {
        return;
    };
    std::thread::spawn(move || {
        #[cfg(target_os = "linux")]
        let mut command = Command::new("xdg-open");
        #[cfg(target_os = "macos")]
        let mut command = Command::new("open");
        #[cfg(target_os = "windows")]
        let mut command = Command::new("explorer.exe");
        #[cfg(any(target_os = "linux", target_os = "macos", target_os = "windows"))]
        let _ = command.arg(path).status();
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Instant;

    fn panel() -> FirmwareDevPanel {
        FirmwareDevPanel::new(
            "/tmp/context.json",
            "python3",
            "/tools/firmware-development.py",
        )
    }

    fn reply(status: &str) -> String {
        format!(
            "FIRMWARE_DEV_V1\naction=cold\nstatus={status}\nmessage=ok%20%E6%B5%8B%E8%AF%95\nEND\n"
        )
    }

    #[test]
    fn protocol_rejects_false_success_and_truncation() {
        assert_eq!(
            parse_reply(&reply("completed"), DevAction::Cold, Some(0))
                .unwrap()
                .message,
            "ok 测试"
        );
        assert!(parse_reply(&reply("completed"), DevAction::Cold, Some(2)).is_err());
        assert!(parse_reply(&reply("blocked"), DevAction::Cold, Some(0)).is_err());
        assert!(parse_reply(&reply("completed"), DevAction::Hot, Some(0)).is_err());
        for text in [
            reply("completed").replace("END\n", ""),
            reply("completed").replace("message=", "status=blocked\nmessage="),
            reply("completed").replace("ok%20", "%XX"),
            reply("completed") + "extra\n",
            reply("ready-ish"),
        ] {
            assert!(
                parse_reply(&text, DevAction::Cold, Some(0)).is_err(),
                "{text}"
            );
        }
    }

    #[test]
    fn paths_are_literal_argv_and_profile_is_scoped() {
        let payload = "/tmp/a ; $(touch nope) `anything` BODYDATA.DAT";
        let args = command_arguments(
            Path::new("/tools/firmware-development.py"),
            "/tmp/context.json",
            payload,
            DevAction::Update,
            true,
        )
        .unwrap();
        assert!(args.contains(&payload.into()));
        assert!(args.contains(&"--virtual-dev-update".into()));
        let cold = command_arguments(
            Path::new("/tools/firmware-development.py"),
            "/tmp/context.json",
            payload,
            DevAction::Cold,
            true,
        )
        .unwrap();
        assert!(!cold.contains(&"--virtual-dev-update".into()));
        assert!(!cold.contains(&payload.into()));
        for value in ["relative.json", "/tmp/../context.json", "/tmp/a\n.json", ""] {
            assert!(absolute_input(value).is_err());
        }
        assert!(command_arguments(
            Path::new("/tools/evil.py"),
            "/tmp/a",
            "",
            DevAction::Status,
            false
        )
        .is_err());
    }

    #[test]
    fn worker_is_nonblocking_cancel_keeps_owner_and_terminal_receipt() {
        let mut panel = panel();
        let ctx = egui::Context::default();
        let (release, waiting) = mpsc::sync_channel(1);
        let started = Instant::now();
        panel.start_worker(&ctx, DevAction::Cold, move || {
            waiting.recv().unwrap();
            parse_reply(&reply("blocked"), DevAction::Cold, Some(2))
        });
        assert!(started.elapsed() < Duration::from_millis(100));
        assert_eq!(panel.phase, JobPhase::Running);
        assert!(!panel.poll());
        panel.cancel_observation();
        assert_eq!(panel.phase, JobPhase::ObservationPaused);
        assert!(panel.busy());
        panel.start_worker(&ctx, DevAction::Hot, || panic!("second job must not start"));
        release.send(()).unwrap();
        let deadline = Instant::now() + Duration::from_secs(2);
        while !panel.poll() && Instant::now() < deadline {
            std::thread::yield_now();
        }
        assert!(!panel.busy());
        assert_eq!(panel.phase, JobPhase::Idle);
        assert_eq!(panel.results.len(), 1);
        assert_eq!(panel.results[0].status, "blocked");
        assert_eq!(panel.results[0].action, "cold");
    }

    #[test]
    fn idle_cancel_does_nothing_and_thread_failure_is_recorded() {
        let mut panel = panel();
        panel.cancel_observation();
        assert_eq!(panel.phase, JobPhase::Idle);
        let (sender, receiver) = mpsc::channel();
        drop(sender);
        panel.job = Some(receiver);
        panel.active_action = Some(DevAction::Update);
        assert!(panel.poll());
        assert_eq!(panel.results[0].status, "failed");
        assert_eq!(panel.results[0].action, "update");
        assert!(panel.current.is_empty());
    }

    #[test]
    fn controls_receive_keyboard_focus() {
        let ctx = egui::Context::default();
        let mut panel = panel();
        panel.initialized = true;
        let mut first = ctx.run_ui(egui::RawInput::default(), |ui| panel.show(&ctx, ui));
        first.textures_delta.clear();
        let input = egui::RawInput {
            events: vec![egui::Event::Key {
                key: egui::Key::Tab,
                physical_key: None,
                pressed: true,
                repeat: false,
                modifiers: egui::Modifiers::NONE,
            }],
            ..Default::default()
        };
        let mut output = ctx.run_ui(input, |ui| panel.show(&ctx, ui));
        output.textures_delta.clear();
        assert!(ctx.memory(|memory| memory.focused()).is_some());
    }

    #[test]
    fn tabs_render_at_narrow_width_in_both_themes() {
        for dark in [false, true] {
            for tab in [
                FirmwareDevTab::Files,
                FirmwareDevTab::Boot,
                FirmwareDevTab::Update,
            ] {
                let ctx = egui::Context::default();
                ctx.set_visuals(if dark {
                    egui::Visuals::dark()
                } else {
                    egui::Visuals::light()
                });
                let mut panel = panel();
                panel.initialized = true;
                panel.selected_tab = tab;
                let input = egui::RawInput {
                    screen_rect: Some(egui::Rect::from_min_size(
                        egui::Pos2::ZERO,
                        egui::vec2(375.0, 800.0),
                    )),
                    ..Default::default()
                };
                let mut output = ctx.run_ui(input, |ui| panel.show(&ctx, ui));
                output.textures_delta.clear(); // This test has no renderer.
                assert!(!panel.busy());
                assert!(panel.results.is_empty());
            }
        }
    }
}
