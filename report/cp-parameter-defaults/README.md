# CP flag-0 constant default writes

[The generator](extract_defaults.py) closes all local writes of the pinned default initializer, including its stack serializer and final copy. It produces **2,223 default-written bytes in 157 ranges**. Applied after the existing 694 common local bytes, these establish **2,913 of 3,428 bytes**, leaving **515 bytes unknown**. This proves local values only: initialization completion, business readiness, generation readiness, publication and capture verification remain false.

The scope is offline analysis of the public ILCE-7CM2 2.01 CP image. No firmware binary is distributed here. The generator reads no private dump, starts no guest, and accesses no hardware or SD card. Existing runtime entry points, branch guards and provider behavior are outside these five new files.

## Reproduce the result

Run from the `2026-10-17-qemu-native-camera` directory, with the existing Python Capstone installation and the public `runtime/analysis/menu-root/cp/cpapp-b.bin`:

```sh
python3 -B report/cp-parameter-defaults/extract_defaults.py
python3 -B -m unittest discover -s report/cp-parameter-defaults -v
```

The first command reports:

```json
{"instructions": 999, "default_written_bytes": 2223, "composed_known_bytes": 2913, "composed_unknown_bytes": 515, "initialization_complete": false, "published": false}
```

To independently regenerate both deliverables without overwriting them:

```sh
defaults_output=$(mktemp -d)
python3 -B report/cp-parameter-defaults/extract_defaults.py \
  --trace "$defaults_output/default-local-stores.json" \
  --include "$defaults_output/cp-parameter-default-init.inc"
cmp "$defaults_output/default-local-stores.json" report/cp-parameter-defaults/default-local-stores.json
cmp "$defaults_output/cp-parameter-default-init.inc" runtime/analysis/device-models/cp-parameter-default-init.inc
rm -r "$defaults_output"
```

`--source PATH` selects another local file only if it has the exact pinned identity. Output creation uses exclusive mode, so an existing output path causes failure. Source tests explicitly skip if the public binary is absent; a skip is not source verification.

Validation at handoff: all 13 source tests passed against the public image, and CLI regeneration reproduced both artifacts byte for byte. A temporary C11 program compiled with `-Wall -Wextra -Werror -Wpedantic -fsanitize=address,undefined` applied both generated tables and checked every composed value and mask byte under `a5` and `5a` poison patterns; all 2,913 values and all 515 preserved holes passed. The repository script-sync check passed. Broader runtime/provider integration and its regression suite remain outside this batch.

## Evidence and findings

