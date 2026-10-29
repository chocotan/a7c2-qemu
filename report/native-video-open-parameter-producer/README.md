# Original EncOpen parameter producer: byte 0x88 is explicitly zero

The original movie-recording producer is now pinned: `mpr::SetEncOpenParam` at ELF VA `0xd2b28` writes **`strb wzr,[A,#0x88]` at `0xd2d60`**. The single-parameter call site in `mpr::ExecEncOpen` first clears all **0x98 = 152 bytes**, calls that setter, then passes the same stack object to the original `Codec::EncOpen`. This closes the producer-side boolean value for that source path. It is a per-open setter store, not a guessed constructor default.

The same investigation identifies the queued parameter owner and the DMM metadata feeding its pointers. It does **not** identify a live SDS/YC pixel plane or a per-frame completion/release lease. Source evidence remains separate from native execution: `capture_verified=false`, gap mask **63**. No native JPEG/MP4 output is claimed.

## Scope and source coordinates

Authorized scope: offline, read-only analysis of the public ALLLANG `runtime/analysis/menu-root/usr/lib/libmpr.so`. Outputs are confined to this report directory and `../../scratch/native-video-open-parameter-producer/`. No VM, firmware execution, network, private/full dump, device, physical SD, integration change, full test run, or commit was performed. This README is the scope record; report flavor is ordinary reverse engineering (`null`).

`M` is the original 3,528,576-byte AArch64 ELF shared library, SHA-256 `4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9`. Addresses below are **ELF VAs**. File offsets are computed using `PT_LOAD`, not raw-address assumptions:

| p_offset | p_vaddr | p_filesz | p_memsz | flags |
|---|---|---|---|---|
| 0x0 | 0x0 | 0x2e4534 | 0x2e4534 | 5 |
| 0x2e53a8 | 0x2f53a8 | 0x77c88 | 0x163e18 | 6 |

All 12 selected windows happen to lie in the first load, where VA equals file offset. BSS owner symbols are addresses, not file contents. [source-pins.json](source-pins.json) contains exact offsets, lengths, hashes, original instruction bytes, and ELF relocation bindings; the windows total **7,086 bytes**. Acquisition used `pyelftools` plus Capstone, with exact bytes as authority. No decompiler output was needed.

The four supplied reports remain the authority for the already closed downstream edges: [packet coordinates](../native-video-packet-coordinates/README.md), [type0 binding](../native-video-type0-binding/README.md), [pointer conversion](../native-video-pointer-conversion/README.md), and [shared binding](../native-video-shared-binding/README.md). Their original `av-cam.bin` identity is `90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`, KVA = `0xffffffc001000000 + raw`. This investigation does not reopen those windows or treat libmpr VAs as kernel raw offsets.

## The actual caller and value of byte 0x88

Let `X` be the queued `execEncOpen_t` and `A` the local API parameter.

| ELF VA | Original operation | Finding |
|---|---|---|
| 0xd30e4 / 0xd30ec | `x19=X`, `x20=FP+0x90` | A is an owned worker-stack object |
| 0xd337c–0xd3380 | test `u8[X+0x760]`; nonzero goes to 0xd3480 | zero chooses the single-parameter path |
| 0xd3384–0xd3390 | `memset(A,0,0x98)` | all bytes have a source-defined initial value |
| 0xd3394–0xd339c | `SetEncOpenParam(X,A)` | exact producer of this A |
| 0xd2b34 / 0xd2b44 | setter preserves `X` in x20 and `A` in x19 | offset bases are explicit |
| **0xd2d60** | **`7f220239`: `strb wzr,[x19,#0x88]`** | **A[0x88]=0 unconditionally** |
| 0xd33a0–0xd33b8 | x0=A, w1=0x20, w2=`u32[X+0x780]`, w3=1, w4=0, x5=FP+0x60 | one 0x98 parameter, view 0, exact original call |

