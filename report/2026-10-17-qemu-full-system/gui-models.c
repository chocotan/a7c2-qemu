/* SPDX-License-Identifier: MIT */
#include "gui-models.h"
#include <string.h>
#ifndef GUI_MODELS_TEST
#include <pthread.h>
#include <stdio.h>
#endif

/* Sizes proven from the 14 direct producer calls to appFw+0x17955d8. */
static const unsigned int lengths[GUI_MODEL_COUNT] = {
    0x274,0x10,0x08,0x1c,0x14,0x0c,0x14,0x0c,0x14,0x0c,0x04,0x10,0x08,0x08
};
static unsigned int le32(const unsigned char *p) {
    return (unsigned int)p[0] | (unsigned int)p[1]<<8 |
           (unsigned int)p[2]<<16 | (unsigned int)p[3]<<24;
}
static int history_slot(unsigned int id) {
    switch(id) {
    case 0x10:return 0;
    case 0x15:return 1;
    case 0x16:return 2;
    case 0x19:return 3;
    case 0x1a:return 4;
    case 0x1b:return 5;
    default:return -1;
    }
}
int gui_models_apply(struct gui_model_state *state,const void *message,unsigned int size) {
    if (!state || !message || size<8 || size>GUI_MODEL_BATCH_MAX) return -1;
    const unsigned char *b=message;
    if (le32(b)!=0 || le32(b+4)!=size-8) return -1;
    const unsigned char *payload[GUI_MODEL_COUNT]={0};
    unsigned int offset=8,seen=0;
    while (offset<size) {
        if (size-offset<8) return -1;
        unsigned int id=le32(b+offset),n=le32(b+offset+4);offset+=8;
        if (id<GUI_MODEL_FIRST || id>=GUI_MODEL_FIRST+GUI_MODEL_COUNT) return -1;
        unsigned int slot=id-GUI_MODEL_FIRST,bit=1u<<slot;
        if ((seen&bit) || n!=lengths[slot] || n>size-offset) return -1;
        seen|=bit;payload[slot]=b+offset;offset+=n;
    }
    unsigned int changed=0;
    for (unsigned int i=0;i<GUI_MODEL_COUNT;i++) if (payload[i]) {
        struct gui_model_value *v=&state->values[i];
        int differs=v->size!=lengths[i] || memcmp(v->bytes,payload[i],lengths[i]);
        int h=history_slot(i+GUI_MODEL_FIRST);
        if (h>=0) {
            struct gui_model_history *history=&state->history[h];
            unsigned int version=(history->initialized?history->version:0x20u)+1;
            if(version>0x5fu)version=0x20u;
            unsigned int slot=version&31;
            memcpy(history->bytes[slot],payload[i],lengths[i]);
            history->changes[slot][0]=differs?0xffffffffu:0;
            history->changes[slot][1]=differs?0x0003ffffu:0;
            history->version=(unsigned short)version;
            history->initialized=1;
        }
        if (differs) {
            memcpy(v->bytes,payload[i],lengths[i]);v->size=lengths[i];
            v->generation++;changed|=1u<<i;
        }
    }
    state->batches++;
    return (int)changed;
}

#ifndef GUI_MODELS_TEST
static struct gui_model_state models;
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
int full_gui_models_dispatch(unsigned int id,void *message,unsigned int size,
    int (*release)(unsigned int,void *),void (*record)(const char *,const char *)) {
    if (id!=0x9088076bu || !release || !record) return -1024;
    pthread_mutex_lock(&lock);
    int changed=gui_models_apply(&models,message,size);
    char text[320];
    if (changed<0) {
        snprintf(text,sizeof text,"endpoint=%#x bytes=%u reason=unsupported-or-malformed sender_retains=1",id,size);
        record("FULL_GUI_MODELS_REJECT ",text);
        pthread_mutex_unlock(&lock);
        return -1024;
    }
    /* Publish actual inline bytes for downstream semantic/render consumers.
     * Bounded: only changes (or the first sample) produce byte records. */
    if (changed || models.batches==1) {
        const unsigned char *b=message;
        for (unsigned int offset=0;offset<size;offset+=64) {
            unsigned int take=size-offset;if(take>64)take=64;
            char hex[129];
            for(unsigned int i=0;i<take;i++)snprintf(hex+2*i,3,"%02x",b[offset+i]);
            hex[2*take]=0;
            snprintf(text,sizeof text,"batch=%llu offset=%u total=%u hex=%s",models.batches,offset,size,hex);
            record("FULL_GUI_MODELS_BYTES ",text);
        }
    }
    unsigned long long batch=models.batches;
    /* No reply is generated: the original sender transfers ownership on 0.
     * Report a release failure as a fatal ownership fault, not a retry, because
     * returning an error after free would make the sender free it twice. */
    int freed=release(id,message);
    if (changed || batch<=8 || !(batch&(batch-1)) || freed) {
        snprintf(text,sizeof text,"endpoint=%#x batch=%llu bytes=%u changed=%#x af_version=%#x original_free_rc=%d reply_sent=0 cp_render_verified=0",id,batch,size,changed,models.history[0].version,freed);
        record(freed?"FULL_GUI_MODELS_FAULT ":"FULL_GUI_MODELS_CONSUMED ",text);
    }
    pthread_mutex_unlock(&lock);
    return 0;
}
#endif
