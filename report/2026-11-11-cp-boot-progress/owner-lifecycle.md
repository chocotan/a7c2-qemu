# Native AP/CP Owner Lifecycle Guard

## Scope

This change closes the host-process lifecycle gap in the explicitly enabled `virtual-native-ap-cp-link-v1` diagnostic route. It is limited to local Linux/QEMU processes and regular files in a one-use pair directory. Implementation and host acceptance did not start an original AP/CP pair; the later v5 QEMU integration attempt is recorded below and did not execute original CP instructions. No real camera, physical disk, SD card, or firmware write was used.

The guard is cooperative: `flock` serializes the AP probe's normal QMP quit with the CP runner's continuation. It is not an atomic crash lock and does not prevent arbitrary same-UID processes from opening the run directory. Unexpected process death is detected with pidfds; it is not converted into a successful shutdown.

## Lifecycle

1. `run-native-ap.py` resolves the pair and binary paths, validates the fixed probe argv, and creates `ap-admission.claim` with `O_EXCL` before `execve`. The claim binds the host boot ID, owner PID and `/proc` start ticks, exact NUL-framed argv SHA-256, binary SHA-256, pair admission, and a random 128-bit run nonce. The PID/starttime survives `execve`; the probe rechecks the post-exec argv and generation before starting QEMU.
2. The native probe creates one `latest-ap-run.txt` pointer and one `ap-cp-control.lock` in a fresh run directory. After QMP connects, `SO_PEERCRED` supplies the actual QEMU peer PID/UID/GID. The probe binds those credentials to `/proc/<pid>` starttime, argv digest, executable device/inode/size/mode, the admitted binary digest, QMP socket inode, pair/run directory identities, claim digest, run pointer, and lock identity. The record is written once as `native-ap-vm.json` and read back.
3. Every native AP QMP `quit` runs through the shared lock helper. While holding the lock, the probe creates `qmp-quit.json` with `O_EXCL`, fsync/readback, sends the single QMP quit, and consumes the response. The marker cannot be overwritten to make a previous shutdown look new.
4. Before either CP `cont` (initial continuation and receiver re-arm), the CP runner first confirms QMP reports the CP paused, then independently verifies the AP claim, run pointer, owner process, QMP peer process and executable, lock inode/timestamps, and absence of the quit marker. It opens the same lock with `LOCK_NB`, repeats the checks under the lock, continues CP, and polls pidfds for both the AP probe owner and actual QMP peer QEMU. If either exits or changes generation, it requests QMP `stop` on its own CP and fails closed. CP shutdown remains QMP-only; no process signal is sent.

The pair claim, run pointer, lock, and owner record are intentionally one-shot (`O_EXCL`). A failed pair is not replayed or reset in place; a retry needs a fresh pair directory owned by the coordinator. The original-pair coordinator starts both launchers with the same `sys.executable`; manually using different Python interpreters causes a fail-closed argv mismatch before CP continuation.

The CP side uses nonblocking flock and refuses `cont` if AP quit already owns the lock. The AP side waits for the lock; CP re-admission includes full binary and stage hashes, so a cont check may hold the lock for seconds. If the CP owner hangs while holding it, AP normal quit waits rather than signaling or releasing the pair. The lock coordinates cooperative same-UID participants; it is not a defense against arbitrary same-UID interference.

## Host Acceptance

The first unified two-worker run found and retained eight failures: the fixed argv helper had been accidentally nested under `_digest`, and several fixtures still modeled the pre-guard owner/locking contract. Those failures are recorded in `analysis/scratch/cp-wait-20261111/native-owner-host-20261111/attempt1-failure.json`. The helper placement and fixtures were corrected; the production `O_EXCL` behavior was not weakened.

The final post-fix two-worker run passed **336 host tests**: 272 CP-boot tests across platform, stage, device, AP, and link contracts, plus 64 CP launcher/observer/owner tests. It includes negative cases for stale/reused PIDs, changed executable identity, altered QMP socket/lock, duplicate JSON keys, a quit marker, a busy lock, and AP owner/QEMU pidfd exit. The public summary is [`host-validation.json`](host-validation.json); a private receipt with local TMPDIR details is retained outside the product source tree.

These tests use local fixtures and fake process/socket identities. They do not demonstrate an actual QEMU QMP peer, original AP/CP execution, full boot, receiver entry, or device consumption.

The independent read-only review found no blocking F1-F3 defect. It confirmed the same-interpreter requirement (the pair coordinator uses one `sys.executable` for both launchers), called out blocking-lock latency as an operational limit, and noted that real `SO_PEERCRED`/pidfd behavior still requires a paired QEMU run.

## Paired-QEMU Integration Readback

The v5 coordinator fixed the v4 publication race by waiting for a complete `native-ap-vm.json` and `notify.sock`, then invoking the production owner checker before launching CP. In the actual v5 pair, the AP claim and `SO_PEERCRED` QMP peer bound to the same QEMU process; CP QEMU then started paused, fully loaded and RSP-read-back-verified its original input images, and pinned pidfds for both AP owner and AP QEMU.

The AP guest raised `guest exception monitor during settle` about 10.23 seconds after AP QEMU start. CP's initial continuation check ran after that owner generation had exited and refused `cont`; no CP instruction, receiver entry, or positive `cont` receipt was observed. This is an actual fail-closed refusal, not a successful original CP/AP boot. AP and CP QMP both confirmed normal quit with return code 0 and no signals; all tool/QEMU PIDs are absent, and the one-use pair lease remains retained. The sanitized main readback is [`native-pair-v5-owner-readback.json`](native-pair-v5-owner-readback.json); raw console, exception, and runtime receipts remain private under the analysis scratch tree.

The actual timing shows CP QMP startup roughly 3 seconds after AP QEMU start, with the first CP status query around 9.1 seconds into CP preflight; AP QMP quit was about 10.23 seconds after AP QEMU start. `run-native-cp.py` inherits the shared broker RSP parser, whose conservative 65,536-byte cap makes a 64 KiB readback chunk require two memory requests. The CP-only subclass now re-queries `qSupported` on its peer-bound RSP connection and caps to the verified QEMU 11.1.2 `MAX_PACKET_LENGTH=131104`; the shared broker and UI path remain unchanged, and complete input SHA readback remains mandatory.

The consolidated two-worker host gate passed **1,055 bridge/CP tests plus 512 product host tests**, with 49 product host cases skipped by their existing asset/display scope and zero failures. All nine parameterized/positive CP packet-size cases passed. The product receipt is [`host-validation-rsp-v16.json`](host-validation-rsp-v16.json). The gate did not start QEMU or execute firmware, so runtime timing, positive CP continuation, and the AP exception root cause remain unverified. The host AST fixture corrections and intermediate failed attempts remain separately preserved in the private scratch evidence.

## Remaining Boundary

The v5 owner-record barrier is now proven on the real local QEMU peer, and its pre-cont refusal was consumed. A fresh pair is needed only after the current source delta passes the two-worker host gate, its source freeze is closed, and the joint storage preflight passes. Do not replay v4 or v5. Keep `original_ap_consumption_verified`, `original_cp_consumption_verified`, `receiver_entry_observed`, and `full_boot_verified` false until actual guest execution crosses those boundaries. Capture, installation, physical compatibility, and real-hardware behavior remain unverified.
