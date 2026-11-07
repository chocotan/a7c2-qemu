/* SPDX-License-Identifier: MIT */
/* Unrelated extracted-main fixtures have no capture owner. These functions
 * delegate without I/O; test-functional-capture.c executes the real owner. */
#ifndef TEST_CAPTURE_INACTIVE_FIXTURE_H
#define TEST_CAPTURE_INACTIVE_FIXTURE_H
#include <stdint.h>
void functional_capture_observe_received(unsigned id,void *p){(void)id;(void)p;}
void functional_capture_observe_freed(unsigned id,void *p,int rc,uintptr_t caller){(void)id;(void)p;(void)rc;(void)caller;}
int functional_capture_release_notification(unsigned id,void *p,int *rc){(void)id;(void)p;(void)rc;return 0;}
void full_imaging_functional_observe_receive(unsigned id,void *p,unsigned source,unsigned bytes){(void)id;(void)p;(void)source;(void)bytes;}
int full_imaging_release_reply(unsigned id,void *p,int (*release)(unsigned,void *),void (*record)(const char *,const char *),int *rc){(void)id;(void)p;(void)release;(void)record;(void)rc;return 0;}
#endif
