# Exact producer metadata and pure publication plan

This finite HOST adapter implements the completed source124 handoff: an exact
88-byte internal record to 96-byte `encodedVideoInfo` conversion, plus the
software publication and queue-update plan. It does not produce encoded pixels,
execute a native publication, authenticate an ES lease, or enable native capture.
`NVIDEO_NATIVE_GAPS` remains **63** and `native_capture` remains **false**.

Scope is the six files in this directory, using the public official-package
`system/av-cam.bin` read-only. Tests run on the host and in prepared QEMU user mode with the original libc,
without a system VM, network, hardware, physical SD, private settings, or full-system dump.

From `report/2026-10-17-qemu-native-camera/`, run:

```sh
python3 -m pytest report/native-video-producer-contract/test_producer.py -q -p no:cacheprovider
```

Result: **18 passed**, including strict C11 `-Wall -Wextra -Werror -pedantic`
and ASan/UBSan. The same seven C modes also compile as AArch64 against firmware
libc2.25 and execute under QEMU user mode, requiring rc0 and complete output.
Their metadata and ES bytes remain explicit HOST_TEST inputs. Compilers and
pytest build only temporary test executables.
No encoder library, test stub, media generation, or FFmpeg is needed.

## Convert one resolved record

The two public functions are declared in [native-producer.h](native-producer.h).
`nproducer_convert` requires exactly 88 accessible, immutable source bytes,
exactly 96 explicit baseline bytes, full known `uint8_t U/G`, an auxiliary
presence byte restricted to 0/1, and the explicitly supplied auxiliary `uint32_t`
value. The output is `struct nproducer_record`: `wire[96]` and
`semantic_written_bits[96]`. The whole source snapshot is mandatory even though
the highest read ends at source offset `0x54`.

There is no implicit zero baseline. K160614 actually clears its local 96 bytes
at `sp+0x80` before calling K162ff4; the tests reproduce that separate event with
an explicit caller `memset`. A poison baseline verifies that all unassigned
bytes/bits survive the converter. Source and baseline may overlap each other;
the **full output capacity**, including unused tail bytes, must be disjoint
from both. Success writes only the output struct; every failure preserves all
output bytes, input bytes and `errno`.

All offsets below are hexadecimal; integers use little endian. Let
`f=S[0e]`, `g=S[35]`, `U=C+94dd0` and `G=C+94e98` as complete known bytes.

| Destination V | Exact source behavior |
|---|---|
| `00` | `f&2`: 4; else `g&40`: ff; else `(g>>4)&3` gives 0,1,`g&8 ? 2 : 9`,3 |
| `01` low 3 bits | `g` bit2→bit0, bit1→bit1, bit0→bit2; preserve upper 5 |
| `02` | Copy `S[0c]` only when `f&1`; otherwise preserve baseline |
| `03` | `(baseline[03]&fe) OR U`, with the **full** U byte |
| `04..07` | Preserve baseline; source bit-packed load/store introduces no new value |
| `08` u64, `10` u32 | `S[00]` u64, `S[08]` u32 |
| `14..17` | Preserve baseline |
| `18` u64, `20` u64 | PTS `S[10]`, DTS `S[18]`; preserve integer units and all bits |
| `28` u16, `2a`, `2b` | `S[3a]` u16, `S[34]`, `S[33]` |
| `2c` u16, `2e`, `2f` | `S[38]` u16, `S[32]>>5`, `S[32]&1f` |
| `30` u16, `32`, `33` | `S[36]` u16, `S[31]`, `S[30]` |
| `34` u32 | `G==0 ? LE32(S+50) : 0`; semantic label unknown, no ready predicate |
| `38` u32 | Low u32 of `LE64(S+20)>>3`, after the complete u64 shift |
| `3c..43` | All **eight** bytes preserve baseline |
| `44` u32 low 2 bits | `(LE16(S+44)&1) OR ((LE16(S+46)&1)<<1)`; preserve upper 30 |
| `48`, `4c`, `50`, `54` u32 | `S[48]`, `S[4c]`, `S[3c]`, `S[40]` u32 respectively |
| `58`, `59` | `g>>7`; preserve baseline at `59` |
| `5a` u16 | `aux_present && !(f&2) ? (uint16_t)aux_next : ffff` |
| `5c..5f` | Preserve baseline |

Auxiliary truncation is intentional: `0x12340059` becomes `0x0059`; this is not
an auxiliary bounds claim. Absent auxiliary input and type 4 ignore its value.
Type ff and other converter results are preserved; normal-AU and parameter-set
consumers apply their own supported-type restrictions afterward.

The semantic-written mask describes defined field bits, **not** knownness,
readiness, guest validity, publication, or a generic patch mask. In particular,
V03's semantic mask is `01`, yet full U can set opaque upper bits. Those bits
must not be erased by a mask-based merge. Other untouched bits retain the
explicit baseline. The independent mask literal is:

