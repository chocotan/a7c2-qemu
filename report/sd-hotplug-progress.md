# SD动态插拔：观察点与消息归属核验

## 已验收发布：默认单卡热插拔、退休导出与原内容消费

Task45/64已完成有限交付，独立包提交 **d69e839b07d8d6df39b17522036ceff6d56ac0f8** 已正常推送，main核远端main=本地HEAD、工作树clean。只提交29份文本源码/测试/文档，729份源码SHA与完整库存一致、27份选择性来源摘要相符；旧脚本同步检查及QEMU两阶段补丁身份检查通过，没有Sony镜像、私有setting、运行资料或私有4KiB诊断preload入仓。

包内修后`run-6o17sqe2`真正完成两轮GTK操作、四次状态导出及正常关闭，四份不可变128MiB块集由main逐块按offset重算全SHA，均为 `b511f810d3cf18a0f3b53367e161f5c394a0d8c24e7588d72c308b4070699b33`；两个absent导出均原retirement证据/Flush_rc=None，两个present原Flush0。两次重插后原AP完整DB/XML Read返回数据与导出卡逐字节摘要相符，main直接查看唯一GTK中SD状态与原卡图标变化，独立fsck0/owner恢复通过。

随后`run-mgfexv9k`不靠测试强设hotplug开关，而由标准RM2自然profile默认启用，并明确沿上一张卡回载。main核实际选用cpio的唯一sd-card.fat成员与源卡同SHA，原内容Read、退休/挂载导出、关闭保存均同b511...699b33，源卡没有改动，独立fsck0/owner恢复/包内运行锁重新获取通过。另有外部full路线VM在运行，未接触或中断它。本包默认开启，显式0可关闭；native研究profile仍保留opt-in，RM1诊断不承诺端到端支持。

发布前最后完整host为279pass/33skip/73subtests；另有93/61定向、16/11镜像、30/27标记/生命周期等各自实测。先前包内失败和安全恢复仍保留，最初按钮超时唯一原因未被回填；修后的实际widget-sensitive/idle门槛与换行printf输出通过新实测。这里验收的是同一张虚拟卡的安全拔出/重插及存储能力，不提供运行中另选镜像界面，不代表原拍照录像、自然重插后新拍摄Write或高层REC空间判断已经修复。

## 独立包首轮：三状态保存有证，第二次重插未确认；已安全恢复

Task64完成选择性移交后，main针对性93tests/61subtests、受限host276tests/33skip/71subtests通过。两位独立review均已结束；A指出测试链接漏项，main复现后只补测试源链接，整份SD镜像16tests/11subtests通过。未凭这些host结果发布功能。

包内`run-ocaot_1j`实际generation2/3/4对应absent/present/absent三次导出SHA均 `f42d70f32a38594d59ef4537992599c095589ac5c16f5b111e58ac240410d694`，其中absent使用原卷退休证据、FlushVolume_rc=None。但第四次GTK点击没有确认新的insert，自动验收失败。失败退出保存又遇SD_REQUEST标记与内核日志同行的严格解析错误，导致GUI保留；该序列cleanup.resumed=true，不等于已正常退出。

main身份核对后通过同一个UI的export action重新保存，再触发既有GUI正常close；导出与最终关闭卡摘要仍相同、fsck0/owner恢复、pidfd确认GUI退出，主会话再查相机PID集合为空。没有强杀或反向insert，原错误/三次导出/控制目录保留。恢复结果独立放`main-retained-ui-recovery.json`，不改原失败。

现标记发射改前后换行printf，严格parser保持不变，污染原例仍拒绝；host真实shell发布/失败/取消恢复组合30tests/27subtests通过。主会话私有GUI试验也补实际widget-sensitive和idle等待：旧run未记录敏感性，不能断言它就是第一次超时的唯一根因。代码在恢复后才解冻，修后新的包内复验与完整host已再次启动；结果待核，独立包尚不宣称完整热插拔交付。

## 重插后原API写入诊断已通过；独立包移交进行中

`run-atvy5ajv` 已在真实generation3重挂B盘、原程序读取DB后执行显式存储诊断。唯一新文件`B:/C883B25C.BIN`的原Open=0、Write=4096、Flush=0、Close=0、Open=0、Read=4096、Close=0；写入与读回FNV均`3c37c5fe978fc608`。main独立从QMP导出FAT取文件，完整4096B与诊断数据逐字节相同，SHA `4371dae3d0f92258599da5639f174e2836f6fdc0c93629e7e3a49c8f923c7bc2`。整卡SHA `e7b612a108f3d2ba07a3d1ed45090217dde6164a416650e533d9bd62eafd34fa`与export一致，独立fsck0、12files/4734of65399clusters、owner resumed。

