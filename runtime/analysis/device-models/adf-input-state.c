/* SPDX-License-Identifier: MIT */
#include "adf-input-state.h"
#include <string.h>

static void fanout(struct full_adf_input_state *, unsigned int);
static void control_complete(struct full_adf_input_state *, unsigned int);
static int fault(struct full_adf_input_state *s)
{
    if (s) s->fault=1;
    return -1021;
}
int full_adf_input_init(struct full_adf_input_state *s)
{
    if (!s) return -1021;
    const unsigned char *bytes=(const unsigned char *)s;
    for (unsigned long i=0;i<sizeof *s;i++) if (bytes[i]) return -1021;
    s->known=1;s->input_state=1; /* 66af26: selector0 forces input state1. */
    return 0;
}
static int jobs_empty(const struct full_adf_input_state *s)
{
    for (unsigned int i=0;i<32;i++)
        if (s->jobs[i].active || s->jobs[i].priority || s->jobs[i].generation) return 0;
    return 1;
}
static int listeners_empty(const struct full_adf_input_state *s)
{
    for (unsigned int i=0;i<5;i++)
        if (s->listeners[i].callback || s->listeners[i].context || s->listeners[i].generation) return 0;
    return 1;
}
static int cold(const struct full_adf_input_state *s)
{
    return s && s->known==1 && !s->fault && !s->generation && !s->request && !s->pending &&
        !s->parameter && s->input_state==1 && !s->registered && !s->submitted &&
        !s->driver_parameter && !s->driver_callback && !s->callback_pending &&
        !s->callback_submitted && !s->callback_driver_empty && !s->scheduler_registered &&
        !s->scheduler_consumed && !s->controls && !s->readbacks && !s->callbacks &&
        !s->listeners_called && !s->listeners_removed && !s->complete &&
        jobs_empty(s) && listeners_empty(s);
}
int full_adf_input_begin(struct full_adf_input_state *s,unsigned long long generation,
                         full_adf_input_listener listener,void *context)
{
    /* shortcut: selector0 and the first transaction only; add lifecycle proof before other paths or reuse. */
    if (generation!=1 || !listener || !cold(s)) return fault(s);
    s->generation=generation;
    s->listeners[0]=(struct full_adf_input_listener_slot){listener,context,generation};
    s->request=1;
    s->jobs[0]=(struct full_adf_input_job){2,1,generation};
    s->scheduler_registered=1;
    s->registered=fanout;s->parameter=0;
    return 0;
}
static int registered_work(const struct full_adf_input_state *s,unsigned long long generation)
{
    if (!s || s->known!=1 || s->fault || generation!=1 || s->generation!=generation ||
        s->request!=1 || s->pending || s->parameter || s->input_state!=1 ||
        s->registered!=fanout || s->submitted || s->driver_parameter || s->driver_callback ||
        s->callback_pending || s->callback_submitted || s->callback_driver_empty ||
        s->scheduler_registered!=1 || s->scheduler_consumed || s->controls || s->readbacks ||
        s->callbacks || s->listeners_called || s->listeners_removed || s->complete ||
        !s->listeners[0].callback || s->listeners[0].generation!=generation)
        return 0;
    for (unsigned int i=0;i<32;i++) {
        const struct full_adf_input_job *j=&s->jobs[i];
        if (i==0) {
            if (j->active!=1 || j->priority!=2 || j->generation!=generation) return 0;
        } else if (j->active || j->priority || j->generation) return 0;
    }
    for (unsigned int i=1;i<5;i++)
        if (s->listeners[i].callback || s->listeners[i].context || s->listeners[i].generation) return 0;
    return 1;
}
static int control_active(const struct full_adf_input_state *s)
{
    return s && s->known==1 && !s->fault && s->generation==1 && s->request==1 &&
        s->pending==1 && s->registered==fanout && s->submitted==fanout &&
        !s->driver_parameter && !s->driver_callback && s->scheduler_consumed==1 &&
        s->controls==1 && s->jobs[0].active==1 && s->jobs[0].priority==2 &&
        s->jobs[0].generation==s->generation && !s->complete;
}
static void fanout(struct full_adf_input_state *s,unsigned int status)
{
    if (status || !control_active(s) || s->callbacks!=1 || s->listeners_called ||
        s->listeners_removed || !s->listeners[0].callback ||
        s->listeners[0].generation!=s->generation) {fault(s);return;}
    for (unsigned int i=1;i<5;i++)
        if (s->listeners[i].callback || s->listeners[i].context || s->listeners[i].generation) {
            fault(s);return;
        }
    struct full_adf_input_listener_slot slot=s->listeners[0];
    memset(&s->listeners[0],0,sizeof s->listeners[0]);
    s->listeners_removed++;
    s->listeners_called++;
    slot.callback(slot.context,status);
}
static void control_complete(struct full_adf_input_state *s,unsigned int status)
{
    if (status || !control_active(s) || s->callbacks || s->listeners_called || s->listeners_removed) {
        fault(s);return;
    }
    const unsigned long long generation=s->generation;
    s->callback_pending=s->pending==1;
    s->callback_submitted=s->submitted==fanout;
    s->callback_driver_empty=s->driver_callback==0;
    s->callbacks++;
    full_adf_input_completion saved=s->submitted;
    saved(s,status);
    if (!control_active(s) || s->generation!=generation || s->submitted!=saved ||
        s->callbacks!=1 || s->listeners_called!=1 || s->listeners_removed!=1 || !listeners_empty(s)) {
        fault(s);return;
    }
    /* Original 17ad58 clears the saved callback and pending only after fanout returns. */
    s->submitted=0;s->pending=0;
}
static void consume_control30(struct full_adf_input_state *s)
{
    s->pending=1;s->submitted=s->registered;
    s->driver_parameter=s->parameter;
    s->driver_callback=control_complete;
    full_adf_input_completion callback=s->driver_callback;
    s->driver_callback=0; /* Glee 70b350 clears its callback before invoking it synchronously. */
    s->controls++;
    callback(s,0);
}
int full_adf_input_readback(const struct full_adf_input_state *s,unsigned int *parameter,
                            full_adf_input_completion *callback)
{
    if (!s || s->known!=1 || s->fault || !parameter || !callback) return -1021;
    *parameter=s->driver_parameter;*callback=s->driver_callback; /* Glee control31/70b370. */
    return 0;
}
int full_adf_input_pump(struct full_adf_input_state *s,unsigned long long generation)
{
    if (!registered_work(s,generation)) return fault(s);
    for (unsigned int priority=0;priority<5;priority++)
        for (unsigned int i=0;i<32;i++) {
            struct full_adf_input_job *job=&s->jobs[i];
            if (!job->active || job->priority!=priority) continue;
            s->scheduler_consumed++;
            consume_control30(s);
            if (s->fault || s->generation!=generation) return fault(s);
            memset(job,0,sizeof *job);
            s->registered=0;s->parameter=0;s->request=0;
        }
    unsigned int parameter=~0u;full_adf_input_completion callback=control_complete;
    if (full_adf_input_readback(s,&parameter,&callback) || parameter || callback ||
        s->pending || s->submitted || !jobs_empty(s) || !listeners_empty(s) ||
        s->scheduler_consumed!=1 || s->controls!=1 || s->callbacks!=1 ||
        s->listeners_called!=1 || s->listeners_removed!=1 ||
        !s->callback_pending || !s->callback_submitted || !s->callback_driver_empty)
        return fault(s);
    s->readbacks++;
    s->complete=1;
    return 0;
}
