# Original MPR type-4 parameter-set memory parser

This directory implements a strict, standalone reader for the original 96-byte `MPRVideoInfo` **type 4** parameter-set entry. It resolves the entry's logical ES address using the explicitly supplied original context correction, checks the actual caller-owned contiguous mapping, and returns borrowed pure VPS/SPS/PPS NAL slices. It supports one SPS/PPS for AVC and one VPS/SPS/PPS for HEVC, preserving count, span, opaque source ID and change metadata. It neither allocates NALs nor changes a container or cache.

**`native_capture = false`.** The original encoder producer, ordinary access-unit framing and native completion/publication lifecycle remain unresolved. Passing these host tests does not establish original recording or full native execution. The existing `nvideo_parse_info()` continues to accept only sample types `0/1/2/3/9`; no existing binding or `NVIDEO_NATIVE_GAPS` value was changed.

## Scope and files

Authorization and scope are the delegated implementation of this six-file directory, using the supplied public ALLLANG consumer contract. The library is [native-paramsets.c](native-paramsets.c), its stable API is [native-paramsets.h](native-paramsets.h), and the host checks are [test-native-paramsets.c](test-native-paramsets.c) and [test_paramsets.py](test_paramsets.py). [source-pins.json](source-pins.json) binds the public source artifact and eight windows totaling 3296 bytes. This README contains the scope and evidence report; no additional case files are required.

Only these six new files belong to this change. No existing runtime, build, binding, VM, hardware, physical SD, network, private/full-system source or raw firmware was modified. The public library is read only for hash verification. No external dependency was added, and no binary or media artifact is delivered here. General camera preload procedures do not apply to this host memory parser.

## Run the host checks

From the native-camera result root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  report/native-video-paramsets/test_paramsets.py -q
```

Recorded result: **37 passed**. There are 17 C self-check modes and one actual AVC roundtrip/decode test, each built as strict C11 and with ASAN/UBSAN, plus one public source-pin check. Compilation uses `-std=c11 -Wall -Wextra -Werror -pedantic`; the parser itself needs only the C standard library. Tests reuse installed `cc`, pytest, FFmpeg with libx264, and FFprobe. Executables go to pytest's temporary directory. Encoded and decoded media remain in anonymous stdin/stdout pipes. If the extracted public `runtime/analysis/menu-root/usr/lib/libmpr.so` is absent, the pin check is explicitly skipped; it **passed without a skip** in the recorded run.

The AVC oracle makes a real 16×16 red frame using host libx264. Its test-only Annex-B splitter extracts the actual SPS/PPS, constructs the original BE32-length group memory, calls the C parser, and compares **every returned NAL byte** with the originals. Replacing those parameter sets into the actual access-unit stream then produces one independently verified H.264 frame: FFprobe checks codec, dimensions, frame count and keyframe; FFmpeg decodes pixels and checks the red source. This is labeled **HOST_TEST**, and none of these bytes are claimed as a firmware capture. Static HEVC fixtures exercise only group boundaries and NAL headers; complete HEVC RBSP decoding is not verified.

Self-checks cover all change-byte values, all opaque-ID values, all non-type-4 values, all counts above one, every truncated descriptor/output size, zero and arbitrary declared lengths, missing groups, short spans, wrong byte order, a length including its own prefix, zero/overlong lengths, unknown trailing bytes inside a group, wrong NAL kinds, forbidden bits, Annex-B bytes inside a supposed pure NAL, short HEVC headers and zero temporal-id-plus-one. Range checks cover correction overflow, corrected end overflow, logical mapping overflow, unmapped/short mappings, numerical host pointer wrap, misalignment, immutable input/output aliasing (including output-capacity tails), output canaries and exact heap allocation boundaries under sanitizers. Every checked failure leaves the output unchanged.

## Call the parser

The only exported function is:

```c
int nparamsets_parse(const uint8_t *info, size_t info_size,
    uint32_t container_type, uint64_t address_correction,
    uint64_t es_base, const uint8_t *es, size_t es_capacity,
    struct nparamsets *out, size_t out_capacity);
