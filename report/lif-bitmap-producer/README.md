# Source-derived configured LIF bitmap owner

The new `cp-lif-bitmap` implementation consumes the completed `completed09source` builder inputs, constructs the 17-byte command `0a` and its 25-byte logical wire image, and commits a separately owned configured bitmap and type1 gate. A transport receipt requires the exact copied lease identity and comparison of all 25 actual consumed bytes. Only an explicit immutable receive frame creates an `a923d0` snapshot and reaches the existing `cp_lif_frame_decode`. All outputs describe **owned virtual data**. No native queue admission, DMA delivery, CP state, reply, publication, ready or ACK is established.

Scope and authorization are the delegated owner-authorized offline implementation request and the project [AGENTS.md](../../../../../../AGENTS.md). The only new files are [header](../../runtime/analysis/device-models/cp-lif-bitmap.h), [implementation](../../runtime/analysis/device-models/cp-lif-bitmap.c), [host matrix](../../runtime/analysis/device-models/test-cp-lif-bitmap.c), [pytest entry](../../runtime/analysis/test_cp_lif_bitmap.py), this report and [source pins](source-pins.json). Existing runtime integration, the parent common-694 work, other workers' property/parameter changes, VM execution, network, private/full-system assets, hardware and physical SD are outside this worker's scope. The explicit six-file scope takes precedence over creating separate case files; this paragraph is the scope record. Report flavor is `null`; exploitation, IOC and ATT&CK are n/a.

Run from `2026-10-17-qemu-native-camera`:

```bash
python3 -m pytest runtime/analysis/test_cp_lif_bitmap.py runtime/analysis/test_cp_lif_frame.py -q
```

**Result: 4 passed**, including C11 `-Wall -Wextra -Werror -pedantic`, ASan, UBSan, all ten supplied source windows and the existing decoder's regression matrix. The public ALLLANG image was present and its whole-image SHA-256 matched. Source verification skips if that public asset is absent; host matrices remain independent of firmware, devices and a VM.

## Integrate with one externally serialized owner

The API stays fixed-size, caller-owned and allocation-free. It retains no source, transmit or receive pointers. The caller must hold its source/transport lock throughout every call, keep the supplied spans accessible and immutable, and honestly bind the guard to the actual virtual source event. Guard declarations do not create proof of source execution or an internal mutex.

1. Zero-initialize a `cp_lif_bitmap_owner` and call `cp_lif_bitmap_owner_init` with the actual PID, a `HOST_TEST` or `VIRTUAL_SOURCE` origin, equal even before/after sequences and `quiescent=1`. This records ownership only: bitmap and gate remain unknown.
2. For an actual source build event, call `cp_lif_bitmap_request(owner, 1, inputs, guard, lease, capacity)` with a strictly newer sequence. The typed inputs contain K, mode, one coherent Z for both original reads, the actual S43/S5a support-helper results, and at least `0x162` inline property bytes with per-byte known markers. The helper `cp_lif_bitmap_build` is also available statelessly; it has no configuration or transport effect.
3. Request selector 1 commits all 16 bitmap bytes and the gate, increments `configured_generation`, and records `data_producer_sequence` before issuing any lease. If there is no pending lease, the output receives a new nonzero token and a copied immutable logical wire image. A zero lease means configuration committed while an earlier lease remained pending; it does **not** mean a send or queue admission succeeded. The prior pending bytes and token remain unchanged.
4. Keep that lease scoped to this owner and pass the actual bytes read by the virtual consumer to `cp_lif_bitmap_observe_transport_consumed`. All 25 bytes must match both the owner's pending copy and the lease. Token, owner PID, origin, producer sequence, generation and size metadata must also match. A successful call retires that single lease and records its consumed generation and producer sequence. A return code or matching checksum alone never qualifies as a receipt.
5. At an explicit receive boundary, pass the actual immutable `rx` buffer to `cp_lif_bitmap_receive_decode`. It snapshots the current configured bitmap and full gate under the guard, creates `CP_LIF_BITMAP_A923D0_SNAPSHOT`, and calls the existing decoder. Its result includes the exact context plus decoded bytes and field offsets copied into caller-owned output. Freeing the input afterwards is safe. Building or consuming outgoing bytes never creates a snapshot event.

