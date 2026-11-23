# 2026-11-23 本地 MP4 虚拟 CMOS 输入与视频录制写卡

## 1. 目标与诚实边界

1. **支持本地 `.mp4` / `.m4v` / `.mov` 作为虚拟 CMOS 输入**：允许在控制窗口或控制 API 选择本地视频文件，按原视频帧率解码并缩放/垫边（`#101010`）至 `640×480 RGB24` 循环写入 `fast-shm` CMOS 共享内存区，实时驱动相机取景框，同时可供静态拍照与视频录制使用。
2. **支持视频录制并经原厂 `libInfraFsys.so` 写卡**：支持取景态按 `REC`（`0x1f0`）起停录像，以及切到 `MODE_MOVIE` / `MODE_SQ` 档按全按快门（`0xa7`）起停录像；支持在切换到回放/APO 休眠或直接点击 `OFF` 关机时自动收尾落盘。生成的 640×480 H.264/MP4 分块传回 guest，经索尼原厂 `libInfraFsys.so` 写入虚拟卡 `A:/PRIVATE/M4ROOT/CLIP/C0001.MP4`、`C0002.MP4`… 并执行 64 KiB FNV-1a 读回校验与 `Fsys_FlushVolume('A')`。
3. **边界说明（软件虚拟模型 vs 物理硬件）**：
   - 因真机 CP 协处理器与专用编码硬件在 QEMU 中缺失（`original_CP=0`，[`report/virtual-video-engine/README.md`](../virtual-video-engine/README.md) 中 CP3003 门控亦未打通），本实现中的 **CMOS 帧流、H.264 视频编码与 MP4 封装均由宿主软件虚拟模型完成**（[`cmos_source.py`](../../runtime/analysis/cmos_source.py)、[`virtual-video-host.c`](../../runtime/analysis/virtual-video-host.c) 复用 `video-engine.c` 调用 `libx264` + `libavformat`），**写卡文件操作则调用索尼原厂 `libInfraFsys.so`**。
   - 为避免阻塞原厂 `sequence_playback`（静态回放调度），不写入或篡改原厂 `MEDIAPRO.XML` 与视频 `sidb` 记录。导出的 `SD/card.img` 可在宿主机用标准播放器/FFmpeg 直接播放 `PRIVATE/M4ROOT/CLIP/Cxxxx.MP4`；机身**播放**按钮仍仅回放静态照片 `DSCnnnnn.JPG`，暂不支持机内回放录像。

## 2. 实现设计与模块分工

### 2.1 共享内存控制面扩展（`fast-shm.h` / `fast_shm.py`）

保留现有 `struct fast_shm_ctrl`（`0x450000`）全部字段偏移不变，在 `0x451000` 与 `0x460000` 新增视频通道：

| 偏移（相对 `0x41e100000`） | 大小 | 用途 |
| --- | --- | --- |
| `0x451000` (`struct fast_shm_video_ctrl`) | `192 B`（4 KiB 槽） | `guest_video_ready`、`rec_toggle_seq`、`rec_stop_seq`、`rec_mode_switch`、宿主反馈 `rec_active`/`saving`/`elapsed_ms`/`frames`/`rec_hud_seq`、分块传输请求/完成寄存器与 `64 B` `guest_path` |
| `0x460000` (`FAST_SHM_VIDEO_BUF_OFF`) | `512 KiB` | 宿主向 guest 传输 MP4 分块的共享缓冲（`BEGIN / CHUNK / COMMIT / ABORT`） |

### 2.2 关键组件改动

1. **宿主实时 MP4 CMOS 推流**：
   - [`cmos_source.py`](../../runtime/analysis/cmos_source.py)：扩展 `.mp4` / `.m4v` / `.mov` 检测、`ffprobe` 元信息探测、首帧抽取，并新增 [`VideoCmosStreamer`](../../runtime/analysis/cmos_source.py) 后台守护线程调用 `ffmpeg -stream_loop -1` 按源帧率输出 640×480 RGB24（`#101010` pad）写入 `fast_shm.set_custom_cmos()`（非 `fast-shm` 兼容路线时上传首帧静态替代）。
