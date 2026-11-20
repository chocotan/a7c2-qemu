/* SPDX-License-Identifier: GPL-2.0-or-later
 * Explicit functional panel: F1..F13 drive thirteen virtual switches.
 * F10..F13 are auxiliary virtual inputs without physical key identities.
 * Pressed=low, released=high and zero latch reset are virtual conventions,
 * not Sony key names, physical polarity, reserved-bit masks or reset values.
 * No IRQ, peer notification, ready/ACK generation or migration is implemented.
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "qapi/error.h"
#include "hw/core/irq.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/sysbus.h"
#include "migration/vmstate.h"
#include "ui/input.h"

#define TYPE_CP_KEY_GPIO "a7c2-cp-key-gpio"
#define CP_KEY_GPIO_PROFILE "virtual-cp-key-gpio-v1"
#define CP_KEY_GPIO_MMIO_SIZE 0x50
#define CP_KEY_GPIO_BANKS 3
#define CP_KEY_GPIO_KEYS 13

/* The separately supplied header contains only ordered official latch writes. */
#include "native-key-gpio-init.h"

OBJECT_DECLARE_SIMPLE_TYPE(CpKeyGpioState, CP_KEY_GPIO)

typedef struct CpKeyGpioBank {
    CpKeyGpioState *owner;
    MemoryRegion mmio;
    unsigned port;
    uint32_t dir, inen, portsel, wdata;
    uint32_t input_mask, input_driven, input_levels;
} CpKeyGpioBank;

struct CpKeyGpioState {
    SysBusDevice parent_obj;
    CpKeyGpioBank banks[CP_KEY_GPIO_BANKS];
    qemu_irq key17[3];
    QemuInputHandlerState *handler;
    char *profile;
    bool down[CP_KEY_GPIO_KEYS];
    unsigned logged, rejected, key_logged;
};

static const struct {
    QKeyCode qcode;
    uint8_t port, pin;
} cp_key_gpio_keys[CP_KEY_GPIO_KEYS] = {
    { Q_KEY_CODE_F1, 6, 3 },
    { Q_KEY_CODE_F2, 6, 4 },
    { Q_KEY_CODE_F3, 7, 18 },
    { Q_KEY_CODE_F4, 7, 19 },
    { Q_KEY_CODE_F5, 7, 20 },
    { Q_KEY_CODE_F6, 11, 20 },
    { Q_KEY_CODE_F7, 17, 9 },
    { Q_KEY_CODE_F8, 17, 12 },
    { Q_KEY_CODE_F9, 17, 18 },
    { Q_KEY_CODE_F10, 7, 17 },
    { Q_KEY_CODE_F11, 11, 9 },
    { Q_KEY_CODE_F12, 11, 18 },
    { Q_KEY_CODE_F13, 11, 27 },
};

static void cp_key_gpio_log(CpKeyGpioState *s, const char *op, unsigned port,
                            hwaddr offset, uint64_t value, MemTxResult result,
                            const char *reason, uint32_t mask)
{
    bool key_event = !strcmp(op, "key-down") || !strcmp(op, "key-up");
    unsigned *count = result != MEMTX_OK ? &s->rejected :
                      key_event ? &s->key_logged : &s->logged;
    unsigned limit = result != MEMTX_OK ? 64 : 128;

    if (*count >= limit + 1) {
        return;
    }
    ++*count;
    fprintf(stderr, "CP_KEY_GPIO virtualprofile=%s port=%u op=%s"
            " offset=0x%" HWADDR_PRIx " value=0x%" PRIx64
            " result=%u reason=%s mask=0x%08x log_limit_reached=%u"
            " physical_compatible=0\n",
            CP_KEY_GPIO_PROFILE, port, op, offset, value, (unsigned)result,
            reason, mask, *count == limit + 1);
}

static CpKeyGpioBank *cp_key_gpio_bank(CpKeyGpioState *s, unsigned port)
{
    for (unsigned i = 0; i < CP_KEY_GPIO_BANKS; i++) {
        if (s->banks[i].port == port) {
            return &s->banks[i];
        }
    }
    return NULL;
}