All successful owner mutations require a sequence strictly greater than the owner's current sequence. Failed calls are atomic: owner and complete output, including capacity tails, remain unchanged. The entire declared output capacity must not overlap any input or owner. Guard/input typed alignment, address wrap, PID, origin, stale/torn sequences and required known markers are checked. No initialized owner may be copied/reset and reused to recycle its tokens; tokens are scoped to that owner instance, not globally unique capabilities. Forked copies refuse both inherited and child-PID guards.

Selector 2 is `-ENOTSUP` with no state change. The original `a946fe` selector-2 branch copies `1719ee8` into command bytes 1..16 without committing `1b1aa12..21` or changing `1b1aa10`; this owner does not guess that source history or treat it as a configured switch. Every selector other than 1 and 2 models the named `a92296` clear event: under the caller's resource-31-equivalent lock, it commits known all-zero bitmap/gate, increments the configured generation, and produces no lease. Such a clear may coexist with an older pending lease; consuming that old lease cannot authorize the newer cleared bitmap.

`cp_lif_bitmap_gate_clear` models the named `a92590` gate-only clear once configuration is established. It clears `1b1aa10` independently of the bitmap and does not increment the bitmap generation. A later receive of type1 fails `-EACCES`, while type2/3 can decode with the same bitmap and explicit zero gate. A gate clear before any configured bitmap remains `-ENODATA` in this bounded owner.

## Exact source builder

K is `u32[1a03ac0 + 0x10]` through `a909b0`. P is the runtime object pointer at `1a03cdc`; input bytes preserve its offsets and little-endian words. Z is `u8[1b1ad1d]` through `a9902a`: the source reads it twice, so this model requires a single coherent value under the before/after guard. S43/S5a are actual support-helper results using `1719e40`, with nonzero values treated as true. Mode is `u32[1107178]`. None of these runtime addresses is sliced as a firmware file offset or inferred from a property seed.

The gate starts at 1 for each actual builder invocation:

| K | Initial bitmap / subsequent work | Resulting gate |
|---|---|---|
| 1 or 2 | `B[0]=0x40`, all other bytes zero; no further input reads. | 1 |
| 4 or 5 | `B[0]=0xdf`, `B[1]=0x79`, `B[8]=0x2f`; then the rules below. | 1 |
| Any other u32 | All bitmap bytes zero; no further input reads. This is an explicit builder event. | 0 |

For K4/5, the implemented rules are:

| Condition | Bitmap effect |
|---|---|
| `P[0x161] & 0x20` | `B2=0x80; B3 |= 0x06` |
| Otherwise | `B0 |= 0x20` |
| `F = mode==1 && (K & ~1)==4 && (P[0x52]&0x60)==0x60` | `B2 |= 0x03`; if P161 bit20 is set, `B3 |= 0x08`, else `B1 |= 0x80` |
| S43 is zero | `B1 |= 0x06` |
| First Z is zero, A=`LE32(P+0x15a)` | A bits `0x1000/0x8000/0x200000` select `B2 |= 0x04/0x08/0x10` |
| First Z is zero, D=`LE32(P+0x15e)` has bit `0x40000000` | `B3 |= 0x01` |
| A has bit `0x80000000` | `B2 |= 0x40` |
| K5 or S43 is zero | `B8 |= 0x10` |
| K4 and `P[0x51] & 0x20` | `B8 |= 0x80` |
| Second Z is zero, K5 and S5a nonzero | `B9 |= 0x01` |
| Second Z is zero, A bits `0x10000000/0x20000000` | `B9 |= 0x02/0x04` |

Only consumed fields need known markers. K1/2 and other K values require only K. K4/5 always require mode, Z, S43, P161 and the full A word because A's high bit is tested independently of Z. P52 is required only for mode1, P51 only for K4, D only for Z0, and S5a only for Z0/K5. A consumed property marker must be exactly 1; zero is unknown and greater than 1 is malformed. Unconsumed property bytes and their markers are ignored rather than read or defaulted. Unknown bits in the scalar known mask are rejected.

