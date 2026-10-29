# Source-derived JPEG execution core

This bounded host component really compresses an explicitly leased RGB888 frame, checks the result against a source-derived coding profile, writes only `FF DA..FF D9` to bounded callback memory, reads every written byte back, and then publishes a length and external IRQ **29**. The original header builder is now understood well enough to configure those coding controls without reading an unwritten guest prefix. **The original native YC/MMIO capture path remains unsupported.** No QEMU build/run, guest, network, private asset, real device or physical SD was used.

All implementation is new in this directory. The public API is [jpeg-hardware.h](jpeg-hardware.h). The parent owns QEMU integration, CP state, native interrupt delivery and the final joint VM test. This component never triggers a real interrupt.

## Build and verify

From `report/2026-10-17-qemu-native-camera/`:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  report/virtual-jpeg-hardware/test_hardware.py
```

Result: **8 passed** in this directory. A final combined run with `virtual-jpeg-sos/test_sos.py` and `virtual-jpeg-engine/test_engine.py` passed **35 tests**. The tests build both normal and ASan/UBSan executables with `-std=c11 -Wall -Wextra -Werror -pedantic`, plus a shared library in pytest's temporary directory. Dependencies are already installed: C compiler, `pkg-config libjpeg`, Python pytest and Pillow. Tested GCC 16.2.1, libjpeg-turbo 3.2.0, Pillow 12.3.0; source disassembly used installed capstone 5.0.7. No new dependency was installed.

The C tests cover six groups: checked source/AIF/output arithmetic; completion/FIFO/W1C ordering; ten memory, lease, codec and verification failure cases; seven cancellation positions; unknown contracts/unsupported registers/invalid starts; and exact output capacity plus ignored row padding. They verify canonical-backing alias rejection, exactly one release for every acquired lease, no early success length/IRQ, no prefix read before write, and non-overwriting guards. The Python tests independently decode the actual device-written suffix joined in **memory** with the original-order, source-built prefix. Inverted source pixels and nonconstant custom quantization tables change the entropy/output, and all three images decode with mean absolute RGB error below 3 and maximum error at most 12 for the fixture. The test RGB gradient is an explicit host fixture, not a claim of consumed guest/optical pixels.

The initial self-test run aborted with rc134 because its expected sampling-byte index was 569 instead of 567; that fixture assertion was corrected. Both strict and sanitized complete reruns passed. No failed result was treated as a completion receipt.

To link the component into the parent's host adapter, compile these inputs with the installed libjpeg flags:

```sh
cc -std=c11 -Wall -Wextra -Werror -pedantic \
  report/virtual-jpeg-hardware/jpeg-hardware.c \
  report/virtual-jpeg-hardware/jpeg-hardware-codec.c \
  report/virtual-jpeg-sos/jpeg-sos.c \
  report/virtual-jpeg-hardware/test-hardware.c \
  $(pkg-config --cflags --libs libjpeg) -o /tmp/virtual-jpeg-hardware-test
