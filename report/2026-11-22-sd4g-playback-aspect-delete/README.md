# 4 GiB 默认 FAT32 虚拟 SD 卡、回放去暗边、原生照片删除与自动强制关机修复

## 1. 现象与目标

1. **回放左右暗边**：拍摄后进入原厂播放界面（`scr7102_0001_still`），画面左右各约 107px 出现 80% 暗度遮罩及 1px 白色竖线。
2. **默认虚拟 SD 卡扩容至 4 GiB**：原默认卡为 1 GiB FAT16，升级为默认 4 GiB FAT32 稀疏虚拟卡（同时向下兼容既有 1 GiB 存档卡镜像）。
3. **回放删除卡在“正在删除”**：在回放界面按删除并确认后，界面长期停留在 `scr7110_0002`（`id=0x294`，“正在删除”）。
4. **卡住时关闭模拟器窗口无响应**：当 guest 无响应导致正常保存关机失败或超时时，关闭窗口不应继续卡住或仅弹窗滞留，而应自动降级强制关闭本窗口拥有的 QEMU 进程组。

## 2. 根因分析与证据

### 2.1 回放左右暗边（1:1 纵横比遮罩）
- 反汇编 `appFw.so` 证实：`scr7102_0001_still`（`id=0x23`）的 `view_aspect_guide`（`appFw+0x23e6f5c`）读取属性 `0x25c4` 并查表 `appFw+0x41b0840`；值为 `0` 映射为 1:1 纵横比标记（左右 80% 暗度遮罩），`>= 6` 则隐藏。
- `sequence_playback::start_playback_exit`（`appFw+0x33ce72c`）在 `0x33ceb54` 读取 `*(uint32_t *)(obj_addr + 120)` 并经 `0x2d47314` 写入属性 `0x25c4`。此前 `virtual_pb_start_playback_intercept` 未设置 `obj_addr + 120`，保持默认值 `0`。

### 2.2 4 GiB FAT32 虚拟 SD 卡及实机发现的两个关键细节
1. **BusyBox `test` 32 位整数截断**：反汇编原厂 `/bin/busybox` `getn()`（`0x442bf0: mov w0, w21`）证实其编译为 `CONFIG_FEATURE_TEST_64=n`，`[ $((offset + length)) -le "4294967296" ]` 会将 `4294967296` 截断为 `0` 导致 `install-sd.sh` 静默退出；而同二进制的 `expr`（`0x43da84`）使用 64 位 `strtoll`。
2. **FAT32 FSInfo 计数与挂载态刷盘**：`mkfs.fat -F 32` 默认在 FSInfo 扇区写入固定空闲簇数 `131038`，而原厂 `PrFILE2`（`libInfraFsys.so`）在 `Fsys_FlushVolume()` 时保持挂载不回写 FSInfo，导致导出时只读 `fsck.fat -n` 报 `Free cluster summary wrong` 返回码 `1`。按 Microsoft FAT32 规范将主/备 FSInfo 扇区的 `FSI_Free_Count`/`FSI_Nxt_Free`（偏移 `488..496`）置为 `0xFFFFFFFF`（未初始化/按 FAT 计算）后，原厂写盘与只读 `fsck.fat -n` 均稳定返回 `0`。

### 2.3 回放删除卡在“正在删除”（`scr7110_0002`）
- 确认删除后，原厂 `appFw+0x25f827c` 登记 MPR 删除目标，再调用 `appFw+0x24d1a44` 入队序列 `0x62`（`model::sequence_delete_multipul`，大小 `0x220`，`ctor=0x310e384`，`execute=0x3093a20`，`dtor=0x30931d4`）并打开 `scr7110_0002` 等待事件 `0x01000019`。
- 序列 `0x62` 映射到已被冷启动 `sequence_boot` 驻留占用的 Group 0 队列，无法被调度。反汇编证实 `sequence_delete_multipul::execute()` 100% 在 AP 端运行（调用 `libmpr.so` 的 `mpr::Delete` 与 `sidb::GetRootSet` 并经 `0x309430c` 发布 `0x01000019`，无任何 CP IPC）。

### 2.4 卡住时关闭窗口无响应
- `menu_control.VM.close()` 原先等待 `shutdown_done` 达 180 秒，且失败后 `CameraUI._close()` 仅弹窗滞留窗口；`self.closing` 期间再次点击窗口 `X` 亦被忽略；`OFF` 按钮遇到“SD保存失败；VM未关闭”后不会自动强停。

## 3. 实施改动

1. **`runtime/analysis/menu-observe.c`**：
   - 在 `virtual_pb_start_playback_intercept` 调用 `start_playback_exit` 前置 `*(unsigned int *)(obj_addr + 120UL) = 6u;` 禁用 1:1 纵横比暗边遮罩。
   - 新增 `virtual_pb_delete_trampoline` 与 `virtual_pb_delete_intercept` 拦截 `appFw+0x24d1a44`，清理回放背景缓存并唤醒 `vcmos_worker_main`（延迟 50ms 确保 `scr7110_0002` 完成挂载订阅后），原生执行 `sequence_delete_multipul`（`0x310e384`/`0x3093a20`/`0x30931d4`）与 `Fsys_FlushVolume('A')`。
