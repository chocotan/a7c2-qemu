# Live input: observed AppFw allocation wait

Status: investigation in progress; manual input has not passed acceptance.

## Post-input stack

Evidence is local to `runtime/analysis/menu-runs/run-6wlpc06i/`:
`live-input-stack.txt` contains module mappings and the AppFw thread's frame
chain sampled after a manual DOWN request. This run identifies AppFw as TID 299;
that number must not be reused for another run.

- appFw mapping bias: `0x7f6076f000`.
- libosal_uipc mapping bias: `0x7fb5640000`.
- Frame return `0x7fb5646864`: libosal_uipc VA `0x6864`, inside
  `osal_valloc_msg_wait` (entry `0x67b0`).
- Frame return `0x7f61f04708`: appFw VA `0x1795708`, immediately after
  the allocation call at `0x1795704`.
- Further AppFw frame returns: `0x179a470`, `0x1796ef4`, `0x36ec1b0`.

Original instructions at appFw `0x17956f0..0x1795704` construct destination
`0x9088076b`, size `(x20 >> 32) + 8`, and allocation wait argument 1.
This sample places the thread in message allocation, rather than the input
receive loop. It does not establish that every historical failed run had this
same wait, nor that fixing this wait is sufficient to restore all controls.

The run's console contains 489 `SND_MSG_OTHER` records for destination
`0x9088076b`, each reporting 748 bytes. These are send-entry observations:
**489 is not an independently measured pending-queue length or successful-send
count**. No queue statistics or receiver ownership conclusion is inferred from
that count. Source `0xa5a5a5a5` is not used as sender identity.

## Actual wire samples

`runtime/analysis/menu-runs/run-qkinr3aj/gui-property-{0,1,2}.bin` were reconstructed
in offset order from bounded `GUI_PROPERTY_BYTES` records at send entry. This
observer captures at most three messages, does not receive/free these requests,
and sends no reply.

All three samples contain 748 bytes and are byte-for-byte identical:

```text
SHA256 11f59ba59721043ec09ae9b9ab22d3706180eac2809d49b2a7c54382d8da8b8a
first u32 words: 0, 0x2e4, 0x10, 0x274, 0, 1, 1, 0
```

The bounded follow-up investigation located the original CP consumer. CP
addresses in this paragraph are raw offsets (CPVA = raw + `0x108000`): task
`0x550c4a` receives from `0x9088076b` and calls distributor `0x67f84`. The AP
producer starts at appFw VA `0x1795688`. The first two words are zero and the
number of trailing bytes, followed by contiguous `{u32 type, u32 size, data}`
records with no alignment padding or record count. This packet contains:

| Type (hex) | Model | Size (hex) |
| --- | --- | --- |
| 10 | AFWindowInfo | 274 |
| 15 | ApertureInfo | c |
| 16 | ShutterSpeedInfo | 14 |
| 19 | RemoteFaceObjectTrackingInfo | c |
| 1a | RemoteTCUBInfo | 4 |
| 1b | RemoteAfWindowInfo | 10 |

The checked model bodies are inline, not AP pointers. The producer retains its
model cache and sends all nonempty entries each time; identical successive
packets therefore do not by themselves indicate erroneous retransmission.

The CP AF path `0x53a0d0 -> 0x539e28 -> 0x53a26c` validates the 628-byte
body and writes a protected 32-version ring, with change notifications through
`0x549a52 -> 0x64260` to subscribed `0x92900778..0x9290077c` endpoints.
The receiving task frees the message after dispatch; there is no business ACK.
The AP widget drawing path is a separate consumer of widget trees, not a decoder
for this protocol. Version/subscription effects and the final CP rendering
connection still require implementation evidence.

`runtime/analysis/gui-model-wire.c` now strictly decodes these six inline types,
rejecting unknown types, wrong sizes, duplicates, truncation and trailing bytes
without modifying its output on failure. ASan/UBSan testing passed nine packet
cases. That initial parser-only check did not constitute
a CP model service or an input repair. Merely draining/freeing messages or
returning allocation success would not constitute a consumer implementation.

