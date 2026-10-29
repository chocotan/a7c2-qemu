# Functional JPEG adapter at the original SDK service boundary

Implementation by **gpt-6.1-sol, thinking=max**, functional profile authorized by the user and root `AGENTS.md`.

## 实际 reply free 与原 JPEG 内容验证（当前）

本轮只修改授权的 codec C/H、原 C/Python fixture、codec README/追加验证记录，以及 evidence checker/test/README。共享 worker、原 Main/MainComp 方法、输入 P/I/O 与 State128 路线不变；source pins 未改。限定自测最终 **320 passed /4364 subtests passed（47.17s）**：codec 213项（105 normal场景 +105 ASan/UBSan场景 +1原 source pin +2实际 C stdout/checker 正例），evidence 107项。此前189项记录及其源摘要原样保留在 `verification-main.json`，新结果仅追加到 `reply_free_and_main_evidence_followup`。

父在真实 generic `osal_free_msg` 返回后调用唯一新 API：

```c
int functional_jpeg_codec_observe_freed(unsigned destination, void *pointer, int actual_rc);
```

顺序是原 receive → 保存实际完整40B packet/接收PID、TID/队列/地址 → SDK复制body → **真实原free返回** → observer → 原ResCmd。父保留原free结果及errno；observer也自行保存caller errno。返回1=已匹配的实际free0，0=未认领（含无pending、错队列/线程、重复、过期），负值=owner错误或已匹配的实际free失败；返回值绝不替换原free结果。observer不读free后bytes、不修改packet、不调用free/SDK，不重试；fork先PID guard再锁，logger在锁外。ACK和DONE各有一条地址/完整快照/free-attempt/result，成功free后同址新message在实际receive前不认领；接收后可关联DONE。失败free为sticky，保留owner/lease并禁止成功Res或clean shutdown，不把重试free0当清理成功。

新增 `original-freed-ack/done` 公共identity与lease generation/token保持同job；具体字段为 `receiver_pid receiver_tid reply_address response_source response_destination free_rc response_hex reply_hex`。`reply_hex`是receive时已保存的全部40B，`response_hex`是其中16B body，两条receive也增加`reply_hex`。Res增加 `response_address terminal lease_released`：Main ACK原return0但terminal0/released0，Comp DONE验证原length readback后才terminal1/released1。缺任一真实free0，checker拒绝`recv < free < Res`成功链。

[内容 checker](../functional-camera-evidence/README.md)现在要求共同kind/selector、三个selector的实际80/104B schema、非零Main geometry、quality集合与SOI0/1/0；Main ACK `120e64` return0、独立CompExec `122dfc`的同一ACK实参地址/PID/TID/manager/control/context/selector、Comp DONE `122b44` return0与原key1048 `5c/68/74`长度实际读回均严格连接。Main0匹配原Fsys JPEG的primary coding/scan/geometry；Thumb1必须从**同一个原文件**的EXIF TIFF IFD1 0201/0202标签严格解出，完整JPEG等于实际model/leasedThumb，原Fsys sourceareas/readback/双exports独立解码要求仍在。大小端、tag type/count、offset/length/span、重复/重叠IFD、另文件/缺source与内容差异均有负例。每file至多一个Main0和一个Thumb1；Without_Pin保持独立文件。Screen2 adapter仍支持，但原MPF/layout未证明，checker明确拒绝缺layout，不伪造映射。

Main/Thumb只连接可观察的同source/control/context、primary geometry、原config pointer及同core/model lifetime/config generation；当前各selector分别render，没有capturegroup/sensor-frame retain ABI，**不声称同一sensor frame**。实际C stdout测试使用真实bridge/core/CMOS编码/lease/free收据和实际376B model proof，原SDK方法及caller-PC映射、broker/Fsys仍是明确HOST_TEST夹具；最终`capture_verified`保持false。未运行VM、原guest/AP、主模型build、全回归、网络、真机/真实SD，physical/original writer均未验证。

| Evidence | Finding | Path |
| --- | --- | --- |
| E-free：真实malloc/free后回调、同址ACK/DONE、fork/错线程/队列/无free/失败/重复/过期，normal+SAN | F-free：实际free0才允许原Res消费；失败保留lease，日志不访问free后bytes | original receive snapshot → real OSAL free result → matched observer → original Res → DONE lease release |
| E-content：Main/Thumb两种TIFF endian真实嵌入JPEG、原writeback夹具与完整字段/内容负例 | F-content：Thumb与Main可写同file，缺真实内嵌布局/原source不能通过 | actual model/leased bytes → primary or bounded IFD1 → original Fsys areas/readback/exports → independent decode |
| E-host-final：两文件完整pytest原始输出320/4364；实际C stdout正例2项 | F-scope：组件与checker通过，原AP/guest/整机成片仍待父验收 | host codec/real model → HOST_TEST transport+Fsys → checker；HOST_TEST verdict不可升格 |

本轮首次失败原样追加验证：86项后fixture把DONE free失败也误用于ACK；新configuration-only fixture未初始化thumb；独立transport缺INIT、verdict夹具缺products；原VDF路径覆盖局部body；既有refresh测试仍找旧literal format。均修正fixture根因，未放宽生产协议。工具skill的tool-index/ops链接在本checkout缺失，按纯文本模板与`flavor=null`更新本授权README，无外部bootstrap。

