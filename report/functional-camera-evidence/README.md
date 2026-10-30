# Functional capture evidence checker

当前公开增量增加[原API40源内容检查](../functional-face-source-snapshot/README.md)与[015e/OP12位宽事务](../disp-bit-width/README.md)。OP11使用独立source provider及token空间，不生成Core/frame proof；检查实际暂停窗口、完整源读取、分块/功能CP读回、原callback和退租。OP12要求真实RGB消费、完整168B/class7/proof kind4及独立成功115e的request-free/send/receive/ticket/free；它的proof result_bytes/result_fnv覆盖168B，不沿用旧kind4空结果规则。两份profile策略须类型和值完整匹配。复现当前公开host检查用仓库根的 `python3 -B tools/test-public-models.py`；下述前轮结果和工作区命令保留为历史资料。新增本包测试不证明原VM拍照录像或物理ASIC，`capture_verified=false`。

`check_evidence.py` implements the positive content joins for the approved `virtual-functional-camera-v1` software RGB888 bus: original AP/SDK request → actual rendered/encoder-consumed frame → original MPR/Fsys → virtual SD → independent JPEG **and** H.264 MP4 decoding. It returns a structured verdict for a completed run and its current immutable batch. Missing or invalid evidence fails the relevant stage; there are no unconditional obsolete missing-contract markers or force flags.

## 3006 background initialization evidence (fresh formatter integration)

`check_background_start(run, manifest, rows, transport=None)` now consumes every
`FUNCTIONAL_BACKGROUND_START_*` row through a closed typed grammar. Its result
appears under `transport.background_start` and `evidence.background_start`.
A retained original request with no probes/reply is reported `pending=true`,
`verified=false`; absent background logs leave old evidence behavior unchanged.
Unknown tags, failed/malformed receipts and purported completion without the
actual closed transport fail validation. The new profile fields are checked in
both manifest and `backup_transport`, with exact types and values from the
current `backup_profile.py`; the original strict profile is unchanged.

The content join checks the actual libObj return PC `base+eda50`, two complete
BL reads `0x97fdb339`, full u32 dynamic source `0x8102xxxx`, original type0/3006/24B
wire and whole-wire FNV. Request byte1 and bytes8..23 stay opaque. Reply12 must
be independent type1/3006, virtual byte1=0, exact original opaque4 echo and
status `0x0000f000`. The request must remain retained until INIT=1 and STATE=2
both return the exact same complete valid State128 from independent immutable
broker payload files and actual bridge transfers, joined by origin, producer,
nonce, sequence, length, token and FNV. No generation=1 assumption is added.
The READBACK row must match all State128 bytes, instance/config/frame/counters
and full/cache/readback hashes; the existing full proof/history checker still
requires the real first RGB render/retire. INIT is a sensor probe with no encoder
consumption; it never supplies JPEG/H264, original3003/start, UI or media evidence.

The checker joins all thirteen individually recorded original AP free0 receipts
and same-run all13 readback before the accepted guard29 resource diagnostics.
It separately requires actual original-request free0, distinct response
allocation, successful send, original-sender receive and original-sender free0.
The bridge producer may be a different thread. Missing receive/free, stale or
mixed cycle/owner/source/model/bytes, bad State128, premature ACK, transport
failure, wrong sender and incomplete cleanup cannot supply a completed join.
Inline receive/free and a second INIT/STATE cycle reusing a retired address are
covered by real C owner transcripts.

**The fresh formatter now supports a complete causal trace.** Main records and
both LEASE rows carry the actual mutex-captured `snapshot_id`. The checker joins
exactly one main plus roles0/1 by `(pid, cycle, snapshot_id)` and restores capture
order from the global nonzero consecutive IDs. INIT/STATE/READBACK are independent
single-row snapshots and must have no leases. Main and lease lines may interleave
or arrive in a different output order; adjacency and logger-thread identity are
not used to select matching leases. Missing/duplicate IDs, mixed cycles, foreign
owners and duplicate/missing leases fail closed.

Real `INIT_BEGIN`/`STATE_BEGIN` records must contain the actual call counters,
retained original request, current producer, accepted predecessor and held guard.
All13 free0/readback and accepted resource diagnostics must precede INIT_BEGIN;
each BEGIN must precede its actual matching bridge transfer and result snapshot.
STATE_BEGIN follows the completed INIT result. INIT/STATE snapshots must contain
zero uncached/readback arrays; READBACK must independently contain all three
identical 128-byte arrays, with their whole-body hashes, complete geometry,
instance, config/frame generations, counters and reserved bytes matching the
immutable Core payloads. The actual `receive_ticket` and `free_ticket` must each
be the current cycle, first appearing only after the corresponding original
sender receive/free. Actual request free, independent allocation, queued send0,
receive, free0 and a final phase6/live0/working0/guard0/fault0 snapshot are all
required, including the inline-send case.

`content_join_verified` reports the complete content/lifecycle join;
`causal_trace_verified` additionally requires all fresh formatter observations.
For a complete native-format trace, `verified`, `native_completion_verified` and
`AP_consumed` can now become true. HOST_TEST remains pending/unverified even when
both content and causal joins pass: false host/native-acceptance flags are not
proof of SDK origin or original AP/all13 execution. The native source still has
to satisfy the exact caller-PC/double-BL-read/dynamic-source join. Legacy logs
without the four new observations retain their content result but stay pending,
with explicit missing observations; partially upgraded or inconsistent logs are
rejected. Physical ASIC, CP modules/masks/RTOS, business publication,
hardware/image ready and capture flags remain false.

Tests compile a temporary instrumented copy of the **latest existing C fixture**
against the unchanged production owner and real Core/optics. Instrumentation
prints existing logger text, actual State128 and the real 376-byte proof without
stripping or adding production evidence fields. The fixture's own limits remain
`body<2048` and `tag+body+6<4096`; all complete cache/readback bytes and the final
capture=false suffix survive. Strict C11/Werror/pedantic and ASan/UBSan/leak checks
cover deferred-thread, inline and retired-source two-cycle positives. All13,
libObj caller provenance, guard, broker, runner and mailbox support are explicitly
simulated fixtures. `require_native=True` selects an independent
`NATIVE_PARSER_TEST` fixture to exercise the complete native-format parser path;
it is not a relabelled native execution claim. The original HOST_TEST fixture
keeps its scope and cannot establish native completion. Both fixture classes
are explicitly barred from top-level capture acceptance.

The prior **14 tests /2665 subtests** are retained as historical results, not
backfilled native success. The fresh bounded selection, including those tests,
new native-format positives, full cache/readback byte mutations, BEGIN timing,
active guard holders, snapshot census, actual tickets and model identity
negatives, passed **21 tests /3497 subtests /100 deselected (7.93s)** after
recompiling the parent's latest fixture. An initial checker indentation error
was recorded before correction. No prior model-budget failure is reclassified.

Reproduce from project ROOT:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider --color=no --import-mode=importlib \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/report/functional-camera-evidence/test_evidence.py \
  -k 'background or control or Xsync or requires_complete_independent_typed_policy or complete_HOST_TEST_actual_positive_stages_and_evaluate or verdict_gate_needs_both_products' \
  -q --tb=short
```

| Evidence | Finding | Path |
| --- | --- | --- |
| E-3006-formatter: actual owner/Core stdout, complete State128/cache/readback and proof, strict/SAN deferred/inline/retired-source cases | F-3006-causal: the new formatter can supply every required causal/content observation | actual source binding → all13/guard → BEGIN → Core INIT/STATE → independent READBACK → request free → reply send/receive/free tickets → idle final snapshot |
| E-3006-negative: raw wire/cache/readback byte mutations, old/partial schema, early/late/missing BEGIN, active resources, mixed snapshots and stale tickets | F-3006-reject: missing or mismatched evidence cannot acquire native closure | typed snapshot census → full payload/origin/nonce joins → actual lifecycle/order checks → reject or pending |
| E-3006-scope: HOST_TEST stays pending; NATIVE_PARSER_TEST exercises the native grammar but is barred from capture acceptance | F-3006-boundary: parser implementation is complete for these fields; a fresh original AP/SDK/all13 run remains necessary for execution evidence | actual formatter tests + explicit simulated support → parent fresh native integration → independent full media acceptance |

Scope remains this checker/tests/README and the worker's new
`analysis/scratch/functional-background-native-evidence/` outputs. That directory
retains the first failure, final selected-test output, compiler receipts, complete
actual C stdout/stderr, supported console/broker payloads and parser results.
No runtime/core/profile/graph/runner/build/oldrun/private files were edited;
no VM/debugger/network, physical hardware or full regression was run. Parent
publication/commit/push is separate. Documentation uses docs-generator
`flavor=null`; its absent local tool-index/ops references require no bootstrap.

## 原 JPEG Main/Thumb 与实际 native free（当前增补）

本轮授权范围是codec C/H、原C/Python fixture、codec README/追加验证，以及本目录三文件；沿用原Main调查与共享adapter，不改原Main/P/I/O或State128，source pins原样保留。最终限定两文件运行结果为 **320 passed /4364 subtests passed（47.17s）**：codec213项、evidence107项。此前189/source与Xsync23/2930等记录保留为历史证据，没有回填旧run。正式内容以本节及[codec API/验证记录](../functional-jpeg-codec/README.md)为准；HOST_TEST与原AP/整机成片验收分开，physical/original writer/capture仍未验证。

`check_jpeg`现在逐job要求公共 `kind=without-pin|main selector=<0|1|2> comp_object` 与完整source identity。实际104B packet/80B body必须符合source字段、回复CID/MID、quality、SOI与目标/primary geometry；Main缺尺寸绝不作State fallback。Without_Pin保留原caller/entry/Res与0x200 ACK规则；Main entry=`base+1226c4`、ACK Res=`base+120e64`原return0且terminal0/released0，只有独立CompExec=`base+122dfc`之后的Comp Res=`base+122b44`原return0才能terminal1/released1。Comp必须匹配同job真正ACK16、相同ACK实参地址、PID/TID、manager/control/context/selector与不同object，原key1048 `Cprime+5c/68/74`长度必须由原Res写入并实际读回；adapter不能代写。

每个ACK/DONE还必须有 `original-received-* < original-freed-* < original-rescmd-*`。父在真正generic free返回后调用 `functional_jpeg_codec_observe_freed(unsigned, void *, int)`，保持原free rc/errno；observer仅匹配实际received且未free的同pointer/qid/receiver，并在失败时sticky保留lease。free行必须 `rc=0 free_rc=0`，完整40B `reply_hex`、16B `response_hex`、地址、receiver、source/destination、lease generation/token逐项等于该次receive快照，common identity逐行一致。完整header/body来自receive前保存的副本，禁止读free后的bytes。缺free、错误free、重复/错线程/队列/owner、fakekind、Comp drift、ACK伪terminal与长度不符均拒绝。

### 同一个原Fsys JPEG中的Main0与Thumb1

Main0按原文件primary coding markers、完整SOS/entropy/EOI及geometry匹配actual model和leased readback；APP/COM可由原MPR改变。Thumb1只接受从**同一个原file**的EXIF APP1 → TIFF → IFD0.next → 唯一IFD1，通过LONG/count1标签0201/0202解出的真实JPEG范围。解析验证II/MM、magic、IFD count/span、重复tag/EXIF、next/重叠IFD、offset/length溢出与边界、实际JPEG结构；绝不全file搜索SOI。Thumb整份JPEG必须等于actual Core JPEG与完整leasedThumb，暂不接受未经源证的Thumb APP/COM变换。

同file至多一个Main0和一个Thumb1，不能两Main0共享file、重复Thumb或跨file借Thumb/复用一个实际encoder transfer；Without_Pin仍一job一独立JPEG。两selector必须可观察地连接同source/manager/control/context、primary geometry、原config pointer、同core/model lifetime/config generation，以及该**原文件**的Fsys sourceareas、原readback、两次exports和独立decode；缺source即拒绝。这里没有捕获组ID/跨selector sensor-frame retain：当前分别render，`cross_selector_same_sensor_frame_verified=false`。Screen2 adapter可编码，但原MPF/layout映射缺源证，checker明确返回missing，不作假映射或忽略作业。

### 复现与证据边界

从项目ROOT运行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider --color=no \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/runtime/analysis/test_functional_jpeg_codec.py \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/report/functional-camera-evidence/test_evidence.py --maxfail=1
```

最终原始摘要：`320 passed, 4364 subtests passed in 47.17s`。codec为105 normal+105 ASan/UBSan场景、1历史public-source pin和2实际C stdout→checker正例；原94场景（含27 Without_Pin）全部保留。实际C正例运行真正bridge/core/CMOS/JPEG并输出实际376B proof、packet/lease/free/logger；仅原SDK方法及caller-PC映射、broker/Fsys为HOST_TEST支持夹具，HOST_TEST verdict仍禁止capture提升。EXIF正例由已依赖Pillow/ffmpeg构造真正可独立解码的primary+160x120 JPEG，走原Fsys/readback/export检查夹具；它们不是native文件。完整默认仍 `require_media=True`，JPEG/H264/drain、原MPR/Fsys/存储门槛以及20a6/3-72/BB/HIST所有历史负例均保留。

