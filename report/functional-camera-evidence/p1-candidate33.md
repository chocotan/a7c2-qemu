# 第三十三跑：首设后进入拍摄模式与原快门输入

本轮沿用第三十二跑的已核定产品binding，扩展温度提示后的原App32输入。两轮均观察到原`ENTER_REC_STILL`、Imaging三连接commit与原AP回复释放；首跑快门前读到`EE_STATUS=1`，原AP确实收到完整半按/全按/释放消息。未观察到自然`0x4038`或capture生命周期，实际LCD仍为触控说明，HUD与拍摄写卡未通过。首跑因16MiB串口上限结束；唯一重试控制了采集日志，延长观察中又在关机流程的`0x4001`前置检查失败后出现真实Imaging3109断言。两轮均QMP quit、rc0、无信号；原失败、异常与只读现场全部保留。

## 范围与输入

授权与覆盖见[scope.md](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate33/scope.md)。本轮没有进一步委派、没有产品源码修改、没有真实设备操作，也没有修改EE/拍摄禁止单元。采用ponytail最小私有驱动修改及docs-generator报告约定（flavor=null）；技能引用的同级tool-index不存在，使用现有已核定工具入口，Evidence契约取实际存在的reverse-skill-router/ops/evidence-finding-path.md。

| 输入 | 身份 |
| --- | --- |
| binding | `derive-prod-4758b35a9afc58fc` |
| derivation SHA-256 | `14b79d178680145206125d55ad229d3a7455bc5a540f15a77609ed8a44d9245e` |
| 派生CPIO SHA-256 | `a59cb874d55c56a2234a856906183406e6ad552d24bdb5d82daaea71b57ec373` |
| QEMU SHA-256 | `b36998138a65b1bd2645ca24bf0dde0c0801d868d1291ec6f9e83ff707d64bad` |
| preload SHA-256 | `f283fa05008a8683ac5bda7b69c21fe284b3b9af9809b4ae65a6a951e10e5440` |
| UDATE KO SHA-256 | `837342f6dd72361cee3e4dd1ffedbff1a7f4951e1f628defb37359c17a6334ec` |
| 首跑 | `04a1` |

保留`MENU_CP_PERIODIC_SERVICE=virtual-config-v1`与此前全部环境变量，仅TMPDIR随任务隔离。周期服务实际只接收/释放配置；日志保留`timer_started=0 original_cp_executed=0 samples=0`，不能提升为原CP周期任务运行。此路线为direct-bootin AP诊断，未执行Sony loader/WBI或物理ASIC。

## 首跑输入与观察

1–37步复用第三十二跑原动作；38–41步按已校验LCD/OCR追加。每个动作对应`action-N.json`、`input-N.raw`、`ui-N.raw/.bin/.png/.json/.ocr.txt`与`stage-N.raw`，原始材料留在受管scratch目录。初始第0帧尚无可导出画面，单独保留错误；不计作有效LCD。

| 动作 | 原输入 | 实际页面/事件 |
| --- | --- | --- |
| 37 | ENTER | `0x1db`自动电源关闭温度提示 |
| 38 | DOWN | 从“设置”移到“以后设置” |
| 39 | ENTER | `0x1f4` Creators’ App连接说明 |
| 40 | ENTER | `0x1e6`触控操作说明 |
| 41 | ENTER | 原`MODE_TRANSITION(mode=2)`及`ENTER_REC_STILL`；三连接完成；创建id=0的565项拍摄页面 |

纠正上一轮对温度页的猜测：`0x1db`原图是“现在设置自动电源关闭温度，还是以后设置”的提示，并非30秒/1分钟计时列表。此次选择“以后设置”，不改变温度参数。

原PIN/CONTROL/ADF连接均观察到`connections=1`的commit，原AP回复释放为`rc=0`、`ap_consumed=1`。日志常含重复的诊断dump与插入的内核printk；`runtime-summary.json`的counts是不同原文本行计数，不是业务事务次数，不可把同一commit的多次打印相加。

首跑readiness使用修正后的事件行解析器，排除grep命令回显。第41步三项为true后提交half1/full1/full0/half0；原按键编码分别为`0x1f1`和`0xa7`，由原`inject-key --app`入口消费。原输入返回成功只说明输入提交，不证明捕获请求或写卡。另在原console观察到`INPUT_EVENT32 n=85..88`依次为`0x1f1/1`、`0xa7/1`、`0xa7/0`、`0x1f1/0`，原AP接收线程tid318确实收到四条消息；这仍不证明自然capture请求产生。

## 首跑实际门控与显示边界

快门前的只读[门控读回](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate33/capture-gate.json)有25项，每项必须有完整BEGIN/RC配对，不写单元。

