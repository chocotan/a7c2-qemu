# 启动流程 02 · QEMU 装配：从控制台窗口到 guest shell

本篇覆盖索引第 2–5 步：GTK 控制台如何拥有一台 VM、运行器如何自检重建、
QEMU 命令行如何拼出、原内核如何启动到串口 shell。
变量约定见[索引](README.md)；下列命令没有在本次整理中执行。

## 1. 控制台窗口拥有一台 VM

入口 `camera_ui.py::main` 只做两件事：构造 `menu_control.VM`
（`native_display='none'`、`natural_boot=True`、`usb_net=True`、绑定持久实例），
再把它交给唯一的 GTK 窗口。没有 shell、没有第二个显示后端、没有 HTTP 服务。

- 实例：`settings_instance.default_instance` 指向 `runtime/analysis/camera-instances`，
  持有配置代数与历史运行资料（详见 [08-settings](08-settings.md)）。
- 启动：`VM.start()` 起后台线程 `_run()`，先拿实例租约，
  再建 socketpair 作为控制通道（guest 侧固定继承为 fd 20，`MENU_CONTROL_FD`），
  防止与 `run-menu-probe.sh` 自用的 fd 9 冲突。
- 环境：`start-menu.py::profile_environment(natural_boot=True)` 生成自然启动 profile——
  先**清掉**所有继承的 `MENU_*`/`QEMU_*`/`SONY_*` 研究开关，再逐项显式打开
  headless OSD、软件 LZ77、GPE RGBA4444、原语言字体、GUI 模型、RM 文件媒体、
  日期/音频/HDMI 服务等。隔离 USB 网络与派生 DTB 是另外的 opt-in 透传。

完成标志：控制通道收到 `{type: ready, run, sd_card}`，UI 进入 `running`。

注意：profile 故意不接受"继承的环境变量"，历史教训是裸调用与正式入口行为不同，
导致开关静默丢失；所以每个能力都要在 `profile_environment` 里显式列出。

## 2. 运行器自检与重建

`run-menu-probe.sh` 在任何 QEMU 之前执行：

1. `flock` 占用 `.menu-probe.lock`（fd 9），防止两台 VM 并发踩同一运行目录。
2. 传入了虚拟 SD 镜像（`A7C2_SD_IMAGE`）时，先用 `sd_transport.card_source`
   做宿主侧来源校验（普通文件、非符号链接、空间余量）。
3. 存在 `native-assets.json` 时先 `prepare-assets.py --check-runtime` 复核已安装资产。
4. 默认重建观测器 `menu-observe.so` 与实验 initramfs
   （`build-observers.sh` + `prepare-menu-initramfs.sh`）。

完成标志：打印 `rebuilt observer + initramfs`。

注意：`SKIP_REBUILD=1` 存在但默认不用——忘记重建会让旧观测器假装是干净实验，
阴性结果全部作废。这条纪律来自实际事故。

## 3. 启动前身份核算

`qemu-menu-probe.py` 在拼命令之前先核算"这次要进 guest 的每一个关键文件"：

- 逐个比对 SHA256：`appFw.so`、`libObj.so`、`libgpe.so`、观测器、字体、
  DMM 配置、媒体/音频库、seed 文件等；对不上直接拒绝启动。
- 观测器二进制必须与本次构建输入清单（`observer-build-inputs.json`）一致，
  防止"源码改了、库里是旧的"。
- 写本次运行的 `runtime-manifest.json`，建 `menu-runs/<run-id>/` 输出目录。

完成标志：manifest 落盘且全部身份检查通过；任何一项不符则没有 QEMU。

## 4. DTB 修补与装载布局

`qemu-kernel-probe.sh` 负责把"通用 virt 板"修成原内核能接受的布局：

1. 自然启动走高 DDR 布局：DTB 装载 `0x400002000`、内核 `0x400080000`、
   initrd `0x440000000`，由 `-device loader` 固定地址写入。