本轮失败证据追加到codec `verification-main.json`：早期fixture role误判、configuration-only未初始化Thumb、独立transport缺INIT/verdict缺products、VDF局部body被覆盖，以及父共享refresh producer改为`global_va=%#lx`后旧literal源文本断言失败（39 passed/1499 subtests）。最终只将该旧测试改为精确匹配父当前共享formatter、command0141→原global910fa30选择和完整字段集合；生产VDF契约未降低。另一次排除该单项的104/4297中间通过不作为最终全通过替代。无旧run读取/修改/重验；未运行VM、debugger、信号、网络、真机/真实SD、主模型build或fullreg。文档按docs-generator `flavor=null`，其缺失tool-index/ops链接不触发外部bootstrap。

| Evidence | Finding | Path |
| --- | --- | --- |
| E-free：真实free后API、ACK/DONE同址重用、sticky失败和全部字段/因果负例，normal/SAN | F-free：source free调用本身不够，必须实际free0且匹配receiver/lease才能原Res消费 | actual receive snapshot → actual generic free rc → original Res → terminal DONE lease release |
| E-main：原schema与独立Comp、实际length readback、真实C logger到checker正例 | F-main：Main ACK0不退租，Comp需实际同ACK实参/原对象配置 | Main1226c4 → ACK120e64 → Comp122dfc → DONE122b44/readback |
| E-thumb：II/MM真实EXIF JPEG、type/count/offset/span/duplicate/另file/缺source/篡改负例 | F-thumb：同原file的Main0+Thumb1可验证，跨selector同sensor frame与Screen MPF仍未验证 | actual codec bytes → bounded IFD1 → same original Fsys file/exports/decode |

## 软件时钟 20a6 集成（此前）

本次范围仅为本目录 `check_evidence.py`、`test_evidence.py`、`README.md`。按 [control90b 的实际字段和原表 pins](../functional-camera-control/source-pins.json) 接入功能模型的单帧 readout/sync 能力，默认真实 State128 FPS30 对应 **`(word=30, half=1)`**；曝光和 ISO 不驱动该能力。全部 c00 BB9、d343 HIST10 的 schema、snapshot ID/census、所有权和生命周期负例保留。这里是 host 证据组件实现；physical/UI/原 AP 对新能力的业务应用均未验证，`capture_verified` 继续 false。

进入本任务的三文件版本没有 `full_snapshot`、旧 2/73 full fixture 或 control publication reader；实际已有媒体参数名为 `require_codecs`。因此本轮新增一个共享 `full_snapshot(State128)` oracle 和薄的 `check_control` source-publication join，没有替换不存在的旧实现，也没有重做既有 HIST/BB 框架。`check_frames` 现在公开默认 **`require_media=True`**，保留旧 `require_codecs=False` 组件调用兼容；默认仍要求真正 INIT/JPEG/H264/drain，首帧 histogram 或 timing 收据不能替代成片。

### 完整包与来源

`full_snapshot` 从该次完整、不可变、已验证的 State128 读取 aperture、FPS、instance/config generation，按原76块 schema 构造全部1748B：2012常量保持；201b取实际 aperture；2044保留 integrated fixed optics；20a6为第三个投影块。20a6 offset`0x664` 的16B严格为原type6/command20a6/header0、`+8 LEu32=fps`、`+12 LEu16=1`、`+14 LEu16=0`；FPS30时是 `0600a620000000001e00000001000000`。其它72块按明示零策略，计数严格 **3 projected /72 zero /76 defined**。

只允许原 AP73项表与 State128整数 FPS1..120的精确交集：`1,2,4,5,6,8,10,13,15,20,25,30,40,45,50,60,80,90,100`。测试独立验证原表 SHA256 `a387e2fc4d3fb45047f8f93d5064b575f04d74ac6998dabb6564775d98b75e90` 并推导全部 canonical tuples，再比对共享 schema 的完整76行。FPS3/61/120不接受，不能用当前曝光、ISO、近似值、等比但非原 canonical pair 或非零常数替代。

`check_full_snapshot(source_state, fields, raw=None, known=None)` 逐项要求常规 producer 的五个真实字段 `xsync_defined / xsync_source_fps / xsync_word / xsync_half / xsync_source_generation`、拷贝 flags、3/72/76 和 published generation。提供实际 `raw` 时比较全部1748B；提供 `known` 时精确比较1748B mask（仅 outer+1为0，其余为1），连201b/2044 header保留位的mask也必须符合本功能 assembler 的实际输出。任何 raw 字节、三投影块、header、padding 或 mask 改动均拒绝。

`check_transport` 消费 `FUNCTIONAL_CAMERA_CONTROL_*` 时，从实际 immutable broker output 文件取 State128，按完整 native origin/FNV、真实 bridge producer TID、INIT/STATE opcode、probe ID 和 console transfer先后连接原 PROBE。完整通知的1748B FNV与实际 accepted RECEIVE 的完整 wire/expected FNV、长度和 source/destination 一致才通过 timing join。新 publication 的五字段严格绑定该次 State128；同代 ACK-only不产生新 full。下一代 PROBE 尚未发布时可如实保留上一代五字段及其原 source，绝不拿最新 `config_generation` 盲比旧 cached 能力。错 source generation、同代 Config变化、旧代能力借给新 full、缺真实 source或错完整包FNV均拒绝。结果在 `transport.control` / `evidence.control` 中仅报告这组 timing/content 一致性。

**证据边界：** 当前生产 control logger 提供完整 wire FNV，没有独立1748B native raw文件或known-mask dump。native join使用实际 State128与原包FNV核对重建预期包；结果中的 `full_sha256` 是预期包摘要，不是另一次 native raw SHA读回。`raw/known` 的逐字节路径由 HOST_TEST直接消费验证，不能报告为已测量当前 native mask。新 `check_control` 不提供完整 CP lease census、ACK/free ownership或 AP property/UI应用验收；既有 BB/HIST 生命周期检查仍独立执行。原 control90b 的253 strict/SAN场景和 AP table/converter原字节验证是此前组件证据，本轮没有重新运行它们或启动原 AP。

### 明示 profile 与目标验证

`check_profile` 严格检查实际 `backup_profile.functional_camera_profile_fields` 的 clock policy：`virtual-one-model-frame-period-from-State128-fps-canonical-AP-pair`、clock_source=`State128.fps`、readout_frame_periods=1、exposure_independent=true、noncanonical=`reject-before-mode1-ACK`、精确 canonical rates、flash_trigger_supported=false；两份 manifest/backup_transport 的类型和值都必须一致。七个新增 false claims（BB work/units、Histogram bin semantics/physical callback/UI、original Xsync producer/physical capability）必须显式 false，不能省略、以0替代或被单独非法声明后忽略。实际 control出现时必须有完整 clock policy。

从项目 ROOT 执行本轮限定选择：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider --import-mode=importlib \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/report/functional-camera-evidence/test_evidence.py \
  -k 'Xsync or ACK_allocation or BB_ or Histogram or requires_complete_independent_typed_policy or Display_policy or Startup_policy or complete_HOST_TEST_actual_positive_stages_and_evaluate or verdict_gate_needs_both_products' \
  -q --tb=short
```

最终结果 **23 passed /77 deselected /2930 subtests passed（4.04s）**，其中新增 Xsync5项。覆盖30→30/1与多种其它合法频率、非法实际 State FPS3/61/120、源字段缺失、zero20a6、曝光替代、错误half/sourcegen/source FPS、同代/跨代错配、完整1748B逐字节篡改、padding/mask、ACK-only旧缓存、typed policy/falseclaim篡改；同时运行既有 BB/HIST/ACK和完整媒体 verdict门槛。Python无产物语法编译和 `git diff --check` 通过。选择中的完整媒体测试仅使用原有、明确标注HOST_TEST的临时Pillow/ffmpeg夹具，不是当前相机成片证据。

早期失败保留：第一次目标选择为 **1 failed /7 passed /91 deselected /2343 subtests passed（1.82s）**，原因是新 source join把实际 C `%016llx` 的 `native_fnv1a` 错送给普通十进制/`0x`解析器，报 `ValueError: noncanonical unsigned decimal/hex field`；现按完整16位裸十六进制摘要解析。修正后的中间选择为21 passed /79 deselected /2927 subtests（3.93s），最终以上23项通过。无旧日志回填。

旧 `run-52od7asp` 仍是 AP转换zero tuple失败，未打开、修改或重新验收。仅由共享oracle重建其旧zero20a6对照包，得到原完整 SHA256 `1116c69d00ce3ee55f85758d70d368ae43d726161fed323b78363f4988b35484`、FNV `1fae3c8aaffaf2d0`；两个值固定为回归断言，并确认新checker拒绝该包。它不能因新producer实现而变成成功。

| Evidence | Finding | Path |
| --- | --- | --- |
| E-clock：control90b实际record/source-pins、原73表摘要、完整76块schema与当前State128输入 | F-clock：one-frame pair由实际FPS精确定义；第三投影块/3-72全包oracle可验证，曝光不参与 | immutable source State128 → canonical domain → full1748 → native full-wire FNV与accepted RECEIVE |
| E-cache：full7 / ACK-only7 / 下一代PROBE仍缓存7 / full8的实际broker格式HOST_TEST与错代负例 | F-cache：source generation表示原full来源；最新probe不构成旧能力刷新 | probe ID/origin/TID → 原publication source → 保留旧五字段或新full五字段 |
| E-negative：逐字节/known-mask/typed-policy变异及原失败包精确SHA/FNV | F-negative：旧zero20a6、错source与非法声明都拒绝；本轮不是native capture验收 | focused pytest → 保留首次失败及旧run结论 → parent另做当前batch/AP/成片验证 |

本轮没有修改本目录以外的生产代码/测试/oldrun/batch，没有 VM、debugger、信号、网络、私有资产、真机/真实SD、主模型build或fullreg。没有新增独立报告文件；按 docs-generator 的 `flavor=null` 将E/F/P和复现记录留在此README，缺失的skill tool-index/ops文档情况沿用下述既有记录。

## 快照交错集成修复（此前 d343 FINAL）

本次同时修改授权的 histogram owner/header、C fixture/pytest 与本目录 checker/tests/README，并增补 histogram README。`record()` 在同一私有 mutex 内递增非零 `snapshot_id` 并复制完整 state，随后释放锁再调用 logger；没有新增 worker、轮询、sleep 或日志串行锁。主行 `event_role` 由真正执行的调用点传入：request=1、ACK=2、notification=3，COMPLETE/非 lease=0。三条 LEASE 各携带相同 `pid/cycle/snapshot_id`。新 serial 纳入私有 alias 拒绝；fork 检查先于 mutex；u64 serial 耗尽只记录 `RECORD_FAILED snapshot_id_exhausted=1` 并置 fault，不回绕或发送伪正常 ID。

checker 按实际 ID 严格 join 一条主行与 role1/2/3 三条 lease，再按 ID1..8 恢复 capture 顺序。允许不同线程主行/lease 交错，但字段缺失、重复主行/lease、ID 缺口/0/溢出/非 canonical、错误 PID/cycle/role、未知失败 tag 均拒绝；不回填无 ID 的旧日志。八个事件的 census 仍为 REQUEST_FREE1、SEND2、COMPLETE1、RECEIVE2、AP_FREE2，每个输出角色必须有自己的实际 send/receive/free 事件。事件角色不再由相邻 snapshot 的 flag delta 猜测。

SEND 要求其角色真实 `send_started=queued=1`、send_rc0 且 inflight0；RECEIVE 要求其角色实际 received、真实 live pointer、尚未尝试 free；AP_FREE 要求其角色实际 free_attempted/freed、free_tid 与 free_rc0。其它角色可在同次 snapshot 已推进多个状态，但所有持久 flags 必须单调并满足各自事件、原 source/D、allocation、pointer、TID、FNV 和整体消费关系。特别地，notification 的 receive/free 可以先于其 SEND **日志捕获**，queued 也可能已经提交；真正 inline send 未返回时则须 send_started/inflight 支持并最终 send0。SEND 捕获时同一 lease 可能正由真实 receiver 在锁外验证（releasing1），这不等于已收到或消费。RECEIVE 记录捕获前不允许该角色已经 free；request-free 记录之前不允许输出 allocation。busy/guard 必须真实单调释放，COMPLETE 时均0，不能凭 send0、event_role 或伪 consumed 替代两个实际 AP free。

新增组合自测直接运行生产 `functional-histogram.c` 的 `record()`，将其 **stdout 原行**喂给现有 `host_test_capture` → `check_transport` → `check_histogram`。模型1192B仍是明确的组件 fake 响应，前驱 transport/core proof 与原-global binding 仍为 HOST_TEST 支持夹具，不声称运行了真 core/AP。C 使用 pthread/condition 确定性覆盖：foreign ACK 主行与 sender SEND/notification 交错、inline receive/free、SEND 捕获时真实 receive validation 尚在进行，以及 send0 但没有实际 receive 的拒绝。正例逐项连接全部1192/1034/1024B 与摘要；同批真实 C 日志的错 ID/缺 lease/错角色/旧 allocation/重复 free/缺 receive/FNV/假 busy/假 consumed 负例均必须拒绝。另保留多状态同时可见的 HOST_TEST 边界与原290个 C 场景。

从项目 ROOT 执行以下限定选择，不生成 JPEG/MP4，不构建主模型：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider --import-mode=importlib \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/runtime/analysis/test_functional_histogram.py \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/runtime/analysis/test_functional_vdf_path.py \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/report/functional-camera-evidence/test_evidence.py \
  -k 'Histogram or histogram or BB_ or ACK_allocation or vdf_original_transport_owner or pinned_public_vdf_source_ranges or bb_neutral_packets or production_owner_keeps_real_bridge_dependency' -q
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider --import-mode=importlib \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/runtime/analysis/test_functional_jpeg_codec.py \
  -k exact_public_source_abi_and_interposition_pins -q
```

