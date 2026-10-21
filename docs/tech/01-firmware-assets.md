# 启动流程 01 · 固件资产：从 BODYDATA 到可启动的根文件系统

本篇讲启动链路的第 1 步：一份官方更新包 `BODYDATA.DAT` 如何变成
"可以拿去启动 QEMU"的根文件系统、内核、DTB、字体和 seed 配置。
之后的 QEMU 装配见 [02-qemu-boot](02-qemu-boot.md)。

变量约定见[索引](README.md)。本篇只回读源码与已有记录，没有执行导入、构建或仿真。

## 1. 找到唯一一份 BODYDATA

`start.sh` 转到 `runtime/analysis/bodydata-launch.py`。它先在
`incoming/bodydata/`（或 `--bodydata` 指定的位置）找输入文件：

- 路径任何一层是符号链接都拒绝；最终必须是普通文件。
- 目录里必须**恰好一份** `BODYDATA.DAT`，找不到或找到多份都报错退出。

同名文件不代表同一固件，所以选定输入只是开始，下一步立刻核身份。

## 2. 解密并固定固件身份

用包内 vendored 的 fwtool SDK 解包：

1. `dat.isDat()` 确认是 Sony DAT 容器；
2. `readDat()` 读出固件段，`decryptFdat()` 解密成 `firmware.fdat`；
3. 读取前后比对文件指纹（设备号、inode、大小、时间戳、SHA-256），
   读的过程中文件变了就放弃；
4. `readFdat()` 解析出身份，`supported()` 只接受一个元组，其余全部拒绝：

```text
model=0x20030014  version=2.01  region=0 (ALLLANG)  isAccessory=False
```

5. 固件 tar 展开成 `firmware-root/`：拒绝路径穿越、绝对路径、重复成员；
   链接和设备文件不在宿主创建，跳过并记进 `archive-skipped.json`；
   展开总量有预算，写前检查磁盘空间。

本包验收过的那份官方输入 SHA-256 是
`eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31`。

## 3. 缓存：解包只做一次，每次用都复核

解包结果按原包 SHA-256 缓存到 `runtime/bodydata-cache/<sha>/`：

- 先在临时 staging 目录里解，全部成功、写完 `success.json` 清单后
  才重命名发布；失败的 staging 保留并记 `failure.json`，不冒充成功。
- 之后每次启动都对缓存做全量清单复核（每个文件的大小和 SHA-256），
  内容变了就拒绝使用。

注意：缓存清单不是签名，它和下一步的 `native-assets.json` 是两层独立检查，
缓存通过不能跳过资产校验。

## 4. 安装资产：rootfs、身份卷、seed

`prepare-assets.py` 把解包树变成运行目录里的可用资产。官方输入的大小和
摘要全部固定在源码里（`verify_official_inputs`），包括分区镜像
`nflasha3/nflasha8/nflasha15`、ALLLANG Backup（2390264 字节）、
DmmCfg.bin、DTB、kemco.txt 等十项——setting 全部来自公开固件包，
不从研究者的相机补取。

安装动作：

- 从 ext2 格式的原 `initrd.img` 提取根文件系统到 `menu-root`，
  从 `nflasha15` 提取 `/usr`；CP 文件进 `/cp`，启动分区文件进 `/system`。
- 用 FDAT 头 512 字节生成一个 4 MiB 的虚拟身份 FAT 和
  `firmware-version.dat4`，让 guest 里的原固件能读到自己的版本号。
  这是**实验派生**的身份卷，不是相机里原始的 `nflasha1`。
- 改 `libIMDB.so`：把十项 SKIP 服务的标志位清掉（`mask &= ~7`），
  让菜单实验不需要的硬件服务不再阻塞启动。改后的库单独命名、
  单独记账，不能叫"未改动的原厂库"。
- 生成两份相同内容的 seed：`seed-backup.bin` 和 `seed-setting/Backup.bin`，
  即公开固件里的 ALLLANG 默认配置。
- 全部结果写进 `native-assets.json`（schema 2）；之后每次运行前
  `--check-runtime` 复核，通过时输出
  `CHECK_RUNTIME_PASS ILCE-7CM2 2.01 all lang`。

