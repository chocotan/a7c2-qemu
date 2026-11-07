#!/usr/bin/env python3
"""Generate a pinned QEMU 11.1.2 source overlay; never modify its input tree.

Apply the four generated files only to an independent source/build copy. This
covers the listed custom state, not a complete camera machine audit. Connected
sony-ui-input peers block migration; file descriptors/host pointers never move.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

INPUTS = {
    'hw/timer/sony_hwtimer.c': '050193cca7d211539430440f076d7edf15c70bb1275003369057e8d93b97c30b',
    'hw/misc/sony_spacc_stub.c': 'a99d1c98b620e401ca624504c2524688c63644f43faf7aa2e46c883aa90dbe06',
    'hw/input/sony-ui-input.c': 'd787ec495f9679b29f66678e0fd5314643f31fda19f3dd7704d46a41a474591a',
    'hw/arm/virt.c': '13943b9197eb232180d4a068a3351ae5b820665deb2cd5f638f19f9a9dd2e577',
}
FIELDS = {
    'sony-hwtimer': ['epoch', 'snapshot_clock', 'count', 'control', 'compare', 'irq_level', 'timer'],
    'sony-spacc-stub': ['ram[65536]'],
    'sony-ui-input': ['held[KEY_MAX+1]'],
    'sony-media-detect': ['value', 'reads', 'writes'],
    'sony-mmc-trace': ['reads', 'writes', 'reset', 'base(equal)'],
}
TIMER_STATE = '''static int sony_timer_pre_save(void *opaque)
{
    SonyHwtimerState *s = opaque;
    s->snapshot_clock = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    return 0;
}

static int sony_timer_post_load(void *opaque, int version_id)
{
    SonyHwtimerState *s = opaque;
    int64_t shift = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) - s->snapshot_clock;
    s->epoch += shift;
    qemu_set_irq(s->irq, s->irq_level);
    if (!(s->control & 0x1000)) {
        timer_del(s->timer);
    } else if (timer_pending(s->timer)) {
        /* Keep remaining time even when the target clock origin differs. */
        timer_mod(s->timer, timer_expire_time_ns(s->timer) + shift);
    } else {
        return -EINVAL;
    }
    return 0;
}

static const VMStateDescription vmstate_sony_timer = {
    .name = "sony-hwtimer",
    .version_id = 1,
    .minimum_version_id = 1,
    .pre_save = sony_timer_pre_save,
    .post_load = sony_timer_post_load,
    .fields = (const VMStateField[]) {
        VMSTATE_INT64(epoch, SonyHwtimerState),
        VMSTATE_INT64(snapshot_clock, SonyHwtimerState),
        VMSTATE_UINT32(count, SonyHwtimerState),
        VMSTATE_UINT32(control, SonyHwtimerState),
        VMSTATE_UINT32(compare, SonyHwtimerState),
        VMSTATE_BOOL(irq_level, SonyHwtimerState),
        VMSTATE_TIMER_PTR(timer, SonyHwtimerState),
        VMSTATE_END_OF_LIST()
    }
};

'''
SPACC_STATE = '''static const VMStateDescription vmstate_sony_spacc = {
    .name = "sony-spacc-stub",
    .version_id = 1,
    .minimum_version_id = 1,
    .fields = (const VMStateField[]) {
        VMSTATE_UINT32_ARRAY(ram, SonySpaccStub, 0x40000 / 4),
        VMSTATE_END_OF_LIST()
    }
};

'''
INPUT_STATE = '''static int sony_input_pre_save(void *opaque)
{
    SonyUIInput *s = opaque;
    if (qemu_chr_fe_backend_open(&s->chr)) {
        error_report("sony-ui-input: disconnect/quiesce external peer before migration");
        return -EBUSY;
    }
    return 0;
}

static int sony_input_post_load(void *opaque, int version_id)
{
    return sony_input_pre_save(opaque);
}

static const VMStateDescription vmstate_sony_input = {
    .name = "sony-ui-input",
    .version_id = 1,
    .minimum_version_id = 1,
    .pre_save = sony_input_pre_save,
    .post_load = sony_input_post_load,
    .fields = (const VMStateField[]) {
        VMSTATE_BOOL_ARRAY(held, SonyUIInput, KEY_MAX + 1),
        VMSTATE_END_OF_LIST()
    }
};

'''
MEDIA_STATE = '''static const VMStateDescription vmstate_sony_media = {
    .name = "sony-media-detect",
    .version_id = 1,
    .minimum_version_id = 1,
    .fields = (const VMStateField[]) {
        VMSTATE_UINT32(value, SonyMediaDetectState),
        VMSTATE_UINT64(reads, SonyMediaDetectState),
        VMSTATE_UINT64(writes, SonyMediaDetectState),
        VMSTATE_END_OF_LIST()
    }
};

'''
MMC_STATE = '''static const VMStateDescription vmstate_sony_mmc = {
    .name = "sony-mmc-trace",
    .version_id = 1,
    .minimum_version_id = 1,
    .fields = (const VMStateField[]) {
        VMSTATE_UINT64(reads, SonyMmcTraceState),
        VMSTATE_UINT64(writes, SonyMmcTraceState),
        VMSTATE_UINT32(reset, SonyMmcTraceState),
        VMSTATE_UINT64_EQUAL(base, SonyMmcTraceState),
        VMSTATE_END_OF_LIST()
    }
};

'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError('Source anchor drift: ' + repr(old[:100]))
    return text.replace(old, new)


def transform(name, data):
    if name not in INPUTS or sha(data) != INPUTS[name]:
        raise ValueError('Source SHA256 drift: ' + name)
    text = data.decode()
    text = replace(text, '#include "qemu/osdep.h"', '#include "qemu/osdep.h"\n#include "migration/vmstate.h"')
    if name.endswith('sony_hwtimer.c'):
        text = replace(text, '    int64_t epoch;', '    int64_t epoch, snapshot_clock;')
        text = replace(text, '    uint32_t count, control, compare;', '    uint32_t count, control, compare;\n    bool irq_level;')
        text = replace(text, '        qemu_irq_raise(s->irq);', '        s->irq_level = true;\n        qemu_irq_raise(s->irq);')
        text = replace(text, '            qemu_irq_lower(s->irq);', '            s->irq_level = false;\n            qemu_irq_lower(s->irq);', count=2)
        text = replace(text, '        break;\n    case 8: s->compare = value; break;',
                       '        if (!(value & 0x10)) {\n'
                       '            return; /* ACK alone preserves the comparator deadline. */\n'
                       '        }\n        break;\n    case 8: s->compare = value; break;')
        text = replace(text, 'static void timer_class_init(', TIMER_STATE + 'static void timer_class_init(')
        text = replace(text, '    DEVICE_CLASS(klass)->realize = timer_realize;',
                       '    DEVICE_CLASS(klass)->realize = timer_realize;\n    DEVICE_CLASS(klass)->vmsd = &vmstate_sony_timer;')
    elif name.endswith('sony_spacc_stub.c'):
        text = replace(text, '    uint32_t *ram;', '    uint32_t ram[0x40000 / 4];')
        text = replace(text, '    s->ram = g_malloc0(0x40000);\n', '')
        text = replace(text, 'static void spacc_class_init(', SPACC_STATE + 'static void spacc_class_init(')
        text = replace(text, '    dc->realize = spacc_realize;', '    dc->realize = spacc_realize;\n    dc->vmsd = &vmstate_sony_spacc;')
    elif name.endswith('sony-ui-input.c'):
        text = replace(text, 'static void sony_input_class_init(', INPUT_STATE + 'static void sony_input_class_init(')
        text = replace(text, '    dc->realize = sony_input_realize;', '    dc->realize = sony_input_realize;\n    dc->vmsd = &vmstate_sony_input;')
    else:
        text = replace(text, 'static uint64_t sony_media_detect_read(', MEDIA_STATE + 'static uint64_t sony_media_detect_read(')
        text = replace(text, 'static uint64_t sony_mmc_trace_read(', MMC_STATE + 'static uint64_t sony_mmc_trace_read(')
        text = replace(text, '            s->value = g_ascii_strtoull(detect, NULL, 0);',
                       '            s->value = g_ascii_strtoull(detect, NULL, 0);\n'
                       '            vmstate_register(NULL, 0, &vmstate_sony_media, s);')
        text = replace(text, '                s->base = bases[i];',
                       '                s->base = bases[i];\n'
                       '                vmstate_register(NULL, i, &vmstate_sony_mmc, s);')
    return text.encode()


def generate(source, output):
    source, output = Path(source).absolute(), Path(output).absolute()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError('Source and output must be separate trees')
    if any(p.is_symlink() for p in (source, *source.parents, output, *output.parents)):
        raise ValueError('Symlink source/output forbidden')
    originals, patched = {}, {}
    for name in INPUTS:
        path = source / name
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Symlink source forbidden')
        originals[name] = path.read_bytes()
        patched[name] = transform(name, originals[name])
    # Validate every input before creating any output.
    output.mkdir(mode=0o700)
    diff = []
    for name, data in patched.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        diff.extend(difflib.unified_diff(originals[name].decode().splitlines(True), data.decode().splitlines(True),
                                         fromfile='a/' + name, tofile='b/' + name))
    receipt = dict(schema=1, profile='qemu-device-retained-state-v1',
                   inputs=INPUTS.copy(), outputs={n: sha(d) for n, d in patched.items()}, fields=FIELDS,
                   external_peer_policy='sony-ui-input pre_save/post_load reject open chardev',
                   physical_wbi_verified=False, compiled=False, actual_roundtrip_verified=False,
                   device_migration={'complete': False, 'blockers': ['Adopted machine inventory and external owners need separate audit']})
    (output / 'device-state.patch').write_text(''.join(diff))
    (output / 'patch-receipt.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.source, args.output), indent=2))


if __name__ == '__main__':
    main()
