# VEF SetPath 0149：路径1的控制消费与完成合同

2026-10-25，范围为公开 ALLLANG 2.01 与隔离 native QEMU。
**虚拟NoMem控制子集已通过原AP实际消费，下一前沿为ADF 0323。**
`run-ba2cnxt9`完成两阶段路径应用、精确1149回包与原AP释放；EE仍0，无JPEG/MP4。
不将此提升为原CP硬件/帧/拍摄成功。下述首次非空拒绝保留为历史对照。

### 首次运行准入：run-sfl0pwn2

同一已验收a0d候选、全新目录卡，observer `f46a9bead885f4ebb0f4ad01e3c3db0177ba31d5df8d42321721e1f8a5c464ac`。
原Common381的有效0149/path1被接收；实际共同事务下的读回为：

- native DMM已绑定，两个slot均 `allocated=1/open_count=1`，所以**不满足已知空态**。
- 控制404池 `bound=1/live=0/faults=0/allocations=releases=1`。
- 连接格式已消费、backing已释放、原连接回复已释放，blocked=0/faults=0。
- VEF16与PinMem13对象均已初始化到正确owner；pending/live/retained/fault均0。

`FULL_VEF_RESOURCES_REFUSED` 后只有 `FULL_VEF_PATH_PENDING`：原请求/92840747 owner保留，
reservation_rc=-1021，reply_queued=normal_completion=ap_consumed=0；没有APPLIED、QUEUED或REPLY_FREE。
没有放宽判据、释放未知缓冲或发成功状态。

Still入口后与快门后两份无暂停读回均为group0当前2f、stop0、各自前后组字节一致；
queued分别31、40，跨时点不当作静态同一个队列快照。Common用户候选和原kernel收包栈
继续匹配0149；EE0、Backup pending0。此前group0空current/prompt来源的采样bug已修，
这次实际取得字段，未给旧run回填。

HUD/自然快门输入与原Fsys导出分别完成，但只有database/XML/INPUT。
`vef-pending-assessment.json`核对3文件全树摘要、clean commit、owned进程组和QEMU退出、
主锁及目录租约释放；没有SIGKILL。该成功导出不能提升NoMem完成或拍摄标志。

当时的下一未知是这两块unit63a缓冲的实际创建者、用途和NoMem资源槽的隔离关系。
原DMM日志此前未镜像控制台，不能从缺日志推断所有权；后续联合证明及实际验收见下文。


2026-10-25后续 `run-glsda8ag` 已在新增DFS候选恢复HUD、自然快门和原Fsys导出。
Still入口后及快门后的两份无暂停采样都确认Common381边界前后不变，
原kernel=`osal_rcv_msg_tmo`，用户栈候选链：
`34e5788 ← 34e6e58 ← 34c6d04 ← 339d59c ← 33aaa3c`。
同期EE为0、Backup pending为0，精确请求仍 `0d2049010a0001800100`。
原始栈未正式unwind，collector仍保留current_blocker_proven=false，不冒充原子/完整调用帧证明。
这比此前只有请求记录的前沿更强；完整SD读回只有数据库/XML/INPUT，仍无拍摄文件。

共同资源gate `device-models/vef-resource-guard.{c,h}` 已实现并接入sender；首次VM已按非空状态拒绝：
只覆盖905a0048/90590818/9061003c三个已核实资源变更入口，进程owner在任何mutex之前检查，
拒绝fork继承所有权；自动cleanup覆盖所有早返回。
初版空态要求native DMM已绑定且两槽无allocated/open、控制池已实际分配并全部释放，
格式消费/连接回复释放完成、VEF与PinMem的正确owner/初始化及消息工作全部排空；
后续只按上述强证明加入首次Speech外部域，其它条件全部保留。
已通过ASan/UBSan判据反例、三入口并发、早返回与持锁fork测试。
NoMem路径模型 `device-models/vef-path-device.{c,h}` 已实现两阶段、资源槽、请求世代和独立回复所有权，
只支持路径1、单outstanding reply、已确证空资源的虚拟实例。显式 `A7C2_VEF_PATH=virtual-nomem-v1`
需DFS/TCIN/Backup自然profile，拒绝YC/其他pipeline/ready注入及旧UI强制激活开关。
当前相关95 tests + 44 subtests通过，包括28个路径sanitizer情形、资源gate并发/fork/早返回、
原始CP选择常量`0x38`与消息构造字节、默认关闭与VM前准入。
首次独立审查发现父constructor只绑定共同gate、未绑定路径模块，子进程首次调用会先触发继承回调；
已同时绑定两个PID，并加“不先reset/snapshot就fork”的零回调反例。独立增量复核确认关闭，
28个路径C用例由审查方另行通过ASan/UBSan。原ABI构建/源码身份和真实链接核对通过，
包含共同gate enter/leave、两个PID初始化、资源predicate和路径处理器。
这仍不证明整个guest DMM空闲，也不把原CP构造器值当成当前CP运行值。

