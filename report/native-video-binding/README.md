# Native video descriptor binding: implemented parts and blocked native execution

This directory implements strict readers for the original MPR/Avbbc request, selected fields of its coherent EncOpen parameters and the encoded VideoInfo entry, a builder for the proved Sampletype64 member offsets, and a bounded packet bridge that borrows the existing `video_engine_stream`. The bridge actually consumes a caller-owned RGB lease, encodes H.264, writes the actual packet through the caller's DMA operations, reads it back, retires the source lease, and only then publishes a **component** completion. It adds no encoder, mux, file writer, subprocess backend or media-file output.

**Native recording remains unsupported.** The original per-frame input lease/SDS, YC packing, access-unit framing, parameter-set byte ranges and ES/PI publication contract are not closed. `nvideo_native_request()` returns `NVIDEO_UNSUPPORTED` for every otherwise valid original request and reports all six mandatory gaps. It cannot invoke the component bridge or emit a native completion. No native successful ACK or original MPR/Fsys output is claimed.

The stable integration API is [native-video.h](native-video.h); implementation is [native-video.c](native-video.c). The EncOpen extension changes only this binding directory. The parent owns the joint batch and single eventual end-to-end VM.

**EncOpen validation:** the extension is accepted through the joined batch, not an independent VM. See [the batch receipt](../2026-10-27-unified-camera/verification-with-encopen-and-bank3.json) for executable test/build/ABI results; absence of that receipt means acceptance is pending. The historical results below predate this extension. No existing source-pin manifest was changed.

## Reproduce the component checks

