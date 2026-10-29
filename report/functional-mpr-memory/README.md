# Functional MPR memory device

This provider supplies real process-owned RW memory to the original movie-recording DMM allocation API and resolves its original JPEG output SDS in `virtual-functional-camera-v1`. The original `SetMemTbl` builds the full **0x760-byte** table from actual mapped arenas. Type0 SDS uses the actual registered **unit ID directly**, as proved by the original producer; it is not an address or a packed unit/area pair. The profile uses a defined **identity software IOVA**, `V = P`; these addresses do not describe Sony physical DRAM or prove physical ASIC compatibility. Fresh zero-filled ES capacity is available storage, not encoded output. `capture_verified` remains false until the complete capture/write/readback chain passes.

The implementation and host scenarios compile in normal and sanitizer configurations. The production provider also links for **AArch64 against the public original libc 2.25, dl, pthread and loader with `--no-undefined`**. Its actual scanf import is `__isoc99_sscanf@GLIBC_2.17`, with no C23 import. **The delegated workers did not execute pytest or C scenarios**, as requested; the parent owns the combined batch. No original SDK invocation or guest boot has been exercised by this work.

## Integrate with the functional profile

Files owned by this implementation:

- [`functional-mpr-memory.c`](../../runtime/analysis/functional-mpr-memory.c) and [public header](../../runtime/analysis/functional-mpr-memory.h).
- [Host C scenarios](../../runtime/analysis/test-functional-mpr-memory.c) and [parent batch](../../runtime/analysis/test_functional_mpr_memory.py).
- This README and [source pins](source-pins.json).

Add the C source to the parent's existing observer link, retaining its normal `-pthread -ldl` flags. After validating and setting up the approved local functional profile, call:

```c
#include "functional-mpr-memory.h"

int rc = functional_mpr_memory_enable(record);
/* rc == 0 enables only this process's explicit functional memory provider. */
```

There is no constructor, probe thread, environment-variable activation, or allocation of record buffers during enable. Enable checks the original writer, selector and exported root variable before accepting work. Original record arenas are mapped only when original MPR calls `AllocDmmMemory`; fixed type2 has its own lazy allocation when original MPR requests it. Enable refuses a preexisting live original area list.

The parent must validate the actual mapped ALLLANG library identity before enable:

```text
libmpr.so size:   3528576 bytes
libmpr.so SHA256: 4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9
```

The runtime additionally resolves the actual `RTLD_NEXT` symbols and verifies their runtime addresses and whole instruction-window FNV values for `SetMemTbl`, `UnitTypeTableSelect`, both switch tables, the original release-mask helper, `GetUnitInfo` and `GetStillBufConfig`. The last two windows gate the source-defined direct-unit SDS schema. The full artifact SHA-256 is a parent setup prerequisite, rather than a digest claimed by this runtime FNV check. No file BSS contents are loaded as runtime state.

**Codec integration:** type4 really has an 8 MiB secondary arena, so the original table gives `EncOpen` a nonzero secondary capacity at parameter `+0x18`. A codec adapter accepting only zero secondary capacity must handle that field before opening this table. Both ES ranges are real, disjoint owned memory; this provider does not manufacture secondary encoded data.

## Allocations and table contract

| Range | Real usable capacity | Original table producer | Identity |
|---|---:|---|---|
| Unit type3 | 32 MiB | `SetMemTbl` → T+00 | RW CPU pointer equals model IOVA |
| Unit type4 | 8 MiB | `SetMemTbl` → T+20 | Separate RW range |
| Unit type6 | 16 MiB | All default-branch subareas | Separate RW range |
| Fixed area type2 | 512 bytes | `GetFixedArea(2)` returns P, V, size | Separate page-backed mapping |

A record generation reserves **56 MiB + four 4096-byte guard pages** with anonymous `mmap`, then enables RW access only on the three arena ranges. Each base is 4096-byte aligned and below 4 GiB for the original `NativeDmacAddList` u32 addresses. No `MAP_FIXED` replacement is used. If Linux returns an address different from the safe hint, that newly returned mapping is immediately unmapped; existing mappings remain untouched. Hints are bounded to the local low-address pool and do not wrap.

The whole BufferTable starts as software-defined disabled zero entries. Three fully initialized nodes provide the actual group, unit identifiers, area identifiers, extent count, V base, size, validity and P base. Model identifiers refer to these real arenas; they are not physical-device handles. Their `area` values are explicitly defined as the software unit types 3/4/6, rather than borrowed physical DMM area numbers. The nodes are published under the model mutex, with their final tail pointing to the preserved original inactive list. Existing original nodes and links are not changed.

