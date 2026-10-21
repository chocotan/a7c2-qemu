# 本包验证记录

## Settings 源码移交与本包动态复验

本次从 `final/a7c2-re/report/2026-10-17-qemu-native-camera/runtime/analysis/` 选择移交 settings helper、snapshot/restore、实例租约与 GTK 重初始化接线。未复制整个 runtime，未引入 SD 热插拔、portgate 或改变本包 RM/filemedia/SD Flush 路径；保留 `/var/tmp` 安全 socket alias 与无关文件保护。

native 的真实 GTK 三轮 `run-zacu447o`、`run-k43fdxy7`、`run-qjk1g9iz` 已由 main 核验 SD/settings/restore/reset，后台112/110项与GTK27项测试证据属于 native，**不能计作本包已运行**。真实菜单语言25/日期格式2跨 VM 原API读回属于有限参数验收；完整2390264字节 Backup 的双 bank checksum、guest 独立 SHA、QMP/FNV 与实例 CAS 发布不能证明全部 SID 已提交。首设完成状态仍未持久化，完整设置、成像和声音继续未验。

本包接线为：启动持同一实例租约并严格 load，私有 cpio 两 seed 恢复；OFF 顺序为配置 snapshot→SD 保存→配置 CAS 发布，任一失败保留 VM；OFF 退出后确认 reset，成功发布墓碑后才启动。默认保留 SD 与配置历史；跨进程 SD 仍由 `--sd-image` 显式选择。源码移交阶段只做受限 host 检查，没有编译或启动 VM；main 的后续包内动态结果见下节，不将两个阶段混为代理自己已做全部验收。

`python3 -B tools/test-host.py` 实际返回0：**259 passed、33 skipped、71 subtests passed**。新增 settings checkpoint/instance 用例使用本包本地官方 seed 通过；生命周期用例使用小型 Python 子进程检查跨进程排他，出现一条多线程 `fork()` 弃用警告。无 DISPLAY 的 GTK 控件用例（含新增重置两项）明确 skip，不能将此计作 GTK 复验。另通过 Python AST、修改脚本 Bash 语法与 `git diff --check`。自然 GTK 输入驱动强制使用本次输出目录下的独立实例根，避免继承用户实例路径。

### main：本包真实 GTK 保存、恢复和重置通过

main独立复核了选择性移交diff和五份配置运行源码身份，确认没有SD热插拔runtime、portgate或SD插拔按钮，也未改变原RM/filemedia实现和安全短socket alias；随后重新执行受限host suite，仍为259 passed/33 skipped/71 subtests。代理的隐藏旧项目和Sony资产布局另为237 passed/55 skipped/71 subtests；跳过项与原固件/显示依赖有关，不扩作动态结果。

实际三轮运行使用本包自己的production `camera_ui.main`、默认launcher、新编译的guest helper、已安装QEMU和私有实例。main逐项核selected-initramfs helper身份、原配置独立guest SHA/QMP文件、配置代与两seed恢复清单，实际xdotool点击ON/OFF及确认按钮，没有使用stub后端或替换运行器。

| run | 实际行为 | 配置文件 SHA-256 |
| --- | --- | --- |
| `run-0dcczdbi` | 空实例首次保存，配置代 `dc443d86f18f48f6b97ab5715321ff97` | `29b5c7d43721ba2117371aa61b48741730c9730a1ce3d20703c9425bf0be81f6` |
| `run-h3lr1ci5` | 从上一代两seed恢复后保存，代 `328c9858632946f5985240d84a217333` | `dd9d778f825979b835b5a394823580adbac751957fdae7a0d203eae64c5f1c42` |
| `run-56a6nn27` | 真实确认框接受后reset，启动manifest不载旧配置，恢复默认后再保存 | `29b5c7d43721ba2117371aa61b48741730c9730a1ce3d20703c9425bf0be81f6` |

main直接查看确认框截图：当前实例路径、恢复默认/重走首设以及SD/原固件/overwrite/历史代/运行资料保留范围均可见。实际reset代 `b08f1ef888124e9db2378d3353084f51` 是逻辑墓碑，两个旧backup代保留。第三次启动SD seed与重置前卡摘要一致，三份实际SD整卡SHA均为 `61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727`，独立fsck全部0、原Flush全部0、owner全部恢复，每轮正常退出。最终实例锁可重新获得。

