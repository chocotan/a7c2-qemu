/* SPDX-License-Identifier: MIT */
#ifndef HDMI_HPD_OWNER_H
#define HDMI_HPD_OWNER_H
#include <pthread.h>
#include <stdint.h>

#define HDMI_HPD_CLIENTS 3u
#define HDMI_HPD_EVENTS 8u
#define HDMI_HPD_EVENT_BYTES 12u
#define HDMI_HPD_MASK_OFF 0x0006000du
#define HDMI_HPD_MASK_ON 0x0006000fu

struct hdmi_hpd_event {
    uint64_t lease;
    unsigned int client;
    unsigned char wire[HDMI_HPD_EVENT_BYTES];
    unsigned int live,read;
};
struct hdmi_hpd_client {unsigned int sid,mask,open;};
struct hdmi_cold_config {
    unsigned int owner_client,initial_known,has_config;
    unsigned int current_mode,target_mode,active,dirty;
    unsigned int job_live,job_applied,descriptor_live;
    uint64_t generation,submitted,applied_count,completed,completion_lease;
    unsigned char initial[18],staged[36],applied[36];
};
struct hdmi_hpd_snapshot {
    unsigned int initialized,hpd,clients_ever_opened,open_clients,live_events,level_updates;
    uint64_t next_lease,queued,reads,consumed;
    struct hdmi_hpd_client clients[HDMI_HPD_CLIENTS];
    struct hdmi_cold_config config;
};
/* An explicitly new virtual resource, not the CP hardware backend. Initialize
 * a zeroed, process-lifetime object once before other threads can use it. Never
 * memcpy/reset/destroy it while live; a fork child is rejected before locking.
 * Three clients/eight event slots are this model's finite limits. All output
 * ranges must be valid and writable; ranges overlapping this owner are
 * rejected. The dequeue buffer and lease output must not overlap each other. */
struct hdmi_hpd_owner {
    pthread_mutex_t mutex;
    long pid;
    struct hdmi_hpd_snapshot state;
    struct hdmi_hpd_event events[HDMI_HPD_EVENTS];
};
int hdmi_hpd_init_unplugged(struct hdmi_hpd_owner *,int explicit_enable);
int hdmi_hpd_open(struct hdmi_hpd_owner *,unsigned int sid,unsigned int *client);
int hdmi_hpd_set_mask(struct hdmi_hpd_owner *,unsigned int client,unsigned int mask);
/* Update only the cached virtual input. Asynchronous edge broadcast and the
 * original hardware poller are outside this resource's scope. Reject input
 * changes while a config job/descriptor is outstanding; never strand it. */
int hdmi_hpd_set_level(struct hdmi_hpd_owner *,unsigned int level);
/* Model the HPD replay operation. 1 means not subscribed, no event; 0 means a
 * real lease was queued. Exhaustion/invalid inputs return -1 without mutation. */
int hdmi_hpd_replay(struct hdmi_hpd_owner *,unsigned int client,uint64_t *lease);
int hdmi_hpd_read(struct hdmi_hpd_owner *,unsigned int client,uint64_t lease,unsigned char out[12]);
/* A consumer must read and return all exact bytes before retiring this lease. */
int hdmi_hpd_consume(struct hdmi_hpd_owner *,unsigned int client,uint64_t lease,const unsigned char received[12]);
/* Model only resource op1's atomic copy/retire of the queue node. -11: empty;
 * -90: capacity too small, node retained. Success never means the separate
 * 2500/0701 message has been sent or consumed by original firmware. */
int hdmi_hpd_dequeue(struct hdmi_hpd_owner *,unsigned int client,unsigned char *out,
                     unsigned int capacity,uint64_t *lease);
int hdmi_hpd_close(struct hdmi_hpd_owner *,unsigned int client);
int hdmi_hpd_snapshot(struct hdmi_hpd_owner *,struct hdmi_hpd_snapshot *);
/* One explicit new fresh configuration owner, sharing the same finite client
 * event resource. Bind the first handle once; never reset an existing owner.
 * Input/output storage must be valid, independent of this owner, and exclusive
 * to the caller for the call. Only cold {0,0,config28} is supported. */
int hdmi_config_bind_fresh(struct hdmi_hpd_owner *,unsigned int client);
int hdmi_config_write_initial(struct hdmi_hpd_owner *,unsigned int client,const unsigned char *,unsigned int bytes);
/* Success queues a job, not a completion. The generation is an owned job ID.
 * One event-lease credit is reserved until this job's completion is posted. */
int hdmi_config_submit(struct hdmi_hpd_owner *,unsigned int client,const unsigned char *,unsigned int bytes,uint64_t *generation);
/* An explicit worker consumes the saved config. 0 queues {7,0,0} to that same
 * handle; -2 retains the applied job/descriptor when the completion queue is
 * blocked; -1 rejects invalid/noncold work. No physical or CP task assertion. */
int hdmi_config_work_once(struct hdmi_hpd_owner *,unsigned int client,uint64_t generation);
#endif
