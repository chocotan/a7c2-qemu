# 原菜单语言与日期格式：保存、恢复验收进展

当前有限 SID51 启动记录的原提交/完整导出/新VM恢复已通过，详见 `backup-noop-sync-contract.md`。本项另验真正由原GUI修改的语言和日期格式，不能套用启动记录成功。后续已完成有限稳定实例/GTK保存、重初始化和选择性独立包移交，前期“未完成”段落保留当时范围；首设完成状态与全部参数仍未完成。

## 最新独立包补验：真实改值跨整个GTK进程恢复

`check_package_changed_settings.py` 已正常结束：本包 `run-mm4glr5l` 原GUI选简中25/“月-日-年”2，正常OFF/关闭GTK，再全新GTK同实例启动 `run-p6jloiyb`，最终原API/file仍25/2。main直接查看第一轮两张高亮原LCD，重算两份完整Backup的SHA/FNV/双bank/目标值，独立解析实际恢复cpio中两个seed各一次、SHA均为来源 `05f50c52021ad674ec17738fae569120ff8f2698dae6d09971f1621b401b2c11`；第二关闭文件SHA `fd99bda79d184c4756959dee1a6735163d58c8e1786ae35a0e0768ae082d20df`。来源代eec6ef396bb94d7da9fa531d7bcfb534→新代e1d5982d35114d0ea95477e49b1da8fb，持久化未靠宿主遗留env。

第二GTK采图过早，机身窗口还等待原LCD首帧；不拿它作为重开后的原语言页视觉证明。原console已有FRAME_DRAW_ENTER，关闭时getter与完整file一致。两SD整卡main核摘要与export一致、独立fsck0、owner resumed。该轮没有把前次卡传给第二进程，SD跨进程内容保持另有已验路线，不混用。

独立包validation/README.md已增加精确范围。首设完成/全部设置/第二次原页面视觉复验仍false，Task49继续in_progress。主会话首次一次性核验脚本误对已是hex字符串的fnv返回值再做整数格式化，立即报ValueError、未得到核验结果；修调用后完整核验通过，工具错误不算VM或设置失败。

## 原参数和工具

原 AP getter/setter 的 ELF PT_LOAD、PLT/GOT 和实际指令核验在 `config-parameter-contract/`。语言ID `02cf0401`、日期格式ID `02cf0403`，均1B、SID02cf。公开seed分别为1、3；具体用户选择由原LCD和getter现场值确定，不由序号猜标签。

候选 `scratch/user-settings-checkpoint/user-settings-checkpoint.c` 只调用原 `Backup_nread` 与公开 `Backup_sync_subsystem(02cf)`，不包含 setter。原ABI构建和main独立14项host测试通过。它校验完整2390264B、两个bank/checksum、原API与文件目标值和二次API稳定，并通过已有精确保留RAM窗口导出/FNV回读；调用返回0本身不算保存通过。失败文件使用明确FAILED标记导出，不包装成功。

## 第一轮真实GTK：两值已变，helper前置过严

实际 `run-w5ph3fau` 使用单GTK、真实xdotool点击原语言页选择简体中文。原日期格式页初始高亮“日-月-年”，一次UP后截图 `gtk-date-format-alternate-selected.png` 清楚高亮“月-日-年”，main已直接查看。

原API现场值为语言25、日期格式2，均不同于seed。helper读取原文件却为语言25、日期3，说明语言此前已由原固件提交，日期仍待提交。旧helper要求**两项都必须与文件不同**，于是报 `before_file_both_different`，未调用SID同步，本轮总体失败。

FAILED文件已导出：guest FNV `24e8a3fbf9cc0848` 与main实际字节运算一致，SHA256 `c86c29eb6c65975674b9b1fb9fb4ae2a9d44fcc875ab51729a09bc2179b2affb`，双bank校验有效，原parser独立确认语言25/日期3。原错误、文件、SD及自动proof全部保留；有限main复核另存 `main-first-settings-review.json`，save/crossVM仍false。

## 修正与下一轮

