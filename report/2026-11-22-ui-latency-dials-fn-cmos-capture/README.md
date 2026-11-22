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
- **边界说明**：全部拍摄/镜头/预览为软件虚拟模型，不代表真实 CP ASIC、物理 ISP 或硬件直方图/EXIF 解码，`capture_verified` 保持 `false`。当原厂菜单设为 Auto ISO 时，底部原厂 ISO 框仍显示 `ISO AUTO`（虚拟 ISO 步进反映在 EXIF）；`scr7102_0003_still` 直方图与详细 EXIF 面板受 CP 缺失限制保持为空。

## 4. 后续实机问题根因修复（原生播放界面、拨轮与聚焦一致、OFF 关机与窗口关闭）

用户实际体验反馈 4 项问题，全部已完成根因定位、修复与隔离实机复验：

1. **播放界面非原厂 UI → 接入索尼原厂 `scr7102_0001_still`**：
   - 根因：旧版使用自绘 5×7 点阵覆盖全屏（`/tmp/virtual-playback-frame.bin`）并改写按键消息，未走原厂 `libmpr.so` `sidb` 与 `sequence_playback`。
   - 修复：全按写卡后调用原厂 `libmpr.so` `sidb` 登记新拍照片（`getrec_rc=0 uid_rc=0 upd_rc=0 flush_rc=0`）；在 `appFw+0x3228ec0` 拦截被 CP Lane 0 阻塞的 `sequence_playback`（`seq_id=0x30`），交由单常驻工作线程运行原厂 `0x33cd8fc`/`0x33d1b08`/`0x33cd894`，并在 `appFw+0x33d1478` 同步软件解码原厂 `sidb::Select` 选出的真实 JPEG 到 `/tmp/virtual-playback-bg.bin`、置 `*(uint32_t *)(obj + 3024) = (bg_rc == 0 ? 0 : 4)` 后调用纯 AP 路径 `start_playback_exit`（`appFw+0x33ce72c`）；`ramfb-viewer.c` 优先在 `playback_bg_active` 下将原厂透明播放 OSD 合成在真实 JPEG 背景上。EXIF 补齐 `0x0132` / `0x9000` / `0x9003` / `0x9004` 标准 2.32 字段。
   - 实机验证：色卡 `DSC00001.JPG`（58,241 B，`uid=0x41020001`）与自定义图 `DSC00002.JPG`（14,358 B，`uid=0x41020004`）均写卡读回并入库成功；按 `PLAYBACK` 进入原厂 `scr7102_0001_still`（`id=0x23`，70 控件，显示 `2/2` / `1/2`、`100-0001`、`3:2`、`22-11-2026 12:00:00`），`LEFT`/`RIGHT` 同步切换 OSD 编号与解码 JPEG 背景，`UP`/`DISP` 循环 `scr7102_0001_still -> scr7102_0003_still -> scr7102_0002_still -> scr7102_0001_still`，再按 `PLAYBACK` 返回 `scr0132_0001` 并清除播放背景。
2. **A 档后拨轮无效 / 聚焦与变化值错位 → 直接挂载原厂 7 个拨轮叶子执行函数**：
   - 根因：旧版在 `menu-observe.c` 中根据前/后拨轮事件与本地猜测挡位自行改写虚拟光圈/快门，与 `appFw.so` 真实自定义拨轮分配及橙色聚焦框不一致（例如 A7C II 默认 M 档前拨轮为光圈、后拨轮为快门，A/S 档前后拨轮均调对应主参数）。
   - 修复：删除手写拨轮-挡位猜测逻辑，直接 Hook `appFw.so` 自身执行光圈（`0x264fde0`）、快门（`0x274b1f8`）、程序偏移（`0x2552138`）及 ISO（`0x26a85cc`/`0x26a86bc`/`0x26a64ec`/`0x26a65dc`）的 7 个叶子函数，只在原厂决定改动某个参数时按相同方向步进并重发。
   - 实机验证：A 档前后拨轮均调整光圈并橙色聚焦 `F5.6`/`F6.3`；S 档前后拨轮均调整快门并橙色聚焦 `1/500`/`1/2000`；M 档前拨轮调光圈（`F8.0`）、后拨轮调快门（`1/4000` 橙色聚焦）；P 档前后拨轮均触发 `progshift`。
3. **点击 OFF 一直停在“正在关闭” → 消除事件就地改写与高频线程泄漏**：
   - 根因：旧版每次按键/HUD 发布都 `pthread_create` 分离线程（70+ 并发线程叠加 `osal_snd_msg`）且在播放态直接将输入队列消息 `ev[0] = 0` 就地清零，导致 `bootin.elf` 挂起、`Backup_nread` 串口超时与串口事务失步。
   - 修复：彻底取消 `ev[0] = 0` 改写，将所有异步 HUD/写卡/回放任务合并为**唯一常驻 pipe 唤醒工作线程**（`vcmos_worker_main`）。
   - 实机验证：`EXPORT_SD + SHUTDOWN_STORAGE` 连续多轮均在 **2.43–2.63 s** 内完成，`ok=True`、`settings_ok=True`、`internal_frozen=True`、`qmp_quit_confirmed=True`、`returncode=0`、`signals_sent=[]`。
4. **虚拟机开启后无法关闭窗口 → 修复启动期取消与增加明确确认的强制关闭兜底**：
   - 根因：旧版在 `boot_profile == 'original-init-cold'` 且 `state == 'starting'` 时关闭窗口会直接关闭 `MENU_CONTROL_FD` 触发 `ORIGINAL_COLD_OWNER_RETAINED` 死等；且 `camera_ui._close()` 在非 `running` 态无条件调用 `release_inputs()` 导致静默拒绝关闭，优雅保存失败后也缺乏用户确认的兜底关闭入口。
   - 修复：`menu_control.py` 启动期停止统一排队 `export_sd`；新增 `VM.force_close()` 仅对本控制器拥有且 `getpgid == pid` 的子进程组依次尝试 QMP `quit` / `SIGTERM` / `SIGKILL`，严格核验线程与进程组已彻底退出后才释放本实例租约；`camera_ui.py` 仅在 `running` 态调用 `release_inputs()`，在 `_close_failed()` 提供明确确认的“取消 / 重试正常保存 / 强制关闭”对话框，并将 `SIGINT`/`SIGTERM` 通过 `GLib.idle_add(ui._close)` 安全转交 GTK 主循环。

