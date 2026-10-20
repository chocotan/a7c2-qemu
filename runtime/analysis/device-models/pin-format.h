/* SPDX-License-Identifier: MIT */
#ifndef FULL_PIN_FORMAT_H
#define FULL_PIN_FORMAT_H
#define PIN_YC_FORMAT_BYTES 80u
/* Raw PinMem manager fields and encoded VEF payload flags are intentionally
 * distinct types. No dimensions are invented by the decoder. These helpers
 * own no devices or global state; the calling owner serializes its cache. */
struct pin_yc_parameters {
    unsigned int raw_flags,width,height;
    unsigned char code,component;
};
struct pin_yc_payload {
    unsigned char code,component;
    unsigned short encoded_flags;
    unsigned int width,height;
};
struct pin_yc_current_info {
    unsigned int pin_index,ordinal;
    unsigned char code,component;
    unsigned short encoded_flags;
    unsigned int width,height;
};
/* Finite single-entry/key0/offset0 subset. The original constructor's unchecked
 * writes are replaced with capacity checks; unsupported entries are refused. */
int pin_yc_build(const struct pin_yc_parameters *,unsigned char *,unsigned int);
int pin_yc_decode(const unsigned char *,unsigned int,struct pin_yc_payload *);
int pin_yc_store(const struct pin_yc_payload *,struct pin_yc_current_info *);
#endif