The call at `0xd33b8` targets PLT VA `0x7be20`. That stub loads its target from `0x2fe6b0`; the `R_AARCH64_JUMP_SLOT` relocation names `_ZN3mpr5Codec7EncOpenEP16AvbbcApi_EncOpenNS0_9CodecTypeENS0_10FileFormatEjNS0_6ViewIdEP12PayloadCodec`, symbol VA **0x280bc8**. This is the requested original function, rather than a similarly named API.

The single-path guard is a **source condition**, not an observed camera setting. `w1=0x20` is the source `CodecType` argument; it must not be relabeled as the kernel constructor's `type0`. The producer zero store is independent of `u32[X+0x764]`, which only affects other fields. The dual path also calls this setter for its first block, but the second setter was not expanded here.

Conditional consequence when this same parameter reaches the already pinned type0 route: byte 0x88 selects Z's **zero branch `0x13dd50`**, and common H selects **H+0x18 / handler `0x177840`**, whose selected 0201/210/subtype0 copy action is `0x1779a0`. This removes the boolean uncertainty for that producer, without proving that a live type0 request came from it. Original dispatcher bypasses, state/subtype guards, address conversion, and conditional byte 0x67 clearing remain in force.

The public `MprIf::EncOpen` at `0x2c9d00` contains only `mov w0,#0; ret`. It is a negative route: its success-shaped return does not construct A, call the codec, or prove capture.

## All 0x98 bytes have a producer expression

The following is the single-path pre-`Codec::EncOpen` object. Offsets are hexadecimal. `T=X+0` is the copied `BufferTable`; `V=sign_extend(u32[X+0x768])` indexes `g_videoParamComb` rows of 0x18 bytes; `U=sign_extend(u32[X+0x774])` indexes `g_audioParamComb` rows of 0x0c bytes. These are runtime inputs, not recovered numeric frame addresses. The original codec subsequently converts pointer fields as established in the shared-binding report.

| A field | Width | Original source expression |
|---|---|---|
| +00 / +08 | u64 / u32 | T+00 / T+10 |
| +10 / +18 | u64 / u32 | T+20 / T+30 |
| +20 / +28 | u64 / u16 | T+2c0 / **0x4b0** |
| +30 / +38 | u64 / u16 | T+40 / **0x4b0** |
| +40 / +48 | u64 / u16 | T+60 / **0x300** |
| +50 / +58 | u64 / u64 | T+140 / T+160, independently supplied bases |
| +64 / +85 | u8 / u8 | 1 if `u32[X+764]` is 1 or 2; otherwise 0 |
| +65 | u8 | `GetCodecAudioFormat(u32[X+774], g_videoParamComb[V].word0)` |
| +66 | u8 | `ConvertVideoCodecToCodec(row.word0,row.word14)` |
| +68 / +6a | u16 / u16 | video row halfword4 / halfword6 |
| +7b | u8 | `GetAudioBitrate(u32[X+774])` |
| +7c | u8 | `GetAudioOutputChannel(u8[X+778])` |
| +7d | u8 | low byte of audio row word4 |
| +7f | u8 | 0 in this single path; setter produces 2 when X[760] is nonzero |
| +80 / +81 | u8 / u8 | low byte of `pconv::ConvertFrameRateForCodec` output32 and its first output byte, input `u32[X+770]` |
| +82 | u8 | `ConvertPictureQualityDefStructToMpr(u32[X+76c])` |
| +83 | u8 | `ConvertVideoAspectForAspectRatio(GetVideoAspect(u32[X+768]))` |
| +86 | u16 | `u16[X+77c]` if `u32[X+764]==1`; otherwise 0 |
| **+88** | **u8** | **explicit zero store at 0xd2d60** |
| +89 | u8 | 1 if `u32[X+764]==2`; otherwise 0 |
| +94 / +95 | u8 / u8 | `GetChromaFormat(u32[X+768])` / `GetVideoBitLen(u32[X+768])` |

