# Borrow a matching baseline JPEG SOS suffix

This standalone C11 host component returns a bounded, zero-copy view of an existing host-engine JPEG from **`FF DA` (SOS) through its final `FF D9` (EOI)**, only after its coding controls exactly match a caller-owned reference prefix. The component allocates nothing, changes neither input, and performs no external I/O.

**The original guest prefix has not been obtained.** Tests extract their reference prefixes from actual output of the adjacent [host JPEG engine](../virtual-jpeg-engine/README.md); no default Sony header is fabricated. Passing these component tests establishes suffix provenance and coding-control compatibility for those supplied buffers. It does not establish original-source equivalence, guest execution, DMA, interrupts, device readiness, Fsys saving, or camera capture.

## Verify in host memory

Run from this directory with the already installed C11 compiler, `pkg-config libjpeg`, Python, pytest, and Pillow:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider test_sos.py
```

Observed result: **11 passed** with libjpeg-turbo 3.2.0, Pillow 12.3.0, and pytest 9.1.1. Every C build uses `-std=c11 -Wall -Wextra -Werror -pedantic`. The suite compiles the adapter alone without libjpeg, then builds test executables and a test shared library against the existing `../virtual-jpeg-engine/jpeg-engine.c`; no engine sources are copied or modified. The sanitizer executable adds ASan/UBSan, leak detection, fail-on-first-error, and non-PIE flags for stable Linux ASan mapping. Both normal and sanitized executions report:

```text
jpeg-sos: 4 C self-check groups passed (host memory only)
```

Compiler products live in pytest's temporary directory. Generated RGB pixels, full JPEGs, prefixes, borrowed suffixes, and test reassemblies stay in memory; no JPEG files are written. No VM, network, firmware/private asset, real hardware, or physical SD is accessed.

## Use the borrowed view

Compile [jpeg-sos.c](jpeg-sos.c) into a host caller and include [jpeg-sos.h](jpeg-sos.h). The adapter itself needs only C standard-library headers and `memcmp`; it has no libjpeg dependency.

```c
struct jpeg_sos_view jpeg_sos_suffix(
    const uint8_t *candidate, size_t candidate_size,
    const uint8_t *reference_prefix, size_t reference_size);
