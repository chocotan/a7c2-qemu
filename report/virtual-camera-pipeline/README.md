# Executable virtual camera component pipeline

`camera-pipeline.c` composes the existing optical frame owner, pixel-scored AF,
JPEG hardware core, streaming libx264 encoder, packet memory sink and MP4 mux in
one controller. Actual encoders consume the rendered frame lease. This is a host
component result; original camera requests, native YC packing, guest IRQ binding
and firmware media storage remain outside this controller.

```json
{
  "component_pipeline_verified": true,
  "capture_verified": false,
  "guestSDK": false,
  "originalMPRFsys": false
}
```

These are report fields. They are never inserted into image pixels, JPEGs,
compressed packets or MP4 metadata.

The assignment authorizes only these new files. No existing component/header,
QEMU build, VM, private asset, network, real camera, physical disk or SD was used
or changed. Parent integration retains responsibility for original request
adapters and the joint VM batch. CP 0/4 and native YC remain open there.

Run from this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider test_pipeline.py -q
```

The verified result is **28 passed**: 11 contract groups in normal and combined
ASan/UBSan builds, plus six complete media runs (2, 4 and 6 frames in each build).
Compilation uses C11, `-Wall -Wextra -Werror -pedantic`; sanitizer runs enable
leak detection and stop on the first error. Prerequisites are `cc`, `pkg-config`,
Python/pytest/Pillow, ffmpeg/ffprobe, libjpeg, libavcodec with libx264,
libavformat, libavutil, libswscale and libm. No new dependency was installed.
Observed versions: GCC 16.2.1, libjpeg 3.2.0, libavcodec/libavformat 63.1.102,
libavutil 61.1.102, libswscale 10.1.102 and ffmpeg/ffprobe n9.0.2.

All media travels through caller-owned C memory, stdout pipes, Python `BytesIO`
and decoder pipes. Tests write build executables to pytest temporary storage;
no test media is written to disk. The C test emits a length-delimited binary
wire plus separate JSON evidence records. Use the Python runner to consume it.

The public [header](camera-pipeline.h) is stable. It reuses the exact types from
[the optical owner](../virtual-optical-frame-owner/optical-frame-owner.h),
[JPEG hardware](../virtual-jpeg-hardware/jpeg-hardware.h) and
[video engine](../virtual-video-engine/video-engine.h); their functions and codec
implementations are linked, never copied. Production builds compile
`camera-pipeline.c` with `virtual-optics/optics.c`,
`virtual-optical-frame-owner/optical-frame-owner.c`,
`virtual-jpeg-hardware/jpeg-hardware.c`,
`virtual-jpeg-hardware/jpeg-hardware-codec.c`, `virtual-jpeg-sos/jpeg-sos.c` and
`virtual-video-engine/video-engine.c`, using the pkg-config libraries above and
`-lm`. The test runner contains that complete build recipe. Its adversarial C
harness includes the controller implementation for private callback checks;
the runner separately checks the production translation unit.

The caller creates one opaque controller with a live RGB frame pool and optional
IRQ/packet observers, then configures an `optical_frame_config`. The pool also
serves as AF scratch while no lease is active. `vcam_autofocus` scores actual
rendered pixels using the existing coarse/refinement scan; it never reads scene
depth to select focus. Near/far ROIs recover the 1 m and 4 m targets. Flat exposure
returns `OPTICAL_FRAME_NO_CONTRAST`, leaving focus and AF result unchanged.

For stills, call `vcam_capture_still` with a caller-proved typed `vjpeg_coding`,
a bounded output buffer and a `vcam_still_result`. Zero quantizers, unknown
contracts and dimension mismatches fail before frame consumption and assert no
completion IRQ. Test quantizers are explicitly generated test fixtures; the
controller never derives a quality setting or fabricates original guest tables.
The native header reconstruction is used only to decode this explicit component
RGB job; it is not evidence that a guest supplied the contract.

The actual flow is configure/optional AF → acquire → render → optical borrowed
consumer → `vjpeg_hw_prepare/execute` → exact destination readback → component
IRQ 29 → outer retirement. The controller prepares the job before entering the
borrowed consumer, then executes inside it. Device `probe/read/write/acquire/
release/irq` callbacks carry the exact lease, live pool, stride, output and
capacity. The fixed component address space exposes only those two disjoint
allocations, with canonical object IDs 1 and 2; alias/overlap and out-of-range
accesses are rejected. An acquire requires the exact generation, owner, buffer
and capacity and an RGB888 borrowed view in `OPTICAL_FRAME_READING` state.

The hardware writes a real `FF DA` SOS/entropy/EOI suffix. The output buffer has
SOI plus the exact source-order combined DQT, combined DHT and SOF before it.
`vcam_still_result` returns actual prefix/suffix/full lengths and individual
CRC32 values, frame generation and source pixel hash. No APP/EXIF identity or
secret metadata is guessed. The core compares every written suffix byte on
readback. Prefix validation and incremental suffix CRC precede the forwarded
completion IRQ. IRQ observers can inspect the readback evidence while the
borrowed lease is still live. Core release only schedules retirement; the outer
controller retires after `optical_frame_consumer_read` returns and verifies the
source hash again. A settled snapshot has `lease_live == 0` and
`jpeg_release_pending == 0`.

For video, `vcam_record_begin` accepts bounded caller-owned packet bytes, packet
index and config buffers. `vcam_record_frame` acquires/renders/borrows exactly one
frame, feeds the existing synchronous stream, copies the real borrowed packet
before feed returns and retires afterward. No raw frame pointer survives feed.
Every accepted session frame has `pts == dts == frame_index`, duration 1 and
time base `1/fps`. Optical generations continue across stills and record sessions.
Focus, aperture, shutter, ISO and stride can change between record frames; record
width/height stay fixed. All mutations during an active borrowed callback return
`VCAM_BUSY`, except snapshot and deferred cancel. Still/record switching while a
record is active is rejected.

The packet sink bounds each copy, verifies the bytes and publishes its index
only after any optional consumer returns zero. It extracts actual Annex-B SPS
and PPS bytes from the first published access unit into the supplied config
buffer. A failed consumer preserves its exact nonzero error, consumed/received
counts and any partial sink effects, but publishes no success for that packet.
The stream faults without retry. Data/config integrity checks also catch caller
mutation before mux. `vcam_record_end` drains, sends EOS, finishes, then invokes
`video_engine_mux_mp4` with these real published bytes, indices and SPS/PPS.
The existing bounded seekable memory AVIO writes the actual MP4 header, packets
and trailer. No Fsys facade or independently generated substitute clip exists.

`record_end(NULL, 0, &result)` returns `VCAM_BOUNDS` and exact `result.required`.
It retains `VCAM_DRAINED`; a larger buffer retries mux without encoding again.
An exact output capacity succeeds; a one-byte-short buffer remains untouched.
An empty record cannot finalize. Cancel abandons future work, preserves errors
and counters and allows a new session. Cancel from a synchronous observer defers
until its borrowed callback returns; a packet/IRQ already published remains
published. A stale lease cannot be retired or destroyed; the failure retains the
live token for diagnosis. External serialization is required for all calls;
there are no internal locks and no asynchronous cancellation contract.

Snapshot counts deliberately describe distinct stages:

| Counter | Evidence |
| --- | --- |
| `rendered` | Owner completed an acquisition render; AF trial renders excluded |
| `source_read` | Owner invoked a hash-verified borrowed consumer, even if it failed |
| `encoder_consumed` | JPEG attempted actual lease encoding; video codec accepted frame |
| `encoded` | JPEG produced a complete suffix fitting destination; video received actual compressed packet, including rejected sink packet |
| `output_readback` | JPEG completed the core byte comparison before forwarded IRQ; video sink copied/verified a complete packet, even if an additional consumer then rejected it |
| `retired` | Owner accepted the exact outer retirement token |

Lifetime counts remain independent of per-session video counters. Raw source
copies are not called AP/native consumption. Stage snapshots retain actual
optical, JPEG and video error codes, sink errors, lengths and readback CRC.
Faulted record operations remain blocked until cancel; rejected follow-up calls
do not replace the root fault. Still errors preserve the JPEG core snapshot
until an explicit subsequent still attempt resets its FIFO/events.

Evidence → Finding → Path:

| Evidence | Reproduction / observation | Finding and call path |
| --- | --- | --- |
| E-01 | `test_controller_contracts`, both builds: lifecycle, callback map, stale token, AF, JPEG errors/cancel, sink failures/capacities, cancellation, mutation and mux groups | F-01 validated: exact lease/capacity ownership and deferred retirement. P-01: configure/AF → owner acquire/render → borrowed encoder → return → retire. |
| E-02 | `test_complete_pipeline_products_consumed_in_memory`, 2/4/6 frames in both builds: Pillow decodes two real 128×64 JPEGs, checks source quantizers/Huffman profile/marker order/SOS/lengths/CRCs and compares decoded pixels to padded-stride RGB | F-02 validated: actual hardware JPEG output consumes the provided optical pixels. P-02: caller coding → hardware callbacks → verified SOS output → source prefix reconstruction → independent JPEG decode. |
| E-03 | Same complete test: ffmpeg independently decodes H.264 and MP4 to identical RGB bytes; ffprobe validates H.264/YUV420P dimensions, frame counts, fixed PTS/DTS/durations and MP4 duration | F-03 validated: real stream packets and actual extracted SPS/PPS survive memory mux without substitution. P-03: owner RGB → libx264 → synchronous packet sink → EOS → memory MP4 → decoder. |

The full reproduction command is above; raw result was `28 passed in 4.00s`.
Evidence is command-derived (`content_hash`/`artifact_path`: n/a); no persistent
media artifact or private data is needed. Independent marker/CRC/pixel/decode
checks support the implementation assertions. Per media run the expected final
stage counts are `count + 2` for all six stages and exactly two JPEG assertions.
Source generations are 1..`count + 2`; video timestamps are 0..`count - 1`.
Each row has 11 untouched padding bytes and guarded buffer ends. Retired active
pixels are overwritten with `0xCC` before the next frame and before final mux;
independent decoding proves output does not depend on a retained raw pointer.

The strengthened cancellation test initially exposed that an ARMED JPEG job was
not cancelled by an observer request. The controller now cancels ARMED and
RUNNING states while still deferring optical retirement. Both sanitizer and
normal regressions pass with the corrected behavior.

Component limits are inherited video bounds (1920×1080, up to 120 fps, 600 frames,
64 MiB packet bytes) and the caller's explicit pool/output capacities. MP4 uses
fixed-rate contiguous timestamps; irregular-duration recording is outside this
small controller even though the underlying stream can represent it. JPEG
encoding uses the existing source-header-422 profile, not unknown native YC.
The optical scene is the existing bounded synthetic two-plane renderer; native
padding, sensor/lens calibration, guest lease provenance, CP state transitions,
guest SDK and original MPR/Fsys writes are unverified. No native capture claim
follows from successful component media decode.
