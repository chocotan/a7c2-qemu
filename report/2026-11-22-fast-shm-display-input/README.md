# 2026-11-22 共享内存直连显示合成与无串口按键环（Fast-SHM）

## 1. 现象与硬件架构原因

### 1.1 为什么原有按键与显示热路径严重卡顿（500 ms ~ 2,000 ms）

在优化前，单次按键到画面刷新需要串联 4 条高延迟、高争用链路：

1. **Guest `/tmp` 是同步 VFAT 闪存而非 `tmpfs`**：原厂 `fstab` 将 `/tmp` 挂载到 `/dev/nflasha10`（`vfat, rw, sync`，由 `sony_persistent_flash.ko` 通过 MMIO 模拟）。
   - `headless-osd.c` 每收到一帧 OSD（包括像素未变的 `0x1005` 元数据帧）都执行 639 KiB `write + fsync + pread + memcmp + rename` 以及 639 KiB FNV-1a 哈希。
   - `gui-model-store.c` 在索尼 UI 线程内同步执行 `/tmp/gui-model-state.bin` 的完整 VFAT 写+校验+重命名（即使 `changed == 0` 也会在一次会话内触发数万次）。
   - 快门闪烁（`/tmp/virtual-shutter-blink`）与回放解码图（`/tmp/virtual-playback-bg.bin`）也走同步 VFAT。
2. **Guest TCG 单核软件合成**：独立进程 `ramfb-viewer` 轮询读取 639 KiB VFAT 文件，在单核 ARM64 TCG 上对 307,200 像素做软件 `RGBA4444 -> XRGB8888` Alpha 混合并拷贝 1.2 MiB 到 `/dev/mem`，再经 `fw_cfg DMA` 通知 QEMU。
3. **Host QMP `screendump` 60 Hz 抢占 vCPU**：`ContinuousLCD` 在每次按键后 1.5 s 内以 60 Hz 发送 QMP `screendump`，频繁锁住 QEMU Big Lock（BQL）暂停单核 TCG vCPU，同时以 ~55 MiB/s 反复读写 `/out/lcd-continuous.ppm`。
4. **按键走 PL011 串口往返**：每次按键都经过 `stdin -> PL011 UART -> guest shell/inject-key -> console.log -> inotify` 往返，叠加 `usleep(20000)`。

### 1.2 能否直接模拟硬件屏幕接入索尼固件？

在 Sony ILCE-7CM2（α7C II）双芯片架构中，LCD/EVF 物理面板、VDF 视频合成器与 LIRO 显示驱动均归属 **CP 协处理器**，Linux AP 端并不存在 `/dev/fb0` 或标准 DRM/KMS 硬件显示驱动；AP 侧的真实“硬件显示边界”就是将 `640×480 RGBA4444` OSD 帧渲染到 DDR 物理地址并通过 OSAL UIPC 队列 `0x8280074d / 0x8280084d / 0x8280084e`（命令 `0x1002 / 0x1003 / 0x1005`）提交给 CP。

因此，**直接消费 AP 的 `0x1003` OSD DDR 缓冲区并在宿主侧合成输出，本质上就是模拟 CP 的虚拟硬件显示合成器**——无需任何 guest 临时文件、无需 `ramfb-viewer` 进程、无需 QMP `screendump`，也不改动原厂内核或重编 QEMU 二进制。

## 2. 方案（三项高收益优化，零 QEMU 重编）

利用 `os.memfd_create` 创建匿名稀疏 guest RAM（24 GiB 逻辑长度，零磁盘/零 `/tmp`/零 `/dev/shm` 落地文件），通过 `pass_fds` 传入 `bwrap` 与现有 `qemu-system-aarch64` 的 `-object memory-backend-file,id=fast-shm-ram,size=24576M,mem-path=/proc/self/fd/<fd>,share=on`。在既有预留 DDR 窗口 `memrsv=0x00900000@0x41e100000:uc`（对应 `memfd` 偏移 `0x3de100000`，长度 5 MiB，不碰 `0x41e600000` 处的 `sd-window-export`）中规划共享内存 ABI（[`fast-shm.h`](../../runtime/analysis/fast-shm.h)）：