本机原始输出为忽略文件 `validation/main-settings-gtk.log`，第三run的`main-package-settings-review.json`保留有限main核验。此三轮配置值为默认语言1/日期3，证明实际GTK保存/恢复/重置交互；native另有真正原菜单25/2改值并跨VM恢复的有限证据，两者不混为本包本轮也重新操作25/2。首次设置完成状态、全部SID提交覆盖、拍照/录像/AF/音频仍未完成。原native首轮GTK第二次SD导出被SIGTERM中断的失败和未知来源没有被这轮包内成功改写。

本记录保留首次独立源码打包、主机检查与官方包准备结果，并追加 main 的后续验收。**本包已复验独立构建、单 GTK 相机窗口、中文首设、原 HUD/MENU、SD 保存、后端网络开关和两轮跨运行卡回载。** 全部实验限定普通虚拟文件与隔离网络。旧路线 VM 结果仍只作为 README 中标注的基线状态；照片/录像等未完成功能见下文边界。

## main 后续构建验收

本包自己的 `./build-qemu.sh` 已返回 0，并安装到本包 `runtime/sources/`。编译和测试在共享运行锁释放后串行执行，未使用旧交付目录的 QEMU 程序。

实际输出包含 `QEMU_NATIVE_INPUT_PASS`（真实 QMP/device/socket 路由、按住去重、未知按键及正常退出）、GTK 显示后端、`qemu-aarch64 version 11.1.2` 和 `HOST_LIBFDT_SYMBOLS_PASS`；已安装 GTK/SDL/none 显示支持。DTC 编译有上游 const 警告，板级 DTS 有时钟/GPIO phandle 警告；构建未据此失败，也不将这些警告解释为相机硬件仿真通过。

本机安装摘要由被忽略的 `source/build-programs.sha256` 保存：

| 安装产物 | SHA-256 |
| --- | --- |
| 整机 QEMU | `f8ac2b3033dcf193570f54417d8fe478b76b39e8a46d862f6db76de0ca709695` |
| 用户态 QEMU | `137e06877ed4b7ed273f86372eaef0e29d8410b6f497eeb85b03399dfd93336b` |
| libfdt | `b1eb40b61c1d1d8db2d63d407964d11887278d2636baf1a9ccce390950d7b750` |
| dtc | `c6af532ed9d576f6add3877ab3c91242f0936908936e4dcaf5ef9e92b9eac68a` |
| 派生 DTB | `bb1248f5b1338b37ba125a0033a378ad1b319f912405bac34fee859f3c64a20c` |

上述为本机这一轮构建的程序身份，不要求其它主机复现相同程序 SHA。相机实际启动、中文首设、MENU、SD 保存、网络和跨运行回载需各自观察；下文首次打包时“未编译/未运行”的记录保留其当时范围。

## main 后续相机启动验收

在本包 `runtime/analysis/` 执行：

```bash
python3 -u check-natural-gtk-input.py --new-ui --firstboot --simplified-chinese --export-sd
```

主会话在全项目单 VM 锁下运行，使用本包新构建程序，先核 `source/build-programs.sha256` 全部匹配。实验 run 为 `run-0wfqbd6k`；自动化返回 0、`automation_completed=true`，但原 `gtk-input-proof.json` 的总体 `ok=false` 保留，未将“自动化执行结束”当作相机全部功能成功。

main 直接查看本轮 PNG，另在该 run 建立限定范围 `main-ui-review.json`：

- `gtk-simplified-chinese-selected.png`：原语言页清楚显示简体中文被高亮。
- `gtk-window-shooting-after-setup.png`：唯一 1360×930 GTK 机身窗中显示原 640×480 拍摄 HUD；场景仍为黑色，不能认作 CMOS 图像。
- `gtk-window-menu-stable.png`：原中文 MENU 可见，第 2/57 页、快门速度标题和相机参数图标；实际鼠标/按键经已有控制链操作。

原 Fsys Flush 返回 0，32 个 4 MiB guest/QMP 导出块逐段摘要匹配。main 再次从磁盘读取 134217728 字节卡镜像计算 SHA-256，与 export 完全一致：`23bc64afc94b54990edced3123d5b5d77bda9d19126fd73bf5c0acd200d6ce80`。独立 `fsck.fat -n` 返回 0（11 files、4732/65399 clusters），owner 恢复有确认；关闭时再次保存同样摘要。

FAT 内容解析得到原应用生成的 `/PRIVATE/DATABASE/DATABASE.BIN`（9670656 字节）和 `/PRIVATE/M4ROOT/MEDIAPRO.XML`（406 字节）。这些数据库/XML 是文件系统和卡写入证据，不是照片或视频。此轮不包含 Wi-Fi 实际切换、跨运行恢复、动态插拔、配置保存或合焦；相应字段在人工限定 review 中保持 false。

