#ifndef SD_STATE_H
#define SD_STATE_H
#include <stdbool.h>
#include <stdint.h>

typedef enum { SD_PRESENT, SD_EJECTING, SD_ABSENT, SD_INSERTING,
               SD_FAILED_UNCERTAIN } sd_state;
typedef enum { SD_EJECT, SD_INSERT } sd_operation;
typedef enum { SD_MOUNT, SD_UNMOUNT, SD_NOTIFY_FREE } sd_observation_kind;
typedef enum { SD_SENT, SD_NOT_SENT, SD_DELIVERY_UNCERTAIN } sd_delivery;
typedef enum { SD_OK, SD_DUPLICATE, SD_ALREADY, SD_PENDING, SD_STALE,
               SD_CONFLICT, SD_BUSY, SD_GUARD_FAILED, SD_BACKING_FAILED,
               SD_QUIESCENCE_FAILED, SD_UNBOUND, SD_INVALID,
               SD_MISMATCH, SD_ROLLED_BACK, SD_UNCERTAIN,
               SD_EXHAUSTED } sd_result;

typedef struct { int fd; uint64_t identity, size; } sd_backing;
typedef struct { uint64_t sequence; sd_operation operation; } sd_request;
typedef struct {
    uint64_t generation;
    sd_observation_kind kind;
    uint32_t drive;
    int rc;
    bool genuine, path_validated, owned;
} sd_observation;
typedef struct { sd_delivery delivery; bool observable_ack; } sd_send_result;
typedef struct { uint64_t generation; } sd_timeout;
typedef struct {
    void *context;
    bool (*guard)(void *);
    bool (*validate_backing)(void *, const sd_backing *);
    bool (*validate_quiescence)(void *, uint64_t, uint32_t);
    sd_send_result (*notify)(void *, uint64_t, sd_operation, const uint8_t[7]);
} sd_adapters;
typedef struct {
    sd_state state;
    uint64_t generation, sequence;
    uint32_t drive;
    uint8_t bytes[7];
} sd_snapshot;

/* Zero initialize once. Fields are private to sd_state.c despite static storage. */
typedef struct {
    sd_adapters adapters;
    sd_backing backing;
    sd_state state;
    uint64_t generation, sequence;
    uint32_t drive, observed_drive;
    uint8_t remove_count;
    bool bound, callback, present, fs_ack, free_ack, attempted;
    sd_operation operation, last_operation;
} sd_core;

sd_result sd_bind(sd_core *, const sd_adapters *, const sd_backing *,
                  const sd_observation *already_observed_mount);
sd_result sd_request_apply(sd_core *, sd_request);
sd_result sd_observe(sd_core *, sd_observation);
sd_result sd_expire(sd_core *, sd_timeout);
sd_result sd_snapshot_read(sd_core *, sd_snapshot *);
#endif
