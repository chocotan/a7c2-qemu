# A7C II 固件 QEMU 启动源码包

在 Linux 桌面上，用自己的 **ILCE-7CM2 2.01 ALLLANG `BODYDATA.DAT`** 启动原 Sony 内核和相机应用，显示原软件 LCD、操作菜单并保存虚拟 SD。当前仍是研究模拟器，**尚不能通过原固件拍出照片或录制视频**。

本目录可以整体搬走，运行路径由脚本位置推导，不需要旧研究目录或符号链接。Git 仓库包含两阶段 QEMU 补丁、完整 DTC、项目设备模型和辅助源码。**QEMU 源码由使用者自行下载：[qemu-11.1.2.tar.xz](https://download.qemu.org/qemu-11.1.2.tar.xz)**，放入 `source/vendor/`；固定 SHA 和详情见 [下载说明](source/vendor/README.md)。不分发 Sony 固件、原厂库/字体、真实设备 setting 或已生成程序。首次准备会在被忽略的本地目录生成这些资产，勿把整个工作目录直接打包公开。

## 首次准备、构建和启动

先安装下节列出的宿主依赖，自行下载上述 QEMU 归档到 `source/vendor/qemu-11.1.2.tar.xz`，所有命令在本目录执行：

```bash
./tools/check-host.sh
python3 tools/check-source.py
./start.sh --bodydata /path/to/BODYDATA.DAT --prepare-only
./build-qemu.sh
./start.sh --bodydata /path/to/BODYDATA.DAT
```

`/path/to/BODYDATA.DAT` 换成自己的文件。也可以把文件放入本目录 `incoming/bodydata/BODYDATA.DAT`，以后只需 `./start.sh`。从其它工作目录调用入口也可以。

`--prepare-only` 只解密、解包、校验官方版本与固定资产、安装 ALLLANG 默认配置和字体，**不编译任何程序，也不启动 VM**。版本、地区或资产摘要不匹配就拒绝；改文件名不能绕过校验。原输入只读，解包缓存按输入 SHA 命名，再次启动会复核缓存。损坏的缓存和失败 staging 会留存并报告，不静默覆盖。

`build-qemu.sh` 从使用者下载的 `source/vendor/qemu-11.1.2.tar.xz` 离线构建整机 QEMU、用户态 QEMU、libfdt、dtc 和板级 DTB；验证归档及补丁应用前后 SHA。编译阶段使用 bubblewrap 无网络环境，构建后会运行 QEMU 冒烟测试再安装到本目录。它不会安装宿主依赖或隐式调用 pip 下载。构建脚本完整执行会启动测试 QEMU；需要只检查源码时使用 `tools/check-source.py`。

常规启动会使用本机 Clang/LLD，针对已导入的原 glibc ABI 编译 guest observer 和辅助程序，再生成 cpio。首次出现机身窗口后按 **ON**，等待原固件进入语言首设；自行选简体中文、设置日期并进入 HUD/MENU。初始时钟为原默认 `2023-01-01`。窗口中的按键状态和“待验”说明代表各自已知边界。

## 宿主依赖与资源

当前目标环境为 **Linux x86_64、Python 3.12+、X11/Xwayland 桌面**；其它平台未验收。构建和运行均用普通用户，bubblewrap 需要可用的用户/挂载/网络命名空间。

| 用途 | 显式依赖 |
| --- | --- |
| Python 运行 | Pillow、PyGObject/GTK3、pycairo 和 PyGObject cairo 支持、`pycryptodomex`（`Cryptodome`）或 `pycryptodome`（`Crypto`） |
| QEMU 构建 | C/C++ 编译器、Python、Ninja、Meson（至少 1.5）、Make、Flex、Bison、pkg-config、patch、bubblewrap、flock；QEMU 版本需要的 Python 构建模块由系统预先提供 |
| 图形开发库 | GTK3、SDL2、pixman、glib2、libseccomp 的开发文件 |
| guest 助手构建 | Clang、LLD、AArch64 glibc 头文件，当前脚本查 `/usr/aarch64-linux-gnu/include` |
| 导入和虚拟卡 | e2fsprogs/debugfs、dosfstools/fsck.fat、cpio、util-linux、coreutils、Bash |
| 主机测试 | pytest；完整图形自动验收另需 Xvfb、xdotool、ImageMagick |

请通过发行版包管理器或自己准备的离线 Python 包安装；入口从不自动下载。`requirements.txt` 仅记录两个可用 pip 管理的运行依赖，不包含 GTK 系统组件。fwtool 的解密/归档代码和 FAT 子集已经随包提供；不要求另行 clone、真机 USB 工具或完整系统 dump。

QEMU 归档自身随附 Meson 1.11.1、pycotap 1.3.1、qemu.qmp 0.0.6 的离线 wheel；configure 可用这些文件建立本地 venv。宿主仍须提供 Python 的 pip、setuptools≥44.1.1、wheel≥0.34.2；`--disable-download` 和无网络构建环境禁止退回在线获取。

本次本地验证使用了被忽略的 `runtime/analysis/vendor/host-python/` 内已有 PyCryptodome 扩展；该目录不属于公开源码清单。将包搬到新机器前须安装上表的加密依赖，不能假设此扩展会随源码发布。

建议 4 核运行、8 核构建、32 GiB RAM，以及至少 20–30 GiB 可用磁盘。QEMU 的 24 GiB 参数用于覆盖 Sony 高物理地址的稀疏映射，实际驻留与内存提交策略有关，未做最低内存配置验收。构建保留独立 `source/build/`，运行保留每次 `menu-runs/`，会继续增加占用。`start.sh` 默认将临时文件放在 `runtime/tmp/`（也替换环境中的 `/tmp`），可用 `TMPDIR` 指定自己的其它可写目录。

为满足 Unix socket 的 108 字节路径上限，隔离以太网运行还会建立一个 `/var/tmp/a7c2-usb-<本次后缀>` 短链接，退出时清理；只允许复用当前用户同一 run 的链接，不覆盖其它文件。

## 关机、保存与下次继续

在机身窗口按 **OFF** 或关闭窗口，等待固件刷新、冻结导出与校验结束再退出；保存失败会报告并保留运行，勿直接强杀当作保存成功。保存的卡是虚拟 FAT 普通文件，不是宿主物理卡。

```bash
./start.sh --bodydata /path/to/BODYDATA.DAT \
  --sd-image /path/to/previous-run/SD/card.img
```

默认新卡为 128 MiB FAT16；同窗口 OFF→ON 会继续使用已保存卡。跨进程运行要显式传入 `--sd-image`。卡导出成功以 `SD/export.json` 的刷新、恢复、完整摘要及 fsck 结果为准；初始语言页的卡可能尚无数据库。菜单数据库写入不是拍摄完成的证据。

自定义固件覆盖使用普通文件的 guest 相对路径：

```bash
./start.sh --overwrite-dir /path/to/overwrite
# 例如 overwrite/usr/lib/appFw.so 对应 guest /usr/lib/appFw.so
```

覆盖只派生本次启动 cpio，原始输入/基础资产不变，记录替换前后 SHA。拒绝路径穿越、符号链接等特殊条目。自定义库可能使固定地址探针失效，启动成功不证明兼容。`--sd-image` 也拒绝物理块设备和链接。

| 本地输出路径 | 内容 |
| --- | --- |
| `runtime/bodydata-cache/<SHA>/` | 解包缓存、成功身份/清单；失败 staging 单独保留 |
| `runtime/analysis/menu-root/`、`unpacked/` | 官方包派生的启动根与内核输入，不可公开打包 |
| `runtime/analysis/menu-initramfs.cpio` | 本机生成的启动镜像 |
| `runtime/analysis/menu-runs/run-*/SD/` | 导出的 `card.img`、`export.json` 和验证材料 |
| `runtime/analysis/menu-runs/run-*/`、`ui-runs/` | 串口、快照、模型及输入证明；快照不是照片 |
| `runtime/sources/` | 本地安装的 QEMU、libfdt、dtc，构建产物默认忽略 |
| `source/build/`、`source/build-programs.sha256` | 构建目录和本次程序摘要 |

## 已支持与未实现

下表“基线已验”指打包前同一源码路线的已有验收。本包已完成主机检查、prepare-only、自身 QEMU 的独立构建/安装，并实际复验 **单 GTK 相机窗、简中首设、原 HUD/MENU 和 SD 保存**。网络开关及跨运行卡回载另行验收。新目录自己的记录见 [validation/README.md](validation/README.md)。

| 功能 | 当前范围 |
| --- | --- |
| 官方 BODYDATA 导入/安全 overwrite | 基线已验；本包实测导入、原输入校验及全部字体安装 |
| 原软件 LCD 640×480、单 GTK 机身窗 | 本包 VM 已复验；LCD 由原应用绘图提交消费 |
| 简中首设、原 HUD 与 MENU | 本包 VM 已完成首设并显示原 HUD、中文 MENU，main 已直接核画面 |
| 主要按键/拨盘 | 输入链和菜单导航基线已验；送达不等于各拍摄业务已完成，未知码保持禁用/待验 |
| 单物理槽虚拟文件卡、原 Fsys 读写 | 本包已验原数据库/XML 写入、Flush、整卡导出、摘要和 fsck；跨运行回载继续复验 |
| 隔离 USB 以太网 | 默认 UI profile 初始 OFF；基线同 VM ON/OFF/ON＋SD 保存正常退出已验；源码包含 sysbus xHCI 补丁 |
| 原固件照片/视频生成 | **未实现/未验收**：CMOS 真实像素消费与完整编码链未闭合 |
| 镜头、AF 合焦、完整曝光 | **未完成**，不以输入 ACK 或虚拟状态代替实际消费 |
| 原固件驱动宿主声音 | **未实现**；WAV 资源导出不能算播放 |
| 配置跨 VM 保存、“销毁并重新初始化” | **未接入完整 UI/VM 验收**；随附 store 的 host 测试不能代表此功能完成 |
| SD 动态热拔插 | **未完成 guest/UI 验收**；只有 Ccore/adapter 修正及 owner/dest 分离的 host 验证源码 |
| 真实无线关联 | **未实现**；虚拟网络为隔离 host–VM USB 以太网，没有真实 Wi-Fi 芯片 |
| CP3006 与其它设备合同 | **未接管/仍缺若干实际消费合同**；不强写门禁，不伪 ready/ACK 美化显示 |

启动方式是原内核＋实验 cpio＋修改的 QEMU virt 板，并不模拟 BootROM/安全启动完整冷启动链；部分缺失硬件 initcall 被明确排除，十个 IMDB 实验服务掩码被导入器修改。AP 软件绘图的 RGBA4444/source-over/nearest 实现也不保证与实体硬件逐像素相同。所有实验只使用普通虚拟文件、隔离网络和本地 socket，无真实相机、SD、物理磁盘或宿主 TTY 直通。

## 源码、测试和故障定位

```text
start.sh / build-qemu.sh / import-assets.sh
runtime/analysis/       启动器、GTK/UI、guest 助手、设备模型、fixtures、测试
source/vendor/         QEMU 下载说明；使用者下载的固定归档忽略
source/dtc/            完整 DTC/libfdt 源码及许可证
source/*.patch *.json  两阶段补丁和 before/after 身份
analysis/qemu-control/  兼容的本机网页控制界面源码；默认入口使用 GTK
tools/                 依赖检查、无构建源码校验、限定 host 测试
validation/            本包验证报告；原始验证日志仅本地保留
```

```bash
python3 tools/test-host.py
sha256sum --check SOURCE-SHA256SUMS
```

限定 host 测试不要求 Sony 资产、构建 QEMU 或 guest 助手；显式跳过需要 libfdt/DTB/固件字节的三项集成检查，并拦截编译器与 QEMU 子进程。其余原有 C/guest/图形集成测试保留在源码中，供构建后按各脚本前提运行；请勿把全部 `test*.py` 当作纯主机测试一次执行。

`./start.sh --help`、`./build-qemu.sh --help` 可以查看入口边界。缺命令/模块先修复宿主依赖；缺 QEMU 或 DTB 先构建；wrong asset/hash 错误先确认 **2.01 ALLLANG** 和输入未变；namespace 或 DISPLAY 错误检查 bubblewrap 权限、桌面与认证。保持失败日志及返回码，不通过改固定 hash、强制 ready 或关闭安全检查继续运行。

完整来源、修改记录及许可边界见 [SOURCES.md](SOURCES.md)、[THIRD-PARTY.md](THIRD-PARTY.md)。`SOURCE-ORIGINS.json` 记录所选原文件 SHA；`SOURCE-SHA256SUMS` 记录本包交付源码 SHA，均不包含 Sony 派生产物。

本包已完成独立构建及相机启动、中文菜单、SD 保存复验，其它功能继续串行核验，见 [validation/README.md](validation/README.md)。