以下 Main/MainComp 189项与 Without_Pin 章节是此前证据；若其旧free/checker限制与当前小节不同，以当前实际hook和验证为准。

此前 Main/MainComp 扩展仅修改本成果的 codec C/H、原有 C/Python 测试、README 与 source pins/验证记录。沿用同一个 TLS、worker、bridge/core、SDS 输出租约和原 Dataflow 回复路径；没有另造适配器、修改 main/build/profile/evidence/bridge/core/MPR memory，也未运行 VM、debugger、全回归、原 guest SDK、网络或真机。

此前限定 host 验证为 **189 项通过（26.67s）**：原 27 个 Without_Pin 场景全部保留，新增 67 个 Main 场景，分别执行 normal 与 ASan/UBSan，加 1 项原 public 资产/ABI/relocation/完整函数指纹测试。Host fixture 使用实际 bridge/core/CMOS 渲染和编码输出，但 AArch64 SDK 方法与 SDS provider 是明确的 host fixture；**不把这些测试称为原生主照片、原 AP 业务消费或虚拟 SD 成片验收**。原 guest 双 ABI、整批回归与一次 VM 验收仍由 parent 负责。`capture_verified=false`、`physical_asic_compatible=false`、`original_writer_verified=false`。

## Main/MainComp 的共享实现

新增四个精确原 export，启用时校验各完整函数 FNV、原模块地址和实际 vtable relocation，另校验原公共 controller 两个完整函数：

| 原对象 | Exec VA / bytes(hex) | Res VA / bytes(hex) | 实际 address point / 对象 bytes(hex) |
|---|---|---|---|
| Without_Pin，保留 | `11b654 / 2f4` | `11a9dc / 25c` | `1af448 / 30` |
| Main，新增 | `1226c4 / 444` | `120e64 / 60` | `1af7c0 / 28` |
| MainComp，新增 | `122dfc / 4c` | `122b44 / 2b8` | `1af808 / 28` |

Main 的 `+10` 是 manager，`+18` 是 control，`+c` 是 context，`+20` 是 selector byte；没有 Without_Pin 的 key/mode/宽高字段。Main 前置 DMM completion 先仅安全读 4B；`s16[+2]!=0` 时执行真正原 Main 并保留返回 1，不接管请求、不触及模型。正常分支才要求可读 32B，以覆盖原日志条件读取的 `u64[+18]`。Main/Comp 仅按 `28` 字节读取与做 object alias 检查，测试含真正页边界上的 `28` 字节对象、截短对象与仅 4B 的失败 completion。

原 Main 实际执行、构造并发出的 80B body/104B OSAL packet 才能进入共享 dispatch。SID 仍是 `82830752`，CID/MID 仍取原 Convert `(3,304)`，完整原 packet 保留。`body+18/+1c/+20` 明确是输入**元数据** SDS，不当像素指针使用；原 MakeInputYcStdData 与 builder 均继续由原 SDK 执行。未知原 P/pixel/AP producer 与其 generation 因果关系仍未验证，不制造输入 unit，不发送 1000/1006/event9，不绕过原驱动。

| 原 selector | 必须来自实际 body 的目标/primary | 允许原 quality code | addSoi | 原 key1048 长度写回 |
|---|---|---|---|---|
| 0 Main | 目标与 primary 均非零，且两组 W/H 相等 | `0,1,2,6` | 0 | `Cprime+5c` |
| 1 Thumb | 目标 `160x120`，primary 均非零 | `4` | 1 | `Cprime+68` |
| 2 Screen | 目标与 primary 均非零，允许两组几何不同 | `3` | 0 | `Cprime+74` |

全部几何均受真实 codec 最大值约束。只有 Without_Pin 保留原先明确的软件 `0 -> State` fallback；Main/Screen 的缺失尺寸绝不提升成默认 640x480 主照片。原选项 `body+4c/+4d` 仅支持明确的 `0/0`，非零以 `-ENOTSUP` 拒绝。所有允许的 quality code 仍使用实际 `State.quality` 软件编码策略；不宣称恢复了 Sony 物理 quantization 效果。三个 selector 当前各自触发一次真实 STILL 渲染/编码；没有跨 selector sensor-frame retain/reuse ABI，**未验证它们共享同一原 CMOS 帧**。

Main ACK 的真正原 Res 无论 status 均返回 0，永远非 terminal，因此保留当前 generation/token 的输出 lease。不同对象 MainComp 只有在同次实际 ACK 已观察并由原 Main Res 消费后才能关联：要求原 controller 的 `13b7e0` 返回 PC、同一 receiver PID/TID、完整原 ACK 16B、原 controller 保留并继续传入的同一 ACK 参数地址、不同对象，以及匹配的原 manager/control/context/selector。直接或过期 MainComp、缺 ACK/Exec、重入、foreign PID、错误 vptr/字段/收据全部拒绝。

