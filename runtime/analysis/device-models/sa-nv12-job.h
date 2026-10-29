/* SPDX-License-Identifier: MIT */
#ifndef SONY_SA_NV12_JOB_H
#define SONY_SA_NV12_JOB_H
#include <stdint.h>
#define SA_NV12_SOURCE_BYTES (1920u*1080u*2u)
#define SA_NV12_OUTPUT_BYTES (1920u*1080u*3u/2u)
struct sa_nv12_job { uint64_t source,destination,parameters,table,program; };
/* Exact observed job shape only; program identity must be checked separately. */
int sa_nv12_job_decode(const uint32_t registers[1024],const uint32_t parameters[128],
    const uint32_t table[88],struct sa_nv12_job *job);
#endif
