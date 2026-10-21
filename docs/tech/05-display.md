# 启动流程 05 · 显示链：从建屏到 GTK LCD 画布

本篇讲原应用启动后画面怎么走完全程：原控件发绘图请求 → 软件 GPE 写位图 →
AP 输出消费者在租期内复制提交 → ramfb 桥交给 QEMU → GTK 窗口画出 LCD。
对应索引第 7、8 步。只覆盖 AP 软件 OSD；CMOS 取景、CP 合成、实体面板不在内。

变量见[索引](README.md)。历史动态结论引自原报告，本次只核对源码，没有重跑。

## 1. 建屏：先分清"建了屏"和"画了像素"

观测器（`menu-observe.c`）挂接原 `view::create_screen`，记录屏 ID、控件数和返回。
`CREATE_SCREEN_ARGS/RETURN` 只说明原建屏入口被调用——控件有没有画、
像素有没有显示，要继续看 `notifyDraw`、`drawFramebuffer` 和输出消费者。

早期定位时，启动屏 `0x308/count28` 已建立但 GPE 只清屏。受控菜单实验
（原九参数生命周期入口，appFw 基址 `+0x1e78870`，菜单 controller `0x346`）
后来自然创建了菜单屏 `0x2ca/count44`。

注意：受控入口是定位工具，不是"自然冷启动已恢复"的证据；`0x1e78870` 是
相对装载基址的偏移，不是任意运行都能用的绝对地址。黑屏时也不要回头改内核——
先分清是没建屏、只清屏、没提交还是显示桥没接。

## 2. 像素格式与软件 GPE

真机 GPE 硬件没有模拟，绘图由软件模型完成
（`gpe-raster.c`、`gpe-sprite.c`）：受限的 Fill/Copy、RGBA4444 sprite、
A8 字体着色、source-over 混合、nearest 缩放。请求先核几何、stride、
地址范围和重叠，不受支持的模式直接拒绝（返回 5），不补假成功。

RGBA4444 是本项目的显式软件模型，不是 Sony 全部像素格式的规范：

```text
像素：little-endian u16，数值 0xRGBA
R=(v>>12)&15，G=(v>>8)&15，B=(v>>4)&15，A=v&15
8bit 展开：channel8 = channel4 * 17
黑底合成的 8bit 通道 = (channel4 * 17 * A + 7) / 15（整数）
ramfb 输出内存字节为 B、G、R、0；配置格式 XRGB8888。
```

踩过的坑：BitBlit 参数块是 144B、callback 在 `+0x80`，不是 Fill 的 `+0x28`；
历史上 69 条"不支持"请求后来被 10 条精确 copy 加 59 条显式软件模型覆盖。
硬件混合舍入和全部 GPE 格式仍未逐像素闭合，不能外推到实体相机。

## 3. 资源解码：Sony LZ77 必须真解出字节

背景和图标是压缩资源。曾经资源文件都打开了，但 31 次 format7 LZ77 解码
因 `/dev/ldec` 缺席全部失败，画面只剩文字重叠。现在的路径：
`observe_lz_decode()` 在 `QEMU_SOFTWARE_LZ77` 下走 `sony_lz77_decode()`
——先完整校验（短读、回距、终止标记、精确输出尺寸），再写入原目标位图。

历史动态结果：九份资源与 Python 参考逐字节匹配，实际菜单 31/31 解码成功，
共写入 1,244,864B，背景、图标、选中条出现。本次没有重跑。

注意：资源"能打开"不等于"已解码消费"；这只覆盖已核资源路径，
不代表 LDEC DMA 驱动已模拟。字体 pins 见 [01-firmware-assets](01-firmware-assets.md)。

## 4. 帧提交：两把 gate 和 LIRO 配对

帧完成链是 `notifyDraw → drawFramebuffer → CmdGpeFlush → callback → 交换缓冲`。
headless-osd 接收端（`headless-osd.c::hosd_step()`）接在原 LIRO 边界，
串行处理这些配对：

| 用途 | 队列 | 消息 |
| --- | --- | --- |
| 控制接收 | `0x8280074d` | GUI 元数据，或 AP `0x1002` 控制体（12B） |
| GUI 来源 | `0x9088076b` | `0x1000`（80B）/`0x1001`（96B）/`0x1004`（16B） |
| 新像素提交 | `0x8280084d` | `0x1003` descriptor（36B） |
| 仅元数据更新 | `0x8280084e` | `0x1005`（8B，只能引用上一次成功保留帧） |
| 完成通知 | 发往 AP `0x8288076c` | `0x6003/0x6005`（各 8B） |

接收端完整提交、读回校验后才发完成通知；任何一步失败就停，不补 ACK。

