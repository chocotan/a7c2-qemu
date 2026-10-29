/* SPDX-License-Identifier: MIT */
#include "rc-reference.h"
#include <string.h>

static int channel(const uint32_t dma[32], uint64_t *physical)
{
    for (unsigned i=0;i<32;i++) {
        uint32_t expected=0;
        if (i==0) expected=3;
        if (i==6) expected=dma[6];
        if (i==8) expected=dma[8];
        if (i==9) expected=3840;
        if (i==11) expected=1079;
        if (dma[i]!=expected) return -1;
    }
    if (dma[6]!=0 && dma[6]!=0x100) return -1;
    *physical=UINT64_C(0x400000000)+((uint64_t)(dma[6]>>8)<<32)+dma[8];
    if (*physical>UINT64_C(0x600000000)-1920u*1080u*2u) return -1;
    return 0;
}

int rc_reference_decode(const uint32_t rc[32], const uint32_t input[32],
                        const uint32_t output[32], const uint32_t input_pack[4],
                        const uint32_t output_pack[4], struct rc_reference_request *request)
{
    const uint32_t expected[32]={[0]=1,[1]=0x00c0050a,[3]=0x01000100,[4]=0x01000100,
        [6]=0x1000,[7]=0x1000,[10]=0x07800438,[11]=0x07800438,[12]=1,[15]=0x07800438};
    const uint32_t plain_input[4]={0},plain_output[4]={0,0,1,0};
    struct rc_reference_request candidate={0};
    for (unsigned i=0;i<32;i++) {
        if (i==2) { if (rc[i]&~UINT32_C(0x1000000)) return -1; }
        else if (rc[i]!=expected[i]) return -1;
    }
    if (memcmp(input_pack,plain_input,sizeof plain_input) ||
        memcmp(output_pack,plain_output,sizeof plain_output) ||
        channel(input,&candidate.source) || channel(output,&candidate.destination)) return -1;
    const uint64_t bytes=1920u*1080u*2u;
    if (candidate.source<candidate.destination+bytes && candidate.destination<candidate.source+bytes)
        return -1;
    candidate.input=(struct rc_identity_image){.width=1920,.height=1080,.stride=3840,
        .capacity=bytes,.format=0,.phase=0,.type=1};
    candidate.output=candidate.input;
    *request=candidate;
    return 0;
}
