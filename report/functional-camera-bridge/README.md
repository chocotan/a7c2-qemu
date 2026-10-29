# Functional-camera mailbox transport

The isolated `virtual-functional-camera-v1` transport moves actual C-model results from a dedicated, pinned guest mailbox into the original adapter's caller buffer. It records transport facts; AP capture, original MPR/Fsys storage, SD readback, and independent media decode remain separate acceptance gates.

**Verification state:** source and test fixtures pass compile/syntax checks. Runtime tests, sanitizers, a real QEMU connection, and the original AP→CMOS→encoder→MPR/Fsys→SD chain have **not** been executed by this worker. The user requested one joined test batch after the parent freezes the implementation. Do not describe this handoff as capture verification.

## Scope and files

This delivery follows the functional-profile authorization in the project `AGENTS.md`: local isolated QEMU, local Unix debugger sockets, virtual storage only. Original firmware, the HDMI UPM watcher, shared headers, VM configuration, QEMU builds, and physical media are outside this component's write scope.

| File | Purpose |
| --- | --- |
| [`functional-camera-bridge.c`](../../runtime/analysis/functional-camera-bridge.c) | Guest `init/call/close` implementation |
| [`functional_camera_broker.py`](../../runtime/analysis/functional_camera_broker.py) | Owned Unix RSP/QMP client and hash-bound ctypes core |
| [`test-functional-camera-bridge.c`](../../runtime/analysis/test-functional-camera-bridge.c) | Actual C implementation with explicit `FCAM_HOST_TEST` OS/fault boundaries |
| [`test_functional_camera_bridge.py`](../../runtime/analysis/test_functional_camera_bridge.py) | Fragmented Unix protocol, physical-page, lifecycle, and real-core tests |
| [`functional-camera-abi.h`](../../runtime/analysis/functional-camera-abi.h) | Parent-owned authoritative little-endian wire ABI |
| [`functional-camera-bridge.h`](../../runtime/analysis/functional-camera-bridge.h) | Parent-owned public guest API |
| [`functional-camera-core.h`](../functional-camera-core/functional-camera-core.h) | Actual synchronous model C API |

There is no host image-file source, subprocess encoder, host MP4/JPEG output, arbitrary guest-pointer access, original-code breakpoint, register write, or firmware patch in this implementation.

## Attach the host broker

The parent must finish the old HDMI UPM watcher's shutdown before calling `start()`. Passing `debugger_quiesced=True` asserts that this handoff has happened; it does not stop or take over another debugger. A missing socket, active existing client, invalid ownership, or absent coordination fails closed.

The broker requires two distinct, already-created **private Unix sockets** directly inside the owned run directory: a free GDB endpoint and a free QMP endpoint. Use an additional QMP monitor if the parent's main monitor already serves a persistent control client; this broker does not multiplex someone else's QMP stream. Both endpoints must have mode `0600`. It verifies the run is a direct nonsymlink child of `runtime/analysis/menu-runs`, the specified live QEMU process is an owner descendant, the actual executable matches the explicitly accepted SHA256, and the QEMU process owns each listening socket through `/proc/<pid>/net/unix` and `/proc/<pid>/fd`. A `/out/...` endpoint must resolve to this exact run's mounted directory. After connecting, `SO_PEERCRED` must identify that same QEMU PID and UID.

The parent supplies the actual values from the current run; no PID, nonce, PFN, socket path, or accepted binary hash is guessed:

```python
from functional_camera_broker import start


def attach(run, owner_pid, qemu_pid, mailbox, core_library,
           accepted_core_sha256, accepted_qemu_sha256,
           gdb_socket, qmp_socket, vm_coordination_lock,
           resume_allowed, previous_debugger_cleanup):
    if previous_debugger_cleanup.get('safe_to_close') is not True:
        raise RuntimeError('Previous debugger has not completed its shutdown')
    return start(
        run, owner_pid, mailbox, core_library,
        qemu_pid=qemu_pid,
        qemu_sha256=accepted_qemu_sha256,
        library_sha256=accepted_core_sha256,
        gdb_socket=gdb_socket,
        qmp_socket=qmp_socket,
        coordination_lock=vm_coordination_lock,
        debugger_quiesced=True,
        resume_allowed=resume_allowed,
        seconds=300.0,
        io_timeout=2.0,
    )
```

`mailbox` has exactly these keys:

```python
mailbox = {
    'phys0': actual_pages[0],
    'nonce': actual_nonce,
    'pid': actual_guest_pid,
    'pages': actual_pages,  # 16 actual physical page addresses, in logical order
}
```

