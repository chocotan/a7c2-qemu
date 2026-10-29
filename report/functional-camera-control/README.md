# Functional CP startup and state owner

This backend connects original CP startup requests to the live software camera model for the explicitly selected `virtual-functional-camera-v1` profile. It requires a real broker INIT/STATE response before sending a success reply. The strict source profile and shared ABI/snapshot helpers are unchanged.

**当前软件时钟投影验证：253 个 control 场景在 strict C11 和 ASAN/UBSAN 下均通过（506 次场景执行），包含原有全部 124 个场景。新增独立原表与实际 C State128/POD 校验，4 项 focused pytest 在3.33s通过。AArch64 strict C11 fixture链接与production control对象检查通过；production对象仍要求真实`fcam_bridge_call`，不含HOST_TEST hook。完整原 AP 身份、73 项表、converter 和 mode1 call 原字节的只读验证通过。没有运行 VM、完整回归或主模型 build；AP 实际应用与后续拍摄仍由主会话单独验收。**

## 软件定义的单帧 readout/sync 能力

本轮只修改 control C/header、它自己的 C/Python 测试，以及本报告目录。按用户已授权的 `virtual-functional-camera-v1` 功能模型，虚拟 CMOS 的完整帧 readout/sync 预算定义为**一个当前模型帧周期**。频率直接来自本次已验证、不可变的 State128 `FCAM_S_FPS`（offset16）。[core State128 与视频入口](../functional-camera-core/functional-camera-core.c) 使用同一个 `Config.fps`；[视频编码器](../virtual-video-engine/video-engine.c) 实际消费它作为 `time_base={1,fps}` / `framerate={fps,1}`，并消费帧/packet PTS。这是明确的软件 timing 定义，未声称恢复 Sony 的物理 X-sync、滚动读出或闪光触发；**flash trigger 尚未实现，物理滚动读出未验证，原 CP writer/选值仍未知**。

协议使用软件定义 one-frame-period canonical pair `(wire_u32=fps, wire_u16=1)`。只能输出原 AP 73 元组表中精确存在的项；不约分、不四舍五入、不找近值、不选择额外非零常数。默认实际 FPS30 确定性输出 `(30,1)`；25 和60分别输出 `(25,1)`、`(60,1)`。`FCAM_S_SHUTTER`、ISO 与该能力独立，改变曝光不会改变 pair；原 State128 对零曝光的拒绝仍然有效。

[source-pins.json](source-pins.json) 保留全部73行原字节、表摘要、原 converter/call pin 和软件策略。`half=1` 与模型整数 FPS `1..120` 的完整交集是：

```text
1 2 4 5 6 8 10 13 15 20 25 30 40 45 50 60 80 90 100
```

原表不存在 `(0,0)`、`(3,1)`、`(61,1)`、`(120,1)`。后面三种 FPS 虽通过普通 ConfigState 范围校验，仍在 full projection 时返回 `-ENOTSUP`，发生在 ACK 分配、请求接管和 full/shadow 更新之前。已经存在的 full 与五个 timing 字段保持原样；最新 probe/config 元数据可以如实显示被验证的新代。`REFUSED` record 保存实际 `probe_rc`，不把成功 STATE probe 当作投影成功。

### 20a6 字节与记录

`full_snapshot()` 持有已验证的不可变 State128、instance、config generation，内部 helper 由 FPS 建立能力。nominal16与 full offset`0x664` 保持原布局：

| block offset | 字段 | 软件来源/约束 |
| --- | --- | --- |
| `+0` / `+2` | type6 / command20a6 | 原 schema |
| `+4` | u32零 | 原 header word |
| `+8` | u32 FPS | 本次 State128 offset16，与当前曝光无关 |
| `+12` | u16一 | one-frame-period 的 canonical half |
| `+14` | u16零 | 显式 virtual padding |

所有16B、known mask 和 source generation 都在 assembler 返回后、任何 ACK 分配前读回校验。默认 block 为 `0600a620000000001e00000001000000`。2012固定值、201b/2044、全部76槽位顺序/大小、generation/shadow与真实 ACK/notice receive/free/ticket规则保持原行为；没有新增通知、RPC、外部 mutable setter 或 State128 reserved 字段。

以下五个字段直接保存于 snapshot，并逐字段写入常规 `FUNCTIONAL_CAMERA_CONTROL_*` record（receive 专用记录仍保持其原格式）。它们只表示最近一次 full copy 的软件能力，不能表示 AP 已应用或物理闪光完成。

| 稳定字段 | C 类型 | 含义 |
| --- | --- | --- |
| `xsync_defined` | unsigned int | 有效 full copy 已定义并投影该能力；普通3003/无 full 时为0 |
| `xsync_source_fps` | unsigned int | 该 full 的实际 State128 FPS |
| `xsync_word` | unsigned int | 已投影的 wire u32，等于 source FPS |
| `xsync_half` | unsigned int | 已投影的 wire u16，值为1 |
| `xsync_source_generation` | uint64_t | 该 full 同一次已验证 State128 config generation |

新代 full 更新这五项；同代 ACK-only 不重新构建或更新。投影计数是 `projected_blocks=3`（201b/2044/20a6）和 `zero_policy_blocks=72`，另有2012固定块。常规日志固定容量增加至2560；按全部格式字段的最坏整数/指针宽度计算，上界含NUL为2142，fixture 还检查末尾原诊断字段未被截断。