MainComp 原 Exec 必须实际运行。原 ParameterControl `GetValue(pointer)@a46e4/c4` 完整函数有 runtime pin，control 的虚表 `+a8` 必须确实指向它；读取原 key1048 只用于核对当前 writable `Cprime` 与该请求的 unit/position/capacity，并验证读写权限与 alias。key1047 是独立 120B 稳定 copy，不能与 key1048 pointer 当作同一 storage。DONE 先通过真实 original receive 的逐字节校验，再由真正原 MainComp Res 写回长度；adapter 只读回比对、不代写该字段。只有原 DONE 的正确返回值与实际原长度写回均成立后才退租。错误编码也必须排入真实 ERROR DONE，使原 MainComp 清零对应长度并返回 `201`；不会因错误 ACK 的原返回 0 而挂住或伪造成功。发送、原请求 free 或 lease release 失败均保留相应所有权并阻止 clean shutdown/reuse。

当前 provider 在原注册节点中明确声明 identity IOVA，故保留其已有 `virtual_base == iova_base` contract 检查；额外核对 CPU `lease.address == virtual_base + offset`、实际 mapping/RW、精确 extent、token/generation 与输出 alias。所有 CPU 访问仍只使用 provider 的 CPU lease.address；不主机解引用独立 IOVA，也没有把原输入 P/V 两个地址域合并。

## Parent 收据 schema（本次新增）

公共字段保留旧含义，新增 `kind=without-pin|main selector=<0|1|2> comp_object=<pointer>`；`exec_entry` 随 kind 为 `base+11b654` 或 `base+1226c4`。Main 无 parameter-key 字段，因此旧通用 `key=0`，不能解释成 key1047/1048 内容。`stream_mode` 仍是实际 addSoi，不能把 selector2 当作 true。未关联 Comp 时 `comp_object=(nil)`；setup/rejection 无 job 的 sequence0 行不是 Main job 证据。

| Operation | 新字段与实际证据 |
|---|---|
| `original-maincomp-exec` | 公共完整 job identity + `comp_caller comp_exec_entry previous_ack_hex previous_ack_address original_result native_config config_length_offset`。实际原 Comp Exec 返回后记录；只有 rc0 才是有效关联，entry=`base+122dfc`，previous_ack_hex 必须等于同次已观察/已消费的 ACK16。 |
| `original-maincomp-config` | 公共完整 job identity + `native_config config_length_offset actual_length expected_length original_result`。原 MainComp Res 返回后实际读回 Cprime 对应字段；rc0 说明字节相等，错误 DONE 的实际/期望长度都为0。 |
| `original-rescmd-ack` | 既有完整原 response16 与 receive identity；Main 的 `res_entry=base+120e64 expected_result=0`，不退租；Without_Pin 原规则不变。 |
| `original-rescmd-done` | Main 的 `comp_object` 必须是已关联独立对象，`res_entry=base+122b44`；原成功0/错误201，必须结合配置读回和实际 release_rc。Without_Pin 保留 `base+11a9dc`。 |

所有行继续 `capture_verified=0 physical_asic_compatible=0`。Adapter 自己保持已有 1024B buffer（有效正文少于1024），格式溢出会明确变为 receipt-format-error；用户已确认 main `record()` console mirror 有 4096B 完整预算，1024 截断只在辅助 menu-load/memory_log，本次无需扩 main console。Parent checker/index 由 parent 独占维护，需接纳上述 kind、独立 MainComp 与两个新 operation。

SDK Receiver 在 Res 之前复制实际40B packet并调用原osal_free；此前189项版本未跟踪该次free返回值，本轮已通过上述generic尾hook补齐。源中存在free调用或静态pin仍不构成free0证据；实际原AP→producer→CMOS→原MPR/Fsys→虚拟SD成片仍待父集成。

| Evidence | Finding | Path / 尚未验证 |
|---|---|---|
| E-main-source：已完成 Main 合同，现 manifest 的完整函数、构造/selector 窗口和四个 relocation | F-main：独立对象/前置条件/三 selector/ACK-DONE 合同已闭；source_verified | 原 controller → 真正 Main Exec → 实际 OSAL packet → 同一 shared worker |
| E-main-host：本成果原 C/Python 测试 189 pass（94 normal + 94 sanitizer + 1 source）；19 个成功场景各独立解码 model/SDK 两份 JPEG，共76次 decode | F-host：实际功能 CMOS/编码输出、精确租约写读回、分离 MainComp 和原形状长度写回通过 host fixtures | 真实 bridge/core → mapped host output → SDK ABI fixture；不是原 AArch64 执行 |
| E-main-errors：前置失败/零尺寸/unknown caller/Comp 关联/错误 ACK-DONE/原长度不符/退租失败场景 | F-fail：失败不会退租成 clean，也不会提升为 capture_verified | 父会话实际 sender/receiver/free、原 MPR/Fsys 与 SD 完整验收仍未执行 |

本次最初三次限定运行分别因 fixture 把 setup sequence0 误断言为 Main、把缺 Comp 的拒绝误用于 ACK、以及 tiny-capacity packet 未同步到 fixture 原配置而失败（57/105/153 已通过后停止）；均修正原 fixture 根因，未改为放宽生产协议。随后 175、181 项中间全通过，最终几何及相同 ACK 副本拒绝补测后以本节 189 项结果为准。验证记录在 [verification-main.json](verification-main.json)。

以下保留既有 Without_Pin 实现细节与历史验证，若与上面的 Main 扩展范围不同，以对象/kind 明确区分。