该文件**有意作为诊断证据保留**，`left_behind=/C883B25C.BIN`，不是照片/视频或自然相机Write。原重插后自然DB/XML内容消费与三轮卸载/重挂载已分别有上文后续段落证据，不能与诊断写入混称拍摄成功。Task63有限原API写入/读回/跨通道内容验收完成，唯一权威C、README和实际重跑通过的离线复核器已交付`report/sd-reinsert-api/`，旧scratch驱动只引用该C，不维护副本。

Task64现由独立worker选择性移交已验核心/原Mount-Unmount观察/控制器/GTK/相关测试到`final/a7c2-qemu`，保持opt-in直到main包内实际复验；不复制整个native树，不移交私有诊断preload或把native运行结果写成包内结果。Task45仍跟踪最终交付、安全导出及包内验收，不将“native可插拔”扩大为发布包已提供。当前原REC媒体规则复验与包内host移交独立并行，guestVM/构建串行。

## 重插后原内容消费通过；补原API写入诊断

补验 `run-h7tn8rmu` 已实际绑定含内容观察的file-media库 SHA `ec0c6fe5e66221d72e48c4a4f67eca62676d132a8bee95365c94c4b4ec7d27e3`，再完成真实REMOVE/INSERT。generation3重挂B盘后，原AP自身Read返回：

| 原文件/handle | 请求→实际字节 | 原Read返回内容FNV | main独立读导出卡 |
| --- | --- | --- | --- |
| DATABASE.BIN / 0x62 | 10485760→9670656 | 8bbe7d404f0256fa | 完整9670656B相同 |
| MEDIAPRO.XML / 0x82 | 45056→406 | 5c88f8ba89b3a1f8 | 完整406B相同 |

main以FAT解析器直接从导出镜像取这两份完整文件，逐字节算FNV相同；文件SHA分别为 `ecc72d1faf312aa9fa9b00ad0ffccbd3004a550c2ffc9e61332d83aed4ac6fe7`、`fb850fae72857c305f68128549d4eb0a6526400d85d25b03930a2f9f5875687a`。整卡SHA `ba34dd15a5c4bb0025b305cb2bf63fa6458018a4dc1fc8c7a891314d675c8825`、独立fsck0、owner resumed；`main-original-content-review.json` 限定原重插后内容read=true，write/整体/capture仍false。这是真正的原Read返回数据证据，超出了Open成功；本轮没有新的自然Write记录，不宣称写入已验。

Task63现补**明确标为存储诊断**的同进程原Fsys API写入：只在真实generation3单卷重挂、原Read成功之后，调用原Open/Write/Flush/Close/Read，用唯一8hex.BIN文件写4096B并原读回；保留该诊断文件供独立导出比对，不伪装成照片/视频或自然拍摄动作。新preload只在实验overlay显式flag启用，不改Mount/Unmount/状态模型，也不改原触发Read的buffer/返回/errno。主会话host ASan/UBSan正常和10种拒绝/错误路径（旧代、原Read失败、文件存在、短写、Flush/Close错误、数据不符、多卷、严格flag/名字）与实际派生UI语法通过，2tests/11执行场景。该原ABI单VM已启动，结果尚未返回；不能先把诊断写成功标为true。

## 三轮重复实际通过；内容观察构建漏项已纠正，补验中

`run-oe74q3vt` 已完成六次真实GTK按钮动作。main逐个从原console核通知载荷、每代唯一Front原free0、原Fsys观察、卷mask及对应UI终态：

| generation | 原载荷 | 原卷操作/mask | 移除计数 |
| --- | --- | --- | --- |
| 2 | 02000002001000 | Unmount A: 1→0 | 1 |
| 3 | 02000002001200 | Mount B: 0→2 | 1 |
| 4 | 02000002002000 | Unmount B: 2→0 | 2 |
| 5 | 02000002002200 | Mount C: 0→4 | 2 |
| 6 | 02000002003000 | Unmount C: 4→0 | 3 |
| 7 | 02000002003200 | Mount D: 0→8 | 3 |

每次原操作返回0、UI lost=false、当前代终态正确；B/C/D是同一物理虚拟卡的原库新逻辑盘符，不是创建额外SD。main直接看第三轮LCD，拔出时卡图标消失、重插后出现；本次拔出帧处于文字闪烁时刻，不将它写成每次截图都显示NO CARD。三轮是明确的测试范围，不承诺无限次插拔。

整卡main独立SHA `c6f3aaa8b0e5a6a877d7e0d374a0d0deb7258a1bdc60cf782e364b6b7e5424b4` 与export相同，32段guest/QMP记录匹配、独立fsck0、11files/4732of65399clusters、owner resumed。`main-sd-three-cycle-review.json` 限定重复通知/卸载/重挂载true，整体hotplug/capture和重插后内容消费仍false。