| 相对偏移（`0x41e100000 +`） | 大小 | 用途与方向 |
| --- | --- | --- |
| `0x000000 .. 0x12bfff` | 1,228,800 B | 保留原 `ramfb` slot 0（兼容旧路径） |
| `0x130000 .. 0x210fff` | 921,600 B | `playback_bg_rgb`（640×480 RGB24，Guest 解码 JPEG 直写 -> Host 读取） |
| `0x220000 .. 0x300fff` | 921,600 B | `custom_cmos_rgb`（640×480 RGB24，Host 直写 -> Host 显示 & Guest 拍照读取） |
| `0x310000 .. 0x3a5fff` | 614,400 B | `osd_rgba4444[0]`（Ping 帧缓冲，Guest `hosd_capture_frame` 直写） |
| `0x3b0000 .. 0x445fff` | 614,400 B | `osd_rgba4444[1]`（Pong 帧缓冲，无撕裂双缓冲） |
| `0x450000 .. 0x45ffff` | 65,536 B | `struct fast_shm_ctrl` + 64 槽位无锁 SPSC 按键环 |
| `0x4ff000 .. 0x4fffff` | 4,096 B | 保留 `RAMFB_DMA / RAMFB_CFG` |

具体改动：

1. **优化 #1（消除 Guest 同步 VFAT `/tmp` 热路径）**：
   - [`headless-osd.c`](../../runtime/analysis/headless-osd.c) / [`headless-osd.h`](../../runtime/analysis/headless-osd.h)：注册 `hosd_fast_sink` 后，`0x1003` 直接从索尼锁定帧缓冲单次拷贝 614 KiB 到共享内存 Ping/Pong 槽位并原子发布，跳过 `malloc`、FNV 哈希与 `/tmp/headless-osd-frame.bin` VFAT 写入；`0x1005` 仅在拍摄态切换时发布标志，零像素拷贝。
   - [`gui-model-store.c`](../../runtime/analysis/gui-model-store.c)：`MENU_FAST_SHM=1` 时保留启动首包（`packets == 1`）写入 `/tmp/gui-model-state.bin`，`packets >= 2` 纯内存更新，彻底消除索尼 UI 线程上万次同步 VFAT 阻塞。
   - [`ramfb-viewer.c`](../../runtime/analysis/ramfb-viewer.c)：`MENU_FAST_SHM=1` 时直接正常退出（`return 0`），不抢占 TCG CPU、不写 `/tmp/ramfb-viewer.{log,status}`。
   - [`virtual-cmos-capture.c`](../../runtime/analysis/device-models/virtual-cmos-capture.c) / [`menu-observe.c`](../../runtime/analysis/menu-observe.c)：回放 JPEG 解码直写 `playback_bg_rgb`、自定义 CMOS 拍照直读 `custom_cmos_rgb`、快门闪烁仅原子递增 `blink_seq`，全面移除 `/tmp` 临时文件。
2. **优化 #2（Host 原生 x86_64 合成，零 QMP `screendump`）**：
   - [`fast-osd-blend.c`](../../runtime/analysis/fast-osd-blend.c) 编译为宿主原生库 `fast-osd-blend.so`（`-O3 -shared -fPIC`），在宿主 CPU 上以 <0.25 ms 完成 `RGBA4444` over `RGB24`（与 `ramfb-viewer.c` 全部 65,536 像素值逐像素一致）。
   - [`continuous_lcd.py`](../../runtime/analysis/continuous_lcd.py) / [`original_cold_live.py`](../../runtime/analysis/original_cold_live.py) / [`run-original-cold.py`](../../tools/run-original-cold.py)：`A7C2_FAST_SHM=1` 时直接轮询共享内存状态并合成 RGB24 推送至 GTK，零 QMP `screendump`、零 `.ppm` 临时文件、并在宿主原生执行 55 ms 快门黑屏闪烁。