### 本轮证据 → 结论 → 下一验收边界

| 证据 | 结论 | 下一验收边界 |
| --- | --- | --- |
| E10：[本轮 pins](source-pins.json)，原 AP 表`4c7d830`、converter`352a094`、call`35497d0`；73行SHA256 `a387e2fc4d3fb45047f8f93d5064b575f04d74ac6998dabb6564775d98b75e90` | F8，高置信、原字节验证：canonical域为精确查表，零pair非法；实际先前 AP副本20a6为零，FNV `1fae3c8aaffaf2d0` | P6：保持原 AP/表不变；本轮仅修功能producer，不宣称其余payload/AP应用已通过 |
| E11：State128 `Config.fps`、视频编码timebase/PTS源代码与本轮完整C full输出 | F9，高置信、源代码/host验证：功能预算由实际模型clock定义，独立于曝光；同一full/sourcegen | P7：由主会话核对下一次真实 AP 消费，继续镜头/CMOS/EE/capture/MPR/Fsys验收 |
| E12：253场景×2、实际C POD、原表独立交集与负向字段/State/probe/record/wire检查 | F10，host验证：无效cadence在ACK/接管之前拒绝，旧full/shadow和能力保留；同代ACK-only不伪重建 | P8：保持原真实receive/free与票据验收；host fixture不提升为新native/physical/capture证明 |

[verify_xsync.py](verify_xsync.py) 可独立核对原73表和当前C交集；指定原公开ALLLANG文件时，还检查全文件身份、全部表字节、converter摘要、call原字节及BL目标。测试的 POD 来自实际编译 C owner 的 State128/full/record；负向验证用这些实际输出逐字段变异，覆盖五个真实字段拼写错误、非法 State/probe、旧 source generation、20a6头/word/half/padding和record截断，不使用手写成功POD。

从 native-camera 目录执行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  runtime/analysis/test_functional_camera_control.py -q -ra --tb=short
PYTHONDONTWRITEBYTECODE=1 python3 -B report/functional-camera-control/verify_xsync.py \
  --app-fw runtime/analysis/menu-root/usr/lib/appFw.so
