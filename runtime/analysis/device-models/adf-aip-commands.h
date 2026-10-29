/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_AIP_COMMANDS_H
#define FULL_ADF_AIP_COMMANDS_H

/* Owned semantic response; this is not the original CP response wire format. */
struct full_adf_aip_command_response {
    unsigned int opcode;
    int status;
    unsigned int sequence;
    unsigned long long generation, event_sequence;
};

#define FULL_ADF_AIP_RESPONSE_SLOTS 76u
#define FULL_ADF_AIP_TASK_ERROR 0x1004u
#define FULL_ADF_AIP_SNAPSHOT_BYTES (8u + 75u * 12u + 4u)

struct full_adf_aip_commands;
struct full_adf_aip_input_commands {
    const struct full_adf_aip_commands *owner;
    unsigned long long generation, last_event;
    unsigned int enqueued, dispatches;
    /* Current shared ring indices/storage, reused by generation3 without cloning. */
    unsigned int ring_read, ring_write;
    unsigned char ring[FULL_ADF_AIP_RESPONSE_SLOTS][12];
    unsigned char snapshot[FULL_ADF_AIP_SNAPSHOT_BYTES];
    /* Generation2 failure evidence and statistics stay unchanged after output_begin. */
    unsigned char failure_snapshot[FULL_ADF_AIP_SNAPSHOT_BYTES];
    unsigned int snapshot_count, checked, local_cursor, task_status, uninspected;
    unsigned int failure_opcode, failure_status, failure_task_status;
};

struct full_adf_aip_output_commands {
    const struct full_adf_aip_commands *owner;
    unsigned long long generation, last_event;
    unsigned int enqueued, dispatches, snapshot_count, checked, local_cursor, task_status, uninspected;
};

struct full_adf_aip_commands {
    unsigned char buffer[0x514];
    unsigned int known, interpreter_state, command_count, cursor; /* cursor is in words. */
    unsigned int response_pending;
    struct full_adf_aip_command_response response;
    unsigned int sequence, events, af_applied, b0_applied, stateflag;
    unsigned int busy, fault;
    unsigned long long generation, dispatch_event, af_event, b0_event;
    struct full_adf_aip_input_commands input;
    struct full_adf_aip_output_commands output;
};

/* Only an entirely zero destination may acquire the owned cold S0 interpreter. */
int full_adf_aip_commands_init(struct full_adf_aip_commands *);
int full_adf_aip_commands_enqueue(struct full_adf_aip_commands *, const unsigned char *,
                                  unsigned int bytes, unsigned long long generation);
/* The serial caller supplies a real dispatch epoch, not a fabricated event count.
 * disable must consume its register work and verify readback; a bare ACK is invalid.
 * Failure retains queue/response evidence and latches fault; init cannot reset it. */
int full_adf_aip_commands_consume(struct full_adf_aip_commands *,
                                  unsigned long long generation,
                                  unsigned long long event_sequence,
                                  int (*disable)(void *), void *context);
/* The trusted parent must first prove the original 0323 reply was freed and other
 * owners drained. This one-shot phase reuses the completed AF/B0 owner/buffer;
 * the old generation1 response/events remain history. Header word0 is owned
 * virtual policy 0, not an original acknowledgement sequence. */
int full_adf_aip_commands_input_begin(struct full_adf_aip_commands *,
                                      unsigned long long generation);
int full_adf_aip_commands_input_enqueue(struct full_adf_aip_commands *,
                                        const unsigned char *, unsigned int bytes,
                                        unsigned long long generation);
/* Only actual shared source7 global events 5,6,7,8 may dispatch generation2.
 * The provider must execute/verify data and register work. rc!=0 means unknown
 * work; rc==0/status1 is the expected AB negative response in cold S0.
 * Return 0 means dispatch completed: the first snapshot still has task0x1004,
 * checked=2, cursor=6 words and 7 uninspected entries; later empty snapshots
 * have task0 without inspecting those entries. failure_snapshot is immutable.
 * The serial provider cannot reenter or mutate this owner. A fault retains all
 * queue/response evidence. There is no asynchronous ring producer in this scope. */
int full_adf_aip_commands_input_flush(struct full_adf_aip_commands *,
                                      unsigned long long generation,
                                      unsigned long long global_event,
                                      int (*provider)(void *, const unsigned char *,
                                                      unsigned int, unsigned int *),
                                      void *context);
/* The trusted parent must first prove original AP 1336 free and common-resource
 * guards. One-shot generation3 reuses the same owner, command buffer and response
 * ring only after generation2 drained at global event8. Input/legacy metadata and
 * failure_snapshot remain history; input.ring/snapshot and their indices are current.
 * Header word0 remains owned policy0, never an acknowledgement sequence. */
int full_adf_aip_commands_output_begin(struct full_adf_aip_commands *,
                                       unsigned long long generation);
/* Only the exact Notify2 source0 B0 command is admitted. */
int full_adf_aip_commands_output_enqueue(struct full_adf_aip_commands *,
                                         const unsigned char *, unsigned int bytes,
                                         unsigned long long generation);
/* Called before GleeNoOp on the sole actual generation3/global event9.
 * disable must consume seven S0 register writes/readbacks on the existing bank.
 * Faults retain evidence; no foreign ring entries are cleared or old tails inspected. */
int full_adf_aip_commands_output_flush(struct full_adf_aip_commands *,
                                       unsigned long long generation,
                                       unsigned long long global_event,
                                       int (*disable)(void *), void *context);
#endif
