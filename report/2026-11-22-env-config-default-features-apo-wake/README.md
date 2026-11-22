# 纯环境变量配置、默认全特性启用与 APO1 自动关机单键唤醒修复

## 1. 现象与目标

1. **配置入口收敛**：原 `./start.sh`、`runtime/analysis/bodydata-launch.py`、`runtime/analysis/camera_ui.py` 存在多组命令行参数，且多个真实已实现特性默认关闭（如 Sony USB 设备端点模型默认关闭，界面点击“连接电脑”提示“本次 VM 尚未启用相机 USB 设备端点模型”）。
2. **UI 直接可控**：需要提供用户可编辑的 `a7c2.env` 默认配置文件，去掉启动入口的命令行参数，并在 UI 中直接提供功能开关（含互斥后端自动切换）。
3. **APO1 自动关机无法唤醒**：模拟器约 60 秒无操作后会触发原厂内核 APO1 省电关机（`scr0132_0001 -> scr0039_shutdown`，`id=0x309`，LCD 黑屏），此前在休眠后按任意机身按键均无法像真机一样恢复到实景取景界面。

## 2. 根因分析与证据

### 2.1 默认特性与 QEMU 构建碎片化

- 历史仓库中 Sony USB 设备模型与 QEMU RAM 恢复分别依赖不同目录的定制 QEMU 构建，且 `start.sh` 默认未开启 USB 设备端点模型。
- 统一构建单一全特性 QEMU 产物 `source/build/qemu-EJjB4N/build/qemu-system-aarch64` 并通过 `source/build/qemu-EJjB4N/usb-device-build.json` 与 `source/ram-state-build.json` 复用。

### 2.2 APO1 省电自动关机后无法唤醒的 3 层根因

1. **缺少休眠后按键唤醒链路与活动定时续期**：
   - 在实景取景正常操作期间，向 App32 队列注入按键不会自动重载真实内核 60 秒 MSS 省电定时器，需调用原厂 `appFw+0x34da608` 续期（`APO_MSS_RELOAD`）。
   - 进入 `scr0039_shutdown`（`0x309`）后，按任意机身键需要通过 UPM 队列 `0x80920021` 发送 `cmd=0x920142`（`factor=8`）触发原厂切入 `scr0039_boot`（`0x308`），随后发送取消关机完成事件 `0x01000090`。
2. **`scr0039_boot::process_power_on` (`appFw+0x209dd68`) 在 Group 0 上死锁**：
   - 冷启动阶段 `sequence_boot`（`0x2a`）在完成其 promise 后，使 Group 0 工作线程永久驻留在后续 `CameraBackground` 尾部。
   - APO1 唤醒再次进入 `scr0039_boot` 时，`process_power_on` 看到 `*(u32*)(appFw+0x7e5d498) == 0 && *(u32*)(appFw+0x7e5d428) == 0`，再次调用 `0x2731660 -> 0x272ef3c -> 0x272ffa4` 排队 `sequence_boot`（`0x2a`）并在 `0x272ffb0`（`EventWaiter::wait`）上永久死锁 UI 线程。
   - 同时 `boot_info[0]` 必须保持 `2`（普通启动），而 `cancel_key`（`appFw+0x7e5df08`）需为 `0x1b`，且首次设置完成后（`date_time_set_status` `appFw+0x7e5df40 != 2`）需清零 `clock_force_settled`（`appFw+0x7eda8d0`），`process_power_on` 才会沿其内置暖恢复路径（`s498 != 0`）跳过重复 `0x2a` 并打开 `rep_boot`（`0x347`）。
3. **`rep_boot` (`0x347`) 因休眠清零的媒体就绪标志而延迟挂起**：
   - 反汇编 `rep_boot_controller::open_screen_or_defer`（`appFw+0x205f144`）及其门控 `can_open_next_screen`（`appFw+0x205eecc`）证实：离开 `rep_boot` 进入 `rep_shooting`（`0x343`）要求单卡槽就绪标志 `*(u8*)(appFw+0x7e5d3a8)`（属性 `0x16f`）非零且媒体状态 `*(u32*)(appFw+0x7e5d0f8 + 40)` 为 `1` 或 `2`。
   - APO1 进入 `scr0039_shutdown` 时，关机序列 `appFw+0x2743ef0` 会将 `0x7e5d3a8` / `0x7e5d3c8` 清零（真机期望冷启动 `sequence_boot` 重新挂载 SD 卡后置 1）。在 QEMU 暖唤醒中虚拟 SD 卡（`A:/`）从未卸载，实机日志实测 `pre=[0,0,1,0,0]` 证实了该字节被清零。
   - 另修复关机阶段 `id == 0x5503e0 && code == 0x20f` 路径下调用 `file_media_flush_pending_fn()` 与 `start_sd_ack_retry_worker()`，消除 APO1/boot 屏期间关机可能出现的 `SD_FSYS_ABSENT`。

## 3. 实施改动

1. **纯环境变量配置与 `a7c2.env`**：
   - 新增根目录 [`a7c2.env`](../../a7c2.env)，统一维护所有可编辑开关与路径参数；`start.sh` 自动加载（已导出的外层环境变量优先级更高），并移除 `start.sh`、`runtime/analysis/bodydata-launch.py`、`runtime/analysis/camera_ui.py` 的全部 CLI 参数（传入任意参数即返回退出码 2）。
