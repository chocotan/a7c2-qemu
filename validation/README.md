# 本包验证记录

## 媒体只读诊断：访问器层修正

旧`media-policy`观测把5584c38表+08的基值读数标成当前媒体状态；main核原通用值读取28bb0c8走+20，与+10/+18 setter配对，+08另用于初始化/重置。102d/102e的ROM基值本来是0/30，不能据旧日志这两个数宣称运行状态没更新。原日志保留；旧数据无修订号的unsuffixed字段按+08基值解释。

修正代码同时保留`_base08`字段，将无后缀字段绑定+20，并给结果及每个事件加`media_observation_revision=2`。原指令按PT_LOAD解析，验证双层标量LDR w0/RET和实际通用API的+08/+20分发，且fake基值2/运行值1分别采到，避免仅把标签改名。原生目录与包内文件逐字节相同。

包内完整受限host在本修正后实际 **281 passed / 33 skipped / 73 subtests passed（7.75s）**，一条既有多线程fork警告；跳过项仍是该入口约定的显示/资产/构建边界。此前SD阶段记录的279/33/73保留为历史结果。

更根本的限制：名字目录给`0x1037..0x103c`的是`PRM_HAITA_..._relay_...`拼接名，而同一批键的validator范围都是`(-15,15,1)`有符号数值；`0x1052`也如此。名字目录编号与分发表/校验器键空间的同一性整体未证，`0x10xx`段已有实证冲突。因此诊断里的`prm_*`只是目录派生标签，不能当作已证的挂载/可录/容量语义；本包不据此改变任何业务判断。

同一轮还撤回一处更强的错误：分发表键`0x1052`原被标成“剩余容量”，但其两个setter的validator范围是`(-15,15,1)`，运行期由`0x103c`转接，业务入口原字符串为`set_picture_profile_black_level`；名字目录编号与分发表键的同一性未证明。该字段已从媒体表移出为`dispatch_1052_unresolved_value/base08`，只读保留、不计入容量结论，回归测试锁住范围/转接/键计算原字节。故“媒体剩余容量=0”的旧说法撤回。

原生研究的`run-6frwm5f2`实际完成正常128MiB原GUI/REC及revision2采样：64对entry/return里的值层102d/e也为0/30，与基值相同，其他10字段均0；62次223/2次ffff、LCD仍无空间。不能据此断言零值含义或整个启动没更新。main核每事件修订号、双层字段、32×4MiB guest/QMP摘要、完整卡SHA `f4bc982aae5ec7d7a986d6e2109173c7cff313f0933ab13ca818a78f04c534ae`、fsck0、原Flush/owner恢复及独立CPU运行；source未变、正常关闭、未强杀。原生实际采样与包内同源代码/host测试分别记录，不冒作本包新VM采样。

另一处改动是为了让下一步镜头/传感器工作有真实观测入口：`cp-background-device.c` 原来对非3007命令静默返回“未处理”，现在会把目标、source、type、opcode、长度记一条 `NATIVE_CP_BACKGROUND_UNHANDLED` 再原样委派回原传输——不分配、不回包、不建租约、不改所有权。新增 `observe-unhandled` 用例断言0x4063批次被记录并委派、返回值不动、请求仍归调用方所有，同时覆盖短包；两棵树同一字节、用例通过。这**只是观测**，不代表已实现镜头批次消费。

镜头初始化的下一份合同与只读复核落在 `a7c2-re/.../report/lens-init-contract/`（4073无自增generation、4063由AP发、2040内嵌2044、AP快照固定偏移无新鲜度校验）；焦距/镜头ID/挂机UI映射仍未闭合。

该变更只涉及被显式启用的只读诊断；下方已实测原SD通知、Mount/Unmount、整卡摘要和实际文件内容证据继续保持原范围。原生研究的1GiB FAT16有效输入案例已正常完成，REC仍显示无空间；这是限定案例结果，空零尾稀疏交付没有作为任意大卡载入功能移交本包。

## SD热插拔：默认profile、原通知及退休导出已通过

最新验收包括本包真实GTK两轮插拔、四状态导出、原文件内容消费，以及不显式设置hotplug变量、沿用上一卡的默认profile补验。标准RM2自然启动已默认开启，显式`A7C2_SD_HOTPLUG=0`可关闭；RM1诊断和旧菜单profile不自动开启。最新完整受限host为 **281 passed / 33 skipped / 73 subtests passed**（媒体只读诊断修正后复测）。以下保留各阶段的待验、失败、恢复及补验记录，不将阶段性“进行中”当作最新状态，也不把整体拍摄标为通过。

