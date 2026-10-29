/* SPDX-License-Identifier: MIT
 * QOM read-only observation; no MMIO, interrupt acknowledgement or CPU context.
 */
static char *sony_gic_readback(Object *obj, Error **errp)
{
    GICState *s=ARM_GIC_COMMON(obj);
    (void)errp;
    unsigned zero=0;
    for (unsigned irq=32;irq<MIN(s->num_irq,GIC_MAXIRQ);irq++)
        if (!s->irq_target[irq]) zero++;
    GString *out=g_string_new(NULL);
    g_string_append_printf(out,"{\"schema\":\"sony-gic-readback-v1\",\"observations_only\":true,"
        "\"num_cpu\":%u,\"num_irq\":%u,\"distributor_control\":%u,\"zero_spi_targets\":%u,"
        "\"loader_spi_targets\":%s,\"irqs\":[",
        s->num_cpu,s->num_irq,s->ctlr,zero,s->sony_loader_spi_targets?"true":"false");
    const unsigned irqs[]={33,35,36,48,49,50,198,232,233,234,235};
    bool first=true;
    for (unsigned i=0;i<ARRAY_SIZE(irqs);i++) {
        unsigned irq=irqs[i];
        if (irq>=s->num_irq || irq>=GIC_MAXIRQ) continue;
        const gic_irq_state *state=&s->irq_state[irq];
        g_string_append_printf(out,"%s{\"irq\":%u,\"target\":%u,\"enabled\":%u,\"pending_latch\":%u,"
            "\"active\":%u,\"level\":%u,\"group\":%u,\"priority\":%u,\"edge\":%s}",
            first?"":",",irq,s->irq_target[irq],state->enabled,state->pending,state->active,
            state->level,state->group,s->priority2[irq-32],state->edge_trigger?"true":"false");
        first=false;
    }
    g_string_append(out,"],\"cpus\":[");
    for (unsigned i=0;i<MIN(s->num_cpu,GIC_NCPU);i++)
        g_string_append_printf(out,"%s{\"cpu\":%u,\"control\":%u,\"priority_mask\":%u,"
            "\"running_priority\":%u,\"current_pending\":%u}",i?",":"",i,s->cpu_ctlr[i],
            s->priority_mask[i],s->running_priority[i],s->current_pending[i]);
    g_string_append(out,"]}");
    return g_string_free(out,false);
}