注意：manifest 记录的是"这些文件应该是什么样"，不是对整个 menu-root 的
白名单；构建产物等额外文件允许存在，但不因此变成可信原件。
安装过程不承诺中断后的完整回滚，失败的 staging 保留供排查。

## 5. 语言字体

首设页面要用原固件字体渲染。`language_fonts.py` 固定两份字体的
大小和 SHA-256：

| 字体 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `MYingHeiC-Big5-SJ_wIcon.ltt` | 1150740 | `25f3afa8008c6d038e5bf61582c06539a70786a2de1c74fe63e73814d468ab9f` |
| `MYingHeiC-GB18030-SJ_wIcon.ltt` | 2054740 | `a8afccc2e226d5a519f3698796c2a76a0ad6e163f7e5fc9e35d5e89d58db3276` |

安装时先校验再把官方 `tmp/images` 资源树整体复制到
`simulation/language-fonts`，目标文件只读、逐份读回核对。

完成标志：`LANGUAGE_FONTS_PASS`。
注意：字体文件就位 ≠ 原固件真的消费了字形，那要靠后面显示链的证据。

## 6. 打出实验 initramfs

`prepare-menu-initramfs.sh` 把 `menu-root` 打成原始（未压缩）newc cpio：

- 原内核没有 gzip initrd 支持，所以只能出原始 cpio；
- 写入三行的 `/init`（挂 devtmpfs，把 shell 接到串口 `ttyAMA0`）；
- 放入观测器 `menu-observe.so`、改过的 `libIMDB.so`、seed；
- 排除语音资源（屏幕朗读不在实验范围）；
- 传了 `MENU_SD_IMAGE` 时，把校验过的虚拟卡 FAT 镜像
  作为 `/simulation/sd-card.fat` 追加进 cpio，并输出其 SHA-256。

打出来的 cpio 还要过 `initramfs_identity.py::verify_image`：
不解包、不执行，直接解析 newc 格式，逐文件算 SHA-256，
和"这次 profile 应该包含的文件清单"比对，结果写进运行 manifest。
这样防止"目录里的 .so 是新的、cpio 里还是旧的"这类事故（实际发生过）。

完成标志：`rebuilt observer + initramfs`（由上一层 `run-menu-probe.sh` 打印）。

## 7. 踩过的坑

- **ELF 地址换算**：第二 `PT_LOAD` 的 VA 和文件偏移差 `0x10000`，
  曾把 VA 当偏移用，还曾让测试和被测字典共享同一份错偏移"互证通过"。
  现在一律按段表逐段换算。
- **guest ABI**：宿主编译通过不代表 guest 能加载。Sony glibc 2.25 没有
  新编译器默认的 outline atomics 和 C23 符号，helper 要加
  `-mno-outline-atomics` 和旧 ABI 声明。
- **旧路径依赖**：旧研究 rootfs 混有本机链接和配置残留。
  验收时把整个原项目目录隐藏、只读绑定官方输入，证明包能独立准备。

## 证据入口

- [启动故障 §3–5、§13–14](../../../a7c2-re/report/2026-10-17-qemu-native-camera/BOOT-TROUBLESHOOTING.md)
- [资产导入合同](../../../a7c2-re/report/2026-10-17-qemu-native-camera/runtime/analysis/ASSET-IMPORT.md)
- 本包 [导入器](../../runtime/analysis/bodydata-launch.py)、
  [资产安装器](../../runtime/analysis/prepare-assets.py)、
  [字体 pins](../../runtime/analysis/language_fonts.py)、
  [验收记录](../../validation/README.md)

## 如果你在做别的机型

DAT/FDAT、ALLLANG、IMDB 是这条 Sony 路线特有的。可复用的是方法：
固定输入身份和摘要、原件与派生物分开记账、按 ELF 段表换算地址、
核对实际打包进镜像的字节、隐藏旧路径做独立复现。
新机型先建自己的身份元组和输入清单，不要只删掉 `supported()` 的拒绝条件。
