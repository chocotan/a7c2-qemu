# P1 candidate 34 — VDF panel-out backend, 0118→1118 closure, extended soak

Schema: `a7c2-capture-p1-candidate34-report-v1`
Date: 2026-11-15/16
Worker: 1e2a92c8 (implementation + integration + host acceptance), main session (runtime takeover and final accounting).

## Implementation (integrated, host-verified)

- `device-models/vdf-device.c/.h`: strict no-change 0118 subset — accepts only
  observed LCD-on/EVF-off requests, reads the installed headless output consumer
  state twice, then emits the correct 12B `1118`. Other configs refused; no
  fabricated pixel/hardware completion.
- `menu-observe.c`: routes the VDF backend; `4001` under `virtual-mode3-cold-v1`
  goes to the existing CP background parameter receiver (original `0x354768`
  saves four zoom config fields — not a shutdown command per se).
- New `test_vdf_panel_out.py` + `device-models/test-vdf-panel-out.c`, registered
  in `tools/public-model-tests.json`. Host acceptance 2 threads / 2 groups:
  4 passed + 22 subtests; existing VDF C regressions under ASan/UBSan.
- Binding: `derive-prod-cea11c32e1b4618c` (derivation SHA
  `65ab37ce…`, CPIO `01561182…`, observer `7b55ff9d…`).

## Guest runtime (run `dd15`, taken over by main session)

- 0118 reached the bounded panel backend (`FULL_VDF_PANEL_OUT_NOCHANGE`, two
  consumer readbacks matched); AP thread tid=322 released `1118` with
  `FULL_VDF_NATIVE_REPLY_FREE cmd=0x118 rc=0`.
- The run soaked for **2.4 hours** (console 126,853 lines): UDATE to
  generation=3 (`virtual_completion=1`), `BACKUP_K_REPLY` generation=2
  (stage3 frozen + stage0, `data_bytes=1419512`, readback `a718b3aa…`),
  DMM 0x62a lifecycle (`allocated=1 opens=1`), full BB display-config chain
  (015a/0145/011b/0160/0150 intents recorded), periodic service active.
- QMP quit (unique ID), QEMU rc0, no signals, lease retained to exit, owner
  absent; result `status: failed` only on `Functional broker never attached`
  (mailbox dependency).
- The pre-positioned capture action (42) was gated by readiness; no natural
  `0x4038` / `natural-request-owned` was observed. LENS/display readiness
  conditions remain the P3 frontier.

## Measurement caveat (from worker, to honor)

`LENS_RETRACTED=1` from the run-33 field sampling may cross power-saving or
shutdown states; the pre-existing
`capture-gates-reader.c`/`capture-gates.py` samplers must be used before
treating lens state as a stable root cause.

## Remaining frontier (P3/P4)

1. Lens-extended state chain and shutter-forbidden counter clearing
   (`cp-retracted-producer.txt`: getter 0x8d740e → 0xa49b18 → 0xa9885a/0xa97de2).
2. Display consumption: pages are created but the LCD stays on the touch-guide
   frame; the applied/pixel path after 1118 needs the display consumer.
3. Capture readiness gate, then natural shutter → 0x4038 → JPEG → P4 write.
4. mailbox/broker still never appears (independent long-standing item).

## Integrity

Restore manifest `restore-manifest.json` (+ `restore/tools/` public-test-list
preimage); run evidence under `runtime-1/`; no reclamation performed.
