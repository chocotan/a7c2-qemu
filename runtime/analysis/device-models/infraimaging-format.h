/* SPDX-License-Identifier: MIT */
#ifndef FULL_INFRAIMAGING_FORMAT_H
#define FULL_INFRAIMAGING_FORMAT_H

#define FULL_INFRAIMAGING_FORMAT_BYTES 80u

struct full_infraimaging_format {
    unsigned int cache[5], initialized, consumed;
    unsigned long long payload_fnv64;
};

/* Caller initializes the lifecycle flag to zero and owns locking and DMM leases.
 * Cache order is component, code, width, height, full u16 flags (OUT1 only). */
int full_infraimaging_format_init(struct full_infraimaging_format *);
/* Exact canonical 80B SSYN06/key0/type1 container from the BB IN1 posthook. */
int full_infraimaging_format_build(unsigned char *out, unsigned int bytes);
/* Canonical SSYN06/type1 or forwarded SSYN01/type0, single key0 and 16B payload.
 * CP raw 582abc..582b5c reads SSYN/ETRY/key0 without inspecting version/type;
 * the model deliberately admits only these two audited writer variants.
 * Failure leaves every byte of the owner unchanged; no MMIO, task or frame work. */
int full_infraimaging_format_consume(struct full_infraimaging_format *,
                                   const unsigned char *, unsigned int bytes);

#endif