/tmp/virtual-jpeg-hardware-test
rm -f /tmp/virtual-jpeg-hardware-test
```

`test-hardware.c` is the executable/self-contained owner-callback example; leave it out when linking the adapter. There are no generated photograph/video files. Test JPEG bytes travel only through a subprocess pipe into Pillow `BytesIO`.

## Positive source contract

The only original binary read is public ALLLANG `runtime/analysis/menu-root/system/av-cam.bin`, 13,797,088 bytes, SHA-256 `90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`. K is the raw file offset, with no CP `+0x108000` adjustment. [source-pins.json](source-pins.json) binds 17 bounded byte windows and 11 instruction anchors to that full hash. The test checks every window and instruction. A whole-module import/symbol survey is not claimed: this is a raw AArch64 module with local branches/module API indirection, not a new ELF import analysis.

`K2ac7a0` accepts a snapshot whose first two u32 words are width and height and whose `+8/+48` hold two 64-byte quantization tables. It writes:

| Original segment | Proven content |
| --- | --- |
| DQT, length `0x84` | Combined 8-bit tables 0 and 1, copied from snapshot `+8/+48` |
| DHT, length `0x1a2` | DC0 `K4512ed/29`, AC0 `K451327/179`, DC1 `K45130a/29`, AC1 `K4513da/179` |
| SOF0, length `0x11` | Template `K30a0c0/17`; precision 8; dimensions from snapshot; IDs 1,2,3; sampling `21/11/11`; Q selectors `0/1/1` |

The source explicitly replaces the Y sampling byte with `0x21` at `K2acadc`. Thus the profile is **4:2:2**, which the older RGB host engine's default 4:2:0 configuration cannot represent. No libjpeg quality-to-table guess is used here. The four embedded Huffman definitions are compared against the immutable original bytes, not just against libjpeg defaults.

`K2aa374` builds natural-order quantization buffers at `L+b2/L+f2` from the caller's scale/table parameters. `K2acc90..2acca4` calls `K2ae0a0` twice to convert these into the per-job prefix snapshot's zigzag tables; `K2ae0a0` traverses the standard zigzag. The API consumes that **explicit zigzag snapshot**, rather than inferring it from a quality byte. The float-to-quant builder and live-register resolver are not executed or invented by this implementation.

The original builder has no SOI, SOS or DRI. Its DQT+DHT+SOF bytes total exactly `0x23d = 573`. `vjpeg_source_prefix()` adds SOI solely to provide a complete independently decodable header contract and returns 575 bytes. The actual device output starts at SOS and excludes all these prefix bytes. The native final-length rule remains hardware length plus `0x23d`; SOI ownership is outside that builder.

The bounded profile explicitly supports a baseline three-component sequential scan with default table selectors and **restart interval zero**. Those scan controls are declared by the typed caller and enforced in the encoder; the prefix builder alone does not prove the original ASIC's scan/restart programming. Other scans/profiles are unsupported.

`K2acdbc..2ace54` checks `FF DA` at E. Only after that check does `K2ace58..2ace68` call `K2ac7a0` to write the prefix. The new core therefore obtains coding controls from the explicit parameter snapshot/immutable tables and never waits for a guest prefix to exist. Internally it splits/reorders the source DQT/DHT/SOF segments to the existing SOS checker's canonical sequence, preserving every coding byte. The host codec receives those exact quantization/Huffman/component controls; `jpeg_sos_suffix()` checks the resulting complete candidate before its suffix can be written. No existing engine or SOS file was edited.

This proves coding-header compatibility and independent decoding of the host implementation. It does not prove entropy-bit equivalence to the ASIC, a native request-to-coding resolver, or a guest capture.

## Owner integration contract

1. Construct a device with all six callbacks: `probe`, `read`, `write`, `acquire`, `release`, `irq`.
2. Independently establish known RGB888 source pixels, an immutable source lease and a complete `VJPEG_SOURCE_HEADER_422` coding snapshot. Set explicit source and effective destination **E** ranges in `vjpeg_job` and call `vjpeg_hw_prepare()`.
3. Execute synchronously with `vjpeg_hw_execute()` or B+8 bit0. Registers alone never arm a job and yield `VJPEG_NEED_DATA`.
4. The core probes the entire source and destination first, checks canonical backing-object overlap, acquires/validates the RGB view, encodes, checks the coding header, writes bounded SOS bytes, reads all bytes back, releases the lease, then publishes length/FIFO/DONE and IRQ 29.
5. Read length at B+4c, pop the single-entry FIFO with B+40=1, and W1C the **virtual** DONE event with `vjpeg_hw_ack()`. Both FIFO consumption and event ACK are necessary before another job can be prepared. ACK and FIFO pop can occur in either order.

`probe` must identify aliases using the same nonzero canonical object ID and byte offset. A success pins the complete mapping through the return from execute. `acquire` returns an immutable, readable RGB view of the requested source range; the provider must establish that correspondence. Invalid or unknown returned formats release the acquired lease without consuming pixels. Once the actual codec is attempted, release receives `consumed=1` exactly once, including failures after encoding; that flag is not a success receipt.

There are no private locks. The owner serializes entry points, and callbacks run without component locks. Callbacks may inspect, cancel and ACK. Other mutation returns BUSY; destroy must not be called from a callback or during execute. Cancellation is synchronous at callback boundaries, not a thread-safe asynchronous interrupt of libjpeg. Cancellation before encoding consumes no pixels; cancellation after write invalidates those bytes and publishes no success length or IRQ. A failed/partial owner write or readback failure can leave invalid destination bytes; the caller must discard that buffer. The core never rolls back external memory.

Unknown pixels/coding, zero tables, overflowing/wrapping ranges, unmapped output, too-small output, aliasing, bad leases, failed write/readback and cancellation cannot produce a success FIFO entry or raised IRQ. Fault/cancel events are explicit typed results and require their own virtual W1C ACK. Early or unrelated ACKs do not clear a later DONE. Pending output cannot be overwritten by a repeated start.

## Source-closed arithmetic and sparse registers

`vjpeg_source_address()` implements the memory-branch address `P0 + 2*((P14+P24)*CanvasX + P10+P20)` with checked arithmetic. It does not label the source's 2-byte samples as RGB or a YC packing. The typed RGB provider has its own stride; it is not the native `2*CanvasX` interpretation.

`vjpeg_phys_to_aif()` and its bounded inverse implement only the three nonempty original `K3320d8` ranges: `[0,100000000)`, `[100000000,200000000)` add `400000000`, and `[3fe000000,3fe6c0000)` subtract `300000000`. High encoding is `(AIF>>24)&ffffff00`, not ordinary high32. A span crossing an original range boundary is rejected even where the arithmetic would remain continuous.

`vjpeg_output_layout()` implements mode3 `E=base+offset+23d`, `D=E&~f`, skip E-D, DMA capacity `(base-D+offset+cap)&fffffff0`, and the separate threshold `cap>63d ? cap-63d : 0`. Bad capacity, overflow and an AIF span crossing a range fail. An owner using this native layout should pass **E** and at most `dma_capacity-skip` to the typed job; the prefix is reserved before E. The core never writes padding or prefix bytes.

| B offset | Implemented behavior |
| --- | --- |
| `+8` | bit0 launches an already explicitly armed job; other bits unsupported; idle read zero |
| `+10/+14` | Native read/W1C shape preserved, no invented native bits; B+10 remains zero in this subset |
| `+40/+44/+4c` | Pop=1 / one-entry count / non-destructive actual suffix length |
| `+0,+18,+1c,+30,+38,+7c,+80,+84,+90` | Source-used control/dimension/threshold word shadows only, no readiness or native coding inference |
| `+800..824` step4 | Source DMA word shadows only |
| `+1200,+1218,+1298` | Routing and encoded high-address word shadows only; no pixel packing inference |
| `+12a0..12c4` step4 | Output DMA word shadows only |

Only these offsets are accepted. Reads support aligned 1/2/4-byte accesses contained in one word, matching the original byte-read assembly. Writes support aligned words. Read-only, unknown or mis-sized accesses return UNSUPPORTED. Word shadows do not configure the typed job or make the original driver usable; automatic register-to-job decoding is deliberately absent until its missing facts are established. This is a root execution subset, not a complete original MMIO model.

The original PA/IRQ number contract is inherited from [the verified IRQ routing investigation](../jpeg-irq-routing/README.md): device0 PA `f3020000`, Linux/GIC INTID61, QEMU external input29, LIRO EOIR PA `f13a2010`. This component emits only a callback with 29 after verified writeback. It does not set a real GIC line, mask, target, native status bit or EOIR.

## Evidence, findings and remaining path

| Evidence | Finding | Execution path / boundary |
| --- | --- | --- |
| E-prefix: pinned `K2ac7a0`, table windows, `K2acc90`, SOF template | F-profile: exact original-order header and explicit 4:2:2 table profile can be reconstructed before output exists | P-host: explicit RGB lease → configured codec → strict SOS verification → bounded write → complete readback → lease release → virtual FIFO/event/IRQ |
| E-lifecycle: strict + ASan/UBSan self-tests and callback assertions | F-order: no data-success event precedes actual verified bytes; error and cancellation paths release acquired leases once | P-host is locally tested; no guest path execution |
| E-decode: source-prefix byte comparison and independent Pillow decode | F-content: host-written suffix plus original-order source header is decodable and depends on actual input pixels and quantization | Does not establish native input packing, native request ownership or guest storage |
| E-registers: bounded address/start/FIFO/status stores; prior IRQ report | F-subset: source arithmetic and sparse access shapes are modeled; native bit-to-completion interpretation remains open | P-native stops before automatic pixels/coding job formation and native completion translation |

The exact first unknown source components for the parent are:

- **Native pixels and lease:** the parameter1054 producer and memory-source interpretation at `K2aa3e8/K2af9a8`. `P50/P58` and B+1200 routing are not YUYV/plane evidence. `L69/L6a` are not assumed initialized.
- **Live coding binding:** natural quant tables at `L+b2/L+f2`, the snapshot conversion at `K2acc90..2acca4`, and their original programming through `K2af65c/K2af698` / `K2a43a4` still need a live register-to-configuration resolver. The core accepts an explicit source-derived snapshot; it does not pretend to obtain that snapshot from the current register bank. Scan/restart controls need their own source proof before a native claim.
- **Native completion:** B+10 bit semantics, actual registered mask/target/enable and IRQ clearing/LIRO EOIR consumption. The virtual DONE/FAULT/CANCELLED bits have no claimed mapping to native bits.

`capture_verified=false`, `guest_pixel_consumed=false`, `native_mmio_capture_usable=false`. All pre-existing files and other workers' changes were preserved. Publication synchronization and the full joint development batch / single end-to-end VM remain with the parent; this worker ran only the local checks above.
