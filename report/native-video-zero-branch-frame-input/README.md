# Zero-selected EncStart: first frame handoff remains open

**Source frame handoff closed: NO.** The normal START call is traced past its state machines into original codec work at raw `0x134640 → 0x1363a4`. No source-proved YC/SDS input owner, pixel byte reader/writer, hardware job carrying a proved frame pointer, or actual frame callback was recovered in this bounded investigation. Keep **`capture_verified=false`, native gap mask `63`**. The result adds no executable native field closure.

The last newly checked START call is **`0x134688 → 0x1363a4`**, after timing-normal reaches `0x145550`. Cross-checking the earlier [S88 START contract](../native-video-source-record/README.md) identifies `14fcd4`'s result as the **88-byte encoded-output record array**, carried by this same lower start operation. That pointer is not a YC input plane. Other helper outputs remain unclosed; this call is not evidence that the first frame interface has been found.

## Scope and reproducibility

Offline read-only public ALLLANG source only. Writes are confined to this new report directory and `../../scratch/native-video-zero-branch-frame-input/`. Existing reports/runtime files remain frozen. No VM, original execution, private/full dump, network, device/SD access, firmware change, regression rerun, build, ABI run, or commit was performed. Parent's completed **3253 / 381 + 398 source build + dual original-libc ABI** is inherited, not represented as a test performed here. Ordinary reverse-engineering report, `flavor=null`.

Artifact: `runtime/analysis/menu-root/system/av-cam.bin`, **13,797,088 bytes**, SHA-256 **`90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`**. `K` means raw offset; KVA is `0xffffffc001000000 + K`. The raw image has no ELF import table; direct calls and original vtables are the source binding anchors. No new libmpr coordinate or ABI assumption was introduced.

[source-pins.json](source-pins.json) pins **12 exact windows / 6,792 bytes**, each with full SHA-256 and branch conditions. Matching `E1`–`E12` disassemblies are in the new scratch directory. Extra exploratory scratch spans are not additional closed interfaces. All instruction and state-table assertions were checked against the original image. Capstone was used only to render original bytes; there are no AArch64 delay slots.

Previously closed inputs are inherited without reinterpreting them: [parameter producer](../native-video-open-parameter-producer/README.md) proves source `A[88]=0` for its guarded single-open path; [type0 binding](../native-video-type0-binding/README.md) proves ISP wrapper → common `H+18`, handler `177840`. Its existing `367cd0` table already contains subtype1 → **`178064`**. No runtime invocation of that producer/route is established.

## Actual START path and conditions

Let `R=H+18`, `T` be the original timing-normal object registered at `R+20`, and `Q=u64[T+478]` its state-machine handle. These names denote objects, not frame owners. State indices in the tables below are decimal; explicit `h` suffixes mark hexadecimal values.

| Evidence | Exact source operation | Consequence |
|---|---|---|
| E1 `178064..178144` | Copies packet+8 header `28h` to `R+160`; when copied header pointer `R+168` is nonzero, loads **packet+10**, copies **80h** to `R+188`, rewrites header pointer/length to that snapshot; `17813c → 17f83c` | Original START parameter ownership, no pixel consumption |
| E2/E4 `17f83c`, table `369408` | State `15h/16h` returns error; active/reentrant dispatch has a bounded deferred-event path; idle uses `{guard,action,next}` rows, stride `18h` | Incoming state and transition success remain conditions, not defaults |
| E3/E4 | **State3 or18** action `1858b0/185a84`: `17e020` then `17b8b0`; **state6 or11** action `185934/1859bc`: `17b908` | Two distinct phases; normal START does not unconditionally jump to the second phase |
| E5/E6 | `T` vptr `36d500`: virtual `+20=193e6c → 198570(Q,…)`; virtual `+28=193e74 → 1987b8(Q,…)` | Exact original timing targets |
| E7–E9 | First timing table `36e120`, **state6** row action `19dc90 → 194e04`, next7. Second table `36e360`, **state7** queues via `19def8 → 196788`; **state8/16** action `19df20/19dff0 → 194ee4`, next9 | Pending START is deferred until original conditions permit it |
| E10 | `194e04`: calls `194e34` and then `145614(T+20, original_argument)`. `194ee4`: copies argument+28's **80h** to `T+140`, resets local state, calls `194f70`, then **`145550(T+20, original_argument)`** | Still control/state operations; neither copy is a proved input plane |
| E11/E12 | `145550` obtains codec configuration via `146680/146dcc`, reads conditional configuration bytes, calls `134640`, then `14153c`; `134640` calls `14f8a8`, **`1363a4`**, and tail-calls `12cf8c` | Reaches actual original codec start work, without proving frame acquisition |

