# P1 candidate 10 — EE-entry investigation and Bluetooth virtualization

Schema: `a7c2-capture-p1-candidate10-report-v1`
Date: 2026-11-15
Task directory: `scratch/a7c2-capture-p1-runtime-20261115-candidate10/`

## Runs

| Run | Directory | Outcome |
| --- | --- | --- |
| first | `menu-runs/e491` | first-setup walked (language/accessibility/privacy/Creators' App via original App32 keys); `INFRA_NOTIFY_BLUETOOTH_ERROR` (BSA socket startup failure) → original system error → known shutdown BB:906/Imaging:3109 asserts; QMP quit rc0, no signals, lease to exit |
| retry | `menu-runs/a442` | `A7C2_VIRTUAL_HCI=virtual-rom-v1` binds `/simulation/start-bt-virtual.sh` over the original `startBTCore.sh`; original request starts original BSA; 310+ BSA traces and normal VHCI exchange; **no Bluetooth error, no system error, no BB/Imaging assert**; `sequence_boot::run` completes; OSD persists 1024 frames; first-setup walked by main session (9 keys, same sequence as first run); finish → original driver diagnostics → QMP quit, QEMU rc0, no signals, lease retained to exit, owner absent afterward |

Retry result receipt: `retry-1/result.json` (`status: failed` only because
`Functional broker never attached` — mailbox still not reached; every
lifecycle check passed). Independent verification: `retry-1/verification.json`
(2 groups / 2 threads, sources stable, guest whole-card SHA verified,
QMP quit, driver rc2, no signals, owner absent, lease to exit).

## Static conclusions

1. The Common-thread futex seen in candidate 9 is an empty-queue
   `std::condition_variable::wait` at `appFw+0x3209d48`; it does not indicate
   an EE-init hang.
2. `EE_ENTRY_SOURCE@0x7e5dd40` is misleading: it is Boot Factor `+8` returned
   by getter `0x285f8b0` and printed by `model::get_boot_factor@0x25c2c58`
   as `eecap`. The real `EE_STATUS@0x7e67700` commit point remains
   `enter_rec_still` (`0x339fc70 → 0x338d998`, model 0x304, value 1).
3. The production seed is an **empty card**: 1 GiB FAT16 with zero files
   (free 1,073,577,984 B, verified with `7z l -slt`). The earlier assumption
   that it contained DATABASE.BIN/MEDIAPRO.XML is wrong; the
   `A:/PRIVATE/DATABASE/DATABASE.BIN` open error `0x80000051` is consistent
   with a missing path. (Historical DATABASE.BIN verification used a
   different, already-written card.)
4. DMM `0x62a / -3`: `dmm-service.c` op20 accepts only unit `0x63a` and
   returns -3 for every other unit. The caller is
   `model_user_lut_files@0x3020f70 → 0x34d35e8 → 0x3552790 → 0x35521a0`,
   which allocates AP and CP side `0x62a` user-LUT resources. This is a
   known model coverage gap, not an uninitialized DMM service.

## Iteration chain (P1 runtime, cumulative)

OOM(DTB 6GiB) → 8GiB DDR; debugger basename → `/qemu-system-aarch64` bind;
`sequence_boot::run_i:1436 / 0x11` → `MENU_BUSPOWER=1`; `iCrypt_HasPublicKey`
→ `MENU_CRYPT_LIB=1`; BB/Imaging asserts → `MENU_RM_FILE_SLOT=1` (RM2) —
original `Fsys_Mount` then mounts the RAM card as `A:`; Bluetooth error →
`virtual-rom-v1`.

## Remaining frontier

- Mailbox still never appears; `Functional broker never attached` is the only
  failing acceptance item of the retry. The three FULL_IMAGING_*_CONNECT
  business events remain 0/0/0 and InfraBB→VEF predecessors stay unsatisfied.
- Candidate causes to investigate next, in order: the DMM `0x62a` user-LUT
  model gap (blocking `model_user_lut_files`, plausibly upstream of the
  Imaging chain), then why no `0x90050004` connect request is emitted.
- The seed being empty also means the database-initial path
  (stat-miss → create on `A:`) has never been exercised with real card
  content; a written card or an explicit create-path observation is still open.

## Evidence integrity

First-run failure and retry artifacts retained verbatim (`run-1-evidence/`,
`retry-1/`, `ui-*.raw/png/verified.bin`, `seed-directory.txt`,
`ee-source-callers.json`, `original-functions.txt`, `ee-source-functions.json`).
Product run sources unchanged this run. No real device, no QEMU signals,
no reclamation performed this round.