2. **宿主录像编码与分块写卡协调**：
   - [`virtual-video-host.c`](../../runtime/analysis/virtual-video-host.c)：编译为 `virtual-video-host.so`，包装 [`report/virtual-video-engine/video-engine.c`](../virtual-video-engine/video-engine.c) 的 `video_engine_stream_*`，抽取 Annex-B SPS/PPS 并通过 `libavformat` 内存缓冲动态封装标准 MP4（上限 64 MiB，同步计算 `vcmos_fnv64`）。
   - [`video_recorder.py`](../../runtime/analysis/video_recorder.py)：实现 [`VideoRecordManager`](../../runtime/analysis/video_recorder.py)，监听 guest 写入的 `rec_toggle_seq` / `rec_stop_seq`，24 fps 读取 `read_active_cmos_rgb24()` 送入 `virtual-video-host.so`，编码结束后分 512 KiB 块提交到 guest，写入运行目录 `last-video-record.json` / `video-records.jsonl`，并通过 `Condition` 状态标记严格消除 `wait_after_rec_key()` 与 `stop_if_recording()` 启停竞态。
3. **Guest 原厂按键监听与 Fsys 写卡**：
   - [`virtual-cmos-capture.h`](../../runtime/analysis/device-models/virtual-cmos-capture.h) / [`.c`](../../runtime/analysis/device-models/virtual-cmos-capture.c)：抽取公共 `vcmos_fnv64_step`、`vcmos_fsys_write_all`、`vcmos_pick_numbered_path`，新增 `virtual_cmos_movie_{begin,write_chunk,commit,abort}`，经原厂 `libInfraFsys.so` 逐块写入 `A:/PRIVATE/M4ROOT/CLIP/C%04u.MP4`（DOS 8.3 大写兼容），提交时执行 64 KiB 读回计算 FNV-1a 校验并调用 `Fsys_FlushVolume('A')`。
   - [`menu-observe.c`](../../runtime/analysis/menu-observe.c)：在 `vcmos_worker_main` 增加 `flags & 1024u` 分发；追踪模式键 `0x71c9`，在按 `REC`（`0x1f0`）或非 STILL 模式下全按快门（`0xa7`）时递推 `rec_toggle_seq`；进入回放或 APO 休眠屏时递推 `rec_stop_seq` 自动停录。
4. **合成指示与控制集成**：
   - [`fast-osd-blend.c`](../../runtime/analysis/fast-osd-blend.c)：非破坏性地仅在取景合成输出图像左上角绘制 `● REC MM:SS` 或 `SD SAVING...` 徽标（不污染 CMOS 原帧）。
   - [`menu_live.py`](../../runtime/analysis/menu_live.py)、[`menu_control.py`](../../runtime/analysis/menu_control.py)、[`continuous_lcd.py`](../../runtime/analysis/continuous_lcd.py)、[`camera_ui.py`](../../runtime/analysis/camera_ui.py)：整合 `VideoCmosStreamer`、`VideoRecordManager`、`video_status`、`export_sd` 自动停录，更新工具栏为「选择图片/视频…」、增加录制状态胶囊与红色录像按钮高亮。

## 3. 验证结果

### 3.1 Host 独立验收（2 工作线程，6 检查组，6/6 覆盖通过）

- `group1_fast_shm`（`runtime/analysis/test_fast_shm.py`）：**9 passed**（C/Python ABI 偏移校验、REC HUD 非破坏叠加、`OP_BEGIN/CHUNK/COMMIT` 通信 roundtrip 等）
- `group2_virtual_cmos_c_asan`（`runtime/analysis/test_virtual_cmos_capture.py`，ASan + UBSan）：**1 passed**
- `group3_cmos_snapshot_controls`（`test_cmos_image_source.py`、`test_cmos_source.py`、`test_source_snapshot.py`、`test_menu_control.py`、`test_original_cold_boot.py`、`test_app_input.py`、`test_key_injection.py`、`report/camera-input-coverage/test_input_bindings.py`）：**260 passed, 23 subtests passed**（含 `source-pins.json` 全部钉扎校验）
- `group4_mp4_cmos_and_video_record`（`runtime/analysis/test_mp4_cmos_and_video_record.py`）：**2 passed**（真实循环 MP4 CMOS -> `ContinuousLCD` 帧变换；`REC` 起停 + 宿主 `ffprobe`/`ffmpeg` 帧哈希验证）
- `group5_virtual_video_engine`（`report/virtual-video-engine/test_video_engine.py`）：**22 passed**（含正常与 ASan/UBSan 构建）
- `group6_camera_ui`（`Xvfb 1920x1200x24`, `runtime/analysis/test_camera_ui.py`）：**56 passed**（含新增 `test_mp4_cmos_source_label_and_video_recording_badge`）

