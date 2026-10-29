# Bounded real LIF frame decoder

`cp_lif_frame_decode` validates and copies a real LIF wire frame and extracts the source-derived dynamic layouts of top commands 5 and 6. It consumes explicitly known runtime bitmap and type1 gate inputs. It owns no CP state and calls no start-state data owner. Positive tests are synthetic host fixtures; `transport_decoded=1` does not establish actual native receive, semantic application, publication, readiness or ACK. **`native_producer_wired=false`** remains the integration status.

The delegated scope is six new files under this public ALLLANG result: [C implementation](../../runtime/analysis/device-models/cp-lif-frame.c), [header](../../runtime/analysis/device-models/cp-lif-frame.h), [host C matrix](../../runtime/analysis/device-models/test-cp-lif-frame.c), [pytest entry](../../runtime/analysis/test_cp_lif_frame.py), this report and [source pins](source-pins.json). The owner-authorized offline research agreement and delegated request authorize this work. Existing changes, JPEG geometry, runtime wiring, unified validation, VM execution, network, private/full-system data, real hardware and physical SD are outside this worker's scope. This paragraph is the scope record; no separate case files are created. Report flavor is `null`; exploitation, IOC and ATT&CK analysis are n/a.

## Reproduce and integrate

Run from `2026-10-17-qemu-native-camera`:

```bash
python3 -m pytest runtime/analysis/test_cp_lif_frame.py -q
```

Both tests passed with the public CP asset present. The host matrix compiles C11 with `-Wall -Wextra -Werror -pedantic`, ASan and UBSan. The source test checks the full image identity, all 12 supplied windows (5,280 bytes), three supplementary gate windows (46 bytes), table pointers/rows, schema IDs, lengths and `80 00` terminators. If public assets are absent, only source verification skips. Host tests require no firmware, VM or device.

The API exports only `cp_lif_frame_decode(rx, rx_size, context, out, out_capacity)`. The context and decoded output are caller-owned, fixed-size objects. No allocation, PID ownership, hidden global, callback, task queue or publication API is introduced.

1. Hold the external source/transport owner's lock and provide accessible immutable frame/context storage. Set the actual `HOST_TEST` or `VIRTUAL_SOURCE` origin, matching even `sequence_before/sequence_after` and `quiescent=1`. These declarations are caller contracts, not proof of native execution or an internal mutex.
2. Supply `CP_LIF_BITMAP_A923D0_SNAPSHOT` only for an explicit snapshot of the runtime bitmap copied by `a923d0`: `1b1aa12..21` to `1b1aa23..32`. Every one of the 16 `bitmap_known` bytes must be exactly 1. An all-zero bitmap is valid only with this explicit event and fully known mask. Zero construction leaves the bitmap and provenance unknown; it does not select an all-off capability set.
3. For type1, additionally supply the full u8 at `1b1aa10` and `type1_source_known=1`. A known zero fails admission; every known nonzero u8 passes this particular source gate. Types 2/3 do not require this byte. The value is not a Boolean free pass or a mode/property default.
4. Provide `out_capacity >= sizeof(*out)` with no overlap between the entire declared output capacity and either input. Only `sizeof(*out)` bytes are written on success; capacity tails remain unchanged. The output contains its own copied frame and field/command offsets into that copy. It retains no input pointers, so freeing or reusing the original receive buffer cannot invalidate the result.
5. A separate transport/semantic consumer must establish actual delivery and apply decoded fields to its real model. This decoder never advances CP state/current/known reply/worker/generation, invokes `cp_start_state_data`, or sends an ACK. There is no direct binding to the CP provider.

The API is stateless: the parent must bind snapshots to the correct transaction and enforce freshness, source/process ownership and replay policy under its lock. A matching old sequence cannot be identified as stale without external history. No fork/PID or staleness test is claimed here. Sequence equality does not independently detect a dishonest or unsynchronized producer.

## Exact wire contract

`404c48` is the source wire validator. Let `L = LE16(frame[1:3])`.

| Bytes | Source meaning / decoder treatment |
|---|---|
| `0` | Must be `f0`. |
| `1..2` | LE16 `L`; bounded decoder accepts `9 <= L <= 0x220`. |
| `3` | Low three bits are type 1, 2 or 3; the full byte is copied and exposed as `flags`. High bits are preserved. |
| `4` | Full opaque byte, copied and exposed as `opaque`; never required to be zero. |
| `[5,L-3)` | Exactly `L-8` command bytes. |
| `[L-3,L-1)` | LE16 `sum(frame[1:L-3]) & 0xffff`, including both length bytes, full flags, opaque byte and command payload. |
| `L-1` | Must be `55`. |
| `L`, if present | Exactly one extra byte may be supplied, and must be zero. It is copied; `rx_length=L+1`, `frame_length=L`, `extra_zero=1`. |