### AP传输拒绝和故障停驻

原AP `34e552c` 的调试原型是void `send_and_wait_cmp_i`，不是返回业务错误码的API。
`34e56e4` 发消息后，只在发送返回0时继续收包；非零经日志/延迟后在 `34e5774 → 35aa4b4`
进入 `__assert_fail`。它没有把错误写入初始清零的reply+8；也不会沿正常路径将这个零误判成功。
只有实际接收之后，`34e5798` 才复制12B回复。native既有assert探针仍tail-call真实assert，未改成成功。
原status mapper已核对：raw0与005a0000均映射API0，ffffffff映射109。
FFFFFFFF只适用于已验证的CP内层发送失败，不泛化成资源或不支持请求的业务错误。

因此，本模型对有效10B路径1、正确caller且已经接受的请求，若真实资源reservation拒绝：
在私有锁中保存原请求/owner并锁存fault，清busy，返回OSAL0仅表示所有权转移；
**不分配、不发送12B回复，不递增世代/应用/queued，不改路径或完成阶段**。
`FULL_VEF_PATH_PENDING` 明确记录accepted1/reservation_rc/reply_queued0/normal_completion0/ap_consumed0。
AP会保持等待，这是故障停驻，不能验收启动。未知或非空资源不会被success带过。
保留原请求的错误owner或释放失败均不会丢指针，正确恢复释放不清fault、不增加AP回复消费。

其它格式/范围错误与发送前错误仍返回负传输状态，可能触发原AP断言；不得称作“AP正常收到错误回复”。
实际回复入队之后原请求释放失败，则由模型保留并返回OSAL0防止caller double-free，clean_completion仍false。

## 已证明的外部Speech资源域：实现与原AP消费验收

后续 `run-dru5iey2` 在同轮完成了初始Speech的独立请求/原4个saved-return-PC、
首两epoch1/2、creator1/1、allocations2、lifecycle_changed0，以及原AP表两次144B一致的联合验证。
该run仍使用旧pool-empty判据并保留pending；完整SD三文件、摘要和全部资源退出已核验。

资源guard当前只新增一个具体已知外部域，并非放过任意非空池：
DMM需已绑定到同一有限native pool，两槽必须是上述首次分配，完整CP marker/u16 handle、
generation1、opens1、epoch/creator均匹配；原AP表地址、ID1a/1b、两份完整相同字节、
handle/长度/CP地址逐项匹配。任何未知、重初始化、引用变化、部分、篡改或epoch33等复用均unknown。
原NoMem自有四个无效缓存、extra/context/work/phase/世代检查不变，control/connection/registry排空检查不变。

`full_vef_resource_dmm_domain` 明确返回UNKNOWN/EMPTY/SPEECH_INITIAL；
`full_vef_resources_admissible` 替代旧的全池empty检查。
外部Speech缓冲不释放、不清零、不重映射；gate只保护metadata，不冻结其数据。
`foreign_speech_kept / data_frozen=0 / global_dmm_idle_verified=0` 在资源日志中区分。
相关127 tests + 31 subtests通过，含输入与完整1MiB backing不变、未知creator、
真实引用1→2→1、历史复用、原表变化、fork和共同事务反例。
相关127 tests + 31 subtests、独立审查3cd及ARM ABI构建/源码链通过。
项目规定的旧工具离线/mock回归另为244 passed / 1 skipped / 58 subtests，
按约定排除缺Cryptodome的remove_dat_signature和jiritsu_crypto；脚本同步检查也通过。

### 原固件联合验收 run-ba2cnxt9

observer `c0c435c05c8c4f2bab53fc321a9de03d3af6bea618bc05d6b0416d6923490365`，
沿用已过DFS/Backup/目录SD检查的a0d候选，不替换e235生产二进制。
`nomem-qualified-evaluation.json`核验以下各标记恰一次：

1. 原10B path1请求，动态source81cf61c9；同轮Speech强证明与domain2准入，
   slots/opens仍1/1，foreign_speech_kept1/data_frozen0，所有其它共享状态排空。
