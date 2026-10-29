/* SPDX-License-Identifier: MIT */
#include "sa-nv12-job.h"

static int overlap(uint64_t a,uint64_t asize,uint64_t b,uint64_t bsize)
{ return a<b+bsize && b<a+asize; }

int sa_nv12_job_decode(const uint32_t r[1024],const uint32_t p[128],
    const uint32_t t[88],struct sa_nv12_job *job)
{
    if (r[0]!=1 || r[1]!=1 || r[2]!=0x80000000 || r[0x60/4] ||
        r[0x118/4] || r[0x11c/4] || !r[0x30/4] || !r[0x110/4] || !r[0x114/4]) return -1;
    for (unsigned i=0;i<128;i++) {
        uint32_t expected=0;
        switch(i) {
        case 0:expected=0x1564e;break;case 1:expected=1920;break;
        case 2:expected=1080;break;case 3:expected=3840;break;
        case 4:expected=1;break;case 8:case 9:expected=p[i];break;
        }
        if (p[i]!=expected) return -1;
    }
    const uint32_t expected[88]={[0]=1,[2]=0x180,[3]=r[0x110/4],
        [4]=1,[5]=0x200,[6]=0x1518180,[7]=p[8],
        [8]=1,[9]=0x1518200,[10]=0x2a30180,[11]=p[9]};
    for (unsigned i=0;i<88;i++) if (t[i]!=expected[i]) return -1;
    struct sa_nv12_job candidate={
        .source=UINT64_C(0x400000000)+(uint64_t)p[8]*4,
        .destination=UINT64_C(0x400000000)+(uint64_t)p[9]*4,
        .parameters=UINT64_C(0x400000000)+(uint64_t)r[0x110/4]*4,
        .table=UINT64_C(0x400000000)+(uint64_t)r[0x114/4]*4,
        .program=UINT64_C(0x400000000)+r[0x30/4]};
    const uint64_t addresses[]={candidate.source,candidate.destination,candidate.parameters,candidate.table,candidate.program};
    const uint64_t lengths[]={SA_NV12_SOURCE_BYTES,SA_NV12_OUTPUT_BYTES,512,352,0x1400};
    for (unsigned i=0;i<5;i++) {
        if (addresses[i]>UINT64_C(0x500000000)-lengths[i]) return -1;
        for (unsigned j=0;j<i;j++) if (overlap(addresses[i],lengths[i],addresses[j],lengths[j])) return -1;
    }
    *job=candidate;
    return 0;
}