本轮的内容日志缺失来自**main私有重建入口错误**：build-observers.sh仅在MENU_RM_FILE=1或MENU_MEDIA_SELFTEST=1时重编file-media-config.so；私有重建清空了MENU_*却未重新设置该标志，故虽然RM主observer已重编，file-media库仍是旧版。main实查该ELF不含FSYS_CONTENT字符串，而guest确已export观察flag。不能据“无日志”推原固件没有Read/Write，也不能把源清单包含新C当成已链接证明。

现私有入口明确MENU_RM_FILE=1，并在启动VM前核编译库含两个内容标记、实际base cpio只有一份且逐字节等于该库；旧库/陈旧cpio/重复entry均拒绝。身份检查与派生三周期/透明内容观察合计4tests通过。已单独启动一轮补内容试验；保留上轮全部原成功/未知边界，不重复算三轮完成，更不增加主动文件I/O冒充固件消费。Task45仍in_progress，等待绑定库后的实际内容证据。

## 修正掩码后：一轮真实GTK拔出/重插通过，重复与内容验收继续

`run-rqiyv09k` 原ABI重建observer SHA `84ec669eb76ee23671a78a1680dcef714f442dd02f73f902d2e4abe0c529c48f`，透明观察库保持同SHA `9de332bc945c414bf5181c53318cac22974b36edcfcd7268601b9d1aed99e113`。完成简中首设和原MENU后，真正点击GTK按钮：

* generation2 REMOVE `02000002001000`：原parser把R1改成port0/count1，M0自然初始化得到mask2。原Update发上层Notify(status0)，M0 status1→2。原Fsys_Unmount返回0，卷mask1→0，Front原free0；worker确认absent（drive0），没有强卸载。
* generation3 INSERT `02000002001200`：R1port1/count1，计数没有错误清零。原Update发Notify(status1)，M0 status2→1；原Mount `/nondev/rm2` 返回盘符 **B**，卷mask0→2，路径验证和Front原free0；worker接受新drive66并确认present。重插后原固件重新Open `B:/PRIVATE/DATABASE/DATABASE.BIN` 和 `B:/PRIVATE/M4ROOT/MEDIAPRO.XML`，不沿用A盘符。
* main直接查看原LCD：拔出图出现NO CARD，重插图不再显示NO CARD。原图与整体false proof保留，有限主会话review单独存储。这里只证明本轮输入、原通知/卸载/挂载及画面，不证明照片/录像。
* 原关闭保存后main独立整卡SHA `53da775fc87d726a3c28ed2e40e258e3239b6e9e737743967bb4dce3b6616ca2` 与export相同，独立fsck0、11files/4732of65399clusters、owner resumed。

task45尚不完成：Open成功不等文件内容已消费，仍需重复周期和重插后原内容读写。main新增严格opt-in `A7C2_FSYS_CONTENT_OBSERVE=1`，只对generation>=3的实际原Read/Write成功返回字节求FNV，记录handle/代号/请求及实际长度，不发起额外文件调用；不可信返回长度不读buffer，原返回、errno和在途计数保持。ASan/UBSan实测原Read调用一次、确实abc摘要、错误/旧代/非严格flag拒绝、无状态改变通过；Unmount/Flush/runtime组合6tests/24subtests，content与launcher2tests另过。

`observe_cycle.py --rebuild --cycles 3` 已串行启动，逐周期单独截图，任何uncertain即停、不自动反向。重建后本轮运行源冻结。重复/内容结果未返回，不预填为成功；两位独立mask reviewer也仍待正式结果。

独立review B现已结束并实际落盘于 `runtime/analysis/scratch/rm-mask-review-b/REPORT.md`（路径按实际产物记录）。它独立核原PT_LOAD、Init/Update/parser，确认同一rec+4→MediaInfo.mask→Rindex过滤链，未发现默认slot1一行修正的偏移错误；M0与R0不要求同号。main又独立读原10cb8..10d38，核payload[3] bit1写R1enable、payload[5] bit0/bit1/高4位写hold/port/count，与现场原数据相符。B提醒slot0诊断仍固定INITIAL通道；main核rm-file-device现有hotplug入口已拒绝slot!=1，因此本次不宣称RM1诊断的完整插拔支持。B只做静态审查，不将它写作动态复测；A仍待正式结果。