代理仅部分移交runtime和RM接线后结束；main已独立核diff并补齐构建、原Mount/Unmount与generation观察、在途处理、退休卷导出、控制通道及GTK按钮。原配置实例、恢复环境隔离、USB网络、`/var/tmp`短socket alias与无关文件保护保持；没有整体覆盖native树，也没有移交私有4KiB诊断preload或把诊断文件冒作照片。

本包实际针对性回归 **93 passed / 61 subtests passed（26.57s）**，覆盖SD状态/runtime/RM迟到释放、控制隔离、原Fsys、配置、网络与GTK；3172条警告来自GTK/Python弃用。随后资产无关/无VM/无构建的`tools/test-host.py`加入SD控制及退休导出测试，实际 **276 passed / 33 skipped / 71 subtests passed（7.68s）**，一条多线程fork弃用警告。跳过项遵守该入口的显示/资产/构建边界，不计为动态通过。

已准备实际production包内GTK两轮拔出/重插、每个absent/present状态后的独立导出；absent必须使用原Unmount退休证据而非新的Flush返回，导出等待本次新sequence并核owner恢复。该VM结果尚未收取，两份独立只读移交审查也未收齐，因此当前没有包内热插拔已通过或默认开启的结论。下方配置、显示、网络等既有记录各自保持原范围。

后续两份审查已交付，未发现已确认的运行代码阻塞；A发现既有`test_sd_image.py`漏链新增runtime/core。main先实际复现链接失败，再补齐测试输入和`-ldl`，整份镜像测试 **16 passed / 11 subtests passed**；不把静态审查写作执行过VM。

首轮包内`run-ocaot_1j`实际完成generation2拔出导出、generation3重插导出、generation4再次拔出导出，三次完整卡SHA均 `f42d70f32a38594d59ef4537992599c095589ac5c16f5b111e58ac240410d694`；之后第二次重插点击未确认，自动试验超时，整体失败。失败关闭期间一次`SD_REQUEST_seq`输出与内核UDIF日志同行，严格解析拒绝；owner恢复有确认，但GUI没有正常退出，按保护保留VM。不能把前三次成功扩大为两轮验收通过。

main核owned PID/目录、当前稳定absent状态及上一保存的owner-resumed后，仅通过原UI action做一次安全保存，再走原GUI正常关闭。恢复保存和最终关闭保存都保持同一卡SHA，独立fsck0，pidfd确认原GUI退出、相机进程集合为空；未重插、未SIGKILL，原失败proof保持。故障控制目录作为证据有意保留。

后续只改善标记输出为前后换行的printf，解析仍严格、受污染标记仍拒绝；真实host shell的成功/失败发布和既有取消/恢复等组合 **30 passed / 27 subtests passed**。私有GTK驱动另显式记录并等待实际widget-sensitive与busy/pending清空后点击；旧run没有记录该属性，首次点击超时的唯一根因仍未知，不以竞态猜测回填。修后包内复验及完整host复测正在单独进行，未默认开启或发布功能。

标记修正后的完整受限host复测已实际结束：**278 passed / 33 skipped / 73 subtests passed（7.62s）**，仍只有原多线程fork弃用警告。该结果包含新增真实shell发布/拒绝场景；不会将首次VM失败改成通过，包内修后动态验收仍待主会话核。

### main：修后本包两轮真实插拔与退休导出通过

`run-6o17sqe2` 使用本包production UI、正常launcher及本包编译的guest库，实际四次GTK按钮均在widget-sensitive=true、busy空、pending0后点击。generation2/4原Unmount使卷mask1→0、2→0，generation3/5原Mount绑定新盘符B/C；Front原free与终态均有对应代号，未丢事件，RemoveCnt为1/1/2/2。

每次absent/present之后均单独导出：absent明确`original_volume_retirement=true`、`original_Fsys_FlushVolume_rc=null`；present原Flush返回0。main读取四套不可变导出目录的32个4MiB块，按offset顺序重算完整镜像SHA，四者及最终关闭保存均为 `b511f810d3cf18a0f3b53367e161f5c394a0d8c24e7588d72c308b4070699b33`。后台每份fsck0，main另独立对最终同字节镜像执行fsck0；owner均恢复，自动验收正常结束。

两次重插后原AP都实际Read完整DATABASE.BIN9670656B和XML406B，返回数据FNV分别 `269a0126c48af1d8`、`9bcc48eb1e140ffb`，main直接从FAT提取全部字节重算相同。文件SHA分别 `4965312e162b3b6b1cea36703bb34846a7811da06b9406408929c4e584608a7c`、`29e3c945be9e99688310882506b4aafe9f97445d5a9f096310a2fbf1e9d914d9`。这超出Open成功证据；本轮没有私有诊断preload，不宣称生成照片/视频或自然重插后新Write。

