# Opaque normal AU address correction and ES ring spans

`nau_resolve()` implements the original normal access-unit address correction and one/two ES-ring source spans. It preserves the entire AU byte range and all 96 descriptor bytes, returning borrowed views with the existing typed `nvideo_info` metadata. The normal AU NAL format remains **unknown**. **`native_capture = false`; `NVIDEO_NATIVE_GAPS = 63`.** This result establishes bounded opaque byte transport; it does not establish an encoder producer, native recording, native completion, ES/PI publication or Fsys completion.

Scope: six new files in this directory, public ALLLANG `libmpr.so` evidence and synthetic HOST_TEST fixtures. Existing binding, parameter-set parser, runtime and parent changes are preserved. No VM, network, hardware, physical SD, private/full-system source or media-file output is used. The parent owns integration. Formal report flavor: null, ordinary firmware contract reconstruction.

## Use the borrowed views

The stable interface is [native-au.h](native-au.h), implemented in [native-au.c](native-au.c):

```c
int nau_resolve(const uint8_t *info96, size_t info_size,
    uint64_t address_correction, uint64_t es_base,
    const uint8_t *es, size_t es_capacity,
    struct nau *out, size_t out_capacity);
```

Supply exactly 96 immutable, accessible descriptor bytes and an immutable contiguous host mapping of the **whole** ES ring. `address_correction` is the explicitly known original context+`0x40` u64 value, including zero when known. The caller owns the mapping lease and keeps it live until every consumer finishes both slices. The adapter cannot prove accessibility, immutability or ownership from numerical addresses.

The following complete C11 HOST_TEST example consumes every returned byte in order. It resolves raw address `0x1006` plus correction `0x1000` into a ring at `0x2000`, producing bytes `6,7` then `0,1`:

```c
#include "native-au.h"
#include <assert.h>

int main(void)
{
    const uint8_t es[8] = {0, 1, 2, 3, 4, 5, 6, 7};
    const uint8_t info[96] = {
        [0] = 1, [8] = 0x06, [9] = 0x10, [0x10] = 4
    };
    const uint8_t expected[4] = {6, 7, 0, 1};
    struct nau au;
    size_t consumed = 0;
    int rc = nau_resolve(info, sizeof(info), 0x1000, 0x2000,
        es, sizeof(es), &au, sizeof(au));
    assert(rc == 0 && au.span_count == 2 && au.total_length == 4);
    for (size_t i = 0; i < au.span_count; ++i)
        for (size_t j = 0; j < au.spans[i].length; ++j) {
            assert(consumed < sizeof(expected));
            assert(au.spans[i].data[j] == expected[consumed]);
            ++consumed;
        }
    assert(consumed == sizeof(expected));
    return 0;
}
```

`struct nau.info.address` remains the original raw address. `corrected_address`, `address_correction`, `es_base` and `es_capacity` record the actual resolution context. `raw_info[96]` is an independent snapshot, including every reserved byte and every unrecognized flag bit. The existing parser's known-bit masks still apply to `info.parameter_set_changes` and `info.unit`; they never replace the snapshot. PTS/DTS retain the original units and 64-bit values.

Each `spans[i]` contains `data`, `length`, `logical_address` and `es_offset`. The first starts at the corrected address. If needed, the second starts at `es_base` with offset zero. The unused second span is zero. `total_length` equals the original LE32 descriptor+`0x10`, and both nonempty spans together cover exactly that length. Ending exactly at the ring boundary returns one span. Starting away from the base with length equal to capacity returns two spans covering one full traversal.

There is no ES copy, heap allocation, linearization, NAL validation/filter, generated length prefix, Annex-B conversion, padding subtraction, unit-byte removal or implicit byte-order conversion. Callers consume the views in order. The adapter acquires/releases no lease, advances no index and emits no ACK or native publication. It introduces no callback or state framework.

## Validation and error contract

The implementation copies the descriptor to a local snapshot, reads raw address and length for arithmetic checks, then invokes the **actual existing** `nvideo_parse_info()` with the abstract extent `[raw_address, raw_address+length)`. This reuses its strict type selection and metadata decoding. That extent is used **only for metadata validation**; it is not represented as a host mapping or a real contiguous lease. The adapter independently checks the actual corrected ring mapping. The original `nvideo_parse_info()` remains unchanged and still rejects wrapped AUs supplied as a real contiguous lease.