独立review A随后已结束并实际落盘 `scratch/rm-mask-review-a/REPORT.md`。A另核GetRMConfigInfo传输memcpy、PrintInfo原字符串`rmdataMask`、parser到Update的PLT relocation，以及旧回复到新回复只有消息offset68变化。main重算生产RM源码SHA `051d0bd588b14db483dc846bfc63a34f1896853dcebde5cbdcea1381ce5792fd`、旧失败console SHA `1ee47de3b0d23f52826d97e4b449ce0b3c9b85842457781296672bb970f2f9c7` 与A原件身份相同。A/B同意默认虚拟拓扑有依据，但这不把“rec+4恒等1<<record_index”推广到所有真实硬件；此模型成立因为所选记录与已建模通知通道同号。两review均已结束，未做VM，未互读新报告；一轮动态通过属于上文main试验，不能归为代理运行结果。三轮/内容试验仍待终态。

## 最新消费者实测：已进入原Update，RM配置通道掩码不一致

`run-kmc6m5y4` 已实际完成透明库原ABI编译、加载、简中首设和原MENU。REMOVE发送于console第4765行，Front原free0在4767；4768..4774明确同pid217/tid298解析原7B `02000002001000`，原parser返回0。两次PAYLOAD是同一parser对原getter的两次调用，不能计作两个通知。R1由`1/0/1/0`变为`1/0/0/1`（enable/hold/port/count）；Update前后M0都为valid1/mask1/start1，未出现新的上层Notify或原Fsys_Unmount。45秒后仍ejecting，驱动拒绝反向INSERT，自动proof保持失败。

主会话以原库98224B/SHA `4c1dbb303cf9d2d762723e0eb2266309c83aefe7d50f050fc8baa3964e4ea70d`核Init1007c、GetRMConfigInfo fd4c、Update fb48。Init从opcode9输出+8（首record+4）读word，按record stride36循环，将此word OR进MediaInfo+14；Update取该mask，按index0..2对R数组stride24筛选。实际mask1只选择enable0的R0；改变的是R1，因此没有触发上层通知。原rm-file-device回复在index1/RM2持有媒体，却把rec+4固定填1；**先前将rec+4称作未证class的注释被新的原消费者证据取代**。

main现仅把设备配置rec+4改为`1u<<state.slot`，默认RM2返回2，与现有R1通知相容。不写AP的MediaInfo、挂载状态或完成事件，不直接调用Unmount。固定原PT_LOAD字节测试、RM协议17个sanitized场景和runtime组合 **3 tests/17 subtests通过**；这是修复依据及host回归，动态修复尚未验收。两名同题独立review分别核原件，不互读新报告，尚未收取。

`observe_cycle.py --rebuild` 已通过共享idle_lock排入原ABI重建和同样的真实GTK试验；源码冻结至该run结束。上一失败SD仍正常保存退出：main独立整卡SHA `7801fd030844fdb0a675de11649b2d81d8b2b4961b9617d37e1ca1f25e50c84c` 与export相同，独立fsck0、11files/4732of65399clusters、owner resumed。保存成功不改变上述拔卡失败结论。即使修后出现Unmount，仍需INSERT/原Mount/读写/重复周期才能验收整个任务45。

## 最新状态：仍未完成guest插拔与最终UI验收

主会话已加入实验接线，需显式 `A7C2_SD_HOTPLUG=1`：

- `sd-hotplug-runtime.c/.h` 在同一 RM worker 中处理请求；其它线程仅排队原 Mount、Unmount 和通知 free 观察。
- `rm-file-device.c` 从原订阅目的队列发送 Front 所属 7 字节通知；`file-media-config.c` 回读同进程卷表，确认旧卷退休或新卷挂载。原 Flush 不暂停进程。
- `sd_hotplug.py`、`menu_live.py`、`menu_control.py` 接入同一控制队列；唯一 GTK 窗口已有“安全拔出 SD / 插入 SD”入口，实际结果未确认时不显示成功。
- 已拔出卷的导出使用单独 `SD_FSYS_RETIRED` 证据：原 Unmount 成功、原卷 mask 清位、无在途 I/O、worker 已确认退休。它不冒充一次新的 Flush 成功。

相关集成回归 61 tests / 61 subtests 通过；控制与恢复组合另有 48 tests / 20 subtests 通过；退休回复解析 5 tests 通过。首次 guest 构建因宿主头文件引入相机旧 glibc 没有的 `fstat`、`__isoc23_sscanf` 符号而失败；已改用 `SYS_fstat` 与显式旧 `sscanf`，宿主测试及 AArch64 未定义符号检查通过。首次周期驱动随构建失败退出，未取得 guest 拔插证据；原失败日志保留。

周期驱动位于 `scratch/sd-hotplug-cycle/drive.py`，按基线导出→拔出→退休导出→重插→再导出取证；原相机重插后读写恢复仍须单独证明，不能由卡摘要相同推出。

### 首轮真实通知：run-9isvuc6s 未完成卸载