结果：**26 passed /82 deselected /668 subtests passed（16.82s）**；独立 codec 原 ABI/pin 选择 **1 passed /54 deselected（0.31s）**。histogram pytest 为8项，原290场景×strict/SAN保留；新增 stdout/serial 选择均以 strict C11/Werror/pedantic 与 ASan/UBSan/leak checks 执行。未动 full_snapshot/evidence20a6 或旧73 zero golden，未执行 VM、debugger、网络、真机、真实SD、主模型 build 或 fullreg。capture/UI/continuous/physical/original CP flags 继续 false。

| Evidence | Finding | Path |
| --- | --- | --- |
| E-ID：同锁 serial/state capture、调用点显式 event_role、严格 C/SAN 与 serial alias/overflow 负例 | F-ID：不需要锁内 logger，也能唯一连接一次捕获的四行 | actual owner record → pid/cycle/snapshot_id join → ID 顺序与八事件 census |
| E-stdout：真实 owner stdout，pthread/condition 交错、inline、receive-validation overlap；内容 checker 实际消费与变异拒绝 | F-stdout：交错不再被误配，多角色状态同时推进不再借 delta 猜事件；send0 仍不证明 AP 消费 | fake1192组件输入 → owner 真正复制/OSAL 生命周期/record → 原 helper/内容验证；真 core/AP/整机由 parent 另验 |

以下“本轮 ACK / BB / histogram”及后续段落保留前轮 c00/更早结果与当时限制；其中无 snapshot ID 的旧 schema 已由上述合同替换，不用于新日志验收。

**前轮状态：已修正 layout/display 在原请求释放后分配 ACK 的真实生命周期，并接入 BB9 与 first-histogram10。定向受影响选择58项/2041 subtests通过；最终新增11项/650 subtests通过。** 以下旧82/1665记录是当时的 HOST_TEST 结果；其旧合成夹具没有覆盖生产的先释放后分配时序，不能据此否认已确认的 checker 错误。原 native JPEG/MP4 与 `capture_verified` 仍未验证。

## 本轮 ACK / BB / histogram 检查

范围只包括本目录 `check_evidence.py`、`test_evidence.py`、`README.md`。原始固件、真机、SD、VM、debugger、主模型/observer 构建和整库回归均未执行。下述结果是有界的证据组件测试，不能替代重新冻结 batch、原 libc ABI 或实际 AP 运行验收。文档采用 `flavor=null`；本轮授权范围为上述三个文件，无额外 case 目录。

### 原 ACK 的真实分配时序

`check_vdf_path` 不再从 `REQUEST_FREE.ack_retained` 推导所有命令的 ACK identity。它要求实际 `RECEIVE.ack_retained` 为非零 live pointer，并逐记录验证分配地址、cycle、原命令/完整 wire/FNV、PID/TID、nonce、当前模型结果/代际、真实 send/receive/free 和最终 guard 释放：

| 分支 | REQUEST_FREE | 后续分配与 AP free |
| --- | --- | --- |
| path5 / Zebra6 | ACK 已分配，live pointer 必须为本周期的 p。原 live-alias/错误分配仍拒绝。 | 后续未 free 的 pointer 为 p；实际 AP free 后为 nil。旧记录可省略此前就未要求的可选分配诊断。 |
| layout7 / display8 / BB9 | `ack_retained=nil`、`allocation_returned=nil`，原 request free 已成功；过早分配 ACK 拒绝。 | 每条后续记录必须保留 `allocation_returned=p`、alias0、request-free rc0。RECEIVE 必须实际观察 p；实际 AP free 后 live pointer 为 nil。 |
| inline receive/free | REQUEST_FREE 规则不变。 | RECEIVE/AP_FREE 可以早于 SEND 日志，SEND 此时 live pointer 为 nil，持久 allocation_returned 仍为 p。SEND 不能借无分配/旧周期 pointer。 |

同一 allocator 地址在先前 lease 完成 free 后允许复用；地址本身不证明新 ACK 已分配。原 request 已退休的地址不再被视作 live alias。本 checker 没有回填旧日志，也没有把缺 SEND allocation、缺 RECEIVE pointer 或实际错误的 alias 变成成功。

### BB9：五个独立 initial/neutral 软件配置

实际 [shared ABI](../../runtime/analysis/functional-bb-startup-abi.h) 定义 op9：input32=`LEu16 native_command + LEu16 body_bytes + body28`，未用尾部全零；result192=`base160 + canonical32@160`，**class5 / proof kind5**。它沿用 `FUNCTIONAL_VDF_PATH_*` 五记录与 cycle census，新增实际 producer 的 `canonical_bb32`，并要求完整结果192/FNV、原 request free、独立 ACK receive/free。每次必须真实执行 active640×480 RGB、stride1920、921600B 的 render → independent sink copy/readback → retire，配置和 frame generation 各增1；仅 bank staged 不能生成回复成功。

| 原命令 / body | 仅支持的明示软件语义 | 独立 ACK |
| --- | --- | --- |
| 0111 / 28B | `00000f02` +24个零；软件 SQ idle/off，无延迟工作。 | 1111，status0 |
| 0166 / 28B | `0001` +26个零，或精确 `00010000000000000000000008000000070000000100000001000000`；两者明示软件 RGB identity，六个原word全部保存，不推Sony CreativeLook算法或单位。 | 1166，status0 |
| 0167 / 2B | LEu16为0或1；两个软件 RGB identity domain，余26个 envelope 字节全零。 | 1167，status0 |
| 015f / 4B | LEu32仅0；保留当前软件 gain tag，其初始值0不解释为 Sony ISO。Config48 ISO 不得被此配置改变。 | 115f，status0 |
| 0128 / 12B | `00 01 00 00`、LEu32 period∈{60,50,40,30,20,10,9,8,7,6,5,4,3,2,1}、四个零；scheduler disabled，period 是 opaque 值。 | 1128，status0 |

这些 ACK 的 +8..11 **全零**，不是1138/114c/1141的00590000。原 source 为该请求实际完整u32 `0x81cf....`，destination92840747；0141的精确 global 例外没有扩给五条 BB 命令，超u32的source不能截低32位后借用前缀。Enabled、除该精确初始token外的非 neutral、未知命令/body count/域、非零虚拟 padding 拒绝，即使输入 FNV 与 tail 自洽。

`BB_POLICY` 逐字段匹配 `backup_profile.functional_camera_profile_fields` 的 actual keys：`bb_startup_config_policy='initial-C-config-banks-RGB-readback-before-independent-reply'`、command顺序[0111,0166,0167,015f,0128]、`bb_startup_neutral_only=false`、`bb_startup_other_commands_neutral_only=true`、`bb_startup_0166_observed_initial_body_hex`为上表精确body、`bb_startup_0166_identity_policy='explicit-neutral-or-exact-observed-initial-tuple-RGB-identity'`，gain_nonzero_supported=false、interval_enabled_supported=false；`original_BB_C_configuration_work_verified` 和 `original_BB_C_configuration_units_verified` 均false。两份 manifest/backup_transport 的 typed 值必须一致，bool不能以0/1代替；当仅声明这些元数据时，profile 同样要求完整策略。profile off 时新策略字段为null，原验证声明仍为false；这些元数据不是运行完成事实。

这个例外来自 `run-pgf891an` 原saved stack-held builder36B，而非live request-memory读回；完整原builder216B pin、原FP链及排除包外`df9c..df9f`的字段证明在 [source-pins.json](../functional-vdf-path/source-pins.json) 的 `bb_0166_observed_initial`。原failed批次和shared-send assert保留。checker要求新输入的完整canonical32/FNV、独立tail32、192B/class5、实际同代RGB/source-sink/retire proof和独立status0 ACK receive/free，不能以token声明冒充工作。Sony物理算法、单位、CP/RTOS及capture均未提升。

### BB0166 本次定向验证

从项目ROOT执行，仅本组件BB选择：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/report/functional-camera-evidence/test_evidence.py \
  -k 'BB or bb' -q
```

本次为 **6 passed、103 deselected、471 subtests passed（1.22s）**。包含旧neutral、
新完整literal的async/inline独立ACK/free、完整192/class5/FNV/真实帧proof/counter关联；
两种identity token各28×255=7140个单字节替换全部拒绝。错误u32前缀、超u32/超u64/
未知类型source、非完整body、虚假work/units/physical声明、off与错误typed字段均拒绝。
本项为HOST_TEST replay，真实core帧数据的单独8项normal/SAN测试见core报告。
另行完整broker/profile单元为143 passed（0.42s）；其首次新测试2 failed/141 passed
（0.43s）因把bytearray传入原bytes-only Core.execute边界，现只修正测试转换为bytes，
未放宽生产边界。原`run-pgf891an`失败和live加载产物均未修改。

E-166-evidence=当前test_evidence的原始payload/完整日志回执fixture、typed profile与
[source pin](../functional-vdf-path/source-pins.json)；F-166-evidence（n/a_re，host_test，
high，evidence_ids=[E-166-evidence]）确认精确软件策略与同代证据join，保留原AP、物理及
capture未验风险。P-166-evidence：canonical32→完整192/真实帧proof→独立ACK/free→
typed scope；任何一步缺失不能借profile声明补齐。时间线为saved字节/完整builder核对→
shared策略→core/owner测试→声明与checker同步→本次正负定向复核。

### Histogram10：首个 enable1/mode1 的真实数据事务

`check_histogram(run, rows, transport)` 可单独返回 first-frame/readback/native ACK+notification AP-free 的证据；同一结果暴露为 `transport.histogram` 和 `evidence.histogram`。它要求完整实际 transport，检查真实 core snapshot 与所有前驱 serial/lifetime/counter/state/route 历史，不依赖 JPEG/MP4 存在。`check_frames(..., require_codecs=False)` 用于这种局部帧验证；默认 `check_frames(...)` 仍强制真实 INIT/JPEG/H264/drain，完整 capture 条件保持原样。

| 内容 | 严格规则 |
| --- | --- |
| 原 request12 | 精确 `0d2048010c00018001010000`；仅首个 enable1/mode1，op10最多一次，完整原 origin/FNV/producer TID 绑定实际 payload reference。 |
| input8 / result1192 | 精确 `4801040001010000`；base160、canonical8@160、1024B bins@168。**class6 / proof kind6**，active640×480、真实 source/sink/lease/retire、config/frame各增1，token0。完整1192B来自实际 immutable broker output 文件并验证 SHA/FNV。 |
| 明示 histogram policy | 四段软件 virtual-Y/R/G/B，各256个 u8 柱高；Y=`(77R+150G+29B+128)>>8`，逐段`(count*255+peak/2)/peak`，每段峰值255。实现/算法依赖冻结的真实 core 源码/构建与 actual C proof；checker 不会从 RGB FNV 反推出像素，也不称其为 Sony physical bins/units。 |
| 原 global D | 一条完整14字段 `FUNCTIONAL_HISTOGRAM_QUEUE_BOUND`，actual global VA0910fa20，两次完整4B读回都等于实际 source；同 PID/producer TID，bind_rc0、source_match/readback_verified1、capture0，必须在实际模型工作前。由公开 `ap-034e521c-034e5454.asm` 的 `034e53a8 BL 0165ead0` 确定 send 返回点034e53ac，与0141的034e4f3c/0910fa30分开。D只按实际 global绑定，不猜81cf前缀。 |
| ACK12 | 精确 `0d2048110c00018000005900`，source92840747、destination实际D。真正 RECEIVE 的线程可不同于原 sender；future 返回的原 ACK 必须由**原 sender**按同 cycle ticket free。 |
| notification1034 | header `0d200c210a040180` + LEu16 软件 selector1 + 完整1024B实际 bins。完整1034B由已验证1192B及固定协议头重构，其全包 FNV、四段 FNV、实际 native lease 的 wire FNV 必须一致；不把缺少 native send/receive/free 的重构字节当作已送达。 |
| Native logger（当前合同） | REQUEST_FREE、两次SEND、COMPLETE、两次RECEIVE、两次AP_FREE；主行显式 event_role，四行以相同 pid/cycle/snapshot_id 严格 join，按同锁 ID1..8 恢复捕获顺序。行可交错，缺/重/错 ID 或角色拒绝；无 ID 的旧 schema 不兼容。字段集合仍精确匹配，含持久 original_request；未知/失败/额外字段拒绝。 |
| 所有权 | 原 request先按Q free；随后独立allocD(12)与allocD(1034)，两份 live 输出不得 alias，ACK先send。每次 RECEIVE 必须观察该角色的真实 live pointer，AP_FREE后nil、allocation_returned仍保留；retired request地址可复用，不把诊断地址视为 live lease。ACK free_tid=原sender，notification free_tid=其**实际receiver**；两者均完成、真实send成功且dispatch退出才overall AP_consumed。 |
| 结果范围 | `first_frame_verified`、`readback_verified`、`native_ACK_and_notification_AP_free` 可true。UI_applied、continuous_histogram、capture_verified、physical/original CP/FIFO/RTOS、Sony bin semantics/physical callback始终false。 |

kind5/6 与旧 kind4 的一个重要 ABI 区别是：**kind5/6 proof 的 result_bytes/result_fnv 覆盖完整192/1192B配置/数据收据**；kind4仍是空 result。三种非 codec kind 均要求 encoder_consumed0、encoded_bytes0、empty encoded FNV、JPEG/H264 counter delta0，且只标为 `configuration_result_sha256`。不泛接受未知 kind/opcode，也不把它们送入 JPEG 或 H264 parser。

`HIST_POLICY` 的实际 typed 字段来自当前 `backup_profile.py`：policy=`first-enabled-mode1-RGB-u8-peak-YRGB-before-1148-and-210c`，commands=[0148]、channels=[virtual-Y,R,G,B]、bins_per_channel256、value_format=`u8-peak-height-255`、上述 luma/normalization 字符串、notification_selector1、logical_bytes1034；mode0/reenable/continuous_supported 与 physical/bin/UI verification字段均false。两份策略逐项比较，不增新的用户 option。

继承的原 source 合同在项目 ROOT `analysis/scratch/functional-histogram-0148-source/RESULT.md`：mode1收到210c只把第0段256B复制到event0xd5再释放原通知。C的0x400B清零/复制及单独1148不是数据到达证据；event0xd5到UI property的实际应用仍未闭合。因此本 helper只报告真实原生消息 receive/free与软件首帧，不称已验证四通道UI或持续stream。主main的 immutable-ticket future handoff集成和实际VM验收仍须独立验证。

### 定向验证与证据链

从项目 ROOT 执行；仅选中本证据组件新增项及受影响的显示/启动回归：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider --import-mode=importlib \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/report/functional-camera-evidence/test_evidence.py \
  -k 'ACK_allocation or BB_ or Histogram or VDF or Zebra or Layout or Display or Refresh or Startup' -q
```