helper现要求两API值都已从seed改变，而**至少一项**与原文件不同才同步；两项均已相同的no-op仍拒绝。新增“语言已保存”“日期已保存”两个host场景，合计 **16 tests passed**，ASan/UBSan保留。原ABI重新构建成功，二进制SHA更新为 `35efe7d6aade92373aa1addae230f6835181bc7bdd8230509091abfcfca11053`，main私有launcher显式钉住该身份；初版二进制与失败结果不改写。

`scratch/user-settings-ui/run_save.py` 再次走原语言页和日期格式页后，在同一控制队列的保存阶段调用helper，先抓取完整Backup再导出SD，避免两者共用RAM窗口时错取内容。精确marker、派生Python/Bash与实际GTK child语法夹具通过；实际第二轮已串行启动，结果待核。

保存通过后另启动新VM，从该次完整文件恢复两份seed，不运行powerseed，不修改菜单；在pre-app与app启动后分别用原helper读取两个实际保存值，并记录原LCD。恢复驱动 `scratch/user-settings-ui/run_restore.py` 及marker/阶段夹具已准备通过，尚未动态执行。界面截图仍由main复核，host parser或shell返回不替代它；整个程序重新打开的稳定实例保存和UI重置继续由任务49跟踪。

## 第二轮：原固件已将两项都提交，改验真实文件恢复

`run-5c95w2bu` 同样通过真实GTK选择简体中文与“月-日-年”，main分别打开本轮两张原LCD截图核对。helper再次读取API=25/2，文件这次也已是25/2，于是按保留的no-op保护报`before_file_no_pending_change`，没有调用原同步。原应用保存时序不同不能用假setter制造待提交值；该自动试验继续false。

main独立读FAILED导出文件并重新算guest FNV一致（`c8d35e1c96b14431`），两个bank checksum有效，原parser读取25/2一致；完整文件SHA256为 `3c619063f6443dcf3db061d041dac30ebb7e12ce9c49103063d4c9c1310c5f3c`。这已是由原菜单实际生成的保存内容。有限`main-settings-file-review.json`只把它作为恢复输入通过，保留原试验false、无helper同步和未跨VM等字段。

后续恢复入口显式接受这种已经main核过的文件，但须重核：原错误必须恰好是no-pending、不得出现helper sync、原API/file四值完全相同且不同seed、实际文件摘要/FNV/两个bank和目标字节、原GUI修改标记与保留的false。没有用“FAILED文件存在”自动信任任意失败。

使用该源的新VM恢复已单独启动：不运行powerseed、不发setting setter，pre-app精确文件SHA/两个原getter与post-app两个原getter都必须为25/2；记录原LCD、正常SD关闭。结果待核。最终完整稳定实例、全设置覆盖和UI重置仍未据此完成。

## 用户设置首次恢复：读回成功，随后原应用 abort

实际 `run-v_beqlwz` 在app启动前两次原API读值均为语言25、日期2，原helper的文件匹配和RESTORE_MATCH/进程RC均为0；同阶段完整文件SHA也与 `3c619063f6443dcf3db061d041dac30ebb7e12ce9c49103063d4c9c1310c5f3c` 一致。因此本轮不是用户字段恢复失败。

之后原应用在settle进入异常监视器，尚未ready，未取得post-app两字段回读或最终LCD/正常SD退出验收。原异常寄存器、maps和crash-stack.bin保留。初步对照：这份仅由用户菜单保存的文件，其SID51启动记录前六word仍全零；此前有限启动记录恢复文件则为 `(0,2,1,1,0,1)`。禁用整个powerseed使两种文件的启动上下文不同，但未以这一对照单独断言abort唯一根因。

main已完整读原 `seed-power-on.c`：它只经原API读写启动记录 `0051004a`，不写语言或日期格式。修正试验在**原用户字段和完整文件pre-app验证完成后**，才执行这个既有启动上下文初始化器，再让原应用正常启动并复查两字段。launcher仍不带自动`--seed-power-on`，顺序由私有setup明确记录；host阶段顺序/marker夹具通过。该实际新对照已串行启动，结果待核，原abort试验不改为通过。

