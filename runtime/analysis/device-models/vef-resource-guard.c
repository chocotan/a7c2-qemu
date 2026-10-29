/* SPDX-License-Identifier: MIT */
#include "vef-resource-guard.h"
#include <pthread.h>
#include <stdatomic.h>
#include <string.h>
#include <unistd.h>

static pthread_mutex_t gate=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
int full_vef_resources_owner_init(void)
{
    int pid=(int)getpid(),unbound=0;
    atomic_compare_exchange_strong(&owner_pid,&unbound,pid);
    return atomic_load(&owner_pid)==pid?0:-1021;
}
int full_vef_resources_lock(void)
{
    if (full_vef_resources_owner_init()) return -1021;
    return pthread_mutex_lock(&gate)?-1021:0;
}
void full_vef_resources_unlock(void)
{
    pthread_mutex_unlock(&gate);
}
int full_vef_resource_send_enter(unsigned int destination,int enabled)
{
    if (!enabled || (destination!=FULL_VEF_CP && destination!=FULL_PINMEM_CP &&
                    destination!=0x9061003cu)) return 0;
    return full_vef_resources_lock()?-1021:1;
}
void full_vef_resource_send_leave(int *held)
{
    if (*held==1) { *held=0;full_vef_resources_unlock(); }
}
static int registry_idle(const struct full_vef_snapshot *s,unsigned int owner)
{
    return s->initialized && s->registry_objects && s->owner_sid==owner && !s->faults && !s->pending &&
        !s->live_replies && !s->retained_request && !s->retained_reply;
}
static unsigned int read_le32(const unsigned char *p)
{
    return (unsigned int)p[0] | (unsigned int)p[1]<<8 |
        (unsigned int)p[2]<<16 | (unsigned int)p[3]<<24;
}
static unsigned long long read_le64(const unsigned char *p)
{
    return read_le32(p) | (unsigned long long)read_le32(p+4)<<32;
}
enum full_vef_dmm_domain full_vef_resource_dmm_domain(const struct full_vef_resource_snapshot *s)
{
    if (!s || !s->dmm_enabled || !s->dmm.memory || s->dmm.physical!=DMM_TEST_PHYSICAL)
        return FULL_VEF_DMM_UNKNOWN;
    if (!s->dmm.slots[0].allocated && !s->dmm.slots[0].open_count &&
        !s->dmm.slots[1].allocated && !s->dmm.slots[1].open_count)
        return FULL_VEF_DMM_EMPTY;
    if (s->dmm.allocations!=2 || s->dmm.lifecycle_changed ||
        s->appfw_base<0x10000UL || s->appfw_base>=0x7ff0000000UL ||
        s->speech_address!=s->appfw_base+0x5f66b08UL ||
        s->speech_read_before!=0x90 || s->speech_read_after!=0x90 ||
        memcmp(s->speech_before,s->speech_after,sizeof s->speech_before))
        return FULL_VEF_DMM_UNKNOWN;
    for (unsigned int i=0;i<2;i++) {
        const struct dmm_slot *slot=&s->dmm.slots[i];
        const unsigned char *entry=s->speech_before+i*0x48;
        if (slot->allocated!=1 || slot->open_count!=1 || slot->generation!=1 ||
            slot->allocation_epoch!=i+1 || slot->creator_kind!=DMM_CREATOR_SPEECH_INITIAL ||
            slot->handle!=(0x8400U|i) || read_le32(entry)!=0x1a+i ||
            read_le32(entry+0x18)!=slot->handle || read_le32(entry+0x1c)!=0x80000 ||
            read_le64(entry+0x20)!=s->dmm.physical-0x400000000ULL+i*0x80000ULL)
            return FULL_VEF_DMM_UNKNOWN;
    }
    return FULL_VEF_DMM_SPEECH_INITIAL;
}
int full_vef_resources_admissible(const struct full_vef_resource_snapshot *s)
{
    if (full_vef_resource_dmm_domain(s)==FULL_VEF_DMM_UNKNOWN) return 0;
    const struct pin_control_snapshot *p=&s->control;
    const struct pin_connection_snapshot *c=&s->connection;
    return p->bound && !p->faults && !p->live && p->allocations && p->allocations==p->releases &&
        c->started && c->connections==1 && !c->faults && !c->format_pending &&
        !c->blocked_requests && c->format_consumed && c->buffer_released &&
        c->native_reply_frees==c->connections && registry_idle(&s->vef,FULL_VEF_CP) &&
        registry_idle(&s->pinmem,FULL_PINMEM_CP);
}
#ifdef FULL_VEF_RESOURCE_TEST
int full_vef_resources_test_trylock(void)
{
    if (full_vef_resources_owner_init()) return -1021;
    return pthread_mutex_trylock(&gate);
}
#endif