The actual original writer is then called as `SetMemTbl(group, original_mode, candidate)`. Before any caller output changes, the provider checks every live table entry's pointer pair, size, zero correction and owned bounds. It also requires every mandatory default-branch area, including those consumed by `GetStillBufConfig`:

| T offset | Offset within unit6 | Declared subarea capacity |
|---|---:|---:|
| 040 | 000000 | 06d000 |
| 060 | 06d000 | 00e000 |
| 140 | 07b000 | 000400 |
| 160 | 07c000 | 000400 |
| 260 | 07d000 | 200000 |
| 280 | 27d000 | 001400 |
| 2a0 | 27f000 | 000400 |
| 2c0 | 280000 | 339000 |
| 300 | 5b9000 | 006000 |
| 320 | 5bf000 | 003000 |
| 640 | 5c2000 | 003000 |
| 660 | 5c5000 | 200000 |
| 680 | 7c5000 | 001400 |
| 6a0 | 7c7000 | 000400 |
| 6c0 | 7c8000 | 003000 |
| 6e0 | 7cb000 | 200000 |
| 700 | 9cb000 | 001400 |
| 720 | 9cd000 | 000400 |

Offsets and capacities in that table are hexadecimal. T+260 supplies the still-data area and T+2a0 supplies the writable 0x78-byte original still-config object. The last listed area ends at unit6+0x9cd400, within its actual 16 MiB mapping. The host writer fixture reproduces all these stores only under `FMPR_MEMORY_HOST_TEST`; production always uses the original writer.

V1 accepts a mode only in `[0,0x22]` for which the original selector returns a table, excluding modes **6 and 0x11**, whose alternate metadata formulas are unsupported. Original modes **5 and 0x0d** select null and fail. Other selected modes use this explicitly defined functional three-unit layout; other physical unit types remain disabled zero. A second allocation while any unit is live fails with `EBUSY`.

The focused SDS follow-up closed the mode question without extending those alternate layouts. The original `GetStillBufConfig` call sites are M **`0xd335c`** (`ExecEncOpen`), **`0xd96ac`** (`EnterRec`) and **`0xddfbc`** (`RecStart`). Their allocation paths call the original `GetDmmModeId` at `0xced08`, whose complete byte table at `0x2ce548` returns **`0x13, 0x15–0x22`**, with fallback **`0x10`**. All use the already validated type6 default branch. Neither 6 nor 0x11 occurs on this closed configuration path; unrelated physical still/decode allocation layouts are not inferred from its name.

## Resolve the original JPEG output SDS

The append-only API required by [JPEG777](../functional-jpeg-codec/README.md) is implemented with the exact declared signature:

```c
int functional_mpr_memory_acquire_sds(uint32_t type, uint32_t handle,
    uint32_t offset, size_t bytes, struct functional_mpr_memory_lease *lease);
```

It returns an actual existing memory lease for exactly the requested current range. It shares `validate`, `write` and `release` with address-based callers. No new registration API, fake allocation response, handle cast, AP ready store, standalone encoder or media writer is added.

The positive original producer chain uses public **M=`libmpr.so`** and **I=`libInfraAvbbc.so`** ELF VAs:

| Source | Actual dataflow |
|---|---|
| M `GetDmmExtList` `0x2b259c/0x1a0`, stores `0x2b26a0/0x2b26a4` | Original allocation unit is stored at node+8; area is a separate node+c field |
| M `GetUnitInfo` `0x2b2b6c/0x74` | Returns node+8 through x1, node+c through x2, address−V through x3, and node+30 through x4 |
| M `GetStillBufConfig` `0xcee7c..0xcee90` | Uses unit output at stack+48, area at +44, offset at +4c; looks up actual T+260 memory |
| M `0xcef04/0xcef18/0xcef40` | Loads **unit and offset**, leaves area unused; stores unit unchanged at the 0x78-byte config's +54 and +60 |
| M `Codec::StillBufConfig` `0x27d348/0x118` | Passes the actual config pointer in the original 0x38-byte payload; no handle conversion |
| I `InfraStillEncoderSeqStillBufConfig::StartSequence` `0x125578/0x1e0` | Copies the original 0x78-byte config into ParameterControl keys1047/104f and retains its pointer under keys1048/1050 |
| I `InternalEncode::SetParameter` `0x11dcd4/0x174` → one-thumbnail constructor at `0x11d510..0x11d534` | Forwards the original configuration key into the actual Without_Pin object |
| I `makeParamEncodeJpeg` `0x11b18c/0x1fc` | Reads config+54 or +60 and copies it unchanged to request+28; request+24 is type0 and +2c is offset0 |

