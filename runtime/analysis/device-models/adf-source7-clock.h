/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_SOURCE7_CLOCK_H
#define FULL_ADF_SOURCE7_CLOCK_H

#include <stdint.h>

#define FULL_ADF_SOURCE7_POLICY "virtual-source7-control-events-v1"
#define FULL_ADF_SOURCE7_PERIOD_NS UINT64_C(1000000)
#define FULL_ADF_SOURCE7_COUNTER_MASK UINT32_C(0xffffff)
#define FULL_ADF_SOURCE7_MAX_EVENTS 4u /* First two groups; output continuation has one event. */
#define FULL_ADF_SOURCE7_HARDWARE 7u
#define FULL_ADF_SOURCE7_SOFTWARE 5u
#define FULL_ADF_SOURCE7_OK 0
#define FULL_ADF_SOURCE7_PENDING 1
#define FULL_ADF_SOURCE7_ERROR (-1)

struct full_adf_source7_snapshot {
    uint32_t counter;
    uint16_t phase;
    uint64_t epoch;
};
struct full_adf_source7_event {
    uint64_t generation, sequence, deadline_ns, observed_ns;
    unsigned int hardware_source, software_source;
    struct full_adf_source7_snapshot hardware, fb, cache;
};
/* Owned virtual state, never original CP RAM, DMM or a Glee shadow.
 * The fixed 1ms policy makes no original frequency/IRQ/CMOS/PCM/capture claim.
 * Parent serializes access, checks its owning PID (including fork), and latches
 * faults for rejected readonly getters. busy rejects reentry, not concurrency. */
struct full_adf_source7_clock {
    unsigned int known, fault, busy, bound, cache_valid, started, armed;
    unsigned int events_delivered; /* Lifetime total: gen1 0..4, gen2 4..8, gen3 8..9. */
    uint32_t reset_counter;
    uint16_t reset_phase;
    uint64_t generation, deadline_ns;
    struct full_adf_source7_snapshot hardware7, published_fb, cache5;
};
/* Construction requires zeroed storage; supplied reset values are virtual
 * policy inputs, not an assertion about unknown original BSS. */
int full_adf_source7_clock_init(struct full_adf_source7_clock *,
                               uint32_t reset_counter, unsigned int reset_phase);
/* First generation1 only, exact software5 -> hardware7 mapping. Bind reads the
 * owned hardware snapshot and publishes epoch0; neither bind nor get ticks. */
int full_adf_source7_clock_bind(struct full_adf_source7_clock *, uint64_t generation,
                               unsigned int software_source,
                               unsigned int hardware_source);
int full_adf_source7_clock_get(const struct full_adf_source7_clock *,
                              uint64_t generation, unsigned int software_source,
                              struct full_adf_source7_snapshot *);
/* Before arm the parent must bind a source5 subscriber and register the actual
 * cold priority2 queued-Start work, or already have consumed/read back controls
 * and registered AIP/AVIO work. Cold Start runs on the first event before audio
 * priority4; its new delay129 work must still wait for a different counter.
 * The source7 device is independent of AIP readiness. Parent owns a guest Linux
 * CLOCK_MONOTONIC timerfd: arm one-shot at deadline_ns, then read/validate one
 * actual expiry before expire. Never call expire from a getter/poll, a provided
 * sequence, host wall clock, timeout fallback or synthetic native-ready path.
 * First-group arm only. Each success emits one owned event; rearm one-shot at
 * the new deadline only while armed. The parent consumes AVIO only on events1..3.
 * Its third output callback at priority4 registers INPUT priority2 after that
 * priority's visit; input therefore needs pass4, with no extra AVIO work. The clock stays armed
 * after event3 and unarms after event4; it does not itself complete INPUT.
 * NOTDUE leaves every byte, including event_out, unchanged. */
int full_adf_source7_clock_arm(struct full_adf_source7_clock *, uint64_t generation,
                              uint64_t now_ns);
