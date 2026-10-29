# Source-defined S88 CPU fill and pure original 0x011c plan

This HOST adapter implements the completed source3cd handoff: the actual
K2433e0 88-byte CPU writer, fed by an explicit immutable whole work item, and
the original 24-byte 0x011c notification/index plan. It returns actual metadata
bytes and logical values. It does not execute the DMA callback, queue work,
write guest memory or send a notification. The lower 0x620 CPU constructor and
registered BSO_DONE callback have since been [source-bound](../native-video-engine-result/README.md);
the actual 0x500 sender, P/Q result-memory fill, ES-byte producer and completion
origin remain unknown. **`NVIDEO_NATIVE_GAPS`
remains 63 and `native_capture` remains false.**

Scope/authorization: six new files in this directory, public official-package
`system/av-cam.bin` read-only, existing pure helpers linked read-only, and HOST
test executables/libraries in temporary directories. No system VM,
network, hardware, physical SD, private configuration or full-system dump is
used. One check executes these same HOST_TEST C cases in prepared QEMU user mode
with firmware libc2.25. The [earlier source-record report](../native-video-source-record/README.md)
is historical evidence before the CPU writer closure; this completed handoff
supersedes its “writer not found” conclusion only. No existing file is edited.

From `report/2026-10-17-qemu-native-camera/`, run:

```sh
python3 -m pytest report/native-video-record-fill/test_fill.py -q -p no:cacheprovider
```

Result: **19 passed**, including strict C11 `-Wall -Wextra -Werror -pedantic`
and ASan/UBSan. All seven C modes also compile as AArch64 against original
libc2.25 and execute under QEMU user mode, requiring rc0 and complete output.
Their work items and ES bytes remain explicit HOST_TEST inputs.
There is no codec dependency, FFmpeg, frame generation or native send stub.
The pin test additionally requires the prepared public official artifact at
`runtime/analysis/menu-root/system/av-cam.bin`; no binary is distributed here.

## Assemble one explicitly selected AU

The API is in [native-fill.h](native-fill.h). Call `nfill_assemble` with:

- Exactly `0xe90` (3,728) accessible immutable bytes of work item B, captured
  **before callback cumulative-length rewrites for the selected AU**.
- Explicit inclusive `first_segment_index` and `last_segment_index`, both below
  90. The caller establishes that the first index really begins this AU.
- Exactly `0x18` accessible immutable bytes of already resolved primary node A.
  Source K243e84 resolves it using `LE16(B+6)`; the adapter does no lookup and
  does not guess a node-key offset or invent an equality check.
- Exactly 88 explicit baseline bytes from the destination slot's known state.
  Source initialization can establish zero bytes separately; zero is never an
  implicit default of this API.
- Disjoint storage for `struct nfill_record` and its full declared capacity.

All offsets below are hexadecimal; scalar byte order is little endian. The
original `0x620` input occupies `B+000..61f`: original segment descriptors at
`010..5af`, two metadata items at `5b0` and `5e4`, and u32 values at `618/61c`.
The whole queued work item also contains 90 compact descriptors at `620..bbf`
and 90 parallel full u64 ES cursors at `bc0+j*8`. K244848 copies the **whole**
E90 work item; K244994 is its read slot. A 0x620 prefix alone cannot supply the
compact descriptors or ES cursors and is rejected.

Let `L_j=B+620+j*10`. The finite adapter sums the **original** u32 `L_j+8`
lengths across the explicit selected range and uses `LE64(B+bc0+first*8)` for
p. It never substitutes the final segment's cursor. Source K24b04c accumulates
these lengths with W32 arithmetic and writes the cumulative length back to the
last `L+8` before K2433e0. This adapter computes that source value from the
immutable pre-rewrite range; it never changes B. Do not feed an already
rewritten cumulative value back in as an original segment length.

Every selected length must be positive, every selected `L[0d]` must be below
2, intermediate end markers `L[0c]` must be zero, and the last marker must be
nonzero (any nonzero byte is accepted). The source compaction removes zero
lengths. Selector bounds, original W32 sum wrap rejection and u64 `p+length`
exclusive-end validation are strict finite-adapter checks; the original writer
does not supply these general checks. A numerical p is not a host pointer, ES
mapping, valid encoded payload, lease or frame identity. No continuity claim is
made about other segment cursors or unselected descriptors.

For the last segment, set `D=B+5b0+L_last[0d]*34`,
`q=LE16(D+28)`, `f=(q>>6)&0f` and:

```text
g = (q&3) | ((q>>8)&4) | ((q&3c)<<1) | ((B[8]==2)<<7)
```

The final writer overwrites helper g7 with the `B[8]==2` result. Other B8 values,
including 0, 1, 3 and ff, clear it. Unlabelled fields retain opaque integer
meaning; no clock units or readiness semantics are invented.