Consequently type0's handle is the **unit**, with no unit/area packing on this chain. Each model allocation already publishes real node IDs over its actual arenas. Only after the original writer's complete table passes validation does this provider retain immutable SDS identities for those nodes: unit, area, group, generation, V, IOVA, capacity and type. These are the same IDs returned to the original `GetUnitInfo` consumer. The resolver does not accept arbitrary integers merely because they lie inside a mapping. Fixed type2 is not an SDS registration. Existing foreign inactive unit IDs are checked for collisions before a new model group is allocated.

The native output ranges also have a source-closed origin. Let `O` be the T+260 arena offset and `S` its capacity:

| Without_Pin branch | Handle | Position | Remaining capacity |
|---|---|---:|---:|
| mode0, config+54/+58/+5c | actual unit | `O + 0x100dc` | `S − 0x130d8` |
| mode1, config+60/+64/+68 | same unit | `O + S − 0x2ffc` | `0x2ffc` |

Original request+34 is position+capacity, +38 is position and +3c is capacity. The JPEG adapter checks its full live envelope/body and these sums, then calls this resolver with **request+2c offset + request+38 position**, not the raw input YC descriptor. The source object is the original output configuration. Input pixels use the separately declared functional RGB bus; no physical YC layout is established here.

Lookup, immutable identity comparison, current arena resolution and token acquisition all occur under the same memory mutex as selective Free. IDs are never recycled, including across shutdown/re-enable. A changed node or root, a conflicting live arena alias, or a retired generation cannot retarget the SDS. Retirement immediately invalidates matching SDS lookups and token writes while preserving the original mapped bytes. The existing four-generation limit, 64-token limit, fork-before-lock guard and callbacks outside locks are retained.

| Refusal | Error; caller lease remains unchanged |
|---|---|
| Wrong type, zero/foreign/unregistered handle, pointer cast, group ID or area ID | `-ENODATA` |
| Retired ID, changed registered node, changed root or conflicting arena alias | `-ESTALE` |
| Zero bytes | `-EINVAL` |
| u32 offset+bytes overflow | `-EOVERFLOW` |
| Crossing or starting at the registered arena end | `-ERANGE` |
| Full token table / exhausted token sequence | `-ENOSPC` / `-EOVERFLOW` |
| Disabled provider / fork / unwritable lease output | `-ENODEV` / `-ECHILD` / `-EFAULT` |

SDS registration is a real memory-provider boundary, not proof that the native thumbnail sequence has run. Original DMM open/metadata services, native request occurrence, original queued completion and MPR/Fsys saving still require parent integration evidence. No successful capture is claimed by this resolver or its source checks.

**Parent caller handoff:** the collected JPEG777 `encode()` currently uses `validate → memcpy → validate`. That detects retirement around publication but does not serialize the actual copy against Free. Its owner/parent must use the existing `functional_mpr_memory_write(&lease, 0, encoded + skip, bytes)` for the copy/readback operation. This follow-up changes no JPEG source; the memory provider's write API and its retirement guard are ready and source-compatible. The new SDS resolver alone cannot enforce a protocol on a caller's retained raw CPU pointer.

## Use leases when publishing codec bytes

`functional_mpr_memory_query(address, bytes, &span)` validates a complete current owned span and returns its actual base, capacity, offset, IOVA, group, unit and generation. Zero length, overflow, crossing an arena boundary, guard pages, foreign memory and retired ranges fail without changing the output.

A codec writer can keep one bounded lease for an ES or metadata range:

```c
struct functional_mpr_memory_lease lease;
int rc = functional_mpr_memory_acquire(destination, capacity, &lease);
if (!rc) {
    rc = functional_mpr_memory_write(&lease, offset, encoded_bytes, encoded_size);
    if (!rc)
        rc = functional_mpr_memory_validate(&lease); /* before publication */
    int release_rc = functional_mpr_memory_release(lease.token);
    if (!rc)
        rc = release_rc;
}
```

This is API context, not an executed capture example. `encoded_bytes` must be immutable actual encoder/readback output for the duration of the write call. `write` holds the retirement mutex over lease validation, actual copy and destination digest readback; a retired or released token cannot write through this API. There are 64 outstanding lease slots, each tied to a real range. Forged spans, stale tokens, duplicate releases, over-capacity writes and failed input-span checks are rejected.

Retained raw pointers remain CPU-accessible for original MPR/Fsys borrowers. They cannot enforce a caller's write protocol by themselves: codec integration must use the serialized writer, release its lease after use, and honor retirement before publishing. No source data or packet is published by allocation alone.