| Evidence | Source or artifact | Finding | Consequence for the runtime path |
|---|---|---|---|
| E1 | Full public CP: 18,090,880 bytes, SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`; VA = file offset + `0x108000` | The input is the fixed public CP image | Different images fail before extraction |
| E2 | `[8db9bc,8dc2c2)`: 2,310 bytes, 606 Thumb instructions, SHA-256 `0a576899cd7391403b7508813ed7bad8bfe2a3d990f529554e429b6acc3d1188` | Entire default local routine is traversed, ending at its actual outer `pop ... pc` | No fabricated caller address is executed |
| E3 | `[8dc2c2,8dc67e)`: 956 bytes, 393 instructions, SHA-256 `7803843c7c4f2122c80eeda042eff77b5344d70ce4334bb0df6c18f92de3c32c` | Serializer reads arguments and stack words and writes 176 little-endian bytes to the caller's stack | Final memcpy transfers actual serialized bytes to `P+870` |
| E4 | Zero helper `[61ed00,61ee38)`: 312 bytes, SHA-256 `08db00a35b3411ecffd440d6af222556dbb9f6f386d0fabac7be91a5b6d9281b` | Known source zero semantics close 18 calls | Each target and length is logged; arbitrary calls are rejected |
| E5 | Memcpy `[61e60c,61e84c)`: 576 bytes, SHA-256 `0b43ce9d7e3069da0c5bd26e230220c422906140bf9988b85999e3a4c3de809b` | Final nonoverlapping copy has source-stack offset `-216`, target `P+870`, length `b0` | Copy fails if any source byte is unknown |
| E6 | [Complete root-write trace](default-local-stores.json): 515 store records, each with PC, offset, length and bytes | Final writes cover 2,223 distinct root bytes | Generated ranges contain exactly default-written bytes |
| E7 | [Source tests](test_source.py): exact regeneration and counterfactual failures | Unwritten root bytes and unknown registers are not inferred to be zero | Preserve holes and require runtime branch eligibility before applying the table |

The actual routine has **18 zero calls, one serializer call and one memcpy call**. Its 19 `blx` instructions include memcpy; they do not represent 19 zero calls. Together with the serializer `bl`, this is 20 call records.

## Trace the constants

The extractor decodes the two entire windows with actual Capstone operands, including operand shift metadata. Its finite instruction set covers only the source's moves, arithmetic, loads, stores, logical right shifts, stack operations and the pinned calls. All 999 decoded instructions must be visited once, with a maximum call depth of one. Conditional instructions, other operations, other callees, repeated PCs, unknown addresses, address wrap and out-of-bounds accesses fail.

Initial `r0` is `P=0165a720`, and the synthetic stack has a bounded 1 KiB address region. Other incoming registers, including callee-saved values, are unknown. Unknown saved values can be pushed and restored without becoming parameter data. The source's stack allocations and writebacks determine aliases; `strd` stores the first register at the low address. The serializer's actual `lsr` operations split each word into bytes, including high bytes. The outer return stops at the real `pop`, after verifying stack balance.

The seed comes from running the existing, fixed-path [common extractor](../cp-parameter-initializer/extract_common.py) against the same image and comparing its full result with [the common trace](../cp-parameter-initializer/common-local-stores.json). Only its 694 known bytes enter memory. All other root bytes stay unknown, irrespective of BSS or allocation assumptions. After zero, copy and serializer returns, `r0..r3` and `ip` become unknown; the serializer executes its actual body and preserves callee-saved state.

The actual default writes are independent of common values: tracing with an empty common seed produces the same 2,223-byte default table, while composing with the common seed preserves its additional known bytes. Tests also poison all known common values, make a counterfactual root read consume an absent common byte, and pass nonzero four-byte arguments through the serializer. Those counterfactuals test the finite tracer; production extraction always checks the unmodified public source hashes first.

## Integrate the generated ranges

The [generated include](../../runtime/analysis/device-models/cp-parameter-default-init.inc) declares:

```c
struct default_init_range { uint16_t offset, bytes, data; };
static const unsigned char default_init_values[];
static const struct default_init_range default_init_ranges[];
```

For each range, copy `bytes` from `default_init_values + data` to `root + offset` and mark only those bytes known. Its data and range names are separate from the common include. Apply the common local table first, and this table only after a source-backed flag-0 branch guard. This include does not implement that guard, AP initialization gates or provider promotion.

JSON `ranges` and `data` describe exactly those default-written bytes, including their final values after any later writes. `writes` preserves intermediate evidence. `composed_known_bytes` and `composed_unknown_ranges` describe the common-plus-default mask without storing a second payload; reconstruct the composed image from the two tables in order. The only overlap between common and default writes is `P+d5c..d5f`.

| Field | Composed value | Meaning for integration |
|---|---|---|
| `P+28`, `P+2c`, `P+30` | 5, 1, 60 | Default local constants |
| `P+d8..df` | `9010100b9010100b` | Halfword loads and copies agree with source |
| `P+1c8..1cf` | 8 zero bytes from common | Default table does not rewrite these bytes |
| `P+668`, `P+670`, `P+678`, `P+67c` | 5, 5, 4, 8 from common | Retained common values |
| `P+870..91f` | 176 serialized zero bytes | Derived from source arguments and stack, then copied |
| `P+d58` | 1 | A local byte, not a completion receipt |
| `P+d5c` | 0, replacing common's 1 | Do not use as a publication generation |

The common AE tail, its callback notification and `c1aa3e` are not executed or modeled. The broader constructor, business initialization and publication remain unverified. Neither the generated table nor this report establishes that camera capture is operational.