The remaining bytes are source-defined zero from the caller's full memset: `[0c,10)`, `[1c,20)`, `[2a,30)`, `[3a,40)`, `[4a,50)`, `[60,64)`, byte67, `[6c,7b)`, byte7e, byte84, `[8a,94)`, `[96,98)`. Several of these are redundantly zeroed by the setter. This is not permission to fill unknown runtime source fields with zero. The setter's `T+2d0 > 0x19c7ff` assertion is an input guard on the path to the constant +38 store; failing it goes to `__assert_fail`.

## Source owner, backing identity, and lease boundary

`EnterRec` (`0xd9474`, E11) obtains `mpr::s_movieRecInfo` through its original GOT relocation. The symbol is BSS VA **0x377ff0**, size **0xba0**. In the allocation branch, `0xd9748` forms **T=R+0x290**, stores `GetDmmModeId(R)` at R+0x28c, and `0xd975c` calls `AllocDmmMemory(mode,&handle,T)`. Its true return goes through `GetStillBufConfig(T)` to `EnqueueExecEncOpen(R)` at `0xd96c0`. `GetStillBufConfig` was not expanded, so the DMM writer mapping below is not an assertion that no other setup helper can touch the table.

`EnqueueExecEncOpen` (E3) copies **0x760 bytes** from R+0x290 to its stack X, and fills the recording settings immediately after that prefix. Its `0xd7ee0–0xd7ef4` GOT load stores **`mpr::ExecEncOpen`** at X+0x8e98. At `0xd7fc4`, the actual `execqueue<mpr::execRecMovie>::exec` receives X. E6 copies **0x8ea0 bytes** into queue storage under its mutex. E7 reads callback X+0x8e98 and invokes it at `0xdd8b4` with x0=X; only after callback return does it advance/pop the queue and potentially delete the exhausted node.

This closes a **metadata snapshot lifetime**: the queued X persists while its callback executes, and its local A persists through the synchronous original `EncOpen` call. The queue copies pointer values and table metadata; it does not deep-copy pixel buffers or establish a DMA/frame lease.

`DmmMemInfo::AllocDmmMemory` and `GetDmmExtList` (E4/E9) establish a second owner:

- A selected unit-conversion table is passed to helper **0x2b2224**. That helper was not expanded in this bounded investigation.
- Acquisition constructs a linked list rooted at `mp_AreaExtListStart` (BSS VA **0x3d82f8**): node+0 unit type, +4 common returned group identifier, +8 per-unit returned identifier, +0c source area identifier, +10 next, +18 extent count, +20 returned mapping value, +28 accumulated extent sizes, +30 first extent address.
- `SetMemTbl` matches node+4 against the supplied group, derives `V=node+20`, `P=node+30`, `S=node+28`, and writes address-pair entries `{V,P,S,V-P}`. P/V domain names carry the prior GetUnitInfo/translation contract; no numeric mapping is supplied here.
- Switch table E8 proves **unit type3 → T+0**, **unit type4 → T+20**, and **unit type6 → the suballocation writer at 0x2b2e00**. Thus A+00/+08 and A+10/+18 have exact original metadata sources. It does not establish that either is an SDS/YC input plane.

For unit6's branch where mode is neither 6 nor 0x11, the writer declares T+40 `{V,P,0x6d000,...}`, T+60 bases V/P+0x6d000 with size 0xe000, T+140 bases V/P+0x7b000 with size0x400, T+160 bases V/P+0x7c000 with size0x400, and T+2c0 bases V/P+0x280000 with declared size0x339000, subject to its original size guards. These are source suballocation formulas, not measured allocations. Mode6/0x11 takes different formulas; in particular the displayed alternate branch does not supply T+140/T+160, so those bases cannot be invented from the default branch.

A+30/+38 are the prior **VideoInfo** slots/count; A+50 and A+58 remain independently sourced read/write control bases. The needed VideoInfo count is **0x4b0**, not zero or an arbitrary generic count, on this producer path. Metadata's accumulated size and first extent address do not prove that all physical extents are contiguous, nor that any whole 0x98/slot/frame extent is currently leased.

