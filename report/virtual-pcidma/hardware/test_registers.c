#include "registers.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define BASE UINT64_C(0x400010000)
#define PCI UINT64_C(0x04000000)
struct memory { unsigned char ap[4096], pci[4096]; unsigned writes; };
static unsigned char *lookup(struct memory *m, enum sony_edma_domain d, uint64_t a, size_t n)
{
    uint64_t b=d==SONY_EDMA_LOCAL?BASE:PCI;
    return a<b || n>4096 || a-b>4096-n ? NULL : (d==SONY_EDMA_LOCAL?m->ap:m->pci)+(a-b);
}
static int rd(void *p, enum sony_edma_domain d, uint64_t a, void *v, size_t n)
{
    unsigned char *s=lookup(p,d,a,n); if (!s) return -1; memcpy(v,s,n); return 0;
}
static int wr(void *p, enum sony_edma_domain d, uint64_t a, const void *v, size_t n)
{
    struct memory *m=p; unsigned char *s=lookup(m,d,a,n); m->writes++;
    if (!s) return -1;
    memcpy(s,v,n); return 0;
}
static void put32(unsigned char *p, uint32_t v) { for (unsigned i=0;i<4;i++) p[i]=v>>(8*i); }
static void put64(unsigned char *p, uint64_t v) { for (unsigned i=0;i<8;i++) p[i]=v>>(8*i); }
static void set(struct sony_edma_registers *r, struct sony_edma_bus *b, uint32_t a, uint32_t v)
{ assert(!sony_edma_register(r,b,a,&v,1)); }
static uint32_t get(struct sony_edma_registers *r, uint32_t a)
{ uint32_t v=0xdeadbeef; assert(!sony_edma_register(r,NULL,a,&v,0)); return v; }
static void addr(struct sony_edma_registers *r, struct sony_edma_bus *b, uint32_t a, uint64_t v)
{ set(r,b,a,(uint32_t)v); set(r,b,a+4,(uint32_t)(v>>32)); }
static void init(struct memory *m, struct sony_edma_registers *r)
{
    memset(m,0,sizeof *m); memset(m->pci,0xa5,4096); memset(m->ap,0x77,4096);
    for (unsigned i=0;i<256;i++) m->ap[512+i]=(unsigned char)(i*29+11);
    sony_edma_reset(r,8,4096);
}
int main(void)
{
    struct memory m; struct sony_edma_bus bus={&m,rd,wr}; struct sony_edma_registers r;
    for (unsigned d=0;d<2;d++) for (unsigned ch=0;ch<8;ch++) {
        init(&m,&r);
        unsigned c=0x200+ch*0x200+d*0x100, status=d?0xa0:0x4c;
        unsigned door=d?0x30:0x10, first=(d?0x168:0x128)+ch*4;
        set(&r,&bus,c,8); set(&r,&bus,c+8,256);
        addr(&r,&bus,c+0xc,d?PCI+16:BASE+512);
        addr(&r,&bus,c+0x14,d?BASE+1024:PCI+16);
        uint32_t value=ch;
        assert(sony_edma_register(&r,&bus,door,&value,1)==-1 && !m.writes);
        set(&r,&bus,d?0x2c:0xc,1);
        assert(sony_edma_register(&r,&bus,door,&value,1)==-1 && !m.writes);
        set(&r,&bus,first,1); set(&r,&bus,door,ch);
        assert(r.last[d][ch].bytes==256 && r.last[d][ch].result==SONY_EDMA_PAUSED);
        assert(get(&r,status)==(1U<<ch) && get(&r,d?0x4c:0xa0)==0);
        assert(!sony_edma_irq(&r)); /* reset is explicitly masked */
        if (!d) {
            assert(!memcmp(m.pci+16,m.ap+512,256));
            for (unsigned i=0;i<4096;i++) if (i<16 || i>=272) assert(m.pci[i]==0xa5);
        } else {
            for (unsigned i=1024;i<1280;i++) assert(m.ap[i]==0xa5);
            assert(m.ap[1023]==0x77 && m.ap[1280]==0x77);
        }
        assert((get(&r,c)&0x60)==0x60);
        set(&r,&bus,c,0); assert((get(&r,c)&0x60)==0x60); /* status is not CPU-writable */
        set(&r,&bus,status+8,0); assert(sony_edma_irq(&r));
        value=0; assert(sony_edma_register(&r,&bus,status,&value,1)==-1);
        set(&r,&bus,status+12,1U<<ch);
        assert(!get(&r,status) && !sony_edma_irq(&r));
    }
    /* Original 300h/LLE+CCS programming and 1/9/6 native-style list. */
    init(&m,&r); memset(m.ap,0,48);
    put32(m.ap,9); put32(m.ap+4,256); put64(m.ap+8,BASE+512); put64(m.ap+16,PCI+16);
    put32(m.ap+24,6); put64(m.ap+32,BASE);
    set(&r,&bus,0xc,1); set(&r,&bus,0x128,1); set(&r,&bus,0x54,0);
    set(&r,&bus,0x200,0x300); addr(&r,&bus,0x21c,BASE); set(&r,&bus,0x10,0);
    assert(get(&r,0x4c)==1 && sony_edma_irq(&r) && r.last[0][0].entries==1);
    assert(get(&r,0x21c)==(uint32_t)(BASE+24) && !memcmp(m.pci+16,m.ap+512,256));
    set(&r,&bus,0x58,1); assert(!sony_edma_irq(&r));

    /* True target bus failure: abort only, with no successful completion bit. */
    init(&m,&r); set(&r,&bus,0xc,1); set(&r,&bus,0x128,1); set(&r,&bus,0x54,0);
    set(&r,&bus,0x200,8); set(&r,&bus,0x208,256);
    addr(&r,&bus,0x20c,BASE+512); addr(&r,&bus,0x214,UINT64_C(0x10004000000));
    set(&r,&bus,0x10,0);
    assert(get(&r,0x4c)==0x10000 && sony_edma_irq(&r) && r.last[0][0].write_fault);
    assert(!r.last[0][0].bytes && !r.last[0][0].local_interrupt);
    for (unsigned i=0;i<4096;i++) assert(m.pci[i]==0xa5);
    set(&r,&bus,0x58,0x10000); assert(!sony_edma_irq(&r));
    uint32_t value=1;
    assert(sony_edma_register(&r,&bus,0x201,&value,1)==-1);
    assert(sony_edma_register(&r,&bus,0x224,&value,1)==-1);
    assert(sony_edma_register(&r,&bus,0x1200,&value,1)==-1);
    assert(sony_edma_register(&r,&bus,0x10,&(uint32_t){8},1)==-1);
    puts("PASS bounded eDMA registers: 16 direct channels + native-style LLI, actual data/guards, masks/W1C, read-only state, abort-not-done; NO QEMU/original driver proof");
}