本轮原始输出保存在本机忽略文件 `validation/main-ui.log`，截图、原自动结果、SD 和限定 review 留在该 run。下述首次准备阶段的记录不覆盖这些新增结果，也不会因后续通过而抹去先前失败。

## main 后续网络与卡回载验收

独立包自己的 `menu_control.VM(native_display='none', natural_boot=True, usb_net=True)` 运行两轮；`card_seed` 依次指向前一个 run 的完整导出。本次走同一后端结构化队列，未在这两轮另做 GTK 开关鼠标点击。程序、kernel/DTB、网络代码均来自本包，不使用 scratch QEMU 或旧研究树的运行模块。

在 `run-0hlybhgn` 的同一个 VM 中执行 ON/OFF/ON：首次 ON 接口 UP、地址实际配置，宿主收到本次匹配 echo reply（200.08 ms）；OFF 接口 down，同一个 peer 的新探测无回复；再次 ON 收到新的匹配回复（200.10 ms）。三项 `ok=true`，实际记录保存在该 run 的 `wifi-events.jsonl`。每次 ping 使用递增序号和随机 nonce，旧应答不能当作新成功。这里是隔离 USB 以太网及宿主用户态 peer ICMP，不是宿主系统路由 `ping(8)` 或真实无线关联。

卡回载链如下：

| run | 载入来源 | 完整导出 SHA-256 |
| --- | --- | --- |
| `run-0wfqbd6k` | 首轮新卡，原应用完成首设并写数据库 | `23bc64afc94b54990edced3123d5b5d77bda9d19126fd73bf5c0acd200d6ce80` |
| `run-0hlybhgn` | `run-0wfqbd6k/SD/card.img` | 同上 |
| `run-qt9k1bpj` | `run-0hlybhgn/SD/card.img` | 同上 |

main 逐项核 runtime manifest 的实际 seed 路径/摘要，再独立读取三份 128 MiB 文件计算整卡 SHA；全部一致。两份原文件内容也逐项一致：DATABASE.BIN SHA 为 `a2fa95b03216066ff002a1e106b82c3cc663e72acde5521dd9fbf7097205d1ff`，MEDIAPRO.XML 为 `cc023c33123088b583acff6d18bc546e0770643e80f1489e2edc694c41b879fa`。三份卡均再次独立 `fsck.fat -n` 返回 0，32 段 guest/QMP 摘要匹配、原 Flush 0、owner 恢复；每个 VM 正常保存退出，最初输入卡未修改。

本机原始输出在 `validation/main-network-reload.log`，有限范围人工复核在 `run-0hlybhgn/main-network-reload-review.json`。这证明本包的整卡跨运行保持，不等于相机语言等 Backup 配置持久化，也不证明动态拔插或生成照片/视频。

## 实际检查与结果

| 证据（本地日志，默认忽略） | 实际结果 | 结论与边界 |
| --- | --- | --- |
| `host-imports.log` | `HOST_IMPORTS_PASS`、`HOST_DEPENDENCIES_FOUND` | 导入器、GTK/UI、控制器、USB/SD Python 依赖可导入；使用被忽略的本地 crypto 前置依赖，未重新安装模块 |
| `source-check.log` | `OFFLINE_SOURCE_AND_BOTH_PATCH_IDENTITIES_PASS` | 核对完整 QEMU 归档 SHA、DTC 全树、native 和 USB 两阶段补丁及 before/after 身份；只提取被修改文本，无编译或 QEMU 执行 |
| `start-help.log`、`build-help.log` | 返回 0 | 入口帮助可用，未触发导入/构建/VM |
| `static-checks.log` | Python AST、Bash 语法、本地 C include 闭合通过 | 静态检查支持以 analysis 为 include 根的 device-models；不能替代 C 编译 |
| `host-tests.log` | **213 passed、31 skipped、71 subtests passed** | 新目录主机测试，包含新增 `/var/tmp` alias 与无关文件保留测试；跳过显示/真实运行证据/构建依赖检查 |
| `prepare-only.log` | 安装 1291 项资产，字体校验通过，`BODYDATA_PREPARED` | 只读现有官方 2.01 ALLLANG 输入；所有派生产物只写新目录被忽略区域 |
| `relocated-prepare-only.log` | `CACHE_VERIFIED`、输入/字体/runtime 校验通过、`BODYDATA_PREPARED` | bwrap 将新包绑定到 `/mnt/package`，把整个原项目路径隐藏；输入单独只读绑定。准备代码无旧路径依赖 |
| `relocated-source-only-tests.log` | **209 passed、35 skipped、71 subtests passed** | 同样隐藏原项目，并额外隐藏 menu-root/unpacked/bodydata-cache；虚拟临时区隔离。验证无 Sony 资产/构建产物也可跑限定 host suite |