2. NoMem generation1/inner_generation1、stage0_done1/stage1_done1，path1/phase2/state2、
   property2/selection38、四cacheFFFFFFFF及extra/context/work全0；dmm_release_calls0。
3. 内层20B `0220010014000100010001000000000000000000`，
   内层完成 `022001100c00010000000000`，外层E0映射为005a0000。
4. 精确12B `0d2049110c00018000005a00` 实际queued到动态caller，原请求释放rc0、clean_completion1。
5. 原AP释放该回复rc0、retained0/faults0/ap_consumed1，说明waiter真正消费完成。

无NoMem fault/pending/unsupported；外部Speech未free/clear/remap。
原Fsys三文件全树字节/hash、clean commit、全部owned进程组/QEMU退出及双锁可独占均通过，无SIGKILL。
不把该控制子集提升为原CP硬件/帧/拍摄成功。

下一条实际请求为12B `0d2023030c00018000000000`（ADF proc path0/mode0/format0），
Common两次同轮候选栈 `34e5788→34f26e4→34c6e84→339d61c→33aaa3c`，
已离开旧VEF SetPath收包位置。Still与快门后group0仍current2f/stop0，排队31/40，EE0。

## 实际前沿与证据边界

`runtime/analysis/menu-runs/run-4hvp1_ue` 已消费 TCIN0429，原模式2f与Still入口首次执行。
Common tid381在成功消费HDMI0117后发10B：`0d2049010a0001800100`，
destination=`92840747`、动态caller=`81cf61c9`。
AP `34e6d84` 的原调试名是
`infra_wrapper_bb::detail::vef_set_path(const vef_set_path_in_t&, vef_set_path_out_t&)`，
直接包装器call在 `34c6d00`。`34e6e54 → 34e552c` 期望12B，
`34e6e58` 读取回复+8并经 `34e349c` 转换。

payload是u16路径编号，当前为1；同一原构造器还可能生成0、f、12、13，
不能按10B形状把它当成bool。此后本轮发生UPM_DFS/RCU stall，快门前整体超时。
没有取得该线程的晚期收包栈，不能把请求记录或DFS缺口单独当作完整阻塞因果证明。
原GTK/SD验收保留失败；部分磁盘证据及正常退出见 `report/tcin-inactive-config.md`。

## 原 CP 分派与内层生产

原件 `cpapp-b.bin` SHA256：
`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`。
以下CP地址均为VA，raw=`VA−108000`。

- 0149不在 `69adb6` 扫描的 `d16818` 124项cache表内；switch表
  `1c547c:6902 → 1c58bc` 产生内部请求b3，发到 `92840748`。
- 内部表 `1c413c:5d03 → 1c46d0`；普通路径 `1c4ddc → 1cee40`。
- `1cee62:2389` 读取 `u16 request+8`；`1ceea6 → 6ae3f8` 向 `905a0048`
  发送20B内层 `2002:0001 / length14 / flags1 / path@8`，回复地址 `928407b9`。
- 内层发送成功只是接受；此处释放请求，不立即产生1149成功。
  发送失败折为 `ffffffff`，经 `1c4dfc → 69cccc` 回复。
- 另一分支 `1c46d0 → 6a3684` 读 `01acad14`，等于1直接产生 `005a0000`；
  该字段语义与本轮值未知，不能借此跳过路径工作。

## 路径1实际需要完成什么

表 `10f5ff0:70c97801` 将路径1选择到对象 `0178c970`；静态构造
`6fe872..6fe884` 写vptr=`d28908`，RTTI为 `VEF::PathProcessNoMem`。
这不是“无内存所以无需工作”的命名推断；具体方法已查：

| 具体入口 | 效果与边界 |
|---|---|
| `6ec084`，对象slot+c | 读取资源索引1、2的0x90B描述符；handle=`ffffffff`才可跳过释放。非空时调用 `6f2cc8(desc,-1,-1,1)` 再写回完整描述符 |
| `6ec0ae / 6ec104:4798013019d0` | 检查上述无效handle的具体字节锚点 |
| `6f2e4c` | 非空资源走真实DMM命令23，152B，dest=`0061003c`、source=`905a0048`、handle@8、option@16=2，经同步请求/回复检查u16+2 |
| `6ec13e:0120c8f800000020` | 资源处理后写 `done=1`，返回0 |
| `6ec14e:0120186000207047` | 完整函数仅8B，同步写done=1并返回0，无新像素/传感器回调 |