3. **优化 #3（共享内存无锁 SPSC 按键环 + 瞬时 CMOS 切换）**：
   - [`menu-observe.c`](../../runtime/analysis/menu-observe.c) 在 `AppFw` 进程内启动 `fast_input_worker` 线程，消费共享内存环中的 `EVENT` / `TAP` 命令并直接调用 `real_allocate_msg / real_set_source / real_send_msg(0x5503e0)`，自动触发既有 `INPUT_EVENT32` 与 `virtual_input_observed`（拍照、APO1 唤醒、MSS 重载）。
   - [`fast_shm.py`](../../runtime/analysis/fast_shm.py) 提供 `FastShmAppInput`（兼容 `PersistentAppInput` 接口并在未就绪时自动回退串口）；[`menu_live.py`](../../runtime/analysis/menu_live.py) 的 `cmos_source` 直接将 640×480 RGB24 写入共享内存（~20 ms 完成，替代原 4s+ 串口 Base64）。
   - 保持 `A7C2_RAM_MODE=1`（RAM 快照迁移会话）自动关闭 `fast_shm`、设置 `A7C2_FAST_SHM=0` 可随时回退原链路，且不修改 `qemu-system-aarch64` 二进制（`usb-device-build.json` 与 `ram-state-build.json` 摘要保持有效）。

## 3. 验证结果

### 3.1 Host 独立验收（2 工作线程，4 检查组，4/4 通过）

- `fast_shm_and_stream`：**31 passed, 6 subtests passed**（包含 C/Python ABI 偏移校验、65,536 种 RGBA4444 全量逐像素等价性测试、`ContinuousLCD` SHM 流与快门闪烁、`FastShmAppInput` 环与串口回退、`gui-model-store` & `headless-osd` 零 VFAT 行为）
- `control_cold_and_input`：**251 passed, 11 subtests passed**（`test_menu_control.py`, `test_original_cold_boot.py`, `test_app_input.py`, `test_key_injection.py`, `test_input_bindings.py`）
- `camera_ui_xvfb`（Xvfb `1920x1080x24`）：**55 passed**
- `c_headless_ramfb_and_shell`：`bash -n`、`HOSD_COMPLETE_READBACK_AND_FAILURE_PRESERVATION_PASS`、`RAMFB_TEST_PASS`

### 3.2 隔离实机 QEMU 端到端基准测试（`run-l_dk8is3`，收据见 [`live-verification-receipt.json`](live-verification-receipt.json)）

| 指标 | 优化前（旧链路） | 优化后（Fast-SHM） | 提升 |
| --- | --- | --- | --- |
| 完整冷启动到首帧 | ~45–55 s | **13.57 s** | ~3.5× |
| 8 步首次开机向导 | ~25–35 s | **5.16 s** | ~5× |
| 菜单方向键 `DOWN`/`UP`（按键到屏幕更新） | ~500–2,000 ms | **59.6 ~ 76.4 ms**（`ack 20.2 ms`） | **10× ~ 25×** |
| 关闭菜单返回取景器（`MENU`） | ~500–1,500 ms | **51.3 ms**（`ack 20.3 ms`） | **10× ~ 25×** |
| 打开主菜单（`MENU`） | ~800–2,000 ms | **143.7 ms**（`ack 20.2 ms`） | **6× ~ 14×** |
| 自定义 CMOS 画面切换 | ~4,000+ ms（串口 Base64） | **20.3 ms** | **~200×** |
| 进入回放（无黑边解码） | ~800–2,000 ms | **51.7 ms**（`luma 150.0/147.0/146.31`） | **~15×** |
| `/tmp/headless-osd-frame.bin` 落盘次数 | 每帧一次（数百至数千次） | **0 次** | 100% 消除 |
| QMP `screendump` 次数 / `.ppm` 临时文件 | 15~60 Hz 持续写入 | **0 次 / 0 文件**（1,646 采样，45 变化帧） | 100% 消除 |

全流程同时验证了自定义 CMOS 拍照（`DSC00001.JPG`, `source=custom`, `readback=1`）、原生回放无 1:1 黑边、原生删除（`VIRTUAL_CMOS_NATIVE_DELETE_DONE flush_rc=0`）与正常关机 4 GiB FAT32 SD 导出（`4,294,967,296 B`，实占 `10,067,968 B`，`fsck.fat -n` 返回 `0`）。