static uint32_t *cp_key_gpio_latch(CpKeyGpioBank *b, hwaddr offset)
{
    switch (offset) {
    case 0x00: return &b->dir;
    case 0x20: return &b->inen;
    case 0x30: return &b->portsel;
    case 0x40: return &b->wdata;
    default:   return NULL;
    }
}

static bool cp_key_gpio_latch_write(CpKeyGpioBank *b, hwaddr offset,
                                     uint32_t value)
{
    uint32_t *reg = cp_key_gpio_latch(b, offset & ~(hwaddr)0xf);

    if (!reg) {
        return false;
    }
    switch (offset & 0xf) {
    case 0: *reg = value;  break;
    case 4: *reg |= value; break;
    case 8: *reg &= ~value; break;
    default: return false;
    }
    return true;
}

static bool cp_key_gpio_accepts(void *opaque, hwaddr offset, unsigned size,
                                bool is_write, MemTxAttrs attrs)
{
    CpKeyGpioBank *b = opaque;

    if (size != 4 || (offset & 3) || offset > CP_KEY_GPIO_MMIO_SIZE - 4) {
        /* Validation runs before dispatch, so the write value is unavailable. */
        cp_key_gpio_log(b->owner, is_write ? "reject-write-shape" :
                        "reject-read-shape", b->port, offset, 0,
                        MEMTX_DECODE_ERROR, "value-unavailable-size-in-mask",
                        size);
        return false;
    }
    return true;
}

static MemTxResult cp_key_gpio_read(void *opaque, hwaddr offset,
                                    uint64_t *value, unsigned size,
                                    MemTxAttrs attrs)
{
    CpKeyGpioBank *b = opaque;
    CpKeyGpioState *s = b->owner;
    uint32_t *reg, data = 0, mask = 0;
    MemTxResult result = MEMTX_DECODE_ERROR;
    const char *reason = "unsupported-register-or-alias-read";

    if (size != 4 || (offset & 3)) {
        reason = "invalid-width-or-alignment";
    } else if ((reg = cp_key_gpio_latch(b, offset))) {
        data = *reg;
        result = MEMTX_OK;
        reason = "full-width-latch";
    } else if (offset == 0x10) {
        result = MEMTX_ERROR;
        mask = b->input_mask;
        if (!s->handler) {
            reason = "no-registered-input-producer";
        } else if ((mask = b->input_mask & ~b->input_driven)) {
            reason = "undriven-key-input";
        } else if ((mask = b->input_mask &
                    (b->dir | ~b->inen | ~b->portsel))) {
            reason = "key-requires-dir-input-inen-portsel";
        } else if ((mask = b->inen & b->portsel & ~b->dir & ~b->input_mask)) {
            reason = "unknown-enabled-gpio-input";
        } else {
            data = b->input_levels & b->input_mask;
            mask = b->input_mask;
            result = MEMTX_OK;
            reason = "producer-only-input-mask";
        }
    }
    cp_key_gpio_log(s, "read", b->port, offset, data, result, reason, mask);
    if (result == MEMTX_OK) {
        *value = data;
    }
    return result;
}

static MemTxResult cp_key_gpio_write(void *opaque, hwaddr offset,
                                     uint64_t value, unsigned size,
                                     MemTxAttrs attrs)
{
    CpKeyGpioBank *b = opaque;
    bool ok = size == 4 && !(offset & 3) && value <= UINT32_MAX &&
              cp_key_gpio_latch_write(b, offset, value);
    MemTxResult result = ok ? MEMTX_OK : MEMTX_DECODE_ERROR;

    cp_key_gpio_log(b->owner, "write", b->port, offset, value, result,
                    ok ? "full-width-latch-data-set-clr" :
                    "invalid-access-or-readonly-rdata", 0);
    return result;
}

static const MemoryRegionOps cp_key_gpio_ops = {
    .read_with_attrs = cp_key_gpio_read,
    .write_with_attrs = cp_key_gpio_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {
        .min_access_size = 4, .max_access_size = 4, .unaligned = false,
        .accepts = cp_key_gpio_accepts,
    },
    .impl = { .min_access_size = 4, .max_access_size = 4, .unaligned = false },
};