2. 用 libfdt 直接改 DTB：更新 `/chosen` 的 bootargs 与
   `linux,initrd-start/end`，使 DTB 描述与实际 initrd 一致；
   检查静态 iomap 虚拟区间不重叠，重叠即拒绝启动。
3. bootargs 组合：`ramdisk_size` 按实际 initrd 大小计算；cpio 根用 `rdinit=/init`；
   从固件 `kemco.txt` 提取 `memrsv=` 工作区保留段；按 profile 追加
   CP 缓冲、scanout、媒体后端等保留窗口；最后接
   `initcall_debug initcall_blacklist=…` 黑名单跳过未建模的硬件初始化
   （高 DDR 布局下 OTG 不再黑名单，因为 GPIO 已有寄存器backing）。
4. 内存配置 `-m 24576`：历史高地址 backing 需要，**不是**实体相机 RAM 容量。

完成标志：修补后的 DTB 写入运行目录；`QEMU_PREPARE_ONLY=1` 可只做到这里。

注意：原内核不认普通 `virt -append` 覆盖——console 曾出现
`invalid cmdline override @ 0x400001000`，命令行回落到 DTB。
所以 bootargs 必须写进 DTB，不能只改 QEMU 参数。装载地址表不能混搭，
厂商 `loadaddr.txt` 的 `0x408000000` 是另一套布局，不是上行别名。

## 5. 沙箱与 QEMU 命令行

实际进程由 `bwrap` 隔离后启动：

```text
bwrap --unshare-all --die-with-parent --new-session --clearenv \
      --ro-bind /usr /usr --proc /proc --dev /dev --tmpfs /tmp \
      --ro-bind <工具链> /tools --ro-bind vmlinux.bin /kernel.img \
      --ro-bind <initrd> /initrd.img --bind <输出目录> /out ...
  qemu-system-aarch64 \
      -machine virt,secure=off -cpu cortex-a35 -smp 1 -m 24576 \
      -nodefaults -monitor none -serial stdio -nic none \
      -no-reboot -sandbox on -qmp unix:/out/qmp.sock,server=on,wait=off \
      -kernel /kernel.img -initrd /initrd.img -append <cmdline> \
      -d cpu_reset,guest_errors,unimp -D /out/boot-trace.log
```

要点：

- `-nic none`：默认无网络；隔离 USB 以太网是显式 opt-in profile（见 [09-network](09-network.md)）。
- `-serial stdio` 是唯一控制台，全部 guest 输出进 `console.log`。
- QMP socket 供宿主做 pmemsave、quit、CPU 状态核查。
- UI 拥有进程组（`start_new_session`），停止时先 TERM 后 KILL 整个组。

## 6. 到 shell 的判据

initramfs 的 `/init` 只有两行有效内容：挂 devtmpfs，把 shell 接到 `ttyAMA0`。
宿主侧等 `console.log` 出现 `/ #`，25 秒不到判失败
（`Merged filesystem did not reach shell`）。

完成标志：`/ #` 出现。**注意这只证明内核与 initramfs 活了，
不证明任何相机程序、服务或模块可用**——这是下一篇的范围。

## 证据入口

- [启动故障 §3–5、§13–14](../../../a7c2-re/report/2026-10-17-qemu-native-camera/BOOT-TROUBLESHOOTING.md)。
- 本包 [QEMU 装配脚本](../../runtime/analysis/qemu-kernel-probe.sh)、
  [探针编排](../../runtime/analysis/qemu-menu-probe.py)、
  [profile 生成](../../runtime/analysis/start-menu.py)、
  [运行器](../../runtime/analysis/run-menu-probe.sh)。
- [本包验收记录](../../validation/README.md)。

## 如果你在做别的机型

装载地址、保留窗口、initcall 黑名单、cortex-a35/virt 选型都是本板具体的，
必须重新推导。可复用的是：固定地址 loader + DTB 内 bootargs 的打法、
bwrap 最小文件系统视图、"重建先于运行"的纪律，以及"到 shell ≠ 到应用"的判据分层。