## 4. 伴随发现并修复：蓝牙启动竞争（`scr0039_0002`「系统出错」）

在持久化磁盘二次启动且启用 `fast-shm` 提速后，实机操作暴露出一个既有竞态：

- **现象与证据**（`run-miz6safi` 及持久 `nflasha10` 中的 `/bt-launch-780.log`）：`start-bt-virtual.sh` 后台执行 `/simulation/virtual-hci --virtual-rom > /tmp/virtual-hci.pty &` 时，父 shell 抢在子进程截断 `/tmp/virtual-hci.pty` 之前读到了上一次启动遗留的 `/dev/pts/0`，随即 `test -c /dev/pts/0` 失败打印 `BT_TTY_NOT_CHARACTER` 并 `exit 1`，导致 `bsa_server` 未启动；固件连续 12 次 `killall -0 bsa_server` 失败后触发 `INFRA_NOTIFY_BLUETOOTH_ERROR`（事件 `0x0100012e`）并锁定在 `scr0039_0002`（「系统出错」）。
- **修复**：
  - [`start-bt-virtual.sh`](../../runtime/analysis/start-bt-virtual.sh)：改为按 PID 独立文件 `/tmp/virtual-hci-$$.pty`，启动前先清理旧 `.pty`，并轮询等待直到读到 `/dev/pts/*` 且 `test -c "$BTDEV"` 成立后再启动 `bsa_server`。
  - [`persistent_storage.py`](../../runtime/analysis/persistent_storage.py)：`runtime_reset_commands()` 新增显式清理 `/tmp/virtual-hci.pty /tmp/virtual-hci.pid /tmp/bsa-virtual.pid /tmp/bsa-virtual.log`。
  - [`test_virtual_hci.py`](../../runtime/analysis/test_virtual_hci.py)：新增回归测试 `test_start_bt_virtual_avoids_stale_pty_race`（51 passed, 8 subtests passed）。
- **实机复验**（`run-7ydpb8_i`，在含旧 `.pty` 的隔离克隆盘上启动）：`bt-launch-781.log` 成功拉起 `bsa_server`（PID 794），`virtual-hci` 正常完成 33+ 条 HCI 交互（含 `VHCI_DIAG 07f000`），原厂客户端打印 `bsa_cl_mgt_init`，全程 0 次 `BT_ERROR_PLACE line=4454`、0 次 `scr0039_0002`。

## 5. 伴随实机六项回归修复与二次冷启闭环验收（2026-11-23）

在 `fast-shm` 全功能联机测试（原始失败现场保留于 `run-miz6safi`、`run-8mdpvpxx`、`run-had8fz92`）中定位并根除了 6 项显示、输入、状态机与持久化缺陷：

1. **Bug 1（画面撕裂/错层与长按快门黑屏）**：
   - `1a`（`PLAYBACK_BG` 泄漏至首次开机向导、主菜单、关机页，及首帧 OSD 前误增 `osd_seq`）：[`menu-observe.c`](../../runtime/analysis/menu-observe.c) 的 `vcmos_clear_playback_bg()` 在每次离开回放页（含 `PLAYBACK -> MENU`）及 `fast-shm` 启动初始化时无条件清零 `FAST_SHM_FLAG_PLAYBACK_BG`；[`headless-osd.c`](../../runtime/analysis/headless-osd.c) 仅在收到 `0x1003` 首帧像素后递增 `osd_seq`。
   - `1b`（55 ms 快门黑屏闪烁误用休眠前旧状态 & GTK 帧竞态）：[`continuous_lcd.py`](../../runtime/analysis/continuous_lcd.py) 在 55 ms 闪烁休眠结束后重新采样当前 SHM 帧；[`camera_ui.py`](../../runtime/analysis/camera_ui.py) 新增 `_lcd_idle_lock` 串行化 `_notify_lcd` 与 `_read_frame`，避免 `lcd_idle_pending` 丢帧或半帧覆盖。
   - `1c`（长按快门 `0x1005` 将 `hosd_meta_is_shooting` 置 `0` 导致取景黑屏与跳过拍照）：[`headless-osd.h`](../../runtime/analysis/headless-osd.h) / [`headless-osd.c`](../../runtime/analysis/headless-osd.c) 新增 `hosd_set_screen_liveview(int)`，使 `scr0132_0001` 拍摄态不再被 `0x1005` 误降级，`0xa7` 拍照与取景始终保持活跃。
