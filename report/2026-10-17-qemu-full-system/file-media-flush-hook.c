/* SPDX-License-Identifier: MIT */
/* Native integration pattern: flush in the model sender; retry only ACKs in the worker. */
#include "file-media-flush-hook.h"
#include <pthread.h>
#include <stdlib.h>
#include <unistd.h>

static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static void (*pending)(void),(*retry)(void);
static int worker_started;
static pid_t owner;

static void *ack_worker(void *unused) {
    (void)unused;
    for (;;) { usleep(100000); retry(); }
    return 0;
}

void full_file_media_before_send(unsigned int id,void *(*lookup)(void *,const char *),
                                 void (*record)(const char *,const char *)) {
    const char *enabled=getenv("A7C2_FILE_MEDIA_TEST");
    if (id!=0x9088076bU || !enabled || enabled[0]!='1' || enabled[1] || !lookup) return;
    pid_t pid=getpid(),expected=0;
    __atomic_compare_exchange_n(&owner,&expected,pid,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
    /* A fork child may inherit a locked mutex; reject it before taking the lock. */
    if (__atomic_load_n(&owner,__ATOMIC_ACQUIRE)!=pid) return;
    pthread_mutex_lock(&lock);
    if (!pending) pending=lookup(0,"file_media_flush_pending");
    if (!retry) retry=lookup(0,"file_media_flush_cancel_retry");
    if (pending && retry && !worker_started) {
        pthread_t thread;
        if (!pthread_create(&thread,0,ack_worker,0)) {
            pthread_detach(thread);
            worker_started=1;
            if (record) record("FULL_FILE_MEDIA_FLUSH_BOUND ","model_thread=1 ack_retry_worker=1");
        }
    }
    int ready=worker_started;
    pthread_mutex_unlock(&lock);
    if (ready) pending();
}
