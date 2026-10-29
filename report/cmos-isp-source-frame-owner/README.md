# Upstream RC SOURCE: P owner and handle query pinned; original pixel producer remains open

**True source owner: NO. Plane/format: NO. Actual runtime lease: unknown.** The primary-path owner of descriptor `P`, its original `+70` u64 / `+78` u32 writers, and the two-stage handle query feeding them are now pinned. The producer of the queried pixel contents, a fresh-frame identity, a CMOS/ISP callback and a named packing/depth remain unproved. This is a static source-field result; no executable native capture closure is delivered. **`capture_verified=false`; no original JPEG/MP4.**

The practical input binding is **`P+70 = first address returned by opcode 24 for the handle at SSYC category-zero payload+04`; `P+78 = that first segment's u32 length`**. The metadata handle and reader offset arrive in a registered callback argument. They are not silently promoted to a frame or lease.

## Scope and evidence

This section records the user's authorization for the bounded upstream-only investigation. Input is the public official ALLLANG `runtime/analysis/menu-root/system/av-cam.bin`: **13,797,088 bytes**, SHA-256 **`90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`**. Addresses `K` below are raw file offsets; KVA=`0xffffffc001000000 + K`. This is a flat AArch64 LE64 image, without an ELF import table. Original direct branches, address constructions and vtable words are the equivalent binding anchors; there is no inference that external interfaces are absent.

Only this new report and `runtime/analysis/scratch/cmos-isp-source-frame-owner/` were written. Previous reports, runtime code and frozen inputs stayed read-only. No VM, private/full dump, network, target execution, device, physical SD, original binary edit, build, ABI run, full test rerun, delegation, review or commit occurred. The parent's accepted source/input/test and dual-original-ABI state is inherited. Its original AP3003/EE0/no-JPEG/MP4/capture-false result is unchanged. The independently assigned lower `K2108d8/210bbc/210c3c` path was not investigated.

The [previous source report](../cmos-isp-resize-input-source/README.md) supplies the already-completed forward consumer `K1d317c`, `T+08/J+10` SOURCE distinction and destination exclusion. The existing [SSYC input notes](../virtual-cp/yc-inject/README.md) were consulted as context; their synthetic/runtime claims do not establish the original source owner here. S88, EncOpen and output queues were not continued.

[source-pins.json](source-pins.json) contains **12 exact windows / 9,100 original bytes**, full artifact/window SHA-256 values, 91 instruction pins, 18 direct calls, two vtable bindings, field widths/conditions, evidence-to-finding links and the remaining unknowns. Original bytes and assembly are saved in the owned scratch directory. Tools: `/usr/bin/python3`, Capstone 5.0.7; no decompiler used. Report flavor is `null`.

| Evidence | Raw interval, end exclusive | Bytes | Purpose |
|---|---|---:|---|
| E1 | `1d10d0..1d117c` | 172 | Embedded descriptor pool and free ring |
| E2 | `1d13f4..1d19dc` | 1512 | Callback argument, metadata, second query, source writers |
| E3 | `1d298c..1d2be0` | 596 | Registered continuation, caller and context adjustment |
| E4 | `1d2e38..1d2fd8` | 416 | Selection of P and unchanged argument to inherited consumer |
| E5 | `1df2a0..1df4b0` | 528 | Original callback owner constructor |
| E6 | `1e1b10..1e1b6c` | 92 | Member callback adapters |
| E7 | `278940..278c84` | 836 | Address/range query and handle-retirement wire |
| E8 | `278290..278380` | 240 | Synchronous reply and return conditions |
| E9 | `90488..90530` | 168 | Category-zero 48h-byte metadata object and copy helper |
| E10 | `93208..94318` | 4368 | Contiguous SSYC constructor/parser/payload-copy functions |
| E11 | `375770..3757f8` | 136 | Exact inbound/continuation callback vtable words |
| E12 | `3f1bbc..3f1be0` | 36 | Original ETRY and SSYC name bytes |

## Original P owner and bounded caller chain

Use `A` for the original resize-flow object and **`C=A+d8h`** for its embedded consumer context. Ignoring this adjustment would connect the wrong rings.

`K1d10d0` initializes **20 embedded records `P_i=A+488h+i*c0h`, `0<=i<20`**. At `1d1130/1134`, each record receives a u32 configuration scalar at `P+00` and the u64 owner backlink `A` at `P+08`. `1d1154` publishes pointers into the free ring at `A+1398h`, with count `A+1388h`. This closes descriptor storage ownership, not pixel-buffer ownership.

`K1d13f4` pops one of those free records (`1d1438`). On its checked primary path it later publishes that same pointer at `A+1450h+8*i`, incrementing count `A+1440h` (`1d1994..19c4`). The registered continuation `K1d298c` checks this count and calls **`1d29dc → K1d2b74` with `x0=A+d8h`**. Therefore:

```text
C+1368 = A+1440    source-work ring count
C+1378 = A+1450    source-work ring pointer array
C+1418 = A+14f0    conditional fallback pointer
C+1420 = A+14f8    separate active-work count
```

`K1d2b74` preserves the original flag/count guards. With the flag at `C+15ba` clear it drains/returns records rather than reaching the inherited resize consumer. With that flag set, count greater than one returns; a nonzero eligible count selects its existing ring entry. The zero-count branch selects `u64[C+1418]`; **that fallback's origin is not closed for an arbitrary direct entry**. The checked continuation calls only after observing `A+1440!=0`; no concurrency/coherence proof is claimed.

`1d2e40` loads the selected `P` into x20. **`1d2fcc..2fd4` passes `x0=C`, `x1=P` to `K1d317c`.** It does not construct a new source address. The intervening destination operation is the inherited discriminator only; it does not write SOURCE `P+70/+78`.

The original constructor `K1df2a0` binds two member callbacks:

| Callback object | Stored owner/function | Original vtable adapter |
|---|---|---|
| `A+16a8` | `A+16b0=A`, `A+16b8=K1d13f4`, `A+16c0=0`; exposed at `A+10` | word `K375790=KVA(K1e1b10)` |
| `A+16e8` | `A+16f0=A`, `A+16f8=K1d298c`, `A+1700=0`; exposed at `A+60` | word `K3757f0=KVA(K1e1b50)` |

Both adapters load the stored owner/function/adjustment and branch through the stored function. With constructor adjustment zero, they pass the incoming x1 through unchanged. **The caller that invokes the first callback with an original live input is not identified.** Registration and a continuation callback do not establish a CMOS interrupt or acquisition callback.

The aligned B/BL scan finds `1d29dc→1d2b74` and `1d2fd4→1d317c`; `K1d13f4` and `K1d298c` have no direct B/BL or exact KVA-literal hits. Their positive bindings are the constructor's ADRP/ADD stores and the vtables above. The scan is a candidate index, not an enumeration of all indirect callers.

## Exact source acquisition field chain

Let `I` be the incoming x1 argument to `K1d13f4`. This boundary supplies two u32 values, not a proved frame record:

| Original location | Width | Assignment / role |
|---|---:|---|
| `1d1454..1468` | u32 | `I+00 → P+10` and `A+1c8`: first query handle |
| `1d145c/1464` | u32 | `I+04 → P+98`: metadata-reader byte offset |
| `1d1480 → 278940` | API | Query `A+1c8`, w1=0, w2=0, w3=`827e073f` |
| `1d1494/1498` | u64 | First query address `A+1d0 → P+18`: **metadata buffer** |
| `1d149c..1590` | address | Existing mapping search and `K2f514` translation provide metadata CPU address; failure supplies zero |
| `1d1594..15a0` | API | `K94258(reader, mapped_base, u32[A+230], u32[I+04])` |
| `1d15b0`, `1d1604`, `1d1614` | 48h bytes | Parse category zero, copy its body to `A+368`, then to `P+20..67` |
| `1d1618/1620` | u32 | `A+36c → P+6c`: body `+04`, the **second query handle** |
| `1d1924/1928`, `1d1940` | u32/API | Put that second handle into `A+1c8`, query again with the same zero option/scalar |
| **`1d1954/1958`** | **u64** | **`A+1d0 → P+70`: first segment address from second query** |
| **`1d195c/1968`** | **u32** | **`A+230 → P+78`: first segment length from second query** |
| `1d1964` | u32 | `P+ac=0` on that original branch; a numeric scalar only |
| `1d1984/198c` | u32 | `P+b0=A.24`; no source format or freshness interpretation |

The constructor at `K90488` gives the category-zero metadata object category value zero, a destination payload at object+20 and length **48h**. `K933c8` uses the reader's base+offset, category `K8d800`, `K93e70` entry lookup and `K8d820` payload copy. `K9051c` copies exactly the 48h-byte body. The original strings `SSYC` and `ETRY` are byte-pinned in E12. This identifies the metadata family and field-copy coordinates; it does not certify the producer or pixel contents.

Consequently, **`P+40/+41` originate at category-zero body `+20/+21`, one byte each**, via that copy. Their live values and the original producer's enum/name mapping are unknown. `K1d344c/1d36cc` were not expanded: conversion output numbers, a two-byte calculation or the existing YUV filename would not supply named packing/depth. No NV12/YUYV/UYVY/422/Bayer inference is made.

## Query response boundary and freshness conditions

`K278940` constructs a **d8h-byte opcode `24h`** request: u32 handle at `+08`, the caller's second scalar at `+0c`, magic `1111h` at `+14`, u16 option at `+16`. Handle bit 15 selects destination **`8061003c` or `9061003c`**. The wrapper calls `K278290`, which invokes `K9763c`, retrieves the reply through `K94978`, requires reply magic `1111h` at `+06`, and checks signed16 status `+02`.