踩过的坑：ready 信号量 `0x02886047` 返回 ≠ ExternalOSDIF gate
`0x02886044` 打开——早期第二帧不返回，等的其实是后者。两把 gate 不能混同。

## 5. 租期与 HOSDAP02 容器

复制像素时持一整串锁：framebuffer 生命周期锁 → 身份核验 → Bitmap
`AddRef/ReadLock` → raster 锁，锁内复制到私有 buffer，逆序释放。
文件 I/O 和通知都在锁外。descriptor 相同不代表复制期间像素没变，
所以必须带租期复制，不能事后读显存。

一次提交是一份自校验容器 HOSDAP02：

| 部分 | 字节数 | 作用 |
| --- | ---: | --- |
| header | 128 | magic、事务 sequence、descriptor、FNV-1a 校验 |
| metadata | 24930 | 同次冻结的 GUI/widget 描述 |
| 像素 | 614400 | 640×480×2 RGBA4444 |
| 全容器 | 639458 | 单份完整提交 |

注意：`sequence` 增长可能只是元数据更新；判断"有没有新像素"要看
`pixel_source_seq`。持久化只限本次 guest 运行（`/tmp` 是 tmpfs），
导出信息保留 `ack_delivery_proven=False`——文件完整不证明 ACK 送达。

## 6. ramfb：把像素交给 QEMU 显示设备

`ramfb-viewer.c` 是独立消费者：校验容器 → 按上面的公式转 XRGB8888 →
写专用 scanout 区（`[0x41e100000, 0x41e600000)`，两个 2 MiB 槽轮换，
DMA 描述符在 `+0x4ff000`）→ 经 fw_cfg MMIO（`0x09020000`）配置
`etc/ramfb`（fourcc `DRM_FORMAT_XRGB8888`，640×480，stride 2560）→ 触发 DMA。

该区域由 bootargs 的 `memrsv=0x00500000@0x41e100000:uc`
（或 RM 媒体合并后的 `0x00900000`）预留，缺少或重复都拒绝启动。
这些是仿真接口地址，不是实体面板地址。

注意：日志明写 `DMA is not screenshot proof`——DMA 完成不等于画面可见，
还要 QMP 截帧等消费证据。能打开 GTK 窗口也不等于会消费 Sony 私有 OSD。

## 7. GTK LCD 画布：最后一公里

当前主路径：guest ramfb → QMP `screendump` → `menu_live.py` 校验 PPM 并转
640×480 PNG → `menu_control.py` 校验格式 → `camera_ui.py` 解码绘制。

- `SnapshotPoller` 默认 10 秒一帧、最多一条在途、失败退避到 60 秒——
  LCD 是按请求采样，不是实时视频。
- `_read_frame()` 用 `(number, sequence, sha256, captured_at)` 做 token，
  防止把 PNG 和错误的帧元数据配对；解码失败保留上一幅并明说。
- VM 停止、出错或 token 不匹配时，画面标注"旧画面 / 当前画面未确认"；
  标签区分"显示帧"（QMP 截帧）和"像素提交"（带 `pixel_source_seq`）。

```bash
# 执行目录：$PKG；只读查软件转换和窗口接线
cd "$PKG"
rg -n 'static void convert|DRM_FORMAT_XRGB8888|putbe' runtime/analysis/ramfb-viewer.c
rg -n 'native_display|640|480' runtime/analysis/camera_ui.py
```

## 8. 当前边界

AP 软件显示链（资源 → 绘制 → 租期提交 → 显示桥 → GTK）已在各自范围验证，
自然首设和 HUD/MENU 的验收见 validation。但：

- **取景区域仍黑**：AP OSD 不是 CMOS 图像；
- F12、PNG、HOSDAP02 都是界面快照，不是相机照片；
- 输出新黑帧要看新事务和业务生命周期，不能冻结旧菜单伪装在工作。

## 证据入口

- [黑屏分层及显示细节 §6–9](../../../a7c2-re/report/2026-10-17-qemu-native-camera/BOOT-TROUBLESHOOTING.md)
- [显示链设计](../../../a7c2-re/report/2026-10-17-qemu-native-camera/DESIGN.md)
- 本包 [转换器](../../runtime/analysis/ramfb-viewer.c)、
  [软件 GPE](../../runtime/analysis/gpe-sprite.c)、
  [headless OSD](../../runtime/analysis/headless-osd.c)
- [本包单窗/LCD/HUD 验收](../../validation/README.md)

## 如果你在做别的机型

GPE、UXC、LZ77、LIRO 配对都要重新核。先分清"有没有画、有没有提交、
有没有消费"三层，再谈窗口。可复用的是格式/字节序核验、真实解码、
缓冲租期、单容器自校验和逐层像素对照。
