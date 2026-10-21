# 大步骤 1：固定资产，先让原内核到 shell

这篇解决输入身份、启动布局和依赖顺序的排查，不把到 shell 或受控菜单等同于完整原机启动。

变量约定见[索引](README.md)；下列命令没有在本次整理中执行。

## 小步骤 1：确认解密的是哪一份固件

**问题 →** 同名 BODYDATA 不能说明型号、版本和区域相同。
**现象 →** 自动入口明确拒绝非 ILCE-7CM2 2.01 ALLLANG 输入。
**误判 →** 解出文件就认为它们可与已有固定地址探针混用。
**定位 →** `bodydata-launch.py` 经 DAT 读取、FDAT 解密和身份检查，再交给资产导入器。
当前身份元组是 `(model=0x20030014, version='2.01', region=0, isAccessory=False)`。

```bash
# 执行目录：$PKG；只读核身份实现，不运行导入器
cd "$PKG"
rg -n 'def supported|decryptFdat|readFdat|verify_cache' runtime/analysis/bodydata-launch.py
```

**解决 →** 原包 SHA 作为缓存键，缓存再次做完整 inventory 校验。
解包还检查普通文件、路径穿越、重复成员和空间预算；拒绝复用未知缓存。
本包已验输入 SHA 为：

```text
eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31
```

**剩余 →** 这些 pins 是特定输入的证据，不是其他机型的解密/兼容保证。
迁移时先建立自己的身份与固定清单，不能只删除 `supported()` 拒绝条件。

## 小步骤 2：把根文件系统和字体一并导入

**问题 →** 旧研究 rootfs 混有本机链接、helper 和配置残留。
**现象 →** 拷走研究目录可能依赖原路径，也可能带入设备私有配置。
**误判 →** `manifest` 能列出文件，就意味着它能自证这些文件可信。
**定位 →** 比对源码固定清单、输入 SHA、guest 链接、mode 和两份 seed。
原 initrd 与 `/usr` 从镜像提取，默认 Backup 取公开固件的 ALLLANG。
两份 seed 是 `seed-backup.bin`、`seed-setting/Backup.bin`。
六个 setting 输入也来自固件包，不从研究者相机取补充。

**解决 →** schema 2 以源码固定资产集合约束 manifest；guest 绝对链接按 guest 根解释。
十项 IMDB `mask &= ~7` 与虚拟身份卷明确标为实验派生，不叫原厂未改动文件。
字体另从 `0800_appli/tmp/images` 导入 `simulation/language-fonts`：

| 字体 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `MYingHeiC-Big5-SJ_wIcon.ltt` | 1150740 | `25f3afa8008c6d038e5bf61582c06539a70786a2de1c74fe63e73814d468ab9f` |
| `MYingHeiC-GB18030-SJ_wIcon.ltt` | 2054740 | `a8afccc2e226d5a519f3698796c2a76a0ad6e163f7e5fc9e35d5e89d58db3276` |

**剩余 →** 清单不是签名；字体存在仍需后续真实字形消费证据。
失败 staging 保留，导入器不承诺任意中断后的全量回滚。

## 小步骤 3：把实际装载关系写成一张表

**问题 →** 原内核没有按普通 `virt -append` 预期启动。
**现象 →** console 提示 `invalid cmdline override @ 0x400001000`，命令行回落 DTB。
**误判 →** 改了宿主参数就认为 guest 已采用新 bootargs；把原 initrd 当 cpio。
**定位 →** 查实际 `Kernel command line`、镜像类型及 DTB `/chosen`。
历史最小启动核验关系如下，不能混搭：

| 对象 | 本项目历史最小实验 | 含义 |
| --- | --- | --- |
| Image | `0x400080000` | 原内核装载 |
| DTB | `0x400002000` | chosen/bootargs 来源 |
| 实验 initrd | `0x440000000` | 必须匹配 DTB start/end |
| 厂商 loadaddr.txt | `0x408000000` | 另一原始布局，非上行别名 |
| 原 initrd.img | ext2 | 当前实验 rootfs 则可生成 cpio |