A zero status maps to helper return 0; a positive status maps to 2; negative/error replies map to 1. In `K278940`, **only helper return 0** proceeds to the reply count, `u16[reply+08]`. A nonzero count drives the concrete writers:

```text
u64[query_arg+08+8*i] = u64[reply+18+10h*i]    (2789e0/2789e8)
u32[query_arg+68+4*i] = u32[reply+20+10h*i]    (2789ec/2789f0)
```

Because `query_arg=A+1c8`, the first entries are exactly `A+1d0` and `A+230`. Thus `P+78` is a **first segment length**, not a proved total frame size or plane extent. No reply-supplier handler, original allocation, source-byte transfer or pixel writer is established by this query.

**The caller accepts query returns 0 or 2** (`orr(result,2)==2` at `1d1488/148c` and `1d1948/194c`). Return 2 therefore reaches later assignments without a fresh copy by `K278940`. Return 0 with zero segments also leaves the address/range slots unchanged. This records the original conditions; it is not a demonstrated runtime failure or permission to fill unknown fields with zero. A future consumer must prove the actual successful nonempty query and live contents before treating the fields as a fresh source.

The same bounded source contains an original handle-retirement request wrapper `K278b88`, opcode **23h**, handle `+08`, option `+16`. The source path contains calls with option 2, including `1d1840..1850`, but this supplies neither a proved acquire/release lease pair nor a generation/lifetime contract. **Actual runtime lease remains unknown.**

## First unknown and handoff

The first upstream unclosed boundary is now concrete: **the original invoker and argument writer of callback `A+16a8`, and the writer of category-zero payload `+04/+20/+21` in the metadata selected by `I.00/I.04`.** The corresponding opcode-24 reply supplier and the actual writer of pixels at the second query's address remain untraced. The separate inbound pin-packet route was not positively joined to this callback in these windows, so it is not represented as that producer. This is a bounded negative conclusion, not a claim that no producer exists.

P1, `path_type=callflow`:

```text
[unknown original callback invoker / metadata producer]
  -> A+16a8 vtable+10 -> K1e1b10 -> K1d13f4(I)
  -> first opcode24 query: metadata address/range
  -> SSYC category0 body -> P+20; body+04 -> second query handle
  -> second opcode24 query: first address/range -> P+70/P+78
  -> embedded P source-work ring A+1440/A+1450
  -> registered K1d298c continuation -> K1d2b74(C=A+d8)
  -> K1d2fd4 -> inherited K1d317c SOURCE consumer
```

All edges are conditional as above. No original frame callback, hardware pixel publication, current frame identity, named plane layout or runtime lease is added by calling these records inputs.

| Finding | Evidence | Confidence / status |
|---|---|---|
| F1: primary-path P descriptor owner and source field origins closed | E1–E11 | High static; storage owner only |
| F2: query success alone needs nonempty-copy qualification; return2 is insufficient | E2/E7/E8 | High static conditions |
| F3: true pixel producer, named plane/format and runtime lease remain open | E2/E5/E6/E7/E9–E12 | Bounded negative |

All severities are `n/a_re`. Parent integration can use the exact pointer/length origins and constructor provenance as source evidence. It cannot enable capture, declare a format, invent a frame generation, manufacture a buffer-ready response or replace missing source contents. **Descriptor P owner YES; true source owner NO; plane/format NO; runtime lease unknown.**

## Reproduce and verification

From the native-camera result root:

```sh
python3 -B runtime/analysis/scratch/cmos-isp-source-frame-owner/extract.py
python3 -B runtime/analysis/scratch/cmos-isp-source-frame-owner/finalize.py
python3 -B report/cmos-isp-source-frame-owner/verify.py
```

The report verifier is self-contained with the original asset and `source-pins.json`; saved scratch bytes are additionally compared when present. It checks full hashes, disjoint exact spans and the 10,000-byte ceiling, source-field instruction widths/registers, direct branch targets, both callback vtable words, metadata magic bytes and eight source-coordinate equalities. Two negative checks reject changed artifact bytes and an incorrect same-width instruction claim. It executes no target instruction and writes only `verification.json` under the owned scratch directory.

Final verification: **PASS — 12 windows / 9,100 bytes / 91 instruction pins / 18 direct calls / two vtable bindings / two negative checks.** The first extraction attempt failed with rc=1 because the result-root calculation selected `runtime/runtime`; no windows were written. The root calculation was corrected before successful extraction, and the failed attempt is preserved in the manifest.

Timeline: inherited the completed downstream boundary → found original embedded P pool and source writers → separated the metadata query from the second data-handle query → pinned original constructor/adapters and conditional caller → checked response-copy freshness conditions → verified the bounded evidence and recorded the original producer boundary. Full tests/build/ABI/runtime runs were intentionally not repeated; no runtime functionality or capture claim changed.