```

`info_size` must be exactly 96, with all bytes accessible and immutable for the call. `container_type` must be the semantic container FOURCC `NPARAMSETS_AVC1` (`0x61766331`, `avc1`) or `NPARAMSETS_HVC1` (`0x68766331`, `hvc1`). It is **not** the unproved outer `PayloadMpr+0x18` codec enumeration, a host-endian FOURCC byte load, `hev1`, or a codec guess from a NAL.

`address_correction` is an explicit `uint64_t` supplied from the **known original context+0x40 value**. There is no default, implicit lookup, address masking, host-pointer cast or SDS interpretation. An explicitly known zero value is permitted. The caller resolves `es` to one immutable contiguous mapping with logical range `[es_base, es_base + es_capacity)`. That real mapping capacity bounds the parser. Pointer/range arithmetic is checked numerically, but C cannot establish whether arbitrary caller pointers actually refer to accessible live storage.

The complete `out_capacity` range must be nonwrapping and disjoint from both the input descriptor and the complete ES mapping. `out` must meet `_Alignof(struct nparamsets)` and have at least `sizeof(*out)` capacity. Descriptor and ES may overlap each other because both are read only. All fields and NALs are validated into a local result before a single output copy. Success writes only `sizeof(*out)` bytes, leaving a larger output tail alone; every failure leaves all output bytes unchanged. `errno` is not modified.

| Return | Meaning |
|---|---|
| `0` | Supported entry fully validated; borrowed slices available |
| `-EINVAL` | Null/bad argument, oversized descriptor, misalignment, output/input overlap, bad NAL header or trailing bytes inside a group |
| `-ENOSPC` | Output capacity is smaller than `sizeof(struct nparamsets)` |
| `-ENOTSUP` | Wrong entry type/container or an unsupported group/count form |
| `-ENODATA` | Short descriptor, empty mapping, missing mandatory group, incomplete BE length word, zero-length NAL or NAL length beyond its group span |
| `-EOVERFLOW` | Host pointer range, ES logical range, address correction or corrected group end wraps |
| `-ERANGE` | Corrected parameter-set range is outside the supplied ES mapping |

When several inputs are invalid, the first failed check determines the error; the table does not promise an ordering between simultaneous faults. Ring-wrapped or segmented mappings cannot be represented by this API and fail the contiguous mapping check. A future caller could independently stage a live immutable contiguous copy, but that would be an explicit host adaptation, with its own ownership, and no claim about original ring consumption.

## Wire fields and addressing

All fields in this table are read little endian except the one-byte fields. Unlisted bytes are ignored; there is no reserved-zero requirement.

| Offset | Width | Meaning |
|---|---|---|
| `00` | u8 | Entry type, must be `4` |
| `01` | u8 | Change flags: bit 0 VPS, bit 1 SPS, bit 2 PPS; full raw byte retained |
| `08` | u64 | Original wire ES address before context correction |
| `10` | u32 | Declared data length, retained as informational metadata |
| `28`, `2a`, `2b` | u16, u8, u8 | VPS total span, count, opaque source ID |
| `2c`, `2e`, `2f` | u16, u8, u8 | SPS total span, count, opaque source ID |
| `30`, `32`, `33` | u16, u8, u8 | PPS total span, count, opaque source ID |

The corrected address and group starts are:

```text
A   = checked_add_u64(LE64(info + 0x08), address_correction)
VPS = A
SPS = A + VPSspan
PPS = A + VPSspan + SPSspan
end = A + VPSspan + SPSspan + PPSspan
```

Each `es_offset` locates the group's start, including its four-byte length word, relative to the supplied ES mapping. For the empty AVC VPS, `nal = NULL`, `nal_size = 0`, and its offset remains `A - es_base`. Output also snapshots the container, full source change byte, raw wire address, explicit correction, corrected address, ES logical base/capacity, total group bytes and informational declared length. It does not retain a pointer to the input descriptor.

**`info+0x10` is not a parameter-set bound.** The original parameter-set consumer does not use that word to bound its reads. Its relation to the parameter area is not established, so the adapter neither requires equality nor requires a nonzero value nor compares the group sum with it. Zero, a smaller number and `UINT32_MAX` all remain informational. The sum of the actual three spans and the caller-resolved ES mapping supply the bounds.

## Original behavior and strict adapter rules

M`11bbc4` (`GetParameterSetPerInfo`) copies four bytes through `DataCopy`, reverses the word to obtain a **big-endian NAL length excluding the four bytes**, and advances by `4 + length`. Pure NAL bytes are passed to the container; there is no Annex-B prefix. The original helper takes only the first NAL for a non-PPS group and loops by count for PPS. M`11bed0` dispatches using count/change gates and opaque-ID deduplication, but advances group offsets by the total spans even when a group is unchanged.

This adapter accepts a deliberately smaller set of forms:

| Container | VPS | SPS | PPS |
|---|---|---|---|
| `avc1` | Span and count both zero | One NAL | One NAL |
| `hvc1` | One NAL | One NAL | One NAL |

Every present group must be **exactly `BE32(nal_size) + nal_size` bytes**. Multi-NAL groups return `-ENOTSUP`; unaccounted trailing/padding bytes inside a one-NAL span return `-EINVAL`. Arbitrary unused bytes elsewhere in the caller's larger ES mapping are allowed. Missing mandatory groups return `-ENODATA`. Nonempty AVC VPS forms return `-ENOTSUP`.

The adapter additionally checks AVC NAL types 7/8 and the forbidden-zero bit. HEVC requires at least two header bytes, types 32/33/34, a clear forbidden-zero bit and nonzero `nuh_temporal_id_plus1`; layer IDs are not forced to zero. These header checks and the exact-span rule are **adapter validation**, not recovered checks attributed to the original consumer. Whole RBSP syntax, profile support, ID relationships and decoder suitability remain the downstream consumer's responsibility.

All supported groups are bounded and structurally validated even when their source change bit is clear. The returned `changed` booleans reflect only the corresponding source bits; nonempty data must **not** be automatically applied to a cache or container. No prior cache state or deduplication state is held. `source_id` is a separate opaque byte for each group and is never relabeled as a parsed RBSP parameter-set ID.

## Borrowing and original ownership

The caller owns the ES mapping lease. Each nonempty `nal` pointer is borrowed directly from that mapping and remains usable only while the caller keeps those bytes immutable and the mapping live. Consumers must finish, or make their own owned copies, **before** the caller retires or reuses the mapping. The parser has no retain/release callback, heap ownership transfer, cache update, ring read-index push, completion, ACK or ready state.

The original writer makes heap copies and frees temporary NAL storage at M`116650..11665c` after the container copy. The pinned PPS cache code uses 16-byte slots with length at `+0` and pointer at `+8`; the cache's later lifecycle remains unresolved. These facts do not authorize freeing a borrowed ES slice or passing it to a consumer that assumes ownership of the original temporary heap allocation.

## Evidence, findings and path

The supplied static findings are pinned to public `usr/lib/libmpr.so`, size **3528576**, SHA-256 **`4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9`**. The first `PT_LOAD` maps file/VA `0..0x2e4534`; the second maps file `0x2e53a8` to VA `0x2f53a8` for `0x77c88` bytes. Tests check the actual ELF load headers, full-artifact hash, VA-to-file translation and all eight individual window hashes. No original bytes are embedded here. Reproduction for all evidence rows is the pytest command above; static evidence requires the offline public ALLLANG extraction at the documented menu-root path.

| Evidence | Source reference / content hash | Observation |
|---|---|---|
| E-001 | M`11bbc4`, `0x30c` bytes; window SHA-256 in source-pins.json | Four-byte BE length excluding the word; pure NAL consumer framing; non-PPS first-only and PPS count loop |
| E-002 | M`11bed0`, `0x2a0` bytes; window SHA-256 in source-pins.json | Sequential total-span positioning, count/change gates and opaque-ID deduplication |
| E-003 | M`11835c`/`11661c`, `0x118`/`0x50` bytes; window SHA-256 in source-pins.json | Writer routing and temporary copied NAL free after container consumption |
| E-004 | M`21f54c`/`1d395c`/`20ad18`/`1f6004`, `0x1c8`/`0x210`/`0x110`/`0xe4` bytes; window SHA-256 in source-pins.json | Container pure-NAL context, semantic codec FOURCCs and PPS cache slot layout |
| E-005 | Strict C11 plus ASAN/UBSAN C self-checks; content hash n/a, reproduced by tests | Supported shapes, arithmetic/alias bounds, raw metadata retention and unchanged output on failure |
| E-006 | Real host libx264 parameter sets, independent FFprobe/FFmpeg checks; content hash n/a, bytes generated in pipes on each run | Exact pure SPS/PPS bytes survive parsing and decode with the actual host access unit |

| Finding | Evidence IDs | Status / confidence / location | Consequence |
|---|---|---|---|
| F-001 (`n/a_re`, `reverse_algo`) | E-001, E-002, E-004, E-005, E-006 | Validated for the explicit adapter subset; high; `nparamsets_parse` | Original parameter-group consumer framing and bounded single-group memory parsing are available |
| F-002 (`n/a_re`, `reverse_algo`) | E-002, E-005 | Validated; high; group metadata/offset construction | Change flags and opaque IDs remain independent of group positioning and RBSP syntax |
| F-003 (`n/a_re`, `other`) | E-003, E-004, E-005 | Validated borrowing restriction; high; header lifetime contract | The parser cannot transfer the original writer's heap-copy ownership; later original PPS cache lifecycle remains unknown |

P-001, `path_type=callflow`: caller's immutable type-4 descriptor and live resolved ES mapping → explicit corrected address and sequential span bounds (E-002/E-005, F-001/F-002) → BE32 lengths and borrowed pure NALs (E-001/E-004/E-005/E-006, F-001) → downstream consumer finishes while caller retains the mapping (E-003/E-004/E-005, F-003). The parser stops at borrowed data; no original container, native completion or ES/PI retirement is exercised.

Timeline: read project and binding contracts → publish the standalone header → implement checked single-group parsing and metadata snapshots → run strict and sanitizer fixtures plus the real AVC decode → verify all original source pins → document the stable result. The initial targeted run passed all 37 cases. A joint batch/full regression is reserved for the parent after this directory is stable. Report flavor: null, ordinary implementation from public firmware consumer evidence; no vulnerability, IOC or native capture claim.

## Remaining native integration blockers

The original encoder's BE parameter-set producer has not been located. Ordinary access-unit framing is still unknown; a type-4 parameter-set BE prefix does not establish AU framing. Native source ownership/SDS, pixel layout, encoder completion lease, original container ABI and ES/PI publication/retirement must still be closed independently. This helper does not clear the binding's parameter-set gap bit or enable any native request. Multi-parameter groups, segmented mappings, whole RBSP decoding and original PPS-cache management remain unsupported by this API.