首次新项验证为9 passed、2 failed/subfailed、82 deselected、533 subtests passed（2.02s）：producer并行新增original_request字段尚未入新夹具；另一个 standalone parser负例把有效非零lease改成另一有效非零值。已按实际 C 字段修正夹具/parser，并改为缺lease0，跨代际借用仍由实际 history/proof拒绝。随后上述受影响组件选择通过 **57 passed、35 deselected、2014 subtests passed（11.11s）**；补充未知opcode/class/跨角色alias和缺BB SEND分配后，同一选择最终为 **58 passed、35 deselected、2041 subtests passed（11.26s）**。最后增加无op也必须验证typed metadata的分支测试，单独运行 `-k 'ACK_allocation or BB_ or Histogram'`，为 **11 passed、82 deselected、650 subtests passed（2.08s）**。没有运行整库/fullreg，也没有用修改源码去回填旧 failed run。

最终source复核时，main的 `FUNCTIONAL_HISTOGRAM_QUEUE_BOUND` / future handoff尚未落盘，因此这里只依据用户指定合同与给定assembly固定上述14字段和034e53ac返回点；其真实主程序集成、日志镜像、immutable-ticket转交及VM执行仍未验收。Histogram logger只提供实际 full-wire FNV与四段FNV，完整1034字节来自实际core output1192及固定头的重构；没有伪称另有原生notification raw-hex字段或独立RGB像素留存。无快照标识的交错histogram logger记录会明确拒绝，而不是猜配或放宽线程free规则。

| Evidence | Finding | Path |
| --- | --- | --- |
| E-allocation：当前 functional-vdf-path.c 实际分配顺序、持久 allocation_returned 与 source-faithful async/inline HOST_TEST | F-allocation（组件已验证）：7/8/9的 REQUEST_FREE 必须无ACK分配；SEND日志可在inline AP free之后，RECEIVE live pointer与持久分配仍须一致 | 原 request free→真实 alloc→SEND/RECEIVE/AP_FREE→不可借旧cycle/alias/nonce |
| E-bb：shared header、当前 core/guest producer、actual backup_profile字段与五 neutral bank 夹具 | F-bb（HOST_TEST）：明确9/32→192/class5/kind5，五条status0独立reply，不改变相机ISO或伪造物理工作 | canonical32→真实RGB copy/retire proof→完整result192→原sender receive/free |
| E-hist：当前 histogram C/header 完整logger schema、原0148 source报告/assembly、实际typed policy与async/inline跨线程夹具 | F-hist（HOST_TEST）：首次1192和1034的完整内容/四段摘要/来源/所有权可连接；缺ACK原senderfree或notification实际receiverfree不能overall consumed | 实际op10 payload/coreproof→first-frame1192→独立1148 future与210c→各自actual receive/free；UI/physical/capture仍false |

本轮时间线为先修 allocation根因→核对新ABI/core proof差异→读取主会话落盘policy与histogram producer→新增严校验/无媒体夹具→保留首次失败原因并定向复测。docs skill的直属tool-index缺失；使用现有 stdlib/pytest 与 router 的 evidence-finding-path文档，没有安装、自举或扩展工具。

## 先前验证记录

**原0141 global queue 来源校验：最终组件验证为82 tests /1665 subtests，通过。** 其中原68/1345、startup8/197全部保留，新增绑定6/123；最后一次完整组件命令用时11.47s。新前缀为完整的 `FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND `，独立于 `FUNCTIONAL_VDF_PATH_*`，必须逐0141 cycle 消费。仅0141允许精确绑定的实际 global ID；其它五条命令保留 `0x81cf....`。本轮不启动、检查或修改 `run-rk07d71x`，也不把其已发生的 send assert 或未释放请求改判成功；实际 JPEG/MP4 和 capture 仍未验证。

**Earlier focused host baseline: 68 tests and 1345 subtests**, preserving all 65 tests /1313 subtests from the VDF/Zebra/layout/resource-diagnostic/disabled-display baseline and adding three grouped refresh cases. The Pillow/ffmpeg fixtures exercise transport, the 376-byte frame proof, VDF160/Zebra168/Layout192/Display176 native ACK ownership, JPEG/MP4 content, native completion and final-close helper stages. These are `HOST_TEST` replays; runtime0141 triggering, a newly frozen batch and current-VM capture acceptance remain unverified. Physical ASIC compatibility, original CP execution/RAM and original RTOS verification remain false for every verdict.

**启动寄存器阶段扩展：新增8项 HOST_TEST /197 subtests 通过，原68项全部 deselected，保留上述已 FINAL 的68/1345记录。** 新增检查只接受 guest 本地 canonical32 复制/独立读回与原114c的独立所有权周期；它不会增加 INIT、op7、`model_frame`、ready 或帧消费。晚期另一次原014c只有在自己的实际 Layout192、RGB copy/retire 和原生114c周期全部成立时，才能连接独立 `APPLIED_RECEIPT`。组件结果不提升为整机或拍摄成功；旧批次、`run-ucxhc4xe` 启动期 abort 和其它失败记录未修改或重新判定。原 SDK 合同与物理 work 仍未验证。

## Check a completed current run

From the native-camera package root, after the parent freezes and executes the complete batch:

```bash
: "${RUN:?Set the absolute completed functional run directory}"
: "${BATCH:?Set the absolute completed immutable unified batch directory}"
python3 -B report/functional-camera-evidence/check_evidence.py "$RUN" "$BATCH"
```

The second argument may also be the batch's `ready.json`. Both paths must be canonical absolute owned directories, with safe ancestors, and neither directory may contain the other. The checker never starts a VM/build/regression, loads target `.so` code, connects to a socket, installs dependencies, uses private dumps or accesses hardware. Existing Pillow/ffprobe/ffmpeg requirements belong to the reused independent decoder helper. Anonymous media/initramfs snapshots and bounded decoder processes are used only when evaluating completed evidence.

Exit 0 means both current-run products passed the full chain. Exit 1 means missing/invalid evidence; malformed CLI arguments use exit 2. CLI JSON goes to stdout. Optional `--output` creates one exclusive new JSON file directly beside this checker, outside both inputs; it never overwrites a receipt or writes into the run/SD.

## API and verdicts

```python
result = evaluate(run, batch)
```

| Field | Meaning |
| --- | --- |
| `verdict` | `PASS`, `SOURCE/TRACE_MISSING`, or `FAIL` for inspected invalid evidence. |
| `capture_verified` | True only when both JPEG and MP4 original current-VM chains pass every shared prerequisite. |
| `products.JPEG`, `products.MP4` | Typed per-product writeback, independent decode, functional codec, CMOS/encoder and original compressed-content statuses; selected file paths remain visible when another stage fails. |
| `evidence.batch` | Current immutable source/build/archive/regression/ABI/QEMU/original-library verification. |
| `evidence.graph` | Actual stable [graph evaluator](../functional-graph-evidence/check_graph.py) `evaluate(run, batch)` result and detailed thirteen-edge evidence. |
| `evidence.transport` | Actual raw request/output chunks, chunk ownership, whole-result reconstruction, committed mailbox/guest destination and final safe close. |
| `evidence.transport.VDF_path` | Optional original0138/op5, original0153/op6, original014c/op7, original0141-or-0152-or-0162/op8 and neutral five-command BB/op9 branches; exact command-specific configuration/result/proof and independent original ACK receive/free are mandatory. Unknown/failure tags reject; only the original three exact resource grammars remain diagnostics. |
| `evidence.histogram`, `evidence.transport.histogram` | Optional first-enabled mode1 op10: actual1192, full1034/FNV, exact original-global binding, separate future ACK sender-free and notification receiver-free. Local first-frame success does not grant UI, streaming, physical or capture acceptance. |
| `evidence.startup_layout_stage`, `evidence.transport.startup_layout_stage` | Optional guest-local startup register stage; exact producer grammar, original40/header/source/D, bank32/readback/FNV/generation and independent114c request-free/receive/free. The standalone result survives a missing/unattached broker. `owner_bound_to_mailbox` is true only after actual transport PID binding. Stage semantics/frame/initialization/ready/capture claims remain false; separately verified late op7 applications appear only under `applications`. |
| `evidence.CMOS_encoder` | Actual same-frame RGB render/consumer hashes, geometry, generations, counters, retirement and encoded-result joins. |
| `evidence.JPEG_causality` | Original SDK packet/method, current SDS lease, actual received/native ResCmd results and original Fsys/SD JPEG scan/coding equality. |
| `evidence.MP4_causality` | Actual original request/event ownership, raw Annex-B/AVCC equality, VideoInfo96/PI publication/reader retirement and ordered MP4 sample NAL equality. |
| `evidence.writeback` | Reused formal [native writeback checker](../native-card-write/check_writeback.py), both directory exports and real independent decoders. Its own scope keeps its `capture_verified` false. |
| `missing[]` | `{code, stage, detail}` with precise missing fields/receipts or validation errors. Completed stage evidence survives later failures. |
| Physical/original flags | `physical_asic_compatibility_verified`, `original_CP_executed`, `original_CP_RAM_verified`, `original_RTOS_verified`: always false. |

`HOST_TEST` manifests can exercise positive software stages but cannot receive native capture acceptance. Counts, ACK/ready assertions, screenshot hashes, synthetic receipts and standalone host media are insufficient.

## Accepted evidence and positive joins

### Current batch and unchanged selected code

The existing unified validator supplies `ready.json`, `inputs.json`, `inputs.tar.gz`, regression JSON/log, both original-libc ABI executions, actual host-model ELF/build receipt and exact model source archive. The checker validates their real bytes, complete source groups and current source equality before accepting the batch. The parent must freeze this checker/tests, both reused readers, `initramfs_identity.py`, and the graph evaluator's complete declared dependency closure. A separately authored acceptance manifest or old run receipt is not a substitute.

Same-run observer sources/archive must match the tested production and ABI inputs. `selected-initramfs.cpio` must be retained, fully hash-bound to the manifest, and parsed from the same private snapshot. The existing fourteen public original AP/MPR/Fsys/OSAL libraries remain pinned to their public SHA-256 values. Model compiler receipt/log, source archive, actual ELF64 host library and runner artifacts must agree; no model is loaded by the checker.

The native/directory-SD QEMU candidate is pinned to **`a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02`**. The actual selected executable, manifest file index, runner artifact and broker config must all match this one value. Production control **`e23589c44386c19417551c982e394b7a4e779f8e68a72f2964b705aca1e96c0d`** remains a separate preserved reference; this checker does not replace it or allow arbitrary hashes.

The typed functional profile remains the explicit top-row-first RGB888 software bus with original-MPR/Fsys-only output, separate unchanged strict profile, false physical/original-CP flags and the 256,000,000,000-byte directory SD. Integer 0/1 cannot replace boolean fields. Sony physical format compatibility is not required true for this approved software profile.

### Every actual request, chunk and release

The broker's exact [payload contract](../functional-camera-core/README.md) is consumed directly:

- `request.request_payload` and `core_result.output_payload` name exclusive `functional-camera-data/{sequence:020d}-in/out.bin` files. The directory must be 0700 and files 0600, owned, singly linked, and unchanged in device/inode/size/mtime/ctime.
- Each reference binds its producing event, sequence, opcode, original origin, model nonce, direction, token/total/offset, size, SHA-256, FNV and actual writeback digest. File names, duplicate inodes, per-file and aggregate limits are checked; response/core/request references must agree.
- The original 512-byte request header is reconstructed and its committed response checked. Actual C error, PID/pages/nonce/origin drift, unknown/failure/late-close events, sequence gaps, missing responses and inconsistent runner censuses fail.
- Actual READ_RESULT24 bytes must carry the current token, exact cursor, bounded capacity and zero reserved word. Actual RELEASE_RESULT16 must carry that token and the FNV of **all reconstructed bytes**, after complete consumption. Missing, short, overlapping or reused chunks fail.
- Exact concatenated output SHA/FNV and length must match the guest bridge's complete destination readback. No FNV composition from counts or opaque chunk hashes is accepted.

`producer_tid` in a mailbox header identifies the actual bridge-calling worker. Original SDK/request producer TIDs and original receiver TIDs are retained separately in their native receipts and joined through actual immutable request bytes; those different thread roles are not equated.