Obtain them from the complete guest log line beginning `FUNCTIONAL_CAMERA_MAILBOX `. The guest emits `phys0=`, `nonce=`, `pid=`, `ABI=virtual-functional-camera-v1`, `version=1`, and `pages=` with 16 comma-separated hexadecimal physical addresses. Main must mirror this prefix before native requests start. Header contents must agree with all supplied values.

The shared library path must be a nonsymlink, owned, non-group/world-writable file. The broker hashes the open file descriptor against `library_sha256`, loads **that descriptor** through `/proc/self/fd`, binds `fcam_model_create/destroy/request`, and checks file identity again. Library loading creates no model. Only the first real `INIT` request creates a model, with `instance=mailbox.nonce`; the worker executes and destroys it on the same thread.

`start()` returns after the debugger is attached and physical mode 0 is confirmed. The `attached` receipt explicitly says `model_created=false`; it is not a hardware-ready or capture claim. Operational errors after start are available in receipts and the eventual cleanup result. An exception during startup carries `functional_camera_broker` and `functional_camera_cleanup` when a worker was already started, allowing the parent to inspect/finish cleanup.

### Coordinate pause, resume, and SD export

Use the same parent `threading.Lock` or `RLock` for broker windows, all parent QMP stop/resume decisions, and SDSTOP/export barriers. Its `acquire(timeout=...)` and `release()` methods are required. `resume_allowed()` runs while that lock is held and must be a quick, nonthrowing check of the parent's current barrier state.

Each copy window queries QMP status. A running VM is stopped for the mailbox copy and resumed only when physical mode has been restored and `resume_allowed()` remains true. An already paused VM stays paused. If restoration fails, the broker keeps a previously running VM stopped and records failure. The entire RSP copy window has a five-second deadline; restoring physical mode 0 gets its own bounded I/O attempt even after the copy deadline expires. Each individual RSP/QMP exchange is bounded by `io_timeout`.

RSP memory reads/writes obey the negotiated `PacketSize`, split at actual page boundaries, and translate every logical offset using the supplied PFN list. The implementation never assumes that the 16 physical pages are contiguous. `Qqemu.PhyMemMode:1` encloses physical accesses, and mode 0 is attempted in `finally`, including failed reads and failed enable requests. CPU registers, PC, TTBR, and original instructions are untouched. Actual C rendering/encoding runs outside these copy windows, while a previously running guest is resumed.

Before exporting virtual SD, the parent must quiesce original requests and stop this broker under its own lifecycle protocol. Calling `stop()` while retaining the coordination lock would prevent the worker from acquiring that lock for its final detach; release the lock after establishing the barrier, then stop and inspect cleanup. Never resume a paused SDSTOP merely to finish broker shutdown.

The client uses a clean socket disconnect rather than the RSP `D` command: some QEMU builds resume the VM unconditionally on `D`. Because this transport installs no breakpoints and changes no registers, disconnect requires no restoration of code or CPU state. QMP status is checked before and after disconnect; an unexpected transition is recorded as a cleanup failure, and an unexpectedly resumed previously paused guest is stopped again. Exact paused-disconnect behavior still needs the parent's real-QEMU integration test.

## Call the guest bridge

Build and link `functional-camera-bridge.c` into the parent's original-request adapter with its existing guest glibc 2.25 sysroot and pthread settings. No constructor performs a host probe or wait. Main explicitly calls:

```c
int rc = fcam_bridge_init(record);
```

Initialization requires 4 KiB guest pages. It allocates exactly 16 anonymous pages, applies `MADV_DONTFORK` to avoid parent-side COW changing advertised PFNs, commits every page, requires actual successful `mlock`, reads actual present/non-swapped PFNs from `/proc/self/pagemap`, rejects hidden/zero PFNs, duplicate pages, misalignment, and addresses outside `[0x400000000, 0x540000000)`, and reads a nonzero nonce from `/dev/urandom`. An unadvertised failed allocation is released. Successful initialization logs only the mailbox binding and returns without waiting for the host. Actual pagemap bindings are rechecked before every publication, after every response, and before close; a changed/unreadable PFN fails closed and retains the mapping.

The original adapter retains its real request through the call, supplies its native origin facts, and owns a separate output span:

```c
struct fcam_bridge_result transferred;
int rc = fcam_bridge_call(&actual_origin, opcode,
    request_payload, request_payload_bytes,
    original_destination, original_destination_capacity,
    &transferred);
```