原NoMem调用者忽略资源释放helper的错误；虚拟实现仍须保留释放失败所有权，
不得靠清空handle制造成功。具体路径控制切换可以不等待新帧，但不能跳过资源和请求世代。

`SubsystemAccessor` 的静态构造 `700e7c → 700316` 以 `S=accessor+8`：
current path=`14`、state=2、phase=`1`，不是phase0；四个资源handle初始化为-1，
世代/相邻字段清零，额外资源标志 `S+884=0`。
这是构造器证据，不等于运行时CP读回。

首次Activate需处理前一路径、递增世代，并在路径14时转phase0。
`6fb386..6fb394` 比较请求高16位世代与当前世代；旧请求不能借用新状态。
PathManager `6fdf0a` 更新 selected object `+4728`、property `+472c=2`、
path `+4730=1`，再调用上述两阶段方法。
`21342c` 对path1使用默认选择表 `010f7318`、选择数`0x38`（`2134e2:3821`），未提交像素；
不能把该控制消费升级为NoMem数据面已经工作。

`211c66:0221416029880160` 才将路径状态写为 `state=2/current=requested_path`，
随后生产完成。额外资源标志 `S+884==1` 时还需释放 `S+87c` 所指资源；
前路径上下文 `+8d8` 的保留工作也不能忽略。

## 精确完成、状态翻译与所有权

VEF任务 `2137d6..2137e0` 从 `905a0048` 接收；上下文C分别保存allocator source、
envelope回复地址 `C+4=928407b9` 和内层请求 `C+20`。
命令对象slot+60=`6fd19e` 被 `211cd4` 调用，构造8B头+4B执行状态E，
经 `70109a` 发送，allocator source=`905a0048`。
E=0时内层精确体：`022001100c00010000000000`（2002:1001）。

`69929a` 是 `928407b9` 接收循环。decoder `1c60a0` 检查外封magic，
提取内层指针；`1c6256` 匹配1001，`1c6358` 选择内部完成2a6。
`1c6636 → 1c66a2` 的翻译是无条件：

```text
outer_status = E | 005a0000
```

没有raw0例外、低字mask或查错表。故E=0对应外层 **005a0000**，不是TCIN的raw0。
原外层回复体为 `0d2049110c00018000005a00`。
内部2a6经 `1c3344 → 1c4e88 → 1c5096 → 69cccc`，保留该状态。
原AP请求的caller通过每b3 source FIFO保留，完成时动态弹出；
`1c793a` 设置回复source=`92840747`，`1c7960` 发给原caller。

VEF完成运输为24B envelope+12B内层=36B，allocator metadata另在body−c。
成功解码会保留该外封，处理外层完成后由 `1c52be..1c52cc` 释放；
28B内部事件另行释放。decode返回0没有检查内部enqueue结果，不能仅看decoder成功。

## native 资源准入仍需补齐

`run-4hvp1_ue` 构建清单与当前pin/DMM模型源码一致。该run确实分配过
unit404、handle8000、512B**控制缓冲**，VEF消费格式，双方释放后 `live=0`，
原等待线程也释放连接回复；不能要求“从未分配”。

| 当前实现 | 已有证据与缺口 |
|---|---|
| `device-models/pin-buffer-owner.c` | 16×512B控制池有锁内snapshot，可查bound/live/fault、allocations/releases；不是帧缓存 |
| `device-models/pin-connection.c` | 已有format_pending/blocked/fault、已消费格式、buffer_released与原reply_free统计；私有锁 |
| `device-models/vef-device.c`、`pin-registry-core.c` | 管pin身份/peer/state及消息租约；不拥有NoMem cache、额外资源或framework context；state0连接合法 |
| `dmm-service.c`、`menu-observe.c:dmm_send` | 独立unit63a、2×512KiB缓冲，cap_lock保护；缺公开池snapshot与VEF归属；旧日志未镜像console，不能以未见日志推断为空 |
| `dmm-unit-config.c` | op18配置只读查询只分配消息，不分配DMM数据缓冲 |

原dmm.ko也已加载；上述接口不能证明整个guest DMM空闲。现有snapshot分别释放私有锁，
连续读取不是跨owner reservation，不能据此实现无竞争的SetPath完成。

当前实现明确拥有virtual NoMem的缓存handle、额外资源和pending context，并按共同事务保护路径请求。
首次运行已证明不能仅按构造器或registry值认定整个tracked资源域为空。
下一步须闭合两块live DMM缓冲的归属/隔离，或对确实归属NoMem的资源实现实际释放；
不能释放外来handle、忽略open引用或因无帧后端就把非空状态清零。