2. **Bug 2（回放按快门退出后按键/拨盘锁死 & `AppFw` 队列满卡死）**：
   - `2a`（`PLAYBACK -> SHUTTER_HALF / FULL SHUTTER` 锁死 `PLAYBACK / MODE / MENU / DIALS`）：无 CP 完成回执时，`AppFw` 全局事件过滤器 `*(appfw_base + 0x7e4ea90)` 滞留 7 个 `mask=0x10` 锁定组（`0x305, 0xf4, 0x1c6, 0x1c3, 0x1c7, 0x1c5, 0x2a`），同时回放态属性 `prop 0x183`（`0x7e5d650`）、`prop 0x252d`（`0x7efcfb0`）、`prop 0xf65`（`0x7e82120`）滞留为 `1`，在索尼抑制图中直接抑制 `aperture(0x3ba7) / shutter(0x3ba1) / progshift(0x39d4)`。修复：在 `S1` 释放且离开回放后，经索尼原生线程安全接口 `0x250f108` 解除滞留过滤锁，并经索尼原生线程安全 setter（`0x2af05d0 / 0x2bdf1e0 / 0x2b63c18 / 0x2bdeb04`）与抑制图提交函数 `0x24cb320` 复位。
   - `2b`（高频 `PLAYBACK + UP` 或输入爆发时 `fast_shm_send_app32` 在 `osal_valloc_msg_wait(..., wait=1)` 永久阻塞）：改为非阻塞分配并配有限次退避重试，避免拖死 `fast_input_worker` 与 `AppFw`。
3. **Bug 3（`OFF` 关机后 LCD 残留关机前最后一帧）**：
   - [`camera_ui.py`](../../runtime/analysis/camera_ui.py) 在 `state in ('disconnected', 'exited')` 时清空 `self.pixbuf` 并将 LCD 区域绘制为深色黑屏 `(8, 11, 12)`，新增回归单测于 [`test_camera_ui.py`](../../runtime/analysis/test_camera_ui.py)。
4. **Bug 4（每次 `OFF -> ON` 重复弹出首次开机向导 `scr0099_0001`）**：
   - `sequence_clock::run_i`（`0x306f494`）在向缺失 CP RTC 服务执行 `osal_snd_sync_msg(0x80900141)` 前阻塞，导致未清除 `prop 0x1a76`（`0x7eda8d0`）、`prop 0x1bd`（`0x7e5df40`）且未落盘 `Backup 0x02cf0014=0 / 0x01070140=0`。修复：[`menu-observe.c`](../../runtime/analysis/menu-observe.c) 在 `virtual_clock_ctor_enter` 仅接管 `cmd == 0 || cmd == 2`（忽略启动期 `cmd == 1`），由 `vcmos_worker_main` 清零两项模型属性、调用非阻塞 `0x35aae70(0)` 并执行 `Backup_sync_subsystem(0x02cf / 0x0107)` 读回确认 `bkp14_rc=1 bkp14=0`。`reset_configuration` 仍恢复出厂首次向导。
5. **Bug 5（回放 `DELETE/C2` 及按 `REC` 后 `DELETE/C2` 失效）**：
   - 按 `REC`（`0x1f0`）在无 CP 停录回执时留下事件过滤组 `[0x274:0x1, 0x273:0x1]` 以及模型属性 `prop 0x34d`（`0x7e67fe8 = 1`），导致 `0x179a518`（`0x17a1eec`）在事件路由层将回放 `DELETE/C2` 按下事件 `0x021f0007` 改写为 `0x20000001` 吞掉（而松开事件 `0x021f0008` 仍穿透）。修复：在 `REC` 松开及切换至拍摄/回放页时，经索尼原生线程安全 setter `0x2b034c8 / 0x2b033f8`（及 `prop 0x22a / 0x22f` 的 `0x2af46ac / 0x2af4b4c`）复位并调用 `0x24cb320` 提交抑制图。