2. **4 GiB 默认 FAT32 虚拟 SD 链路**：
   - 更新 `runtime/analysis/make-media-fixture.py`（4 GiB FAT32 + FSInfo `0xFFFFFFFF`）、`runtime/analysis/sparse_seed.py`（4 GiB 默认 + 1 GiB 兼容 + `SEEK_DATA`/`SEEK_HOLE` 稀疏扫描）、`runtime/analysis/sd-sparse.c`、`runtime/analysis/sd_sparse.py`、`runtime/analysis/cold/install-sd.sh`（64 位 `busybox expr`）、`runtime/analysis/rm-file-device.c`（上限 4 GiB + `> 1 GiB` 边界采样 FNV64）、`runtime/analysis/sd_transport.py` 及对应单元测试与 `README.md`。
3. **自动强制关机兜底**：
   - `runtime/analysis/menu_control.py`：`VM.close()` 正常关机等待超时从 180 秒缩短为 30 秒。
   - `runtime/analysis/camera_ui.py`：`CameraUI._close()` 与 `main()` 在 `vm.close()` 失败时自动调用 `vm.force_close()` 关闭本窗口拥有的 QEMU 进程组；等待期间二次点击关闭直接强制退出；`OFF` 遇到正常保存失败同样自动强停虚拟机。
4. 同步更新 `SOURCE-SHA256SUMS` 与 `report/camera-input-coverage/source-pins.json`。

## 4. 验证结果

完整实机结构化收据见同目录 [`live-verification-receipt.json`](./live-verification-receipt.json)。

### 4.1 宿主机 2 线程独立验收（全部通过）
- **SD / 冷启动 / 观察器 4 组（2 线程）**：`sd-sparse-and-seed`（19 passed）、`sd-export-hotplug-state`（27 passed, 27 subtests）、`cold-boot-lens-cmos-menu`（95 passed, 30 subtests）、`sd-transport-and-rm-file`（64 passed, 34 subtests），合计 205 passed + 91 subtests，0 失败。
- **UI 自动强制关机与输入钉扎 2 组（2 线程）**：`control_and_input_pins`（`test_menu_control.py` + `test_input_bindings.py` 全部通过，4.95s）、`ui_xvfb_1920x1080`（`test_camera_ui.py` 55/55 通过，38.51s）、`sha256sum -c`（全部 15 个改动文件 100% 匹配）。

### 4.2 隔离 QEMU 实机闭环验收（`run-c9t_pimr`，全部通过）
1. **4 GiB FAT32 冷启动**：`build_sd_bytes=4294967296`、`PRODUCT_SD_1G_READY bytes=4294967296`、`FULL_RM_FILE_STARTED image_bytes=4294967296`、`pb_rc=0,0,0,0,0`。
2. **双张实拍写卡**：`DSC00001.JPG` 与 `DSC00002.JPG`（各 `58,241` 字节，`rc=0`，`readback=1`）写入 4 GiB FAT32 卡并登记入库。
3. **回放全幅无暗边**：实拍回放 `scr7102_0001_still` 显示 `2/2`、`100-0002`、`3:2`，左/中/右平均亮度分别为 `138.02 / 127.85 / 116.95`，无 1:1 暗边遮罩与白竖线。
4. **两次原生照片删除**：
   - 第 1 次删除：`VIRTUAL_CMOS_NATIVE_DELETE_DONE seq=0x62 flush_rc=0`，自动退出 `scr7110_0002` 返回 `scr7102_0001_still`（`0x23`，显示 `1/1`、`100-0001`）。
   - 第 2 次（最后一张）删除：`VIRTUAL_CMOS_NATIVE_DELETE_DONE seq=0x62 flush_rc=0`，自动退出 `scr7110_0002` 进入空回放屏（`0x8f`，原生中文“没有影像。”，无残留背景图）。
5. **4 GiB FAT32 关机导出与一致性校验**：`export_ok=true`、`expected_total=4294967296`、`fsck_rc=0`、`card_allocated_bytes=10,182,656`（约 9.7 MiB 稀疏实占）、导出镜像 `DCIM/100MSDCF` 已清空（`remaining_dcim_entries=[]`）。

## 5. 清理与空间账本

按白名单核查全部可读 `/proc`、`/sys/block/loop*/loop/backing_file` 与 inode 硬链接后，安全回收本轮 6 个验证运行目录（`run-wc8qddwd`、`run-11s87oe7`、`run-qcpdxbeh`、`run-gwxgbrag`、`run-nck2ox3q`、`run-c9t_pimr`）及 `runtime/tmp/verify-sd4g-live`（0 阻塞）：
- **本轮实际回收分配字节**：`2,269,143,040` 字节（约 `2.11 GiB`；逻辑长度 `20,348,808,526` 字节）。
- **文件系统可用空间变化**：回收前 `988,002,119,680` 字节 → 回收后 `990,271,442,944` 字节（净增 `+2,269,323,264` 字节，剩余 `922.26 GiB`）。
- **保留的正式产物**：重编后的 `runtime/analysis/menu-observe.so`、`runtime/analysis/menu-root/simulation/sd-sparse` 与 4 GiB FAT32 空白镜像 `runtime/analysis/menu-root/simulation/media-camera.fat`（实占 `1.1 MiB`，供默认冷启动消费）。未触及 `persistent-storage/default/` 与历史数据。