```

时间线：复用本轮已闭原字段证据 → 内部clock能力/精确domain/读回实现 → 保留原124场景并补129场景 → strict/sanitizer与原字节静态核对 → 实际C POD负向检查。未重新调查旧case。技能文档的额外 `tool-index.md` / `ops/evidence-finding-path.md` 在本工作区缺失；本报告使用已有E/F/P结构与实际可用Python/C工具，无新增工具依赖。

以下 ACK 修复、早期批次与 source hash 表为**历史记录**，本轮时钟投影与上面结果为当前状态。

**Historical ACK-focused verification: 13 pytest tests passed in 3.12 s. All 124 control scenarios (the existing 114 plus 10 native-shaped ACK cases) and all 30 event scenarios (the existing 25 plus 5 handoff/reservation cases) passed in both strict and ASAN/UBSAN builds: 308 scenario executions. Production object/link checks and all 7 unchanged application wiring cases passed. This repair used host fixtures and read-only public ELF analysis; no new VM, full regression, network, private/full-system assets, hardware or physical SD was used.**

**Repeated-cycle routing:** retain the existing entry points for startup/first mode1, and carry the actual transport event's `lease_cycle_id` into the additive `observe_receive_cycle` / `release_cycle` hooks for later mode leases. The [receive-event adapter](../../runtime/analysis/functional-camera-events.c) now retains each accepted event in a bounded process-owned ledger. ACK tickets follow the original requesting/sending thread through the imaging receiver's promise handoff; full-notice tickets remain bound to their actual receiving/freeing thread. Pointer-only hooks still reject later mode leases with `-ESTALE`. No free looks up a fresh backend ticket, and pending reservations grant no qualified free. Actual corrected native OSAL/AP delivery remains unverified.

## Actual startup ACK root fix

Scope is the delegated control/events implementation, their focused host fixtures, and this README. The frozen batch `unified-camera-c8g79fli` and completed VM `run-xpwm7k0g` remain unchanged. Parent-owned `menu-observe.c`, runner/shutdown code, ABI/schema, broker/model, original binaries and storage paths were not edited. The parent still calls the adapter only after an outermost successful original receive; its public/low-level receive depth guard stays intact.

The original AP has **different ACK receive and free roles**. Its imaging worker receives on `80020002`, passes the original pointer into a promise, and loops without freeing that matched ACK. The requesting thread waits on that promise, copies the reply and frees the same pointer. The old control check `(ACK_ROLE && tid()!=sender_tid)` incorrectly made that valid worker receive sticky-fault the startup lease. Removing that receive-only equality does not change the original-sender check in `release_owned()` or any full-wire, source, length, cycle, duplicate, releasing, send-result or real-free validation.

The old TLS event ledger was a second defect on this same path: the worker retained the ACK ticket, while its original sender could not retire that TLS entry. Later ACK cycles could encounter `-EALREADY` on a recycled pointer or fall through to an unqualified `-ESTALE` free. The shared five-entry ledger retains the **ticket captured at that accepted receive** plus its allowed freeing TID: sender for ACK, receiver for notice. It activates only after backend `handled=1`, invokes backend/accessor/logger/free callbacks outside its mutex, and clears only after a successful qualified original free. Duplicate active observations remain rejected across threads. This is not duplicate-receive idempotence or authorization for a second free.

### Original source and frozen observation

Addresses below are original ELF VAs, independently checked with `aarch64-linux-gnu-objdump`; the existing [AP3003 contract](../cp3003-ap-failure-contract/README.md) supplies the send/future/copy/free context. Public `appFw.so` SHA-256 is `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`; public `libosal_uipc.so` SHA-256 is `09ebf5980237fc473077dc844763dcb00cba423f431646e3be7c0ca49ea70ff3`. `E-imports/exports`: appFw imports `osal_rcv_msg_tmo`, `osal_get_msg_src`, `osal_msg_size`, `osal_snd_msg`, `memcpy`, and `osal_free_msg`; the OSAL library exports those public interfaces and `u_osal_rcv_msg_tmo`/`u_osal_snd_msg`, and imports `ioctl`, pthread locking, malloc/free and libc I/O. Symbols/relocations were read before the targeted Kuna 1.892/disassembly checks; no original code was executed.

| Evidence ID / source | Exact observation | Finding / next boundary |
| --- | --- | --- |
| E6: original appFw `3531528..3531568`, `3531600..353165c`, helper `35310c4` and pointer store `34f340c..34f3444` | Receive ID is full `80020002`; source is compared to `90030001`; matching reply passes `&message` into the promise and returns directly to receive, bypassing the worker's free at `35316d8` | F6, `n/a_re`, high confidence, source/host-validated: ACK receiver is distinct from the eventual original sender/free role; location `observe_receive_cycle` |
| E7: original appFw `3535af8..3535b24`; original OSAL `6468..65c0`, `3c60..3cd4`, `7e08..7e2c` | Requester waits on future, copies reply, then frees ID `80020002`. Public receive passes the original full ID to the low-level receive; source is payload `-12`, size is payload `-8`; no payload rewrite or ACK ID normalization occurs on that read path | F6: preserve the whole ACK and exact metadata; keep sender-only real free |
| E8: frozen [console](../../runtime/analysis/menu-runs/run-xpwm7k0g/console.log), lines 14874–14875 and 14959–14970; SHA-256 `b8e765457ca1b59b99214e0b6b0d532f2552cf9207e4102f811ffe2e06eb7a3c` | PID 258/TID 379 sends original 24B `000003302700008000000000000000000000000000000000`; INIT128 succeeds. ACK pointer `7fa7beb0c0`, source `90030001`, destination `80020002`, size16, FNV `7ef188e66a84bb78`; SENT already has `faults=1/received=0`. Later same TID 379 original free returns0 but consumed remains0 | F6 is consistent with the native ordering. The frozen log does **not** contain the individual receive callback's arguments/result/TID; recorded `IWrapperImaging=354` is the source-backed expected receiver, not a directly recorded receipt of this pointer |
| E9: production control + production events + pthread IO queue in [C fixture](../../runtime/analysis/device-models/test-functional-camera-control.c), case `native-ack-handoff` | Exact public 24B envelope, full request/ACK bytes, source, size, cycle0 and `send_inflight=1`; separate persistent receiver delivers ACK before send returns; original sender alone copies/frees it. Frozen control returns `-EPROTO` (`-71`) on that receive. Fixed control with frozen TLS events later returns `-EALREADY` (`-114`) on cycle2. Both repaired modules pass | F6 and F7, `n/a_re`, high confidence, host-validated: both production changes are required. Location F7 `functional-camera-events.c` ledger/free routing; P-ACK below remains native-unverified |

**P-ACK, callflow:** original AP request → live INIT/STATE validation → actual send begins → exact ACK receipt on imaging worker → immutable event ticket plus promise pointer handoff → send rc0 → original request free rc0 → same original sender copies and frees ACK rc0 → startup/cycle completion. Full-notice shadow still advances only after its actual observed receive, same receiver's original free rc0, and successful send commit. No ready/capture state is manually advanced.

The new `FUNCTIONAL_CAMERA_CONTROL_RECEIVE` record reports actual incoming destination/source/length/TID, original pointer, role, event/lease cycle, started/send-inflight/queued state, exact checked envelope, body FNV, full 12/16B ACK hex, and acceptance/rejection reason. `envelope_checked`/`wire_checked` distinguish unmeasured fields from zero values. Existing SENT/FREE records now include send-inflight, releasing and lease-cycle fields. These records use the existing mirrored `FUNCTIONAL_CAMERA_` prefix; no parent log change is needed. Stale tickets still return before external callbacks. Parent-next-VM pending: directly correlate that receipt with the original sender's free, and then establish any actual mode1/EE/frame/encoder/MPR/Fsys/decode progress. This worker did not rerun the VM or change the frozen no-JPEG/no-MP4 result.

Timeline: read frozen records and public original code → add native queue regression and observe its old-code failure → independently replace frozen control or frozen events to isolate both faults → repair receive-role/ticket routing → run full focused strict/sanitized matrices and unchanged wiring. The previous in-flight notice timing assertions and their negative send-failure case remain effective.

The 2026-10-28 user approval permits independently defined virtual hardware state. It does not establish Sony physical ASIC formats or original CP RAM/RTOS history. `original_cp`, `physical_asic_verified`, `ee`, `frame`, and `capture` remain zero, including after a successful model probe and notification lifecycle. Actual original AP input, sensor/encoder consumption, original MPR/Fsys storage, and independent output decoding remain separate acceptance requirements.

## Integrate the owner

The public interface is [functional-camera-control.h](../../runtime/analysis/device-models/functional-camera-control.h). The production implementation is [functional-camera-control.c](../../runtime/analysis/device-models/functional-camera-control.c).

| Entry point | Parent responsibility | Result |
| --- | --- | --- |
| `native_functional_camera_control_owner_init()` | Call once in the owning process before requests | Local UNKNOWN state only; no RPC or ready import |
| `native_functional_camera_control_dispatch(destination, request, io, guard, enabled, result)` | Select only the functional profile and pass the actual original message | `0`: delegate; `1/result<0`: caller owns request; `1/result0`: this owner accepted responsibility |
| `native_functional_camera_control_observe_receive(destination, pointer, source, bytes)` | Call only after an actual successful original receive, startup/first mode lease only | Checks the exact owned ACK/full-notice pointer, actual envelope, complete saved body, and receiving thread; ACK receiving workers may hand the pointer to their original sender, who alone may free it; later mode leases return `-ESTALE` |
| `native_functional_camera_control_release(destination, pointer, real_free, record, result)` | Route original message frees through this hook before falling through, startup/first mode lease only | Intercepts only tracked leases; validates exact wire/envelope and thread before real free; later mode leases return handled/result `-ESTALE` |
| `native_functional_camera_control_observe_receive_cycle(destination, pointer, source, bytes, event_cycle)` | Carry the ticket retained for this actual original transport event | Same complete validation plus the relevant slot's `lease_cycle_id`; a stale ticket invokes no external callback and changes no lease |
| `native_functional_camera_control_release_cycle(destination, pointer, real_free, record, result, event_cycle)` | Retain the same event ticket through original free; ACKs use their sending event's ticket | Same complete validation plus matching lease ticket; a stale ticket cannot clear or free a newly allocated pointer |
| `native_functional_camera_control_snapshot(out)` | Read diagnostic state at any phase | Copies facts without invoking external code; inherited owners fail before locking |

The transport is the existing `struct full_imaging_io`. The guard is exactly `struct native_cp_state_publication_guard`, without a substitute boolean/provider API. Main must pass its complete same-process predecessor callback, including all 13 required predecessors, actual earlier AP reply frees, and the original `4072` one-way request free. The existing `cp_owned_state_predecessors_ready()` callback demonstrates the required cohort; a profile flag or registration count cannot replace it. Resource reservation and both predecessor checks stay effective.

Main owns profile selection, registration, observer build inputs, bridge initialization/close, and receive/free routing. Link production with the real `fcam_bridge_call`, `cp-full-state-snapshot.c`, and `cp-state-snapshot.c`. There is no production bridge stub or weak fallback. `nm` on the compiled production object reports an undefined `fcam_bridge_call`, and no HOST_TEST lock hooks are present.

All bridge, allocator, envelope accessor, source setter, send, logger, guard, and real-free callbacks run outside the owner mutex. Busy/releasing/send-inflight state protects reentry; a forked owner returns `-EXDEV` before inherited locks or callbacks.

## Startup: live initialization before the 16-byte reply

Supported input is exactly:

- destination `90030001`, actual envelope source `80020002`;
- type `0`, command `3003` or `3000`, length 24;
- original opaque echo at bytes 4..7; all bytes 8..23 zero.

The original request remains caller-owned during resource checks, live model probe, and validation. Its actual source/destination/command/length and FNV1a64 of the original wire bytes form `fcam_native_origin`. The operation is `FCAM_OP_INIT`, with empty input and a guarded 128-byte output. Owner initialization itself never calls the broker.

The returned state must have:

- exactly 128 used/required bytes, no result token, intact output canaries;
- ABI 1 and exactly the declared four capabilities: still, H.264, AF, fixed optics;
- a nonzero model instance matching bridge metadata;
- a config generation in `1..UINT32_MAX`;
- nonzero width/height within the shared still bounds, FPS `1..120`, quality `1..100`, nonzero ISO/shutter, and a supported focus distance;
- the model's supported aperture setting: F4, F8, or F16, encoded as 400/800/1600;
- positive model-rendered and frame-generation counters, coherent consumer/encoder counters, idle stream, no pending result, and zero reserved state bytes.

The host core owns the actual INIT sensor probe render. Its counters are model events; this adapter does not treat the probe as an original AP capture. Missing broker/host, unsupported codec capability, invalid state, CRC/transport error, or bad output guard produces no ACK. The original bridge errno remains in `bridge_rc`; validation failure is separately recorded in `probe_rc`. Guard corruption is sticky.

After actual model initialization, the profile defines the original four compatibility bytes as `{0,0,0,0}`: integrated fixed optics has no serial E-mount/LIF bus, and its LIF tuple and fourth cache byte are defined zero. This is a functional policy, not recovered physical fields. `start_defined_mask=15` and `start_original_known_mask=0` keep the distinction explicit.

The independent reply is 16 bytes: type 1, virtual byte 1 zero, original command and echo, status `0000f000`, then the four defined compatibility bytes. Its envelope source is `90030001`; it is sent to the actual original source. The reply uses a separate allocator-owned message. Original request ownership is retained only after validation; allocation failure leaves it caller-owned. Once transport is accepted, failures retain owned pointers and sticky diagnostics rather than returning a caller-owned request that might already have been sent/freed.

`start_complete` requires the real original request free to return zero and the separate reply's real free to return zero on its original sending thread. Send returning zero alone does not establish AP consumption.

## Mode1: publish coherent state and repeat after retirement

Only exact type `5`, command `4073`, length 12, and little-endian mode word 1 is supported here. Mode0/2 and other mode words delegate, as does `3012`. Malformed supported commands are blocked without a generic ACK. The initial mode1 is blocked until the actual start reply has been freed successfully.

Mode1 performs a fresh `FCAM_OP_STATE` using that original mode request's actual origin on every eligible cycle, including ACK-only cycles. The complete State128 validation used for initial publication remains effective. The core instance must match INIT. Config generation must not regress below the latest validated core generation or the AP-consumed shadow, or exceed the u32 policy. Unchanged generation requires unchanged configuration bytes; monotonic model counters may advance. A genuinely newer core config generation is accepted. The owner never manufactures a generation increment, changes model instance/nonce, invokes CONFIGURE to force freshness, or resets startup provenance.

The complete 76-fragment packet is assembled using the unchanged [shared schema and assembler](../../runtime/analysis/device-models/cp-full-state-snapshot.c). Each fragment uses the table's exact order, command, size, type-6 header, and zero header word. Every fragment byte is a value owned by this declared functional policy; none is an unfilled physical cache read. All fragment mask bytes are 1. The shared assembler's outer byte-1 mask remains its mandated virtual-reserved exception; the owner does not exploit any mask exception to hide undefined payload bytes.

### Declared values

| Fragment | Functional state/policy | Source boundary |
| --- | --- | --- |
| `2012` | Exact bytes `060012200000000000007700` | Preserves the [source-closed constant](../cp-parameter-snapshot-fragments/README.md); does not claim live getter execution |
| `201b` | Current u16 at `+8` is actual State128 `fnumber_x100`; the other four u16 words and final reserved word are defined zero | Uses the documented current-aperture binding; the other words have no recovered physical meaning assigned here |
| `2044` | Raw wire state 1 is the profile's declared integrated virtual optics; name `Virtual functional fixed optics`; focal-range pairs `{0,10}`; aperture range `{0x40,10}` to `{0x160,10}`; remaining capability/reserved bytes zero | Depends on the validated fixed-optics capability and the declared model F4/F8/F16 range. Closed wire domains are checked by the unchanged snapshot helper; state 1 is not promoted to an original Sony product identity |
| `20a6` | u32 at `+8` is the actual validated State128 FPS; u16 at `+12` is1, virtual padding at `+14` is0 | Functional one-frame-period readout/sync budget. Exact original canonical tuple required before ACK; independent of current exposure, no physical X-sync/flash claim |
| Other 72 fragments | Eight-byte schema header plus a defined all-zero payload | Explicit inactive/unsupported/reserved functional state; no original RAM/default/cache proof |

The 72 zero-policy fragment commands, in table order, are:

```text
2000 2001 2002 2003 2004 2005 2006 2008 2009 200d 200e
2013 2014 2016 2017 2018 2019 201a 201d 201e 2020 2022
202d 202f 2030 2031 2032 2036 2041 2043 2045 204a 204c
204f 2050 2053 2054 2057 2058 2059 205a 205c 205d 205e
2061 2062 2065 2066 2067 2068 2069 206a 206b 206c 206d
206e 206f 2070 2071 209e 209f 20a0 20a1 20a2 20a4 20a5
20a8 20ac 20ad 20af 20b0 20b1
```

The lens numerator/denominator and BCD aperture-range layouts follow [the existing optical-format contract](../lens-init-contract/PRODUCT-ENUM.md). Focal length is not exported by State128; zero focal numerators are an explicit unspecified-range policy, with valid denominator 10. Current focus, sensor dimensions, FPS, ISO, shutter, and JPEG quality remain available verbatim in the model-state diagnostic snapshot. FPS additionally defines the explicit functional timing policy above; no original CP getter/writer equivalence is claimed. Other native getter payload bindings have not been established here, so the owner does not guess offsets or encode private data into reserved native fields.

Mutable/published metadata both use the actual checked core config generation. Initial shadow zero is the local virtual-owner policy. The full `2040` outer word remains zero; generation is external metadata. The unchanged assembler/copy validators must accept the whole packet, including lens domains and freshness, **before any mode1 ACK allocation**.

Only then are an independent 12-byte ACK and an independent `0x6d4`-byte full notice allocated. The ACK is queued first. The complete full notice is queued second. Its real received pointer, source, length, and all body bytes must match before its receiver may free it. That receiver can be a different thread from the mode1 sender; it must be the same thread that later performs the notice free.

Shadow advances only after that actual receive observation and the original free returning zero. No receive, a wrong pointer, corrupted envelope/body, wrong free thread, failed free, or failed send cannot advance it.

A later genuine mode1 request is eligible only when the preceding cycle is complete: the original request free succeeded, its independent ACK was consumed on its sender, any full notice was received and freed on its actual receiver, and slots 2–4 have no pointer, releasing callback, send-inflight flag, or fault. Pending ACKs/notices and in-flight frees/sends return `-EBUSY` before RPC/allocation. Sticky faults remain sticky. Startup slots 0/1 and their original evidence are immutable; 3003/3000 still perform only one actual initial start.

| Live STATE generation | Publication behavior | Completion |
| --- | --- | --- |
| Greater than shadow | Assemble and validate all 76 fragments before ACK allocation; independent ACK then full 2040 notice | Exact ticket/envelope/full wire/original receive and same receiver's real free rc0 advance shadow |
| Equal to shadow, with prior full notice actually AP-consumed | Set this owner's notification mode to 1 and send one independent ACK; no new full assembly/copy/2040 and no generation increment | Original request free rc0 and the ACK's original sender free rc0; no full-publication counter advances |
| Backward, wrong instance, inconsistent State128, failed bridge, lost predecessor or changed original envelope | Caller keeps the new request; no new reply/notice allocation or ownership takeover | Previous leases/publication/shadow remain intact; diagnostic model probe facts may change |

Only per-cycle slots, wire copies, and send flags are reset under the owner mutex after retirement and successful live validation. A full-notice slot remains unchanged during ACK-only cycles, so `notification_ap_consumed=1` continues to describe the prior original full notice. It is not a claim that the ACK-only cycle produced or consumed another publication.

`mode1_cycle_id` is a local monotonically increasing ownership ticket, not a model configuration generation. `lease_cycle_id[2..4]` pins each actual mode event across source/size/receive/send/free callbacks; post-callback updates recheck ticket, pointer, role and full saved wire ownership. START tickets remain zero. A full-notice ticket can remain older than the active cycle during ACK-only operation. The native wire is unchanged: no ticket or generation is inserted into its required zero header word. Consequently pointer-only event APIs cannot disambiguate recycled addresses; parent routing must retain and pass the actual event ticket to the additive cycle-qualified hooks. Stale tickets, including a stale ACK/free alias at the same address, return `-ESTALE` without dereferencing/freeing or clearing the newly owned pointer.

## Inspect model health and ownership separately

`FUNCTIONAL_CAMERA_CONTROL_*` logs identify `functional_model=1`, `original_CP=0`, `physical_ASIC_verified=0`, the instance/config generation, actual original wire origin/hash, probe run IDs, and `fixed_optics_policy=integrated-noneLIF LIF_tuple=0,0,0 cache4=0`. Native getter execution/source proof and capture remain zero.

The snapshot exposes:

- local phase, process, busy/resource reservation, sticky faults;
- probe attempts/successes/refusals, exact bridge/validation errors, raw State128 and model counters;
- `model_initialized` and `business_ready`: successful live model initialization/health only, never original CP/EE/AP/capture completion;
- start model-defined mask versus original-known mask;
- all 76 defined-block flags, three projected-block flags, and 72 zero-policy blocks;
- the five saved `xsync_*` fields for the latest full copy's model cadence and source generation;
- full-layout/model/wire copy facts separately from notification queued/received/consumed;
- actual published/shadow generation and all five leases: retained pointer, role, envelope, hash, allocation/send/free results, sending/receiving/freeing thread IDs, send-inflight/releasing flags, and faults.

A full copy can remain visible after an allocation failure; this is copy evidence only. ACK consumption requires its own original sending thread. Full-notice consumption requires its observed receiving thread. Transport send failures retain the original request and clean only unsent independent outputs. A failed cleanup remains retained and visible. Faults never clear into a completion claim.

Additive repeat-cycle diagnostics retain the existing parent guard meanings of `model_initialized`, `start_complete`, and `faults`:

| Field | Meaning |
| --- | --- |
| `mode1_requests` / `mode1_complete` | Lifetime number of accepted mode1 requests / completion of the latest accepted cycle |
| `mode1_cycle_id` / `lease_cycle_id[]` | Local ownership sequence / ticket for each slot; never substituted for a core generation |
| `mode1_cycle_generation` | Actual validated State128 generation for this cycle |
| `config_generation` / `published_generation` / `shadow_generation` | Latest checked live core generation / latest full copy's generation / last actually consumed full notice's generation |
| `notification_mode` / `mode1_ack_only` | Accepted local mode1 subscription / this cycle needs no new full notice |
| `notification_*`, `publication_copied`, full/block diagnostics | Latest full publication's facts, retained during ACK-only cycles; inspect `mode1_ack_only` to distinguish history from a new notice |
| `mode1_cycles_completed`, `mode1_ack_only_requests`, `mode1_ack_only_completed` | Monotonic actual acceptance/completion counts; completion is counted once after original frees |
| `full_notifications_queued`, `full_notifications_consumed` | Monotonic full-notice send rc0 / actual receive plus original free rc0 counts; ACK-only cycles do not change them |

Counter/ticket exhaustion refuses with `-EOVERFLOW`; counters never wrap to fake another initial cycle. The additive `MODE_ACK_CONSUMED` phase identifies a completed ACK-only cycle without renumbering existing phases.

## Verify the focused repair

The [C fixture](../../runtime/analysis/device-models/test-functional-camera-control.c) is guarded by `HOST_TEST` and supplies the only mock bridge. It checks all 1748 assembled bytes against the declared wire policy, then passes them through the unchanged full snapshot copy validator. Its mock State128 is not actual render/capture provenance.

The [pytest harness](../../runtime/analysis/test_functional_camera_control.py) now runs 253 scenarios twice: strict C11 with `-Wall -Wextra -Werror -pedantic`, then ASAN/UBSAN with nonrecovering sanitizers. The 129 timing cases cover every FPS0..121,25/60new generations, same-generation ACK-only retention, exposure/ISO independence, invalid State and first/later full refusals. Independent Python checks derive the domain from all73 original pinned table rows and validate actual C-emitted State128/full/record POD, including negative mutations. The original 98 startup/state cases cover both start commands, all 76 fragments, actual newer model generation, bridge/state validation, ownership, aliased allocations, send/free failures, inline frees, thread/fork/reentry rules, corruption, deferred shadow, and strict-owner isolation. The original 16 repeat cases cover unchanged ACK-only cycles, actual generation advances, pending/in-flight work, foreign frees, backward generation, lost model/predecessor/source evidence, recycled addresses/stale tickets, post-send failure, and the real receive-event adapter. Ten added native-shaped cases exercise a persistent receiving worker and separate original sender with the exact recorded 3003 request/ACK, receive-before-send-return and deferred receive, later ACK-only cycles, recycled addresses, duplicate receive, wrong receiver free, wrong source/size, corruption, failed real free and failed send. The fixture mirrors the original 24B envelope with a static header-size assertion and runtime source/size offset readbacks; its State128 remains a mock. A separate production-object test requires `U fcam_bridge_call` and excludes HOST_TEST lock hooks.

The [event harness](../../runtime/analysis/test_functional_camera_events.py) runs all original 25 plus 5 new cases in both normal and ASAN/UBSAN builds. New cases check cross-thread ACK ticket handoff, recycled pointers, duplicates observed by another thread, rejection of worker frees and reentrant use of a still-pending receive reservation. Existing no-snapshot-at-free, stale tickets, fork, full ledger, errno, backend refusal and failed-free checks remain unchanged.

The [runner module](../../runtime/analysis/test_functional_camera_runner.py) checks build/ELF receipts, immutable mailbox identity, owner/fork rejection, debugger handoff deadlines, startup failures, safe final detach/close, retained ownership on unsafe shutdown, and the actual extracted temporary-export entry point. Temporary SD export keeps the model available through `check()`; final VM shutdown still requires safe close/detach. Candidate `QEMU_SHA256` remains `a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02`; the production executable selection is outside this repair.

### Historical first-batch failure classification

The frozen `unified-camera-2sxwmmdp` full run remains **3603 passed, 434 subtests passed, 80 failed, 32 errors**. Its [raw log](../../runtime/analysis/scratch/unified-camera-2sxwmmdp/host-regression.log) was read without modification; SHA-256 is `d46a5c4861c96785163dfd0184cdd196cee02a30bd845708de66f58c67f42252`. No full regression was rerun or reclassified by the focused repair.

| Failure | Classification and evidence | Bounded correction |
| --- | --- | --- |
| `repeat-send-inflight`, original C fixture line 404 | **Fixture timing error.** The notice is actually received and freed inside `io.send`. `send_message()` defers queue/consumption until that callback returns zero, so the assertion after `dispatch()` returns was checking an earlier phase. The backend's count/retirement rules were correct. | Assert the full in-flight state inside the callback and the exact committed state after return. Keep repeat dispatch blocked while the independent ACK remains pending. Production control C/header are unchanged. |
| `MailboxTests.test_duplicate_owner_or_fork_cannot_rebind`, PID/nonce/reversed-page replacements | **Production parser error.** The regex consumed the newline that the next adjacent record needed as its leading boundary. Each two-line input therefore checked only the first identity and raised no `ValueError`. | Use a nonconsuming newline lookahead. Every complete record reaches the existing exact PID/nonce/ordered-pages identity comparison. LF/CRLF and one/two original mirrors reject all three replacements with `Multiple functional mailbox owners/identities`. No validation was relaxed. |

The repaired in-flight fixture requires these distinct observations:

| Observation in the first full cycle | Queued / consumed counts | Lease and shadow facts |
| --- | --- | --- |
| Inside notice `send()`, after actual receive and successful same-receiver free | `0 / 0` | `send_inflight=1`, `queued=0`, `received=freed=1`, `consumed=0`, pointer cleared, shadow `0`; repeat returns `-EBUSY` before RPC/allocation |
| After successful `send()` and `dispatch()` return, ACK still pending | `1 / 1` | Notice queued/received/freed/consumed, no in-flight send, shadow equals actual STATE generation `1`; cycle incomplete and repeat still `-EBUSY` |
| After original sender frees the independent ACK | `1 / 1` | Cycle completion counted exactly once; no extra notice or manufactured generation |
| Later generation-2 notice freed inline but its send returns `-EPIPE` | Prior `1 / 1` retained | New notice remains unqueued/unconsumed, shadow stays `1`, original request retained, sticky fault blocks completion |

The runner also tests each replacement before any debugger handoff, broker start, or `Core` access, both within one console snapshot and against an already bound prior snapshot. Existing actual run/PID/socket ownership validation and final teardown requirements are unchanged. Historical first-batch repair scope: that earlier repair did not edit the event adapter, bridge, shared ABI/schema, parent fixtures, frozen batch, or global binaries. The current ACK repair changes the control/events source and their own tests as documented above.

Run from this native-camera directory:

```sh
cd runtime/analysis
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  test_functional_camera_control.py test_functional_camera_events.py \
  test_functional_camera_wiring.py -q -ra --tb=short