The adapter now preserves a real `ExecCmd_SDF_EncodeJpeg_Without_Pin::ExecCmd` invocation, claims only the actual OSAL packet emitted on that invocation's thread, asks the real functional bridge/core to render and encode a CMOS frame, and copies verified JPEG bytes into a current SDK output lease. Success replies use the original `DataflowInfraMsg` serializer and `DataflowInfraSender::SendASync`; the original queue receiver and `InfraAvbbcSeqBase::ResponceSequence` call the original `ResCmd` and advance the original sequence. There is no media-file writer or direct MPR/Fsys call in the adapter.

**The current memory provider supplies the strong SDS acquire API; combined host and original guest-libc 2.25 no-undefined links pass.** The adapter retains a weak import only to refuse enable with `-ENOSYS` when that provider is absent. Actual original AP requests, current original SDS registration, OSAL integration and MPR/Fsys -> virtual SD acceptance still require the parent's joined execution. No original AP -> MPR/Fsys -> virtual SD capture has run. `capture_verified=false`, `physical_asic_compatible=false`, `original_writer_verified=false`.

| New deliverable | Purpose |
| --- | --- |
| [functional-jpeg-codec.c](../../runtime/analysis/functional-jpeg-codec.c) | Exact mangled Exec/Res exports, native packet ownership, one bounded worker, real bridge encode/readback, original queued completion |
| [functional-jpeg-codec.h](../../runtime/analysis/functional-jpeg-codec.h) | Explicit enable, OSAL dispatch/receive observation, snapshot, shutdown, and required SDS acquire declaration |
| [test-functional-jpeg-codec.c](../../runtime/analysis/test-functional-jpeg-codec.c) | Real bridge + actual functional model with source-pinned host fixtures for the AArch64 SDK methods and mapped output leases |
| [test_functional_jpeg_codec.py](../../runtime/analysis/test_functional_jpeg_codec.py) | Executed host normal/sanitized matrix, exact public-source pins, independent Pillow decode |
| [source-pins.json](source-pins.json) | Complete public identities, ELF segments, 50 exact windows, 26 instruction anchors, PLT/vtable relocations, Main field contract and inherited bounded Kuna invocation |

The public original `libInfraAvbbc.so` is 1,738,760 bytes, SHA-256 `676197567dbbefa54e08f528968efc6ca2aaffe8bee3ee3eae8164382ed5a7e5`. The original Dataflow library is 306,496 bytes, SHA-256 `620e04a9cd51e65bd190ed1d5459b7235ff5a4109bc6498df342972621991d47`. The raw kernel is 13,797,088 bytes, SHA-256 `90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`. I/D addresses below are ELF VAs. K addresses are raw offsets, whose original KVA is `0xffffffc001000000 + raw`; they are not ELF or CP addresses.

**Original ABI and causal entry.** I `0x11b654/0x2f4` takes `(this, unsigned char const *)`; its actual return is in `w0`, and it never reads its second argument. The adapter therefore never dereferences that unbounded trigger pointer. I `0x11a9dc/0x25c` takes `(this, unsigned char const *, uint16_t)` and returns its controller result in `w0`. I `0x13b6e8` and `0x13b7dc` are the source-pinned virtual Exec calls; their return PCs are the accepted native callers. I `0x13b784` is the virtual Res call; its return PC is required for an owned completion. No standalone adapter API accepts a host timer, key press or made-up AP command as a capture request.

The C++ constructor I `0x11ac38/0x6c` and base constructor I `0x12857c/0x44` prove the copied object fields: context `+0xc`, original manager `+0x10`, ParameterControl `+0x18`, parameter key `+0x20`, mode `+0x24`, logical width/height `+0x26/+0x28`. The manager's actual queue ID comes from its original `GetOsalId()` and must match manager `+8`. The original Exec body is still called. Its original metadata helper and `makeParamEncodeJpeg` remain intact, including the physical mapping behavior of the former. The strict [Without_Pin helper](../jpeg-without-pin/README.md) and its rejection policy are unchanged.

Interposition is supported by actual `R_AARCH64_ABS64` relocations at I `0x1af448/0x1af450`, referring to the mangled Exec/Res symbols. The constructor takes its vtable through the real GOT. Enable verifies the original function addresses and exact code-window fingerprints, and checks those relocated vtable entries actually point to the adapter exports. No original text, vtable, PC or AP state is patched. Runtime verification covers the listed windows; complete-file SHA verification is the parent's public-asset staging responsibility, not a claim made by the runtime adapter.

The actual request reaches `OsalSndMsg` at I `0x11b940`, then original Dataflow serialization and OSAL allocation. The parent passes that allocated OSAL message to `functional_jpeg_codec_dispatch`. A request is accepted only inside the native Exec invocation, with one real 80-byte body inside a 24-byte Dataflow envelope, source and reply queue equal to the original manager, exact source-generated CID/MID conversions, original response MIDs and supported constructor fields. It copies all 104 actual packet bytes into the provenance hash and immutable wire receipt, retains the 80-byte immutable body, obtains an output lease, and frees the original allocated request once through the parent's original OSAL release callback. Errors preserve the original sender's ownership and turn the Exec return into the source-defined controller error `0x201`.

**Output and completion shape.** The request's stream SDS is `{u32[+0x24], u32[+0x28], u32[+0x2c]}`. The native stream position is `u32[+0x38]`, remaining capacity is `u32[+0x3c]`, and `u32[+0x34]` must equal their non-wrapping sum. The output resolver receives the SDS offset plus that original position. It never treats a native handle as a host pointer.

