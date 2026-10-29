# CP full-state snapshot: 76-block schema and pure assembly

This host-side library validates and assembles the nominal successful `0x2040`
packet from 76 caller-supplied getter fragments. Its only success claim is
`CP_FULL_STATE_SNAPSHOT_LAYOUT_ASSEMBLED`. Field providers and source dependencies
remain incomplete. It neither publishes nor advances a generation, applies AP
state, acknowledges mode1, sends a packet, or establishes native business, frame,
or capture success. No `2040` may be offered merely because this assembler exists,
including while CP3003 remains blocked at `0/4`.

Scope is the six new files listed below, public ALLLANG source readback, and host
self-tests. Existing `cp-state-snapshot.c/.h` and its tests are reused unchanged.
B8/CP-start-state data, AF68, video83, runtime mode1/transport/state integration,
and the later joint VM run belong to the parent work. No VM, observer build,
full-root build, network, private/full-system image, hardware, or physical SD was
used. This is an implementation report with `flavor = null`.

## Run the checks

From `report/2026-10-17-qemu-native-camera/`:

```bash
python3 -m pytest runtime/analysis/test_cp_full_state_snapshot.py runtime/analysis/test_cp_state_snapshot.py -q
```

The combined result is **8 passed**: four new pytest cases and four existing
snapshot regression cases. The two new C build cases use strict C11
`-Wall -Wextra -Werror -pedantic`, respectively ASan/UBSan and `-O2`. The raw public
source test skips only when the independently prepared public CP asset is absent;
it ran and passed in this workspace. The restored scratch artifacts are optional
outside the source workspace; their exact hashes and all 74 parseable successful
return lengths were also checked here. `analysis/sync_repo_scripts.sh --check`
also passed. SHA-256 comparisons confirmed the existing snapshot `.c`, `.h`, C
test and Python test remained byte-identical throughout this implementation.

The first combined run was `1 failed, 7 passed`: the C executable passed, but the
API-symbol assertion also saw ASan's `__odr_asan.cp_full_state_snapshot_blocks`
registration symbol. The assertion now excludes exactly that compiler symbol.
The complete combined suite was rerun after this correction.

## Supply published getter fragments

Include [cp-full-state-snapshot.h](../../runtime/analysis/device-models/cp-full-state-snapshot.h)
and link both snapshot C implementations. The public constant table
`cp_full_state_snapshot_blocks[CP_FULL_STATE_SNAPSHOT_BLOCKS]` contains exactly
76 `{command, offset, bytes}` entries. It describes successful layout; it contains
no field values, callbacks, defaults, provider state, or mutable global owner.

The assembler reuses `struct cp_state_snapshot_input` for each fragment:

| Member | Caller contract |
| --- | --- |
| `bytes`, `size` | Actual complete subpacket, including its 8-byte header; size equals that getter's nominal successful return length |
| `known`, `known_size` | Actual logical 0/1 knowledge mask; capacity covers the fragment and its entire declared span remains accessible |
| `generation` | Actual published provenance and caller-owned mutable/published/shadow metadata for that source |

For an already collected, quiescent array `fragments[76]`, a matching
`struct cp_state_snapshot_generation generation`, and a writable
`struct cp_state_snapshot output`, the call is:

```c
int result = cp_full_state_snapshot_assemble(fragments, 76, &generation, &output);
```

Exactly 76 fragments must be supplied in constant-table order. Every fragment
must match the size and header for that position: byte 0 is `6`, `u16le(+2)` is
the command, and `u32le(+4)` is **zero**. The word at `+4` is not a generation.
Zero-length, missing, refused, short, long, duplicate or reordered fragments are
rejected; the assembler never fills or silently skips one. A provider refusal
must remain absent/zero-sized/unpublished, rather than relabeling old or fabricated
bytes as the requested published generation. All four generation fields must
match the requested metadata; publication must differ from shadow. Mutable may
be ahead of publication; zero and wrap are accepted under the original inequality.

The assembler creates the outer `6/2040/zero` header. Its byte 1 is an explicit
**VIRTUAL reserved zero with `known=0`**, since the original producer does not
establish that source byte. All supplied fragment bytes and logical masks,
including fragment byte 1, are copied verbatim. Only the existing outer, `201b`,
and `2044` byte-1 exceptions allow unknown data. Unknown byte 1 of any other
fragment remains refused conservatively. Mask capacity beyond logical size is
not scanned, but is included in output-alias checks.

`cp_full_state_snapshot_copy(&input, &output)` takes a complete `0x6d4` packet,
checks all 77 headers (outer plus 76 subheaders), then calls the unchanged
`cp_state_snapshot_copy`. Assembly calls this same full validator before returning.
The shared helper retains all existing knowledge-mask, aperture/lens view, lens
enum, provenance and publication/shadow checks. No enum validator was duplicated
in the implementation.