```

Historical ACK-focused result: **13 tests passed in 3.12 s**; 124 control and 30 event scenarios passed in both builds, and 7 unchanged wiring cases passed. No sanitizer findings occurred. The same native queue regression was also linked against each independently retained frozen production module: frozen control failed at exact ACK receive (`-EPROTO`), frozen TLS events failed at a later reused ACK (`-EALREADY`), and both repaired production modules passed. Compiler: GCC 16.2.1; Python: 3.14.7. No full regression or guest build was run for this delegated repair.

Historical first-batch result: **30 tests + 33 subtests passed in 2.42 s** (3 control tests, including both original 114-case matrices, and all 27 runner tests); additional shared-API checks: **9 tests passed in 0.44 s**.

## Evidence, findings, and next validation path

| Evidence | Observation | Finding | Next validation path |
| --- | --- | --- | --- |
| E1: [shared ABI](../../runtime/analysis/functional-camera-abi.h) and [bridge API](../../runtime/analysis/functional-camera-bridge.h) | State128 is explicitly software-defined; production owner calls the real bridge with original request origin | F1, implemented: model health and original CP/physical proof remain independent | P1: original AP receive/free observation with the real model remains a separate runtime requirement |
| E2: [shared full schema](../../runtime/analysis/device-models/cp-full-state-snapshot.c), [lens domains](../../runtime/analysis/device-models/cp-state-snapshot.c), and [constant source](../cp-parameter-snapshot-fragments/source-pins.json) | All 76 slots, headers, lens domains, mask/freshness checks and the exact `2012` constant are reused unchanged | F2, implemented: full/ACK-only cycles use actual core generation and separate ownership tickets | P2: actual original AP/frame/codec/MPR/Fsys/decode chain remains unverified here |
| E3: strict/sanitized C matrices and production-object test above | 114/114 cases in each build; external bridge symbol required; real adapter included | F3, fixture-validated: in-flight frees do not commit a send; successful queued commit counts consumption once | P3: preserve receive ticket → exact wire/envelope → actual same-receiver free rc0 → send rc0 commit; native delivery still needs runtime evidence |
| E4: frozen raw-log failures and current C control/fixture transitions | Original post-dispatch assertion expected the pre-send-commit phase | F4, validated fixture repair: no backend counter/retirement change was needed | P4: keep both phase assertions and the negative post-send-failure case in the focused matrix |
| E5: frozen three mailbox subfailures, parser regex boundary, and current parser/watch tests | Adjacent complete records now all validate; all replacement identities fail before debugger/model access | F5, validated production parser repair: immutable identity checks now cover every complete console record | P5: keep LF/CRLF adjacency and cross-snapshot identity checks before handoff/start |

Residual risks: other getter payload semantics are functional zero policy, not recovered Sony field domains; original AP compatibility has not been exercised here. Ticket routing is fixture-validated with the real adapter, while native OSAL delivery remains unverified. The adapter rejects generation values outside its explicit nonzero-u32 policy. This owner does not implement later settings commands, autofocus commands, captures, codecs, storage, warm starts, or physical ASIC emulation. Current broader regression/build ownership remains with the parent; this assignment reports the focused results above.

Historical source artifact SHA-256 after the earlier first-batch repair (superseded by the ACK changes documented above; runner remains outside this assignment):

| Artifact under `runtime/analysis/` | SHA-256 |
| --- | --- |
| `device-models/functional-camera-control.h` | `f20844f61a7e6a3c0c66f87e65dec6a69fc6c521fbf106b4daf743a2bda516be` |
| `device-models/functional-camera-control.c` | `af21649251cd000421f7c1b60e008678ee02c0103d51e19e5bf6cef16add21ed` |
| `device-models/test-functional-camera-control.c` | `f04a4b836828097eb1e1f48676eddc1090ae8a0d80b783aad1baa3ccd3d6839f` |
| `test_functional_camera_control.py` | `b69e4836dcb2c4e1618451d962817262738b3bdc9f7cd869cac8f9668a6a6087` |
| `functional_camera_runner.py` | `d047661b4c94b4fc1de7d9d005500023bcf82a3aa723d11cf4d369e44105bc47` |
| `test_functional_camera_runner.py` | `231602285d34353c4c0d421a746c950d7e8988b2b8b7a627714a60c3d940fe5c` |

Historical ACK-repair source SHA-256 under `runtime/analysis/` (control/header/test hashes are superseded by the timing projection above):

| Artifact | SHA-256 |
| --- | --- |
| `device-models/functional-camera-control.c` | `ac657854b7b44521822056995e29ece94c896fec0e53790fb94d95e04519d62b` |
| `device-models/functional-camera-control.h` | `a619a66a661d50cef3240c5fb1b25b6691034c81b8b519b918670854ab6121ee` |
| `device-models/test-functional-camera-control.c` | `393a63258723cefbbff01e40963945ddbcdb3b85b81ad806c190fbafce689b3d` |
| `test_functional_camera_control.py` | `b88dbc94cfd9e58bd128613c40322152f888cbfa7dc129d8cedb10e6d1a2f05d` |
| `functional-camera-events.c` | `b5de6e68caa491c172d56136435f1704ccfec94be2b4a7758678a53c83ace72d` |
| `functional-camera-events.h` | `7096cacce6d59cb37cdf5bac2d8934c34ddfea3c9139901b210129c178888c2d` |
| `test-functional-camera-events.c` | `1cb876828ce19457f39ed75e94b7b7e8d3cdd74e11e170ed7dbf0156ca4d901c` |
| `test_functional_camera_events.py` | `32f492818918c0e3297773d5d3672f03ea6d3d89ecfeef7216d2fb7fd013d21d` |

Unchanged parent observer SHA-256 at the historical ACK handoff: `d5e448230dbfdc3adb1badd9d0f9432048be0ad2ddc6dc55234e6a55ae48726c`. At that handoff public API signatures and snapshot layout were unchanged; the current timing work appends the five diagnostic snapshot fields documented above.
