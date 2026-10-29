# Bounded RGB888 JPEG engine

This standalone **host software component** compresses caller-owned RGB888 pixels into a caller-owned, bounded JPEG buffer using the installed libjpeg-turbo. It consumes scanlines and produces a real, decodable baseline JPEG in memory. It has no firmware or QEMU integration and does not demonstrate camera capture, EE/JPEG hardware operation, or an Fsys save.

Only the five files in this directory belong to this component. It does not read camera assets, use a VM, access physical storage, use the network, or change the frozen `runtime/analysis/` sources. Test images and JPEG streams stay in memory; temporary files are compiler products, explicitly for this host component.

## Build and verify

Prerequisites: a C11 compiler, `pkg-config libjpeg`, Python, pytest and Pillow already installed. No dependency download or installation is performed. Verified here with libjpeg-turbo **3.2.0**, Pillow **12.3.0** and pytest **9.1.1**.

From this directory:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider test_engine.py
```

Observed result: **16 passed**. The session fixture builds a shared library and two C self-test executables in pytest's temporary directory. Every build uses `-std=c11 -Wall -Wextra -Werror -pedantic`; one executable additionally uses AddressSanitizer and UndefinedBehaviorSanitizer, with leak detection and fail-on-first-error. The sanitizer executable is non-PIE for predictable ASan shadow mapping on the Linux host. Both C executions report:

```text
jpeg-engine: 6 C self-test groups passed (host memory only)
```

For the C-only self-test without Python or Pillow, from this directory:

```bash
build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT
cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 \
  $(pkg-config --cflags libjpeg) jpeg-engine.c test-jpeg-engine.c \
  -o "$build_dir/test-jpeg-engine" $(pkg-config --libs libjpeg)
"$build_dir/test-jpeg-engine"
```

## Call the engine

Include [jpeg-engine.h](jpeg-engine.h), compile [jpeg-engine.c](jpeg-engine.c) into the host caller, and link with `pkg-config --cflags --libs libjpeg`. There is one synchronous entry point:

```c
struct jpeg_engine_result jpeg_engine_encode_rgb888(
    const uint8_t *input, size_t input_size,
    size_t width, size_t height, size_t stride, int quality,
    uint8_t *output, size_t output_capacity);