### Actual rendered RGB and encoder use

The broker's `model_frame` event binds the real read-only `fcam_model_proof_snapshot` v1 **376-byte** scalar POD to that one actual original C call and payload pair. The checker checks its instance, host owner PID, model lifetime, serial, opcode, configuration/frame/lease/packet generations and actual before/after counters.

For JPEG/H.264 frame jobs, actual render, encoder entry/return and retirement must succeed. Whole active RGB FNVs at render, consumer entry and consumer return must match for that same frame; dimensions, stride, byte extent and optical states must agree. Rendered/consumed/retired and codec counter deltas must describe the actual job. Actual JPEG SOS/entropy/EOI or actual H.264 packet bytes must equal the proof's encoded bytes/hash; the complete staged representation must equal its result bytes/hash/token.

INIT remains one rendered/retired sensor probe with no encoder consumption and no encoded result; its actual State128 counters are checked separately. Later INIT calls on the same model instance may return the already configured generation/counters without a new `model_frame` or reset to generation1. This permits original0138, original0153, original014c or original0141 initialization before later CP-control INIT, and unrelated prior initialization. The first display cycle's INIT is found by its complete origin (worker/source/destination/command/size/full-wire FNV), without assuming the first or last INIT is its match. Drain records require actual encoder return/EOS and no invented new render/consumption. State128 reads remain bound to the preceding real job's counters/generations, including intervening VDF/Zebra/layout/disabled-feature consumers. Kind4 display work and INIT kind0 never count as JPEG/H.264 encoding; real JPEG, H.264 and drain proofs remain mandatory.

### Original VDF path configuration and RGB sink

Opcode **5** accepts exactly **16 canonical bytes** and returns exactly **160 bytes** without an encoded result token. This is the functional profile's explicit RGB route, defined by [functional-vdf-path-abi.h](../../runtime/analysis/functional-vdf-path-abi.h); it is neither State128 nor JPEG/Packet96. The parser uses the actual little-endian layout:

| Offset(s) | Field(s) |
| --- | --- |
| 0, 4 | u32 ABI=1, result bytes=160 |
| 8, 16, 24, 32 | u64 model instance, committed config generation, frame generation, lease generation |
| 40, 48, 56, 64 | u64 canonical-input FNV, active source FNV, independent sink FNV, active RGB bytes |
| 72, 76, 80 | u32 width, height, packed RGB stride |
| 84, 88, 92 | u32 functional endpoint `0x90590819`, selected mask=1, completed mask=1 |
| 96, 100, 104, 108 | u32 class, enabled, config-readback=1, committed=1 |
| 112, 116, 120, 124 | u32 frame-consumed, retired, status=0, reserved=0 |
| 128..143 | Exact canonical16 config readback |
| 144, 152 | u64 before-frame generation, before-config generation |

The original24 wire must begin `0d20380118000180`. Canonical16 preserves original bytes8..20 completely and zeroes its tail13..15, matching the original conversion. Opaque config bytes cannot be discarded or compared only by path ID. Config byte4 must be at most2. Endpoint and mask are explicit software-profile policy values; original selector, CP FIFO and physical CP/RTOS compatibility flags remain false.

- Active path1/pins5,5/class1 must increment config generation, frame generation and rendered/consumed/retired counters exactly once. Source and independent sink FNVs must match the same kind4 proof, along with the actual lease, geometry and active RGB extent. Geometry also matches the preceding State128 configuration.
- Disabled path0/pins1,1/class0 commits config generation+1 with no new frame. Source/sink/active bytes/lease are zero; proof geometry/consumer observations are absent, and every render/consume/retire/codec counter is unchanged.
- The v1 proof remains **376 bytes**. Kind4 has zero `encoder_consumed`, encoded/result byte counts and result token, with empty encoded/result FNVs. Its 160-byte config receipt is checked separately from encoded media and reported as `configuration_result_sha256`, rather than `encoded_result_sha256`. No JPEG parser or H.264 packet parser consumes it.

VDF before-generations must match the latest actual transaction history, including intervening State128/CONFIGURE/VIDEO_BEGIN responses. Each VDF commits its own before-config generation+1; two VDF calls separated by a genuine configuration transaction need not have adjacent config generations.

When op5/op6/op7/op8, their native original0138/original0153/original014c/original0141/original0152/original0162 transport, or a lifecycle `FUNCTIONAL_VDF_PATH_*` record is present, the checker requires a bijection of successful display calls and sequential immutable cycles. Only the three exact resource-diagnostic grammars below are classified separately; unknown tags and failure rows still reject the evidence. Each cycle must contain exactly `REQUEST_FREE`, `SEND`, `COMPLETE`, `RECEIVE` and `AP_FREE`, after its actual bridge transfer. The first cycle requires a complete-origin-bound INIT. Every record binds PID, actual bridge/sender/receiver/free TID, dynamic `0x81cf....` caller for0138/0153/014c/0152/0162 (0141 instead requires the exact original-global binding below), destination `0x92840747`, exact original command/wire/FNV, canonical route, complete model result/FNV, instance and before/after generations. Missing, duplicate, failed, stale-cycle, aliased/reused ACK lease or promoted physical flags fail closed.

The independently allocated op5 ACK wire is exactly `0d2038110c00018000005900` (12 bytes, original1138). Original request free precedes send; real receive precedes real free on the original sender thread; successful send, completed model work and released guard are also required before `AP_consumed`. Both queued asynchronous delivery and receive/free inline inside send are checked against their actual state sequence. COMPLETE alone cannot establish AP consumption. All display branches stay optional for an existing complete media chain that never used them; old fixtures are not supplemented with invented display events.

### Resource reservation diagnostics

The source producer `tracked_native_reserve_resources()` in [menu-observe.c](../../runtime/analysis/menu-observe.c) uses the `FUNCTIONAL_VDF_PATH_` prefix for resource inspection as well as native lifecycle receipts. The shared checker previously sent these resource rows into the lifecycle-only tag check, causing `failed/unknown VDF native receipt`. It now recognizes only these complete source grammars:

| Exact suffix | Required diagnostic observations |
| --- | --- |
| `RESOURCE_DEPENDENCIES` | Exact nine fields: positive bounded PID/TID, accepted/proc/input/output AP-consumed/current-request-expected=1, output faults/capture=0. |
| `RESOURCES_TTS_TABLE` | Exact twelve fields: PID/TID, canonical hexadecimal appFw base and base+`0x5f66b08` address, literal table VA, 144-byte `144/144` reads, equal complete lowercase raw observations, unchanged=1, atomic snapshot/ownership verified=0. |
| `RESOURCES_RESERVED` | Exact complete resource schema from the producer, including decimal counters, slash-separated slot/open/handle/generation/epoch/creator pairs, canonical hexadecimal owners/handles and their integer widths. Accepted=1; failure/pending/live/retained flags and frozen/global-idle/original-CP/capture claims remain zero. |

Missing/extra fields, malformed or out-of-range values, wrong raw lengths/read observations, promoted claims and all other tags—including `RESOURCES_REFUSED`, `RESOURCES_FAULT`, `FAIL` and unknown suffixes—fail closed. These rows are preserved unchanged, including original `tag`, `line` and `fields`, under `VDF_path.diagnostics`. They do not supply a cycle, an ACK, ownership, a frozen snapshot, global resource idleness or a capture/physical claim. Valid diagnostics alone return `required=false`, `verified=false`, with no cycles; they cannot replace any of the five native lifecycle records.

`JFZ_VDF_RESOURCE_OBS` contains only the complete public text of one row of each kind from the original `run-jfz16a4v`; the repeated original diagnostics remain permitted outside cycles. Host tests retain PID258 and TID381 verbatim rather than pretending they belong to the HOST_TEST mailbox. The prior run/batch/refusal receipts are neither modified nor re-evaluated by this change.

### Original Zebra display configuration and pass-through RGB

Opcode **6** accepts exactly **Zebra8** and returns exactly **Zebra168**, using the same shared ABI header and 376-byte kind4 proof. The original 14-byte source request observed by the parent is `0d2053010e0001800300204b4100`, destination `0x92840747`, caller `0x81cf61c5`; the checker admits the actual dynamic `0x81cf....` caller. This is Zebra display configuration. It is not mapped to exposure or the 48-byte camera configuration.

| Evidence | Required join |
| --- | --- |
| Original raw14 | Header `0d2053010e000180`; full-wire FNV includes the original padding byte13. Bytes8..12 are preserved in Zebra8, followed by three virtual zero bytes. Padding is retained in raw evidence, never substituted into Zebra8. |
| Zebra8 | Byte1 (enable) must be zero; bytes5..7 must be zero. The other four original configuration bytes are opaque and preserved exactly. Enabled Zebra has no specified rendering/threshold units and is unsupported. |
| Zebra168 base0..159 | Same field offsets as VDF160, with result size168. `INPUT_FNV` hashes Zebra8; `CONFIG16` at128..143 equals the current committed VDF route, including all opaque bytes. |
| Zebra168 tail160..167 | Exact separately saved/read-back Zebra8, checked byte for byte. Wrong, omitted, extended or zero-padded substitutes fail. |
| Actual current route | Active/inactive comes from the current route and base `R_ENABLED`, independently of Zebra enable0. Initial software route is disabled `000101` plus13 zero bytes. |
| Active route | Real RGB render → independent sink copy/readback → retire; frame/rendered/consumed/retired each advance once, config generation advances once. Source/sink FNV, geometry and a strictly newer rendered lease bind the same actual kind4 proof. |
| Inactive route | Configuration stage/readback only; config generation advances once, frame/counters stay fixed, lease/active bytes/source/sink remain zero and render/consumer observations are absent. |
| Native ACK12 | Exact original1153 `0d2053110c00018000000000`, with successful status0. The original1138 `590000` payload or a different reply opcode fails. Same-sender actual receive/free and immutable cycle ownership remain mandatory. |
| Guest logger | `raw` is14 or24 bytes by actual origin; `model_result_hex` is168 or160 by actual opcode. Op6 additionally requires exact `canonical_zebra8` and `model_result_bytes=168`; a present op5 size field must be160. `canonical_config` always contains the route. |

Every op6 requires these independent typed fields in **both** host manifest and `backup_transport`:

```text
functional_camera_zebra_policy = original-0153-disabled-pass-through-RGB-sink-readback-before-1153
functional_camera_zebra_enabled_supported = false
functional_camera_original_Zebra_gate_verified = false
```

The capability policy `zebra_enabled_supported=false` describes the supported model, not a verified-result flag. Missing fields, numeric0 instead of booleanfalse, or promoted physical gate flags fail. When any Zebra metadata is declared, profile validation checks the complete policy even before transport validation.

`vdf_history` joins every display commit to the latest actual State128 or frame job, including intervening CONFIGURE and repeated INIT. After Zebra, layout or disabled-feature display config, the next unconfigured State128 must preserve all exposed Config48 camera parameters and the committed config generation; an explicit CONFIGURE/VIDEO_BEGIN, nonempty INIT or AF can change parameters through its own operation. Current route changes only through op5. Sink readback never counts as encoder consumption: `encoder_consumed`, encoded/result bytes/token and JPEG/H.264 deltas remain zero. Physical Zebra threshold/gate, original CP FIFO and CP/RTOS compatibility remain unverified.

The earlier disabled-route lease mismatch is resolved in the currently inspected core source: disabled responses write lease0. This source inspection and host verification do not replace the parent's component, dual-ABI, frozen-batch or VM verification.

### Original014c initial layout and full-frame RGB readback

Opcode **7** (`FCAM_OP_VDF_LAYOUT`) accepts exactly **Layout32** and returns exactly **Layout192**, token0. The supported initial case0 body is fixed byte for byte:

```text
07010100000000008002e0010000000000000000000000000300000000000000
```

Its original40 wire is `0d204c0128000180` followed by those exact32 bytes. The original request is display layout, with destination `0x92840747` and the actual dynamic `0x81cf....` source/D retained for the native reply. The software policy defines the area order as x/y/width/height and all-zero output area as full-frame pass-through. Only an already active **640×480 RGB888**, stride**1920**, **921600-byte** route is supported. This does not establish Sony's physical area order, source enum, YUV/framebody layout or CMOS/encoder geometry.

| Evidence | Required join |
| --- | --- |
| Layout192 bytes0..159 | Same base schema as op6, with result size192. `INPUT_FNV` hashes all32 input bytes; `CONFIG16` at128..143 equals the complete current route, including opaque fields. |
| Layout192 bytes160..191 | Exact separately saved/read-back Layout32. A self-consistent FNV/tail for a different body is still unsupported. |
| Real frame work | Render → same reading lease → independent consumer copy/readback → retire, with source/sink equality and the actual 376-byte kind4/op7 proof. Config and frame generations advance once; rendered/consumed/retired advance once. |
| State/history | Latest real before-config/before-frame, prior geometry and a newer rendered lease must agree. Repeated CP INIT preserves Config48, generation and counters, and supplies no new INIT render proof. Explicit later CONFIGURE may change geometry for a genuine media request. |
| Native logger | Every cycle row requires exact `raw`40, `canonical_layout32`32, `model_result_bytes=192`, complete result192/FNV and current `canonical_config`16. A present `realresultbytes` must also match the actual result size; present ACK-allocation and request-free fields must show the same allocated pointer, no alias and original-free rc0. |
| Independent ACK12 | Exact `0d204c110c00018000005900` (original114c), sourced from `0x92840747` to the saved original D. Original request free, actual same-sender receive/free, cycle/ticket, PID/instance/TIDs and released guard follow the existing five-record lifecycle, including inline delivery. |
| Codec scope | Kind4 has zero encoder consumption, encoded/result bytes/token and JPEG/H.264 counter deltas. Layout192 is reported as a configuration result; it cannot supply a JPEG, H.264 frame, MPR/Fsys completion or independent decode. |