| Native behavior | Source proof | Functional adapter |
| --- | --- | --- |
| `addSoi=0` | I `0x11b268..28c`; K `0x534d8` skips SOI, native header writer starts `FF DB` | Copy the actual full model JPEG with exactly its first two SOI bytes omitted; native returned length omits those bytes |
| `addSoi=1` | I `0x11b35c..384`; K `0x53548..568` writes `FF D8`, advances position by 2; K `0x56b24..350` adds 2 back to the completion length | Copy the complete actual model JPEG, including SOI |
| Complete service output | K `0x2ac7a0` writes DQT/DHT/SOF, K `0x2acd34` checks hardware SOS then adds a `0x23d` prefix | Use `STILL16(FULL_JPEG)` at this service boundary. Kernel hardware/prefix code is not executing here, so no second prefix or SOF is added |
| 16-byte ACK | K `0x3ca50..b58`: request response CID/MID/tag, size 16, converted status, service transaction ID | Original serializer, exact original CID/MID/tag; nonzero accepted virtual service transaction sequence in the source-defined transaction field |
| 16-byte done | K `0x42058..108`: second CID/MID/tag, status at `+8`, actual encoded length at `+0xc` | Same source shape and actual copied length; source SDK queues it |
| ACK controller return | I `0x11aa04..3c`: status 0 → `0x200`; error → `0x201` | Original ResCmd runs after actual queue observation |
| Terminal controller return | I `0x11aaec..b50`: status 0 → 0, stores length at configuration `+0x5c` or `+0x68`; error clears it | Original ResCmd performs those stores, then original sequence controller progresses |

The backend's returned full JPEG is checked for the actual source-style 575-byte prefix, exact original immutable Huffman tables, nonzero DQT entries, 4:2:2 baseline components, requested logical dimensions, the actual SOS structure, bounded stuffed entropy and a final EOI. This framing check does not replace independent decoding; the real core is the encoding producer and the parent fixture decodes its bytes. The original hardware would expect an SOS suffix at a lower boundary, but this adapter intercepts the complete service, so forwarding a bare SOS here would drop the native header.

Both native discrete quality selectors (`3` for mode 0, `4` for mode 1) explicitly use current functional `State.quality`. These source table selectors are not silently interpreted as JPEG percentages. Nonzero original logical dimensions are used exactly, through 8192 × 8192. A zero dimension uses the declared profile state for that dimension. Other modes/selectors fail. This is the approved software hardware policy, not a recovered Sony quantization or physical YC policy. The model itself renders and consumes the profile's RGB888 image bus; this adapter does not claim the original `0x1054` physical YC layout has been learned.

The one worker delays even the positive ACK until actual bridge rendering, encoding, complete result drain/release and SDK output readback have succeeded. Output uses `functional_mpr_memory_write(lease, 0, data, bytes)`, the current provider's serialized copy/readback API, rather than a validate-then-unlocked-copy sequence. The adapter then reads the actual destination in bounded 4 KiB chunks, compares all bytes, computes its readback FNV and validates the same generation again. It holds the real lease through native ResCmd. It validates the lease and output hash again before terminal publication and before allowing successful native terminal consumption. Source, destination and exact body must first be observed at the parent's successful original OSAL receive. A wrong caller, source, tag, duplicate/stale body or unobserved callback cannot publish success. No callback runs under the adapter lock. Forks fail before inherited locks; disabled exports delegate their exact `RTLD_NEXT` originals and preserve their errno behavior.

The service-generated first ACK transaction ID is a real monotonically increasing accepted virtual job ID, bounded to `uint32_t`. K `0x3cd3c` proves this field is generated by the service, separate from the echoed response tag. It is not reported as an original CP transaction, sensor generation or fabricated OSAL source. Provenance logs retain actual PID/TID, native producer TID, module load bias, original Exec entry, native caller, object/manager/control/context, original source/destination/command, actual packet hash, model instance, job sequence, output size and output hash. Every record keeps physical compatibility and capture verification false.

**Parent integration.** Compile the new C file into the existing preload adapter alongside the real bridge and memory owner, and include its header. After the pinned public SDK libraries are loaded and the real bridge/model has been initialized, call `functional_jpeg_codec_enable(record)` explicitly. Before legacy send emulation, call `functional_jpeg_codec_dispatch(destination, message, &original_io, &result)` from the real OSAL send hook; return `result` only when it returns 1. After a successful original OSAL receive, before original Dataflow parsing/freeing, call `functional_jpeg_codec_observe_received(destination, message, &original_io)`. After the real original OSAL free returns, call `functional_jpeg_codec_observe_freed(destination, message, actual_result)` while preserving the original result/errno. Replies remain allocated/freed by original Dataflow/OSAL; the observer only matches previously received identity/snapshot and never frees again.

The memory owner's required declaration is already exposed by the new header:

```c
int functional_mpr_memory_acquire_sds(uint32_t type, uint32_t handle,
    uint32_t offset, size_t bytes, struct functional_mpr_memory_lease *lease);
```

