# 首个 enabled/mode1 histogram 功能事务

本组件为 `virtual-functional-camera-v1` 的首个 `0148` 事务提供独立 owner：验证真实桥接回执1192B，再释放原请求，复制四段真实返回数据并发送独立1148 ACK与210c通知。原 **290个场景 × strict / ASan+UBSan 的 host组件测试**及公开原件44窗口读回校验全部保留；当前 pytest 为8项，另覆盖真实生产 record stdout→内容checker组合与serial边界。与限定 VDF/BB/allocation/evidence 选择合计 **26 passed /668 subtests passed**，codec原ABI/pin单项通过。fixture没有运行core、原AP或VM；真实core组合、原AP接收和UI显示仍待主会话整批验收。`capture_verified`、物理ASIC、原CP/FIFO/RTOS、UI应用与连续histogram均保持false。

此项只新增 [owner接口](../../runtime/analysis/device-models/functional-histogram.h)、[owner实现](../../runtime/analysis/device-models/functional-histogram.c)、[C组件fixture](../../runtime/analysis/device-models/test-functional-histogram.c)、[pytest](../../runtime/analysis/test_functional_histogram.py)和本目录。调用方、broker、bridge、core、ABI、build和profile由主会话集成。本组件不要求CP mode1完成；使用主会话既有all13/resource guard。

## 本机复现

