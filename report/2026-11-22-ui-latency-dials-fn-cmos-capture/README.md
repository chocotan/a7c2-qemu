# 2026-11-22 按键延迟优化、Fn/拨轮修复、自定义 CMOS 与全按写卡实机验证

## 1. 现象与原因

1. **按键到显示延迟高**：`ContinuousLCD` 原先以 120 Hz 轮询 QMP `screendump` 与单核 TCG 争抢，且每帧在同进程内 Pillow 编码 PNG 后再由 GTK `PixbufLoader` 解码 PNG；GTK 以 16 ms 定时器每帧重刷 26 个按钮与“快捷键与日志”文本；`PersistentAppInput` 每次唤醒全量重读 `console.log`；guest `ramfb-viewer` 10 ms 轮询并逐像素写非缓存 `/dev/mem`；冷启动未启用 `tb-size=2048` 且开启 `-d guest_errors,unimp`。
2. **Fn 键无反应**：原厂 `scr0132_0001` 在 `EVENT_INPUT_TACT_FN_ON` 启动约 500 ms 长按定时器，超时落入 `process_fn_key_long_press` 返回 `SCREEN_NONE`。guest 虚拟时间约 6.5 倍快于宿主，导致宿主计时的鼠标按下/抬起或键盘按下/抬起（~80–150 ms）在 guest 内超过 500 ms。
3. **拨轮反了且无响应**：`KEY_DEFINITIONS` 中 `REAR`（`0x10000016` / `2ea`）与 `TOP`（`0x10000013` / `2ef`）码值互换，且 4 个拨轮统一发 ±1024 而非 A7C II 单步（前 ±22、后 ±30、控制 ±24、右上 ±1024）；虚拟 CP 缺失下原厂拨轮不会回发 `0x201b`/`0x200e`/`0x2036` 通知。
4. **默认无色卡 / 无法选图 / 全按无写卡**：`cold/bootin.sh` 未写 `/tmp/virtual-preview.profile`，`original-init-cold` 链路无自定义 CMOS 上传工具和全按写卡钩子；`libInfraFsys.so` 是在运行时 `dlopen` 加载的，constructor 期解析 `Fsys_*` 会得到空指针。

## 2. 方案与改动

- **延迟与抽屉**：`continuous_lcd.py` 改为 15 Hz 空闲 / 60 Hz 激活 + `nudge()` 立即唤醒，新增 `encode_png=False` 原始 640×480 RGB24 零 PNG 通路；`menu_control.py` 存 `self.rgb` 并在 HTTP `/api/snapshot` 懒编码 PNG；`camera_ui.py` 用 `GdkPixbuf.Pixbuf.new_from_bytes` 零解码显示、定时器降至 100 ms、缓存按钮状态并移除底部“快捷键与日志”抽屉；`persistent_app_input.py` 改为 `seek` 增量读；`ramfb-viewer.c` 改为 RAM `stage` 缓存合成 + `inotify`；`qemu-kernel-probe.sh` 对 `A7C2_ORIGINAL_COLD` 默认启用 `tb-size=2048` 并关闭 `-d` 跟踪。
- **Fn 与 4 拨轮**：`inject-key.c` 增加 guest 原子 `TAP` 命令；`input_bindings.py` 将 GTK Fn 按钮点击和键盘 `F` 全部路由到 `op='tap'` -> `PersistentAppInput.tap(0x7095, 20000)`；`menu_live.py` 对调后/右上拨轮并修正 4 拨轮步长；`menu-observe.c` 监听拨轮按 P/AUTO/MR/A/S/M 步进 `virtual_lens_hud_current` 并在 `rc == 0` 时重发给原厂 HUD。
- **CMOS 与全按写卡/播放**：`cold/bootin.sh` 启动前写 `functional-cmos-chart-v1`；新增 `cmos_source.py` + guest 工具 `cmos-import.c` 实现分块 base64 JPEG 上传、C 解码与原子热替换 `/tmp/virtual-cmos-custom.rgb`；`menu-observe.c` 在 `dlopen("libInfraFsys.so")` 绑定 9 个原厂 `Fsys_*` 函数，全按编码 Baseline JPEG（含 Sony EXIF）写 `DCIM/100MSDCF/DSCnnnnn.JPG` 并读回校验，播放键进入叠加回放并屏蔽下层键位避免误触拍摄菜单。

## 3. 验证结果

- **实机验证**（独立隔离实例，不触碰宿主已有实例，完整收据见 [live-verification-receipt.json](live-verification-receipt.json)）：
  - 冷启动 11.21 s，`tb-size=2048` 生效，无 `-d` 跟踪；零 PNG 原始 RGB24（921,600 B）正常输出。
  - 按键到 LCD 延迟：菜单打开 624.6 ms、关闭 827.9 ms；Fn 打开 652.0 ms。
  - Fn 打开原厂 `scr0135_0001`（`id=0xc2`）快捷菜单并可退出（截图：[live-fn-menu-20261122.png](../../docs/images/live-fn-menu-20261122.png)）。
  - 4 拨轮：右上拨轮在 P 档调出原生橙色曝光补偿 `+0.7`；M 档前/后拨轮将底部原厂 HUD 从 `1/125 F4.0` 步进至 `1/1000 F5.6`（截图：[live-dial-m-hud-20261122.png](../../docs/images/live-dial-m-hud-20261122.png)）；控制轮步进虚拟 ISO 至 `ISO 200`（写入 EXIF 与播放页）。
  - 自定义 CMOS 图片 25,260 B 在 3.32 s 内上传热替换生效（截图：[live-custom-cmos-hud-20261122.png](../../docs/images/live-custom-cmos-hud-20261122.png)），恢复色卡生效。
  - 全按快门连拍两张：`A:/DCIM/100MSDCF/DSC00001.JPG`（自定义图，27,878 B）与 `DSC00002.JPG`（色卡，58,133 B）均 `rc=0 readback=1`；播放页展示/翻页/退出通过（截图：[live-playback-20261122.png](../../docs/images/live-playback-20261122.png)）；导出 `SD/card.img` 经宿主 FAT16 解析与 Pillow 解码确认 640×480 JPEG + Sony EXIF（`SONY / ILCE-7CM2`）。
- **边界说明**：全部拍摄/镜头/预览为软件虚拟模型，不代表真实 CP ASIC、物理 ISP 或原厂 `DATABASE.BIN` 索引，`capture_verified` 保持 `false`。当原厂菜单设为 Auto ISO 时，底部原厂 ISO 框仍显示 `ISO AUTO`（虚拟 ISO 步进反映在 EXIF 与播放页）。
