"""One serialized SD export at a time; tombstones survive until guest teardown.

serial(command, timeout=..., cleanup=...) returns bytes. cleanup=True must bypass
GUI_MODEL_FAILED; timeout=None must wait without a host deadline. Kernel panic or
loss of console is an explicit unrecovered failure, never proof of cancellation.
"""
import re
import time


class BarrierError(RuntimeError):
    pass


def _sequence(sequence):
    if type(sequence) is not int or not 0 < sequence < 2**64:
        raise ValueError("sequence must be a positive uint64")
    return str(sequence)


def _line(raw, pattern):
    matches = re.findall(rb"^" + pattern + rb"\r?$", raw, re.M)
    if len(matches) != 1:
        raise BarrierError("missing or ambiguous barrier evidence: " + repr(raw))
    return matches[0]


def _reply(serial, seq, *, cleanup):
    path = f"/tmp/sd-flush.{seq}.reply"
    raw = serial(f"if [ -e {path} ]; then cat {path}; "
                 f"else echo SD_FSYS_ABSENT_seq={seq}; fi",
                 timeout=None if cleanup else 10, cleanup=cleanup)
    if re.search(rb"^SD_FSYS_ABSENT_seq=" + seq.encode() + rb"\r?$", raw, re.M):
        if re.search(rb"^SD_FSYS_FLUSH ", raw, re.M):
            raise BarrierError("contradictory reply evidence")
        return None
    pid, drive, rc = _line(raw, rb"SD_FSYS_FLUSH seq=" + seq.encode() +
                           rb" pid=([1-9][0-9]*) drive=([0-9]+) rc=(-?[0-9]+)")
    pid, drive, rc = int(pid), int(drive), int(rc)
    if pid <= 1 or not 0 <= drive <= 255 or not -(2**31) <= rc < 2**31:
        raise BarrierError("invalid flush owner/reply")
    return dict(pid=pid, drive=drive, rc=rc)


def _state_command(pid):
    return (f"grep -Fq /usr/lib/appFw.so /proc/{pid}/maps 2>/dev/null && "
            f"sed -n 's/^State:[[:space:]]*\\([A-Za-z]\\).*/\\1/p' /proc/{pid}/status")


def quiesce(serial, sequence, *, timeout=5.0):
    """Return only after original flush success AND observed group stop."""
    seq = _sequence(sequence)
    raw = serial(f"echo {seq} > /tmp/sd-flush.request.new && "
                 "mv /tmp/sd-flush.request.new /tmp/sd-flush.request && "
                 f"echo SD_REQUEST_seq={seq}", timeout=10, cleanup=False)
    _line(raw, rb"SD_REQUEST_seq=" + seq.encode())
    deadline = time.monotonic() + timeout
    while True:
        reply = _reply(serial, seq, cleanup=False)
        if reply:
            if reply["rc"]:
                raise BarrierError("original Fsys_FlushVolume rc=" + str(reply["rc"]))
            raw = serial(f"s=$({_state_command(reply['pid'])}); echo SD_STATE=$s",
                         timeout=10, cleanup=False)
            state = _line(raw, rb"SD_STATE=([A-Za-z]?)")
            if state == b"T":
                return dict(original_Fsys_FlushVolume_rc=0, sequence=sequence,
                            pid=reply["pid"], drive=reply["drive"], owner_stopped=True)
            if state not in (b"R", b"S", b"D", b"I", b"W"):
                raise BarrierError("flush owner exited or cannot be verified")
        if time.monotonic() >= deadline:
            raise BarrierError("flush/STOP timed out")
        time.sleep(0.05)


def cancel_resume(serial, sequence):
    """Arm cancel before reading reply; observe STOP before CONT, then verify it left T.

    Waiting after an rc=0 reply deliberately has no deadline: a deadline between
    guest's cancel lookup and SIGSTOP would reintroduce the late-stop race.
    """
    seq = _sequence(sequence)
    cancel = f"/tmp/sd-flush.{seq}.cancel"
    raw = serial(f"echo {seq} > {cancel}.new && mv {cancel}.new {cancel} && "
                 f"echo SD_CANCEL_seq={seq}", timeout=None, cleanup=True)
    _line(raw, rb"SD_CANCEL_seq=" + seq.encode())
    reply = _reply(serial, seq, cleanup=True)
    if reply is None:
        return dict(ok=True, sequence=sequence, status="cancel_armed_no_reply", resumed=False)
    if reply["rc"]:
        return dict(ok=True, sequence=sequence, status="flush_failed_no_stop", resumed=False,
                    original_Fsys_FlushVolume_rc=reply["rc"])
    pid = reply["pid"]
    ack = f"/tmp/sd-flush.{seq}.cancelled"
    # All interpolated values are validated integers. Commands touch guest /tmp and
    # this reply's appFw owner only; no user strings enter the shell.
    command = (
        f"while :; do s=$({_state_command(pid)}); "
        'case "$s" in '
        f"T) if ! kill -CONT {pid}; then echo SD_RECOVERY=CONT_FAILED; break; fi; "
        f"while :; do s=$({_state_command(pid)}); "
        'case "$s" in T) sleep 0.05;; '
        'R|S|D|I|W) echo SD_RECOVERY=RESUMED; break;; '
        '*) echo SD_RECOVERY=OWNER_LOST; break;; esac; done; break;; '
        f"R|S|D|I|W) if grep -qx 'SD_FSYS_CANCELLED seq={seq} pid={pid}' {ack} 2>/dev/null; "
        'then echo SD_RECOVERY=CANCELLED; break; fi;; '
        '*) echo SD_RECOVERY=OWNER_LOST; break;; esac; sleep 0.05; done'
    )
    raw = serial(command, timeout=None, cleanup=True)
    status = _line(raw, rb"SD_RECOVERY=([A-Z_]+)").decode()
    if status not in ("RESUMED", "CANCELLED"):
        raise BarrierError("flush owner recovery failed: " + status)
    return dict(ok=True, sequence=sequence, pid=pid, status=status.lower(),
                resumed=status == "RESUMED")
