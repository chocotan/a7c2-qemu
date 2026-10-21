# 启动流程 03 · guest 环境：挂载、模块与服务按依赖序就位

本篇覆盖索引第 6 步：shell 出现之后、原相机应用启动之前，
宿主通过串口逐条下发的 `setup` 命令序列（`qemu-menu-probe.py` 构造）。
顺序即依赖；任一硬失败直接中止，不进入应用启动。
变量约定见[索引](README.md)；下列命令是历史实际下发序列的整理，本次未执行。

## 1. 基础挂载与运行目录

```text
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t tmpfs tmpfs /tmp
mount -t tmpfs tmpfs /setting
mount -t tmpfs tmpfs /tmp_wbshd
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
export LD_LIBRARY_PATH=/usr/lib:/lib
```

随后建 cpuset cgroup：`/dev/cgroup` 下按原固件期望建
`cpu0 cpu1 cpu2 cpu3rt cpu0_1 cpu0_1_2 cpu0_1_2_3rt` 分组并初始化 cpus/mems。
完成标志：回显 `MENU_ROOT_READY`，且 `im.elf`、`appFw.so` 在预期路径可见。

## 2. 语言字体复核

`simulation/language-fonts` 的两份原字体复制到 `/tmp/images/`，
逐份用 guest 自带 `openssl dgst -sha256` 复核——在 guest 里再算一遍，
防止 cpio 组装阶段的静默损坏。字体 pins 见 [01-firmware-assets](01-firmware-assets.md)。

## 3. IPC 与内核模块（依赖顺序即启动顺序）

模块按原 `initrc/insmod_drv2` 的依赖关系排序下发，不能按字母或顺手顺序：

1. `devno.ko` → `osal_utm.ko` → `osal_uipc.ko`：进程间通信底座，
   完成后 `/dev/uipc` 可见。
2. `utimer.ko`：Sony 定时器（对应命令行里把 hwtimer 从 initcall 黑名单移除）。
3. seed Backup 落位 `/setting/Backup.bin`，再 `insmod backup.ko Backup_load=1
   Backup_save=<0/1>`——**保存写回是显式 opt-in**，默认只载不存。
   随后 `stream.ko`、`stream2.ko`。
4. seed setting 落位 → `osal_ulogio.ko`（带 ulogio.bin）→
   `dmm.ko`（带 DmmCfg.bin）→ `grm_ma.ko`。
5. `upm.ko`：电源管理。
6. `udate.ko` + `seed-date-clock`：原日期服务初始化，
   成功才 `touch /tmp/date-clock.ready` 并回显 `DATE_CLOCK_INIT_OK`；
   失败则应用启动命令根本不会被下发。

注意：顺序是真实修出来的——input/ioexp/indctr/udate 曾排在 Backup 之前导致
`Unknown symbol`；insmod 失败也不一律是"缺硬件"，要按缺符号/设备访问分别记账。
未建模控制器（USB core、MMC、MS）明确排除或拒绝，不回成功。

## 4. 固件身份卷

原固件要读自己的版本身份。造一个虚拟 `nflasha1`：
`mknod /dev/ram1` → 软链 `/dev/nflasha1` → 把预制的 FAT 身份镜像 `dd` 进去，
并放 `firmware-version.dat4` 到 `/setting/updater/`。
完成标志：回显 `VIRTUAL_FIRMWARE_IDENTITY_FILES_READY`。

## 5. 上电种子与服务开关

- `seed-power-on <boot_type>`：用原 Backup API 写虚拟 loader 的启动类型记录
  （`QEMU_BOOT_TYPE` 默认 1，合法范围 1–8）。
- 各原服务以环境变量声明给观测器/服务层：CapID、SA 地址、HDMI 格式/照片、
  DMM 服务、显示信息、软件 GPE、headless OSD、CP 释放/时钟、加密库、
  总线电源等。每个开关对应 profile 里一项显式 `MENU_*`/`QEMU_*`。

## 6. 媒体接入

RM 文件媒体 profile 下：虚拟卡 FAT 镜像复制为 `/image_mmca`，
`file-media-config.so` 加入 `LD_PRELOAD`，把原 Fsys 的 `/dev/mmca` 路径
引到普通文件后端（详见 [07-storage](07-storage.md)）。
SD 热插拔默认开启（`A7C2_SD_HOTPLUG=1`），单槽 RM1 诊断是显式 opt-in。

## 7. 观测器自证后才启动应用

带观测运行时，先跑观测器自测与读内存工具自测
（`check-menu-observe`、`menu-regs --selftest`、readmem 正负对照），
全部通过才拼最终的启动前缀：

```text
LD_PRELOAD=<媒体配置等>:/simulation/menu-observe.so \
  /usr/bin/bootin.elf 'target=qemu ' dmode=3 > /tmp/im.log 2>&1 &
```

常驻 UI 还会把研究日志重定向到 `/dev/null`，只保留有界 OSD 导出。

完成标志：`IM_LAUNCH_PID` 回显，进入下一篇的应用启动与首设。

注意：guest helper 的 ABI 单独核过——新编译器 outline atomics、
宿主头文件带进的 C23/fstat 符号在 Sony glibc 2.25 上都缺，
修复是 `-mno-outline-atomics` 与旧 ABI 声明。宿主链接通过不保证 guest 可加载。

## 证据入口

- [启动故障记录](../../../a7c2-re/report/2026-10-17-qemu-native-camera/BOOT-TROUBLESHOOTING.md)。
- 本包 [setup 序列构造](../../runtime/analysis/qemu-menu-probe.py)、
  [上电种子源码](../../runtime/analysis/seed-power-on.c)。
- [开发模式核验](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/developer-modes/README.md)：
  `dmode=3` 不是万能硬件仿真开关。

## 如果你在做别的机型

模块清单、依赖序、服务开关、`dmode` 语义都要从原 initrc 重新推导。
可复用的是"顺序即依赖、每步有完成标志、硬失败即中止"的下发结构，
以及 seed 文件与写回权限分离（载默认开、存显式开）的做法。
