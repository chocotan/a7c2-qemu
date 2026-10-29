/* SPDX-License-Identifier: MIT */
#include "adf-aip-disable.h"
int full_adf_aip_disable_init(struct full_adf_aip_disable *out,
                             const struct full_adf_aip_disable_registers *initial,unsigned int software_byte)
{
    if (!out || !initial || software_byte>255) return -1021;
    const unsigned char *bytes=(const unsigned char *)out;
    for (unsigned long i=0;i<sizeof *out;i++) if (bytes[i]) return -1021;
    struct full_adf_aip_disable next={0};
    next.known=1;next.software_byte=software_byte;next.registers=*initial;
    *out=next;return 0;
}
int full_adf_aip_disable_apply(struct full_adf_aip_disable *s,unsigned int software_s)
{
    /* shortcut: cold S0 AF/B0 then Notify2 B0 only; prove active callbacks/other lifecycles before extending. */
    if (!s || s->known!=1 || software_s || (s->registers.active0400&1) || s->calls>=3 ||
        s->writes!=s->calls*7 || s->readbacks!=s->calls*7 || s->software_byte>255 ||
        s->completion_byte!=(s->calls?1u:0u)) return -1021;
    struct full_adf_aip_disable next=*s;
    unsigned int active=next.registers.active0400;
    next.software_byte=0; /* b68098: 1a743b4. */
    unsigned int *routes[]={&next.registers.route8828,&next.registers.route882c,&next.registers.route8830,
        &next.registers.route8928,&next.registers.route892c,&next.registers.route8930,&next.registers.controla000};
    for (unsigned int i=0;i<7;i++) {
        *routes[i]=0;next.writes++;
        if (*routes[i]) return -1021;
        next.readbacks++;
    }
    if (next.registers.active0400!=active) return -1021;
    next.completion_byte=1; /* b69940(1), only after actual disable writes. */
    next.calls++;
    *s=next;return 0;
}
