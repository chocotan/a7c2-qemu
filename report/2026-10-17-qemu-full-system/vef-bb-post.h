/* SPDX-License-Identifier: MIT */
#ifndef VEF_BB_POST_H
#define VEF_BB_POST_H
#include "pin-buffer-owner.h"
#include "vef-bb-format.h"
enum post_status {
    POST_READY, POST_RELEASED_SAME, POST_RELEASED_CHANGED,
    POST_RETAINED_UNSUPPORTED, POST_SEND_FAILED, POST_NOT_AFTER_PEER,
    POST_BAD_TRIGGER, POST_ALLOC_FAILED, POST_WRITE_FAILED,
    POST_CLOSE_FAILED, POST_BAD_MESSAGE, POST_BAD_REFS,
    POST_OPEN_FAILED, POST_READ_FAILED, POST_BAD_FORMAT, POST_RELEASE_FAILED
};
enum post_refs_state { POST_NO_ALLOCATION, POST_REFS_LIVE, POST_REFS_UNKNOWN, POST_REFS_RELEASED };
enum post_retention { POST_NOT_RETAINED, POST_RETAINED, POST_RETENTION_UNKNOWN };
/* Decoded SystemCmdTrigger tuple, not a substitute for decoding a wire frame. */
struct post_trigger {
    unsigned command,subcommand,extent,flags;
    const unsigned char *record;
    unsigned record_bytes;
};
/* Actual MsgAccessor+70 arguments. Not an OSAL response or pixel completion. */
struct post_message { unsigned pin_index,unit,handle,offset; };
struct post_bb {
    unsigned char cache[16];
    unsigned initializations,updates;
    unsigned pin_states[6];
};
struct post_report {
    enum post_status status;
    enum post_refs_state refs_state;
    int operation_rc,refs_rc;
    unsigned actual_handle,unit,cp_virtual,address_known,consumed_bytes,format_valid;
    unsigned cache_changed,cache_initializations,cache_updates;
    enum post_retention retained;
    unsigned long long physical,fnv;
    unsigned char consumed[80],cache_before[16],cache_after[16];
    struct vef_bb_format format;
    struct pin_control_references refs;
    struct pin_control_snapshot before,after;
};
extern const unsigned char post_original_cold_cache[16];
int post_bb_init(struct post_bb *,const unsigned char *,unsigned);
enum post_status post_produce(unsigned,const struct post_trigger *,struct post_message *,struct post_report *);
enum post_status post_send_result(const struct post_message *,int,struct post_report *);
enum post_status post_consume(struct post_bb *,const struct post_message *,struct post_report *);
#endif
