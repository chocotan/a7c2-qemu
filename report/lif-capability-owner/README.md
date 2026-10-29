# Bounded LIF capability owner

This directory implements a caller-owned diagnostic capability cache from actual immutable received frame bytes. It consumes the unmodified authenticated public stage and accepts exactly one fixed command `01`, `07`, `08`, `09`, or `3d` in a type 2/3 frame. Capability commands copy their complete bodies to the evidenced P destinations; command 9 consumes the bounded handshake data/stores described in the [handshake contract](../lif-handshake-contract/README.md). It retains the entire received frame and exports known inputs to the existing bitmap builder. A separate dynamic receive entry calls the live bitmap owner's existing decoder for actual commands 5/6. It does not integrate into or modify the frozen runtime.

The authenticated public profile has byte `[0x20]=1`, while decimal offset `[20]=0`. The pinned source at `404e0e` reads hexadecimal `+0x20`. Its helper `a9096c` only reads the currently unknown byte `1b1a7b1`; it has no side effects. Therefore command bodies and other support bits can be consumed without inventing that value. Positive support results in `41..49` remain unknown unless another operand proves false; no supported/ready state is inferred.

The status fields are `diagnostic_only=1`, `owned_data_transport=1`, `original_cache_admission=0`, and `original_CP=0`. Parsing actual bytes is evidence of this owner's consumption; original CP frame-to-cache admission remains **UNVERIFIED**. There is no native capture, ACK, readiness, original queue admission, CP publication, generation, or `3003` claim.

## Build and verify