/* Continue this same owner exactly once: completed generation1 -> generation2.
 * Parent must first prove original AP 0323 reply-free and drain all pending
 * work, subscriptions and queues. This API does not admit other owners for it.
 * Requires intact, unfaulted state at event4, started/disarmed, now_ns no earlier
 * than deadline_ns-period (last observed expiry), and now_ns+period in range.
 * Only generation, armed and deadline change; get(gen2) still reads epoch4.
 * The next four actual guest timerfd expiries emit generation2, sequences5..8;
 * total counter/epoch/phase and cache history continue without reset or rebind.
 * Parent still validates each actual guest expiry under the same virtual policy;
 * continue itself does not tick or assert native frequency/readiness/capture.
 * Only generation2's four-event group is admitted here; arm/bind/init cannot be reused. */
int full_adf_source7_clock_continue(struct full_adf_source7_clock *, uint64_t now_ns);
/* Continue the same owner once more: completed generation2 -> generation3.
 * Parent must prove original AP 0336 reply-free, all pending work, commands,
 * rings and subscriptions drained, and authorize the same owner before calling.
 * This clock API does not replace those resource admission checks.
 * Requires intact, unfaulted, started/disarmed event8 and the same time bounds
 * as continue. Only generation, armed and deadline change; get(gen3) still reads
 * counter=(reset_counter+8)&0xffffff and epoch8, preserving phase/cache.
 * Parent must read/validate a real guest CLOCK_MONOTONIC timerfd expiry before
 * expire(gen3): that sole event emits sequence9/epoch9 then disarms. No getter,
 * reset/rebind, synthetic tick or four-event padding can advance this job.
 * The fixed 1ms virtual policy asserts no native frequency/IRQ/PCM/capture.
 * shortcut: exactly two four-event groups then one output event; prove further
 * owner lifetimes before extending. Generation4 and further continuations fail. */
int full_adf_source7_clock_continue_output(struct full_adf_source7_clock *, uint64_t now_ns);
int full_adf_source7_clock_expire(struct full_adf_source7_clock *, uint64_t generation,
                                 uint64_t now_ns, struct full_adf_source7_event *event_out);
/* Cancellation of the currently bound generation1, generation2 or generation3 latches fault,
 * disarms, preserves event/deadline metadata and cannot yield normal completion.
 * Invalid mutations latch fault, retain state. */
int full_adf_source7_clock_cancel(struct full_adf_source7_clock *, uint64_t generation);

/* Bounded mode0/delay0 control129 owner, not the control-call return value.
 * registered/priority/pending_work are the actual owned logical work record;
 * parent invokes poll from its async worker after a real expiry, not a ready ACK.
 * shortcut: mode0, processing states0..2, delay0 and generation1 only; extend
 * after the other original branches and work lifetimes are independently proved. */
struct full_adf_delay129 {
    unsigned int known, fault, busy, mode, processing_state;
    unsigned int software_source, hardware_source, owner18, callback_pending;
    unsigned int control_state, registered, priority, pending_work, pending;
    uint32_t saved74, delay78, start7c;
    uint64_t generation, registered_epoch;
    const struct full_adf_source7_clock *clock;
};
int full_adf_delay129_init(struct full_adf_delay129 *);
/* Success registers priority2 and stays state1/pending even when delay78==0. */
int full_adf_delay129_register(struct full_adf_delay129 *, uint64_t generation,
                              const struct full_adf_source7_clock *);
/* Uses readonly cache5. saved74==current waits first (b6c00a); only a new event
 * and a valid processing state allow state2/work removal/74,78,7c clearing.
 * A fault preserves pending work for diagnosis; no unregister-as-ready path. */
int full_adf_delay129_poll(struct full_adf_delay129 *, uint64_t generation,
                          const struct full_adf_source7_clock *);
int full_adf_delay129_cancel(struct full_adf_delay129 *, uint64_t generation);
#endif