Accepted normal sample types remain exactly `{0,1,2,3,9}`; type 0 retains its original sync/keyframe predicate. `MakeVideoEsList` itself only skips type 4, which is broader than this supported set. The adapter does not expand the existing filter. Type 4 belongs to the separate [strict BE32 parameter-set parser](../native-video-paramsets/native-paramsets.h).

For a validated start, `offset = corrected_address - es_base`, `first = min(length, capacity-offset)` and `second = length-first`. A nonempty AU cannot exceed capacity. Raw address+length, raw address+correction, corrected address+length and base+capacity must all have representable u64 exclusive ends, even when the actual ring data wraps. Consequently a range requiring an exclusive end of `2^64` is conservatively rejected. Host pointer+size arithmetic must also be nonwrapping; no source address is truncated to 32 bits.

`out` must be aligned for `struct nau`. Its **entire declared capacity**, including any unused tail, must be disjoint from the input descriptor and whole ES mapping. Descriptor and ES inputs may overlap each other. Success writes exactly `sizeof(*out)` bytes and preserves its tail. Every failure preserves every output byte. All operations are pure and leave `errno` unchanged.

| Return | Meaning |
|---|---|
| `0` | Metadata and actual one/two spans validated |
| `-EINVAL` | Null input/output, empty mapping, oversized descriptor, zero-length normal AU, misaligned output or output alias |
| `-ENODATA` | Descriptor shorter than 96 bytes |
| `-ENOSPC` | Output capacity smaller than `sizeof(struct nau)` |
| `-ENOTSUP` | Type outside `{0,1,2,3,9}`, including type 4 |
| `-EOVERFLOW` | Host pointer arithmetic or any required logical exclusive end wraps |
| `-ERANGE` | Corrected start outside the ring or length exceeds capacity |

Existing parser status mapping is `NVIDEO_OK -> 0`, `NVIDEO_INVALID -> -EINVAL`, `NVIDEO_UNSUPPORTED -> -ENOTSUP`, `NVIDEO_RANGE -> -ERANGE`; explicit arithmetic checks return `-EOVERFLOW` before the metadata parser runs. If multiple arguments are invalid, the first implemented validation failure determines the result.

## Original evidence and byte-copy path

[source-pins.json](source-pins.json) records the original public `usr/lib/libmpr.so`, **3,528,576 bytes**, SHA-256 `4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9`. All 14 exact windows fall inside the first PT_LOAD `[0,0x2e4534)`, where ELF VA equals file offset. Their supplied individual lengths sum to **1,652 bytes**; the delegation brief's 1,752-byte aggregate was an arithmetic discrepancy. All individual offsets, lengths and expected hashes are preserved and verified against the original artifact.

| Evidence | Finding | Path consequence |
|---|---|---|
| E-au-list, M`11b958`, `0x140` bytes | F1: `MakeVideoEsList` skips only infoType 4, adds context+`0x40` to LE64(V+8), and uses full LE32(V+`0x10`) | P1 resolves the corrected address and full opaque AU; no prefix or descriptor padding/unit subtraction |
| E-ring, M`282fb8`, `0x98` bytes; caller `GetEncESBufferAreaInfo` M`283050` | F2: `GetEsAreaInfo` compares inclusive `address+length-1` with the ring end and supplies end-part then base remainder | P1 returns explicit one/two ordered borrowed spans; the adapter additionally enforces complete source bounds |
| E-copy-call M`118168`; E-copy-list M`2b11bc`; E-copy-memcpy M`2b1500` | F3: original list-to-software-copy path carries the same bytes/count | P1 closes opaque byte transport through this copy path; no native producer or Fsys-complete claim |
| E-avc-config-entry, E-hevc-config-value/context, E-avc/hevc-stored-copy, E-avc/hevc-serializer and E-avc/hevc-array-writer | F4: concrete extension configuration stores, setter copies and staged serializer reads are proved independently | P2 leaves stored-to-staged transport and normal NAL production open; the AU API performs no framing inference |
| HOST_TEST modes in [test-native-au.c](test-native-au.c), C11 and ASAN/UBSAN | F5: arbitrary bytes are actually consumed from bounded views in order, with atomic failures | Parent can use the stateless opaque range adapter while retaining ownership/publication gates |