From the native camera root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  report/lif-capability-owner/test_capabilities.py -q
```

The 33 focused Python cases authenticate the public CP and ALLLANG files before selecting a stage, verify the unchanged 15 capability CP windows (7,796 bytes), the separate 16 handshake/enqueue windows (4,728 bytes), and the existing 48-byte mode binding, build strict C11 with `-Wall -Wextra -Werror -pedantic`, and run all 28 C scenarios again with ASAN/UBSAN. An additional check compiles the same C scenarios as AArch64, links firmware libc2.25, and executes all 28 under the prepared QEMU user binary. Its [minimal entry](original-abi-entry.c) calls the actual libc `exit` after `main`, preserving and flushing the original stdio output; each case requires rc0 and the complete `ok` marker. This remains HOST_TEST data, not original CP execution. Generated binaries and the authenticated stage fixture are written to pytest's temporary directory. No system VM, network, hardware, physical SD, private configuration, or full-system assets are used. Without the public assets the source-dependent cases report skipped.

Every normal copy-path scenario goes through real `cp_property_stage_init` and `cp_property_stage_consume` on unmodified authenticated bytes; capability initialization calls **`cp_property_stage_snapshot` directly**, with its actual guard. Context bytes are not accepted as a caller payload. The public-stage case checks successful initialization without changing the stage, unknown S43 when capability and mask are set, and known false S43 when the received capability bit is clear. Only an explicitly labeled HOST_TEST counterfactual subcase changes context to exercise the source context-zero early exit. They check nonzero command bodies, every copied byte, unknown poison storage, partial support, cache refresh ordering, both selector rows, Z boundaries, bitmap composition, rejection atomicity, errno, exact sequences, origin/PID, frozen stage, full output capacity overlap, pointer wrap, and typed alignment.

## Use the owner

1. Authenticate complete public CP and ALLLANG files and the selected initial stage according to [the existing stage contract](../cp-property-repository-contract/source-pins.json). Consume that immutable stage into the existing property stage owner with an even quiescent `cp_start_state_guard`, normally sequence 2.
2. Zero every byte of a `struct lif_capabilities_owner`. Under the caller's external lock, call `lif_capabilities_init(&owner, &stage, &actual_stage_guard, selector)`. The current authenticated public stage is accepted unchanged. Its unknown support-gate byte is represented by per-entry known flags rather than a fabricated value. Selector is an explicit separate input; it is not inferred from a mode. Selector 3 binds mask row 1; every other selector, including 1 and 2, binds row 0.
3. Submit actual accessible immutable receive bytes with `lif_capabilities_receive`. A matching `cp_lif_bitmap_guard` must have the same PID/origin and a strictly newer even sequence, normally 4, 6, 8, and so on. Neither input pointers nor borrowed bytes are retained.
4. Use `lif_capabilities_snapshot` or `lif_capabilities_export_bitmap` with the **exact current owner sequence**. The stage's immutable `source_sequence=2` stays separate as receive sequences advance. A failed call leaves all owner/input/output bytes unchanged and preserves `errno`.

The two guard origins are mapped explicitly: property `VIRTUAL_SOURCE` becomes LIF `VIRTUAL_SOURCE`, and `HOST_TEST` stays `HOST_TEST`. PID must equal `getpid()`. Caller serialization and accessible immutable buffers are prerequisites; these C APIs do not supply a mutex or certify an external process's memory. Full declared output capacity, including its unused tail, must be disjoint from the owner and guard. Only the defined output object is written on success.

For the optional handshake continuation, use the two independent reset-store APIs, receive capability frames and command 9, and explicitly consume the dispatcher event-9 prefix. `lif_capabilities_receive_dynamic` requires one external lock covering **both** capability and bitmap owners, the same guard PID/origin and a strictly newer sequence for both. It calls `cp_lif_bitmap_receive_decode` once on the real live owner after alias prechecks, retains its complete actual decode separately from the fixed receipt, and conditionally applies the evidenced command-5-before-6 state stores. Every error leaves both owners unchanged. No bitmap owner is cloned or reset to reuse a lease token.

## Initialization and knownness

P is explicit owned storage of 1,088 bytes with one known byte per storage byte. Initially every known flag is zero; storage contains diagnostic poison `a5`. The source pointer `*1a03cdc` is published by `a901fc` after construction with `3e164c(0x200, 0x440, 0x220, 0xe15)`. This provides **no proven native P initialization**, and the owner makes no zero-P or original CP state assertion.

Initialization explicitly models `a9073e`: clear all 100 support entries, set slot 1 to one, and mark those reset values known. It records `reset_sequence` separately from the initially absent support-refresh event. Handshake state, K and control flags remain **unknown**; initialization does not execute either new reset-store event. It binds the selector through `a907ba` and configures a 33-byte command 1 request: byte `01` followed by the actual 32-byte row at `f8f997 + row*0x20`. Request bytes are available in the snapshot, with source fingerprints in [source-pins.json](source-pins.json). Configuration alone does not enqueue or send the request.

The full owned 256-byte stage context comes from the existing public `CP_INITIAL_STAGE`/`CP_PRIMARY` owner. For that stage, context `[0x17]=0` and `[0x20]=1`; decimal `[17]` and `[20]` are both zero and must not be substituted for the source's hexadecimal offsets. With actual nonzero `[0x20]`, `a9096c` remains an unknown input to the affected support bits. Unknown/wrong repository, absent profile, wrong source guard, and frozen stage bytes are refused; the implementation performs no repair or caller-supplied zero-context bypass.

## Framing and fixed copies

Framing follows the existing received-frame source: `L=LE16(rx+1)` in `9..0x220`; receive extent is exactly `L`, or `L+1` with an exact final zero; start `f0`, end `55`; checksum is `sum(rx[1..L-4]) mod 65536 == LE16(rx+L-3)`. `flags=rx[3]`, type is `flags&7`, and opaque byte `[4]` is preserved. Types outside 1..3 are malformed; type 1 returns `-ENODATA` because the original `1b1aa10` gate is unmodeled. Type 2/3 fixed commands need no bitmap. The existing dynamic 5/6 decoder is unchanged.

The single command starts at byte 5. Its body includes the command byte, and `L` must equal `body_length+8`. Extra bytes, additional commands, and duplicate commands are rejected. Byte values within the fixed body are data, not recursively parsed commands.

| Command | Table row VA / exact bytes | Body bytes | P destinations | Support event |
| --- | --- | ---: | --- | --- |
| `01` | `1205542` / `010021002100` | 33 | `0..0x20` via `a957a4` | `a90720` after copy |
| `07` | `1205566` / `070002002300` | 35 | `0x21..0x43`, `0x116..0x138` via `40ba2a` / `40ba42` | No refresh |
| `08` | `120556c` / `08000900ca00` | 202 | `0x44..0x10d` via `40ad58` | `a9556a` refreshes support and requests state 2 in both branches |
| `09` | `1205572` / `090005000c00` | 12 | No P copy; immediate K/state stores or retained deferred body | No refresh; immediate/replayed path requests state 3 |
| `3d` | `12056aa` / `3d0018004000` | 64 | `0x139..0x178` via `40afe4` | No refresh |

The ordered four capability commands `01/07/08/3d` establish exactly **369/1,088** destination bytes; command 9 adds no P bytes. All other P bytes stay unknown and retain their poison. In command `3d`, A at body `[0x21..0x24]` maps to P `[0x15a..0x15d]`; D at body `[0x25..0x28]` maps to P `[0x15e..0x161]`. All 64 body bytes are retained.

## Z=0 boundary and cached support

Command 7 runs `a98fe8(LE16(body+0x0a))` before either copy. With actual context byte `[0x17]`, the source produces:

- Context 1: Z=1.
- Context 0: Z is `(value & 0xfff) != 0xfff && (value >> 14) >= 3`.
- Other contexts: Z=0.

This adapter accepts only computed Z=0. Computed Z=1 returns `-ENOTSUP` atomically, preserving receipt, sequence, P, Z and cached support. Commands 8, 9 and `3d` require known Z=0; command 1 may be consumed before Z is known. The header and API make no Z=1 command-blob normalization claim. Upgrade only after closing **all three complete normalizers**; the existing Kuna output for `a99082` ends at a false function boundary and is not a complete command 8 normalizer.

For `3d`, raw D bit 29 set returns `-ENODATA`: source flag `1b1ac73==1` could clear that bit before normalization, and the flag's value is unproven. When the raw bit is zero both flag paths agree, so the Z=0 copy is exact without inventing the flag.

On command 1 or 8, source `a90720` refreshes cached entries 0..99 using `404de0`: entry 1 is true. For `41..49`, context `[0x20]==0` proves false. With the actual public context value 1, the unknown pure getter is an additional gate: a known false capability/mask result still proves false, while a positive result remains unknown. Other entries use `offset=((c-1)&0xff)>>3`, `bit=1<<((c-1)&7)`, P byte `offset+1`, and selector mask row for Z=0 or mask `404e68` for Z=1. Per-entry knownness represents partial evaluation: a known clear capability bit proves false; a proven clear mask proves false; a known capability with identical mask bits proves the result even while Z is unknown. Remaining entries stay unknown, not false by default. `support_refresh_sequence` records only actual modeled refreshes. Computing Z in command 7 does **not** silently refresh or improve cached knownness.

## Local handshake continuation

The [handshake contract](../lif-handshake-contract/README.md) defines the exact boundaries. `lif_capabilities_consume_handshake_reset_store` applies only `a913d2`'s state=0/K=0 prefix. `lif_capabilities_consume_control_flags_reset` separately applies enabled=0/pending8=0/pending9=0 from `a948a8..a9491a`. Neither clears capability/support storage, pending body bytes or unrelated history. Command 8 requests state 2 after its actual copy/refresh; known old 0/1 commits, unknown or invalid old state does not. A successful copy is still a local byte receipt when the request cannot commit.

Command 9 is exactly 12 body bytes including `09`, hence 20 logical frame bytes with an optional exact final zero. The bounded source-header-independent subset requires body bytes 8 and 9 to be zero, known P+22, known Z=0 and known control-enabled. Other header-dependent body values return `-ENODATA`. Disabled control stores all 12 bytes and sets pending9 without changing K/state. Enabled control consumes only `a955da`'s local stores: P+22 low bits 2 and body byte 1 low bits 1/2 write shared K=5/2 respectively; other combinations preserve K. It then requests state 3, which commits only from known 2.

`lif_capabilities_consume_dispatch_event9_prefix` is an explicit local source operation: enable control, check pending8 first, then replay pending9. Unknown pending flags are refused; pending8=1 is unsupported because this adapter has no deferred8 producer. The source prefix does **not** clear pending9 after replay. Repeated event 9 can replay the same body and request state 3 again without an additional state write. Receive/refresh/K-store/request/commit/pending-body/event-9 sequences are separate readback facts.

`lif_capabilities_receive_dynamic` derives command presence from actual decoded bytes under the configured, actually consumed bitmap schema. Command 5 conditionally writes known state 3 to 4, then command 6 conditionally writes known 4 to 5, independent of wire order. These are direct writes, separate from the last setter request. Unknown state stays unknown; command 6 alone at state 3 does not advance it. The complete last dynamic result owns its fields/frame and never replaces the fixed receipt. Even modeled state 5 establishes no native AP state, CP generation, ACK, ready, worker `135f88`, publication, `3003` or output/capture.

The boot event-9 enqueue producer is **source-closed**: both logged/nonlogged boot paths call `a48f86 -> a96c7a -> a9699c`, which passes event 9/`ff` and the dispatcher descriptor to `50ff1c`. Actual message delivery and dispatcher execution remain unknown. Calling the explicit local prefix leaves `original_event_delivery=0` and `original_handler_executed=0`. Bitmap command `0a` construction/transport receipt does not supply command 9, event 9 or dynamic 5/6, and never advances handshake state.

## Bitmap export and remaining sources

Export includes P/known through `0x161`, Z/known, cached S43/S5a/known, and the validated stage's E-mode. The existing [mode consumer contract](../cp-property-repository-contract/source-pins.json) pins `40c278..40c2a8` (48 bytes, SHA-256 `25b804e82236b03332195cacb42b31f602e22753b1728d29cec1057206cfd0f4`), which writes the **same `1107178`** read by the bitmap builder; `eb5650` initializes that source to 3. The authenticated public stage consumes mode 1. `MODE_KNOWN` therefore exports the actual bound value. This E-mode is distinct from the start-state data owner's **M predicate**.

K initially remains unknown. A separate `lif_capabilities_consume_initial_kind_store` event executes only the original `a95856` prefix's local assignment: actual received `P+22 & 3` equal to 1 stores K=4 at `a95876`; equal to 2 stores K=1 at `a958a6`; both call `a909a4`, whose store target `1a03ad0` is exactly what `a909b0` reads. Missing P+22 returns ENODATA; types 0/3 return ENOTSUP, unchanged. This does not execute later calls, queues or original handler invocation. Command7 imports alone preserve the old K and never run this step implicitly. `k_store_sequence`, receive receipt and support-refresh sequence remain separate.

On initialization the bitmap builder refuses the export for missing K. The composition test consumes the actual command7 byte, invokes the local initial-kind store, re-exports K, and builds the real 25-byte bitmap command using the unmodified public context; it never assigns a fixture K=4. The separate handshake reset exports known K=0 only after its explicit source-store event, and applicable command-9 stores update the **same** K ledger. These are HOST_TEST frame bytes and local-source events, not native execution or original command `0a` delivery. The complete 100-entry support readback is diagnostic; the existing builder consumes only S43/S5a.

The initial-kind functions' later calls/delay/timer work are unmodeled. The callback `a95fa6` queues **event 2**, not event 9; there is no timer-expiry adapter. The 17-byte command-`0a` reply comparison writes the separate flag `1a03c8c`, not handshake state `1a03ac0`, and can return 0 on mismatch. No new reply API or state advancement from it is implemented.

No native frame-to-cache admission, complete Z=1 normalization, original P constructor state, original support callback execution, or camera capture path is established by this delivery. Runtime integration and additional providers remain separate work.
