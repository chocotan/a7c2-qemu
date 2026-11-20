# CP 启动外围与原生 AP/CP 配对

整批外设、独立 RAM、原生 DMA/门铃和原 AP 配置见 [BOOT-PERIPHERALS.md](BOOT-PERIPHERALS.md)。新能力默认关闭，先完成相关实现再统一构建与两工作线程回归；源码接线阶段不计为原固件消费或完整启动通过。

本目录仍保留下面的 GPIO18 冻结基线，供已有证据和父stage复现。

## 原生配对诊断选项

`run-native-cp.py --backup full` 只在明确选择时原样加载完整官方 PP；两个 BK4 均需通过完整身份验证。输入合同及当前原CP停点见 [BACKUP.md](BACKUP.md)。

`official_loader_page_tables.py` 接受精确匹配 A7C II 2.01 官方 SHA256 的 `loader_nor.bin`（94,176 字节）或 `loader_nor.tar`，后者在内存中校验完整归档及四个原成员，不解包到磁盘。它从 `0xfe049000` 原始基址静态重建页表；不拼接缺失的 NOR 前缀，也不依赖研究目录或私有 dump。输入须能以 `O_NOATIME` 只读打开，权限不足时明确报错。报告还列出原代码初始化的每核栈顶间距和 BSS 清零范围，但不推定栈深或物理 SRAM backing；所有结果均不证明 loader 或 BootROM 曾运行，也不证明物理总线别名。该实现及官方输入路径尚待本批回归验收。

`run-native-ap.py --virtual-upm-diagnostic` 显式启用未还原的虚拟 UPM 回复及 BT 日志内存补丁；默认关闭，只用于定位，不能作为原机电源行为或完整启动证据。未知消息和布局继续交给原传输。

隔离 observer 构建使用 `build-observer-diagnostic.sh`：四个链接库先从运行根复制到新建的私有目录，并与受保护的原始 `menu-initramfs.cpio` 对应成员完整 SHA256 比对，再用于编译。原运行根库即使可被其他用户写入也不会被直接信任或修改；构建及派生启动验证使用 v2 收据，旧 v1 构建不可复用。此流程仅提供诊断，不能作为历史观察证据或完整启动验收。

`run-native-ap.py --p1-spi-component` 显式启用上游 PL022 组件及 P1 所需的 24MiB AP eDMA 预算。它不提供 SPI BootROM 对端、guest 设备树/时钟复位绑定、GPIO17:7 ready 或 CP updater，因此不声称 P1 下载、链路或安装成功。

原 P1 更新还需要它自己的 CP 更新 loader、PCIe 和 PCIDMA；暂停普通 CP 冷启动不会自动补齐这些依赖。该适配层不能替代更新 loader 或虚构其成功返回。

独立的 `p1-spi-ssi.c` / `p1-spi-ssi.h` 是默认关闭的纯 C 虚拟协议适配层，复用 `p1-spi-monitor`；其 `virtual-p1-ssi-monitor-v1` profile 仅供显式调用，不自动接入 PL022、QEMU、原更新器或产品启动入口。EXEC 仅记录请求，不执行固件。源码及其 strict/ASan/UBSan 测试已在 [非 CP host 验证](../../validation/non-cp-host-20261115.json) 中通过，两线程合批的 P1 模型组共 9 项、0 跳过；结果 SHA-256 `13f8be6ca3061fc23df4ae228067443aa0d8b9ecc823f536590f750cc6b30508`。这是合成协议组件检查，不代表原 loader 或安装通过。

`run-native-ap.py --capture-diagnostic --control-fd FD` 仅接受 pair 目录下本用户拥有且不可被其他用户写入的单链接 `capture-seed.img`（恰好 1GiB FAT16），以及同 UID 父进程持有的继承 Unix 流式控制 socket。启动器只读检查原 seed 的FAT16几何和 `fsck.fat -n`，在专属目录构造可压缩seed的派生initramfs、完整校验压缩流及解压摘要并拒绝超出固定initrd窗口；guest解压至专属可写卡后必须再次验证大小与SHA才能启动原bootin。该选项只接入原 RM 文件后端、原按键通道及 JPEG/Fsys 观察，不生成合成拍摄回复；原 CP、帧/编码、原 Fsys 和卡读回须分别取证。成功导出的 `SD/capture-export-<sequence>.json` 不可覆盖；原始卡证据适配器为 `report/native-card-write/check_raw_writeback.py`，写回/解码也不等于拍摄来源通过。

## CP GPIO18：显式功能输出 latch

此目录提供 `virtual-gpio18-loader-state-v1` 的小型寄存器核心和 QEMU adapter，供**独立 CP 启动研究**使用，默认关闭。普通产品窗口与默认 QEMU 不受影响。

模型按同 SoC Sony OSS 的 `regs-gpio.h` 实现四组 32 位 DATA/SET/CLR：DIR、INEN、PORTSEL、WDATA。虚拟 reset 定义为 0，再应用原 BK4 record ed000 的 `f9014a` 六条寄存器脚本，得到 DIR=f、INEN=f、PORTSEL=e、WDATA=2。原脚本只确定写入位；完整复位字和未写位是本功能模型约定，**物理兼容性未验证，也不证明原 NOR 已执行**。

WDATA 由原 CP 的写入保持；未实现的 RDATA、IRQ、pull、保留地址、未对齐和错误尺寸访问拒绝，不返回伪输入、link/ready 或 UIPC ACK。

## 测试

在产品根目录运行，测试材料写本项目目录：

```sh
mkdir -p runtime/tmp/cp-gpio18
TMPDIR="$PWD/runtime/tmp/cp-gpio18" python3 -B -m pytest -q -p no:cacheprovider \
  --basetemp "$PWD/runtime/tmp/cp-gpio18/pytest" \
  source/cp-boot/test_gpio18.py source/cp-boot/test_stage.py
```

C 核心测试严格编译并启用 ASan/UBSan；不依赖原固件或私有镜像。

## 冻结 CP 基板接线

`stage.py` 只接受内置两个完整 SHA 的既有 CP 诊断基板，不能直接当成 vanilla QEMU 的完整板移植。新的 `stage-platform.py` / `build-cp-native.sh` 产品路线负责从官方源码加原 native patch 重建该基板；旧stage中“private”的来源标签不要求提供私有固件或设置。它保存原两文件到 `cp-gpio18-before/`，追加三份小源码，写 `cp-gpio18-stage.json`；重复调用必须全部摘要相同，未知基准或漂移拒绝。

```sh
python3 source/cp-boot/stage.py /path/to/private-cp-qemu-source
ninja -C /path/to/private-cp-qemu-source/build-cp -j2 qemu-system-aarch64
```

仅当环境变量 `QEMU_CP_GPIO18_PROFILE=virtual-gpio18-loader-state-v1` 时接入 `0xf102f000` 的 0x100B 窗口；未知 profile 直接拒绝，未设置时不创建设备。

实际验收、原始 CP 身份、输入来源与剩余阻塞见[CP 启动专题](../../report/2026-11-11-cp-boot-progress/README.md)。不能把核心单测或一次GPIO写入提升为原接收任务、AP↔CP、固件更新或成片通过。

源码按 GPL-2.0-or-later 授权。