The existing decoder's field ID `0x40` uses byte 8 **bit 0**. Byte 8 mask `0x40` would select field `0x46`, which this builder never selects. Tests exercise this distinction through a real type2 command-6 decode: K4's baseline byte `0x2f` selects IDs `40,41,42,43,45`, consuming `2+11+9+4+7=33` field bytes.

## Logical wire and transport boundary

The source table row at `1205578` is exactly `0a 00 11 00 11 00`: command `0x0a`, metadata `0x11`, length `0x11`. Command data is the 17-byte `0a || B[16]`. The owner produces only:

```text
f0 19 00 02 00 0a B[0] ... B[15] checksum_lo checksum_hi 55
```

The checksum is `(0x25 + sum(B)) & 0xffff`, consistent with the existing validator's sum over length, flags, opaque byte and command. Type is 2, source sequence byte is zero, logical length is 25, original rounded DMA span is 32 and only the 25 logical bytes are known. There is no 32-byte array and no invented zero padding. The seven padding bytes remain unknown.

A one-pending-lease restriction avoids a guessed original queue implementation. A source builder or clear can still overwrite configured state while that pending lease is immutable. In that case the latest receipt can be real for the old lease and still fail attribution to current configuration. The owner deliberately requires both `configured_generation == consumed_generation` and matching data-producer sequences before decoding; otherwise it returns `-EAGAIN` without a snapshot output. Missing configuration/receipt returns `-ENODATA`.

This is a **conservative owner policy**, not a claim about the raw source validator: `a923d0` snapshots the current configured bitmap even if a newer build has committed before enqueue/delivery. A successful owner receive exposes `configured_matches_consumed=1`; mismatched configurations are observable in owner generations but cannot produce a successful receive result. Equality proves the bounded virtual owner association only. Source support for command `0a`, original queue admission/callback scheduling and native DMA execution remain separate unclosed constraints. Original DMA error clobbering is a further reason that producing or comparing this logical wire does not establish native delivery.

## Errors and verification

| Result | Meaning |
|---|---|
| `0` | The requested bounded build/commit/receipt/decode succeeded; no native side effect is implied. A selector-1 zero lease explicitly means no new lease was issued. |
| `-ENODATA` | Missing owner/provenance/required source field, no configured bitmap, no receipt or no pending lease. |
| `-EAGAIN` | Torn/odd/nonquiescent guard, or receive configuration newer than last receipt. |
| `-ESTALE` | Reused owner sequence or wrong lease token/generation/producer identity. |
| `-EXDEV` | Wrong PID, inherited owner or changed/invalid origin. |
| `-ENOTSUP` | Selector 2 or unsupported owner revision. |
| `-EINVAL` | Null/wrapped/overlapping/misaligned spans or malformed required known/guard/lease metadata. |
| `-EMSGSIZE` | Insufficient output capacity or receipt size other than 25; decoder receive-size errors propagate. |
| `-EBADMSG` | Any wrong receipt byte or decoder wire error. |
| `-EACCES` | Decoder type1 with explicit zero source gate. |
| `-EALREADY` | Reinitializing an initialized owner. |
| `-EOVERFLOW` | Configured generation or next lease token cannot advance. |

The host matrix checks 131,072 combinations (`8 K values × 256 source-bit subsets × 64 mode/P52/S43/Z/P51/S5a controls`) against an independently composed expected bitmap, plus an out-of-range u32 K. It checks a literal K1 wire vector, checksum and wire layout for every combination, consumed versus unused unknown fields, all required A/D property bytes, zero-default refusal, malformed markers and provenance, odd/torn guards, alignment/wrap/capacity/alias errors, stale sequences, every wrong receipt-byte position, wrong token and producer sequence, no receipt from generation alone, pending lease immutability across overwrite and clear, gate-only clear, copied command-6 fields after freeing receive storage, capacity-tail preservation, atomic errors, generation overflow and fork rejection. The linked object imports only the existing decoder, libc and sanitizer support, with no CP start-state/publication/send dependency.

The first C matrix run succeeded under ASan/UBSan. Its Python wrapper initially failed because the import check matched `ack` inside an ASan stack-support symbol; the check was narrowed to actual symbol names and rerun. The final bounded command above passed all four tests. No VM or native transport run was used as evidence.