The public operations are `INIT`, `STATE`, `CONFIGURE`, `AUTOFOCUS`, `STILL`, `VIDEO_BEGIN`, `VIDEO_FRAME`, `VIDEO_END`, and `CANCEL`. The bridge owns `READ_RESULT` and `RELEASE_RESULT`; callers cannot bypass its drain/readback protocol. The input must remain accessible and immutable until return; output must remain accessible and mutable. Input/output/result spans must not overlap. Origin source, destination, and original byte count must be nonzero. Validation of arithmetic and overlap cannot establish that arbitrary caller pointers are mapped; the original adapter owns that contract.

The process owner is checked **before** the mutex, so a forked child returns `-ECHILD` without touching an inherited lock. Thread-local reentry returns `-EDEADLK`, including recursive record callbacks. The process-local mutex covers each complete transaction. All public functions return `0` or negative errno and preserve the caller's `errno`.

Each call uses one 30-second guest `CLOCK_MONOTONIC` deadline, `nanosleep` waits, monotonic nonrepeating sequence numbers, bounded wire payloads, native origin metadata, and FNV1a64. A release-store of status 1 publishes the complete request. The host validates the request before entering C, stages actual returned bytes, checks exact physical readback, and commits status 2 **last**. The guest checks magic, ABI, PID, nonce, all 16 PFNs, sequence, opcode, native fields, reserved bytes, sizes, error range, result bounds, and FNV before using data.

For retained codec output, the guest checks the initial total before touching the caller buffer, drains `READ_RESULT(token,current_offset,capacity)` to the exact total, rereads each actual destination byte through volatile accesses, compares and hashes that readback, and rehashes the whole actual destination. It sends `RELEASE_RESULT(token,whole_destination_FNV)` only after all bytes match. `used` reports the whole output only after release succeeds. A real buffered video operation may return zero bytes according to the core contract; the broker does not invent this result.

### Interpret errors and partial transfers

| Result | Caller data and required action |
| --- | --- |
| `0` | `result.used` bytes reached the actual caller buffer; any retained result was fully read back and released |
| `-ENOSPC` | `result.required` contains the actual required size and `used=0`; no caller bytes were copied; any retained result is cancelled, with cancellation failures logged separately |
| Initial argument/protocol/hash error | Output and result remain unchanged, except the documented `-ENOSPC` result metadata |
| Error after a live drain starts | Output may contain an earlier validated prefix; result is not published as complete; transfer receipt records copied bytes/hash/error |
| `-ETIMEDOUT` or protocol/hash fault | Further calls are refused; attempt controlled close and retain pages unless detach is acknowledged |
| `-ECHILD` / `-EDEADLK` | Forked owner / reentrant call rejected before inherited-lock access or recursive locking |

Requests are executed using mailbox output capacity, independently of the caller's final destination capacity. An `-ENOSPC` return therefore does **not** undo a real configuration, AF, or codec operation. Its receipts preserve the actual model work and any cancellation/fault evidence; do not blindly replay an original native operation.

## Close without freeing host-owned pages

Guest shutdown publishes `FCAM_STATUS_CLOSED=3`. The broker finishes any current synchronous C call, suppresses its response if close arrived, explicitly attempts `CANCEL`, destroys the actual C model, then writes `FCAM_STATUS_DETACHED=4`. That acknowledgement is the **last RAM access**; it is followed only by protocol-mode restoration, logging, and socket cleanup. There is no memory readback after status 4 because the guest may immediately unpin/unmap.

`fcam_bridge_close()` verifies the unchanged header binding and detach acknowledgement before `munlock`/`munmap`. A 30-second timeout or validation failure keeps the mapping, reports `mapping_retained=1`, and refuses new calls or initialization. Close can be retried after a late acknowledgement. Failed cleanup is never reported as clean.

Host `watch.stop()` sets its stop event and joins for at most 35 seconds. It returns cleanup evidence. If actual C work is still running, it returns `safe_to_close=false`, leaves resources owned by the worker, and performs no forced termination or acknowledgement. Calling `stop()` again can collect eventual cleanup. No SIGKILL is used.

Inspect all of `worker_stopped`, `debugger_stopped`, `mailbox_detached`, `protocol_physmode_restored`, `safe_to_close`, and `errors`. A host-initiated stop can acknowledge status 4 without a guest status-3 request, after model destruction; an in-flight guest call fails and can then close safely.

## Read the evidence