P1, `path_type=callflow`: `MakeVideoEsList` M`11b958` -> `GetEncESBufferAreaInfo` M`283050` -> `GetEsAreaInfo` M`282fb8` -> `BaseListAdd` -> `CreateXferLinkedList` M`11805c` -> `DmacLib::AddList` M`2b11bc` via vtable+`0x10` at M`118168` -> `DmacLib::TransferByMemcpy` M`2b1500`. `MakeVideoEsList` appends the returned ranges unchanged. `AddList` creates 12-byte `{u32 count, u32 source, u32 destination}` records, splitting at 8 MiB; `TransferByMemcpy` copies the exact recorded count/source/destination. This historical guest record layout does not authorize truncating host pointers, and this adapter implements no DMA records.

The original range getter does not itself validate the complete source extent. Rejecting zero length, length over ring capacity, starts outside the ring, host pointer wrap and all logical arithmetic wrap is deliberate stronger adapter validation.

P2, `path_type=dataflow`: original AVC extension configuration stores `3` at object+`4` (instructions around M`220970..78`); original HEVC configuration stores `3` at object+`0x1d` (M`220b1c..20`). Setters copy fields into the stored objects at those same offsets. Serializers read **staged** object+`0xc` / +`0x25` to produce avcC payload byte 4 / hvcC payload byte 21, whose low bits are lengthSizeMinusOne. **The stored-to-staged field transport remains unverified.** An apparent `+8` displacement is not proof of a constructor copy, and fixed configuration values or MP4 specification semantics do not prove ordinary native AU BE32 NAL prefixes. The normal AU producer remains unclosed. No constructor/staging decompilation was undertaken for this implementation.

## Reproduce the checks

From the native-camera result root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  report/native-video-au-contract/test_au.py -q --tb=short --color=no
```

Final result: **15 passed**: seven C self-check modes in both strict C11 and ASAN/UBSAN, plus original source-pin verification. Builds use `-std=c11 -Wall -Wextra -Werror -pedantic`, `-ffunction-sections`, `-fdata-sections` and `-Wl,--gc-sections`. They compile and retain the real existing parser, discard unrelated component encoder sections and require no mock parser, new library or dependency installation. Only executables in pytest's temporary directory are created; test data stays in host memory. Source verification needs the public ALLLANG `libmpr.so` at `runtime/analysis/menu-root/usr/lib/libmpr.so`.

Checks cover all normal types and every change-flag/unit byte value; preserved typed metadata/raw reserved bytes; arbitrary binary including mixed Annex-B-looking and BE-prefix-looking patterns without interpretation; actual ordered byte consumption and full expected-byte comparison; every offset and length for capacities 1 through 16; exact-end/no-empty-second-span/full-capacity cases; short/oversized/missing descriptors; unsupported types including 4; zero/oversized AUs; corrected start below/at end; correction/raw-end/corrected-end/ring-end overflow; host pointer wrap; output alignment and whole-capacity tail alias; allowed input overlap and adjacency; success tail preservation; failure atomicity and `errno` preservation. The real original contiguous parser's positive and negative boundaries and gap mask 63 are checked directly.

Initial verification stopped at a synthetic timestamp constant accidentally containing 17 hex digits and the incorrect aggregate window-byte assertion copied from the brief. The timestamp fixture was corrected, the 14 individual source hashes were independently verified, and the aggregate was corrected to 1,652. No implementation field or source window was altered to satisfy those checks. The final rerun passed.

Timeline: read AGENTS and existing binding/parameter-set contracts -> publish stable header -> implement snapshot/metadata reuse and real ring validation -> add opaque ordered-consumption/boundary checks -> verify every original source window -> correct fixture/aggregate errors -> pass scoped C11/sanitizer checks. No full regression or end-to-end native capture was run; native framing, producer, lease/publication lifecycle and Fsys completion remain integration blockers.