```

The result is returned by value: `status` is an enum and `used` is the valid JPEG byte count. No result pointer can alias either buffer. Callers must only consume `output[0..used)` when `status == JPEG_ENGINE_OK`.

| Argument or property | Contract |
| --- | --- |
| Pixel format | Explicit virtual **RGB888**, R/G/B byte order, top row first. This does not establish the original Sony YC format. |
| Width and height | Both `1..JPEG_MAX_DIMENSION` from the installed libjpeg; 65,500 in the verified installation. |
| Stride | At least `width * 3` bytes; padding is ignored. |
| Input span | Non-NULL, readable for its declared size; at least `(height - 1) * stride + width * 3` bytes. The final row needs no trailing padding. |
| Quality | Integer `1..100`; 100 remains lossy. Baseline quantization is forced. |
| Output span | Non-NULL, writable for its declared capacity. Zero capacity reports `OUTPUT_TOO_SMALL`. An exactly sufficient capacity succeeds. |
| Aliasing | The full declared input and output spans must be disjoint, including unused input padding or suffix bytes. Adjacent spans are allowed. Address-range wrap and extent arithmetic overflow are rejected. |
| Ownership | Caller retains both buffers for the whole synchronous call. Input is never modified. Concurrent calls need separate writable buffers and stable input. |
| Failure | Always returns `used == 0`. Output may contain a partial, invalid JPEG and must be discarded; no buffer rollback is promised. |

C cannot determine whether a non-NULL pointer actually names a mapped object of the stated size. Supplying valid host objects remains the caller's responsibility; future guest-memory adapters must validate and map their own address spaces before invoking this API.

| Status | Meaning |
| --- | --- |
| `JPEG_ENGINE_OK` | Complete JPEG stream, with `used` valid bytes. |
| `JPEG_ENGINE_INVALID_ARGUMENT` | NULL pointer, zero/excessive dimensions, short stride, or quality outside 1..100. |
| `JPEG_ENGINE_INPUT_TOO_SMALL` | Declared input span does not cover all active pixels. |
| `JPEG_ENGINE_OUTPUT_TOO_SMALL` | Zero capacity or actual compressed stream exceeds capacity. |
| `JPEG_ENGINE_SIZE_OVERFLOW` | Unrepresentable row/extent arithmetic or declared address-range wrap. |
| `JPEG_ENGINE_OVERLAP` | Declared input and output spans overlap. |
| `JPEG_ENGINE_NO_MEMORY` | Per-call context or libjpeg allocation failed. |
| `JPEG_ENGINE_CODEC_ERROR` | Other libjpeg failure, recovered through the overridden error handler. |

## Memory and compression behavior

The destination manager writes directly to the caller's output span; it never calls `jpeg_mem_dest`, grows an allocation, or buffers an entire compressed frame. A one-byte private probe handles libjpeg's callback when the final byte exactly fills the span. Any actual additional output fails without writing outside the caller's buffer.

The compressor reads one caller scanline at a time, uses libjpeg's default RGB-to-YCbCr conversion and 4:2:0 sampling, and disables optimized Huffman coding. It emits sequential baseline JPEG rather than progressive output. There is no whole-frame pixel copy or full-frame coefficient-buffer request. Libjpeg still allocates its own scanline/MCU workspace; this API does not impose a separate allocator-byte quota. Allocation failure is recoverable.

Each call owns a small heap context containing codec, error and destination state. The context survives `longjmp` with defined values, so output exhaustion and libjpeg failures can destroy the compressor and release allocations safely. There is no mutable global engine state or file I/O.

## Verification evidence and limits

| Evidence | Observed finding | Reproduction path |
| --- | --- | --- |
| E1: [C self-tests](test-jpeg-engine.c), normal and ASan/UBSan executables | F1: Original installed libjpeg decompresses nonuniform scenes at 1x1, odd and non-MCU dimensions. Input bytes remain unchanged; decoded RGB errors at quality 95 are at most 35 per channel and mean below 9. | `test_c_selftests` → scanline encode → original libjpeg memory decode and pixel comparison. |
| E2: [Pillow tests](test_engine.py), seven scene dimensions and two changed inputs | F1 corroboration: SOI/SOF0/SOS/EOI and dimensions are checked; an independent decoder frontend produces the expected gradients/checkers. Changing actual pixels changes both stream and decoded content. | `test_pillow_roundtrip` and `test_changed_pixels_change_decoded_content` → memory encode → Pillow decode → bounded pixel comparison. |
| E3: C boundaries and Python capacity checks | F2: Short/zero/exact output capacity, input underflow, invalid dimensions/quality/stride, extent and span overflow, overlap, adjacency, padding noise, last-row extent, and repeated failure/retry obey the API. Red-zone canaries remain intact. | `test_output_bounds`, `test_validation`, `test_padding_and_last_row`, `test_adjacent_spans`, `test_recovery_and_quality_limits`, and `test_exact_capacity_and_overflow`. |
| E4: Joint sanitizer execution and four-worker concurrency test | F2 corroboration: No sanitizer or leak report in the exercised paths; 12 concurrent calls decode correctly using their own buffers. | `test_c_selftests[sanitized]` and `test_concurrent_calls`. |

The reproduction command above is the evidence command; no JPEG byte hashes or library-version-dependent golden streams are used. Same-run comparisons only check identical active pixels and ignored padding. Quality endpoints 1 and 100 are also decoded. Exhaustive image sizes, forced allocator-failure injection and every internal libjpeg error path were not tested.

The implemented data path is **caller RGB888 span → libjpeg scanlines → bounded caller JPEG span → memory decoder**. The following integration work remains unimplemented and unverified:

| Future connection | Current status |
| --- | --- |
| Original guest DMA address/length and ownership contract | Missing; no guest bytes are mapped or consumed here. |
| Original JPEG MMIO commands, completion status and reset behavior | Missing; no registers or ready bits are introduced. |
| Original Sony input layout and conversion | Unknown to this API; no NV12 or YC layout is assumed. |
| Guest output DMA and completion IRQ | Missing; return status only describes this synchronous host function. |
| Original firmware request and error handling | Missing; no original driver uses this component yet. |
| Fsys/virtual-SD photo save | Missing; no capture or stored-camera-photo claim follows from these tests. |

Future integration can call this engine only after those contracts are established and the adapter validates actual guest memory. Component verification does not establish successful firmware photography.