## Explicit virtual state endpoint (bounded GTK input acceptance passed)

The owner approved a bounded software state endpoint and a fixed exposure
fixture. `MENU_GUI_MODELS=virtual-six-v1` is default-off globally and explicitly
selected by the natural-boot launcher. It requires the existing headless OSD
startup checks, an exclusive per-boot claim and no conflicting queue callbacks.

Destination `0x9088076b` has nonzero `id & 0x70000000`, which the original
kernel routes through its CP/public forwarding handler. It cannot be served by
merely starting another ordinary userspace receive loop. The enabled observer
therefore handles this one destination synchronously in its sender process.
No other destination is redirected by this endpoint.

`gui-model-store.c` validates and copies the inline values, atomically saves
`/tmp/gui-model-state.bin` through `hosd_persist` (including fsync and byte
readback), then frees the original message with its original owner ID. It sends
no reply. Transport success means that the endpoint accepted ownership; a
subsequent processing fault is sticky and is surfaced by `GUI_MODEL_FAILED`.
Future requests are rejected with their caller still owning them. This is an
explicit virtual AP state store, **not an implementation of the original CP
subscription or query protocol**.

The current 860-byte `GMDL0002` snapshot contains original model bytes, local transaction
generations, change bits and the last input FNV64. Its fixed F4, 1/125-second,
ISO100 fields are separately labelled virtual exposure metadata: original guest
exposure queries are not yet connected to them. Local generations must not be
CP versions. The original AF version range `0x20..0x5f`, default
write and 32-slot query interface remain separate unimplemented CP behavior.

An independent review identified a shutdown handoff race: stop could be set
between accepting pending input and the step's initial stop check. The fix
retains caller ownership and returns failure if the step did not take the
message. Owner publication now uses release/acquire and startup has an atomic
once claim. ASan/UBSan tests cover 12,000 concurrent sends with stop transitions,
fork rejection while the parent holds the service mutex, duplicate startup,
caller-owned rejected input, commit-before-free and processing failures.

The natural launcher now uses the separate original `inject-key --app` helper
for complete 32-byte press/release messages. The experimental single-slot file
mailbox is no longer selected by this profile. This change alone is not an
input acceptance result. Mandatory post-key ptrace sampling is disabled in the
normal path, and temporary unbounded receive/send console mirrors were removed
after they corrupted a menu-only snapshot export. Full observer file records
remain available.

Targeted tests passed: four tests and 21 subtests. The subsequent actual GTK run
`run-l4we7h7v` passed mouse DOWN/ENTER and keyboard UP, including repeated
navigation after 60 seconds. Read-back model commits increased from 753 to 4217.
Main-session visual review and six exact window-LCD crop comparisons also passed.
See [the bounded acceptance report](gtk-live-input/README.md) for source identity,
images, the failed exporter attempt and remaining functionality limits.

## Menu-only comparison

The user's earlier menu-only version had working controls. The current launcher
retains two distinct profiles in `runtime/analysis/start-menu.py`:

- Menu-only: `MENU_APPLY_MENU=1`, eight-second settle, separate `inject-key`
  command transport.
- Natural boot when the failure was investigated: additional finite device
  services, twenty-second settle, `MENU_LIVE_KEY_FILE` mailbox. The repaired
  profile uses `inject-key --app` instead and has no automatic first-boot input.

These are independent differences in startup and input transport. Neither
"the old version had less load" nor "timing was the only cause" has been
demonstrated. Running the old profile on current shared code is also not the
same as reproducing the historical source revision. Comparison must retain
each run's frozen source identity and actual LCD images.

Required acceptance remains actual UP/DOWN highlight movement and ENTER page
progression through manual controls, including after sustained operation.