在 `report/2026-10-17-qemu-native-camera/runtime/analysis/` 下执行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider test_functional_histogram.py -q
```

测试只编译专属临时host binary/object，不构建主模型，不连接VM。strict参数为 `-std=c11 -Wall -Wextra -Werror -pedantic`；另一个构建启用AddressSanitizer、UndefinedBehaviorSanitizer和leak检查。公开ALLLANG原件需位于既有 `menu-root/usr/lib/appFw.so` 和 `menu-root/cp/cpapp-b.bin`，不随本组件附带。源证据及验证摘要见 [source-pins.json](source-pins.json) 与 [validation.json](validation.json)。

## 精确范围与软件政策

| 项 | 合同 |
|---|---|
| 原请求 | exact12B `0d2048010c00018001010000`，enable1/mode1/flag0/pad0 |
| 原请求目的Q | `0x92840747` |
| 原请求sourceD | 原AP global `*0910fa20` 的实际运行值；不能固定为81cf |
| canonical8 | `4801040001010000`：LEu16命令0148、LEu16 bodybytes4、原body4 |
| ACK | exact12B `0d2048110c00018000005900`，目的D、metadata sourceQ |
| 数据通知 | logical1034B，header `0d200c210a040180`，+8 LEu16软件selector1 |
| 四段数据 | +0x00a/+0x10a/+0x20a/+0x30a，各256B；从真实result+168完整复制1024B |
| 有限性 | 只支持本进程首个成功enabled/mode1事务；mode0、disable、re-enable、未知body和第二次0148拒绝 |

功能profile明定四段为软件Y/R/G/B的256个u8柱高。core应从同一份640×480 RGB sink pixels计算 `Y=(77R+150G+29B+128)>>8`，每段独立按 `height=(count*255+peak/2)/peak` 归一化，再完成独立缓存读回、frame retire及generation commit。selector1是本软件四段政策，不能由原请求selection推为物理语义。本owner只消费真实桥接结果，**不自行生成RGB、bins、JPEG或MP4**。fixture使用各段不同的哨兵模式测试复制与生命周期，其FNV不是一帧真实RGB证据。

原件已证的是四段各256B、通知长度及AP复制/所有权；尚未证明Sony物理通道名、u8 bin解释、1204入口/callback注册和event0xd5后的UI property绑定。不能把上述软件政策称作Sony原格式或完整UI histogram。

## 主会话集成接口

1. 启用profile后，在本进程调用一次 `functional_histogram_owner_init()`。它只初始化本地owner，无RPC、无AP/model位变化，无reset。
2. 主会话在已核对的原callsite独立读取原AP `*0910fa20` 两次，要求两次值均等于实际请求metadata source，再调用 `functional_histogram_bind_queue(source)`。bind只接受非0、非UINT_MAX、非本SID，一次不可变；相同ID可幂等绑定，不同ID返回`-ESTALE`。busy返回`-EBUSY`，fault后返回`-EPROTO`。bind参数本身不构成native验证，原readback应由主会话单独prefix记录。
3. 在既有原请求hook中调用 `functional_histogram_dispatch(dst, request, io, guard, enabled, &result)`。无关请求返回0；匹配但拒绝返回1且result负值，原请求仍归caller。只有完整模型回执、请求原字节与metadata读回、guard复核全部成功后才接管；接管后result0包括后续真实free/allocate/send失败。错误与retained leases须查看snapshot，不能将result0等同AP消费。
4. main提供 `fcam_bridge_histogram(origin, input8, output1192, metadata)`。生产owner的此符号保持未定义依赖；没有production fake。它不调用INIT或其它operation；主会话负责真实桥接的PID、mailbox、nonce、预算与输出完整性。
5. 仅在真实原`rcv`成功后调用 `functional_histogram_observe_receive_cycle(dst, ptr, source, bytes, &ticket)`。成功返回1并写入**首次保存且不变的cycle1**；原receive线程可以接到1148后将其指针移交原promise/future。
6. 原free hook调用 `functional_histogram_release_cycle(dst, ptr, initial_ticket, real_free, record, &result)`。ACK的原receive线程可以不同于sender，但原free必须由**原0148请求sender TID**执行；通知free必须由**该通知实际receiver TID**执行。main须把最初保存的ticket移交waiting caller，禁止free时从snapshot刷新ticket。`real_free`必须是dispatch的`io.release`同一函数。未知指针、已退休地址返回0；活alias、无receive、错误metadata/原字节/线程/目的地均不能触发原free。

owner没有通用registry、worker、daemon或streaming框架。snapshot、IO、guard、logger的调用均在私有mutex外；fork继承owner会在进入继承mutex前返回`-EXDEV`。NULL、对齐、地址溢出、输出与输入/私有状态/常量/活lease重叠均作边界拒绝。RPC接管前的借用原请求、调用方result和活动IO/guard也受保护；原请求free0后该地址不再因借用记录而被保留。

## 模型证据与所有权

模型回执严格检查：`used==required==1192`、token0、ABI1、非0且metadata与wire相同的instance、原canonical8的FNV、活动921600B、640×480/stride1920、source/sink FNV非0且相等、endpoint90590819、两mask1、class6、enabled1、config-readback/commit/frame-consumed/retired均1、status/reserved0、当前route1/pins5,5、canonical8全字节读回、config/frame各自`before+1`且不溢出、非0 lease generation。每段须有软件peak255；不能接受全0或未归一化的四段成功回执。owner验证回执的全部结构，再实际复制bins并读回独立通知；像素到bins的真实计算必须由主会话的core组合测试证明。

| lease | 实际顺序与消费条件 |
|---|---|
| request | 完整模型验证后owned；按Q真实free0后退休；原sender TID；free失败粘滞且不隐式重试 |
| ACK | request free0后独立allocD12，完整copy/sourceQ/readback；先send；实际receive且原sender真实free0，且最终send0，才ACK_AP_consumed |
| notification | 独立allocD1034，完整copy1024/sourceQ/readback；ACK send0后send；实际receiver真实free0且最终send0，才notification_AP_consumed |
| overall | 两回复各自consumed、request free0、模型完整、busy结束且无fault，才AP_consumed；这只表示两份OSAL消息被消费 |

`send0`只表示queued。ACK可以在send回调返回前receive并由原sender free；通知也可在send返回前由foreign receiver receive/free。send返回后不会再解引用可能已释放的envelope；send随后失败保留实际freed/queued状态，不回滚为虚假live指针。失败allocate若返回独立nonnull指针则保留该真实lease；活地址/私有状态/常量alias只记录原返回地址并拒绝拥有，不能free它。所有错误均sticky，不隐式cleanup/free重试。

原request成功free后的同址新ACK是合法的新分配；仍活的ACK与notification不得重叠。所有lease退休后，旧诊断地址不继续owned，foreign消息同址复用返回0。本owner仅一次事务，不更新周期或刷新旧票据。

`FUNCTIONAL_HISTOGRAM_*`日志记录原12B、canonical8、真实回执1192B的FNV及metadata、完整通知1034B的FNV/selector、四段各FNV、before/after generation，以及三份lease的allocate/queued/received/free TID/rc/retained/consumed。snapshot保留完整回执与通知原字节，所有physical/UI/capture位保持0。

当前 `record()` 在同一mutex中捕获完整state与唯一递增的非零 `snapshot_id`；logger和全部IO仍锁外。主行 `event_role` 由调用点传实际角色：request1/ACK2/notification3，COMPLETE或非lease0。三条LEASE带相同pid/cycle/snapshot_id。不同线程可互相插入行，内容checker必须严格join后按ID恢复capture顺序；不能靠四行相邻、原始行顺序或flag delta猜角色。serial受private-alias保护，fork先拒绝再考虑mutex；耗尽u64时置fault并只发`RECORD_FAILED snapshot_id_exhausted=1`，不回绕正常ID。

新增组合测试直接把生产 `record()` 的stdout交给现有证据helper和 `check_transport` / `check_histogram`，不再只比另一套golden日志。模型1192B与前驱proof/global-binding仍是明确的HOST_TEST组件输入；真实core/AP组合由parent另验。pthread/condition确定性覆盖foreign ACK的主行延迟三条LEASE、sender SEND及notification交错、inline free，以及SEND捕获时真正receiver仍在锁外验证的releasing1。SEND只证明其实际角色发送返回，实际RECEIVE仍须live pointer，AP_FREE仍须正确线程和free0；最终send0与两份实际receive/free齐备才consumed。真实日志的错ID/缺lease/错角色/旧allocation/重复free/缺receive/FNV/假busy/假consumed变异均拒绝。完整复现命令、结果及E/F/P见[证据checker本次集成记录](../functional-camera-evidence/README.md#快照交错集成修复本次)。本次没有改full_snapshot/evidence20a6或旧73 zero golden。

## 验收矩阵

| 能力 | 本次证据 | 状态 |
|---|---|---|
| exact首个mode1识别、sourceD不可变bind | strict/SAN、错误sourceQ/D/0/未绑定与body/length拒绝 | 组件通过 |
| 真实结果1192B结构验证 | 151个逐字段字节破坏及metadata、canonical、hash、retire、overflow等负例 | 组件通过 |
| 四段数据独立复制到210c | 不同段哨兵、末byte变化、copy-corruption及full readback | 组件通过 |
| future ACK线程合同 | foreign receiver→原sender free；foreign free拒绝 | 组件通过 |
| notification receiver free | foreign receiver/free；错线程、错source/len/wire/dst拒绝 | 组件通过 |
| 同锁快照ID、显式event_role与交错logger | 真正record stdout→原内容checker；strict/SAN、inline、releasing overlap、ID/role/内容负例 | 组件集成通过 |
| 原free/alloc/send失败、inline时序、地址复用 | retained指针、free不重试、send返回后无UAF、退休不拦截 | 组件通过 |
| 原件公开字节证据 | AP/CP全SHA、44窗口14624B含重叠、VA/raw映射、报文字节 | 读回通过 |
| core同sink RGB→bins及真实bridge组合 | 本fixture不运行core | 主会话待验收 |
| 原AP1148 future/210c event接收与free | 本fixture不运行AP | 主会话待验收 |
| 连续histogram、event0xd5→UI property | 超出首个事务；绑定未闭合 | 未实现/未验证 |
| 物理1204/ASIC、原CP/FIFO/RTOS | 功能profile独立领域 | 未验证false |
| 原AP拍摄→编码→原MPR/Fsys→虚拟SD解码 | 本项无此链证据 | capture_verified=false |

## Evidence → Finding → Path

- **E1**：继承的公开ALLLANG完整SHA与44个原字节窗口，见source pins；**F1**：0148请求、1148未来完成、210c1034B结构及mode1 first256B event复制合同；**P1**：原C0338e164→AP034f54cc→034f34e8/034f340c→原waiting caller freeD，与独立210c→event0xd5→receiver freeD分域。
- **E2**：strict/SAN组件fixture及production未定义符号检查；**F2**：只有完整typed1192B才接管，1024B来自桥接输出，三份lease按角色、原字节、source和TID控制；**P2**：exact原请求→真实bridge接口→model validation→freeQ0→allocD/copy/readback→send1148→send210c→观察receive→真实free0→分域AP_consumed。
- **E3**：异常、alias、inline free、fork-held-lock与重复请求负例；**F3**：失败保留真实lease，退休地址不认领后续foreign消息，无法以send0/单ACK冒充整体消费；**P3**：各边界拒绝→sticky故障/完整snapshot→主会话按整批证据继续验收。
- **边界**：E1不证明物理bin语义或event后UI绑定；E2/E3是组件证据，不证明core RGB帧、原AP、真实媒体或capture。已有原研究不重做；新实现仅应用已给合同。文档采用普通实现报告结构，`flavor=null`。