It resolves a currently registered original SDS into an actual owned RW mapping and acquires the existing memory lease. Type 0's `handle` is the actual `GetUnitInfo` unit ID; it is neither a packed unit/area nor a pointer. Area identity is separately registered by the real provider from actual allocations and original `SetMemTbl` verification. The adapter additionally requires that the acquired unit and offset exactly match the request's handle and SDS offset plus stream position. Unknown/retired handles, stale generation, aliasing and offset/length overflow fail. The returned extent must exactly match the request. Existing `functional_mpr_memory_write`, `functional_mpr_memory_validate` and `functional_mpr_memory_release` retain their authority. The current strong definition is provided by the separate memory owner; the JPEG implementation's weak import remains only an unavailable-provider guard. This follow-up did not edit the memory owner's files.

Call `functional_jpeg_codec_shutdown()` only after the original receiver and MPR/Fsys have drained. It joins the single worker when idle. Outstanding native replies, a retained lease, active work or a failed original queue send return `-EBUSY` and retain state; they are not declared clean. A failed lease release after a rejected original request is also retained in a cancelled pending job, blocking reuse and shutdown; a terminal ResCmd release failure retains its exact lease/token and release error. Native constructor objects belong to the original sequence and must stay alive until its original response handling or coordinated process teardown. No borrowed trigger pointer is retained by the worker. Without_Pin never reads its trigger; Main checks its source-required conditional DMM completion before entering the original method, then worker data are the copied native packet, source context values and current owned output lease.

**Runtime-content receipt schema.** All rows retain the existing ASCII `FUNCTIONAL_JPEG_CODEC` tag. The public C API adds only `observe_freed`; the snapshot layout remains unchanged. Main adds the kind/selector/Comp operations documented above; parent-owned checker/index integration remains with parent. Every row still has `physical_asic_compatible=0 capture_verified=0`.

The common fields are `operation rc pid tid producer_tid sequence original_base exec_entry caller object manager control context key source destination command native_bytes trigger_fnv response_tag model_instance bytes output_fnv stream_mode`. `sequence` is the accepted job sequence assigned inside that actual original ExecCmd invocation, not an inferred AP action or original CP transaction. `trigger_fnv` binds all 104 original SDK packet bytes. Common `source/destination` describe the **original request** on every row; response directions are separately recorded below. Pointer fields are identity values copied while valid and never dereferenced by logging.

| Operation | Exact additive fields / observation |
|---|---|
| `original-request` | `request_hex`: all **104 actual original SDK bytes**, including the 24-byte envelope. The existing original method/object/manager/control/caller/load-bias/PID/TID/SIDs/FNV identity remains on the same record. Emitted from the immutable copy after original request release and before waking the encoder worker. |
| `original-request-lease` | `sds_type sds_handle sds_offset stream_position lease_offset lease_address lease_capacity lease_generation lease_token lease_group lease_unit lease_area lease_unit_type`. The actual current resolver lease names the exact output interval. This pre-encode row has `model_instance=0 bytes=0 output_fnv=0`; join it to later output by the original sequence/PID/request identity, not by pretending an encoder has run. |
| `output-readback` | `lease_generation lease_token lease_address lease_offset lease_capacity model_token model_bytes model_fnv model_offset readback_bytes readback_fnv`. `readback_bytes/readback_fnv` equal the actual copied destination interval and common `bytes/output_fnv`, after serialized provider write and complete actual destination comparison. `model_token/model_bytes/model_fnv` bind the full actual bridge JPEG result; `model_offset` is the actual source interval start (2 for no-SOI mode, 0 for full-JPEG mode). |
| `original-received-ack`, `original-received-done` | `receiver_pid receiver_tid reply_address response_hex reply_hex response_source response_destination lease_generation lease_token`. `reply_hex` is the full received40B snapshot; `response_hex` is its16B body, copied before native parsing/freeing. PID/TID name the actual receiver. |
| `original-freed-ack`, `original-freed-done` | Same immutable receive snapshot/receiver/address/source/destination/lease identity, plus actual `free_rc`; emitted only after the actual generic free result is observed. No post-free read or second free. Failed frees remain sticky. |
| `original-rescmd-ack`, `original-rescmd-done` | `receiver_pid receiver_tid callback_caller res_entry response_hex response_address response_source response_destination response_mid original_result expected_result original_errno lease_generation lease_token release_rc terminal lease_released`. `response_address` is the actual copied-body argument into original ResCmd; MainComp must receive that same ACK argument. Original entry/results follow kind above. Actual successful free is mandatory before this callback; nonterminal ACK explicitly has terminal0/released0. |
| `request-lease-release-failed` | `primary_rc lease_generation lease_token lease_address lease_capacity request_hex`, with common `rc` equal to the actual release error. The complete 104-byte copied request and actual retained token remain identifiable; the request is rejected and the lease is not forgotten or reused. |
| `receipt-format-error` | `rc=-75 pid sequence requested_operation` and the unchanged false scope flags. This replaces an overlong/failed formatted payload, never truncates it into an apparent positive receipt. |

Successful original callbacks are logged only after actual original ResCmd returns; raw response bytes and identity values come from local copies, so terminal release/native destruction cannot cause a logging dereference after free. Counts `native_ack/native_done` require the expected original controller result. Actual error responses and release failures remain visible and do not certify capture. Logger callbacks run outside adapter locks and may query snapshots.

