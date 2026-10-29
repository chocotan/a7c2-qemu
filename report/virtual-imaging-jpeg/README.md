# Virtual optics → bounded JPEG component integration

`Capture_verified=false`. This host-only test connects the existing optical
renderer to the existing bounded JPEG engine, then fully decodes the resulting
bytes using installed Pillow. It makes a virtual lens/CMOS-to-codec component
path available for future integration; it does not establish firmware capture.

## Run the four tests

From `report/2026-10-17-qemu-native-camera/`:

```bash
python3 -B -m pytest -p no:cacheprovider report/virtual-imaging-jpeg/test_integration.py -q -s
```

Requires an installed host C11 compiler (`CC`, default `cc`), `pkg-config`
`libjpeg`, libm, ASan/UBSan, Python, pytest and Pillow. No dependency installation
is performed. Compilation uses `-Wall -Wextra -Werror -pedantic` and references
[optics.c](../virtual-optics/optics.c), [optics.h](../virtual-optics/optics.h),
[jpeg-engine.c](../virtual-jpeg-engine/jpeg-engine.c) and
[jpeg-engine.h](../virtual-jpeg-engine/jpeg-engine.h) in place; their code is
neither copied nor modified.

The fixture builds normal and ASan/UBSan executables in pytest's host temporary
directory. It launches four process batches concurrently (two of each build),
with a 30-second limit per batch. Each batch renders four frames and passes
RGB/JPEG bytes through a captured memory pipe to Python. All 16 JPEGs are fully
decoded from `BytesIO`. There are no image or video output files. Temporary
executables are host test artifacts, not camera photos. Process concurrency
does not establish same-process threaded API safety.

## Actual pixel connection

[`integration.c`](integration.c) calls `optics_render` with caller-owned storage
of `stride * height` bytes. The renderer already produces quantized **linear
RGB888**, interleaved R/G/B bytes in increasing row order. It writes only
`width * 3` bytes per row; the test chooses `stride = width * 3 + 13` and checks
that padding stays `0xa5`, including the final row. The same pointer, extent,
width, height and stride go directly to `jpeg_engine_encode_rgb888` at quality
95. No float conversion, repacking, scaling or gamma transform is needed or
performed. A separate snapshot is only used to detect input mutation.

The engine is a host libjpeg encoder, not the original Sony encoder. Its default
baseline JPEG uses libjpeg's internal RGB-to-YCbCr/4:2:0 processing; that says
nothing about Sony YC layouts. Pillow returns RGB bytes, which are compared
against the renderer's active bytes with lossy tolerances (mean absolute channel
error below 3, maximum at most 24). This is a byte-domain component check, not
colorimetric or sensor calibration.

The explicit scene is the renderer's existing fixed two-depth fixture: left
half a 1 m checker target, right half a 4 m checker target, fixed 35 mm focal
length and 36 mm sensor-width assumption. The API has no external scene-input
parameter. The test uses the existing model and fixture rather than adding a
second scene generator or optical implementation.

## Evidence and results

Verified with installed libjpeg **3.2.0**, Pillow **12.3.0** and pytest **9.1.1**:
`4 passed` with strict warnings and ASan/UBSan/leak checks enabled.

| Test evidence | Finding | Component path exercised |
| --- | --- | --- |
| `test_aperture_light_ratio_survives_jpeg` | F4→F8 mean red ratio: raw **0.253521**, decoded **0.242445**. Raw is within 0.02 of the model's 1/4 exposure contract; decoded is within 0.035 of raw. | Existing optical exposure → RGB → JPEG → Pillow |
| `test_near_far_focus_exchange_survives_jpeg` | At 1 m/4 m focus, near-target raw gradients **12.75/0.25**, decoded **12.818657/0.3125**; far-target values reverse. Each decoded gradient stays within 1.5 of its raw counterpart, and focused contrast exceeds twice defocused contrast. | Existing depth/focus blur → actual pixels → lossy decode |
| `test_odd_size_padded_frame_decodes` | **1025×65**, stride **3088**, decodes at the original dimensions and matches active RGB bytes within the same lossy tolerances. | Odd dimensions and ignored row padding |
| `test_parallel_batches_keep_bounds_and_ownership` | Four disjoint process batches agree byte-for-byte; every child checks render rejection atomicity, ownership and output bounds. | Normal and sanitized host component calls |

The first three frames are 1024×64, stride 3085. Baseline parameters are F4,
focus 1 m, shutter 0.001 s and ISO 100, matching `test_optics.c`. The aperture
case changes only F4→F8; the focus case changes only 1 m→4 m. Gradients use the
original model test's interior regions, avoiding the depth boundary. Checks
consume nonuniform pixels and decoded brightness/derivatives, not golden hashes.

Each frame also checks that one-byte-short optical capacity leaves destination,
metadata and completed-frame count unchanged; successful rendering increments
the count once and preserves the requested frame number. The JPEG checks cover
capacities 0, 31, exact required size minus one, and exact required size. Failures
return `OUTPUT_TOO_SMALL` with `used=0`; an invalid partial stream is allowed
inside the declared destination. Prefix/suffix canaries, bytes beyond the
output limit, row padding and the entire original input are checked. Every
batch holds disjoint buffers until synchronous encoding returns. Neither API
has a firmware lease protocol, so none is invented or certified here.

## Remaining integration boundary

Original AP/guest consumption, the firmware frame SDK and DMA contracts, Sony
pixel/hardware headers, the hardware header/SOS completion protocol, IRQ delivery
and Fsys storage are still missing from this component path. Standard JPEG SOS
bytes produced by libjpeg do not establish that hardware protocol. No runtime,
VM, frozen assets, private dump, hardware, network or physical SD is used.

A future firmware adapter must demonstrate actual frame consumption and the
completion/storage chain before `Capture_verified` can change. These host
results do not represent a firmware photograph, recording or original Sony
encoding result.