From the native-camera result root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  report/native-video-binding/test_native_video_binding.py -q
```

Before the EncOpen extension, the recorded result was **23 passing pytest cases**: ten C self-check modes and an independent pipe decode, each in strict C11 and ASAN/UBSAN builds, plus one source-pin verification. Builds use `-std=c11 -Wall -Wextra -Werror -pedantic`. Existing installed libavcodec/libavformat/libavutil/libswscale and libx264 are reused. FFmpeg is a test oracle only; decoded media and encoded packets stay in anonymous stdin/stdout pipes. Only test executables are created in pytest's temporary directory.

The two-frame decode checks dimensions, frame count, mean RGB error below 8/channel against each actual synthetic source, and visible source change. Fault modes cover acquire/release/write/read errors with exact callback error preservation; corruption; mismatched SDS identity; unknown source layout; one-byte destination; repeated frame sequence; reentry; stop/cancel/restart; and DMA canaries. Wire checks include every truncated 48-byte request, wrong service/message/command/parameter lengths, pointer overflow, all four blob lengths, descriptor capacity, ES capacity, parameter-set fields, 64-bit PTS/DTS and Sampletype64 permutation. All fixtures are explicitly synthetic HOST fixtures, not recorded native data.

Initial verification recorded 21 passes / 2 failures: the same host test incorrectly checked byte 29 instead of byte 28 for a synthetic 64-bit file offset in both builds. The fixture assertion was corrected; no wire field changed to satisfy it. The final rerun passed. See [validation.json](validation.json).

## Original request wire: positive contract

Only these public ALLLANG binaries supplied the implementation evidence:

| Artifact | SHA-256 | Coordinates |
|---|---|---|
| `system/av-cam.bin` | `90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096` | Raw offsets; KVA = raw + `ffffffc001000000` |
| `usr/lib/libmpr.so` | `4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9` | ELF VA, mapped through PT_LOAD |

The public appFw export table was also consulted; it supplied no additional implemented field. No private/full-system binary was used. [source-pins.json](source-pins.json) binds **22 small raw-byte windows** to full-artifact and window hashes; each accompanying `.asm` includes original instruction bytes. [original-api.json](original-api.json) records exact original exported C++ APIs and ELF PLT relocation names, including `osal_snd_msg` and `osal_set_msg_src`.

MPR `Codec::SendMsgToAvbbc` at M`27c058` allocates and copies **48 bytes**. M`27c120..13c` explicitly sets message source **`0x80c70047`** with `osal_set_msg_src`, then sends to **`0x8055001f`** with `osal_snd_msg`. These are different roles. `NVIDEO_MPR_SID` names the destination accepted by the parser; `NVIDEO_MPR_SOURCE_SID` records the observed source.

M`27be38` (`Codec::CreateMessage`) assigns the following fields. Unassigned bytes remain opaque; the parser does not invent reserved-zero checks for potentially uninitialized original bytes.

| PayloadMpr offset | Width | Meaning proved by original stores |
|---|---|---|
| `02` | u16 | Command ID |
| `08` | u64 | First pointer returned by `memory::GetFixedArea(2, ...)` |
| `10` | u32 | Copied parameter byte count |
| `18`, `19` | u8 each | Primary/secondary codec values, enum meaning left uninterpreted |
| `1a` | u16 | View value |
| `1c`, `1e` | u8 each | Primary/secondary file-format values, enum meaning left uninterpreted |
| `24` | u32 | Message ID |
| `28` | u64 | Second fixed-area pointer; parameter memcpy destination |

The implemented single-codec message ID is **`0x210`**. All parameter lengths must be exact; the mapped parameter address must be nonzero and nonwrapping. The parser never dereferences guest addresses. In command 0, both secondary codec/format header values must be zero, as explicitly assigned at M`280f7c..80`; commands 1–3 retain their existing header acceptance rules.

| Original API | Original site | Command | Parameter bytes |
|---|---|---|---|
| `Codec::EncOpen` | M`280bc8`, construction M`280f5c..9c` | 0 | `0x98` (exactly one unit) |
| `Codec::EncStart` | M`27df88`, construction M`27e0ac..ec` | 1 | `0x80` |
| `Codec::EncIPicture` | M`27c5a4`, construction M`27c5e0..610` | 2 | 4 |
| `Codec::EncStop` | M`27e37c`, construction M`27e4b8..ec` | 3 | `0x10` |

`EncIPicture` copies one u32 from its argument. **This is not proof of a frame owner, sequence or SDS request.** Neither the parser nor the component bridge relabels that word. Multi-codec message `0x1610`, secondary EncOpen forms, multiple EncOpen units, close/other command forms and unknown lengths are rejected. This parser is the original MPR/Avbbc boundary; it is not a recovered Imola hardware command channel.

## Read a coherent EncOpen parameter snapshot

`nvideo_parse_encopen_parameters()` calls the existing request parser, accepts only command 0 with exactly `0x98` parameter bytes, and requires `mapped_base == request.parameter_address`. It consumes the caller's accessible, coherent whole parameter snapshot; it cannot acquire or certify that snapshot's ownership, lifetime or coherence. The caller must keep both inputs stable throughout the call. No snapshot or borrowed pointer is retained.

The [packet-coordinate contract](../native-video-packet-coordinates/README.md) and its unchanged [source pins](../native-video-packet-coordinates/source-pins.json) bind the complete M`280bc8` EncOpen code: `w27=0x98`, `w1=0`, normal `w0=0x210`, parameter count times unit size in `w4`, and the actual copy to V. `request.fixed_area` at wire+`08` is P in the mmap-offset/physical domain; wire+`28` is V in the mapped-user domain. Both remain full u64 values and are **not required to be numerically equal**.

Only these fields are returned from the snapshot:

| Parameter offset | Width | Returned member |
|---|---|---|
| `00`, `08` | u64, u32 | `main_es_base`, `main_es_capacity` |
| `10`, `18` | u64, u32 | `secondary_es_base`, `secondary_es_capacity` |
| `20`, `28` | u64, u16 | `auxiliary_base`, `auxiliary_capacity` (units remain opaque) |
| `30`, `38` | u64, u16 | `video_info_base`, `video_info_count` (96-byte slots) |
| `50` | u64 | `read_control_base`; read index at this base+0 |
| `58` | u64 | `write_control_base`; write index at this independent base+4 |
| `88` | u8 | `selection_byte`, preserved in full, including non-boolean values |

The [shared-binding contract](../native-video-shared-binding/README.md) and its unchanged [source pins](../native-video-shared-binding/source-pins.json) establish the two control bases, slot count and source-declared control extents: `read_control_declared_bytes=0x294`, `write_control_declared_bytes=0x330`. These extents are declarations, not measured allocation capacities. The source [receiver selection](../native-video-pointer-conversion/README.md) tests byte `+88` for nonzero; the parser preserves the byte without claiming a runtime branch. UIF and all other unknown parameter fields are ignored. The whole original `0x98` ABI is not reconstructed, zero-filled or copied from a partial API shape; input bytes are never modified.

The parser checks nonwrapping source-proven byte declarations, including `video_info_count*96` and both declared control extents. Auxiliary units are opaque, so `auxiliary_capacity` is preserved without interpreting it as a byte extent. Zero optional fields are retained. These arithmetic checks do not certify actual mappings, allocations, required buffers or readiness. All addresses are logical values and are never host-dereferenced. The entire output capacity, including its unused tail, must be nonwrapping, accessible and disjoint from both inputs; `out` must be aligned for `struct nvideo_encopen_parameters`. Read-only inputs may overlap each other. Success writes only `sizeof(*out)` bytes. Every failure preserves all output bytes. Invalid spans, exact lengths, alignment or overlap return `NVIDEO_INVALID`; mismatched mapped base or logical overflow returns `NVIDEO_RANGE`; unsupported services, message/command forms or secondary values return `NVIDEO_UNSUPPORTED` under the shared request rules.

The [original producer](../native-video-open-parameter-producer/README.md) explicitly writes byte `88=0` at M`d2d60` on the bounded single-open path; its metadata queue retains the parameter until callback return. This condition selects the zero branch only when that producer supplies the established route. It does not establish a live frame/lease, and the generic snapshot parser retains the complete byte domain.

The `encopen` self-check passes actual parsed ES values into `nvideo_parse_info()` and `nvideo_build_sample64()`, checks the independent read base/write base+4 and full byte `88`, and covers truncation, wrong lengths, secondary/multiple forms, high u64 addresses, optional zeros, logical overflow, output alignment/capacity and unused-tail aliasing with atomic failures. This is a synthetic source-primitive check, with no native allocation, publication or completion. `nvideo_native_request()` recognizes the new valid request through the same parser and still returns `NVIDEO_UNSUPPORTED`, gap mask **63**.

## Original encoded descriptor and Sampletype64 members

K`1609c8..161348` logs each original VideoInfo field with its source load. M`2820fc` consumes entries at **`0x60` stride** and uses the ES/PI indices and memory barriers. `nvideo_parse_info()` recognizes this exact 96-byte entry and requires a nonempty AU entirely inside a caller-provided contiguous ES lease. A ring-wrapped AU is not silently linearized. The parsed AU address is a **u64 address**, not an invented `{type, handle, offset}` SDS.

| VideoInfo offset | Width | Source-proved member |
|---|---|---|
| `00` | u8 | infoType |
| `01` bits 0/1/2 | flags | VPS/SPS/PPS change |
| `02`, `03` bit 0 | u8 / bit | padingAreaLength / videoInfoUnit |
| `08` | u64 | auStartAddr |
| `10` | u32 | auDataLength |
| `18`, `20` | u64 each | PTS64 / DTS64 |
| `28`, `2a`, `2b` | u16, u8, u8 | Total VPS size, count, ID |
| `2c`, `2e`, `2f` | u16, u8, u8 | Total SPS size, count, ID |
| `30`, `32`, `33` | u16, u8, u8 | Total PPS size, count, ID |

These parameter-set sizes/counts/IDs do **not** prove the byte positions of SPS/PPS, a decoder configuration record, or native Annex-B versus length-prefixed framing. Native timestamp units are preserved without assuming the component engine's `1/fps` timebase.

M`1184d0` (`XavcsMovieWriter::SetVideoSampleInfo`) admits sample types **0, 1, 2, 3, 9** and maps type 0 to the synchronization boolean. It does not treat every metadata/control entry as a sample. `nvideo_build_sample64()` implements only the following observed member stores before M`118594` calls M`222dc0`:

| Sampletype64 member offset | Original source |
|---|---|
| `00`, `04`, `08`, `0c` | PTS low, DTS low, PTS high, DTS high |
| `10` | AU length u32 |
| `18` | Caller file offset u64 |
| `20` | `infoType == 0` |
| `21` | Last-sample boolean |

The API writes a deterministic **40-byte host scratch image** containing these proved members and zeroes unassigned bytes. **Original total `sizeof` is not proved by these loads/stores.** The tail is not assigned new semantic fields, and the scratch buffer must not be passed to an original writer as evidence that its complete ABI has been recovered. This builder never encodes, muxes, writes files, advances a native ring or completes a guest request.

## Blob ownership correction

K`21c348` submits four blobs with copied lengths **`0x40`, `0x1c0`, `0x300`, `0x80`** through K`216f1c` and K`2291b4`. The pool is at object+`1038`; each 16-byte slot contains base at slot+`10` and u32 capacity at slot+`18` relative to the indexed pool header. K`2291b4` copies only the requested bytes, but returns `{base:u64, capacity:u32}` retaining the **full allocation capacity**.

`nvideo_blob_copy()` implements this bounded copy for a caller-resolved 16-byte descriptor and matching mapped base. It rejects unsupported copy lengths, too-small or unmapped capacity, wrong base and wrapping ranges. It neither traverses arbitrary guest trees nor assumes that the capacity equals the blob's copied length.

**Correction to the earlier imaging report's §15 interpretation:** K`2223dc` calls K`218c68` with the tag. K`218cc8` passes the found node+`20` to K`2290d8`, which appends its `{base, capacity}` to the **free pool** and increments the available count, capped at `0x2a8`; K`218d44..50` then removes the tagged node. This is **lease return/removal**, not a pixel/blob read. This directory pins those original bytes and does not edit the other report. Returning a blob must not be used as evidence that its pixels were encoded.

## Component bridge and integration boundary

Create a binding around the caller's existing `video_engine_stream`, provide acquire/release/write/read/publish operations, then call `nvideo_component_begin`, `nvideo_component_frame`, and `nvideo_component_finish`. The caller owns and serializes the stream and all callbacks. No native request dispatches into these functions.

Each component frame supplies a separate caller-ledger key `{owner, sequence, SDS}`. The binding checks owner, strictly increasing sequence and exact acquired key identity, and accepts only explicitly typed **HOST RGB888**. This ledger is not asserted to match the original four-byte `EncIPicture` request. Unknown/native YC layouts fail before the engine consumes pixels.

On the actual engine packet callback the bridge validates destination bounds and timestamps, writes the borrowed packet once, and compares every output byte using readback in bounded 4096-byte chunks. It retains no packet bytes, raw-frame array or upstream pixel pointer. Successful acquire always has exactly one release, even on validation/codec/DMA failure. Publication is delayed until release succeeds. A failure aborts without publish/retry; exact callback errors remain available through `nvideo_component_error`, and engine counters/errors through the caller-owned stream snapshot. DMA may retain partial bytes after failure, but no completion is published. Cancel permits explicit restart. Mutating callback reentry is rejected and destroy during a callback is ignored.

The component completion carries actual packet address, byte count, PTS/DTS, duration, keyframe and ledger identity. Its timestamps remain in the engine's `1/fps` units and its bytes remain actual **Annex-B**. It does not carry invented Sony SPS/PPS metadata, native source pixel names, MPR ring state or a native completion SID. There is no host MP4 copy path.

## Evidence, findings and remaining blockers

| Evidence | Finding | Integration consequence |
|---|---|---|
| M`27be38`, `27c058`, `27df88`, `27c5a4`, `27e37c`; original API relocations; packet-coordinate M`280bc8` pin and shared-binding pins | F1: exact original MPR request header, destination/source, four command lengths and selected EncOpen declarations | Strict parsing available; unknown forms fail; native execution stays unsupported |
| K`1609c8`; M`2820fc`, `1184d0`, `222dc0` | F2: native AU address/length/time and parameter-set metadata; sample member permutation | Existing descriptors can be parsed within an independently owned ES lease |
| K`216f1c`, `2291b4`, `218c68`, `2290d8` | F3: bounded blob copy and actual return/removal direction | Do not mistake free-pool return for pixel consumption |
| C11/ASAN/UBSAN checks and independent FFmpeg pipe decode | F4: actual caller source → existing H.264 engine → bounded write/readback → release → component completion | Component path usable without a new encoder; native success gate stays closed |

P1, `path_type=callflow`: original MPR APIs → 48-byte PayloadMpr → Avbbc service; unknown native input mapping/channel → Imola encoder; original VideoInfo → native MPR sample member mapping → original writer. The two unknown native links are not replaced with host output.

P2, `path_type=callflow`: caller-owned HOST RGB lease → exact ledger match → existing stream feed → actual packet → bounded DMA write/readback → exact source release → component publication. This is the path exercised by the decode test.

K`138720` checks the local RMC receive header `0x2103`; its source-pinned jump table maps `0x110` to `VIDEO_ENC_START_COMP` and `0x113` to `VIDEO_ENC_STOP_COMP`. The exact external VIDEOENC request SID, complete request/reply lengths, result status, frame lease and completion payload are not proved. The code therefore does not export a guessed native RMC response builder.

| Mandatory gap bit | Why native execution remains unsupported |
|---|---|
| `FRAME_SDS` (1) | No source-proved native frame owner/sequence/SDS request binding; `EncIPicture` is only a 4-byte trigger |
| `YC_LAYOUT` (2) | Legal tuples/InputFormat 4/5/d/e and pitches do not establish component order, planes or CMOS packing; settings producer excludes tuple0 on that path |
| `BITSTREAM_FRAMING` (4) | Native Annex-B versus length prefixes is unresolved |
| `PARAMETER_SETS` (8) | Sizes/counts are proved; actual SPS/PPS byte ranges/configuration construction remain unresolved |
| `COMPLETION_LEASE` (16) | RMC/MMIO channel, status/ownership transitions and complete completion payload remain unresolved |
| `MPR_PUBLICATION` (32) | Native ES/PI write-index publication, read-index retirement and original MPR/Fsys file lifecycle remain unresolved |

Initial implementation timeline: read project/engine/pixel contracts → read public exports and focused raw instruction windows → correct blob return direction → publish stable header → implement wire readers/member builder and existing-engine bridge → run checks → correct one synthetic test-byte assertion → freeze source pins and rerun checks. No VM or full-root regression was run; no hardware, physical SD, network, private/full-system source, firmware patch, or existing code edit was used. Formal report flavor: null, ordinary firmware reverse engineering; no vulnerability/IOC claim.