To join JPEG content, the parent must reconstruct the actual `model_token` transfer from its bounded retained binary trace, verify `model_bytes/model_fnv`, select `[model_offset, model_offset+readback_bytes)`, and match the current output lease's complete readback. Original MPR metadata/prefix transformations and original Fsys source contribution ranges must then match the actual exported JPEG portions and independent decode. A whole-file FNV candidate alone does not invent a buffer lifetime or unobserved transformation. This adapter writes no standalone media or trace file.

Payloads remain bounded below the adapter's own 1,024-byte buffer; media bytes are not hex-printed. The user confirmed main's complete console mirror has a 4,096-byte budget; only auxiliary menu-load/memory_log paths truncate at1,024. The record callback is void, so disk/console write success is unavailable here. Parent retains/hashes complete console records, checks for missing/format-error rows, and joins pre-encode rows by sequence rather than assigning them later output hashes. Parent-owned main/checker files were not changed by this worker.

**First-batch integration fixes.** The parent's preserved [unified run log](../../runtime/analysis/scratch/unified-camera-2sxwmmdp/host-regression.log) reported 3,603 passed / 434 subtests, 80 failed / 32 errors across the full combined run. That run remains failed evidence and is not replaced by this focused result. Its unchanged log SHA-256 is `d46a5c4861c96785163dfd0184cdd196cee02a30bd845708de66f58c67f42252`.

| Evidence | Validated finding | Fixture correction / call path |
| --- | --- | --- |
| E-fix-init: original line 417 asserted success for `fcam_bridge_init(NULL)`; the bridge source explicitly returns `-EINVAL` for a missing callback, and the focused fixture now asserts the actual `-22` return, preserved errno and no mailbox/sequence allocation | F-fix-init: invalid fixture setup, not a pagemap, nonce, broker, state-layout or libx264 failure | P-fix-init: reject NULL without allocating or publishing a mailbox → initialize the unchanged bridge with `record_metadata` → retain bridge mailbox/transfer/cleanup diagnostics on stderr |
| E-fix-stale: after setup was corrected, `stale-normal` reached its final State call and failed; `test-functional-jpeg-codec.c` directly includes `functional-camera-bridge.c`, and both declared the same file-static `retired` object | F-fix-stale: retiring a fixture output lease also retired the transport | P-fix-stale: rename the fixture flag to `lease_retired` → the actual lease still returns `-ESTALE` → original error response releases that lease → the bridge still returns valid State128 |
| E-fix-wide: the real 8192×16 default optics call returned only byte value 255 at f/4, ISO100, shutter16667µs, focus3m; the original Pillow content assertion independently rejected that all-white JPEG | F-fix-wide: width-scaled defocus and exposure clipped the scene before encoding | P-fix-wide: configure only the wide fixture at f/8 with the same shutter/ISO/focus → actual model render/encode → independent 8192×16 decode with 101 distinct RGB byte values; retain the original `>20` content requirement |
| E-fix-chunks: actual bridge diagnostics returned `required=2561491 error=-28` against the old 2 MiB arena, in both normal and sanitizer builds | F-fix-chunks: the real quality100 2048×1536 output exceeded fixture capacity; production correctly returned `-ENOSPC` | P-fix-chunks: use a 4 MiB mapped arena and matching native SDS capacities → preserve the same encoder, dimensions and quality → real STILL/READ_RESULT/RELEASE_RESULT transaction spans sequences4..44 and closes destination readback |

No production bridge/core fix is needed for these failures. The invalid-callback refusal is newly asserted in the existing C integration scenarios; existing stale/wide/chunks cases already cover the other roots, so no duplicate test matrix was added. Mailbox pages remain the explicit host pagemap fixtures; nonce/model identity is still 7, State128 layout is unchanged, and the first real INIT probe still has rendered1/consumed0/jpeg0. The source-backed 104-byte request, serialized memory-write API, exact SDS type0 unit ID, lease retirement/release errors, native ACK/DONE bodies and content receipts remain in force.

A focused diagnostic run of the final normal executable measured these actual in-memory outputs; no encoder bytes were substituted:

| Scenario | Actual full JPEG bytes | Independently decoded geometry | JPEG SHA-256 |
| --- | --- | --- | --- |
| `wide` | 26,962 | 8192×16 | `7a6777ef9eb205e558dd4bf46a4991c6b491769f247a895c7e1b15ccdcb38e45` |
| `chunks` | 2,561,491 | 2048×1536 | `586ab1f56823db32f085b2fc713b0e2ab5a4e014b058767f2139162a02017d41` |

**Prior Without_Pin validation status.** The earlier focused command below passed **55 tests in 11.36s**: 27 normal scenarios, the same 27 ASan/UBSan scenarios with leak detection enabled, and one exact public-source pin test, with no skips or failures. Eight success scenarios in each mode decode both the model JPEG and its native stream with Pillow: **32 real JPEG decodes**, preserving byte equality, logical dimensions, non-flat content and exact native length stores. Host strict `-std=c11 -Wall -Wextra -Werror -pedantic` syntax compilation, AArch64 object compilation, and both joined host fixture builds also passed in that invocation. The bridge and functional core/optics/JPEG/video dependencies are real; original AArch64 SDK methods and the mapped SDS lease provider remain explicit host ABI fixtures. This verifies the adapter protocol and actual output writes/readback, not original guest SDK execution or the actual production memory provider's allocation hooks.