main直接查看本轮唯一GTK拔出/重插画面，控件显示SD已拔出/已插入，原LCD卡图标相应消失/出现。原总体false proof保持，有限`main-package-sd-review.json`只对两周期、退休导出和内容read记true。首次`run-ocaot_1j`失败及恢复记录不因这轮成功改写。

本地标准RM2自然启动profile随后设为默认开启，并保留`A7C2_SD_HOTPLUG=0`退出选项；RM1诊断/旧菜单profile不自动开启。默认/optout边界、配置隔离和控制回归25tests通过，原start-menu完整隔离/锁交接脚本通过。当前另跑不显式设置hotplug变量、沿用上一卡的真实默认profile；该附加结果与最终发布状态仍待核。

### main：默认启动与上一张卡回载补验通过

`run-mgfexv9k` 的测试驱动没有强设`A7C2_SD_HOTPLUG`，标准自然启动profile自行启用。源卡明确为上一轮`run-6o17sqe2/SD/card.img`；main不只核manifest路径，还读取实际选用cpio中的唯一`simulation/sd-card.fat`，SHA与源卡完全相同。真实GTK完成一轮原卸载/退休导出/重挂载/Flush导出，两次原文件Read的完整数据FNV仍匹配源文件。

源卡、两次状态导出、最终关闭保存都保持 `b511f810d3cf18a0f3b53367e161f5c394a0d8c24e7588d72c308b4070699b33`；main独立fsck0、owner恢复、包内运行锁重新获取均通过。正常关闭无cleanup_error。验证结束后另有外部full路线VM启动，不属于本次owned实例，未干预；退出判据使用本包的正常cleanup与独立锁核验，没有把全机无任何QEMU作为必要条件。有限结果在`main-package-default-sd-review.json`，原自动总体false保留。

默认策略后的完整asset-free/build-free宿主复测为 **279 passed / 33 skipped / 73 subtests passed（7.70s）**，一条既有多线程fork警告。全部测试先于功能提交。照片/录像、真实AF/CMOS/编码、原Wi-Fi关联及全部参数仍未验；native的4KiB显式原API存储诊断另有证据，未伪装成本包自然拍摄，也没有随本包默认加载。

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

### 内部恢复环境变量隔离

后续主会话host故障夹具复现：若宿主残留 `A7C2_SETTINGS_RESTORE` 或其SHA，空实例会继承该内部参数，可能选到不属于当前实例的恢复输入。控制器现先清除三个内部settings参数，再仅由当前租约/store生成，正式的`A7C2_INSTANCE_DIR`选择不变。新增三项测试分别覆盖空实例、未绑定实例、已提交实例覆盖旧参数；全部不启动子进程。受限host suite复测 **262 passed、33 skipped、71 subtests passed**。此前真实GTK三轮正常环境结果继续有效；没有把这三项host边界测试写成新的VM实验，也没有以此声称首设问题已解决。

### main：本包实际改值后跨整个GTK进程重开

补验使用本包production UI、launcher和稳定实例；不是恢复测试时直接写入25/2。`run-mm4glr5l` 中实际操作原语言页选简体中文，原日期页选“月-日-年”，main直接查看两张高亮截图。正常OFF并关闭整个GTK后，配置代 `eec6ef396bb94d7da9fa531d7bcfb534` 的完整Backup SHA为 `05f50c52021ad674ec17738fae569120ff8f2698dae6d09971f1621b401b2c11`，原API/file均25/2。

全新GTK进程启动 `run-p6jloiyb`，从同一实例加载该代。main独立解析实际选用cpio，两份 `seed-backup.bin`/`seed-setting/Backup.bin` 各出现一次，内容SHA都与来源相同；不只看恢复manifest。新运行正常OFF时原getter/file仍25/2，完整Backup SHA为 `fd99bda79d184c4756959dee1a6735163d58c8e1786ae35a0e0768ae082d20df`，发布新代 `e1d5982d35114d0ea95477e49b1da8fb`。两个全文件都由main重算SHA/FNV、原双bank checksum和目标字节，并核guest独立SHA记录。

两次SD保存的完整SHA分别为 `7a1a4a077be0ff588359d2f68081bc269431971cc549a200fe5a1f8fce04cedb`、`61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727`；main独立读卡核摘要、fsck均0、owner均恢复。本次没有指定同一张SD跨进程恢复，不能把这两个不同摘要当作卡内容保持证明。

第二GTK截图采得过早，仍是等待首帧的机身窗口，不能作为重开后的原语言页面证据。原console确有FRAME_DRAW_ENTER和后续原25/2读回；本次有限通过的是实际原菜单改值的跨进程保存/恢复，**首设完成、全部设置、重开后原页面的视觉复验、照片/录像仍未通过**。原自动proof总体false保持；本机main有限复核保存在实验目录 `main-review.json`，不随源码发布运行资料或Backup。

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