Every op7 requires this complete exact typed policy in **both** manifest and `backup_transport`:

```json
{
  "functional_camera_layout_policy": "original-014c-initial-case0-full-RGB-passthrough-readback-before-114c",
  "functional_camera_layout_virtual_area_order": "x-y-width-height",
  "functional_camera_layout_virtual_zero_output": "full-frame-pass-through",
  "functional_camera_layout_supported_rgb_geometry": [640, 480, 1920],
  "functional_camera_layout_initial_body_hex": "07010100000000008002e0010000000000000000000000000300000000000000",
  "functional_camera_original_VDF_area_order_verified": false,
  "functional_camera_original_VDF_layout_hardware_verified": false
}
```

Missing fields, `null`, numeric0 for false, boolean/float elements in geometry, other geometry or promoted verification flags fail. As with VDF/Zebra, declaring any layout metadata invokes complete profile validation even before transport. Legacy op5/op6 manifests that declare none of these new fields continue to use their existing policies without requiring layout metadata.

The source investigation at project path `analysis/scratch/functional-bb014c-source/RESULT.md` distinguishes AP producer/wait/free, external014c→0305 and 1305→independent114c status conversion from actual hardware work. The actual metadata source→original FIFO ingress, actual downstream0305/1305 work and physical area/layout remain unverified. The checker keeps `original_VDF_area_order_verified`, `original_VDF_layout_hardware_verified`, original CP FIFO/RTOS and physical compatibility false.

### Startup guest-local initial layout registers

`FUNCTIONAL_LAYOUT_STAGE_*` is a separate producer from `FUNCTIONAL_VDF_PATH_*`. Its source contract is [functional-vdf-layout-stage.c](../../runtime/analysis/device-models/functional-vdf-layout-stage.c) and [header](../../runtime/analysis/device-models/functional-vdf-layout-stage.h). The startup policy permits only copying the fixed canonical32 body into a guest-local virtual register bank and copying it back, before display route work. Full-frame semantic application is deferred to another actual original014c/op7. No bridge/model operation is inferred from the startup request or its ACK.

Only when stage records appear, both manifest and `backup_transport` must contain these exact typed fields:

```json
{
  "functional_camera_startup_layout_policy": "guest-local-canonical-initial-register-stage-before-active-route",
  "functional_camera_startup_layout_stage_only": true,
  "functional_camera_startup_layout_frame_completion": false
}
```

Missing fields, `null`, bool/int substitution, wrong strings or promoted completion claims reject. Legacy traces without stages do not acquire this requirement. The existing late-op7 layout policy remains separate and mandatory for actual op7.

Every stage requires exactly one `READBACK`, `REQUEST_FREE`, `SEND`, `COMPLETE`, `RECEIVE` and `AP_FREE` record. All six carry the **complete same producer schema**, including the following groups; no omitted or extra fields are accepted:

| Fields | Grammar and join |
| --- | --- |
| `pid`, `tid`, `sender_tid`, `receiver_tid`, `free_tid` | Canonical decimal values. PID and actual sender are positive signed31 values; zero receiver/free is permitted only before its event. Startup receive/free runs on that cycle's sender. One guest PID is retained across all stages and bound to the actual mailbox when available. |
| `cycle`, `stage_generation`, `requests`, `completed_cycles`, `busy`, `faults` | Independent startup cycles and generations start at1 without gaps/reuse. Requests/completed counters remain u32; generations are u64. Completion increments only after the real original ACK receive/free, successful send and dispatch exit. |
| `source`, `destination`, `command`, `bytes`, `original_fnv1a64`, `raw` | Source is actual dynamic `0x81cf....` metadata D, destination `0x92840747`, command `0x14c`, bytes40. Header is exactly `0d204c0128000180`, followed by the fixed body below. Complete wire FNV is recomputed. Source is retained for ACK routing; it is never taken from the body. |
| `bank_written`, `readback_verified`, `bank_fnv1a64`, `readback_fnv1a64`, `bank32`, `copied_readback32` | Both independent32-byte observations equal the exact canonical body. Written/readback flags are1 and both recomputed FNVs agree; changed padding/body, self-consistent unsupported content or fake readback rejects. |
| `request_owned`, `request_retained`, `request_freed`, `request_free_rc`, `ack_retained`, `allocation_returned`, `allocation_alias`, `ack_wire` | READBACK retains the actual request; independently allocated ACK must not overlap it. Request free succeeds before send. ACK is exactly `0d204c110c00018000005900`; its actual allocation address is stable until original free. `%p` accepts only canonical nonzero lowercase hex or `(nil)`, never numeric0 as a substitute. |
| `queued`, `received`, `AP_consumed`, `send_inflight`, `releasing`, `allocate_rc`, `send_rc`, `free_rc`, `validation_rc` | Actual lifecycle states must match record order, including inline receive/free while send is inflight. Every error/alias/fault is0, and COMPLETE alone never establishes AP consumption. |
| `stage_only`, `semantic_applied`, `frame_consumed`, `hardware_ready`, `capture_verified`, `physical_ASIC_verified`, `original_CP_FIFO_verified`, `physical_CP_RTOS_verified` | Stage-only is1; every semantic/frame/ready/capture/physical/original flag remains0, even on a later application receipt. Extra `phase`, `ready`, `model_initialized`, `model_complete` or `model_instance` fields reject instead of granting claims. |
| `applied_receipt_verified`, `applied_stage_generation`, `applied_model_instance`, `applied_config_generation`, `applied_frame_generation`, `applied_result_fnv1a64` | All0 in the six startup records. An optional exact `APPLIED_RECEIPT` retains the completed latest stage state and supplies a distinct later result join; it cannot alter the startup stage's scope. |

```text
canonical32 = 07010100000000008002e0010000000000000000000000000300000000000000
```

All decimal/hex widths, lowercase raw lengths and fixed16-digit FNVs are bounded. Unknown, malformed, duplicate and failed records reject, including `FAULT`, `FAIL`, `TICKET_RETAINED` and `BIND_FAILED`. Cross-command ACKs, missing or failed request/ACK free, wrong PID/TID/D, stale stages and any startup stage after display work also reject. Stage records never enter the op5/6/7/8 native-cycle census.

`check_layout_stage(run, manifest, rows)` can preserve `status=staged-unapplied` with `verified=true` for the **local copy and original-register-ACK lifecycle only** when the broker never attaches. It explicitly returns `model_initialized=false`, `semantic_applied=false`, `frame_consumed=false`, `hardware_ready=false`, `capture_verified=false`; mailbox ownership and late application remain unverified. With an application record but no transport, status is `staged-late-application-unverified` and `late_application_verified=false`. Missing model work, JPEG/H.264/MPR/Fsys, graph or final close still blocks capture.

With real transport, an `APPLIED_RECEIPT` must join one later original014c/op7 through all192 bytes/FNV, exact input32 and result tail32, same model instance, config/frame generations, actual RGB source/sink copy and retirement, and that operation's **own** original request-free/114c receive/free cycle. The receipt's current TID binds the later original worker; its retained sender/receiver/free TIDs describe the separate startup ACK. Duplicate, regressing, foreign-instance or reused result/lease application fails. Multiple distinct increasing applications are admitted by the module API; none create a new startup frame claim. Success is reported as `status=staged-with-separate-late-op7`, `late_application_verified=true`, with independent `applications`; the stage's false flags stay false. An identical early114c wire cannot satisfy the late cycle.

本轮新增验证仅执行以下定向命令，从项目根运行；原68项/1345 subtests没有重跑：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider --import-mode=importlib \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/report/functional-camera-evidence/test_evidence.py \
  -k Startup -q
```

最终结果为 **8 passed, 68 deselected, 197 subtests passed**。正例包含三次startup stages→path→独立晚期014c→原JPEG/MP4链、仅stage的async/inline交付、未attach broker时保留局部证据，以及两个不同晚期原014c的递增apply。负例覆盖完整producer字段逐项缺失、未知/失败tag、typed policy、错误原wire/header/D/PID/TID、bank/readback/FNV/代际、别名和原free、晚期192B篡改、缺少实际RGB/retire或原生cycle、借早期ACK、重复/回退apply与错误phase。测试直接比较完整C logger字段集合及当前profile policy；没有构建/执行该C模块。

首次新测为 **6 passed, 1 failed, 68 deselected, 192 subtests passed**：仅stage夹具沿用的最小State128配置代际为0，因此在检查缺失INIT proof之前报了`state configuration generation regressed`。仅修正新夹具为合法代际1且仍无frame proof，之后7项/192 subtests通过；补充两个实际producer失败tag及多次apply后，最终8项/197 subtests通过。既有68项、w2e批次和nativeucx失败记录保持原样，没有重新评估、补填或提升为success。

| Evidence | Finding | Path |
| --- | --- | --- |
| E-stage-source：公开stage C/header与当前`backup_profile.py`字段；完整字段集合/typed值HOST_TEST比较 | F-stage-scope（tested）：stage是guest本地寄存器复制/读回与独立原114c生命周期；不产生模型初始化或帧工作 | `STARTUP_LAYOUT_POLICY` → `check_layout_stage` → 独立`startup_layout_stage`结果 |
| E-stage-replay：上述定向命令，8项/197 subtests；三次stage与晚期真实op7的HOST_TEST完整join | F-stage-join（HOST_TEST）：晚期apply须匹配另一次实际192B结果、RGB/retire与自己的原生free周期，早期ACK不可借用 | `check_transport` → `check_vdf_path`/`vdf_history` → stage late-application join → 既有`check_frames`/JPEG/MP4判据 |

范围仅为本目录三个文件；没有新反编译、graph/runtime修改、VM、fullreg、build、私有dump、旧run重评、真机或真实SD访问。本段为普通技术实施记录（`flavor=null`），时间线为读取公开producer→新增parser/夹具→修正新夹具单项拒绝原因→定向验证。原SDK契约、物理ASIC与CP/RTOS work保持未验证，`capture_verified=false`。新的实际VM/冻结批次验收由parent独立完成。

### Original0141 refresh, original0152 disabled peaking and original0162 off

Opcode **8** (`FCAM_OP_VDF_DISPLAY_CONFIG`) requires a typed **16-byte** input and returns exactly **176 bytes**, token0. Its envelope is LEu32 original native command, LEu32 original body byte count, then body8. The original native header remains separate and participates in the complete original-wire FNV. The three commands share an opcode but retain separate native command, body grammar, saved/read-back tail and independent ACK.

| Command | Accepted envelope body | Original native wire and independent ACK |
| --- | --- | --- |
| `0141`, body bytes0 | No native body. All **eight virtual bytes are zero**; the exact typed input is `41010000000000000000000000000000`. | Original8 is exactly `0d20410108000180`; independent ACK12 is exactly `0d2041110c00018000005900`. |
| `0152`, body bytes8 | `sel=3`, enable0, level0..2, magnification0/10/40, color_type0; final Y/Cb/Cr must equal one of `(81,90,240)`, `(210,16,146)`, `(29,255,83)`, `(235,128,128)`. All eight bytes are preserved. | Original16 header `0d20520110000180`; the parent's observed disabled request is `0d205201100001800300010000eb8080`. ACK12 is exactly `0d2052110c00018000005900`. |
| `0162`, body bytes2 | Original two bytes `00 00`, followed by **six virtual zero bytes**. Feature identity remains unnamed. | Original10 is exactly `0d2062010a0001800000`; ACK12 is exactly `0d2062110c00018000005900`. This wire is an accepted source-defined fixture, not a claim of a newly observed VM request. |

The inherited [AFTER-BB source investigation](../../../../../../analysis/scratch/functional-cp-vdf-startup-inventory/AFTER-BB-RESULT.md) identifies0141 as display refresh. Original AP `034e7d50` sends its8 bytes through `034e4dac` using the global queue object at `0910fa30`, created during startup by `01710808` as type2. The later `034e7da4→034e4104` receives12 bytes and frees that response on the same actual D; it does not destroy the global queue. CP `0309→1309→event295/kind1` constructs independent1141 with status00590000 and metadata source`92840747` to that saved actual D. The original downstream work/native FIFO ingress remain unverified; this implementation checks the explicit software RGB consumer and exact native receipts. These source addresses are inherited evidence, not newly executed observations. The project-relative source path is `analysis/scratch/functional-cp-vdf-startup-inventory/AFTER-BB-RESULT.md`.

The four color triples and field names follow the original AP producer and CP front-end contract; they do not define physical colorimetry, threshold units, a peaking operator or the identity of0162. Enable/on and unknown selectors, levels, magnifications, color types, palettes, body counts, commands or nonzero virtual padding fail even if their input FNV and returned tail agree with each other. The batched source findings are retained at project paths `analysis/scratch/functional-ap-startup-frontier/RESULT.md` and `analysis/scratch/functional-cp-vdf-startup-inventory/RESULT.md`; they are inherited here without repeating the opcode investigation.

Display176 uses the base160 offsets above with ABI1/result bytes176. `INPUT_FNV` hashes the **complete typed envelope16**. `CONFIG16` at128..143 remains the exact currently committed VDF route, including opaque bytes; bytes160..175 are this command's separately saved/read-back envelope16. They cannot be replaced by Zebra8, Layout32, another command's tail or the route itself. The shared maximum remains192 for Layout192.

All three commands require an already committed **active** route. Any legal current RGB geometry is accepted, including non640×480: refresh and the disabled features perform full-frame pass-through without a crop. Actual render → same reading lease → independent RGB copy/readback → retire must succeed before config/frame generation+1 and the independent reply. The 376-byte kind4/op8 proof must show rendered/consumed/retired+1 with source/sink equality, matching geometry/extent, fresh lease, same model instance/owner/lifetime and no encoding. Encoder consumption, encoded/result bytes/token and JPEG/H.264 deltas stay zero. Config48 camera parameters and current route are preserved through repeated CP INIT; it must read existing counters/generations without another INIT render proof.

Every op8 requires these exact fields in **both** manifest and `backup_transport`:

```json
{
  "functional_camera_display_config_policy": "original-0141-refresh-0152-disabled-and-0162-off-RGB-readback-before-independent-reply",
  "functional_camera_display_config_commands": [321, 338, 354],
  "functional_camera_peaking_enabled_supported": false,
  "functional_camera_display_flag_enabled_supported": false,
  "functional_camera_original_Peaking_operator_verified": false,
  "functional_camera_original_0162_feature_verified": false
}
```

Here321/338/354 are0141/0152/0162. Missing fields, `null`, bool/int substitutions, incorrect list contents/order/types and promoted claims fail. Declaring any display field also invokes the complete policy during profile validation; old profiles with no op8 and no display fields remain accepted without the new fields. The actual current producer's policy is compared with the checker in the focused test.

Each native lifecycle row requires `canonical_display16`, `model_result_bytes=176`, complete `model_result_hex`/FNV and `canonical_config`16. Original raw length/header/body/full FNV, source `0x92840747` → saved actual D for the independent reply, dynamic caller, PID/nonce, sender/receiver/free TID, original request free, ACK pointer, cycle state and five lifecycle records follow the same shared joins. None of0141/0152/0162 can consume another command's1141/1152/1162 or saved tail, even though all three statuses are00590000. Original command census/mapping and the first display's complete-origin-bound INIT remain enforced. The same global D and allocator address may be reused after the previous response is freed; neither per-refresh queue creation/destruction nor adjacent bridge sequence/frame numbers is required. Genuine CP/State or MPR transactions may occur between send and the later receive. Immutable original bytes, actual command, cycle, sender/receiver/free TIDs and that cycle's model result/generations still bind the response; an old or foreign response cannot satisfy it. Kind4 configuration results never replace JPEG/H.264 jobs, SDK mode1/native completion, MPR/Fsys writes or independent decode.

### Bind each original0141 to the actual original global queue

The accepted full record name is **`FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND`**, including when mirrored as `OBS FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND`. It is neither a `FUNCTIONAL_VDF_PATH_*` lifecycle tag nor a resource diagnostic. The checker joins exactly one complete successful observation to **each** original0141 cycle, before that cycle's first same-origin model transfer (including INIT when present) and all owned lifecycle records, after the preceding cycle's final record. A previous cycle's observation, an extra/orphan observation, or a missing current observation rejects; identical immutable global IDs may repeat with a distinct current receipt. Accepted observations remain visible as `VDF_path.cycles[].refresh_queue_binding` only on0141 cycles.

The trusted main helper must read the original appFw global twice and compare it with `real_get_source(request)` before calling `functional_vdf_path_bind_refresh_queue(unsigned source)`. The bind API itself cannot establish the read provenance. Its successful observation has exactly these14 fields, with no omissions, extras or failure prose:

| Fields | Required content |
| --- | --- |
| `pid`, `tid` | Positive bounded signed31 decimal values; same actual mailbox PID and native0141 bridge/sender TID. |
| `caller_pc` | Original appFw return site `base + 0x34e4f3c`, canonical lowercase `%#lx`. The inferred base is positive and in the existing appFw address range. |
| `global_va`, `global_address` | Literal VA `0x910fa30`, actual address `base + 0x910fa30`. Equivalently, `global_address - caller_pc = 0x910fa30 - 0x34e4f3c`; no new base field is needed. |
| `source`, `first`, `second` | Canonical lowercase `%#x`, all equal the actual metadata source of this request. The source is a nonzero u32 other than `UINT_MAX` and `0x92840747`; no fixed owner/high16 is inferred. |
| `read_before`, `read_after` | Both decimal4, each an actual complete four-byte pread observation. Short, negative, differently sized or unequal reads reject. |
| `bind_rc`, `source_match`, `readback_verified`, `capture_verified` | Exactly0,1,1,0. A failure uses the same prefix but never qualifies as a successful bind. |

