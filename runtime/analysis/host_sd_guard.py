"""Retain the bwrap parent when a host-backed disk has no verified save boundary."""
import json
import signal


def guard_shutdown(proc,run,verified):
    if verified or proc.poll() is not None:return
    report={'host_disk_save_verified':False,'retain_parent_until_vm_exit':True,
            'quit_sent':False,'terminate_sent':False,'force_kill_authorized':False,
            'reason':'Unsaved host disk: bwrap die-with-parent forbids parent exit; manual verified QMP recovery required'}
    try:(run/'host-sd-retained-owner.json').write_text(json.dumps(report,indent=2)+'\n')
    except OSError:pass
    # Block on process exit, not a polling loop; TERM/INT cannot drop bwrap ownership.
    handlers={number:signal.signal(number,signal.SIG_IGN) for number in (signal.SIGTERM,signal.SIGINT)}
    try:proc.wait()
    finally:
        for number,previous in handlers.items():signal.signal(number,previous)
