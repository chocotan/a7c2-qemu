#!/usr/bin/env python3
"""Stage the previously reviewed Sony timer/SPACC/input VMState for a RAM candidate."""
import hashlib
import json
from pathlib import Path
import sys

INPUTS = {
    'hw/timer/sony_hwtimer.c': '050193cca7d211539430440f076d7edf15c70bb1275003369057e8d93b97c30b',
    'hw/misc/sony_spacc_stub.c': 'a99d1c98b620e401ca624504c2524688c63644f43faf7aa2e46c883aa90dbe06',
    'hw/input/sony-ui-input.c': 'd787ec495f9679b29f66678e0fd5314643f31fda19f3dd7704d46a41a474591a',
}
FIELDS = {
    'sony-hwtimer': ['epoch', 'snapshot_clock', 'count', 'control', 'compare', 'irq_level', 'timer'],
    'sony-spacc-stub': ['ram[65536]'],
    'sony-ui-input': ['held[KEY_MAX+1]'],
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
        timer_mod(s->timer, timer_expire_time_ns(s->timer) + shift);
    } else {
        return -EINVAL;
    }
    return 0;
}

static const VMStateDescription vmstate_sony_timer = {
    .name = "sony-hwtimer", .version_id = 1, .minimum_version_id = 1,
    .pre_save = sony_timer_pre_save, .post_load = sony_timer_post_load,
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
    .name = "sony-spacc-stub", .version_id = 1, .minimum_version_id = 1,
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
    .name = "sony-ui-input", .version_id = 1, .minimum_version_id = 1,
    .pre_save = sony_input_pre_save, .post_load = sony_input_post_load,
    .fields = (const VMStateField[]) {
        VMSTATE_BOOL_ARRAY(held, SonyUIInput, KEY_MAX + 1),
        VMSTATE_END_OF_LIST()
    }
};

'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError('RAM device-state source anchor drift: '+repr(old[:100]))
    return text.replace(old, new)


def transform(name, data):
    if name not in INPUTS or sha(data) != INPUTS[name]:
        raise ValueError('RAM device-state source SHA256 drift: '+name)
    text = data.decode()
    text = replace(text, '#include "qemu/osdep.h"',
                   '#include "qemu/osdep.h"\n#include "migration/vmstate.h"')
    if name.endswith('sony_hwtimer.c'):
        text = replace(text, '    int64_t epoch;', '    int64_t epoch, snapshot_clock;')
        text = replace(text, '    uint32_t count, control, compare;',
                       '    uint32_t count, control, compare;\n    bool irq_level;')
        text = replace(text, '        qemu_irq_raise(s->irq);',
                       '        s->irq_level = true;\n        qemu_irq_raise(s->irq);')
        text = replace(text, '            qemu_irq_lower(s->irq);',
                       '            s->irq_level = false;\n            qemu_irq_lower(s->irq);', count=2)
        text = replace(text, '        break;\n    case 8: s->compare = value; break;',
                       '        if (!(value & 0x10)) {\n'
                       '            return; /* ACK alone preserves the comparator deadline. */\n'
                       '        }\n        break;\n    case 8: s->compare = value; break;')
        text = replace(text, 'static void timer_class_init(', TIMER_STATE+'static void timer_class_init(')
        text = replace(text, '    DEVICE_CLASS(klass)->realize = timer_realize;',
                       '    DEVICE_CLASS(klass)->realize = timer_realize;\n'
                       '    DEVICE_CLASS(klass)->vmsd = &vmstate_sony_timer;')
    elif name.endswith('sony_spacc_stub.c'):
        text = replace(text, '    uint32_t *ram;', '    uint32_t ram[0x40000 / 4];')
        text = replace(text, '    s->ram = g_malloc0(0x40000);\n', '')
        text = replace(text, 'static void spacc_class_init(', SPACC_STATE+'static void spacc_class_init(')
        text = replace(text, '    dc->realize = spacc_realize;',
                       '    dc->realize = spacc_realize;\n    dc->vmsd = &vmstate_sony_spacc;')
    else:
        text = replace(text, 'static void sony_input_class_init(', INPUT_STATE+'static void sony_input_class_init(')
        text = replace(text, '    dc->realize = sony_input_realize;',
                       '    dc->realize = sony_input_realize;\n    dc->vmsd = &vmstate_sony_input;')
    return text.encode()


def stage(source):
    source = Path(source).resolve(strict=True)
    originals, patched = {}, {}
    for name, expected in INPUTS.items():
        path = source/name
        if path.is_symlink():raise ValueError('RAM device-state symlink input: '+name)
        originals[name] = path.read_bytes()
        if sha(originals[name]) != expected:raise ValueError('RAM device-state input drift: '+name)
        patched[name] = transform(name, originals[name])
    for name, data in patched.items():
        (source/name).write_bytes(data)
    return dict(schema='a7c2-ram-device-state-stage-v1',
                stage_source_sha256=sha(Path(__file__).read_bytes()), inputs=INPUTS.copy(),
                outputs={name:sha(data) for name,data in patched.items()}, fields=FIELDS,
                external_peer_policy='sony-ui-input pre_save/post_load reject an open chardev peer',
                default_enabled=False, actual_roundtrip_verified=False,
                physical_wbi_verified=False, full_machine_migration_audited=False)


if __name__ == '__main__':
    if len(sys.argv) != 2:raise SystemExit('usage: stage.py STAGED_QEMU_SOURCE')
    print(json.dumps(stage(sys.argv[1]), indent=2))