E2/E10 show original reconfiguration release: when X+0x7b8 selects an existing open, `ExecEncOpen` calls `EncClose`/`EncClose2`, checks its transport result, calls `DeleteUseStreamBufferArea`, calls `FreeDmmMemory(mode)`, and allocates/copies replacement table metadata before opening again. `FreeDmmMemory(mode)` delegates with mask7 to the selected conversion table; `FreeDmmExtList` reaches helper **0x2b24f0**, and successful release clears the stored per-unit identifier. The two helper bodies, any hardware wait behind close, and the final frame-completion callback are outside these windows. **Allocation/reconfiguration release is not per-frame completion.**

## Evidence → finding → path

All findings have severity `n/a_re`; confidence refers to the static source claim only.

| Evidence | Source ref | Finding / status / confidence |
|---|---|---|
| E1, E2, E12 | exact writer, call site, actual PLT/GOT | F1: this single-open producer explicitly emits byte88=0 / closed / high |
| E3, E6, E7, ELF binding to callback | original enqueue, memcpy, worker BLR and post-return pop | F2: queue owns parameter metadata through callback return / closed / high |
| E4, E8, E9, E11 | original allocation owner, unit table, linked-list writers | F3: table owner and type3/type4/type6 address sources / closed as metadata; frame identity open / high |
| E2, E10 | original close/reconfigure and DMM release wrappers | F4: group release source exists; per-frame completion lease unclosed / bounded / high |
| E5 | MprIf::EncOpen exact two instructions | F5: public wrapper is a no-op return, unsuitable as proof of native open / closed / high |

P1 (`path_type=callflow`): E11 EnterRec allocates original T → E3 snapshots it and its settings → E6 owns queue copy → E7 invokes original ExecEncOpen → E2 clears A and calls E1 setter → E12 resolves to original M280bc8 → carried prior reports transport/convert/copy the same parameter under their guards. F1 provides the zero branch only when this source path supplies that message.

Timeline delta: inherited the four existing downstream contracts; located original setter/caller; pinned explicit zero and full memset; closed queue metadata lifetime; traced unit-list/table owner and reconfiguration release; stopped at unexpanded allocation/release helpers and absent live frame identity. No state was promoted to native completion.

## Reproduce and use the result

From the native-camera result root:

```bash
python3 report/native-video-open-parameter-producer/verify.py
aarch64-linux-gnu-objdump -d --start-address=0xd2b28 --stop-address=0xd2e00 runtime/analysis/menu-root/usr/lib/libmpr.so
aarch64-linux-gnu-objdump -d --start-address=0xd30d4 --stop-address=0xd3514 runtime/analysis/menu-root/usr/lib/libmpr.so
```

`verify.py` is only a **source-pin self-check**: artifact identity, file-backed ELF mapping, 12 hashes, exact instruction assertions, ELF bindings, original PLT target, unit switch rows, and conservative status fields. It performs no VM or integration tests. The executed self-check passed (`12 windows / 7086 bytes`, byte88=0, capture=false, gaps=63); a separate field-accounting assert covered all 152 bytes exactly once. Scratch disassembly is inspection evidence and is reproducible with the corresponding E-window start/length. Source hashes and offsets reproduce the findings independently of scratch names.

For integration, record `A[0x88]=0` with the specific producer/caller provenance above; retain the original single-path guard and all downstream guards. Still required before any capture claim: a live request proving this producer/type0 selection; a coherent full 0x98 fixed-area lease; numeric DMM mapping/extent and contiguity validation; identified frame/SDS/YC owner and actual pixel writes; consume/complete/release ordering; native ES and final JPEG/MP4 written by the firmware. No arbitrary zero/default buffers, empty ACK, ready flag, host media generation, or physical-start-only check closes those gaps.