此次旧 glibc ABI 构建通过并实际启动。原 Fsys Mount 得到 A 卷，同进程卷表从 0 到 1；基线导出 SHA-256 为 `61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727`。原 Flush 返回 0；请求序号 `962360925644747`、generation 2 的通知是 `02000002001000`，发送目的地 `0x80af6188`，allocation/source owner `0x8028017c`。原接收方按该 owner 释放返回 0，日志明确保留对应 generation。

但 45 秒观察内没有原 Fsys Unmount，状态始终 `ejecting`，host 返回 `uncertain`。驱动未反向插入、未伪造卸载，之后正常 Flush/导出并退出 VM。本轮只证明变化通知到达原接收方且被释放，**不证明 Parse/Update、卷退休或拔插完成**。完整日志和失败 JSON 保留于该 run，未回填成成功。试验未走完中文首设，不能排除原媒体管理器所处启动阶段的影响，也不能据此断言是唯一原因。

### 独立审查与修复

`scratch/sd-hotplug-review/REPORT.md` 的只读审查已交付，代理已结束。主会话逐条核对后修复六项边界：入队即阻断新输入且执行排队命令前再检查；未结请求跨超时和旧回读保持隔离；普通回复/INITIAL 的 send 错误也保留 lease；事件溢出在消费完成观察前检查且禁止退休导出；先过滤无关卷/操作再解释错误；原 Mount/Unmount 在调用入口捕获 generation 并原样传到完成观察。

`scratch/sd-hotplug-cycle/test_control_quarantine.py` 的三项故障现已在生产控制器通过，独立候选不作为运行依赖。控制/窗口组合 **46 tests / 17 subtests** 通过；核心/原调用/归属组合 **13 tests / 41 subtests** 通过，其中 C 使用 ASan/UBSan。新增夹具覆盖队列溢出禁止退休、无关卷错误、旧代成功/失败、原调用执行期间代号改变仍携带入口代号、send 错误后的原接收方迟到释放。修复后的动态验收仍待进行；实验入口未升为默认，也未同步至独立包快照。

后续修复版已完成原 glibc ABI 编译、链接和 raw cpio 重建（`REVIEWED_SD_GUEST_BUILD_PASS`，退出 0）。既有 observer 格式和 libc 声明警告保留，不能据编译成功推导热拔插通过。下一轮新增 `check-natural-gtk-input.py --new-ui --firstboot --simplified-chinese --sd-hotplug-probe --export-sd`：先走完中文首设和稳定原 MENU，再点击最终 GTK 的真实 SD 按钮，只有卸载完成才尝试重插；失败不反向操作。驱动静态语法与前提拒绝检查通过，实际结果仍待观察。这个对照用于区分原媒体管理器启动阶段，未预设缺少 Unmount 的原因。

首次“首设后插拔”调度在 ready 前失败，尚未建立新 run：启动通道等待超时；对应 UI/launcher 日志为空，`latest-menu-run.txt` 仍指向前次 `run-9isvuc6s`。主会话随后核 `/proc/locks`，发现另一个本会话排队实验的外层等待器持有 native 锁；它在等待相机实验退出，而启动中的 GTK 又需要该锁，形成等待顺序冲突。没有 SD 请求、原通知或新的卸载观察，不能把这次失败解释为固件拒绝卸载。后续不再提前并发排队这些外层启动器；待当前实验结束后单独调度该对照，并把等待锁与实际 ready 超时分开。

主会话随后为 `scratch/native-body-control-run/wait_and_run.py` 增加 `idle_lock`：先以 pidfd 等已有启动器/VM 退出，再取锁并重新检查；若取锁前出现新启动器，先释放再等待，绝不拿着它需要的锁等它结束。取锁、竞争、异常释放和向真实子启动器释放锁的四项 host 测试通过。首轮组合测试因旧夹具只替换 wait、却仍查询宿主真实进程而超时；现已把夹具的进程集合也隔离为空，复测 4 passed。没有在这些 host 测试中启动/终止相机。

后续对照入口已保存为 `scratch/sd-hotplug-cycle/after_setup.py`，保留源码摘要等待核对，并通过共享 admission helper 进入。运行时仍由实际 launcher 持有自身锁；该 helper 不承诺阻止不遵守共享锁的外部工具，故继续在当前外层实验终态后再单独调用，暂不提前并发排队。

### 首设后真实 GTK 对照：仍未完成原卸载

修正调度后实际 `run-nksugd_8` 已走完中文首设并进入原 MENU；通过实际 GTK SD 按钮触发请求 `965653735648615`、generation 2。原 Flush 返回 0、inflight=0；`02000002001000` 再次发送到订阅队列 `0x80af6188`，原接收方按 `0x8028017c` 归属释放返回 0。初始原 Mount 的入口 generation 为 0、原卷表从 0 到 1，随后绑定到第一代，均有实际日志。