`watch.read_receipts()` or `read_receipts(run)` returns complete JSONL records from the owned `functional-camera-broker-receipts.jsonl`. The writer creates it exclusively with mode `0600`. The reader ignores an incomplete final line while the writer is live and validates event ordering.

The records contain the accepted QEMU/core bindings, mailbox identity, raw request header and its SHA256, original source/destination/command/count/FNV, actual C result/error, returned byte count and hashes, token/total/offset, physical staged/committed readback, late-close discard, cancellation, physical-mode restoration, and detach/cleanup evidence. Guest `FUNCTIONAL_CAMERA_TRANSFER` records separately include the whole actual caller-destination readback and release outcome. They distinguish the validated returned prefix from `destination_written_bytes` and the actual destination FNV, including a chunk that failed destination verification. The broker's `data_readback` proves mailbox bytes, not native AP/MPR acceptance.

Evidence → finding → path for this implementation handoff:

| Evidence | Observation | Finding and path |
| --- | --- | --- |
| E-001: guest source plus successful native/AArch64 strict compile-only commands below | Real pin/pagemap path and explicit drain/close protocol are implemented | F-001, implemented/compile-checked: original adapter → pinned mailbox → actual caller output; runtime validation pending |
| E-002: broker source plus successful AST parse | Hash-bound ctypes calls and PFN-mapped Unix physical transport are implemented | F-002, implemented/syntax-checked: dedicated pages → actual model C API → staged readback → status-last response; runtime validation pending |
| E-003: C/Python fixtures, not executed by this worker | Component and fault assertions are available for the parent's joined batch | F-003, pending: guest close → stopped model → final detach ACK → unpin; no dynamic pass or capture claim yet |

## Run the joined tests after the parent freeze

From this result directory's root (`2026-10-17-qemu-native-camera`):

```bash
python3 -m pytest runtime/analysis/test_functional_camera_bridge.py -q
```

The batch compiles/runs actual guest C under normal and ASAN/UBSAN builds, tests fragmented Unix RSP/QMP, noncontiguous physical pages, wrong nonce/PID/PFNs, replay, bounds/FNV, short reads/chunks, actual destination readback, late close, retained timeout storage, paused/SDSTOP behavior, and mode restoration in `finally`. Host-only wrappers exist exclusively behind `FCAM_HOST_TEST`; production has no zero-PFN or fake-pin fallback.

The same batch builds the actual delivered core shared library and exercises it through ctypes and the fragmented mailbox. It needs the core dependencies and installed `pkg-config` libraries `libjpeg`, `libavcodec`, `libavformat`, `libavutil`, and `libswscale`. If core source/dependencies have not arrived, those specific tests explicitly skip. With an already accepted parent build, set both `FCAM_CORE_LIBRARY` and `FCAM_CORE_SHA256` to use that exact library instead. These tests keep codec bytes in memory and write only test build artifacts.

The commands below reproduce the source/syntax checks. The final compile-only pass also successfully linked the actual C fixture at `-O2` and at `-O1 -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer -fno-pie -no-pie`, and compiled the production source to an optimized AArch64 PIC object. `aarch64-linux-gnu-readelf -Ws` on that object showed no `fstat`, `getentropy`, or `newfstatat` imports. Build artifacts were temporary and deleted; no resulting executable was run.

```bash
cc -std=c11 -Wall -Wextra -Werror -pedantic -fsyntax-only -pthread runtime/analysis/functional-camera-bridge.c
cc -std=c11 -Wall -Wextra -Werror -pedantic -fsyntax-only -pthread runtime/analysis/test-functional-camera-bridge.c
aarch64-linux-gnu-gcc -std=c11 -Wall -Wextra -Werror -pedantic -fsyntax-only -pthread runtime/analysis/functional-camera-bridge.c
python3 - <<'PY'
import ast
from pathlib import Path
for name in ('functional_camera_broker.py', 'test_functional_camera_bridge.py'):
    path = Path('runtime/analysis') / name
    ast.parse(path.read_text(), filename=str(path))
    print(name, 'syntax OK')
PY
```

Cross-compiler syntax checks do not prove guest glibc symbol-version compatibility; the parent must use the existing original-glibc sysroot for the final link. The implementation avoids `fstat`, `getentropy`, `newfstatat`, and constructor-time host probing. `mlock` is the requested guest locking mechanism, not a kernel GUP pin: arbitrary guest page migration/hotplug is outside this transport's supported runtime, and a detected PFN change requires stopping the broker and retaining the guest mapping. A real QEMU integration pass and all downstream capture/storage acceptance remain outstanding.
