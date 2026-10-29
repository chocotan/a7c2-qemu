# Streaming virtual H.264 video component

Host C11 component that consumes actual RGB888 frames incrementally with installed
`libswscale` and `libavcodec/libx264`. Each accepted feed copies/converts the source
before returning and publishes real compressed Annex-B access units through a
bounded synchronous callback. The existing one-shot clip API now composes this
same streaming core; a separate component mux produces video-only MP4 in memory.
The encoder launches no subprocesses and creates no files.

**Component evidence only:** guest AP/SDK consumption, native Sony AVCC buffers,
codec DMA/IRQ, MPR/Fsys recording and firmware capture/storage remain unproved.
The current CP3003 provider gate remains **blocked at 0/4**. No VM, hardware,
physical SD, private/full-system dump, network or runtime integration file was
used or changed by this worker. The parent owns the single joint integration
selftest/fix/retest and end-to-end VM.

## Run the checks

From this directory, using the already installed C compiler, pytest, FFmpeg
headers/libraries, `ffmpeg` and `ffprobe`:

```sh
pkg-config --modversion libavcodec libavformat libavutil libswscale
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider test_video_engine.py -q
```

Verified installed versions: libavcodec **63.1.102**, libavformat **63.1.102**,
libavutil **61.1.102**, libswscale **10.1.102**. Only the installed software
`libx264` encoder is selected. Missing it returns `AVERROR_ENCODER_NOT_FOUND`;
there is no hardware or CLI fallback and no added dependency.

The suite has **22 passing pytest cases**: all **10 original cases**, plus
**12 streaming cases**. It compiles the original **6 C self-check groups**, new
**8 streaming C self-check groups**, and the paced optical-owner caller in
normal and ASAN/UBSAN builds. Every build uses
`-std=c11 -Wall -Wextra -Werror -pedantic`. Media remains in memory or subprocess
stdin/stdout pipes; only compiled binaries/shared libraries use pytest's temp
directory. ffmpeg/ffprobe are independent test validators, never the backend.

Files are [video-engine.h](video-engine.h), [video-engine.c](video-engine.c),
[test-video-engine.c](test-video-engine.c),
[test-video-stream.c](test-video-stream.c),
[test_video_engine.py](test_video_engine.py),
[example-optical-stream.c](example-optical-stream.c) and this report.

## Consume a live frame without retaining its lease

The stable [header](video-engine.h) exposes an opaque
`struct video_engine_stream`:

1. `video_engine_stream_create()` allocates a stream in `IDLE`; NULL means host
   allocation failure. `video_engine_stream_begin()` opens the explicit virtual
   RGB8 format and installed encoder with dimensions, fps, maximum delivered
   packet bytes, callback and callback context.
2. Call `video_engine_stream_feed_rgb888(stream, &rgb, pts, duration)` while the
   upstream source is valid. It copies visible rows into padded owned workspace,
   converts to owned YUV and calls `avcodec_send_frame`. Only an actual codec
   acceptance increments `frames_consumed`; success cannot precede conversion
   and acceptance. Input is never modified or retained, including on failure.
3. Feed immediately drains actual compressed output. With the selected
   zerolatency profile, the tested callback runs once per accepted frame before
   feed returns. Callback `data` and its descriptor are immutable borrowed
   objects **valid only during that callback**. Copy everything needed later;
   retaining these pointers is invalid.
4. After feed returns, retire the upstream lease and reuse its RGB buffer.
   `video_engine_stream_drain()` receives available packets without ending the
   stream. `video_engine_stream_finish()` actually sends EOS and drains to EOF;
   repeated successful finish is harmless. `video_engine_stream_cancel()` frees
   codec workspace without EOS or implied publication. Destroy releases all
   remaining resources; `destroy(NULL)` is harmless.

[example-optical-stream.c](example-optical-stream.c) is a compiled caller, using
only the optical owner's public API. Its `feed_borrowed()` consumer constructs a
stack `video_engine_rgb` from the current `optical_frame_view`, calls feed and
returns without retaining either borrowed pointer. The caller retires the exact
lease, overwrites that one producer buffer, changes optics parameters, and
renders the next frame. It never collects raw frames for a later clip encode.
Its sink copies packet bytes during the callback. The caller is paced at 25 fps
and runs with either 2 or 6 genuinely changing rendered RGB frames.

For the test oracle, the example emits length-delimited source RGB and actual
H.264 records to a pipe. Its final `DONE` record contains actual consumed,
received, published and retired counts. This test wire is not a media container,
Sony ABI or firmware recording path. The Python tests parse it, count/decode with
ffprobe/ffmpeg, and correlate decoded RGB against each source. No JPEG/MP4 disk
file is created.

The example can be built directly from this directory:

```sh
cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 \
  video-engine.c example-optical-stream.c \
  ../virtual-optical-frame-owner/optical-frame-owner.c \
  ../virtual-optics/optics.c -o /tmp/virtual-video-optical-example \
  $(pkg-config --cflags --libs libavcodec libavformat libavutil libswscale) -lm
/tmp/virtual-video-optical-example 6 | wc -c
rm -f /tmp/virtual-video-optical-example
```

The pytest command above performs the stronger independent decode checks.
Production code needs only `video-engine.c` and the four libraries; the optical
example additionally links the sibling optical owner and optics sources.

## Handle packet bounds, sink failures and state

`max_packet_bytes` bounds **each delivered access unit**, not the recording's
lifetime bytes. The core retains one packet, one RGB frame and bounded
YUV/codec/scaler workspace. It has no full-clip raw-frame array or compressed
packet backlog. libav may allocate a packet before its size can be checked;
the callback cap is not a custom allocator or a real-time memory quota.

Only zero from the sink means the entire packet was consumed/copied. A nonzero
return means this packet was **not published**. The core saves that exact return
as `sink_error`, unreferences the rejected packet and enters sticky `FAULT` with
`VIDEO_ENGINE_SINK_ERROR`. It never retries that callback or accepts subsequent
frames. This is a clear stream abort: a sink with partial external side effects
must clean those up itself. It must not return zero for partial work.

An actual packet exceeding the delivery bound similarly faults with
`VIDEO_ENGINE_OUTPUT_TOO_SMALL` before any callback. Codec failures preserve the
original negative libav error, including send-side EAGAIN, in `codec_error`.
ENOMEM maps to `VIDEO_ENGINE_NO_MEMORY`; EOVERFLOW maps to
`VIDEO_ENGINE_SIZE_OVERFLOW`; other codec failures map to
`VIDEO_ENGINE_CODEC_ERROR`. Active receive-side EAGAIN is the ordinary
no-available-output condition, without changing counters or inventing output.

| Current state | Allowed lifecycle operations | Evidence retained |
| --- | --- | --- |
| `IDLE` | begin, cancel, destroy, snapshot | Zero counters |
| `ACTIVE` | feed, drain, finish, cancel, destroy, snapshot | Actual per-call progress |
| `FINISHED` | repeat finish, begin, cancel, destroy, snapshot | Final counters until begin |
| `FAULT` | cancel, destroy, snapshot; feed/drain/finish return the sticky fault | Exact error and partial consumed/published counters |
| `CANCELLED` | begin, repeat cancel, destroy, snapshot | Previous counters/error until begin |

Beginning an active/faulted stream is rejected. Invalid arguments/state do not
mutate state. Cancel is required before beginning again after a fault; begin
resets evidence for the new session. Feed/drain on a stopped stream return
`VIDEO_ENGINE_INVALID_STATE`. Calls are externally serialized: no mutexes,
threads or asynchronous framework are present. A sink may snapshot the stream,
which shows received but not-yet-published callback progress. Mutating reentry
is rejected, and destroy from its own callback is ignored.

Snapshot fields have distinct meanings:

| Field | Counts only |
| --- | --- |
| `frames_consumed` | Successful codec frame acceptances after conversion |
| `packets_received` | Actual successful codec packet receives, including rejected packets |
| `packets_published` | Complete callback returns of zero |
| `bytes_published` | Bytes of those published packets |
| `packets_flushed` | Actual packets received after accepted EOS |

A frame can therefore be consumed while its output fails to publish. A failed
callback, drain without output, cancellation or lease retirement creates no
fake successful packet count. Counters are checked against overflow.

## Supply timestamps and understand the encoder model

Input/output timestamps use time base **1/fps**. PTS must be nonnegative,
duration positive, and `pts+duration` must fit `int64_t`. Each next PTS must be
at least the prior frame's end; gaps and varying durations are supported,
overlap/regression is rejected before consumption. Received codec PTS/DTS are
validated against the pending accepted frame, and supplied duration is checked
against codec duration when present. Output preserves `pts=dts` and duration;
no B-frame reorder or fabricated timestamp progression is introduced.

The known libx264 zerolatency model permits **one pending accepted frame**. If
its packet is not yet available, another feed returns `INVALID_STATE` without
accepting a new frame; call drain or finish. This bounds pending metadata and
needs a bounded queue before supporting a delayed/reordering encoder. There is
no 600-frame lifetime cap for streaming: tests exercise 601 feeds in one session.

The shared core uses constrained-baseline 8-bit YUV420P, CRF 18, veryfast,
zerolatency, one software thread, no B-frames, and GOP size `2*fps`. It explicitly
converts full-range RGB into limited-range BT.709. SPS/PPS are repeated at
keyframes and available in the first actual access unit. These are virtual
component settings, not recovered Sony codec behavior or a native AVCC layout.