这次仍没有原 Unmount 观察，45 秒内状态一直为 `ejecting`，未丢事件（lost=0），未执行反向 INSERT。自动验收失败并保留原 proof。关闭路径正常原 Flush/导出/恢复，main 独立回读 SD SHA `af8844d80d87a72fa934948b1806cc0d9961ae4dd6ffbbd780535dd4dd13fab8` 与 export 一致，fsck=0；不把正常保存当作拔卡成功。

该对照不支持“只是尚未完成首设”这一解释，但仍不能从 free 直接推出 Parse/Update 及挂载管理器业务已运行。下一有效观测是原 `libInfraMediaDetect.so` 的 `CallbackPointFromFront`、`ParseInternalMessage`、`Update` 对同一份 7 字节的处理与下游 Fsys 调用，需只读入口/出口取证，不直接调用 Unmount、清业务门禁或补完成事件。

按用户允许暂放难题的要求，暂不再无差别重试 SD 周期。实验入口继续显式 opt-in，独立已发布启动包不包含这套 WIP；先完成 overwrite 回退和配置宿主生命周期等可独立闭合事项，再从上述消费者入口恢复。

### 任务45恢复：补原解析与上层通知的透明观察

配置有限交付完成后，main已恢复此任务，只推进上次缺少的消费者证据，不重做核心或通知包调查。新 `scratch/sd-notify-trial/media-consumer-observe.c` 透明包装原MediaDetect的ParseInternalMessage、Update、StartInOut、NotifyInOutEventByMediaInfo，以及parser调用的MWF::Struct::GetValue。

每次仍调用原函数一次，保持参数、原返回和errno；只读原R/M状态布局和原getter实际返回的载荷，不猜ObjMsg字段中的指针，不读已经释放的缓冲，不调用Mount/Unmount、设置presence或生成完成事件。头七字节只在parser自身获取有效size/value后记录，原free与Fsys观察继续来自既有链。

ASan/UBSan夹具核原调用/返回/errno/self未修改、opt-in日志和原载荷字节；实验probe/launcher/GTK child语法与参数前提也过，合计 **2 passed / 0.12s**。这仅是host结果；原guest ABI编译及动态符号interposition仍须下一台ownedVM证实。

`observe_cycle.py` 已准备独立overlay观察库，先原简中首设和MENU，再实际点击SD按钮；若仍uncertain不反向插入，保留原consumer日志和正常关闭结果。当前独立包非默认参数的跨GTK验收仍在占用运行槽，main没有并发启动SD VM。该轮只在其终态后单独构建与启动，已有失败proof不回写。

以下保留此前里程碑及原始证据；其中“尚未接入”描述对应当时状态，不代表上述实验接线已通过动态验收。

### 此前的归属与适配层里程碑

用户再次明确要求优先完成SD热拔插。最新main已将`rm-file-device.c`的消息分配owner与
发送destination分离，lease分别记录二者；发送失败按owner释放，原接收端free也核owner。
原query reply和initial通知仍使用其原来的owner/destination，不因此发送变化通知。
宿主测试覆盖17个RM场景（含Front不同owner的分配失败、发送失败、立即free和错误free），
与原Unmount/Flush测试合计3项、41子场景通过，C启用ASan/UBSan。
首次重跑因主机/tmp用户quota编译失败；使用独立/var/tmp TMPDIR后通过，未删其它任务数据。

旧`sd-hotplug-adapter`的notify传owner/dst零、共享全局context、初始化自行构造Mount
观察及send0映射ack问题，已由代理复现，main又独立运行复现与候选后修正生产层。
新版每实例持有core/ops/counters，显式路由按值透传，`sd_send_result`不改写；真实mount
必须由调用者提供。薄层移除多余的request/snapshot wrapper，直接使用原core接口。
代理候选四组与旧缺陷复现均在main ASan/UBSan下通过，集成回归13项、41子场景通过。
另一代理仍核原AP消费者及安全Flush/通知/Unmount/Mount顺序。动态SD状态与UI尚未加入。

验收仍必须是同VM写入→安全拔出→原Unmount与通知free→重插→原Mount→读写内容保持，
再核整卡摘要及fsck。已有SD导出和DB/XML写入不能重复算作热拔插完成。

最终唯一GTK窗口运行中插入/拔出虚拟SD的要求仍未完成。本轮没有发送介质
变化通知，没有卸载、关闭镜像或执行插拔VM实验。既有DB/XML持久化结果
不扩展为热插拔已通过。

## 已实现和测试