| S88 destination | Exact value from the actual CPU writer |
|---|---|
| `00` u64, `08` u32 | AU-first full p, cumulative selected length |
| `0c` u16, `0e`, `0f` | 0, full f byte, 1 |
| `10` u64 | `(LE32(D+00)<<32) OR LE32(D+04)` |
| `18` u64 | `(LE32(D+08)<<32) OR LE32(D+0c)` |
| `20` u64 | Sign-extend the signed 32-bit bits from `D+10` to 64 bits |
| `28` u64 | `(LE32(D+14)<<32) OR LE32(D+18)` |
| `30`, `31` | `D[24]`, `D[25]` |
| `32` | `(D[20]&1f) OR ((D[21]&7)<<5)` |
| `33`, `34`, `35` | `D[1c]`, `D[1d]`, final g |
| `36`, `38`, `3a` u16 | `LE16(D+26)`, `LE16(D+22)`, `LE16(D+1e)` |
| `3c`, `40` u32 | `LE32(B+618)`, `LE32(B+61c)` |
| `44`, `46` u16 | `LE16(A+08)`, `LE16(A+0a)` |
| `48`, `4c` u32 | `LE32(A+0c)`, `LE32(A+10)` |
| `50` u32 | `(f&2) ? 0 : LE32(A+14)` |
| `54..57` | **Unwritten**: preserve all four explicit baseline bytes |

`struct nfill_record` contains only `wire[88]` and
`semantic_written_bits[88]`, alignment 1. The first 84 mask bytes are ff and
last four are 00. The mask reports source writes, not knownness, readiness,
validity or capture. Complete snapshots are mandatory even for bytes not read
by the adapter; unknown values cannot be inferred from zero-filled storage.
Inputs may overlap one another but their full declared extents must be disjoint
from the **entire output capacity**, including its unused tail. No allocation,
copy of the entire input, pointer retention or hardware stage is introduced.

## Plan the original notification

`nfill_plan_notify(index,N,cid,unit,primary_id,secondary_id,record_base,out,cap)`
requires an explicit coherent source index/N snapshot and known source scalars:
CID at `T+734`, unit at `T+8e4`, with `T=O+20`; primary ID is `LE32(A+4)` of
the actual resolved primary node. Secondary ID is the actual source secondary
lookup result at node+4, or ffffffff **only when that lookup truly returned no
matching node**. K2440d0's lookup is not executed here. Passing a scalar is a
caller provenance contract, not proof that the lookup occurred.

The returned `struct nfill_notify_plan` contains `record_address`, original
`index`, `next_index`, `destination` and exactly 24 wire bytes. Logical address
is `record_base + (u64)index*58`; the actual source UMADDL does not truncate this
product to W32. The adapter requires N>0, index<N, and that the full logical
N*88 ring extent fits in u64, including its exclusive end. Next index is
`index+1>=N ? 0 : index+1`. No ring is mapped or written. The header is exactly
`03211c0118000000`:

| Message field | Width and exact source value |
|---|---|
| `00..07` | Original header: u16 2103, u16 011c, u16 0018, u16 0000 |
| `08` | u32 unit |
| `0c` | u32 **original index**, before advance |
| `10` | u32 primary ID |
| `14` | u32 actual secondary ID or known-not-found ffffffff |

The actual source sequence is CPU-write S88 → advance source index → queue
**original** index/cumulative length → original 011c send to CID. The pure plan
executes none of these operations, including no queue reservation, store,
barrier, DMA completion, native ACK or send. It does not claim atomic visibility
between a real source array and a callback recipient. Original receive
`M+0c → E+0` remains unclosed, so correct message bytes alone do not execute the
upper callback.

The actual DMA callback error behavior is also not a synthetic success rule:
argument `+4` bit31 reports `dma_err`; the error service may return and the
callback can continue. K227e38 response `r` with `(r&3000)==3000` reports a
parameter error and exits; another nonzero response reports `IMOLA_RESPONSE`
and may continue if the error helper returns. Nonzero original 011c send rc
logs/asserts. This module supplies no callback-success boolean, status generator,
new ACK, IRQ or inferred successful send.

## Error and memory contract

Both functions return 0 or a negative errno and preserve `errno`. Every error
preserves every output byte, including the capacity tail, and every input.
Success writes only `sizeof(*out)` and preserves the tail. The notification plan
requires its natural struct alignment; record output and all byte inputs allow
unaligned addresses. Caller guarantees accessible immutable full extents,
provenance and lifetime; numerical checks cannot discover mappings or leases.

| Error | Rejected adapter input |
|---|---|
| `-EINVAL` | Null pointer, oversized input, full-capacity alias, plan misalignment, N=0 |
| `-ENODATA` | Short E90/node/baseline snapshot or any selected zero segment length |
| `-ENOSPC` | Insufficient output capacity |
| `-ERANGE` | Reversed range, index outside 90/N, selector>=2, intermediate end marker, missing last end marker |
| `-EOVERFLOW` | Host span wrap, W32 cumulative-length wrap, u64 AU/ring exclusive-end wrap |

