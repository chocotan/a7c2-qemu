/* SPDX-License-Identifier: MIT */
#include "adf-aip-coefficients.h"
#include <string.h>
static const unsigned int mode0[16]={
    0x3f85,0x39f2,0x3e99,0x3ff9,0x022e,0x037f,0x02d2,0x3fff,
    0x3c2e,0x3992,0x3a74,0x0000,0x0979,0x143f,0x1cc3,0x1fff
};
int full_adf_aip_coefficients_init(struct full_adf_aip_coefficients *out,
                                  const unsigned int *initial,unsigned int control3904)
{
    if (!out || !initial) return -1021;
    const unsigned char *bytes=(const unsigned char *)out;
    for (unsigned long i=0;i<sizeof *out;i++) if (bytes[i]) return -1021;
    struct full_adf_aip_coefficients next={0};
    next.known=1;next.control3904=control3904;
    memcpy(next.registers,initial,sizeof next.registers);
    *out=next;
    return 0;
}
int full_adf_aip_coefficients_mode0(struct full_adf_aip_coefficients *s,unsigned long long generation)
{
    /* shortcut: mode0 and first generation only; complete reset/gates and other modes separately. */
    if (!s || s->known!=1 || generation!=1 || s->generation || s->writes || s->readbacks) return -1021;
    struct full_adf_aip_coefficients next=*s;
    for (unsigned int i=0;i<16;i++) {
        unsigned int upper=next.registers[i]&~0x3fffu;
        next.registers[i]=upper|mode0[i]; /* b6cc64: f48a3800+4*i, bfi width14. */
        next.writes++;
        if ((next.registers[i]&0x3fff)!=mode0[i] || (next.registers[i]&~0x3fffu)!=upper) return -1021;
        next.readbacks++;
    }
    unsigned int before=next.control3904;
    next.control3904&=~(1u<<24); /* b6cd04 -> b6c32c(0). */
    if (next.control3904!=(before&~(1u<<24))) return -1021;
    next.generation=generation;
    *s=next;
    return 0;
}