导入的官方输入 SHA-256 为 `eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31`；未把输入本身复制到源码清单。成功缓存和 native-assets 清单由导入器保留在本包被忽略区域。本轮再次核对所选原文件 SHA，原来源文件没有变化。

三个集成用例在 `tools/test-host.py` 中明确标注超出 asset-free/build-free 范围：USB 派生 DTB 的两个测试需要本地 libfdt/DTB，capture gate 原 getter 绑定测试需要原 appFw 字节（及 capstone）。它们的原测试仍保留，可由 main 在构建/准备后执行。完整测试目录中的其它 C、guest 与 GUI 测试也未在本轮执行。

## 失败记录与修正

`host-tests-initial.log` 保留首次 3 failed：libfdt/DTB 尚未构建，且测试与导入并行时原 appFw 尚不存在。修正限定 host suite 的测试范围后，相关集成检查显式 skip，不把未构建步骤写成通过。

`relocated-prepare-initial.log` 保留第一次隔离布局因只读根无法创建 `/input` 的失败；改用现有 `/mnt` 下的私有 tmpfs 后成功。

`relocated-tests-initial.log` 保留两项 USB 短别名测试在只读 `/tmp` 下失败；本包把别名迁到 `/var/tmp` 并添加“不删除无关文件”的检查。隔离复测为 `/var/tmp` 提供私有临时区，没有放宽原项目路径或资产隐藏。

fwtool SDK 在 Python 3.14 上会发出其已有正则字符串 `SyntaxWarning`，不影响本轮 prepare 成功；本包未顺手改第三方解析器。

## 复现与 main 待验证步骤

在本包根执行：

```bash
./tools/check-host.sh
python3 tools/check-source.py
python3 tools/test-host.py
./start.sh --bodydata /path/to/BODYDATA.DAT --prepare-only
sha256sum --check SOURCE-SHA256SUMS
```

重定位准备测试使用以下隔离布局；`bodydata` 换成自己的普通官方文件：

```bash
package="$PWD"
bodydata=/path/to/BODYDATA.DAT
mkdir -p runtime/tmp
bwrap --unshare-net --die-with-parent --clearenv \
  --ro-bind / / --dev /dev --proc /proc --tmpfs /mnt --dir /mnt/input \
  --ro-bind "$bodydata" /mnt/input/BODYDATA.DAT \
  --bind "$package" /mnt/package --tmpfs "$package" --chdir /mnt/package \
  --setenv PATH /usr/bin:/bin --setenv TMPDIR /mnt/package/runtime/tmp \
  --setenv PYTHONDONTWRITEBYTECODE 1 \
  python3 /mnt/package/runtime/analysis/bodydata-launch.py \
    --bodydata /mnt/input/BODYDATA.DAT --prepare-only
```

main 已完成独立构建、相机 helper/cpio 启动、单 GTK 窗/LCD、中文首设与 HUD/MENU、菜单输入、SD 保存和两轮回载、USB 后端 ON/OFF/ON，以及本包GTK配置保存/恢复/确认重置的三轮复验。照片/录像、AF/CMOS/编码、宿主声音、首设完成持久化和全部设置覆盖、SD 动态热拔插和真实无线关联继续标为未完成。

以上首次打包验证时尚未提交或推送；随后已在本目录独立 Git 仓库提交推送。源码与验证记录按目录分离，验证日志默认不随源码发布。main 的本包构建结果见上节，其它动态验证以追加结果为准。

## Git 发布准备补充

按用户最终要求，QEMU 完整归档由使用者自行下载；Git 只提供 [下载链接/固定 SHA](../source/vendor/README.md)，不提交大归档或分卷。`SOURCE-ORIGINS.json::external_inputs` 保留本地归档身份，`SOURCE-SHA256SUMS` 更新为实际 Git 源码清单。项目模型、完整 DTC、两阶段补丁和许可证均纳入 Git；没有隐式下载或 LFS 依赖。

发布前复跑受限 host suite，结果写入被忽略的 `publish-host-tests.log`；固定本地归档和双阶段补丁由 `tools/check-source.py` 再核验。官方直链 HEAD 得到 HTTP 200、content-length 141815216（`qemu-download-head.log`），未重新下载归档、执行构建或启动 VM。
