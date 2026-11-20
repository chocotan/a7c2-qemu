/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_CAPTURE_RAW_H
#define FUNCTIONAL_CAPTURE_RAW_H
#include "../../report/functional-capture-output/capture-output-memory.h"
#include "functional-capture-raw-blobs.h"
int functional_capture_raw_native_writer_arm(struct capture_output_memory *);
int functional_capture_raw_native_writer_ready(struct capture_output_memory *);
/* Current serialized capture, not a standalone readiness flag. */
int functional_capture_raw_writer_current(struct capture_output_memory *,uint64_t *,uintptr_t *,uint64_t *);
void functional_capture_raw_writer_fault(int);
void functional_capture_raw_native_event(struct capture_output_memory *,uint64_t,uintptr_t,uint64_t,int,int);
#endif