2. **默认开启全特性与 UI 功能开关栏**：
   - 默认启用 Sony USB 设备模型（`A7C2_ENABLE_USB_DEVICE=1`）、省电自动唤醒（`A7C2_AUTO_WAKE=1`）、虚拟镜头 HUD / CMOS（`A7C2_VIRTUAL_LENS_HUD=1`）、虚拟蓝牙 HCI ROM（`A7C2_VIRTUAL_HCI=virtual-rom-v1`）与持久化设置盘（`A7C2_USE_PERSISTENT_STORAGE=1`）。
   - 在 `runtime/analysis/camera_ui.py` 增加直接可见的“功能开关”控制栏，支持勾选切换各项特性，并自动处理 USB 设备模型与 QEMU RAM 会话的互斥切换。
3. **APO1 暖唤醒修复（`runtime/analysis/menu-observe.c`）**：
   - 在 `create_screen` 进入任意活跃非休眠界面时，通过 `apo_snapshot_live_media_state()` 快照真实运行期媒体就绪标志（`0x7e5d3a8`、`0x7e5d3c8`、`0x7e5d0f8+40/+152`、`0x7efd110`）。
   - 在 `apo_boot_evt_wrapper`（挂钩 `appFw+0x209f300`）仅于 APO1 暖唤醒时临时置 `s498=1`（返回后恢复原值）、保持 `cancel_key=0x1b`、首次引导完成后清 `clk=0`，并恢复休眠前已证实的媒体就绪标志，使 `scr0039_boot -> rep_boot -> rep_shooting -> scr0132_0001` 原生贯通。
   - 同步更新 `SOURCE-SHA256SUMS`、`report/camera-input-coverage/source-pins.json`、单元测试与 `README.md`。

## 4. 验证结果

完整结构化证据见同目录 [`live-verification-receipt.json`](./live-verification-receipt.json)。

### 4.1 宿主机 2 线程独立验收（4 组全通过）

- 线程数：`2`；检查组数：`4`；通过：`4/4`，失败：`0`：
  - `group1_bodydata_and_fastboot`（1.35s）：纯环境变量解析、CLI 参数拒绝（退出码 2）、`a7c2.env` 默认加载与快速启动控件测试通过。
  - `group2_menu_control_and_input_pins`（5.12s）：`menu_control` 开关逻辑、源码摘要钉扎校验通过。
  - `group3_camera_ui_xvfb`（38.09s）：Xvfb 下 `CameraUI` 功能开关栏、USB/RAM 互斥切换与交互测试通过。
  - `group4_cold_boot_usb_and_entrypoints`（1.71s）：`original_cold_boot`、`sony_usb_device`、`start-menu.py`、`start.sh` 入口测试通过。

### 4.2 隔离 QEMU 实机闭环验收（`run-avrxz4lc`，全部 6 项通过）

使用独立克隆的临时存储盘（未改动 `persistent-storage/default/`），开启 `a7c2.env` 默认全特性启动：

1. **默认开启 USB 设备模型**：`usb-context.json` 存在，`usb_ui.action(run_dir, 'status')` 正常返回 `phase=blocked, code=gadget_not_ready (VBUS absent)`，不再出现 `device_backend_not_enabled`。
2. **MSS 省电定时器续期**：活跃操作触发 `OBS APO_MSS_RELOAD n=1 rc=0`（共 8 次均 `rc=0`）。
3. **真实 60 秒 APO1 自动关机**：实景取景（`01-before-apo.png` 平均亮度 `126.5`）静置 58.0 秒后自动切换 `scr0132_0001 -> scr0039_shutdown`（`APO_SLEEP_ENTERED`），`02-apo-sleep-black.png` 平均亮度 `0.0`（纯黑）。
4. **单键原生唤醒回实景取景**：单次按下 `SHUTTER_HALF` 后 **0.9 秒**内完成：
   - `APO_WAKE_TRIGGERED -> APO_WAKE_UPM_SENT rc=0 -> scr0039_shutdown -> scr0039_boot`
   - `APO_WAKE_COMPLETE_SENT ack_rc=0 event=0x01000090 mss_reload_rc=0`
   - `scr0039_boot -> rep_boot`，`APO_BOOT_WARM_RESUME_DONE pre=[0,0,1,0,0] post=[1,0,1,0,0] saved=1`
   - `rep_boot -> rep_shooting -> scr0132_0001`（`APO_WAKE_RESUMED`），`03-after-wake.png` 平均亮度 `126.45`（完整实景色卡与 `1/125 F4.0 ISO AUTO` HUD 恢复）。
5. **唤醒后交互正常**：按前拨轮与 `MENU` 正常进入 `scr0132_0001 -> rep_menu -> scr7001_1003`（`04-post-wake-menu.png` 显示原生中文主菜单“快门速度 2/57”）。
6. **干净关机与存储持久化**：`vm.close()` 在 **2.08 秒**内完成 `SD_FSYS_FLUSH rc=0` 并安全退出。

## 5. 清理与空间账本

按精确白名单核查全部可读 `/proc` 与 `/sys/block/loop*/loop/backing_file` 以及 inode 内外硬链接计数后，仅回收本任务产生的 10 个验证运行目录（`run-kv4s_9_y` 至 `run-avrxz4lc`）及 `runtime/tmp/verify-apo-usb/`（共 11 项，0 阻塞）：

- **本任务实际回收分配字节**：`2,558,832,640` 字节（约 `2.38 GiB`；逻辑长度 `12,958,766,403` 字节）。
- **文件系统可用空间变化**：回收前 `987,802,316,800` 字节 → 回收后 `990,361,477,120` 字节（净增 `+2,559,160,320` 字节，剩余 `922.35 GiB`）。
- **保留的正式产物**：统一全特性 QEMU 构建 `source/build/qemu-EJjB4N/build/qemu-system-aarch64`（供默认启动与 USB/RAM 切换消费）及重编后的 `runtime/analysis/menu-observe.so`（供主模拟器启动消费）。未触及 `persistent-storage/default/` 与历史验证目录。