## Evidence, findings and source path

Evidence fixity is in [source-pins.json](source-pins.json). All pin ranges are checked before slicing the public raw ARM/Thumb CP image: length 18,090,880 bytes, SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`, file-backed `CP_VA = raw_offset + 0x108000` in `[0x108000,0x1248b80)`. Ten supplied windows total 3,886 bytes. An ELF/PE import table is n/a for this raw image; the relevant internal runtime helpers and wire/table dependencies are identified by the pinned windows. This continues the completed investigation rather than claiming new native execution.

| Evidence | Source reference / immutable observation | Reproduce / content hash |
|---|---|---|
| E-build | `a91e96..a9259e`: whole builder, configured commit, named clear and receive snapshot/gate routines. | Bounded pytest command above; pin `configured-builder-clear-snapshot`. |
| E-input | `a90720..a907ba`, `a909a4..a909bc`, `a981f4..a9823c`, `a9902a..a99036`: K, support and twice-read Z dependencies. | Same command; four named input-helper pin hashes. |
| E-selector | `a946fe..a947ec`: selector1 builder, selector2 alternate source without configured commit, other-selector clear. | Same command; pin `selector-dispatch`. |
| E-wire | `406350..40689a`, `a911e4..a91254`, `1205578..120557e`: 17-byte command/table row, logical framing, rounding and unresolved native DMA outcome. | Same command; three named wire/table pin hashes plus literal table-row bytes. |
| E-receive | `405566..4055d8` and E-build: source receive/gate and configured snapshot boundary. | Same command; pin `receive-snapshot-boundary`; existing [decoder contract](../lif-runtime-input-contract/README.md). |
| E-host | `test-cp-lif-bitmap.c` through `test_cp_lif_bitmap.py`: owned virtual build/receipt/receive assertions and sanitizer results. | Same command; test stdout explicitly keeps `native_delivery=0 cp_state=0 ready=0 ack=0`; generated host fixture hash n/a. |

| Finding | Severity / confidence / status | Location / evidence |
|---|---|---|
| F-build: Actual branch inputs determine a known configured bitmap/gate; unknown construction does not select an all-off bitmap. | `n/a_re`, high, validated for the bounded host implementation | `cp_lif_bitmap_build/request`; E-build, E-input, E-host. |
| F-lease: Configuration commit precedes enqueue and can diverge from the immutable pending/consumed logical wire generation. | `n/a_re`, high, validated for bounded ownership policy | `cp_lif_bitmap_request/observe_transport_consumed`; E-build, E-selector, E-wire, E-host. |
| F-snapshot: Outgoing build/consumption is not the receive snapshot; actual immutable receive bytes and current configured context are required. | `n/a_re`, high, validated for bounded decoder handoff | `cp_lif_bitmap_receive_decode`; E-receive, E-host, existing decoder contract. |
| F-boundary: Owned virtual bytes and decoder output do not establish original queue support/admission, native DMA delivery, semantic application or CP readiness. | `n/a_re`, high for the API's limited effects, native path remains unclosed | All six API exports; E-wire, E-receive, E-host. |

P1 (`path_type=callflow`): coherent K/P/Z/support/mode source event (E-input/F-build) → `a91e96` bitmap/gate build and configured commit (E-build/F-build) → owned command `0a` and logical wire lease (E-wire/F-lease) → all-25-byte virtual consumption comparison (E-host/F-lease) → explicit immutable receive and current configured snapshot (E-receive/F-snapshot) → existing source-derived frame decoder and copied field views (E-host/F-snapshot). Residual risks are the honest external serialization/event binding contract, unresolved original support/queue/DMA behavior, and absent semantic application/publication/CP state proof (F-boundary).

The implementation timeline was: read project/decoder contracts; publish the header; implement the stateless source builder and process-owned generation/lease owner; add the branch/receipt/receive host matrix; verify the ten supplied source windows and table row; correct the sanitizer-symbol import check; run the four focused tests; record API and evidence limits here. Parent runtime integration and the full unified batch remain separate from this delegated host result.
