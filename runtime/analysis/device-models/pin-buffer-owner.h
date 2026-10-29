/* SPDX-License-Identifier: MIT */
#ifndef FULL_PIN_BUFFER_OWNER_H
#define FULL_PIN_BUFFER_OWNER_H
#define PIN_CONTROL_PHYSICAL 0x500000000ULL
#define PIN_CONTROL_CP_VIRTUAL 0x80000000u
#define PIN_CONTROL_SLOTS 16u
#define PIN_CONTROL_SLOT_BYTES 0x200u
#define PIN_CONTROL_CAPACITY (PIN_CONTROL_SLOTS*PIN_CONTROL_SLOT_BYTES)
#define PIN_CONTROL_RESERVATION "memrsv=0x00002000@0x500000000:uc"
#define PIN_CONTROL_UNIT 0x404u
/* This is a new finite control owner, not Sony's current allocation policy.
 * The binding caller must own this exact guest reservation for the VM lifetime.
 * Host tests bind an explicitly labeled byte-array fixture, not guest evidence.
 * A slot's 5-bit generation never wraps during this VM: exhausted slots refuse
 * further allocation. No pixels, format-ready or DMM message ACK is produced. */
/* Forked children cannot reuse inherited allocator state or mapping ownership.
 * PID guards precede all potentially inherited mutexes; exec may bind afresh. */
struct pin_control_lease {
    unsigned int handle,unit,slot,bytes,cp_virtual;
    unsigned long long physical;
};
struct pin_control_snapshot {
    unsigned int bound,live,exhausted,faults;
    unsigned long long allocations,releases,header_writes;
    unsigned long long shares,consumer_opens,consumer_closes;
    unsigned long long creator_releases,consumer_releases,payload_writes,consumer_reads;
    unsigned long long creator_closes,creator_transfers;
};
/* This finite owner supports two distinguished roles, not general Sony DMM.
 * The existing PinMem/VEF path shares an open creator, adding a consumer owner;
 * both roles must release before retirement. Sharing freezes writes. A consumer
 * close alone preserves its owner reference for reopening or forwarding.
 * The InfraBB/InfraImaging path instead closes the sole creator's open, then
 * transfers that same owner to a closed consumer without adding a reference.
 * Transfer does not count as a share or creator release; the consumer must open
 * before reading and release its own reference to retire the slot. */
struct pin_control_references {
    unsigned int handle,owners,opens,creator,consumer,consumer_open;
};
int pin_control_bind_reserved(volatile unsigned char *,unsigned long,unsigned long long);
/* Returns 0 disabled, 1 bound, -1 failure. Requires both explicit guest boot
 * tokens and the matching DTB ownership identity before opening /dev/mem. */
int pin_control_open_guest(int);
int pin_control_allocate(unsigned int,struct pin_control_lease *);
int pin_control_write_ssyn(unsigned int,unsigned long long *);
int pin_control_write_payload(unsigned int,const unsigned char *,unsigned int,unsigned long long *);
/* Closing requires a sole, open creator and preserves its owner. Both closed
 * and transferred creators refuse writes; only a closed creator can transfer. */
int pin_control_close_creator(unsigned int);
int pin_control_transfer_creator(unsigned int,unsigned int);
int pin_control_share(unsigned int,unsigned int);
int pin_control_open_consumer(unsigned int,unsigned int,struct pin_control_lease *);
int pin_control_read_consumer(unsigned int,unsigned int,unsigned char *,unsigned int);
int pin_control_close_consumer(unsigned int);
/* Option 2 free closes an open consumer; an already closed consumer is refused. */
int pin_control_release_consumer(unsigned int);
/* Option 0 free requires a sole closed consumer; it never closes again.
 * A transferred, never-opened owner may also be freed. Callers enforce any
 * required Open/read/Close history before invoking this owner-only operation. */
int pin_control_release_closed_consumer(unsigned int);
int pin_control_references(unsigned int,struct pin_control_references *);
int pin_control_release(unsigned int);
void pin_control_snapshot(struct pin_control_snapshot *);
#ifdef PIN_CONTROL_TEST
void pin_control_test_reset(void);
void pin_control_test_hold_lock(void);
void pin_control_test_drop_lock(void);
void pin_control_test_hold_binding(void);
void pin_control_test_drop_binding(void);
#endif
#endif