`GetUnitInfo` fills its required outputs with the real owned arena's unit, area, u32 offset, u64 IOVA base, and optional capacity. Outside current functional ranges it returns zero without traversing the original empty-root case. Original `ChangeVirtToPhysAddr` is **not overridden**: with identity IOVA its existing `old - offset - base` difference is zero and the pointer remains CPU-accessible. Fixed type2 is independently queryable with group/unit/area zero and software unit type2; its reported capacity is 512 bytes, even though Linux maps one 4096-byte RW page.

## Release and coordinated shutdown

`FreeDmmMemory(mode, mask)` retires only units in the current matching-mode group selected by the original mask convention:

| Mask bit | Functional units retired |
|---|---|
| 1 | Types3 and 4 |
| 2 | None of the enabled three types |
| 4 | Type6 |
| 7 | All current units |

The bit mapping comes from original `CnvAreaId2ModeSubArea`, which is called with the conversion row's unit type. A zero mask is a successful no-op. Bits outside 7 or a different mode fail without changing the group. The void overload uses mask7. Queries and lease validation stop recognizing each retired unit immediately; **Free never unmaps or recycles borrowed bytes**.

A subsequent original allocation gets a fresh nonoverlapping generation. V1 retains at most **four successful record generations** until coordinated shutdown: at most **224 MiB RW capacity + 64 KiB record guard reservations**, plus the optional fixed 4096-byte page. Further allocation fails with `ENOSPC`; this is not an infinite-clip claim. `mapped_bytes` in the snapshot and operation record is the actual total virtual mapping reservation, including retired mappings and guards, not a physical or resident memory claim. Low-address hints also have a finite process-lifetime budget and never wrap, including across successful shutdown/re-enable cycles.

The parent performs the shutdown ordering:

1. Stop/join codec writers and drain their original transport work.
2. Finish original MPR/Fsys writes and flush the virtual SD.
3. Retire the active group through the original Free API and release all model leases.
4. Call `functional_mpr_memory_shutdown()`.

Shutdown refuses an active group or any outstanding token with `-EBUSY`. It also refuses a changed original root or changed model links with `-ESTALE`. On those refusals all mappings are preserved. A valid shutdown restores the saved original root and unmaps retired generations plus fixed memory. Original MPR/Fsys drain proof is an external parent precondition; the provider cannot infer it from an empty token table.

All exported entry points compare the owner PID **before any model lock**. A forked child receives `ECHILD`/`-ECHILD` and does not reinitialize inherited locks or release its parent's leases. There is no destructor performing unsafe cleanup.

## Original ABI and strict-profile behavior

The provider exports exactly these interposed symbols:

```text
_ZN3mpr10DmmMemInfo14AllocDmmMemoryEiPjPNS0_11BufferTableE
_ZN3mpr10DmmMemInfo13FreeDmmMemoryEij
_ZN3mpr10DmmMemInfo13FreeDmmMemoryEi
_ZN3mpr10DmmMemInfo11GetUnitInfoEPvPjS2_S2_PmS2_
_ZN3mpr6memory12GetFixedAreaENS0_13FixedAreaTypeEPPvS3_Pj
```

With the provider disabled, each wrapper resolves its actual `RTLD_NEXT` target and passes through the original arguments and return type. It restores incoming `errno` after symbol resolution and leaves the delegated function's final `errno` intact. Missing symbols fail rather than synthesize an allocation. Enabled fixed-area requests other than type2 also delegate. The strict profile gains no implicit enable path or fabricated buffers.

Enabled failure paths validate writable output spans and reject overlap before mutation. They construct the full candidate table privately; failed mode selection, low mapping, table validation or capacity checks leave the caller's group/table unchanged. Callback records run outside the mutex and identify software IOVA and conservative verification flags.

## Evidence → finding → path

Scope: only new assigned implementation/test/report files under this result root and read-only inspection of the public ALLLANG ELF. No VM, private/full-system data, network, hardware, real SD, original binary changes, new dependencies, review agents or additional delegation were used. Report flavor is ordinary technical reverse engineering (`null`).

