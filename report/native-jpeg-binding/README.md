# Native JPEG register binding: coding conversion and verified completion adapter

The new [native-jpeg.h](native-jpeg.h) / [native-jpeg.c](native-jpeg.c) decode the original memory-source DMA and actual quantization/Huffman register writes into a checked configuration. They also implement the original interrupt-priority table and a separate completion/FIFO/W1C adapter for an already verified host codec execution. **Native START remains blocked:** input component/plane layout and native scan/restart meaning are unproved. Unrounded header dimensions now have a source-checked parameter-snapshot resolver; registers alone still cannot supply them. This is a concrete partial binding for the parent's unified development batch, with no native capture or guest success claim.

The [scope](scope.md) permits public offline source analysis and local checks only. Every new file is in this directory. No existing core, header, QEMU integration, CP implementation or other worker's file was edited. The header's public API is stable for the parent and c209 pipeline worker. No QEMU/VM, original executable/module, network, private/full-system asset, physical device or SD was used. JPEG bytes remain in pipes and memory.

From `report/2026-10-17-qemu-native-camera/`, run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  report/native-jpeg-binding/test_native_binding.py
```

The updated local result is **15 passed**, using GCC 16.2.1, libjpeg-turbo 3.2.0, installed Kuna 1.892 for bounded source recovery, strict C11 `-Wall -Wextra -Werror -pedantic`, normal and ASan/UBSan builds, and independent Pillow decoding. The tests compile `native-jpeg.c`, `test-native-jpeg.c`, the unchanged `virtual-jpeg-hardware/jpeg-hardware.c` and `jpeg-hardware-codec.c`, and unchanged `virtual-jpeg-sos/jpeg-sos.c`, with installed `pkg-config --cflags --libs libjpeg`. They build in pytest temporary storage. No dependency was installed.

The tests exercise invalid/missing configuration, missing and partially reuploaded tables, changed Huffman bytes and nonzero final AC padding, unsupported routing/control values, alignment/AIF/range/overlap failures, denied reset/read-only/unknown accesses and repeated blocked START. Actual callback memory then receives a real codec SOS suffix, reads every written byte back and releases the immutable host RGB lease before success. The separate adapter publishes the source-native bit only from that actual complete core, handles ACK/pop in both orders, refuses duplicate imports, preserves unrelated status bits, clears a source-defined rejection latch and refuses failed write/readback results. In-memory reconstruction independently checks the source Huffman bytes, exact natural-order quantization tables, 4:2:2 sampling, actual RGB content and changed entropy when pixels or quantization change.

The supported RGB fixture is independent of the native source: its byte size is deliberately different from the native DMA span. It proves that register-derived coding reaches the real codec and that verified output can drive the completion adapter. It does not prove native YC input consumption. `njpeg_binding` has no RGB-job API, no owner callback and no success injection API.

The original artifact is public ALLLANG `runtime/analysis/menu-root/system/av-cam.bin`, 13,797,088 B, SHA-256 `90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`. K is the raw ARM64 file offset, base zero; original KVA is K plus `ffffffc001000000`. Never apply CP's `+108000` rule. [source-pins.json](source-pins.json) pins 31 bounded windows against that full identity. [source-windows.asm](source-windows.asm) retains the original26 windows' Capstone instructions; [logical-geometry-source.asm](logical-geometry-source.asm) retains the five additional geometry windows. [kuna-bounded.json](kuna-bounded.json) contains successful raw-base-zero Kuna recovery of exactly `K2a4164`, `K2afcf8` and `K2afd30`, each with an explicit end address, a 6-second per-function limit and 256 MiB function budget. This is a raw module with local calls/module API indirection; there is no claimed ELF import table or whole-module survey. No target code was executed.

The original submission at `K2acba4` calls `K2aab4c`, which zeros all `0x1d8` bytes of L. Thus this path establishes zero `L+69/+6a`; those route bytes are no longer treated as uninitialized in this bounded path. `K2aa374` writes scale controls `16/16` at `L+b0/+b1` and real scaled natural-order quantization bytes at `L+b2/+f2`. `K2acc90..2acca4` converts those exact arrays into the later header snapshot with `K2ae0a0`. No default JPEG quality guess is required.

`K2af65c` passes `S=L+90` to `K2af780`. Its call of `K2a4164` receives `S+20=L+b0`: it writes B+ac=0, the two scale-control low bytes at B+b4/B+b8, and all 64 bytes of each actual quantization table to B+200..23c and B+280..2bc as little-endian words. The converter takes those live words, rejects any zero quantizer and applies the independently source-checked standard natural-to-zigzag traversal. The source profile's precision, component IDs, 4:2:2 sampling, Q selectors and immutable Huffman bytes are inherited from the unchanged core's [source contract](../virtual-jpeg-hardware/README.md).

`K2aaa8c` fills L+20 with default Huffman controls and pointers into the immutable module. `K2af698` sends that object to `K2a43a4`. The writer loads B+4c0=1, B+500=3c and these exact arrays, without the JPEG table-info byte:

| Original table | Bits register / bytes | Values register / bytes | Original data |
| --- | --- | --- | --- |
| DC0 | 600 / 16 | 610 / 12 | K4512ed+1 / +11 |
| AC0 | 620 / 16 | 630 / 162 | K451327+1 / +11 |
| DC1 | 700 / 16 | 710 / 12 | K45130a+1 / +11 |
| AC1 | 720 / 16 | 730 / 162 | K4513da+1 / +11 |

All offsets and `+11` pointer arithmetic in that table are hexadecimal except byte counts. `K2a4274` zero-pads the final two bytes of each 162-byte AC value upload. Changed Huffman data, nonzero padding or an incomplete upload is rejected. The converter supports the actual default profile only; it does not silently replace a guest's changed table with the immutable default. As a conservative snapshot rule, repeating B+ac=0 invalidates quantization write coverage, and repeating B+4c0=1 invalidates Huffman coverage. Every word in that new upload must be observed again. This is the decoder's completeness policy, not a claim that those writes erase ASIC RAM.

| Native words | Checked meaning or exact supported value | Source |
| --- | --- | --- |
| 0 / 30 / 38 / 7c | Encode path values zero | K2acbb8, K2af698 |
| 80 / 84 | Low halfword = hardware height / width; supported complete words are H8/W16 aligned and bounded | K2aa3e8, K2a4010 |
| a0 / a4 / ac / b0 / b4 / b8 | Exact original subset `1/0/0/1/16/16`; no scan/restart names invented | K2af780, K2a4098, K2a4110, K2a4164 |
| 1218 / 800 | Source high AIF encoding / source low32 | K2a510c, K2af824, K2a4650 |
| 804 / 808 | Access chunk 256; `stride = B808+256 = 2*CanvasX` | K2af9a8 |
| 80c / 810 / 814 / 818 / 81c | `7`, `-7*stride`, `access_width/128-1`, `stride-2*access_width`, `height/8-1` | K2af9a8, K2a4650 |
| 820 / 824 | Zero in the selected memory-source, no wrap subset | K2af9a8 |
| 1008 / 1200 / 1280 | Supported **zero-preserved-bit subset**: `0/0/0` before gating, then `10/2000/3`; partial sequence returns NEED_DATA. Original K2a5404 uses RMW, not these unconditional whole-word constants. Other preserved bits are unsupported by this adapter, not source-proven zero. Route bits remain zero in the selected subset; bit13 has no component-order meaning | K2aaaf0, K2a52fc, K2a5404 |
| 1298 / 12a0 / 12a4 | Output AIF high / aligned D low / bounded aligned DMA capacity | K2af698, K2a476c |
| 400 | Low16 output prefix skip, E-D, supported 0..15; not labeled restart interval | K2af7f0, K2a430c |
| 12a8 / 12ac / 12b0 / 12b4 / 12b8..12c4 | Exact `0/0/-capacity/ffff/0..0` output traversal subset | K2af6fc..2af734 |
| 90 | Separate threshold snapshot, not output capacity | K2af7ac |
| 870 | Bit0 set to 1 by the original output path; exact word1 subset | K2a48c0 |
| 18 | Original writer word `01100005`; retained separately from native enable/target proof | K2af6d4..2af6e0 |
| 2400/2410/2420, 2430/2440 | Known source-used colorimetry words are shadows only; no transformation or pixel packing asserted | K2a4938 |

The last identified helper, `K2af620→K2a5404`, performs `B1008=old|0x10`, `B1200=old|0x2000`, then `B1280=(old&~6)|3` before setting B+8 bit0. The converter accepts the coherent pre-gate or complete final sequence **only in its zero-preserved-bit subset**; it refuses partial sequences and unmodeled preserved bits. This is a conservative support boundary, not a claim that the source clears those bits or that its shadows prove pixel readiness. The [AIF field contract](../jpeg-aif-layout-contract/README.md) records the full RMW and unknown byte-lane boundary. This paragraph was clarified after the 3249/381 frozen batch; runtime C and tests did not change.

`njpeg_resolve()` requires every active configuration word and every table word to have been observed. It checks a conservative complete source span `(height-1)*stride + 2*access_width`, aligned source and output addresses, supported full AIF spans, output capacity minus skip, and physical overlap. The AIF high word is `(AIF>>24)&ffffff00`; it is decoded by the existing source-checked helper, never by ordinary high32 concatenation. Source width/height here are hardware dimensions: the source rounds W16/H8 before these MMIO stores. A native prefix's unrounded logical geometry cannot be recovered solely from these registers.

`njpeg_resolve_parameter_geometry(binding, parameter, bytes, out)` additionally accepts an immutable original **P snapshot from the same submission**. The source chain is positive: `K2a5b4c` uses **ADD x0,task,#18**, not a pointer load; `K2acd18` copies `u64[P+28]` into payload+8, therefore task+20/+24. On real code1 completion and FFDA validation, `K2ace60` passes task+20 to `K2ac7a0`, whose `K2aca44..2acacc` stores height then width as big-endian SOF0 fields. Meanwhile `K2acc18` passes P+28 independently to `K2aa3e8`, which rounds hardware W16/H8. A decompiler incorrectly describing task+18 as a pointer field is superseded by the actual ADD instruction.

The resolver reads the two complete little-endian u32 values at P+28/+2c, checks nonzero/bounded values and exact W16/H8 agreement with the current validated register snapshot, and exposes them separately as `logical_width/logical_height`. `coding.width/height` keep their hardware meanings. No pointer is retained and failed size/mismatch/overflow does not publish partial geometry; input/output or binding/output overlap is refused without mutating the aliased object. Only `NJPEG_GAP_LOGICAL_GEOMETRY` can clear. The caller must obtain a coherent original P snapshot; this function does not establish that native firmware supplied one.

The existing strict and ASan/UBSan C runs now also test all128 combinations W17..32/H9..16, exact logical SOF bytes, input immutability, truncated/zero/large/mismatched geometry, changed MMIO, pointer wrap and forbidden overlap. The updated component is **15 pytest cases passed**. Six strict/SAN cases independently decode logical sizes17×9,31×15 and32×16 over identical32×16 hardware-MCU entropy, comparing every decoded byte with a crop of the rounded reference. This is a host codec check of header/MCU consistency, not original pixel consumption. A raw-register resolver call still reports three gaps; supplying valid P reduces that snapshot to pixel-layout and scan/restart gaps. Native START remains NEED_DATA and no status/FIFO/IRQ is produced.

Reads accept contained aligned byte/halfword/word accesses, as used by the original byte-read routines. Writes accept only known aligned words. Unknown/read-only offsets, B+4 reset and unsupported starts are refused. Unwritten configuration shadows read zero; zero is not treated as proof that required configuration was written. Partial/source-incompatible configurations return `NEED_DATA`, `INVALID`, `BOUNDS`, `OVERLAP` or `UNSUPPORTED`, with a zeroed output configuration. A complete supported register snapshot returns OK **with three explicit gap flags**. `B+8=1` always refuses native execution; B+10, B+44 and B+4c remain zero, and empty FIFO pop is invalid. There is no `AP0/AP4` workaround.

`K2afcf8` calls `K2a3f78` to read B+10, then calls `K2a3f48` to write the same word to B+14 before returning the original status. `K2aef98` includes it in the actual 12-byte queued interrupt message, sent through `K2aedd0`. `K2afd30` consults the following table in order; it returns the first matching original dispatcher code, never the bit number:

| Priority | Native B+10 mask | Dispatcher code |
| --- | --- | --- |
| 1 | 01000000 | 10 |
| 2 | 00000001 | 1 |
| 3 | 00010000 | 2 |
| 4 | 00000004 | 3 |
| 5..11 | 10,20,40,20000,40000,80000,100000 | 4,5,6,7,8,9,13 |

In the encode consumer `K2acd34`, code1 enters the post-hardware `FF DA` check and only then writes the original header; code3 clears the reported length and returns error `1a`. Other codes take a different rejection path. Therefore native bit0 is a positive encode-completion candidate and bit2 is an encode-rejection candidate. No bounded evidence here proves a specific FIFO-overflow cause for bit2. Host `FAULT` or `CANCELLED` virtual event bits are never copied into these native bits, and no other native error event is synthesized.

`njpeg_completion_import()` borrows an actual unchanged `vjpeg_hw` object only when its snapshot reports COMPLETE/OK, the exact DONE event, one FIFO entry, a nonzero real suffix length and completed host IRQ publication. That core only publishes after real encoding, bounded write, complete byte readback and lease release. The adapter explicitly sets native status `1`, preserves the measured length, supports original B+10/14 and B+44/4c/40 behavior, and acknowledges/pops the underlying core when the owner consumes them. The same still-complete result therefore cannot be imported twice. Keep the borrowed core alive until both W1C and FIFO pop finish; serialize all access and do not ACK/pop that core independently while borrowed. The completion adapter's `interrupt_mask` is an explicit **host** enable gate. Native B+18 polarity and actual guest enable/target/GIC/EOIR consumption remain the parent's work, with the physical contract inherited from [IRQ routing](../jpeg-irq-routing/README.md): device0 PA f3020000, GIC INTID61, external input29, LIRO EOIR PA f13a2010.

| Evidence | Finding / confidence / status | Path and practical boundary |
| --- | --- | --- |
| E-quant: pinned K2aa374, K2a4164, K2acc90 and K2ae0a0; bounded Kuna; real Pillow DQT comparison | F-quant: actual register bytes bind to the codec's exact quantization tables; high, implemented; severity n/a_re | P-coding (callflow): natural live MMIO table → checked source-compatible coding snapshot → actual existing host codec; logical geometry remains explicit |
| E-huff: K2aaa8c, K2a43a4/K2a4274; source immutable bytes; changed/padded/partial upload tests | F-huff: exact source-default profile is validated, not guessed or silently replaced; high, implemented; n/a_re | P-coding includes full Huffman upload and partial-reupload rejection; other Huffman profiles unsupported |
| E-status: K2afcf8/2aef98/2aedd0, table K3ef054, K2acd34; real write/readback/release tests | F-status: bit0/code1 and bit2/code3 identities, priority, FIFO and W1C are source-backed; high, isolated adapter implemented; n/a_re | P-host (callflow): independently supported host RGB → real codec → verified callback memory → imported native-shaped status/FIFO; disconnected from native START |
| E-gaps: K2aa3e8 source stride only; rounded MMIO dimensions; a0/a4/b0 words without named scan/restart semantics; inherited pixel-contract §§12–15 | F-block: layout and scan/restart are open; logical size requires a coherent original parameter snapshot through the new resolver; high confidence in the stated search boundary; native implementation blocked; n/a_re | P-native (callflow): original P → zero L → actual register snapshot → resolver → explicit NEED_DATA, no success output or IRQ |

The next integration boundary is a positively established native source layout/lease and named or otherwise positively derived scan/restart control semantics. Logical width/height mapping is implemented, while its caller must still supply the coherent original P snapshot. DataSite/IIB, APYC DataContent2/placement1, the ENCHANDLER domain's unrelated input-format codes and `2*CanvasX` alone do not supply those facts. A future YCbCr backend should use the proven native component layout directly (for example libjpeg `raw_data_in` only after that proof), preserving the current RGB core's semantics. The unchanged core does not yet provide a native YC API. No unsupported parameter is converted into a success ACK.

The bounded verification timeline is: source windows and three Kuna functions were pinned; implementation and valid host-output self-check passed strict C; the added partial-Huffman-reupload fixture initially aborted because its manually typed first Huffman word was wrong; it was corrected to retain the actual valid register word; the complete strict/sanitized/Pillow rerun passed all 9 tests. The failure was a fixture error, not an accepted completion receipt. Parent-owned combined checks and end-to-end execution were not run here.

`register_to_coding_converter_implemented=true`, `verified_host_completion_adapter_implemented=true`, `native_mmio_capture_usable=false`, `guest_pixel_consumed=false`, `capture_verified=false`, `qemu_built_or_run=false`.