static void cp_key_gpio_drive17(CpKeyGpioState *s, unsigned index, int level,
                                const char *op)
{
    unsigned key = 6 + index;
    uint32_t bit = UINT32_C(1) << cp_key_gpio_keys[key].pin;
    bool connected = qemu_irq_is_connected(s->key17[index]);

    if (connected) {
        qemu_set_irq(s->key17[index], level);
    }
    cp_key_gpio_log(s, op, 17, 0x10,
                    level < 0 ? UINT32_MAX : level ? bit : 0,
                    connected ? MEMTX_OK : MEMTX_ERROR,
                    !connected ? "key-17-output-disconnected" : level < 0 ?
                    "key-17-output-unknown" : "key-17-output-callback", bit);
}

static void cp_key_gpio_event(DeviceState *dev, QemuConsole *src,
                              QemuInputEvent *event)
{
    CpKeyGpioState *s = CP_KEY_GPIO(dev);
    QKeyCode qcode;

    if (!s->handler || event->type != INPUT_EVENT_KIND_KEY) {
        return;
    }
    qcode = qemu_input_linux_to_qcode(event->key.key);
    for (unsigned i = 0; i < CP_KEY_GPIO_KEYS; i++) {
        CpKeyGpioBank *b;
        uint32_t bit;
        const char *op;

        if (qcode != cp_key_gpio_keys[i].qcode) {
            continue;
        }
        if (s->down[i] == event->key.down) {
            return;
        }
        s->down[i] = event->key.down;
        op = s->down[i] ? "key-down" : "key-up";
        if (cp_key_gpio_keys[i].port == 17) {
            cp_key_gpio_drive17(s, i - 6, !s->down[i], op);
            return;
        }
        b = cp_key_gpio_bank(s, cp_key_gpio_keys[i].port);
        assert(b);
        bit = UINT32_C(1) << cp_key_gpio_keys[i].pin;
        if (s->down[i]) {
            b->input_levels &= ~bit;
        } else {
            b->input_levels |= bit;
        }
        b->input_driven |= bit;
        cp_key_gpio_log(s, op, b->port, 0x10, b->input_levels, MEMTX_OK,
                        "virtual-pressed-low-released-high", bit);
        return;
    }
}

static const QemuInputHandler cp_key_gpio_handler = {
    .name = "A7C2 CP virtual thirteen-switch input panel",
    .mask = INPUT_EVENT_MASK_KEY,
    .event = cp_key_gpio_event,
};

static void cp_key_gpio_reset(DeviceState *dev)
{
    CpKeyGpioState *s = CP_KEY_GPIO(dev);

    memset(s->down, 0, sizeof(s->down));
    for (unsigned i = 0; i < CP_KEY_GPIO_BANKS; i++) {
        CpKeyGpioBank *b = &s->banks[i];

        b->dir = b->inen = b->portsel = b->wdata = 0;
        b->input_levels = b->input_mask;
        b->input_driven = s->handler ? b->input_mask : 0;
        cp_key_gpio_log(s, "reset", b->port, 0, 0, MEMTX_OK,
                        "virtual-zero-latches-released-input-mask", b->input_mask);
    }
    for (size_t i = 0; i < G_N_ELEMENTS(cp_key_gpio_init); i++) {
        const struct cp_key_gpio_initial_write *init = &cp_key_gpio_init[i];
        CpKeyGpioBank *b = cp_key_gpio_bank(s, init->port);
        bool ok = b && cp_key_gpio_latch_write(b, init->offset, init->value);

        /* Realize validates the entire immutable model-owned array first. */
        if (!ok) {
            abort();
        }
        cp_key_gpio_log(s, "init-write", init->port, init->offset, init->value,
                        MEMTX_OK, "official-ordered-latch-write", 0);
    }
    for (unsigned i = 0; i < 3; i++) {
        cp_key_gpio_drive17(s, i, 1, "reset-release");
    }
}