| Evidence | Finding | Use in the implementation |
|---|---|---|
| Original EnterRec `0xd975c` BL → PLT `0x7bfc0`, relocation `0x2fe780` | Original recording allocation is interposable | Allocation happens on the actual original API call |
| Whole `SetMemTbl` `0x2b2be0/0x858`, original type switch | Types3/4 and all type6 default areas have source-closed writers | Reuse the original producer and validate all output entries |
| Original list acquisition `0x2b259c`, inherited [producer report](../native-video-open-parameter-producer/README.md) | Node field offsets and full table snapshot lifetime | Model-owned nodes and retained generations |
| `GetStillBufConfig` `0xcee2c/0x184` | T+260 lookup and T+2a0 writable config are mandatory | Neither field is omitted from validation or the host fixture |
| `GetUnitInfo` `0x2b2b6c/0x74`, `ChangeVirtToPhysAddr` `0x280650/0x70` | Offset is u32; P base is u64; original lookup dereferences root before null check | Safe owned-range lookup and unchanged original identity translation |
| Fixed-area getter `0x2c38b8/0xb4` | Type2 is the codec parameter area | Separate real 512-byte usable range |
| `CnvAreaId2ModeSubArea` `0x2b2920/0x50` and original free wrappers | Types3/4 map to mask1, type6 to mask4 | Matching group/mode selective retirement |
| Original unit producer → `GetUnitInfo` → `GetStillBufConfig` → I Without_Pin builder | Type0 output handle is the actual direct unit, with separate area metadata | Immutable registered identities resolve only current real ranges through existing tokens |
| `GetDmmModeId` and all three config allocation callers | Needed configuration modes use the existing type6 default layout | No invented mode6/0x11 BufferTable extension |
| Original libc2.25 export and actual linked AArch64 imports | `__isoc99_sscanf@GLIBC_2.17` exists; C23 scanf does not | Explicit assembler alias, old-ABI `--no-undefined` link |
| Host mapping/lease/SDS scenarios, pending parent execution | Verification design covers actual mapped bytes and retirement | Test pass or native capture is not claimed here |

Path P1: explicit approved profile enable → original EnterRec allocation call → real low arena mappings → original table writer over owned published nodes → original queued table/EncOpen consumers → codec leases and actual copied/readback bytes → original MPR/Fsys borrowers → retirement → parent-proven drain → coordinated unmap.

Timeline: reused the supplied successful Kuna source; confirmed exact methods, mode/type tables, PLT, node and still-consumer instructions; implemented the provider/header; added standalone host scenarios and independent ELF/binder checks; compile-checked delivery. Scenario execution remains with the parent batch.

All source coordinates are **ELF VAs**. The Python checks map windows with `PT_LOAD`, verify the complete 3,528,576-byte MPR artifact SHA-256, preserve the original 14 method/source windows, match exact exported symbol sizes/VAs, check original relocation bindings and decode mandatory table-store destinations. The focused SDS addition pins **15 further windows** across M, I and original libc, the full public I/libc identities, direct-unit instruction anchors and three typed ParameterControl relocations. It does not redo or replace the original completed 14-window investigation. A second-load check explicitly verifies VA `0x36b8a8` maps to file offset `0x35b8a8`. Root `0x3d82f8` is BSS and cannot be read as file-backed bytes.

The added source checks were inspected without invoking pytest or scenario functions. Strict C11 host syntax, host shared linking with `-z defs`, normal and ASan+UBSan fixture linking, AArch64 object compilation and original-2.25 AArch64 shared linking all passed. The **combined unchanged JPEG777 + actual bridge + updated memory provider** also linked against those original AArch64 libraries with `--no-undefined`, and its resolver export is strong/global. The compiler uses `-mno-outline-atomics`; actual version requirements are GLIBC_2.17. The scanf alias is checked against public libc SHA-256 `f9104526eb7e5d2ea533c1a209bb0b83e69367f569e4c966895c8e106e6382c9`, export `0x5e640/0x70`. The queued batch repeats the memory provider's original-ABI link when the installed cross tools are available.

## Run the parent batch

From this result root, after the parent joins the combined implementation:

```bash
python3 -m pytest runtime/analysis/test_functional_mpr_memory.py -q
```

The harness compiles the actual provider with the host-only original-writer/loader boundary fixtures and runs **21 separate scenarios** both normally and under ASan+UBSan: the original 15 mapping/provider scenarios plus source-derived SDS output, refusals/atomic bounds, retirement/ID-reuse/alias rejection, token capacity, failed-publication/foreign-ID collision, and all source-required still-config modes. The JPEG-output scenario uses the same real `GetUnitInfo` result and original config formulas to produce its actual body handle/position/capacity, rather than inventing independent matching tuples. The original fork scenario now covers SDS acquisition before inherited locks. The batch separately compiles production without host overrides, checks the unchanged five original mangled wrappers plus the new strong SDS export, verifies the actual ELF producer evidence, and links against original AArch64 libc2.25. The original `SetMemTbl` and original SDK JPEG producer are source-pinned host fixtures in these scenarios; native functional-profile integration remains required.
