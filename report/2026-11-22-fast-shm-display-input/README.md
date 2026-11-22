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

## 4. 边界与剩余事项

- `A7C2_RAM_MODE=1`（QEMU RAM 迁移保存/恢复会话）继续使用原匿名内存与 QMP 路径，以保持 `ram.qevm` 迁移合同不变。
- `fast-shm` 仍属 AP 软件 OSD + 宿主虚拟 CP 合成模型，不代表物理 CP/ISP 硬件实机验证。