static void cp_key_gpio_realize(DeviceState *dev, Error **errp)
{
    CpKeyGpioState *s = CP_KEY_GPIO(dev);

    if (!s->profile || strcmp(s->profile, CP_KEY_GPIO_PROFILE)) {
        error_setg(errp, TYPE_CP_KEY_GPIO " requires explicit profile="
                   CP_KEY_GPIO_PROFILE);
        return;
    }
    if (!G_N_ELEMENTS(cp_key_gpio_init)) {
        error_setg(errp, TYPE_CP_KEY_GPIO " requires official initialization writes");
        return;
    }
    for (size_t i = 0; i < G_N_ELEMENTS(cp_key_gpio_init); i++) {
        const struct cp_key_gpio_initial_write *init = &cp_key_gpio_init[i];
        CpKeyGpioBank *b = cp_key_gpio_bank(s, init->port);
        unsigned op = init->offset & 0xf;

        if (!b || !cp_key_gpio_latch(b, init->offset & ~0xfu) ||
            (op != 0 && op != 4 && op != 8)) {
            error_setg(errp, TYPE_CP_KEY_GPIO " invalid init row %zu: port=%u"
                       " offset=0x%x", i, (unsigned)init->port,
                       (unsigned)init->offset);
            return;
        }
    }
    s->handler = qemu_input_handler_register(dev, &cp_key_gpio_handler);
    qemu_input_handler_activate(s->handler);
    cp_key_gpio_reset(dev);
}

static void cp_key_gpio_unrealize(DeviceState *dev)
{
    CpKeyGpioState *s = CP_KEY_GPIO(dev);

    if (s->handler) {
        qemu_input_handler_unregister(s->handler);
        s->handler = NULL;
    }
    for (unsigned i = 0; i < CP_KEY_GPIO_BANKS; i++) {
        s->banks[i].input_driven = 0;
    }
    memset(s->down, 0, sizeof(s->down));
    for (unsigned i = 0; i < 3; i++) {
        cp_key_gpio_drive17(s, i, -1, "unregister-unknown");
    }
}

static void cp_key_gpio_instance_init(Object *obj)
{
    CpKeyGpioState *s = CP_KEY_GPIO(obj);
    static const unsigned ports[CP_KEY_GPIO_BANKS] = { 6, 7, 11 };
    static const char *const names[CP_KEY_GPIO_BANKS] = {
        "cp-key-gpio6", "cp-key-gpio7", "cp-key-gpio11",
    };

    for (unsigned i = 0; i < CP_KEY_GPIO_BANKS; i++) {
        CpKeyGpioBank *b = &s->banks[i];

        b->owner = s;
        b->port = ports[i];
        for (unsigned k = 0; k < CP_KEY_GPIO_KEYS; k++) {
            if (cp_key_gpio_keys[k].port == b->port) {
                b->input_mask |= UINT32_C(1) << cp_key_gpio_keys[k].pin;
            }
        }
        memory_region_init_io(&b->mmio, obj, &cp_key_gpio_ops, b, names[i],
                              CP_KEY_GPIO_MMIO_SIZE);
        sysbus_init_mmio(SYS_BUS_DEVICE(obj), &b->mmio);
    }
    qdev_init_gpio_out_named(DEVICE(obj), s->key17, "key-17", 3);
}

static const Property cp_key_gpio_properties[] = {
    DEFINE_PROP_STRING("profile", CpKeyGpioState, profile),
};

static const VMStateDescription cp_key_gpio_vmstate = {
    .name = TYPE_CP_KEY_GPIO,
    .unmigratable = true,
};

static void cp_key_gpio_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);

    dc->realize = cp_key_gpio_realize;
    dc->unrealize = cp_key_gpio_unrealize;
    dc->user_creatable = false;
    dc->hotpluggable = false;
    dc->vmsd = &cp_key_gpio_vmstate;
    device_class_set_legacy_reset(dc, cp_key_gpio_reset);
    device_class_set_props(dc, cp_key_gpio_properties);
    dc->desc = "Opt-in CP virtual key GPIOs; physical polarity unverified";
}

static const TypeInfo cp_key_gpio_type = {
    .name = TYPE_CP_KEY_GPIO,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(CpKeyGpioState),
    .instance_init = cp_key_gpio_instance_init,
    .class_init = cp_key_gpio_class_init,
};

static void cp_key_gpio_register_types(void)
{
    type_register_static(&cp_key_gpio_type);
}
type_init(cp_key_gpio_register_types)