**解决 →** 核装载区间、保留区与 GIC 映射，最小路径实际执行到 BusyBox。
guest `uname` 为 `4.9.337-scel+ aarch64`，`BOOT_MARK_$(uname -m)` 在 guest 求值。
**剩余 →** `-m 24576` 是历史高地址 backing 需要，不是实体相机 RAM 容量。
后续大 cpio 仍可能 OOM，见[容量实验](media-state-and-capacity.md)。

## 小步骤 4：从 shell 到原应用，先修依赖再谈硬件

**问题 →** 原模块同时有 `Unknown symbol`、NULL 访问和未映射 MMIO。
**现象 →** input/ioexp/indctr/udate 曾放在 Backup 之前，indctr 又早于 ioexp。
**误判 →** 所有 insmod 失败都归为“模拟器缺硬件”。
**定位 →** 以原脚本依赖和每个模块的实际错误区分缺符号与设备访问。
**解决 →** 调整 Backup/DMM 及附加模块顺序；未建模控制器明确排除或拒绝。
USB/MMC 等缺口仍分别记账，不对缺失服务统一回成功。

guest helper 也要单独核 ABI：项目遇过新编译器 outline atomics 缺符号，
以及宿主头文件引入旧 Sony glibc 2.25 没有的 C23/fstat 符号。
修复包括 `-mno-outline-atomics`、旧 ABI 声明或已核 syscall 路径。
**剩余 →** 模块装上不证明服务数据已初始化；日期故障就是反例，见输入篇。

## 小步骤 5：证明能离开原研究目录

**问题 →** 本机启动成功可能只是旧路径或旧产物兜底。
**现象 →** 换目录、长 socket 路径或隐藏旧树后才暴露问题。
**误判 →** 打包成功等同于自包含启动。
**定位 →** 已有验收把包绑定到 `/mnt/package` 并隐藏原项目，原输入单独只读绑定。
**解决 →** 本包记录重定位 prepare-only、独立构建、实际单窗启动的分阶段证据。
`--prepare-only` 只证明准备；后来的构建和 VM 验收分别列出。
**剩余 →** QEMU 源归档与 Sony 输入仍需使用者自备，自包含不代表随包包含固件。

## 解决了什么，仍未解决什么

解决了固定官方输入、干净默认配置、字体导入、内核最小启动和包内路径依赖的限定问题。
原 bootin 的正常入口已复用；原 `dmode=3` 不是万能硬件仿真开关。
`change_mode.sh` 在参数判断前可能写文件，连 help 都不适合当无副作用检查。
其 3p 分支受原 bootin 四项库前缀表限制，不是任意 preload 文件入口。
模式分阶段启动仍属待验证方向，不能把静态脚本分支写成已跑通。

## 证据入口

- [启动故障 §3–5、§13–14](../../../a7c2-re/report/2026-10-17-qemu-native-camera/BOOT-TROUBLESHOOTING.md)。
- [资产导入合同](../../../a7c2-re/report/2026-10-17-qemu-native-camera/runtime/analysis/ASSET-IMPORT.md)。
- [开发模式核验](../../../a7c2-re/report/2026-10-17-qemu-native-camera/report/developer-modes/README.md)。
- 本包 [导入器](../../runtime/analysis/bodydata-launch.py)、[字体 pins](../../runtime/analysis/language_fonts.py)、[验收记录](../../validation/README.md)。

## 如果你在做别的机型

DAT/FDAT、ALLLANG、IMDB 和 dmode 是此 Sony 路线的具体机制。
可复用的是固定输入、分层装载、原依赖排序、旧 ABI 检查和隐藏旧路径的独立复现。
新机型先拿到 shell 的内容证据，再进入下一大步骤；不要照抄本页物理地址。