Every one of the five native0141 lifecycle records must additionally have `refresh_queue_bound=1` and `refresh_queue_source` exactly equal to its actual native origin/source and this cycle's observation. Later0141 cycles must retain the same bound global ID; coherent replacement of all later source fields still rejects. Other commands may have snapshot0/source0 or an already bound snapshot1/sourceID, and legacy non0141 fixtures may omit both fields. Such snapshots do not authorize that other command or provide a model/frame result. All five other commands retain the old `0x81cf....` caller check even if a valid0141 binding is present.

The parent supplied the bounded read result for the original wire `0d20410108000180`, metadata source `0x80946189`, and two identical LE4 global observations `89619480`. The checker accepts that source only through the complete current receipt and snapshots above, and also admits other actual global IDs with the same evidence. The inherited source contract at project path `analysis/scratch/functional-0141-global-queue-contract/RESULT.md` establishes dynamic type2/operation`0x2a` with the actual subsystem owner, rather than fixed owner`0x1cf`. It also identifies savedLR`0x34e4fcc` as the failed-send `0x4a5` assert; it is not allocation failure evidence. These source/runtime findings were supplied by the parent, not reread from or re-evaluated against the preserved VM here.

Binding alone grants no rendered frame, semantic completion, JPEG/MP4 or capture claim. Display16→176, the full independent tail16/FNV, current route, actual whole RGB source/sink copy and retirement, 376-byte kind4 proof, original request free and separate original1141 receive/AP-free remain mandatory. The existing endian and asynchronous saved-D checks remain active. Unknown `FUNCTIONAL_VDF_*` tags, including invented refresh/diagnostic suffixes, still reject; only the original three exact resource grammars remain diagnostics. No profile/user option or display policy is added.

本轮复现（项目 ROOT；仅此证据组件，不是 fullreg）：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider --import-mode=importlib \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/report/functional-camera-evidence/test_evidence.py \
  -k Refresh_binding -q

PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider --import-mode=importlib \
  final/a7c2-re/report/2026-10-17-qemu-native-camera/report/functional-camera-evidence/test_evidence.py -q
