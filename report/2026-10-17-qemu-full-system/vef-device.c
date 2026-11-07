/* SPDX-License-Identifier: MIT */
#include "pin-registry-core.h"
#include <string.h>
#include <pthread.h>
static pthread_mutex_t record_mutex=PTHREAD_MUTEX_INITIALIZER;
static const unsigned char initial_record0[20]={1,0,0,0,0,0,0,0,1,0,0,0,0x80,7,0,0,0x38,4,0,0};
static unsigned char current_record0[20]={1,0,0,0,0,0,0,0,1,0,0,0,0x80,7,0,0,0x38,4,0,0};
static const unsigned int keys[16][3]={
    {0,1,0},{0,1,1},{0,1,2},{0,1,3},{0,1,4},{0,1,5},{0,1,6},
    {0,2,0},{0,2,1},{0,2,2},{0,2,3},{0,2,4},{0,2,5},{0,2,6},{8,1,0},{8,2,0}};
static struct pin_registry_owner registry={.source=FULL_VEF_CP,.count=16,.name="VEF",.keys=keys};
struct pin_registry_owner *full_vef_registry(void){return &registry;}
int full_vef_dispatch(unsigned int d,void *p,const struct full_imaging_io *io,int enabled,int *rc){return pin_registry_dispatch(&registry,d,p,io,enabled,rc);}
int full_vef_release_reply(unsigned int d,void *p,int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *rc){return pin_registry_release(&registry,d,p,release,record,rc);}
void full_vef_snapshot(struct full_vef_snapshot *out){pin_registry_snapshot(&registry,out);}
int full_vef_current_record(unsigned int index,unsigned char *out,unsigned int bytes){
    if(index || !out || bytes!=sizeof initial_record0)return -1;
    pthread_mutex_lock(&record_mutex);memcpy(out,current_record0,sizeof current_record0);pthread_mutex_unlock(&record_mutex);return 0;
}
int full_vef_update_current_record(unsigned int index,const unsigned char *record,unsigned int bytes){
    if(index || !record || bytes!=sizeof current_record0 || record[0]!=1 || record[1] || record[2] || record[3])return -1;
    pthread_mutex_lock(&record_mutex);memcpy(current_record0,record,sizeof current_record0);pthread_mutex_unlock(&record_mutex);return 0;
}
#ifdef FULL_VEF_TEST
void full_vef_test_reset(void){
    pin_registry_test_reset(&registry);
    pthread_mutex_lock(&record_mutex);memcpy(current_record0,initial_record0,sizeof current_record0);pthread_mutex_unlock(&record_mutex);
}
void full_vef_test_set_state(unsigned int i,unsigned int value){pin_registry_test_set_state(&registry,i,value);}
#endif
