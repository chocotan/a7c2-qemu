/* SPDX-License-Identifier: MIT */
#include "adf-aip-gates.h"
int full_adf_aip_gates_init(struct full_adf_aip_gates *out,
                           const struct full_adf_aip_gate_registers *initial,unsigned int init_f)
{
    if (!out || !initial || init_f>1) return -1021;
    const unsigned char *bytes=(const unsigned char *)out;
    for (unsigned long i=0;i<sizeof *out;i++) if (bytes[i]) return -1021;
    struct full_adf_aip_gates next={0};
    next.known=1;next.init_parameter_f=init_f;next.registers=*initial;
    *out=next;
    return 0;
}
int full_adf_aip_gates_mode0(struct full_adf_aip_gates *s,unsigned long long generation)
{
    /* shortcut: owned S0/K0, F0/F1, generation1 only; extend after active-state lifecycle proof. */
    if (!s || s->known!=1 || s->software_s || s->software_k || s->init_parameter_f>1 ||
        generation!=1 || s->generation || s->writes || s->readbacks) return -1021;
    struct full_adf_aip_gates next=*s;
    unsigned int reset=next.registers.reset3900;
    next.registers.reset3900&=~0x100u;
    next.writes++;
    if (next.registers.reset3900!=(reset&~0x100u)) return -1021;
    next.readbacks++;
    next.registers.gate0c50=0;next.writes++;
    if (next.registers.gate0c50) return -1021;
    next.readbacks++;
    next.registers.gate8814=next.init_parameter_f==1?0x20:0;next.writes++;
    if (next.registers.gate8814!=(next.init_parameter_f==1?0x20u:0u)) return -1021;
    next.readbacks++;
    /* b69dfe S0 returns0 without reading H/B/C/D; do not invent zeros for those owners. */
    unsigned int classification=0;
    next.registers.classification0c54=classification;next.writes++;
    if (next.registers.classification0c54!=classification) return -1021;
    next.readbacks++;
    next.registers.gate23e0=0;next.writes++;
    if (next.registers.gate23e0) return -1021;
    next.readbacks++;
    next.generation=generation;
    *s=next;
    return 0;
}