6. **Bug 6（`M/A/S/P` 模式下光圈/快门/程序偏移前后拨盘）**：
   - 经上述抑制图复位后，首次进入、`PLAYBACK -> FULL SHUTTER` 6 轮循环后、`PB -> MENU -> PB_EXIT` 后以及二次冷启（Boot 2）后，前后拨盘在 `M/A/S/P` 全模式均即时响应。

### 5.1 独立验收记录（2026-11-23）

- **Host 独立验收（2 工作线程，4 检查组，4/4 通过）**：
  - `fast_shm_and_stream`：**32 passed, 6 subtests passed**（新增 `test_fast_shm.py` 针对 `fast-shm` 队列与状态标志回归测试）
  - `control_cold_and_input`：**251 passed, 11 subtests passed**
  - `camera_ui_xvfb`（Xvfb `1920x1080x24`）：**55 passed**（含 OFF 关机黑屏像素读回验证）
  - `c_headless_ramfb_and_shell`：`bash -n`、`HOSD_COMPLETE_READBACK_AND_FAILURE_PRESERVATION_PASS`、`HOSD_STALE_PART_SKIP_PRESERVATION_PASS`、`RAMFB_TEST_PASS`
- **隔离实机 QEMU Boot 1 + Boot 2 端到端全量验收（`ALL_6_LIVE_CHECKS_PASSED!`）**：
  - **Boot 1**（`run-qgfp1dr3`，冷启 `18.60 s`）：全部探针 `rc=0`；首次向导 `PLAYBACK_BG=0`；向导完成后 `VIRTUAL_CMOS_CLOCK_SEQ_DONE seq=0x83 cmd=0 clk_model=0 dt_model=0 sync_2cf=0 sync_107=0 bkp14_rc=1 bkp14=0`；`M/A/S/P` 拨盘 10/10 通过；快门连拍 6/6（含 `4.5 s` 长按，全程 `FLAG_SHOOTING=1`、`caps=1`）；`PLAYBACK -> FULL SHUTTER` 6/6 轮全部自动解除 7 组事件锁与 `p183/p252d/pf65=1->0` 且每轮后 `MODE + FRONT` 拨盘即时响应；`PLAYBACK -> MENU` 清零 `PLAYBACK_BG`（`flags=0x0`）且退回拍摄后拨盘可用；`PLAYBACK + UP` 15/15 零卡死（`sent=113, ack=113, rc=0`）；回放 `DELETE/C2` 正常弹出 `scr7110_0018` 并完成 `VIRTUAL_CMOS_NATIVE_DELETE_DONE`；`REC` 连按 2 次后再进回放按 `DELETE/C2` 正常弹出 `scr7110_0018`；正常关机落盘。
  - **Boot 2**（`run-m4d3rvto`，同一持久盘二次冷启 `12.97 s`）：直接进入 `scr0039_boot -> rep_boot -> rep_shooting -> scr0132_0001`，完全跳过 `scr0099_0001` 首次向导，`flags=0x1`（`PLAYBACK_BG=0, FLAG_SHOOTING=1`），`MODE=M` 前拨盘立即可用，正常关机退出。

## 6. 边界与剩余事项

- `A7C2_RAM_MODE=1`（QEMU RAM 迁移保存/恢复会话）继续使用原匿名内存与 QMP 路径，以保持 `ram.qevm` 迁移合同不变。
- `fast-shm` 仍属 AP 软件 OSD + 宿主虚拟 CP 合成模型，不代表物理 CP/ISP 硬件实机验证；`REC` 物理录像写盘仍待独立 CP 编码管线实现，当前修复保证误触 `REC` 不会污染后续回放删除或拨盘状态。