Caller-owned source spans must remain immutable and quiescent through the call;
no pointer is retained. Output must not overlap the fragment descriptor array,
full-packet descriptor, generation input, any fragment bytes, or any byte of any
declared known-mask capacity. Read-only input spans may overlap each other. Span
wrap is rejected before dereferencing it. The caller still supplies valid aligned,
accessible C objects and a writable output object. On every error output is
unchanged; inputs are never modified.

| Result | Meaning |
| --- | --- |
| `0` / `CP_FULL_STATE_SNAPSHOT_LAYOUT_ASSEMBLED` | Layout and supplied bytes were checked/copied only |
| `-EINVAL` | Count, width, span, alias, mask value, or invalid shared provenance |
| `-EPROTO` | Outer or subheader type/command/zero-word mismatch |
| `-ESTALE` | Mixed fragment metadata, or publication equals shadow |
| `-ENODATA` | A required logical byte is unknown |
| `-ENOTSUP` | Consistently unpublished source, rejected by the shared helper |
| `-ERANGE` | Existing closed lens-domain validation failed |

## Source evidence and findings

The exact CP identity is SHA-256
`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`,
18,090,880 bytes, with `CP VA = raw offset + 0x108000`. The source is a raw ARM
firmware image; PE/ELF import/export tables do not apply to this bounded layout
check. No new binary survey or decompilation was performed. Evidence is pinned in
[source-pins.json](source-pins.json), including all 76 fixed pointers and length
load instructions; the raw function pointers include the Thumb bit.

| Evidence | Finding | Implementation / verification path |
| --- | --- | --- |
| E1: CP353c18 and RO table `D93660`, SHA `ea9a87ba0200e1dbe03212f02f8520c6e9dcfb00d3d57021d05e014d081d6962` | F1: The full path has 76 rows of `(command, getter pointer, zero)`, forced with `1`; it advances by each getter's actual return length | P1: Constant descriptor table; independent raw `<III>` comparison for every row and fixed Thumb pointer |
| E2: Restored 76 getter bodies, 74 constant return values; `2004` raw `8d53f2:8424` and `8d5734:2046`; `20a0` raw `8d99c8:9c20` | F2: Nominal successful sizes sum to `0x6cc`, plus 8 outer bytes gives `0x6d4`; some forced getters can still return zero after secondary I/O failure | P2: Exact per-fragment widths, zero-length refusal, all-76 raw return-load checks and restored-body comparisons |
| E3: CP353c18 per-block writes `6`, command, and zero at `+4`; outer `2040` follows the same layout | F3: All subheaders require validation; `+4` carries no generation | P3: Full validator checks every header; tests mutate all seven defined header bytes of every fragment |
| E4: [Authoritative nominal schema](../2026-10-27-after-302c/full-snapshot-layout.json) and existing snapshot helper | F4: `201b` is 20 bytes at `0x1c4`, `2044` is `0xa0` bytes at `0x2a8`; the existing three unknown-byte exceptions and closed lens domains remain authoritative | P4: Schema comparison, delegate to unchanged helper, exhaustive required-byte/mask checks, opaque-byte preservation and lens-domain rejection |
| E5: Host LAB fixture and sanitizer/optimized executions | F5: Assembly/copy succeeds for actual supplied nonzero LAB payloads and refuses malformed or inconsistent input atomically | P5: C asserts for widths, all 76 mixed-generation/missing cases, stale/wrap/provenance, order/duplicate, overflow, descriptor/generation/bytes/capacity aliasing and input immutability |

The separate incremental table `10fa3e4` has 150 rows and supplies no descriptor
or size to this full schema. The test fixture explicitly supplies nonzero LAB
payloads, `201b` words `{0xf4, 0xffff, 0x8000, 1, 0x201b}`, and a LAB lens wire state
`4` within the existing domains. These values are test data, not native defaults,
provider semantics or a usable camera state.

## Delivered files and remaining work

| File | Role |
| --- | --- |
| [cp-full-state-snapshot.h](../../runtime/analysis/device-models/cp-full-state-snapshot.h) | Early published two-function API and caller/knowledge/generation contract |
| [cp-full-state-snapshot.c](../../runtime/analysis/device-models/cp-full-state-snapshot.c) | Immutable 76-entry descriptor table, full-header validation and atomic pure assembly |
| [test-cp-full-state-snapshot.c](../../runtime/analysis/device-models/test-cp-full-state-snapshot.c) | Positive nonzero LAB fixture and guard/immutability assertions |
| [test_cp_full_state_snapshot.py](../../runtime/analysis/test_cp_full_state_snapshot.py) | Two strict C builds, independent schema/getter checks and optional raw public-source check |
| [source-pins.json](source-pins.json) | Exact public source/table/getter/return pins and explicit false capability flags |
| [README.md](README.md) | Reproduction, API and evidence handoff |

Layout and data assembly are complete for the nominal successful schema. The
library does not implement the 76 field semantics or secondary I/O services.
Actual virtual-model providers, publication ownership/history, generation changes,
CP3003 readiness, mode1 transport, AP application and any runtime send decision
remain parent integration work. Native/business, frame, capture and
`SourceDependenciesClosed` remain false. Joint runtime acceptance remains pending.
