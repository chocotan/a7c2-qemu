/* SPDX-License-Identifier: MIT */
#include "pin-registry-core.h"
#include "hdmi-pin-device.h"
#include <pthread.h>
/* CP raw62298e constructs video at PinHandler+8, then audio at +4. Virtual
 * slots follow construction order; they are not original RAM addresses. */
static const unsigned int keys[2][3]={{4,1,0},{5,1,0}};
static struct pin_registry_owner registry={.source=FULL_HDMI_PIN_CP,.count=2,.name="HDMIPIN",.keys=keys,.type_only=1};
static unsigned int video_connected,audio_connected;
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
struct pin_registry_owner *full_hdmi_pin_registry(void){return &registry;}
int full_hdmi_pin_dispatch(unsigned int d,void *p,const struct full_imaging_io *io,int enabled,int *rc){
    /* Same destination as existing HDMI API 2500. Leave those messages with
     * their existing configuration owner before checking Dataflow envelopes. */
    if(d!=FULL_HDMI_PIN_CP || enabled!=1)return 0;
    if(p && io && io->size && io->size(p)>=2){
        const unsigned char *b=p;if(b[0]==0 && b[1]==0x25)return 0;
    }
    return pin_registry_dispatch(&registry,d,p,io,enabled,rc);
}
int full_hdmi_pin_release_reply(unsigned int d,void *p,int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *rc){return pin_registry_release(&registry,d,p,release,record,rc);}
void full_hdmi_pin_snapshot(struct full_vef_snapshot *out){pin_registry_snapshot(&registry,out);}
/* Only the two shared state bytes are modelled. A VIDEO connect sets +58h and an
 * AUDIO connect sets +60h; neither implies HPD state, format or output. */
int full_hdmi_pin_notify_connected(unsigned int type){
    pthread_mutex_lock(&mutex);
    int rc=0;
    if(type==4)video_connected=1;
    else if(type==5)audio_connected=1;
    else rc=-1;
    pthread_mutex_unlock(&mutex);return rc;
}
unsigned int full_hdmi_pin_video_connected(void){pthread_mutex_lock(&mutex);unsigned int v=video_connected;pthread_mutex_unlock(&mutex);return v;}
unsigned int full_hdmi_pin_audio_connected(void){pthread_mutex_lock(&mutex);unsigned int v=audio_connected;pthread_mutex_unlock(&mutex);return v;}
#ifdef FULL_VEF_TEST
void full_hdmi_pin_test_reset(void){
    pin_registry_test_reset(&registry);pthread_mutex_lock(&mutex);video_connected=audio_connected=0;pthread_mutex_unlock(&mutex);
}
void full_hdmi_pin_test_set_state(unsigned int i,unsigned int value){pin_registry_test_set_state(&registry,i,value);}
#endif
