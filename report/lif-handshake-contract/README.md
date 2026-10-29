# Bounded LIF handshake data and local state contract

The existing [capability owner](../lif-capability-owner/README.md) now consumes the source-evidenced handshake stores and actual received commands through locally modeled state 5. Its inputs remain the unmodified authenticated public stage, immutable frame bytes, and explicit named local-source operations. Initialization leaves handshake state, K and control flags unknown. Every state/history field describes this owner only; native AP state, generation, ACK, readiness, publication, worker execution, `3003` and camera capture remain unestablished.

The **boot event-9 enqueue producer is source-closed**. Actual queue delivery and dispatcher execution remain unknown. The explicit dispatcher-prefix API never asserts that an original queue consumed a message. Original frame-to-cache admission at `a47448` remains **UNVERIFIED**. No runtime integration, queue framework, VM, network, hardware, physical SD, private configuration or full-system work is included.

## Reproduce the checks

From `report/2026-10-17-qemu-native-camera`:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  report/lif-capability-owner/test_capabilities.py -q
```

Result: **32 passed**. The original 24 Python checks remain covered; seven new C scenarios run both as strict C11 (`-Wall -Wextra -Werror -pedantic`) and with ASAN/UBSAN, and a separate Python source check authenticates the handshake windows, command-9 literal row and both boot BL targets. There are 28 C scenarios in total. Generated binaries and the selected authenticated stage fixture go only to pytest's temporary directory. Public CP/ALLLANG assets are prerequisites; absent assets cause source-dependent cases to skip. The parent owns the later combined whole-suite run.

[source-pins.json](source-pins.json) authenticates the full 18,090,880-byte public CP (`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`) and **16 windows / 4,728 bytes** with `VA = raw + 0x108000`. These are separate scope counts, with overlapping source regions, from the unchanged capability contract's **15 windows / 7,796 bytes**. The authenticated stage has context `[0x17]=0`, `[0x20]=1`, and E-mode 1. The unknown pure getter `a9096c` still gates positive support `41..49`. E-mode is not an extra M predicate; no native M/C register default is established here.

## Consume the bounded operations

All functions live in the existing `lif-capabilities.h/.c`; no second state or K owner is introduced. Use the existing PID/origin/even-quiescent guards. Each mutation requires a strictly newer sequence; snapshots/exports require the exact current capability-owner sequence. HOST_TEST stays HOST_TEST. Hold the caller's external lock and supply accessible immutable input storage.

| Operation | Consumed source effect | Deliberate stopping point |
| --- | --- | --- |
| `lif_capabilities_init` | Existing public stage binding, support reset and command-1 request configuration | State/K/control known flags remain false; neither handshake reset executes |
| `lif_capabilities_consume_handshake_reset_store` | `a913d2` prefix: `r4=0` at `a913de`, state store at `a913e8` with DMB, K store at `a913ee` | Only state/K become known zero; no P/support/control/body/history reset or later fields |
| `lif_capabilities_consume_control_flags_reset` | `a948a8..a9491a` modeled stores: enabled `1b1ac4e+0`, pending8 `+5`, pending9 `+6` become known zero | No pending-body fill or change to its known marker/history; other stores/helpers unmodeled |
| Fixed command 8 receive | Actual 202-byte `40ad58` body copy, `a9556a` support refresh, then request state 2 in both P-type branches | Only this local copy/refresh/store point; later helpers do not certify a complete native handler |
| Fixed command 9 receive | Validated actual 12-byte body: defer it or apply `a955da`'s K/state stores | Header-dependent nonzero body bytes 8/9 and Z=1 unsupported; no source cache admission claim |
| `lif_capabilities_consume_dispatch_event9_prefix` | `408d58` event-9 branch at `408efa`: enable, check pending8, replay pending9 | Explicit local prefix only; no queue admission/delivery/execution proof and no deferred8 producer |
| `lif_capabilities_receive_dynamic` | Real live `cp_lif_bitmap_receive_decode`, retained actual result, then conditional command-5-before-6 state writes | No original cache, worker `135f88`, semantic publication, ready/ACK or output promotion |

The handshake reset and control-flag reset are independent source functions and independent APIs. Initialization itself never runs either. Their sequence fields are separate from the original capability support `reset_sequence`.

### State requests and direct writes

The bounded `a908ea` setter records the request even when it cannot commit. Requests 0/1 are unconditional in source, request 2 commits only from known old 0/1, and requests 3..5 commit only from known old `request-1`. Public adapters expose only the source operations above, not arbitrary caller-selected state values. A refused state request does not turn a successful byte copy into an error. Unknown old state stays unknown.

Command 8 records request 2 after its copy/refresh. Enabled or replayed command 9 records request 3. Dynamic receive reproduces the **direct** stores from `405b22`: actual command-5 presence with known state 3 writes state 4 at `405d0c`, then actual command-6 presence with known state 4 writes state 5 at `405d4c`. Command 5 is checked first even when command 6 precedes it on the wire. These direct writes update `state_commit_sequence` without manufacturing another setter request. Other states, including unknown state, still receive actual bytes but do not advance.

### Command 9 framing and deferred body

The literal fixed table row at `1205572` is `09 00 05 00 0c 00`: the **12-byte body includes `09`**. Its logical frame is 20 bytes, optionally followed by one exact zero. Framing/checksum/type checks match the existing fixed receiver; type 1 remains `-ENODATA` because its source gate is not supplied to this fixed subset.

`40bae4` consults header `a91bc2()+24`: header `c06` permits arbitrary body bytes 8/9; other headers require both zero. The owner does not guess the unknown header. Its first supported subset requires **body[8]=body[9]=0** for all cases, plus known P+22, known Z=0 and known control-enabled. Missing inputs or other body values return `-ENODATA` without consuming bytes/sequence; Z=1 returns `-ENOTSUP`.

- Enabled exactly 1: P+22 low bits 2 with body byte 1 low bits 1 stores shared K=5; low bits 2 stores K=2. All other combinations preserve K. Then request state 3, which commits only from known 2.
- Enabled other than 1: set pending9=1 and copy **all 12 actual bytes** to the owned counterpart of `1b1ac5d`. Record the body known marker and source sequence. No K store or state-3 request occurs. Return 0 proves local consumption, not state advancement.

The authoritative K is the same `k/k_known/k_store_sequence` already exported to the bitmap builder, corresponding to `1a03ad0`. The existing explicit initial-kind store still selects P+22 low bits 1 → K=4, 2 → K=1. Capability frame 7 never executes that store implicitly. Tests derive K from actual received capability bytes and named stores; they do not inject K=4/5 as a fixture.

### Explicit dispatcher-prefix consumption

The source sets enabled=1, then checks/replays pending8 before pending9. This finite adapter has no deferred8 producer: unknown pending8 returns `-ENODATA`, nonzero pending8 returns `-ENOTSUP`. Pending9 must be known; if set, its actual body and current P+22 must be known. All refusal checks occur before changing enabled or state.

The source prefix does **not** clear the pending flags after replay. The owner preserves pending9, its body and original receive sequence. Repeating the explicit prefix can replay the same body and request 3 again; state already 3 does not receive another state write. Applicable K stores still execute again and receive a new K-store sequence. No command-9 receive, command-`0a` send/receipt, timer or initialization automatically invokes this API.

## Dynamic data and two-owner atomicity

Call `lif_capabilities_receive_dynamic(&capabilities, &bitmap, actual_rx, size, &guard)` under **one external lock covering both live owners**. Their PID/origin must match the same guard, and the guard must be newer than both sequences. Capability/bitmap/guard/RX spans, alignment, address wrap and all cross-object aliases are checked before calling the existing decoder. The full declared RX extent matters, including a tail beyond the logical frame.

The bitmap owner must have a configuration built from actual exported inputs and an actual transport receipt comparing all 25 bytes with its issued lease. Missing consumption returns `-ENODATA`; newer unconsumed configuration returns `-EAGAIN`. The adapter invokes `cp_lif_bitmap_receive_decode` **once on the real owner**, retains the local result, and performs only infallible copies/conditional stores after decoder success. No temporary live-owner clone or lease-token reuse occurs. A decoder/precheck error preserves both owners byte-for-byte and preserves `errno`.

Actual decoded command views determine command-5/6 presence; callers cannot pass arbitrary booleans or a guessed bitmap. `last_dynamic` retains the complete context, configuration/consumption identity, decoded fields and received bytes. `received5_sequence` and `received6_sequence` track their actual receipts separately. Compound 5/6 never replaces or pretends to be the single-command fixed `receipt`.

One tested chain on the unmodified public stage is:

| Guard sequence | Actual local consumption | Local handshake result |
| ---: | --- | --- |
| 2 | Initialization | State/K/control unknown |
| 4 | Handshake reset stores | State 0, K 0 known |
| 6 | Control-flag reset | Enabled/pending8/pending9 known zero |
| 8 / 10 / 12 / 14 | Capability 1 / 7 / 8 / 3d | 369 known P bytes; command 8 commits state 2 |
| 16 | Initial-kind store from actual P+22 low bits 1 | K=4 |
| 18 | Actual command 9 | All 12 bytes pending; state 2 and K=4 preserved |
| 20 | Explicit dispatcher event-9 prefix | State 3 |
| 22 | Same explicit prefix again | Request 3 recorded; state commit stays at 20; pending body retained |
| 24 / 26 | Actual bitmap request / all-25-byte transport consumption | No capability-owner mutation |
| 28 | Actual dynamic command 6 | State stays 3 |
| 30 / 32 | Actual dynamic 5 / 6 | State 4 then 5; fixed receipt stays at 18 |

Both compound wire orders `5,6` and `6,5` independently reach local known state 5 from known 3. The unknown-state chain remains unknown after the same actual bytes. Known nonmatching old states are preserved. State 5 still has `diagnostic_only=1`, `owned_data_transport=1`, `original_cache_admission=0`, `original_CP=0`, `original_handler_executed=0` and `original_event_delivery=0`.

## Boot enqueue producer and remaining boundaries

The source path is now closed on both branches of boot function `4b6bf4`: logged `sb==1` branch BL at `4b7174`, and nonlogged branch BL at `4b71e0`, target `a48f86`. Its B.W targets `a96c7a`, which sets `r0=9`, `r1=ff` and branches to `a9699c`. That function constructs five descriptor words `{a96a0b,0,408d59,0,0}` and calls `50ff1c(receiver=1a04258, descriptor, event=9, argument=ff)`. The pins and branch-target tests establish this static **boot enqueue producer**, not actual message delivery or dispatcher execution in an original run.

The initial-kind functions' later `a93760`, delay selection, special header handling and timer registration are not executed. Source computes the bounded 16-bit delay from context +80/+82, with zero-delay/type0/3 handling, registers callback pointer `a95fa7`, and stores timer field `1a040b4=0a`. The callback `a95fa6` queues **event 2** through `a9699c(2,ff)`, not event 9. This adapter implements no timer, expiry or callback thread.

A 17-byte command-`0a` reply through `a95f68 -> a9248e` compares a 16-byte bitmap with configuration and writes **another flag, `1a03c8c`**. It does not write handshake state `1a03ac0`; return 0 can describe a mismatch. The existing actual 25-byte outgoing transport receipt is necessary for this bitmap owner's receive policy but supplies no command 9/event 9/dynamic 5/6. No new `0a` reply API or state promotion is included.

## Evidence → findings → path

Scope/authorization is the delegated bounded host-only implementation described above; the firmware/assets were read only. There is no separate runtime timeline because no original run was observed. Documentation flavor is the plain contract template.

| Evidence | Immutable source / reproduction | Finding and implemented path |
| --- | --- | --- |
| E-1 | Full CP identity and first 11 windows in [source-pins.json](source-pins.json); `test_handshake_source_windows` | F-1, validated for local source semantics: independent state/K reset, control reset, requests, body defer/replay and conditional 5/6 writes; path through the named consumers above |
| E-2 | `handshake-*` scenarios in [test-lif-capabilities.c](../lif-capability-owner/test-lif-capabilities.c), strict and ASAN/UBSAN via the reproduction command | F-1, validated host behavior: byte retention, real schema/lease composition, unknown-state preservation, conditional K, duplicate replay and two-owner error atomicity |
| E-3 | Logged boot branch window `4b7168..4b7178` and its independently decoded BL target | F-2, source-proven logged boot enqueue path to `a48f86` |
| E-4 | Nonlogged branch `4b71ba..4b71e4`, thunk/argument/descriptor windows, branch/literal checks | F-2, source-proven nonlogged boot enqueue path through `a9699c -> 50ff1c`; actual delivery/execution unknown |

P-1 (`path_type=callflow`): explicit reset stores → actual capability copies → local initial-kind store → actual command-9 defer → explicit dispatcher-prefix replay → actual built/consumed bitmap lease → actual schema-decoded commands 5/6 → local state 4/5. Each step is covered by E-1/E-2. P-2 (`path_type=callflow`): both boot branches → enqueue thunk → event 9/`ff` descriptor call, covered by E-3/E-4. Residual boundaries are original delivery/cache admission, deferred8, full native handlers/timers, Z=1, worker/publication/output and capture; none is promoted by local state 5.
