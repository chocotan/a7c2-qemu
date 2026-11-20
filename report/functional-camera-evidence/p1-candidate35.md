# P1 candidate 35 — non-lens gate identified: exclusion 0xcb9 & ee_status

Schema: `a7c2-capture-p1-candidate35-report-v1`
Date: 2026-11-16
Workers: 52dfdfb7 (probe + first run + integration), main session (retry takeover,
static adjudication), 0ac52939 (static deep-dive, dual independent checks).

## Findings

1. **The shutter gate is not the lens.** Run `4d33` fast sampling before the
   shutter: `REC_STILL/option=0/transition=0`, `lens_retracted_status=0`,
   inhibit byte and count = 1, `ee_status=0`; original half/full-press reached
   `SHUTTER_FLOW`/`SHUTTER_API` and read `ee_67700=0` directly. No natural
   `0x4038`. LCD consumption never stopped (OSD persisted to frame 2048 in
   run 34) — earlier "stuck at touch page" interpretation withdrawn.
2. **0xcb9 is the forbidden action, not a cause.** It is
   `execute_cap_seq` (kind 8, API 0x3d80) with **13 parameters and 19 static
   inhibition entries**, including EE (`0x7b`/model `0x304 ee_status`,
   `EE_NOT_RUNNING → 0x1294`), lens (skipped by user directive), focus/zoom
   init errors, date/time status, streaming modes, and internal features.
3. **EE state machine fully mapped.** State array `0x7e340d0..0x7e4d120`
   (4270×24B); EE row `0x7e34c58`. Generic accessor table `0x5584c38`
   (stride 0x30/model, EE row `0x558dcf8`, write-current slot `0x558dd10` →
   `0x276b148`). The real writer in the mode sequence is
   `0x338d998 @ 0x338d9ec..f4` (`str w1,[current_ptr]`), reached at the tail
   of `enter_rec_still_mode_proc` (`0x339fc70` write, `0x339fc78` commit).
   The entry probe reading `ee_status=0` is the pre-transition state and
   alone cannot prove the transition failed.
4. **Mailbox/broker never attaching is systemic but not conclusive.**
   `FUNCTIONAL_CAMERA_MAILBOX` appeared 0 times in every historical run;
   the eight bridge-init sites are observer message routes with stage-only
   fallbacks, so zero records do not prove the original AP never called the
   interface.

## Runs

- `4d33` (first, probe off): clean quit rc0, no signals, lease to exit.
- `9478` (retry, `MENU_CAPTURE_INHIBIT_TRACE=1`): 29 ×
  `CAPTURE_INHIBIT_SOURCE source=0xcb9 caller=0x246f620` (return address in
  apply_inhibit_table `0x246f54c`; `set_inh_status@0x246f404` =
  `exclusion_manager.cpp:704`, refcount array `0x7f18d28`). Clean quit rc0,
  `returncode=0`, `signals_sent=[]`. Four fast-gate snapshots: pre-shutter
  `capture_inhibit=1 ee_status=0 focus_init_error=1 zoom_init_error=1
  date_time_set_status=1 system_mode=2 media_mount_state_slot1=2
  lens_retracted_status=0`.
- Result still `failed: Functional broker never attached`;
  `capture_verified=false`.

## Integrity

- Product changes: `menu-observe.c` (`MENU_CAPTURE_INHIBIT_TRACE=1`,
  observation-only, original instructions replayed including `tst` flags),
  `capture_gate_readback.py` (u8/u32 read fix + identity checks) with
  regressions; binding `derive-prod-4b098785d95783b2` (CPIO `4d2c6a38…`,
  observer `365722c6…`). Restore manifest in candidate35.
- Static evidence: `candidate35/ee-static/REPORT.md` + raw table dumps;
  dual independent checks passed (19 entries vs ELF byte-exact); 3,629,056 B
  retained, 0 reclaimed; `1,906,027,352,064 B` available at last reading.
- No QEMU signals; no product gate logic modified; no real device, real CP,
  JPEG encode, or card-write validation.

## Next (candidate 36, in progress)

Read back the 13 exclusion rows (24B each) + EE current/shadow at shutter
time, observe `0x339fc70/0x339fc78`, collapse 19 candidates to the actually
active conditions, then implement the minimal honest fix.