| 单元 | 值 | 已有原代码规则/含义 |
| --- | --- | --- |
| 总禁止字节/计数 | `1 / 1` | 仍有一个拍摄禁止来源 |
| `EE_STATUS` | `1` | 与此前0不同；当前不命中NOT_RUNNING规则 |
| `LENS_RETRACTED` | `1` | 命中现有source `0xcd`的`IN`规则 |
| USB/network streaming | `0 / 1` | 不命中现有阻断值 |
| focus/zoom init error | `1 / 1` | 不命中ERROR规则 |
| steady/date/two-slot inhibit | `0 / 0 / 0` | 不命中现有阻断值 |
| release without lens live/shadow | `0 / 0` | ENABLE；与“镜头缩回”是不同来源 |
| HAITA no-lens/steady/media/relay | `0x1406 / 0x4b97 / 0x4ecf / 0x526a` | 与已有文档列出的这些来源的阻断枚举不同 |

规则引用[既有拍摄门控调查](../capacity-recordable-frontier.md)，不是本轮重新逆向得到。`LENS_RETRACTED=1`是本轮明确的新前沿；它与总禁止计数1相符，但尚未用原状态生产者/完整事件证明其来源，不能直接把单元改成0当作修复。

第41帧与快门后第161帧完整容器SHA均为`28cc3131f00c32ad93af6e47bbc38392c19c9d3f822574e44b72efcc54f5f3b7`，sequence均为1354，像素仍是触控说明。拍摄页被创建和进入拍摄模式，不等于该HUD已呈现。首跑不能归为“HUD内完成拍摄”。

首跑没有原ASSERT_CALLER、没有负值P18 send结果或未处理CP opcode的新证据；自然`0x4038`、`natural-request-owned`、JPEG和写卡均未观察到。mailbox/debugger/broker均未接通。最终错误为`RuntimeError('串口日志超过安全上限；保留原日志及 VM，禁止继续发送命令')`，这是采集限制，不能归为固件崩溃。

## 唯一重试：显示前沿与首设状态分开记账

重试run为`1d25`，输入binding、QEMU、CPIO与产品服务全部保持；只改私有采集：控制台`dmesg -n1`、省略32/36/37重复被动采样、保留初始与最终被动采样，原16MiB串口上限不变。复用首跑已证实的1–41步，快门改为显式`capture`动作并继续用修正的事件行readiness。脚本与变更前后SHA在`retry-1/retry-plan.json`，没有改写首跑失败。

重试再现`ENTER_REC_STILL`及PIN/CONTROL/ADF各一次commit与原AP回复释放。42 MENU由原AP接收并创建`0x346 → 0x2ca(count44)`菜单页；43 MENU返回`0x343 → id0(count565)`拍摄页。原UI事件状态已离开首设，能切换菜单/拍摄页；实际LCD却仍为触控说明。41–43帧sequence都为829、pixel_source_seq都为799，完整容器SHA均为`fe21eb43af438af538cf6db6a5e2b00445606a29e6a589418e116be5643c4749`。第40帧sequence818、pixel_source_seq同为799；后续容器元数据曾更新，但像素来源没有继续推进。

显示与拍摄方面有两个独立前沿：首跑原拍摄门控`LENS_RETRACTED=1`；两轮原UI页面变化后，当前headless导出的像素仍停在触控说明。既没有证明是原AP不再提交像素，也没有证明是虚拟GPE/OSD消费未完成，须沿显示生产者→提交→完成分别追查。不能把创建拍摄页面、容器读回成功或EE状态值1当成实际HUD展示。重试未补发快门，44 finish关闭输入窗口，保留原样等待与退出证据。

最终被动采样为`EE_START_ENABLE=1 / EE_STATUS=0 / BACKUP_SYNC_PENDING=0 / SHUTTER_AGGREGATE=1`，菜单切换后的引擎状态没有保持首跑快门前的1，不能宣布EE持续运行。重试没有发送快门。

重试实际最终错误是`FirmwareFault`。原console:114913先记录`set_pre_power_off_seq`，随后创建`0x309`关机页；114919–114921的同一tid395原请求audit sequence45为`dest=0x90030001 source=0x80020002 bytes=12 raw=050001404e00008000020002`，即cmd`0x4001`。紧随的CP302C只读前置检查为`accepted=0 video_AP_consumed=0 OSD_AP_consumed=0 audio_AP_consumed=0 OSD_live=0`；原UI路径进入`scr0039_shutdown`，114930出现`infra_wrapper_imaging_ipsx_sp_pp_branch.cpp:3109`，之后有原异常提示和只读异常采集。

当前`menu-observe.c:10696`的functional `0x4001`路由先检查12B长度和`0x80020002`来源，再要求`cp302c_no_transition_predecessors_ready()`，失败直接返回`-ENODATA`，尚未进入zoom dispatch。长度和来源与本次原请求匹配，guard日志同线程/同顺序，支持这一拒绝路径；**具体负返回值由源码与现场匹配推导，没有另一个独立运行日志直接打印该负值**。源码SHA为`1deb8b80f87c4d08c6400bc47f205d73113c5cd2b28aa697ddd8cb9f19e68bf8`。下一步应核对关机/恢复场景的4001路由和资源合同，不应删除guard或将这个断言称为快门触发。前置的`sequence_still_record suspend/run`、parentchild release-setting日志记录了时间顺序，不能单独证明触发因果。