## 正常生命周期快照与实例发布候选

证明“新提交”的实验save保留原no-op拒绝；正常保存另增snapshot分支：允许两值未改变或已由原固件保存，只在原API与文件不同时同步有限SID02cf，再核完整文件、两个bank、二次API及RAM摘要。19项host测试通过，尚未作为生产默认入口运行。

宿主 `settings_checkpoint.py` 在同一串行事务中核helper原始marker、RAM/QMP完整文件、FNV、两个bank及目标值，再独立调用guest openssl取得完整文件SHA；任一不一致拒绝发布。`settings_instance.py` 复用原生命周期token和store，只接受该显式核验结果，按expected generation CAS提交；load损坏、目录/文件链接、SHA/API值不一致均不静默回seed。其逻辑reset仍保留旧代和SD。两模块的实际host故障组合 **16 tests passed**，仅scratch候选，尚未接最终GTK或独立已发布包。

完整设置跨UI进程保存、重初始化UI和其它SID的提交覆盖仍未完成；这些候选不扩大当前两字段和有限文件证据的范围。

## 两项用户设置跨VM恢复通过：run-jicsgfqi

补齐启动上下文后的新VM实际正常启动。main独立核原console：启动前原helper两字段回读25/2、二次API稳定、完整文件SHA匹配源文件；这些读回先于`POWER_ON_RECORD_OK`。启动上下文helper返回0后，原app启动后的原helper再次读取25/2、文件/API与保存期望仍匹配。并未使用语言/日期setter补值。

main直接打开 `user-settings-restored-startup.png`，原语言页面清楚高亮“简体中文”。这同时暴露剩余边界：首设完成状态未恢复，仍停在语言页，不能将两个值恢复扩成“完整首次设置已保留/自动进入拍摄”。运行正常退出，原SD Flush=0、owner恢复、整卡摘要和独立fsck通过。有限人工复核另存 `main-user-settings-restore-review.json`；源试验no-op总体false与前轮abort现场不改写。

这完成两个真实GUI设置的原文件→新VM→原API恢复，不等于稳定实例最终UI已经接好。接下来 `check_snapshot_instance.py` 正串行验实际guest snapshot→独立openssl SHA/QMP→生命周期租约内CAS发布→不可变新代读回→正常SD退出。宿主候选和启动脚本检查已通过，实际结果待核；全部SID、首设完成标记、最终UI自动保存/重初始化继续未完成。

## 实际快照发布到宿主实例：run-1j472_yu 已通过

main已核此轮实际结果：原snapshot helper对初始语言1/日期3读取与文件匹配，guest FNV为 `06e5cdb4024712f6`，独立guest openssl SHA与QMP完整文件 SHA均为 `29b5c7d43721ba2117371aa61b48741730c9730a1ce3d20703c9425bf0be81f6`。两个bank/checksum及目标字段校验通过。

VM生命周期租约内通过原store CAS发布代 `7096e871e6594b2eb709e5e86467ce09`；不可变代读回字节与原导出一致。正常SD保存、原Flush/owner恢复和VM退出后，main重新获取实例租约并load，代号、完整字节和参数仍相同；独立fsck=0。限定结果保存在该run的 `main-snapshot-instance-review.json`，没有用主机自行算出的SHA冒充guest独立SHA。

这一轮值是初始1/3，验证的是正常快照与实例新代发布，不能取代前面的真实菜单25/2恢复证据。下一独立进程已从这个稳定实例代开始新VM恢复对照：整个准备、运行和清理持同一租约，原pre/post-app getter和文件身份必须来自存储代，且源代不得变化。动态结果仍待核。最终UI尚未启用这些scratch候选，首设完成状态、全部设置和重初始化UI仍未完成。

## 独立进程从实例代启动：run-jyd041es 已通过