The checksum excludes `f0`, checksum bytes, footer and the optional extra zero. Passing the checksum does not bypass the runtime gate or make the bitmap known. A zero leading byte, oversized receive buffer, short frame, extra nonzero byte or unrecognized type is rejected. The original extra-zero branch can bypass its ordinary length-range branch; this bounded decoder deliberately retains `9..0x220` for both receive forms rather than reproducing unsafe length aliases.

Type1 gate recovery uses the full source function, not a guessed parameter name. `a92580` loads `1b1aa10` and returns `byte ^ 1`; `405590` captures this before the bitmap snapshot, and `4055c6` applies a second XOR before passing validator argument r3. `404d18..1e` rejects only when `(r3 ^ 1) == 1`, hence exactly when the original byte is zero. All 255 nonzero values are exercised. Supplementary exact bytes are in `type1_gate_evidence` in the pin file. `1b1aa10` is a runtime dependency and is never read as a file offset.

The incoming frame cannot declare a new bitmap. Outgoing command `0a` has producer paths through `a91e96`, but its complete source wire/event binding is not closed in this deliverable. Therefore no outgoing-0a consumer or send-verification claim is added. The typed 16-byte snapshot input represents the actual `a923d0` source event only; it is not evidence that an original send occurred.

## Dynamic command subset

Top-command pointer `1107030 -> 120553c` references six-byte rows `{u16 command, u16 metadata, u16 length}`. Rows 5 and 6 are respectively `(5,0,0xff)` and `(6,0,0xff)`. The second word is called metadata; this implementation does not establish that it is a support flag.

`1107034 -> 1206dfd` and `1107038 -> 1206e7f` reference `{u8 field_id,u8 field_length}` schemas terminated by `80 00`. All lengths below are decimal:

| Top command | Field IDs in source schema order | Lengths |
|---|---|---|
| 5 | `00..1b` | `8,1,8,3,10,28,2,6,1,2,8,6,6,6,1,6,3,3,4,4,4,8,36,40,8,4,6,3` |
| 6 | `40..4a` | `2,11,9,4,6,7,45,4,8,8,24` |

`a924e6/a92568 -> a924f4` selects schema fields using `bitmap[(id >> 3) & 15] & (1 << (id & 7))`. Thus ID `07` uses byte 0 bit 7, ID `08` uses byte 1 bit 0, ID `40` uses **byte 8 bit 0**, and ID `48` uses byte 9 bit 0. Selection order is schema order, not bitmap population order. The payload concatenates selected field data **without field-ID bytes**. A command length is `1 + sum(selected lengths)`; the single leading byte is its top command.

The decoder walks `[5,L-3)` using these exact derived lengths. It supports one command 5, one command 6, or both in either order, including explicitly known empty selections. Selected fields cannot cross the command-area end. Each field view contains its top command, source field ID, offset and length; each command view contains offset, total length, metadata, first-field index and field count. There are at most two commands and 39 fields. Selecting every field gives 225 command-5 data bytes and 128 command-6 data bytes; together the frame is 363 bytes.

Other top commands, including `09` and `0a`, fail with `-ENOTSUP` atomically. Duplicate 5/6 commands also fail as an explicit subset restriction; this does not assert that original firmware rejects duplicates. Unknown bitmap bits outside these two schemas remain legal snapshot bytes and consume no field data. A checksum-valid `L=0x220` frame can still fail as unsupported because the finite 5/6 subset cannot account for arbitrary extra bytes. No fixed lengths are invented for other commands.

## Errors and ownership checks

Every failure leaves the complete output object and its capacity tail unchanged. Inputs are never mutated.

| Result | Meaning |
|---|---|
| `0` | Copied, validated frame and all field views; `transport_decoded=1` only. |
| `-ENODATA` | Missing provenance, bitmap event, any required bitmap byte, or required type1 source byte. |
| `-EACCES` | Type1 with a known zero `1b1aa10` source byte. |
| `-EAGAIN` | Torn/odd sequence or nonquiescent source transaction. |
| `-EXDEV` | Invalid source-origin enum. |
| `-ENOTSUP` | Unsupported bitmap event, top command or duplicate command. |
| `-EMSGSIZE` | Receive/declared-length/capacity error or selected field overruns the command area. |
| `-EBADMSG` | Header/footer/type/checksum error or nonzero optional extra byte. |
| `-EINVAL` | Null/wrapped address span, typed misalignment, output/input overlap, or nonbinary known/quiescent marker. |

The entire output capacity participates in overlap checks, including an input placed only in an unused output tail. Input storage may share read-only bytes. Inline fixed-size bitmap/mask arrays have no separate capacity tails. The caller must supply mapped, accessible objects for all declared spans; arithmetic checks cannot discover inaccessible memory or make concurrent mutation safe.

## Evidence, findings and source paths