首跑仅有`FUNCTIONAL_JPEG_CODEC operation=enable rc=0 sequence=0 bytes=0`初始化标记，不是JPEG编码或照片输出。两轮均没有把codec启用、连接commit、无断言或输入send0提升为JPEG/写卡通过。

| 最终核收点 | 首跑04a1 | 唯一重试1d25 |
| --- | --- | --- |
| 原sequence_boot返回、周期配置 | 通过 | 通过 |
| ENTER_REC_STILL / 三连接commit | 1 / 1,1,1 | 1 / 1,1,1 |
| 实际HUD | 未确认 | 未确认；原菜单/拍摄页切换但像素来源停滞 |
| 原半按/全按周期 | AP接收4条 | 未补发 |
| 自然4038 / capture生命周期 / 照片 | 未观察到 | 未观察到 |
| mailbox / debugger / broker | false / false / false | false / false / false |
| 最终错误 | 16MiB串口上限 | 关机流程Imaging3109断言 |
| QMP quit / QEMU rc / signal | 匹配唯一ID / 0 / 无 | 匹配唯一ID / 0 / 无 |
| driver rc | 2 | 2 |

重试console SHA-256为`518e7e8aa0ea9abe06132a89f55d0081d7e2a81364093c52e7574eea9af3936a`；两轮summary、原ulog/异常输出、逐帧hash、退出与原profile账本均各自保留。[new-frontier.json](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate33/new-frontier.json)汇总下一消费者所需的精确字节、线程、来源与覆盖限制。

## 证据与路径

| Evidence | Finding | Path / 下一消费者 |
| --- | --- | --- |
| E1：首跑`candidate33-plan.json`、binding/guest SHA与整卡读回 | F1（validated, high）：当前已核定observer/KO和RAM卡实际被消费 | FD/生产derive→原AP启动；下一轮继续使用同一身份合同 |
| E2：`stage-38..41.raw`与对应有效LCD/OCR | F2（validated, high）：温度提示与后续说明可用原输入推进，进入原拍摄模式 | 以后设置→Creators说明→触控确认→ENTER_REC_STILL→三连接 |
| E3：`capture-gate.json`、`shutter-cycle.json`、`shutter-input.raw` | F3（candidate, high）：当前存在镜头缩回的拍摄禁止，未产生自然捕获请求 | 查原source0xcd状态生产者与虚拟CP/LIF发布链；不清门控绕过 |
| E4：`ui-41.json`、`ui-161.json`和有效容器 | F4（validated, high）：首跑未证明HUD实际显示 | 核对显示提交/完成与原UI等待；不能以id=0创建代替像素 |
| E6：`retry-1/stage-42..43.raw`与`ui-40..43.json` | F6（validated, high）：原UI能切换菜单与拍摄页，显示像素来源未继续推进 | 追原显示提交与虚拟消费/完成；HUD未验收 |
| E7：重试console:114913–114930、原ulog/异常、源码4001守卫 | F7（candidate, high）：关机4001命中functional前置检查失败，是新的模型合同边界 | 核对4001的关机/恢复调用语义与资源owner；不移除guard |
| E5：两轮`attempt-1.json`、`final-audit.json`、原QMP退出收据 | F5（validated, high）：两轮owner正常退出并释放租约 | quit唯一ID回复→rc0→launcher/端点消失→原失败证据保全 |

首跑console SHA-256：`b03a54b058710c34e16f9beab9a3268058d96886d5f4a9905d3d51d71ccb7aab`。正式核收为2工作线程、2检查组，分别核原始运行/帧和owner/存储；不是两次拍摄验收。

## 复现与保留

原运行入口是scratch任务内`prepare.py`、`start.py`、`control.py`和`finalize.py`。脚本采用独占新收据，不能在原目录重跑覆盖；重现须新任务目录并保留相同输入SHA、生产derive/FD合同及隔离profile。部署、原始失败、原帧与退出证据均保留，回收前须核清消费者与活引用。

每轮2工作线程、2检查组完成独立核收，两轮合计4检查组；不是4次拍摄验收。两份run的QEMU/launcher、租约、socket/FIFO均核收退出；`qmp-exit-unknown`文件名不代表退出失败，原wire回复与记录的唯一ID另行比对。新增保留实占、文件系统可用字节与前后净变化由[最终交接收据](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate33/handoff-final.json)和[逐项存储账本](../../../../scratch/a7c2-capture-p1-runtime-20261115-candidate33/storage-closeout.json)记录；按device/inode去重的st_blocks不等于独占物理增量。实际回收0B，未执行回收；原失败、两份原始运行、frame/profile和重放脚本保留给父会话核收及镜头/显示/4001新前沿调查，回收须先核可恢复性与活引用。

未验证原CP计时器、Sony冷热启动/WBI、真实ASIC或物理相机；本轮没有JPEG_ONLY_PASS或写卡通过结论。