新进程从稳定实例目录读取代 `7096e871e6594b2eb709e5e86467ce09`，整个派生准备、VM运行与清理持有同一生命周期租约。原pre-app文件SHA与代数据的 `29b5c7d43721ba2117371aa61b48741730c9730a1ce3d20703c9425bf0be81f6` 一致，启动前后两次原API均为1/3。main独立重读原串口marker，确认启动上下文helper位于第一次读回之后且返回0；退出后重新取租约读取，源代号和字节未变。

该VM正常保存退出，原SD Flush/owner恢复与整卡摘要匹配，main另跑fsck=0。此轮不依赖上一进程的Python对象，闭合的是实际快照→宿主不可变代→独立进程load→新VM原API读回。真实用户改值25/2的跨VM恢复是前述另一轮证据；本轮不假称再次操作了那些菜单，也不据默认1/3推导全部设置通过。

## 权威运行源码移交与构建

已将通过实际试验的组件直接迁入本成果 `runtime/analysis/`：`settings_checkpoint.py`、`settings_instance.py`、`user-settings-checkpoint.c`，两份host测试同迁；scratch只保留实验驱动、构建入口和历史证据，不再维护第二份运行组件源码。构建脚本使用冻结源码快照、原glibc ABI生成helper，probe源码身份清单也加入新组件。

迁移后的快照、实例发布、生命周期、VM/store、C helper与源码快照组合 **112 tests passed**。正式runtime的原ABI helper构建/cpio重建已在共享锁下串行启动，结果待核。此时只是组件移交及构建接入，最终GTK自动保存/恢复、首次设置完成状态、全部SID提交覆盖和重初始化仍未完成；没有把native WIP同步进已发布的独立包。

正式runtime的原ABI构建和cpio重建随后实际返回0，输出 `AUTHORITATIVE_SETTINGS_GUEST_BUILD_PASS`；helper无C23/fstat未满足符号。既有observer格式与libc声明警告仍保留，没有据构建成功扩大成配置功能通过。

后续正式接线已加入可选 `VM(instance=...)`：自然启动从租约内校验的不可变代读取恢复源；probe只派生两份seed的独立cpio并按预期SHA核验。关闭/保存先做原配置snapshot及独立guestSHA/QMP核验，再保存SD；父控制器持原实例租约进行CAS发布，配置发布失败则SD结果整体报失败、VM保留，不提前取消。未绑定实例的入口不启用这一行为。

接线的host回归 **110 tests passed**，包括恢复源SHA错误拒绝、两份seed派生、原store/生命周期/VM与SD重试。正式默认启动器的两轮实际VM往返已启动：首次关闭必须发布配置代和SD，第二次实际manifest必须指向上一代两份seed，原API值保持、关闭再发布并正常退出。驱动不替换 `vm.command`，也不自行调用发布函数，专门验正式控制器路径。动态结果待核，最终GTK尚未默认绑定稳定实例，首设完成状态和重初始化UI仍未完成。

## 正式默认启动器两轮往返：已实际通过

`run-6rt4grfo` 是空实例首次运行，正常关闭通过配置snapshot/独立guest SHA/QMP、CAS发布代 `2a21e9a6505041ffa958e09682fd1f44`，文件SHA为 `29b5c7d43721ba2117371aa61b48741730c9730a1ce3d20703c9425bf0be81f6`。第二次默认启动 `run-2935ulii` 的实际manifest两份恢复seed均匹配该SHA，控制器加载的代号也相同；原getter值保持语言1/日期3。第二轮正常关闭发布新代 `9bd430c44c134dfc83d6c9090a4ca5ba`、新文件SHA `dd9d778f825979b835b5a394823580adbac751957fdae7a0d203eae64c5f1c42`。不要求正常运行后的整个文件与上一轮完全相同，也没有忽略目标参数的一致性。

main重核两轮SETTING实际文件/guest独立SHA、恢复manifest和原SD导出，每轮SD Flush/owner恢复正常、整卡摘要匹配，另跑fsck均0，终态均exited。测试驱动确实没有替换默认launcher或直接调用发布函数，配置恢复与发布由正式VM控制器完成。这个有限默认控制器往返通过，不等于已经重新打开最终GTK进程验证全部设置。