Raw Annex-B does not store external container PTS/duration. Irregular timestamps
are checked at the actual packet callback; independent raw decode verifies
content/count. For fixed-rate streaming, tests extract actual SPS/PPS from the
first packet and use the existing memory mux; ffprobe independently verifies
packet PTS/DTS/duration and decoded frame counts. The fixed-rate MP4 helper
intentionally still rejects irregular metadata.

## Keep the existing one-shot and memory mux contracts

`video_engine_encode_rgb888()` keeps its public interface. It validates every
source/output span, begins the streaming core, feeds each source with
`pts=index, duration=1`, collects copied packets through its sink, and finishes.
Only this convenience wrapper retains a bounded compressed clip to preserve
transactional output and exact capacity queries. It retains no upstream RGB
pointer beyond the synchronous call.

A `NULL/0` output/config/metadata query performs the real encode and returns
`OUTPUT_TOO_SMALL` with exact `required`, `packets_required` and
`config_required`. All encoding failures leave caller output buffers untouched
and `used/packet_count/config_used` zero. Codec failures preserve actual
consumed/flush counts and clear incomplete requirements. All 10 original tests,
including exact/one-byte-short sizes, metadata/config capacities, immutable
input and negative codec-return injections, still pass.

`video_engine_mux_mp4()` remains a separate video-only component helper using
custom bounded seekable memory AVIO. It requires exact contiguous Annex-B packet
spans, SPS/PPS config, `pts=dts=index`, duration 1, a first keyframe and matching
format. A counting pass determines exact container high-water bytes, then a
writing pass writes header, packets and trailer. Zero/short capacity returns
`OUTPUT_TOO_SMALL` with `used=0`; a writing-pass I/O failure can leave partial
invalid output. No original MPR/Fsys function is called.

| Policy | Bound |
| --- | --- |
| Dimensions | Even width 2..1920 and height 2..1080 |
| Frame rate | Integer 1..120 fps, explicitly supplied |
| Streaming packet delivery | Caller bound 1..64 MiB per access unit |
| Streaming frame count | Checked 64-bit counters; no clip retention or 600-frame lifetime cap |
| One-shot clip | 1..600 frames; at most 64 MiB retained elementary bytes |
| Memory MP4 | At most 64 MiB high-water bytes; config input at most 1 MiB |
| RGB source | `stride >= width*3`; `size >= (height-1)*stride+width*3` |

Nonzero NULL spans, invalid dimensions/fps/stride, short input, wrapping size or
address arithmetic, and forbidden span overlap are rejected. Streaming RGB
cannot alias its opaque stream storage. One-shot output/config/metadata cannot
overlap one another, descriptors or source spans. Raw row padding is ignored;
the final row needs no trailing padding. All declared pointers must still name
real live objects; arithmetic validation cannot prove that an arbitrary pointer
is mapped. These are host policy limits, not Sony hardware limits.

## Evidence, findings and remaining integration path

| Evidence | Verified finding | Remaining path |
| --- | --- | --- |
| 22 passing pytest cases; strict normal and ASAN/UBSAN C builds | Existing contracts preserved and new allocations/lifecycle/fault cleanup checked | Parent's joint batch validation remains authoritative for coupling |
| Streaming 2/6-frame ffmpeg decode with input overwritten after each feed; exact one-shot bitstream comparison | Real compressed packets consume each supplied frame, not a retained RGB pointer or stand-in clip | Connect actual recording-owned frames to this component |
| Paced optical-owner 2/6-frame calls in normal/sanitized builds; retire and reuse the same buffer; no frame-copy API | Borrowed consumer can synchronously feed encoding before lease retirement; actual published counts progress per feed | Preserve upstream lease/fault handling in parent adapter |
| Actual streamed SPS/PPS/packets muxed only in memory, with ffprobe timestamps/count and matching ffmpeg decodes | Fixed-rate stream metadata reaches a real component container correctly | Original MPR/Fsys must consume encoded data through its own path |
| Irregular PTS/duration, near-INT64 boundary, immediate drain, empty/repeated finish, 601 feeds | Timestamp and lifecycle limits fail closed without clip accumulation | Other codecs/reordering need additional explicit contracts |
| First/second sink failure, packet exact/short cap, wrapped open/convert/send/receive failures; delayed receive and real EOS receive | Counters distinguish codec consumption from publication; no retry duplicates; real flush counts can be 0 or 1 | No native codec completion, DMA/IRQ or AP-ready state follows automatically |

The delivery changes only files in this directory. It does not mark AP/SDK,
guest DMA/IRQ, MPR/Fsys or firmware capture complete, and does not run a separate
per-feature VM or runtime review.
