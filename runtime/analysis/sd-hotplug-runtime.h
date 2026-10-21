/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_SD_HOTPLUG_RUNTIME_H
#define NATIVE_SD_HOTPLUG_RUNTIME_H
#include "sd-state.h"

struct native_sd_hotplug_io {
    void *context;
    bool (*backing_valid)(void *,const sd_backing *);
    int (*flush)(void *,uint64_t,uint32_t);
    sd_send_result (*notify)(void *,uint64_t,sd_operation,const uint8_t[7]);
};
/* Configure once before the RM worker starts; only that worker calls poll.
 * Other AP threads enqueue observations; none calls core or waits for it. */
int native_sd_hotplug_configure(const sd_backing *,const struct native_sd_hotplug_io *);
void native_sd_hotplug_poll(void);
void native_sd_hotplug_fsys(sd_observation_kind,unsigned int,int,bool,bool);
uint64_t native_sd_hotplug_generation(void);
void native_sd_hotplug_fsys_generation(uint64_t,sd_observation_kind,unsigned int,int,bool,bool);
void native_sd_hotplug_freed(uint64_t,int);
unsigned int native_sd_hotplug_port(void);
int native_sd_hotplug_enabled(void);
int native_sd_hotplug_retired(void);
#endif