后续增加默认owned0700实例目录的安全创建和 `VM.reset_configuration(confirmed=...)` 停止后逻辑重置接口：存在状态不覆盖、链接路径拒绝；活租约/owned进程/未清理线程不允许重置，严格确认和CAS保留。SD指针与文件、旧配置代均保留。此接口及现有store/控制器组合 **78 tests passed**；GTK按钮和默认绑定尚未接入，首设完成状态与全部设置覆盖继续未完成。

## 最终 GTK 稳定实例与重初始化接线（实际窗口验收待核）

`camera_ui.main` 已默认绑定本成果 `runtime/analysis/camera-instances/default`；设置 `A7C2_INSTANCE_DIR` 可选择另一私有根，其下仍使用default实例。目录由既有逐级验证创建，已存在状态不替换，忽略规则排除配置代。首次设置类集成测试使用各自临时实例，避免测试覆盖默认用户配置。

窗口增加“销毁并重新初始化”，只在OFF保存退出且存在配置代时启用。实际确认框列出当前实例，说明默认保留虚拟SD、原固件、overwrite源、历史配置代和运行资料；取消为默认响应。确认后在独立工作线程发布reset墓碑，成功才启动新VM；失败保留窗口/旧状态，不自动启动。发布过程中阻止窗口关闭与其它UI操作，后端仍重新核生命周期/清理状态，按钮禁用不是唯一防线。

GTK组合 **27 tests passed**，包含真实窗口控件、取消确认不重置、不重入、运行中禁用、成功后才start、失败不start和SD指针保留；后端实例/重置组合78项已通过。正式唯一GTK三轮实际验收 `check_gtk_reinitialize.py` 已单独串行启动：真实xdotool点击ON/OFF两轮、实际确认按钮、原reset代和第三次启动manifest、历史配置与SD文件/seed身份，最后正常保存退出。动态结果尚未核，不能把host测试当GTK全链通过。

两位新的只读代理正独立调查原首设完成条件，均不改运行源码或启动VM；主会话将按原指令裁定配置/时钟的真正消费判据，不直接跳页、写完成标志或伪ready。完整设置覆盖、首设完成持久化与最终独立包同步仍待完成。

### 首轮真实 GTK 失败：第二次 SD 导出中断，未到重置

`gtk-instance-4rtis0lt` 的第一轮 `run-oz6k954t` 正常关闭并发布配置代 `993f7b6a82b640948f9022d3e1f84753`。第二轮 `run-br336tbj` 已ready且载入恢复清单，实际点击OFF后SD导出到offset117440512时中断；原console出现QEMU收到signal15，父控制通道报BrokenPipe。原SD结果记录`ok=false/export_data_ok=false`及owner恢复失败，未当作正常保存，更没有继续重置。

目前原日志不能确定SIGTERM来源。主会话没有把它直接归咎为配置恢复错误、UI自动刷新或其它进程。该轮自动结果和未完成导出证据保留。新增独立只读review限定检查本轮提前取消路径；复测驱动仅添加本次Python子进程树的`os.kill/os.killpg`审计及GTK状态转换日志，不改变产品运行保护。审计夹具已用对自身的signal0核验，一条真实调用生成一条记录；派生GTK child语法也通过。新一轮已单独串行启动，结果待核，不能把基本控制器两轮通过扩成最终GTK全链通过。

独立只读review随后交付并结束，结论同样是unknown：OFF导出接收不带取消/超时，成功才置cancel，旧线程未退出时禁止重启，未确认一个能解释本轮提前终止的并发路径。异常finally的SIGTERM以及验收脚本失败后的SIGTERM都可能是后续清理，必须按单调时间区别，不能从存在kill代码倒推第一原因。审计复测仍以原失败为基准保留新证据，没有修改产品保存策略。

### 带审计真实 GTK 三轮验收：已通过

`gtk-instance-u8nktnu6` 使用生产 `camera_ui.main` 与默认launcher，真实xdotool点击两轮ON/OFF，之后点击确认框的重初始化按钮并第三次启动/关闭。原始输出和时间线保留；main直接查看确认框PNG，其列明当前实例、恢复默认/重走首设，以及保留SD、原固件、overwrite、历史代和运行资料。