The inherited owner registration and exploratory whole bodies of `17b8b0/17b908` preserve the phase distinction: `17b8b0` calls `T.virtual20` with a stack u32 copied from its argument+`a8`; `17b908` normally calls `T.virtual28` with the original argument, but receiver byte `ca==0f` takes its separate `18364c` path. The START state path remains conditional on that byte and all state guards. These are not SDS type/handle/offset values.

## Pointer dataflow at the last checked START call

At E11 `145550`, let `D` be its incoming `this`, `S` its original START argument and `C=146dcc(D+18)`:

- `146680(D+18, &flag, &aux)` produces further configuration outputs.
- When `u8[C+118]` is nonzero, bytes `C+334/+174/+34c/+177/+34d/+178` populate the local small configuration; otherwise only the corresponding locally cleared values survive. This is byte access to **configuration**, not YC pixels.
- Call `1455f0` passes `134640(u64[D+10], S, C, &local_config, flag, &aux)`.
- E12 preserves the six arguments, invokes `14f8a8(u64[this+8])`, then at **`134688`** calls **`1363a4(this+10,S,C,&local_config,flag&1,&aux)`**, followed by `12cf8c(this+110,S)`.

Exploratory inspection of whole `1363a4` found calls to **`14fcd4` / `14fccc`**, storing their returned pointer/count pairs into local descriptor fields, setup calls **`1395a0` / `139790`**, and submission helper **`136e1c`**. The earlier S88 contract positively binds `14fcd4 → 15f414` to the encoded-output array and its record capacity, then `136e1c` copies that start descriptor into the original message. This is a rejoin to known output metadata, not a new candidate YC plane. Other setup outputs and the actual frame acquisition/callback remain unknown; do not infer NV12, 422, a sensor buffer or a frame lease.

**Actual next frame callback: unknown.** Exploratory timing event handler **`1946c4`** calls `18d578(T+470,event+8,out)`, dispatches event word+8 values 0/1 through `1947c0/194930`, and checks event+18 against `-1`. Its data is event/configuration metadata. This investigation did not establish its registration as a frame callback, a fresh frame identity, or its relation to a pixel producer. Therefore it is explicitly a candidate event path, not a recovered frame handoff.

## Evidence → finding → path and integration boundary

F1 (E1–E6, high static confidence): normal START snapshot and original timing dispatch are pinned. F2 (E7–E12, high static confidence): original state guards lead into the lower codec START entry and retain pending-request conditions. F3 (bounded negative): input-plane owner, pixel consumption, hardware submission using a proved frame pointer and frame callback remain unresolved; this is not a claim they do not exist.

P1, `path_type=callflow`: inherited zero-selected receiver → E1 START → E2/E3/E4 normal state → E5/E6 timing virtual → E7/E8/E9 timing state → E10 actual Start action → E11 codec Start → E12 lower Start → **known S88 output-record configuration**. The actual frame acquisition and callback remain unidentified.

This closes no native frame field. Parameter snapshot and deferred-request lifetime remain separate from frame identity/coherence, DMA lease and completion/release. `A+94/+95` format/depth were not expanded in this bounded pass; no packing claim follows from their labels. Actual AP frame consumption and native JPEG/MP4 through original MPR/Fsys are still required; all six gap bits remain set.
