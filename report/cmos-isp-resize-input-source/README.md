# RC SOURCE input: descriptor and hardware parameters separated; CMOS/ISP owner remains open

**SOURCE input owner closed: NO. Plane/format closed: NO.** This investigation identifies the RC input descriptor, a real upstream address field, and its separate hardware submission. It does not identify the producer that writes the original frame, a same-frame raw/YC identity, a frame lease, or a named input packing. No executable native field closure is delivered: `native_pixel_layout_known=false`, `guest_pixel_consumed=false`, `capture_verified=false`; no original JPEG/MP4 was produced.

The key correction is **SOURCE `T+08 → J+10`, address `J+18`**, through provider **slot `+28=K2d6dd8`**. The previously investigated **`T+90 → J+98` is destination**, through slot `+40=K2d7958`. Following `J+98` again would miss the input origin. These are local structure labels, not recovered Sony type names.

## Scope and evidence

This [scope](#scope-and-evidence) is the authorization record for this bounded task: user-authorized offline reads of the public official ALLLANG `runtime/analysis/menu-root/system/av-cam.bin`, with writes confined to this report's `README.md` / `source-pins.json` and `runtime/analysis/scratch/cmos-isp-resize-input-source/`. No private/full dump, network, VM, device, physical SD, original execution, original binary change, build, ABI run, full tests, review rerun, or commit occurred. The parent's frozen **3253 / 381** batch and completed build/ABI are inherited, not revalidated here. Existing runtime/report files were not edited.

Artifact: **13,797,088 bytes**, SHA-256 **`90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`**. `K` is a raw AArch64 file offset; KVA=`0xffffffc001000000 + K`. This flat image has no ELF import table; original direct branches and vtable words are the equivalent binding anchors, not evidence of absent external interfaces. Capstone **5.0.7**, `/usr/bin/python3`; no decompiler claim substitutes for original instructions. Ordinary reverse-engineering report, `flavor=null`.

Read inherited [imaging contract](../imaging-pixel-contract/README.md), [RC provider](../rc-pixel-layout-contract/README.md), [RC destination](../rc-destination-layout/README.md), and [zero-selected START investigation](../native-video-zero-branch-frame-input/README.md). The last is already a rejoin to encoded-output S88 records; no START/S88 continuation was used as an input candidate here.

[source-pins.json](source-pins.json) contains **12 windows / 9,932 original bytes**, full artifact/window hashes, exact field origins, source callgraph, conditions, memory roles and explicit negative findings. Each window has `.json` original bytes and `.asm` in the owned scratch directory. Hashes are over original bytes, not rendered assembly. Aligned direct-branch / exact KVA-literal scans are recorded separately as candidate indices; they do not enumerate indirect callers.

## 1. The original upstream SOURCE address

The direct call at **`K1d2fd4 → K1d317c`** passes an already-live parameter/record object `P` as x1. In `K1d317c`, `T=sp+70h`; the call **`K1d332c → K2daf2c`** supplies that request, original context handle `P+a4`, callback address `K1d3138`, and x3=0. The callback address is registered for this resize operation; no frame acquisition, CMOS interrupt registration, input lease release or same-frame identity is proved by that registration.

| Original instructions | Value written | Memory role |
|---|---|---|
| `1d3200..3204` | `u32[T+08]=1` | Descriptor first word; not a proved plane count |
| `1d3208..320c` | `u64[T+10]=u64[P+70]` | Original SOURCE address value; producer of its pointee remains unknown |
| `1d3210..3214` | `u32[T+18]=u32[P+78]` | Source descriptor range value; not a proved total frame size or plane offset |
| `1d3218..3264` | Ten u16 values `P+4e..60 → T+50..62` | Geometry copied independently of the address |
| `1d3268..3274` | `T+78=(u8[P+68]==0)` | Attribute, not freshness |
| `1d3278..329c` | `T+7c=K1d344c(context,P.40,P.41)`; `T+80=K1d36cc(context,P.40)` | Two scalar conversions; no named packing recovered |
| `1d31dc..31f0` | `T+84=P.ac`, `T+88=0`, `T+8c=P.b0` | Mode-related scalars, separately forwarded downstream |

The immediately preceding request **`K1d2f5c → K27817c`**, with w2=`639h`, is followed on success by `context+f8 → P+80` and `context+158 → P+88`. `K1d32c0..32cc` then uses **`P+80/+88` for the destination descriptor**, not SOURCE `P+70/+78`. This does not recover a source allocator or a sensor writer. The source address is already present before this window.

A distinct original client at **`K1cdc20 → K2daf2c`**, with `T=sp+80h`, exposes an important conditional input path:

```text
u32[T+08] = 1
u64[T+10] = (u32[P+b0] == 0 ? u64[P+70] : 0)
u32[T+18] = u32[P+78]
u32[T+84] = u32[P+b0]
u32[T+88] = 0
u32[T+8c] = u32[P+7c]
```

Here the address is deliberately zero for a nonzero input mode (`1cda78..1cdabc`). The nonzero-mode branch also supplies literal selector value 6 at `T+7c` (`1cdb30..1cdb68`). This is evidence of a different input route; it is **not sufficient to name that route on-chip ISP/IIB/CMOS**, or to claim selector 6's packing. Another client, `K1fabf8`, only forwards an existing request from its incoming x2; the preceding `K1fac8c` helper receives pointers to scalar fields `+84/+100`, not a proved pixel producer.

## 2. RC input descriptor and source record path

The common wrapper preserves the original client request: `K2daf2c → K2db004 → K2cff84`, then `K2d01a4` supplies it as x2 to provider slot `+18`, whose original vtable entry is `K2d835c`. The builder uses two separate sides:

| Side | Builder operation | Validation/copy | Preparation |
|---|---|---|---|
| **SOURCE** | `2d83ec..843c`: x1=`T+08`, x2=`T.7c`, x3=`T.84`, x4=`J+10` | slot `+28=2d6dd8`; success at `2d71b8..71c4` copies **60h descriptor bytes** | Source address `J+18`; first `2cd23c` call at **`2d8964`** |
| Destination, discriminator only | `2d84cc..851c`: `T+90 → J+98` | slot `+40=2d7958`, inherited destination contract | Second `2cd23c` at `2d8984`; then `2cdc94` |

`K2d6dd8` checks its own SOURCE selector, alignment and rectangle restrictions. Its `{1,7,9}` mask is not a packing definition. The 60h copy writes the command descriptor; it does not read pixels at any address contained in it.

At `K2d8638..864c`, `T+84/+88/+8c → J+8c/+90/+94`. **Do not call these an SDS type/handle/offset triplet**: they are used as mode-related scalars. At `K2d8950..8964`, the source call is:

```text
K2cd23c(local_context,
        u64(u32[J+8c]) | (u64(u32[J+90]) << 32),
        u32[J+94], u64[J+18])
```

`K2cd23c` returns the supplied address unchanged when low32(x1) is nonzero. Otherwise it searches four mapping records beginning at `K3320d8`, checks `E.00 <= address < E.00 + E.18`, and returns `address - E.00 + E.10`; lookup failure emits a diagnostic and returns zero. This is address translation, not source-byte consumption or a lease acquisition.

The first translation is saved at **sp+40h**, the second/destination translation at **sp+38h**. `K2d8af8..8b00` sends the first as x4 of **`K2cd2b0`**, which constructs the input main record. Destination `K2cdc94` receives the other value. `K2d8b58..8b68` copies the local 88h prepared record to `B+i*88h`: **input begins at +0; output begins at +20h**. No image bytes are copied by that `memcpy`.

`K2cd2b0` input dispatch is conditional:

- `J.84==2`, or `J.84==9 && J.8c!=0`, returns before the main input address writer.
- `J.84==9 && J.8c==0` calls `K2cda48`, unexpanded here.
- The remaining main path calls **`K2cd470`**, which writes address/upper-address/transfer/step/count fields at record `+08/+10/+14/+18/+1c`. Its selector dispatch uses table `K387ca8`; no named format was recovered from those table entries.

The source validator receives **`T.7c`**, whereas the main record writer reads **`J.84`**. Their remaining scalar propagation through **`K2d77dc`** is not pinned in this budget; they are not silently equated. This gap is independent of the unresolved producer behind `P+70`.

## 3. Separate SOURCE hardware submission

The original submitter makes a destination call at `2d8ed0`, then the separate SOURCE call at **`2d8ef8 → K2d4960`**:

```text
K2d4960(H, B+initial_i*88h,
        B+current_i*30h+7200h, u32[J+8c], u32[J+94])
  -> K2d45b4(H, u32[H+3c], u32[H+34], M, Z, J.8c, J.94)
```

The distinction between the initially captured and reloaded index is preserved in the instructions; no race/coherence assertion follows. The exact publication of the source auxiliary area at `B+7200h` is outside the selected preparation span, so the entire auxiliary record's identity and lifetime remain open.

`K2d45b4` does consume **descriptor fields** to construct the hardware API parameter `S=sp+48h`:

| Parameter field | Exact source |
|---|---|
| `S+00..03` bytes | Main record flags bits `2:1`, `3`, `4`, `5` |
| `S+04` u16 | Low16 of `J.94` |
| `S+06` byte | Main flags bits `19:16` |
| `S+07` byte | `J.8c==1 ? 3 : (J.8c==2 ? 4 : 0)` |
| `S+08/+0c/+10` u32 | low32 of `M.08`, `M.10`, `M.14` |
| `S+14` u32 | `Z.28` |

At **`2d464c → K2108d8`**, w0=`u32[H+34]`, x1=`S`. On success, `K210bbc` receives the count/step fields; after that succeeds, `K210c3c` receives auxiliary address fields. Only after these successes do `2d4924/4940` update control bits 13/0 at:

```text
(u32[H+14] | ffffffff00000000h) + (u32[H+3c] << 7) + 200h
```

These are numeric hardware control parameters and MMIO control stores. They do not establish a named input engine/format, an original live-frame registration, a hardware transfer reading the pointed-to pixels, or literal software pixel writes. No NV12/YUYV/UYVY/YC422/Bayer claim follows from this path.

## 4. First genuine unclosed boundaries and handoff

**First upstream input boundary:** the writer of **`P+70/+78` before `K1d2f00`**. The original forward consumer is now identified, but no source pin/SDS acquisition, producer task/descriptor writer, pixel publication, frame generation, raw→YC relationship or release callback is identified. `K1d2f5c` and `P+80/+88` are destination work; they must not be substituted for this source boundary.

**First lower hardware boundary:** the named input mode/pixel interpretation and actual transfer behind **`K2108d8 / K210bbc / K210c3c`**, reached using the SOURCE channel fields `H+34/+3c`. The zero-address/nonzero-mode client and the early-return input branches remain numeric routes, not a proved ISP direct-input contract. Closing a hardware-only first boundary would require a positive original mode name/register interpretation together with the call registering a fresh source frame; neither is closed here.

The next narrowly bounded source investigation should start at the earlier construction of `P` in the caller of `K1d317c`, moving backward from `1d2f00`, or at the actual named input engine behind those three helpers. Do not restart `14fcd4 → 15f414` output S88, `J+98`, `2cdc94` destination geometry or JPEG SOF.

| Finding | Evidence | Confidence / status |
|---|---|---|
| F1: RC source is `T+08/J+10`, not `T+90/J+98` | E7/E8/E12 | High, static field closure |
| F2: Real upstream source address is `P+70`; `P+80` is destination in the checked client | E2/E11/E5 | High for field origin; producer/lease open |
| F3: A conditional client uses address zero with nonzero input mode | E1/E4 | High for code condition; named on-chip/ISP meaning open |
| F4: Source record has a separate hardware parameter submission | E4/E6/E9/E10 | High for descriptor programming; pixels/transfer open |
| F5: Source owner, same-frame identity and plane/packing remain unclosed | Above bounded evidence | Bounded negative; not a claim no implementation exists |

All finding severities are `n/a_re`. P1, `path_type=callflow`: existing `P+70` **[unclosed producer]** → `K1d317c` source descriptor → `K2daf2c/K2cff84` → provider SOURCE slot `K2d6dd8` → SOURCE translation `K2cd23c` → input record `K2cd2b0/K2cd470` → `K2d8ef8/K2d4960` → shared parameter builder `K2d45b4` → **[unclosed input hardware/pixel interpretation]**. Every copy/program step is separate from bytes being consumed.

## Reproduce the static checks

From the native-camera result root:

```sh
python3 -B runtime/analysis/scratch/cmos-isp-resize-input-source/verify.py
```

The verifier **passed** against the original: 12 spans / 9,932 bytes, **14 direct branches, 20 field instructions and 5 vtable bindings**. It checks spans against both manifest and saved original bytes, verifies the source-specific bindings, and enforces the 10,000-byte evidence ceiling. It executes no target instruction and writes only `verification.json` in the owned scratch directory. An initial invocation from the project root used the result-root-relative path and failed with rc=2 before any check; the corrected invocation passed, with both attempts recorded in `verification-attempts.json`. For an individual recorded window:

```sh
python3 -B runtime/analysis/scratch/cmos-isp-resize-input-source/probe.py window 0x2cd23c 0x394
```

Timeline: read frozen contracts/AGENTS → separated SOURCE and destination virtual slots → traced source address back to original RC clients → pinned source translation, record dispatch and channel/parameter submission → recorded the still-open source owner and input hardware boundary. No ready/gate forcing, empty ACK or native capture claim was introduced.