Prior integration checks also recorded a host shared-library link with `-Wl,-z,defs` against the real bridge and memory owner. The strong production SDS resolver and its weak-import availability guard were not changed or rebuilt as global libraries by this central fix.

The maps parser explicitly imports `__isoc99_sscanf`. Public guest libc SHA-256 `f9104526eb7e5d2ea533c1a209bb0b83e69367f569e4c966895c8e106e6382c9` exports that method at ELF VA `0x5e640/0x70` and has no `__isoc23_sscanf` export. The installed cross-toolchain would otherwise emit the newer symbol. That dependency is pinned as L in the manifest. The parent must also check the memory owner's scanf import and use the existing guest-libc link procedure for the combined preload; the host shared-link check does not verify guest symbol versions.

The prior combined codec+memory+bridge+hidden metadata link check used **only original** public libc/libdl/libpthread/loader 2.25 under `--no-undefined`. Dynamic symbol inspection found `__isoc99_sscanf@GLIBC_2.17` and strong `GLOBAL functional_mpr_memory_acquire_sds`, without C23 scanf, test wrappers or video-engine imports. Those checks did not execute original guest libraries; temporary compiler artifacts were removed. The parent's complete preload ABI execution and VM acceptance remain separate.

From this report root, reproduce the authorized focused host check with:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  runtime/analysis/test_functional_jpeg_codec.py
```

The matrix covers default-off delegation, source provenance, current low-address mapped leases, missing/aliased/retired output, native dimensions and 8192 boundary, actual valid JPEG chunk drains, logical metadata mismatch, capacity/readback/backend errors, busy requests, queued send failure, wrong callback origin/source/tag, unobserved completion, fork refusal, exact original length-field stores and independent Pillow decode of the real model full JPEG and native stream. Generated JPEGs stay in memory and stdout pipes. The test has no SD or Fsys writer. Normal and ASan/UBSan builds are provided; an AArch64 compiler is used when already installed.

Four runtime-content scenarios supplement the existing matrix: `receipt-wire`, `receipt-thread`, `receipt-release` and `receipt-request-release`; all eight normal/sanitized invocations passed. Actual C assertions parse all 104 original SDK bytes and all 16 received/native callback bytes; compare current SDS unit/offset/generation/token, actual model/source and destination readback FNVs; run the original host callback fixture on a distinct receiver thread; and retain failed-release tokens after both an actual terminal callback and a rejected request, while refusing shutdown or reuse. The fixture uses the same serialized-write API signature; the real provider's atomic Free/write contract belongs to the separate provider and MPR real-memory matrices, which this focused follow-up did not rerun.

| Evidence | Finding | Path / remaining boundary |
| --- | --- | --- |
| E-entry: I Exec/Res/constructor windows, vtable relocations and native scheduler call sites | F-entry: genuine original method invocation and source-defined return ABI can be intercepted without original patching; high, implemented | P-entry: original sequence → interposed exact export → original Exec → actual OSAL packet |
| E-wire: original Dataflow envelope, source setter and sender; K first/done response construction; I response conversion/controller | F-completion: source/destination/tag/MID and 16-byte responses are source-backed; high, implemented | P-completion: actual backend result → original serializer/sender → real queue observation → original ResCmd/controller |
| E-output: K SOI reservation, stream-position forwarding, native prefix writer; actual core's source-style JPEG contract | F-output: full service output must retain DQT/DHT/SOF and optionally SOI; high, implemented | P-data: actual model CMOS → actual encoder → bridge chunks → owned SDK output readback → native length store |
| E-memory: current real SDS/address lease API and serialized write/readback API; executed mapped host fixture | F-memory: type0 unit ID, exact offset and lease checks pass in the host fixture; original production registration remains unexecuted here | P-SDS: original-shaped request -> mapped current generation/token -> serialized output write -> actual readback -> host ResCmd -> retained-error cleanup |
| E-receipts: executed complete request/response comparisons and leased output reads in both host builds | F-content: complete small wire bytes and actual model/output range identities pass the focused matrix | P-content: parent's actual binary transfer trace -> current output lease -> actual original receiver/ResCmd -> independent original MPR/Fsys range join remains pending |
| E-build: strict native/AArch64 compilation, joined fixture links and complete 55-test host matrix | F-build: implementation compiles and its host protocol/content tests pass | Parent still needs a natural original AP request and original writer/virtual SD acceptance; no full-regression or VM pass is claimed |

The bounded offline recovery used default ELF mode with five explicit `--addr` values, `--max-fn-seconds 8 --max-fn-memory 256 --no-vars`; all five recovered without a per-function error. Original instructions take precedence over decompiler return-type or structure guesses. The manifest records the exact command and output identity. Import/export counts, needed libraries, PLT targets and ELF segment offsets are retained there; this was not a whole-firmware survey.

The static sequence constructor I `0x11d3b8` identifies a thumbnail use of Without_Pin. Reaching that helper does not prove the natural main-photo path has reached it. Original metadata allocations/mappings, actual current SDS registration, actual native request occurrence, original SDK queue delivery and original MPR/Fsys file creation still need the parent's integrated evidence. `MprIf::EncodeStill` at libmpr `0x2c8cd8` is the known zero-return stub and is never used. Final acceptance remains original AP trigger → actual model CMOS/encoder → original MPR/Fsys → virtual SD readback/independent decode.