```

| Value | Required meaning |
| --- | --- |
| `candidate` | Complete, trusted host-engine baseline JPEG, SOI through final EOI. The adapter cannot establish the producer's identity. |
| `reference_prefix` | Caller-owned actual reference SOI and header bytes, ending exactly at a marker boundary immediately **before** SOS. It must contain the required coding controls. Do not pass SOS, entropy, a complete JPEG, or an invented default. |
| Span lengths | Actual readable object extents for the synchronous call. NULL and address-range wrap fail. C cannot prove mapping/object validity; callers must supply valid objects. |
| Ownership | Inputs may overlap, including using the candidate's own prefix as a test reference. Both remain unchanged; callers must prevent concurrent mutation. |
| `JPEG_SOS_OK` (`0`) | `data == candidate + offset`, `length == candidate_size - offset`; all returned bytes remain within the declared candidate span. |
| `JPEG_SOS_REJECTED` (`1`) | Every failure leaves `data == NULL`, `offset == 0`, `length == 0`. Failure reasons intentionally share one status. |
| View lifetime | The caller retains ownership and must keep the candidate alive and unchanged while consuming the view. The function returns a result by value, avoiding a writable result pointer that could alias input. |

A later device adapter may consume only the successful suffix view once it has an authentic original prefix and the remaining device contracts. This component neither copies a full host JPEG into device output nor adds the original driver's `0x23d` reservation to its returned length.

## Accepted coding contract

Both inputs must start with SOI. Header markers and their lengths are bounds-checked; APP0..APP15 and COM may differ and are skipped by their declared lengths, even when their payloads contain `FF DA`. All remaining coding segments must have **identical marker sequence, segment grouping, lengths, and every payload byte**. No hash, CRC, dimensions-only, or table-size-only comparison is used.

The conservative accepted order is DQT segment(s), one SOF0, DHT segment(s), optional one DRI, then the candidate's first SOS. APPn/COM may occur between these segments. Differently ordered/grouped but semantically equivalent headers fail. Tables must be defined once; duplicates and redefinitions fail.

| Control | Validation and comparison |
| --- | --- |
| DQT | Nonempty, bounded 8-bit tables with IDs 0..3; all 64 values nonzero, no duplicate table IDs. All table bytes must match. |
| SOF0 | Exactly 8-bit precision and three uniquely identified components; nonzero 16-bit dimensions, sampling factors 1..4, at most ten blocks per interleaved MCU, each quantization selector actually defined. Every frame byte, including dimensions, sampling, component IDs and selectors, must match. |
| DHT | Baseline DC/AC table IDs 0..1 only, defined after SOF0; bounded symbol counts, nonempty tables, no duplicate definitions/symbols, no oversubscribed or all-ones code, valid baseline DC categories and AC run/size values. Every count and symbol byte must match. |
| DRI | If present, exactly two payload bytes, after DHT. Presence, absence, and all interval bits must match; absent and explicit zero remain distinct header contracts. |
| SOS | Exactly three components in SOF order, all referring to defined baseline DC/AC tables; `Ss=0`, `Se=63`, `Ah=Al=0`, exact segment size. The reference contains no SOS; candidate selectors are validated against its tables, which were already compared to the reference. |
| Tail | At least one entropy data byte, bounded byte stuffing, restart markers only with nonzero DRI and in RST0..RST7 sequence, EOI exactly at the declared end. Unexpected markers, further scans, early EOI followed by bytes, missing EOI, and marker-fill runs fail. |

Progressive, arithmetic, lossless, extended sequential, grayscale, four-component, multi-scan, 16-bit quantization, unknown coding markers, header fill bytes, and other unsupported layouts fail closed. This deliberately small parser is not a general JPEG implementation.

Tail checks establish marker framing only: they do **not** decode Huffman entropy, count MCUs, prove restart placement at the configured MCU interval, or prove complete pixel data. A truncated/corrupted entropy stream that still has acceptable framing can pass; the candidate must come from the existing trusted encoder. APPn/COM semantics (including possible decoder color interpretation) are not compared. Authentic reference provenance also remains the caller's responsibility; there is no generic acceptance of an untrusted or default reference.

## Evidence and integration boundary

| Evidence | Finding | Executed path |
| --- | --- | --- |
| E1: `test_actual_engine_zero_copy_and_pillow_reassembly` | F1: Real engine JPEGs at five dimensions/quality settings yield views at their actual SOS; independent Pillow full decode of actual reference prefix + view produces exactly the same decoded pixels as the original candidate. | Caller RGB → existing engine → derived reference prefix → adapter → memory concatenation → Pillow. |
| E2: Frame/table byte mutations, malformed controls, reference boundaries, SOS, restart, and EOI tests | F2: Coding differences and exercised malformed/unsupported cases reject with unset views. Embedded SOS bytes in metadata are not mistaken for a scan. | Actual generated JPEG → targeted mutations → bounded adapter rejection checks. |
| E3: Normal and ASan/UBSan [C self-checks](test-jpeg-sos.c) | F3: Borrowed pointer provenance, overlapping read-only spans, immutable input, NULL/wrapping spans, every truncation, and systematic per-byte/bit probes obey the exercised bounds contract. | Existing engine → C adapter calls → pointer/bounds/assert checks; no sanitizer report. |
| E-source: [Original JPEG frontier](../jpeg-hardware-frontier.md), K2acdbc..2ace54 | F-source: Original code expects hardware output beginning `FF DA`, writes its own prefix, and reports hardware length + `0x23d`. | Source evidence only; the original driver has not consumed this adapter. |

This directory owns only its C/header/test/README files; runtime sources and the existing JPEG, optics, and imaging components are untouched. No backend or main-model integration is included. Authentic guest prefix/table binding, original input pixel order, guest output range/capacity/ownership, length FIFO, MMIO cleanup, IRQ delivery, native CP business flow, and original Fsys consumption remain unverified.

`capture_verified=false`, `guest_pixel_consumed=false`, `JPEG_hardware_verified=false`, `native_business_verified=false`, `Fsys_save_verified=false`.