file-media-config.c增加观察型Fsys_Unmount包装，原型来自现有原Fsys测试：
unsigned char drive、unsigned int flags、int返回。仅调用原函数并按现有
显式测试开关记录真实返回；不主动发起卸载，不改变挂载缓存或介质状态。
原libInfraFsys.so为687960B，SHA256
33451a884b65f946ac8aca44b620cd3cec677d05752c52f2ff0e212a01824bfa；
其Fsys_Unmount导出VA31728、1420B。真实guest调用尚待验收。

宿主回归命令（在runtime/analysis目录）：

```bash
python3 -m pytest -q test_fsys_unmount_trace.py test_fsys_flush_barrier.py test_sd_session_retry.py
```

复测结果9passed、24subtests passed，0.33s，退出0；C夹具启用ASan/UBSan。
覆盖原参数/返回转发、显式开关日志、成功及错误、无状态修改和既有刷新流程。
首次新夹具编译失败（变量重名和fflush声明冲突）已修正，失败记录保留，
不把首次失败改写成成功。git diff --check通过。

## 分配归属与目的地的原始证据

initial消息从订阅队列N分配、发N并free(N)；变化消息保留Front归属
8028017c，投递N后原AP按相应归属释放。原emit曾把分配/发送/lease归属
绑在同一dst；最新main已分离这两个概念，动态消费者仍待验收。

主会话核原libosal_uipc.so：43752B、SHA256
09ebf5980237fc473077dc844763dcb00cba423f431646e3be7c0ca49ea70ff3。
osal_valloc_msg_wait在67b0、448B窗口SHA256
0a0f8eb439b7d2a57f8c0d27006072b18517ccdb93a2a8e4e8b97cf11da29b91。
67e0按ID bit15分支；8028017c的bit15=0，6860经PLT2670进入原
u_osal_valloc_msg_wait。不能把其他用户态池分支的注册条件当作该路径条件。

u_osal_valloc_msg_wait在3e98、144B窗口SHA256
994c7c4d9245c3490b3f9b21eadc2c10b80a5fd753e12685535f5cdc912b1efd；
它将ID、输出指针、size/count组合传至内核调用。此窗口未见本进程队列
注册检查，但内核分配是否成功、队列状态要求及原AP实际free仍需实测。
静态分支可达不等于分配或通知成功。
完整固定原字节及反汇编在scratch/sd-hotplug-main/osal-ownership-original.txt
和osal-kernel-allocation.txt，单窗均≤1800B。

## 未接受的方案与下一步

两位代理同题独立调查。第一位R2仍有计数文字/字节矛盾、host直接inotify
guest /tmp的不可用通道，以及发出通知后自动回滚的未证实假设，均未照搬。
通知已发但原卸载未确定时须报告不确定状态，不能直接恢复UI为已插入。
等待墙钟超时只表示失败/未完成，不代替原卸载成功证据。

## 原API归属分配实证run-xchyz1p_

独占非显示guest测试通过，未启动原相机UI或替换其消费者。原分配器以
owner8028017c分配7B返回0；原size=7，set/get source=8028017c，七字节
测试内容读回一致，原free(owner,p)返回0。测试数据不是合法RM通知，
从未调用send或注册Front队列。该结果证明分配/source/free的有限合同，
不证明原AP callback收到或释放了一条变化通知。

随后既有RM队列测试真实注册、stat回读、发送32B、callback逐字节检查、
原free及注销全部返回0，注销后idle复核通过。原Fsys在4MiB文件卡写入
4096B、Flush/Close/Unmount成功；另一进程以Mount100hex重新打开、
读回逐字节一致并Unmount。新增观察包装器亦记录原Unmount返回0。
这是独立Fsys测试的卸载，不是热拔卡触发的原相机卸载。

镜像4194304B，SHA256
d2490baadea79eabbfda9e23bea5f70c2f821e41915d172d8603ed96fd5a7acf；
guest导出FNV41613544a04795ca，主会话另行检查fsck.fat -n返回0，
3files/3of254clusters。console72801B，SHA256
479846798fb5efd5781e5f7bfa689175b551471d09837975664d4e51a67ca16e。
选中fsys-file-test摘要
127b84594e248404727c607f551c33e39a39f9c0dd4936750638b73f8aa1deab，
file-media-config.so摘要
4d946b0477939f79402bac7330078b9e98c1237d16a82f6cea13f05707a15126。

下一步将通知的allocate/free owner与send目的地分开，继续核原AP变化消息
消费、原卸载完成、重插Mount及读写恢复。正确处理inflight、Flush和lease后
才接入UI成功状态。未提交任何空ACK、猜测通知包或假有卡标志。

## SD 热插拔状态核心：A/B 选型与落地（main）

