#!/usr/bin/env python3
"""Actual QEMU DFS selector requests/timer/status; no original UPM or clock claim."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from test_hardware import hardware, idle_lock

HERE = Path(__file__).resolve().parent
BASE = 0xf1388f50
OBJECT = '/machine/sony-dfs-test'


def prop(machine, name):
    return machine.qmp('qom-get', {'path': OBJECT, 'property': name})


def initialized(machine):
    machine.qmp('system_reset')
    assert prop(machine, 'phase') == 0 and prop(machine, 'completion-count') == 0
    assert machine.readl(BASE+16) == 0
    machine.writel(BASE+4, 0x101)
    assert prop(machine, 'phase') == 1 and prop(machine, 'faults') == 0


def submit(machine, mode):
    previous = machine.readl(BASE+16)
    completed = prop(machine, 'completion-count')
    machine.writel(BASE, 0x101)
    assert machine.readl(BASE+16) == previous and previous & 0x100 == 0
    machine.writel(BASE+12, 0x100 | mode)
    machine.qtest('clock_step 10000')
    assert machine.readl(BASE) == 0x101 and machine.readl(BASE+16) == previous
    assert prop(machine, 'completion-count') == completed
    machine.writel(BASE+8, 1)
    assert machine.readl(BASE) == 0x101 and machine.readl(BASE+16) == previous | 0x100
    assert prop(machine, 'phase') == 4 and prop(machine, 'completion-count') == completed


def exercise(machine, enabled):
    tree = machine.qmp('human-monitor-command', {'command-line': 'info qtree'})
    assert ('dev: a7c2-virtual-dfs-selector,' in tree) == enabled
    if not enabled:
        machine.writel(BASE, 0x101)
        machine.writel(BASE+12, 0x104)
        machine.writel(BASE+8, 1)
        machine.qtest('clock_step 10000')
        assert machine.readl(BASE) == 0x101 and machine.readl(BASE+16) == 0
        return {'default_off': True, 'ordinary_ram_does_not_complete_dfs': True}

    initialized(machine)
    transitions = []
    for mode in range(7):
        for repeat in range(2):
            count = prop(machine, 'request-count')
            submit(machine, mode)
            assert prop(machine, 'request-count') == count+1
            machine.qtest('clock_step 999')
            assert machine.readl(BASE) == 0x101 and prop(machine, 'phase') == 4
            machine.qtest('clock_step 1')
            assert machine.readl(BASE) == 1 and machine.readl(BASE+16) == mode
            assert prop(machine, 'current-mode') == mode
            assert prop(machine, 'completion-count') == count+1 and prop(machine, 'faults') == 0
            machine.qtest('clock_step 10000')
            assert prop(machine, 'completion-count') == count+1
            transitions.append({'mode': mode, 'repeat': repeat, 'generation': count+1})
    # Original slow-to-slow first selects full(0), then a separate final target.
    for mode in (0, 5):
        submit(machine, mode)
        machine.qtest('clock_step 1000')
        assert machine.readl(BASE+16) == mode and machine.readl(BASE) == 1
    assert prop(machine, 'completion-count') == 16
    submit(machine, 6)
    machine.qmp('system_reset')
    machine.qtest('clock_step 10000')
    assert prop(machine, 'phase') == 0 and prop(machine, 'completion-count') == 0
    assert machine.readl(BASE) == 0 and machine.readl(BASE+16) == 0

    failures = []
    for kind in ('uninitialized', 'missing-target', 'mode7', 'wrong-arg', 'bad-width',
                 'unaligned', 'busy-rewrite', 'read64', 'status-write'):
        initialized(machine)
        if kind == 'uninitialized':
            machine.qmp('system_reset')
            machine.writel(BASE+8, 1)
        elif kind == 'missing-target':
            machine.writel(BASE, 0x101)
            machine.writel(BASE+8, 1)
        elif kind in ('mode7', 'wrong-arg'):
            machine.writel(BASE, 0x101)
            machine.writel(BASE+12, 0x107 if kind == 'mode7' else 1)
        elif kind == 'bad-width':
            machine.qtest(f'writeb {BASE+4:#x} 1')
        elif kind == 'unaligned':
            machine.qtest(f'writel {BASE+1:#x} 0x101')
        elif kind == 'busy-rewrite':
            submit(machine, 3)
            machine.writel(BASE+12, 0x104)
        elif kind == 'read64':
            machine.qtest(f'readq {BASE:#x}')
        else:
            machine.writel(BASE+16, 1)
        machine.qtest('clock_step 10000')
        assert prop(machine, 'faults') > 0 and prop(machine, 'phase') == 6
        assert prop(machine, 'completion-count') == 0 and prop(machine, 'current-mode') == 0
        machine.writel(BASE+4, 0x101)
        assert prop(machine, 'phase') == 6  # initialization is not fault recovery
        failures.append(kind)
    return {'transitions': transitions, 'two_transaction_slow_to_slow': True,
            'pre_trigger_never_completes': True, 'same_mode_requires_fresh_transaction': True,
            'timer_boundary_999_then_1_ns': True, 'reset_cancels_old_completion': True,
            'fail_stop_cases': failures, 'actual_clock_changes': False,
            'silicon_reset_or_timing_verified': False, 'original_upm_executed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    with binary.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    output = Path(tempfile.mkdtemp(prefix='dfs-selector-qtest-', dir='/var/tmp'))
    print('DFS_SELECTOR_OUTPUT', output, flush=True)
    result = {'scope': 'default-off virtual selector functional contract only',
              'binary_sha256': digest, 'selector_device_verified': False, 'capture_verified': False}
    try:
        with idle_lock(HERE.parents[1] / 'runtime/analysis/.menu-probe.lock'):
            for enabled in (False, True):
                run = output / ('enabled' if enabled else 'disabled')
                run.mkdir()
                machine = hardware.Machine(binary, run, False, dfs_test=enabled)
                try:
                    machine.connect()
                    # Machine starts with -S; qtest vCPUs execute no guest code.
                    machine.qmp('cont')
                    assert machine.qmp('query-status')['running']
                    result[run.name] = exercise(machine, enabled)
                finally:
                    machine.close()
        result['selector_device_verified'] = True
        print('DFS_SELECTOR_QTEST_PASS: target consumed, timer/status/readback, default off, faults/reset; no clock changes', flush=True)
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        (output / 'result.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