### 3.2 隔离实机 QEMU 端到端验收（`run-szte281y`，收据见 [`live-verification-receipt.json`](live-verification-receipt.json)）

在独立克隆存储实例上从 `ALLLANG` 首次开机向导自动推进至 `scr0132_0001` 后完成 5 步端到端验证：

1. **本地 `.mp4` 实时虚拟 CMOS 取景**：切入 800×400 测试视频循环播放，1.2 秒内 LCD 采样到 **24 个唯一帧哈希**，画面连续动态刷新。
2. **`REC` 起停录卡 `C0001.MP4`**：按 `REC` 录约 2.75 秒后再次按 `REC` 停录，guest 打印 `VIRTUAL_CMOS_VIDEO_RECORD rc=0 path=A:/PRIVATE/M4ROOT/CLIP/C0001.MP4 bytes=551210 fnv1a64=fba665141ee56039 readback=1`。
3. **同流静态拍照、原生回放与原生删除回归**：在持续播放 `.mp4` CMOS 期间连拍 `DSC00001.JPG`（24,003 B，`source=custom`）与 `DSC00002.JPG`（23,915 B），进入原厂 `scr7102_0001_still` 回放，按 `DELETE -> UP -> ENTER` 完成 `VIRTUAL_CMOS_NATIVE_DELETE_DONE seq=0x62 flush_rc=0` 并返回取景页。
4. **`MODE_MOVIE` + 快门与 `OFF` 自动停录落盘**：切换 `MODE_MOVIE` 并按 `SHUTTER` 开始第二段录像后直接调用 `vm.stop()` 关机，协调器自动停止录像并将 `A:/PRIVATE/M4ROOT/CLIP/C0002.MP4`（352,417 B、`fnv1a64=aacb288836c9db03`、`readback=1`）写卡刷新后正常退出 4 GiB 虚拟 SD。
5. **离线 FAT32 一致性与独立 FFmpeg 帧解码**：
   - `/sbin/fsck.fat -n SD/card.img` 返回 **`0`**；
   - 目录核查：`PRIVATE/M4ROOT/CLIP` 含 `C0001.MP4` 与 `C0002.MP4`，`DCIM/100MSDCF` 仅剩 `DSC00001.JPG`（`24,003 B`）；
   - 提取校验：`C0001.MP4`（551,210 B，FNV-1a `fba665141ee56039`，`h264 640x480`，`2.750000 s`，解码 **66/66** 唯一动画帧）；`C0002.MP4`（352,417 B，FNV-1a `aacb288836c9db03`，`h264 640x480`，`1.791667 s`，解码 **43/43** 唯一动画帧）。

## 4. 清理与空间账本

核查全部可读 `/proc/*/{cmdline,fd,maps,cwd,exe,root}`、`/sys/block/loop*/loop/backing_file` 与白名单内外硬链接计数后，安全清理本任务产生的隔离运行目录 `run-szte281y`、临时克隆盘目录 `runtime/tmp/live-mp4-accept-1795399131` 及 4 份当天 UI 运行日志（共 193 个文件 / 192 个唯一 inode，0 阻塞）：

- **删除前关键记录摘要（SHA-256）**：
  - `run-szte281y/console.log`（`425,664 B`）：`0c5d86c19af083a0a3b37eacca7afb6cb43e95d429490e14de37700aa5907c0d`
  - `run-szte281y/video-records.jsonl`（`646 B`）：`ff799e7fd5525ffb4d9aea73e6d65ade444623d056a99fbc2961b1c521e056f2`
  - `run-szte281y/last-video-record.json`（`363 B`）：`7203516f879ac7d1bfd09657f279e8ee219d176bc4e1a12c7d2965d46c8b1a49`
- **回收与可用空间变化**：回收逻辑大小 `12,733,157,992 B`、实占分配 `3,102,228,480 B`（约 `2.89 GiB`）；文件系统可用空间由 `986,907,561,984 B` 恢复至 `990,009,860,096 B`（净增 `+3,102,298,112 B`，余 `922.02 GiB`）。
- **保留的正式构建产物**：`runtime/analysis/menu-observe.so`、`runtime/analysis/fast-osd-blend.so`、`runtime/analysis/virtual-video-host.so` 及 `.observer-build.stamp.json`（供默认冷启与主窗口直接消费）；未触及 `persistent-storage/default/`、`camera-instances/default/` 与历史保留目录。