| run | 实际配置状态 | 关闭结果 |
| --- | --- | --- |
| `run-zacu447o` | 新实例默认，发布代 `b8938c6e196a4deb8dff7c62c563991a`，SHA `29b5c7d43721ba2117371aa61b48741730c9730a1ce3d20703c9425bf0be81f6` | settings/SD保存成功，exited |
| `run-k43fdxy7` | 两份恢复seed确为上代SHA，关闭发布代 `d24771990a16447f96e12759203ce08d`，SHA `dd9d778f825979b835b5a394823580adbac751957fdae7a0d203eae64c5f1c42` | settings/SD保存成功，exited |
| `run-qjk1g9iz` | 确认后reset代 `4b2b509c05674883a502664cb0d75823` 实际存在，启动manifest无旧配置恢复；默认配置重新生成 | settings/SD保存成功，exited |

main逐份重算实际配置SHA并与独立guest摘要相符；三份128MiB SD的实际整卡SHA均为 `61b905001a33941550e4675325db4e02bc6b4d3c813cb98ecfc673bbd0a32727`，原Flush=0/owner恢复、独立fsck全部0。第三次启动的SD seed摘要匹配重置前卡；旧两代backup文件都存在，原卡未改，最终可重新获取实例租约。有限main核验在第三run的`main-gtk-reset-review.json`。

这闭合了同一真实GTK窗口的稳定配置ON/OFF恢复和逻辑重初始化交互。首设完成状态、完整设置提交覆盖仍不宣称通过；之前导出被SIGTERM中断的失败证据和unknown来源继续保留。本次审计成功流程中终止调用属于已完成保存后的正常清理，不用于反推上轮信号来源。

首设只读现场试验已另行串行启动；同时独立包writer只移交这次已验配置功能，明确不带入未通过的SD热插拔WIP。该包仍须重新跑宿主检查和本包真实VM后才提交发布，native通过不代替包内复验。

### 独立包移交与本包动态验收已发布

随后独立包只移交配置功能，main核diff排除SD热插拔runtime/按钮/portgate、保留包内安全短socket路径；本包host259 passed/33 skipped/71 subtests。包内真实GTK三轮为 `run-0dcczdbi`、`run-h3lr1ci5`、`run-56a6nn27`，其保存/两seed恢复/真实确认重置/默认启动及SD和旧配置代保留均由main重新核验，三卡实际SHA一致、独立fsck全部0、原Flush/owner恢复全部通过。本次不借native成功替代包内试验。提交 `47a780e4fdfd24842feeeadef756b1b0d2c4c12e` 已正常push并核remote==local。

之后另有host边界复现：空实例会继承宿主遗留的内部settings恢复源环境变量。独立包先清掉三个内部变量，再仅由当前租约/store生成；空实例、未绑定实例和已有代三项回归均通过，包内受限suite为262 passed/33 skipped/71 subtests。此修复独立提交 `421cda84c47acced87c2937e642868f2e5b02c0c` 已push并核一致；它不改变guest保存协议、也不解释首设重现。native现场观测期间保持运行源码冻结，该同等环境边界修复将在当前观测终态后同步回权威native，原失败夹具已保留。

当前原生短取样结束后已同步该边界修复及三项回归到native，保留其它WIP，实例/控制器/原失败夹具组合115项全部通过。没有在旧VM运行期间改动源码。

首设模型/clock实际观测和12d创建路径另见 `first-setup-frontier.md`：原Backup标志已经保留，日期入口347不能自动等同实际语言页12d。当前有界调查只追311查询记录，不改完成标志。

另已准备独立包非默认参数的最终补验：生产GTK真实选简中和另一日期格式，正常关闭整个GTK进程，再用新GTK进程从同一稳定实例启动；必须由实际配置代及原snapshot/API-file读回保留25/2，main另核原LCD。先前包内三轮是默认值保存/重置，不冒充这次菜单改值。新补验已单独串行启动，结果待核。