```

| 执行 | 实际结果 |
| --- | --- |
| 首次新绑定定向 | **6 passed, 76 deselected, 123 subtests passed**，1.30s |
| 首次完整证据组件 | **82 passed, 1665 subtests passed**，11.45s |
| 补充完整record名称与OBS允许列表/回读断言后最终完整组件 | **82 passed, 1665 subtests passed**，11.47s |

六组绑定测试覆盖实际`0x80946189`、另一动态ID`0x80abcd12`、原81cf夹具和ID1；async/inline、同ID两次独立收据、之后其它命令snapshot已bound1，以及HOST_TEST的既有JPEG/MP4内容与独立解码join均通过。旧0141默认81cf夹具也显式生成每次当前绑定收据；其它五条命令没有凭空新增绑定日志。每次0141的176B/tail16/token0、实际RGB proof、原receive/free和scope false仍参与校验。所有结果仍是HOST_TEST，不能证明当前VM拍摄。

负例包括每个收据字段缺失/额外字段、错误caller/global差值、read短/错误长度/失败、zero/max/SID和溢出ID、原LE4反序、读值/source不符、PID/TID不符、失败bind及promoted flags；五条0141 snapshot逐条缺bound/source、未绑定/错误source也拒绝。跨cycle缺失/借用/重复/迟到收据、旧绑定替换成另一组自洽source、孤立绑定、未知refresh/额外diagnostic tag、失败prose、duplicate/truncated OBS均拒绝。完整绑定仍不能补足缺失RGB/copy/retire、缺REQUEST_FREE/RECEIVE/AP_FREE或失败原free。其它五条命令逐一测试8094 source仍被原81cf门禁拒绝。

只读source核对确认主helper的14字段与checker相同，实际`record("FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND ",text)`能匹配当前`mirrored[]`里的`FUNCTIONAL_VDF_REFRESH_QUEUE_`前缀，完整OBS record重新解析后保留同tag/fields；检查不依赖只搜索PATH前缀。这个核对仅是源码与组件断言，未构建或运行主helper。没有失败的本轮组件测试；未重新执行旧negative run、重评或回填rk07、重冻batch、build、ABI、VM、网络或真机。文档采用普通实施记录（`flavor=null`），Evidence为只读producer/继承source合同与上述两条复现命令，Finding为组件已验证的逐cycle来源门禁，Path为main只读收据→snapshot精确source→原176B/RGB/ACK/free joins。工具文档的直属`tool-index.md`和`ops/evidence-finding-path.md`缺失；后者复用现有router副本，未安装或自举工具，也不影响实际Python/pytest验证。

### Original JPEG request, SDS and native completion

The exact [JPEG receipt schema](../functional-jpeg-codec/README.md) is required, including `original-request-lease`, `original-received-ack/done` and `original-rescmd-ack/done`:

1. Parse all 104 actual SDK bytes, envelope/body lengths, original SIDs/command, zero response tag, dimensions and mode. Bind the actual original ExecCmd/caller/object identity and full request FNV.
2. Parse the original SDS type/unit, offset, stream position and capacity. Bind its current lease address/range/token/generation to `output-readback` and the real STILL result. Verify the actual full-JPEG or no-SOI `[model_offset, model_offset+readback_bytes)` interval and FNV.
3. Compare both actual 16-byte received replies with actual original ResCmd arguments, response SIDs/MID, callback entry/caller, same receive/callback thread and lease generation/token. ACK must return the original wait value; Done must actually return zero and successfully release the lease.
4. Parse the final original Fsys/SD JPEG. Ordered nonmetadata coding segments, geometry and complete SOS/entropy/EOI must equal the encoder output. APP/COM additions or replacement are permitted; changed coding tables, scan bytes, invalid ranges or extra JPEG bytes are not. The exact encoder/file scan offsets, SHA and validated original Fsys contribution ranges are retained.

This compressed-data equality, actual typed native job/completion and actual Fsys contribution/readback proves the join across legitimate MPR metadata staging. No global memcpy tracer or assumption that opaque whole-file hashes are interchangeable is added.

### Original video requests, VideoInfo96, PI and MP4 samples

The exact [MPR receipt schema](../functional-mpr-codec/README.md) is required. The bounded first proof admits one Open epoch and one complete H.264 MP4, 30 fps and native 90-kHz timestamps:

1. Parse all four original 48-byte Open/Start/Stop/Close requests and events. Verify actual PID, producer/receiver TIDs, request association, instance, epoch, memory generation, event allocation address and full raw body/FNV. Each original receive/free pair must preserve same-receiver ownership and zero operation result. Host CANCEL is not original Stop/mux completion.
2. Reconstruct every Packet96 result from actual broker chunks, parse exact raw Annex-B configuration/AUs and real EOS, then convert delimiter-separated NALs to their ordered payloads/BE32 representation. Check configuration stability, geometry, packet/frame generation and native timestamp order.
3. Bind every `FUNCTIONAL_MPR_ES` readback's actual source offset/length/hash, model token, call request and ES destination lease/extent to those actual bytes. Compare actual converted AVCC bytes/FNV and ordered NAL payload FNV; never compare Packet96+Annex-B FNV to AVCC or MP4 FNV.
4. Reconstruct each actual 96-byte VideoInfo descriptor, including parameter sets, source address/size, timestamps and EOS. Check current PI/ES/read/control leases, slot/ticket/generation/cycle, cursor and counter publication. Every retained descriptor must be read back unchanged and returned by actual original read-cursor advancement through its specific slots/tickets before final original Close. Counts alone do not establish ownership.
5. Parse the actual final MP4's `avcC`, `stsz`, `stsc`, `stco`/`co64` and `mdat` sample extents. Compare exact ordered parameter sets and per-sample ordered NAL payloads with actual encoder/ES data. Reject missing/overlapping/outside-media extents or altered NALs. Independent full decode frame count and geometry must agree.

The first parser intentionally requires a single ordinary AVC video track with bounded nonfragmented sample tables; unsupported layouts remain negative evidence rather than being searched heuristically for matching bytes.

### Original Fsys, both SD exports and final teardown

The unmodified native-card-write helper validates every actual request/source contribution, original submit/callback/finished/callback-return, native Open/Read/EOF/Close, complete observation coverage, host readback SHA/FNV and two exact directory export manifests. Pending/failed unselected tokens invalidate completeness. Actual Fsys/export PID must equal the functional mailbox/graph owner.

JPEG is pixel-decoded with a decoded RGB SHA-256. MP4 is counted by ffprobe and fully decoded by ffmpeg in strict error mode, with final frame count equal to the probe and content join. Both products must pass; one decodable file cannot pass combined capture.

Acceptance requires the **final** `phase=closed` runner receipt, console digest at close, final original video Close/event free and successful write completion. Broker lifecycle must be all responses → actual model cleanup → detach commit → mailbox detached → debugger disconnected → safe cleanup. Temporary exports that let `menu_live` continue are not final-close receipts. Console, broker JSONL, manifest, closed runner, actual payloads and frozen sources/batch hashes are checked again before the verdict.

## Bounds and failure handling

The helper's existing 64-MiB console, 128-MiB media/source snapshot, 512-MiB read budget and bounded private decoder limits remain. Additional JSON/JSONL, per-line/event, tar expansion/member, payload file/read, NAL, box and sample limits fail closed. Duplicate JSON keys, nonfinite values including exponent overflow, archive traversal, symlinks/hardlinks, changed/short reads, unsafe permissions, failed C results or failed native teardown cannot pass.

Evidence is plaintext research evidence. SHA-256 binds actual bytes to receipts; it does not authenticate the producer. FNV is used to match existing actual native observations and is not collision resistant.

## Focused tests and verification status

`test_evidence.py` preserves the existing capture/VDF cases and adds **nine Zebra cases**. Legacy no-op6 fixtures retain their original operations and receipts. New explicit Zebra8 entries produce mixed0138→0153→path0→0153→path1 cycles, CONFIGURE transactions and same-instance repeated INIT before the original JPEG/MP4 chain. That history commits config generations2,4,6,8,10, yields active flags1,1,0,0,1 and frame generations2,3,3,3,4, and ends at rendered/retired9, consumed8, JPEG1 and H.2644. Separate first-Zebra cases start with original0153, CP or unrelated INIT and cover both async and inline ACK delivery; only one INIT probe renders.

The negatives cover all Zebra168 fields and tail bytes, full-wire padding, Zebra8 input FNV, current-route opaque bytes, self-consistent wrong before/after generations or reused RGB leases, camera-parameter/repeated-INIT drift, exact op6 request length, wrong1153 status/opcode, truncated/extended results, stale cycle/ticket ownership, missing actual receive/free, same-sender TIDs, active missing frames, idle invented frames and codec-counter promotion. Host/backup missing, wrong and incorrectly typed Zebra policies fail. Removing original JPEG/H.264/drain, SDK native completion, original MPR event/free or either independent decode still fails.

The nine new diagnostic/layout cases cover complete public diagnostic grammar and retention, unknown/failure suffixes, missing/extra fields and false-claim promotion. Mixed0138→0153→014c→CP INIT commits config generations2,4,6 and frame generations2,3,4 on active640×480; CP INIT reads rendered4/consumed3 without another render. An explicit later CONFIGURE restores24×16 only for the existing media fixtures. Full replay ends with rendered/retired9, consumed8, JPEG1 and H.2644, while `HOST_TEST` and the unfrozen graph continue to prevent capture acceptance. Removing all media work still fails the required JPEG/H.264/drain proof gate.

Layout negatives exercise every result field and all32 tail/input bytes, including self-consistent unsupported body/FNV/tail, wrong shape/geometry, current-route drift, before/after generations, reused leases, Config48 preservation, mailbox opcode/input32 and payload binding. Native negatives cover the exact114c opcode/status, original40/FNV, nonce, PID/TIDs/source/D, stale cycles, partial/missing receive/free, foreign rows and lifecycle state. Kind4 proof mutations reject invented encoding, missing render/copy/retire, counter changes and owner/lifetime/lease drift. Both policy copies reject missing/None/wrong/incorrectly typed fields; legacy no-layout profiles remain accepted by profile validation.

Seven display-config cases extend the same fixtures with `('display', command[, body8])`, leaving legacy bool/bytes8/bytes32 entries and all prior tests intact. The mixed0138→0153→014c→0152→0162→CP INIT history commits config generations2,4,6,8,10 and frame generations2,3,4,5,6. CP INIT reads **rendered6/consumed5**, without an additional render. Both op8 tails and input FNVs are independently checked; the original disabled0152 bytes and distinct1152/1162 ACKs are asserted. The full media replay ends **rendered/retired11, consumed10, JPEG1, H.2644**, with graph/native acceptance and capture still false.

The new grouped negatives cover unsupported enable/on/body fields and typed envelope lengths, wrong independent tail/input FNV, current route/before generations/stale leases, camera-parameter preservation, missing copy/retire and codec promotion, borrowed ACK/tail, missing lifecycle/free, wrong nonce/SID/TID/native command, mailbox input16/op8 and retained payload binding. A non640×480 inline-delivery replay and all four original palette triples pass; idle routes fail. Both manifest/backup policy copies reject missing/None/wrong types and unsupported command lists. These cases reuse the existing bounded joins rather than adding a per-byte mutation suite.

The op8 extension first preserved **58 tests /1113 subtests in6.89s**. Its first expanded run reported **65 tests passed /1311 subtests passed plus2 failed subtests in8.56s**: both new ABI-negative assertions wrote the existing ABI1 unchanged. The fixture mutation was corrected to ABI0. The final complete focused command below passed **65 tests /1313 subtests in8.45s**. This is host evidence only; core/guest compilation, dual ABI execution, a newly frozen unified batch and a completed current VM remain the parent's integration checks. No old run or failed receipt was changed.

The three refresh cases add the source-defined `('display', 0x141)` fixture with explicit native8/body0 mapping, rather than treating it as0162/body2. The full0138→0153→014c→0152→0162→0141→CP INIT replay commits config generations2,4,6,8,10,12 and frame generations2,3,4,5,6,7. A separately retained opcode2/State128 transaction with CP origin occurs between refresh SEND and RECEIVE; the following repeated CP INIT reads **rendered7/consumed6**, config12/frame7, without a new render or camera-parameter reset. The full media replay finishes **rendered/retired12, consumed11, JPEG1, H.2644**, and its positive software joins still leave `capture_verified=false`.

Two successive0141 cycles reuse the same dynamic D, original8/ACK12 and freed allocator address, while retaining separate actual results, generations and cycle ownership. Grouped negatives reject missing/extended/wrong original8/header, body byte counts2/8, nonzero virtual bytes, borrowed peaking/flag tails, wrong1141/status/source/TID, missing/failed original free, stale-cycle results, op8-to-State relabelling, truncated/extended result or input, missing RGB copy/retire, codec promotion and a disabled route. No per-byte expansion of the existing layout/peaking/flag tests was added. The focused module passed **68 tests /1345 subtests in9.18s**, preserving all65 prior cases and adding32 subtests. No failed refresh test run preceded that result. The runtime0141 trigger, guest/core build, dual ABI execution, current frozen batch and native capture chain remain unverified here; old refusals, runs and batches were not modified or re-evaluated.

The complete replay continues to exercise raw payloads, transport, same-frame proof, native JPEG completion, ES/PI ownership, sample-table NAL equality and the original-writeback helper/independent decoders. Its `evaluate()` integration isolates only public-artifact prerequisites; the actual graph evaluator remains required and rejects its unfrozen batch. Synthetic replay never becomes native acceptance.

The preserved first unified batch, `unified-camera-2sxwmmdp`, reported **3603 passed, 434 subtests passed, 80 failed and 32 errors**. Seven capture cases stopped in their shared transport setup before exercising later content checks. The exact offending receipt was `FUNCTIONAL_CAMERA_TRANSFER command=0x0`, corresponding to the original MPR Open command zero. The [bridge formatter](../../runtime/analysis/functional-camera-bridge.c) uses C `%#x` / `%#PRIx64`: nonzero values have a `0x` prefix, while zero prints as `0`. Python `#x`/`hex()` spells that same zero `0x0`. The shared `number()` grammar now accepts both zero spellings and retains its u64 bound, decimal rules and rejection of signs, whitespace, non-string values, alternate prefixes and padded/noncanonical hex. The original capture fixtures were not changed to conceal the mismatch.

After that one parser correction, **all original 32 cases and 37 subtests passed in 2.01 s**; the numeric-format regression brought the prior module result to **33 tests / 67 subtests**. The earlier VDF/repeated-INIT checks reported **39 tests / 211 subtests in 2.82 s**. The Zebra extension passed **49 tests / 492 subtests in 4.59 s**. After this diagnostic/layout extension, the focused command passed **58 tests / 1113 subtests in 6.82 s**:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider --import-mode=importlib \
  report/functional-camera-evidence/test_evidence.py -q
```

The command runs from the native-camera package root and uses the installed Pillow, ffprobe and ffmpeg. From the project root, prefix the test path with `final/a7c2-re/report/2026-10-17-qemu-native-camera/`. The first focused attempt used the package-relative path from the project root and ran no tests (exit4). The first actual expanded run then passed58 tests/1110 subtests but failed one additional assertion that a standalone parser should reject a different positive u64 lease solely from its high word. Lease identity belongs to the history/proof joins; the corrected parser test checks zero lease, while the separate stale-lease and actual proof tests enforce identity. The final complete focused run passed. Negatives passed for corrupt/missing chunks, READ/RELEASE ownership, wrong PID/SID/run/instance, duplicate and typed fields, RGB/config/frame/lifetime/counter changes, JPEG leased ranges/raw request/ResCmd/receiver, video request/receiver/free, PI slot/cursor/body, AVCC source/NAL changes, missing final Close/final runner receipt, graph/current-batch identity, changed media and wrong QEMU selection. JPEG metadata changes preserved coding/entropy joins; changing entropy or ordered MP4 NAL payloads failed as required. The graph evaluator's real missing-current-batch verdict was also exercised.

Current host tests validate the strict VDF/Zebra/layout/refresh/disabled-display contract and exact resource-diagnostic classification as specified. Native acceptance still requires a newly frozen, successful unified batch and a completed current-VM run supplying all thirteen graph edges and both actual original-MPR/Fsys products with final closed/detached receipts. The parent's completed3912/1644 lcr and `run-jfz16a4v` results remain prior evidence; this integration does not re-evaluate or promote them, and establishes no new native JPEG/MP4. Earlier runs and frozen batches were not re-evaluated or backfilled after these source changes. No VM, hardware, physical SD, network, private dump, target model execution, full build or full regression was run for this integration.

## Evidence → finding → implementation

| Evidence | Finding | Implementation path |
| --- | --- | --- |
| Actual zero-command transfer spelling and bounded numeric regression | C alternate-form hex and Python replay zero have two precise accepted spellings; malformed and out-of-range numbers still fail. | `number`, `test_unsigned_trace_numbers_accept_only_bounded_log_spellings` |
| Current immutable batch/build/ABI/archive/profile and public selected image | Current code and unchanged original/native QEMU selection can be checked without executing target code. | `check_batch`, `check_profile`, final immutability check |
| Actual broker payload references, retained bytes and committed bridge destination | Full request, READ_RESULT24, RELEASE_RESULT16 and aggregate byte joins are implementable. | `payload_read`, `check_transport`, `transfer_output` |
| Actual 376-byte core proof and raw coded results | Same-frame rendered/encoder-consumed RGB and encoded bytes can be joined per actual job. | `check_frames`, `camera_packets` |
| Source resource logger and three complete public jfz diagnostic OBS rows | Only these exact grammars are separate diagnostics; preserving their rows grants no lifecycle/resource/semantic claim and unknown/failure tags still reject. | `vdf_resource_diagnostic`, `check_vdf_path`, public diagnostic fixture and two diagnostic cases |
| Canonical16/VDF160, Zebra8/Zebra168 and Layout32/Layout192 ABI, original24/14/40 and ACK12 native records | Optional op5/op6/op7 requires exact saved configuration/current route, actual independent RGB copy and immutable original receive/free; kind4 cannot count as encoding. Layout is restricted to exact initial case0 and active640×480. | `LAYOUT_POLICY`, `vdf_result`, `vdf_history`, `check_vdf_path`, `check_transport`, `check_frames`, seven layout cases and preserved VDF/Zebra tests |
| Typed Display16/Display176 ABI, original0141/0152/0162 source-defined bodies and separate1141/1152/1162 ACKs | Op8 admits only header-only refresh or disabled peaking/off on a committed active RGB route; exact independent tail16, native-command mapping, actual RGB consumption and same-sender free are required. Feature/physical claims remain false. | `DISPLAY_POLICY`, `VDF_OPERATIONS`, `vdf_result`, shared history/lifecycle/transport/frame joins, preserved seven display-config tests and three refresh tests |
| Original0141 startup global type2 D, later paired wait/free, and independent0309→1309→1141 source contract | Global D may be reused; intervening actual State/CP work does not authorize reply borrowing across command/cycle/TID. Runtime triggering and original CP work remain unverified. | `check_vdf_path`, native command census and the two-refresh/interleaved-State HOST_TEST |
| Original0141 actual metadata/global equality and exact main-helper bind receipt | Only0141 can use this immutable actual global ID; every cycle requires a fresh complete pre-model observation plus exact native snapshots, with independent RGB/result/receive/free still mandatory. | `vdf_refresh_queue_binding`, `check_vdf_path`, six binding HOST_TEST groups; other five commands retain81cf |
| Original SDK/SDS/ResCmd and actual MPR ES/PI/event receipts | Native original completion/ownership can be joined to exact JPEG scans and MP4 sample NALs. | `check_jpeg`, `check_video`, `jpeg_parts`, `mp4_samples` |
| Current graph `evaluate(run,batch)` and formal original Fsys/decoder evidence | Full acceptance needs thirteen graph edges, both native products, both exports and safe final close. | `check_graph`, reused writeback helper, `evaluate`, `finish_verdict` |

Scope: authorized local public official-package functional simulation only. Only this directory's `check_evidence.py`, `test_evidence.py` and `README.md` are maintained by this implementation. No physical camera/SD, private dump, network, original binary modification, runtime/producer edit or commit is included.
