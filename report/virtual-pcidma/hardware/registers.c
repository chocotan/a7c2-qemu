#include "registers.h"
#include <string.h>

void sony_edma_reset(struct sony_edma_registers *s, unsigned max_steps, uint64_t max_bytes)
{
    memset(s,0,sizeof *s);
    s->mask[0]=s->mask[1]=UINT32_MAX;
    s->max_steps=max_steps; s->max_bytes=max_bytes;
}
int sony_edma_irq(const struct sony_edma_registers *s)
{
    return !!((s->status[0]&~s->mask[0]) | (s->status[1]&~s->mask[1]));
}
static uint64_t address(const uint32_t *r) { return r[0] | (uint64_t)r[1]<<32; }
static int ring(struct sony_edma_registers *s, const struct sony_edma_bus *bus,
                 unsigned direction, uint32_t value)
{
    unsigned ch=value&7;
    if (value&~7U || !(s->enabled[direction]&1) || s->first_word[direction][ch]!=1 ||
        !s->max_steps || !s->max_bytes || !bus || !bus->read || !bus->write) return -1;
    uint32_t *r=s->channel[direction][ch];
    uint32_t control=r[0]&~0x60U;
    /* Unsupported modes are errors, never successful doorbell acknowledgments. */
    if (control!=8 && control!=0x300 && control!=0x200) return -1;
    r[0]=control|0x20;
    struct sony_edma_outcome out;
    if (control&0x200) {
        out=sony_edma_consume(bus,address(r+7),!!(control&0x100),!direction,
                              s->max_steps,s->max_bytes);
        r[7]=(uint32_t)out.next; r[8]=(uint32_t)(out.next>>32);
        control=(control&~0x100U)|(out.phase<<8);
    } else {
        out=sony_edma_copy(bus,address(r+3),address(r+5),r[2],!direction,s->max_bytes);
        out.local_interrupt=out.result==SONY_EDMA_PAUSED && !!(control&8);
    }
    s->last[direction][ch]=out;
    if (out.result==SONY_EDMA_PAUSED) {
        r[0]=control|0x60;
        if (out.local_interrupt) s->status[direction] |= 1U<<ch;
    } else {
        r[0]=control|0x40;
        s->status[direction] |= 1U<<(16+ch);
    }
    return 0;
}
int sony_edma_register(struct sony_edma_registers *s, const struct sony_edma_bus *bus,
                        uint32_t offset, uint32_t *value, unsigned write)
{
    if (!s || !value || write>1 || offset&3) return -1;
    uint32_t *field=NULL;
    for (unsigned d=0;d<2;d++) {
        uint32_t first=d?0x168:0x128, status=d?0xa0:0x4c;
        if (offset>=first && offset<first+32) field=&s->first_word[d][(offset-first)/4];
        if (offset==(d?0x2c:0xc)) field=&s->enabled[d];
        if (offset==(d?0xc4:0x90)) field=&s->list_errors[d];
        /* Error status registers: no error production modeled; reads return 0
         * (the pinned thread handler reads them after INTSTAT), writes reject. */
        if (offset==(d?0xb4:0x5c)) { if (write) return -1; *value=s->error_status[d?1:0]; return 0; }
        if (offset==0xb8) { if (write) return -1; *value=s->error_status[2]; return 0; }
        if (offset==status+8) field=&s->mask[d];
        if (offset==status) {
            if (write) return -1;
            *value=s->status[d]; return 0;
        }
        if (offset==status+12) {
            if (!write) return -1;
            s->status[d]&=~*value; return 0;
        }
        if (offset==(d?0x30:0x10)) return write?ring(s,bus,d,*value):-1;
    }
    if (offset>=0x200 && offset<0x1200) {
        unsigned ch=(offset-0x200)/0x200;
        unsigned d=!!(offset&0x100), reg=offset&0xff;
        if (reg>0x20) return -1;
        field=&s->channel[d][ch][reg/4];
        if (write && reg==0) {
            *field=(*value&~0x60U)|(*field&0x60U);
            return 0;
        }
    }
    if (!field) return -1;
    if (write) *field=*value; else *value=*field;
    return 0;
}