```text
00: ff07ff0100000000ffffffffffffffff
10: ffffffff00000000ffffffffffffffff
20: ffffffffffffffffffffffffffffffff
30: ffffffffffffffffffffffff00000000
40: 0000000003000000ffffffffffffffff
50: ffffffffffffffffff00ffff00000000
```

V02's mask byte changes from ff to 00 when `!(f&1)`.

## Plan one publication

`nproducer_plan_publish` accepts logical slot/control bases, supplied slot count,
and a coherent externally serialized internal queue snapshot: current at
`Q+0`, N at `Q+8`, occupied at `Q+0xc`, with `Q=C+8b390`.
It computes `j=current+1` and resets to zero **only when j equals N**.
It validates N/count nonzero, current<N, occupied<=N, j<supplied count, the
original W32 `j*96` without truncating wrap, the entire logical supplied ring
extent, and both the `control_base+4` address and its complete u32 storage.
Logical exclusive ends must fit in u64. Supplied count and N need not match.

The plan contains a fixed record size 96, slot/index addresses, j, internal
counters after the source queue update, `source_result`, and
`post_publication_queue_full`. It performs no memory copies, stores, barriers,
callbacks, ACKs, queue mutation, or producer receive API.

The actual source order is:

1. Copy 96 bytes to `slot_base + W32(j*96)`.
2. Execute the actual source `DSB SY`.
3. Store j at `control_base+4`.
4. Attempt the internal queue update.

When occupied<N, current becomes j, occupied increments, and source result is 0.
When occupied==N, **publication has already occurred** before callback operation
`0x0e` with argument `C+94db0`; source result is 1 and the internal counters stay
unchanged. That full-queue case returns C API success with the post-publication
flag, not a preflight failure or rollback. The callback itself is unmodeled.
A host fence or test copy cannot stand in for the actual source barrier.

Both APIs return 0 or negative errno. The header documents null/size/presence,
alignment/alias, capacity, cursor, and overflow errors. Output capacity tails
are never written, on success or failure; callers own accessibility and lifetime.

## Evidence, findings and verification path

[Source pins](source-pins.json) fix the public raw artifact at 13,797,088 bytes,
SHA-256 `90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`.
K denotes raw offset; `KVA=raw+0xffffffc001000000`. All eight completed windows
are verified, totaling **2,248 bytes**, along with the supplied critical raw
instructions and branch targets. K1609c8 is a RET; the logger begins K1609cc.

| Evidence | Finding and implemented path | Status / limit |
|---|---|---|
| E1: K160614, K162ff4, actual clear call K160670→K279e64 | F1: explicit caller baseline→exact conversion, including full U merge and conditional writes | Source-closed metadata only |
| E2: K161374, K168ccc; copy K1613c4, DSB K1613d0, store K1613d8, queue call K1613e0 | F2: copy→DSB→publish index→queue update; full case is post-publication | Pure returned plan; no source execution |
| E3: K15ebbc, K15ed88 | F3: descriptor+58 base, +60 u16 count, +80 control are distinct from internal Q.N; internal 88-byte base/capacity bind | No inferred supplied-count equality or index validity |
| E4: strict/sanitized C selfchecks and independent ctypes wire/mask fixtures | F4: HOST output and errors match the finite contract, and existing consumers process actual converted bytes | No native producer, frame or lease evidence |

E4 covers all 65,536 f/g combinations, every U/G byte, poisoned and explicitly
cleared baselines, optional auxiliary truncation, all eight hole bytes,
unaligned byte output, full-capacity aliasing, immutable inputs, atomic errors,
queue wrap/full behavior, count≠N, W32 multiplication limits and u64 overflow.
It links the actual pure metadata, AU, parameter-set, ring, and length helpers
with function-section garbage collection, without replacing them with stubs.

One composed HOST selfcheck converts an immutable 88-byte record with an
explicit zero baseline, copies its actual 96 bytes to a HOST ring using the
publication plan, reads the last-processed cursor's next slot with
`nring_copy_read_list`, resolves a real supplied ES mapping with `nau_resolve`,
and validates one explicitly AVC1 BE32+NAL fixture via `nlength_validate`.
Its length word crosses the ES ring end. The test consumer copies and compares
all binary AU bytes, verifies preserved metadata, and only then calls
`nring_advance_read` to plan the software cursor return. That is P1, the HOST
producer-metadata→ring→AU/length→cursor callflow, with E1–E4 backing the stated
steps. It neither claims an original encoded producer nor a native ES lease.

The original internal base is `C+8b450=C+210c0`, capacity
`0x63420=0x120c(4620)*0x58`; the original source index is unchecked. This adapter
accepts an already resolved whole snapshot and never indexes that array.
Producer array fill, source generation/configuration provenance, 88-byte source
MMIO/IRQ completion, pixel/encoder production, lease completion and MPR global
pointer identity remain unverified. Existing consumer successes do not close
those gaps. Use the helpers for bounded software contract validation only.
