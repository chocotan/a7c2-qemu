/* SPDX-License-Identifier: MIT */
#ifndef FULL_VEF_RESOURCE_GUARD_H
#define FULL_VEF_RESOURCE_GUARD_H
#include "../dmm-service.h"
#include "pin-buffer-owner.h"
#include "pin-connection.h"
#include "pinmem-device.h"

enum full_vef_dmm_domain {
    FULL_VEF_DMM_UNKNOWN = 0,
    FULL_VEF_DMM_EMPTY = 1,
    FULL_VEF_DMM_SPEECH_INITIAL = 2
};
/* Only the native-owned unit63a/control pools and message work are covered;
 * this never establishes whole-guest DMM idleness, data freeze or original CP cache state. */
struct full_vef_resource_snapshot {
    unsigned int dmm_enabled;
    struct dmm_service dmm;
    signed long speech_read_before, speech_read_after;
    unsigned long appfw_base, speech_address;
    unsigned char speech_before[0x90], speech_after[0x90];
    struct pin_control_snapshot control;
    struct pin_connection_snapshot connection;
    struct full_vef_snapshot vef, pinmem;
};
enum full_vef_dmm_domain full_vef_resource_dmm_domain(const struct full_vef_resource_snapshot *);
int full_vef_resources_admissible(const struct full_vef_resource_snapshot *);
/* Bind the process before any mutex; inherited fork ownership is rejected. */
int full_vef_resources_owner_init(void);
int full_vef_resources_lock(void);
void full_vef_resources_unlock(void);
/* 1=mutator gate held, 0=unrelated/disabled, negative=reject inherited owner.
 * The cleanup attribute on the returned token covers every sender return. */
int full_vef_resource_send_enter(unsigned int, int);
void full_vef_resource_send_leave(int *);
#ifdef FULL_VEF_RESOURCE_TEST
int full_vef_resources_test_trylock(void);
#endif
#endif
