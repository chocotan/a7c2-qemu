#ifndef A7C2_FSYS_WRITE_TRACE_H
#define A7C2_FSYS_WRITE_TRACE_H

#include <stddef.h>
#include <stdint.h>

#define FSYS_WRITE_REQUEST_BYTES 0x508u
#define FSYS_WRITE_PATH_BYTES 0x40fu
#define FSYS_WRITE_AREAS 8u
#define FSYS_WRITE_RESULT_BYTES 0x4d8u
#define FSYS_WRITE_OBSERVATION_LIMIT (128u * 1024u * 1024u)
#define MPR_FSYS_CALLBACK_SYMBOL "_ZN3mpr11stillrecord17fsys_callbackfuncEPviPK22FSYSWRITEDIRECTFILERES"
#define MPR_WRITE_FINISHED_SYMBOL "_ZN3mpr11stillrecord15_write_finishedEPv"

struct fsys_write_area {
    uint64_t physical_address, address, submitted_bytes;
    uint64_t offset, bytes; /* Derived sequential file interval after final truncate. */
};
struct fsys_write_layout {
    char path[FSYS_WRITE_PATH_BYTES];
    uint32_t count, address_mode, open_flags;
    uint64_t callback, cookie, expected_bytes, payload_bytes;
    struct fsys_write_area area[FSYS_WRITE_AREAS];
};
struct fsys_write_finished {
    unsigned token;
    int input_copied, rc;
    uint64_t cookie;
};

/* Public ELF source pins: report/native-card-write/source-pins.json. */
int fsys_write_decode(const unsigned char *request, size_t bytes, struct fsys_write_layout *out);
uint64_t fsys_write_fnv1a64(const void *data, size_t bytes);
unsigned fsys_write_trace_begin(const unsigned char request[FSYS_WRITE_REQUEST_BYTES]);
void fsys_write_trace_submit(unsigned token, int rc);
unsigned fsys_write_trace_callback(void *cookie, int rc, const void *result, uint64_t callback);
void fsys_write_trace_callback_return(unsigned token);
void fsys_write_trace_unobserved(void);
struct fsys_native_read_ops {
    int (*open)(const char *, unsigned long long *, unsigned);
    int (*read)(unsigned long long, void *, int);
    int (*close)(unsigned long long);
};
int fsys_write_trace_readback(const struct fsys_native_read_ops *ops);
struct fsys_write_finished fsys_write_trace_finished_begin(const void *input);
void fsys_write_trace_finished_return(struct fsys_write_finished input);

/* Synchronous ABI is pinned independently in report/native-movie-write-trace/.
 * Observation only: the caller invokes each original Fsys operation unchanged.
 * All functions preserve errno; their return values are observation results.
 * No environment gate here: wrappers must explicitly opt in before calling.
 * Inherited state in a fork child is rejected before touching the parent lock. */
#define FSYS_SYNC_FILES 32u
#define FSYS_SYNC_WRITES 1024u
#define FSYS_SYNC_CHUNK_BYTES 4096u
struct fsys_sync_context {
    uint64_t caller, context, producer; /* Raw identities, never inferred origins. */
};
enum fsys_sync_address_domain {
    FSYS_SYNC_VIRTUAL = 1, FSYS_SYNC_LOGICAL = 2, FSYS_SYNC_PHYSICAL = 3
};
struct fsys_sync_source {
    uint64_t address, extent;
    unsigned extent_known;
    enum fsys_sync_address_domain domain;
};
/* frozen_path excludes its NUL, must be captured before the original Open.
 * initial_size/position are supplied only when independently known; Open's
 * name or flags alone are not evidence of an empty file or initial position.
 * Returns a process-local file identity, never a recycled handle identity. */
unsigned fsys_sync_trace_open(const void *frozen_path, size_t path_bytes,
    uint64_t handle, uint64_t generation, unsigned flags, int original_rc,
    int original_errno, unsigned size_known, uint64_t initial_size,
    unsigned position_known, uint64_t initial_position, struct fsys_sync_context context);
/* Resolve the unique still-open lifetime before an original handle operation;
 * returns zero for missing/ambiguous identities. Keep this token across calls. */
unsigned fsys_sync_trace_file(uint64_t handle, uint64_t generation);
/* Before original Write/WriteAndFlush. Freezes requested virtual bytes through
 * /proc/self/mem within the observation budget. Unknown allocation/lease extent
 * still permits a frozen actual-prefix receipt, but permanently rejects full
 * verification; it is never promoted to known from requested count.
 * A nonzero ticket must be ended even if unreadable or the original fails.
 * Pass and_flush=0 for Write, 1 for WriteAndFlush. Never substitute a buffer. */
unsigned fsys_sync_trace_write_begin(unsigned file, uint64_t handle,
    uint64_t generation, struct fsys_sync_source source, int requested,
    unsigned and_flush, struct fsys_sync_context context);
/* After the original returns; result is its signed int actual byte count or
 * negative status, not a separate status==0 convention. No source reread. */
int fsys_sync_trace_write_end(unsigned ticket, uint64_t handle,
    uint64_t generation, int original_result, int original_errno);
/* Observe the original Seek result and its safely copied u64 output. */
int fsys_sync_trace_position(unsigned file, uint64_t handle, uint64_t generation,
    int original_rc, int original_errno, unsigned position_known, uint64_t position,
    struct fsys_sync_context context);
int fsys_sync_trace_close(unsigned file, uint64_t handle, uint64_t generation,
    int original_rc, int original_errno, struct fsys_sync_context context);
/* Unmodelled mutations (Combine, truncate, rename, unmount, missed wrappers)
 * must invalidate every affected file. file=0 invalidates all lifetimes.
 * This never calls the original API. */
int fsys_sync_trace_invalidate(unsigned file, uint64_t handle, uint64_t generation, int reason);
/* Explicit post-close, post-successful-original-flush readback. ops must be
 * original Open/Read/Close, bypassing interposition. Reconstructs final bytes
 * from ordered frozen write contributions, including seek/overwrite; gaps,
 * unknown initial extent, short/failed writes or stale identities fail closed.
 * Success proves these observed bytes, never movie/capture/producer origin. */
int fsys_sync_trace_readback(unsigned file, uint64_t handle, uint64_t generation,
    int original_flush_rc, int original_flush_errno, const struct fsys_native_read_ops *ops);
/* Snapshot closed lifetime IDs/handles in this generation, then reuse the
 * single-file checker without holding the state lock over original callbacks.
 * Unknown generation fails closed; no additional flush/seek/write is issued. */
int fsys_sync_trace_readback_all(uint64_t generation, int original_flush_rc,
    int original_flush_errno, const struct fsys_native_read_ops *ops);

#endif