The public raw CP image is 18,090,880 bytes, SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`. Mapping is exclusively `CP_VA = raw_offset + 0x108000`, valid in `[0x108000,0x1248b80)`. All pin ranges are checked before slicing. This continues completed source investigation `e2e83196`; no boot history is regenerated. The source is a raw ARM/Thumb image, so an ELF/PE import table is n/a. Relevant internal dependencies are the checksum helper, runtime getter/snapshot and dynamic-cache routines identified below; no whole-image import survey is claimed.

| Evidence | Immutable source / observation | Reproduction |
|---|---|---|
| E-wire | `404c48..404d6c`, checksum loop `a4825a..a4826e`; bounded frame fields, checksum and optional-zero behavior. | Pin labels `wire-validator`, `checksum-loop`; pytest command above. |
| E-schema | `1107030..110717c`, `120555a..1205578`, `1206dfd..1206e97`, `a923d0..a92576`; table rows, schema terminators, snapshot copy and exact ID-to-bit mapping. | Four matching pin labels; raw table/schema assertions in the Python test. |
| E-gate | `a92580..a92590`, `405590..40559a`, `4055c4..4055d8`, together with E-wire; getter/caller/validator double-XOR boundary. | Three supplementary exact-hex windows plus validator pin. |
| E-cache | `a47448..a478c8`, `405b22..405d58`; cache records and source state commits occur outside decoding. | `cache-layout-and-getters`, `cache-commit-state-guards` pins. |
| E-worker | `40bae4..40c2a8`, `a955da..a9564e`, `a908ea..a9092e`, `3c7adc..3c7b68`; worker/state/mode sources remain separate prerequisites. | Remaining supplied windows; no native execution claim. |
| E-host | Independent literal command-5/6/both vectors and sanitizer-tested bounded input matrix. | `test-cp-lif-frame.c` through pytest; stdout explicitly reports native receive/application/publication/ACK as zero. |

| Finding | Severity / confidence | Evidence / status |
|---|---|---|
| F-wire: The copied decoder preserves full flags/opaque bytes and the exact optional-zero receive form. | `n/a_re`, high | E-wire + E-host; implemented and host validated. |
| F-schema: 5/6 data lengths and field ordering depend on an external 16-byte bitmap snapshot; frames carry no field IDs or bitmap declaration. | `n/a_re`, high | E-schema + E-host; implemented and host validated, not a native producer claim. |
| F-gate: Type1 requires a known nonzero full-u8 source byte, independently of checksum validity. | `n/a_re`, high | E-gate + E-wire + E-host; implemented and host validated. |
| F-boundary: Decoding alone supplies no CP transition, worker history, semantic application or publish/ACK authorization. | `n/a_re`, high for this API's effects | E-cache + E-worker + E-host; integration remains unclosed. |

P1 (`path_type=callflow`): actual source event `a923d0` snapshot + actual `1b1aa10` byte (E-schema/E-gate) → immutable receive frame → validator rules `404c48` (E-wire/F-wire/F-gate) → dynamic schema walk `a924f4` (E-schema/F-schema) → caller-owned copied frame and views (E-host). A separate future owner must consume these data and establish delivery/application evidence (F-boundary).

P2 (`path_type=callflow`, residual dependency): receiver `405084` through `a90320 -> a47ca8` fills entries `19edfd0 + slot*0x14`; `a96924` queues callback `a9695d -> 405490`. The original cache uses `*1101f84 + index*0x324`, top-command pointers at `+0x20` with last index `+0x1c`, dynamic field IDs at `+0x124+8*j`, data pointers at `+0x128+8*j`, and last dynamic index at `+0x120` (E-cache). The real 3→4 commit at `405d0c` requires command 5 with old state 3; 4→5 at `405d4c` requires command 6 with old state 4. The separate 2→3 source path `a955da -> a908ea(3)` is gated by actual top command 9 and `1b1ac4e`, not command-5 field ID 9 (E-worker). These effects are not implemented or implied by this decoder.

The implementation timeline was: consume the completed source contract; inspect the full validator and exact bitmap-index instructions; publish the fixed API; implement copy/validation/field views; check source-window hashes; run the host sanitizer matrix; add independent literal vectors and checksum-wrap coverage; rerun focused tests and write this report. No native boot or frame producer was executed.

The host matrix covers each of 128 bitmap bits with both commands, every selected field, both command orders, all-zero explicitly known and all-one selections, the byte-0/1 and byte-8/9 boundaries, all 255 allowed type1 bytes and zero/unknown refusal, high flag bits and opaque-byte preservation, optional zero, corrupt/truncated/short/oversized frames, checksum rollover, unknown/malformed masks and provenance, torn source guards, unhandled/duplicate commands, data offsets and ownership after freeing input, failure atomicity, typed alignment, address arithmetic and output aliasing including capacity tails. Native source delivery, outgoing-0a verification, live worker history, property repository selection and end-to-end camera readiness remain with the parent unified batch. Public property seed bytes are not imported as an implicit mode or capability fallback.