两位执行代理各自独立实现同一份纯 C 迁移核心（≤400 行，仅写自己的 scratch）。两份都通过
了自己的宿主断言，所以**不按“谁通过得多”取**，按契约逐条比对后选定 A：

| 判据 | A | B | 取舍 |
|---|---|---|---|
| 7 字节通知 payload | 核心内部按 `RemoveCnt<<4 | present?2:0` 构造并传给 notify | 仅在快照里构造，notify 只拿 (gen, op) | 选 A：设备模型就是发这 7 字节，单一真源 |
| 回滚条件 | 仅 `delivery==NOT_SENT && !observable_ack` 才回滚并还原 RemoveCnt | 单个否定式判定 | 选 A：把“确证未发送”和“投递不确定”分开 |
| 投递不确定/超时 | 一律 `FAILED_UNCERTAIN`，不回滚 | 同 | 契约要求，二者一致 |
| 观测分代 | `generation != current → STALE`，必须 genuine | 同 | 一致 |
| 两阶段收敛 | 需 fs_ack **且** free_ack 才落到 ABSENT/PRESENT | 同 | 一致 |
| 结果枚举 | 含 PENDING/EXHAUSTED/CONFLICT/ROLLED_BACK 等 | 较简 | 选 A：便于 adapter 映射现有返回码 |

落地（生产树 `runtime/analysis/`）：

- `sd-state.c`（SHA `c06e80da…`）、`sd-state.h`（SHA `fb1ada92…`）、`test-sd-state.c`（SHA `5975be2c…`）。
- 相对选定的 A 变体**只做了一处机械改名**：两处 `#include "sd_state.h"` → `"sd-state.h"`，
  以符合既有 `rm-file-device.*` 的连字符命名。其余逐字节相同。
- `test_sd_state.py`：钉住三份文件 SHA 与 ≤400 行上限，并在 ASan/UBSan 下编译运行 C 断言；
  **2 passed**。C 侧输出 `PASS: 8 groups; bind, ack permutations, retries, wrap, guards,
  sends, stale/fast, errors, deadlines, sentinel`（EXIT=0）。

尚未完成（下一步）：把 adapter 接进现有设备模型——`guard` 用持有生命周期锁的 owner 线程、
`validate_backing` 用已打开的卡镜像 fd + identity、`validate_quiescence` 用原 `Fsys_FlushVolume`
观察、`notify` 用 `rm-file-device` 的 7 字节发送（owner/dst 分离）。接完再做 guest 侧真实
插拔验证；在这之前不宣称动态插拔完成。

## 修正后的适配层：`sd-hotplug-adapter`

状态核心（`sd-state.c`）已有 8 组断言，但还缺“与真实服务对接”的那一层。新增
`device-models/sd-hotplug-adapter.c/.h`，只提供四个钩子。旧版测试过弱，曾把头文件纪律
文字作为测试，现已删除。新版以真实回调参数、实例交错、发送结果和观察条件进行验证：

| 钩子 | 语义 | 失败时 |
|---|---|---|
| `guard` | 仅持有生命周期锁的 owner 进程返回 true | `SD_GUARD_FAILED`，不发送 |
| `backing_unchanged` | 打开的卡镜像 inode/size 与绑定时一致 | `SD_BACKING_FAILED`，不发送 |
| `flush_original` | 跑**原** flush，返回其真实 rc | 非 0 → `SD_QUIESCENCE_FAILED`，不发送 |
| `send_notification` | 接收gen/op/owner/source/dest/原7B，返回原生sd_send_result | delivery与observable_ack保持独立，不由send0推导观察 |

绑定需要实际backing和已观测Mount，由调用者提供genuine/path/rc；适配层不捏造。
对象/context/路由需稳定且由一个worker串行使用，实际观察在callback返回后排队提交。
存在显式路由参数不等于协议合法：具体backend仍必须核原owner/source/destination。

宿主测试 `test_sd_hotplug_adapter.py` 的C夹具（ASan/UBSan）覆盖四组行为，配合核心等
SD回归共13项、41子场景通过。覆盖：
绑定→PRESENT、EJECT 通知送达→EJECTING（RemoveCnt nibble=1、payload `0x10`）→
UNMOUNT+NOTIFY_FREE→ABSENT、**确证未发→ROLLED_BACK 且 RemoveCnt 不变**、
**投递不确定→FAILED_UNCERTAIN 且后续请求不再猜**、flush 失败与 guard 拒绝都在发送前拦截。

下一步（仅隔离guest）：把四个钩子接到 `file-media-config.c`（Mount/Unmount 观察与
FlushVolume）与 `rm-file-device.c`（7 字节通知，owner/dst 分离），再做一次 guest 侧真实插拔验收。
