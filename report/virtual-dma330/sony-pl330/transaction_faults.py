"""Add real MemTx error handling to stock PL330; no success/ready shortcuts."""


def transform(source):
    changes = [
        ('''    int i, t, n;

    t = i = s->head;
    for (n = 0; n < s->num; n++) {
        if (s->tag[i] != tag) {
            s->buf[t] = s->buf[i];
            s->tag[t] = s->tag[i];
            t = pl330_fifo_inc(s, t);
        } else {
            s->num = s->num - 1;
        }
        i = pl330_fifo_inc(s, i);
    }''',
         '''    int i, t, n, kept = 0;
    int original_num = s->num;

    t = i = s->head;
    for (n = 0; n < original_num; n++) {
        if (s->tag[i] != tag) {
            s->buf[t] = s->buf[i];
            s->tag[t] = s->tag[i];
            t = pl330_fifo_inc(s, t);
            kept++;
        }
        i = pl330_fifo_inc(s, i);
    }
    s->num = kept;'''),
        ('''        if (pl330_fifo_has_tag(&s->fifo, ch->tag) ||
            pl330_queue_find_insn(&s->read_queue, ch->tag, false) != NULL ||''',
         '''        /* ARM DDI 0424A section 4.3.2: finish outstanding transfers,
         * then flush this thread's MFIFO. Surplus prefetched bytes alone
         * must not prevent END from reaching the tagged flush below.
         */
        if (pl330_queue_find_insn(&s->read_queue, ch->tag, false) != NULL ||'''),
        ('/*\n * For information about instructions see PL330 Technical Reference Manual.',
         '''/* Cancel this tag's pending operations before exposing its bus fault. */
static void pl330_memtx_fault(PL330Chan *ch, uint32_t fault)
{
    PL330State *s = ch->parent;
    pl330_fifo_tagged_remove(&s->fifo, ch->tag);
    pl330_queue_remove_tagged(&s->read_queue, ch->tag);
    pl330_queue_remove_tagged(&s->write_queue, ch->tag);
    pl330_fault(ch, fault);
}

/*
 * For information about instructions see PL330 Technical Reference Manual.'''),
        ('''    dma_memory_read(ch->parent->mem_as, ch->pc, &opcode, 1,
                    MEMTXATTRS_UNSPECIFIED);''',
         '''    if (dma_memory_read(ch->parent->mem_as, ch->pc, &opcode, 1,
                        MEMTXATTRS_UNSPECIFIED) != MEMTX_OK) {
        pl330_memtx_fault(ch, PL330_FAULT_INSTR_FETCH_ERR);
        return NULL;
    }'''),
        ('''    dma_memory_read(ch->parent->mem_as, ch->pc, buf, insn->size,
                    MEMTXATTRS_UNSPECIFIED);''',
         '''    if (dma_memory_read(ch->parent->mem_as, ch->pc, buf, insn->size,
                        MEMTXATTRS_UNSPECIFIED) != MEMTX_OK) {
        pl330_memtx_fault(ch, PL330_FAULT_INSTR_FETCH_ERR);
        return;
    }'''),
        ('''        pl330_fault(ch, PL330_FAULT_UNDEF_INSTR);
        return 0;
    }
    pl330_exec_insn(ch, insn);
    if (!ch->stall) {''',
         '''        if (ch->state != pl330_chan_fault) {
            pl330_fault(ch, PL330_FAULT_UNDEF_INSTR);
        }
        return 0;
    }
    pl330_exec_insn(ch, insn);
    if (ch->state == pl330_chan_fault) {
        return 0;
    }
    if (!ch->stall) {'''),
        ('''        dma_memory_read(s->mem_as, q->addr, buf, len,
                        MEMTXATTRS_UNSPECIFIED);''',
         '''        if (dma_memory_read(s->mem_as, q->addr, buf, len,
                            MEMTXATTRS_UNSPECIFIED) != MEMTX_OK) {
            pl330_memtx_fault(&s->chan[q->tag], PL330_FAULT_DATA_READ_ERR);
            return num_exec;
        }'''),
        ('''            dma_memory_write(s->mem_as, q->addr, buf, len,
                             MEMTXATTRS_UNSPECIFIED);''',
         '''            if (dma_memory_write(s->mem_as, q->addr, buf, len,
                                 MEMTXATTRS_UNSPECIFIED) != MEMTX_OK) {
                pl330_memtx_fault(&s->chan[q->tag], PL330_FAULT_DATA_WRITE_ERR);
                return num_exec;
            }'''),
    ]
    for old, new in changes:
        if source.count(old) != 1:
            raise ValueError('PL330 source differs: unique transaction patch anchor absent')
        source = source.replace(old, new)
    return source