Errors are all determined before output writes. The full-capacity checks include
work bytes that no source field currently reads and exclude even tail-only
aliases. Shared input spans remain allowed. Input mutation must be serialized
externally; this finite helper is not a queue, ownership or synchronization API.

## Evidence → finding → path

The [source pins](source-pins.json) identify the public raw artifact at
13,797,088 bytes, SHA-256
`90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`.
K is a raw offset; `KVA=K+0xffffffc001000000`. The pin test verifies the entire
artifact and all **12 completed windows / 5,348 bytes**; no new disassembly or
lower-engine investigation is claimed. E1–E3 are the completed read-only
handoff; E4 is the host validation in this directory. Reproduce all four with
the pytest command above (public-artifact preparation is the offline prerequisite).

| Evidence | Source reference / content hash | Finding / location / status / confidence |
|---|---|---|
| E1 | K2433e0, K24b04c, K2426a8, K24a968; per-window SHA-256 in pins | F1: source CPU writer and AU-first/cumulative input contract; `native-fill.c:nfill_assemble`; n/a_re, source-closed and HOST-validated, high |
| E2 | K2442a8, K243e84, K2440d0, K245a38; per-window SHA-256 in pins | F2: original index, IDs, destination and 011c bytes; `native-fill.c:nfill_plan_notify`; n/a_re, source-closed pure plan and HOST-validated, high |
| E3 | K244848, K2471e8, K24cf88, K37b098; per-window SHA-256 in pins | F3: whole work copy and 0x620 entry plumbing; producer origin/completion still unknown; accepted boundary, high |
| E4 | `test-native-fill.c`, `test_fill.py`; reproducible test outputs, n/a runtime log hash | F4: strict/sanitized actual-byte comparison, independent literals, consumer composition; HOST-validated, high; native result unverified |

P1 (`path_type=callflow`) starts with an explicit whole HOST_TEST work snapshot
and resolved node, and ends with actual binary consumption followed by a pure
cursor-return plan:

1. Select first/last AU segments, sum original lengths, and assemble actual S88
   bytes while preserving poisoned baseline holes — E1/E4, F1.
2. Build the original-index 011c plan from explicit source scalars and node ID
   — E2/E4, F2; no message is sent.
3. Pass **those actual S88 bytes** to the existing `nproducer_convert` with an
   explicit zeroed 96-byte caller baseline and explicit full U/G values — E4,
   F4, existing [producer contract](../native-video-producer-contract/README.md).
4. Use its real publication plan for a HOST ring copy, read with
   `nring_copy_read_list`, resolve the explicit whole ES mapping using
   `nau_resolve`, and validate the whole AU with `nlength_validate` — E4, F4.
5. Copy/compare every actual binary AU byte from both borrowed spans, then call
   `nring_advance_read` with the actual borrowed/consumed slot count — E4, F4.

The one composed HOST fixture is BE32(4)+`65 00 80 ff`, with the length word
crossing the ES ring end. These are explicit structural AVC1 test bytes; they
are not a complete decoded H.264 stream or firmware/native encoder output.
A second consumer test uses actual assembled parameter-set metadata and real
`nparamsets_parse` for explicit BE32 SPS/PPS fixtures. Existing helpers are
linked unchanged with function-section garbage collection, without codec
libraries or replacement stubs.

E4 also covers every q value 0..65535 with B8=0/1/2/3/255, both metadata items,
word-pair ordering, all five signed-field boundaries, exact source zeros/ones,
parameter-set fields, poisoned baseline holes, full 90-slot ranges, last slot
89, intermediate/end markers, selectors, zero lengths, exact and overflowing
u32/u64 ends, input immutability, unaligned byte output, all short capacities,
full-input/tail-only alias rejection, plan alignment/errno/error atomicity,
ring wrap and source UMADDL products greater than 32 bits. Python ctypes tests
independently compare complete literal S88/mask and notification bytes.

Timeline: completed source3cd handoff → frozen public header → finite adapter
and pure plan → strict/sanitized HOST batch (18 passed) → six-file handoff.

## Remaining native boundary

The precise unclosed entry is `K24cf88(callback_object+8=O,input620)` →
`K2471e8(O,input620)`, which copies the actual 620-byte input and submits an
internal 0121 message. The callback object is `O+2ac78`, vptr
`ffffffc00137b0a8`, slot `+10` → K24cf88. Who produces those 620 bytes and the
completion event remains unknown. The CPU S88 writer is now identified and
implemented as a finite HOST transformation; engine input/IRQ, actual encoded
ES, original array publication/receive visibility, ES lease completion, native
ownership, MPR globals and end-to-end native capture remain unverified.

Only use the returned bytes/plans after independently establishing their real
input provenance and native lifecycle. This delivery creates no native ready
signal and changes none of the six existing gap bits.
