#include "lli.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

#define LOCAL_BASE UINT64_C(0x400010000)
#define PCI_BASE UINT64_C(0x04000000)
struct memory { unsigned char local[4096], pci[4096]; unsigned reads, writes; };
static void put32(unsigned char *p, uint32_t x) { for (unsigned i=0;i<4;i++) p[i]=x>>(i*8); }
static void put64(unsigned char *p, uint64_t x) { for (unsigned i=0;i<8;i++) p[i]=x>>(i*8); }
static unsigned char *lookup(struct memory *m, enum sony_edma_domain d, uint64_t a, size_t n)
{
    uint64_t base = d==SONY_EDMA_LOCAL ? LOCAL_BASE : PCI_BASE;
    if (a<base || n>4096 || a-base>4096-n) return NULL;
    return (d==SONY_EDMA_LOCAL ? m->local : m->pci)+(size_t)(a-base);
}
static int read_mem(void *opaque, enum sony_edma_domain d, uint64_t a, void *p, size_t n)
{
    struct memory *m=opaque; unsigned char *from=lookup(m,d,a,n); m->reads++;
    if (!from) return -1;
    memcpy(p,from,n); return 0;
}
static int write_mem(void *opaque, enum sony_edma_domain d, uint64_t a, const void *p, size_t n)
{
    struct memory *m=opaque; unsigned char *to=lookup(m,d,a,n); m->writes++;
    if (!to) return -1;
    memcpy(to,p,n); return 0;
}
static void descriptor(unsigned char *p, uint32_t control, uint32_t length, uint64_t src, uint64_t dst)
{
    put32(p,control); put32(p+4,length); put64(p+8,src); put64(p+16,dst);
}
static void setup(struct memory *m)
{
    memset(m,0,sizeof *m); memset(m->pci,0xa5,sizeof m->pci);
    for (unsigned i=0;i<512;i++) m->local[512+i]=(unsigned char)(i*37+11);
    descriptor(m->local,9,256,LOCAL_BASE+512,PCI_BASE+16);
    descriptor(m->local+24,6,0,LOCAL_BASE,0);
}
int main(void)
{
    struct memory m; struct sony_edma_bus bus={&m,read_mem,write_mem};
    struct sony_edma_outcome o;
    setup(&m); o=sony_edma_consume(&bus,LOCAL_BASE,1,1,8,4096);
    assert(o.result==SONY_EDMA_PAUSED && o.local_interrupt && o.bytes==256 && o.entries==1);
    assert(o.next==LOCAL_BASE+24 && !memcmp(m.pci+16,m.local+512,256));
    for (unsigned i=0;i<4096;i++) if (i<16 || i>=272) assert(m.pci[i]==0xa5);

    setup(&m); memset(m.local+2048,0x71,258);
    descriptor(m.local,9,256,PCI_BASE+16,LOCAL_BASE+2049);
    o=sony_edma_consume(&bus,LOCAL_BASE,1,0,8,4096);
    assert(o.result==SONY_EDMA_PAUSED && o.local_interrupt && o.bytes==256);
    assert(m.local[2048]==0x71 && m.local[2305]==0x71);
    assert(!memcmp(m.local+2049,m.pci+16,256));

    /* First cycle-bit mismatch is a pause, not fabricated completion. */
    setup(&m); put32(m.local,0); o=sony_edma_consume(&bus,LOCAL_BASE,1,1,8,4096);
    assert(o.result==SONY_EDMA_PAUSED && !o.local_interrupt && !o.bytes && !m.writes);
    setup(&m); put32(m.local,1); o=sony_edma_consume(&bus,LOCAL_BASE,1,1,8,4096);
    assert(o.result==SONY_EDMA_PAUSED && !o.local_interrupt && o.bytes==256);

    /* Valid LLP with toggle changes consumer phase before following pointer. */
    setup(&m); descriptor(m.local,7,0,LOCAL_BASE+128,0);
    descriptor(m.local+128,8,16,LOCAL_BASE+512,PCI_BASE+16);
    put32(m.local+152,1); o=sony_edma_consume(&bus,LOCAL_BASE,1,1,8,4096);
    assert(o.result==SONY_EDMA_PAUSED && !o.phase && o.entries==2 && o.bytes==16 && o.local_interrupt);

    setup(&m); o=sony_edma_consume(&bus,LOCAL_BASE+4096,1,1,8,4096);
    assert(o.result==SONY_EDMA_FAULT && !o.local_interrupt && !m.writes);
    setup(&m); put64(m.local+8,LOCAL_BASE+4096);
    o=sony_edma_consume(&bus,LOCAL_BASE,1,1,8,4096);
    assert(o.result==SONY_EDMA_FAULT && !o.bytes && !m.writes && !o.local_interrupt);
    setup(&m); put64(m.local+16,UINT64_C(0x10004000000));
    o=sony_edma_consume(&bus,LOCAL_BASE,1,1,8,4096);
    assert(o.result==SONY_EDMA_FAULT && o.write_fault && !o.bytes && !o.local_interrupt);
    for (unsigned i=0;i<4096;i++) assert(m.pci[i]==0xa5);
    setup(&m); put64(m.local+16,UINT64_MAX-10);
    o=sony_edma_consume(&bus,LOCAL_BASE,1,1,8,4096);
    assert(o.result==SONY_EDMA_FAULT && !m.writes);
    setup(&m); put32(m.local+4,0);
    assert(sony_edma_consume(&bus,LOCAL_BASE,1,1,8,4096).result==SONY_EDMA_FAULT);
    setup(&m); put32(m.local,25);
    assert(sony_edma_consume(&bus,LOCAL_BASE,1,1,8,4096).result==SONY_EDMA_UNSUPPORTED);
    setup(&m); assert(sony_edma_consume(&bus,LOCAL_BASE,1,1,8,255).result==SONY_EDMA_BUDGET);
    assert(!m.writes);
    setup(&m); descriptor(m.local,5,0,LOCAL_BASE,0);
    assert(sony_edma_consume(&bus,LOCAL_BASE,1,1,3,4096).result==SONY_EDMA_BUDGET);

    /* A later bus fault preserves earlier real writes but never signals done. */
    setup(&m); descriptor(m.local,9,512,LOCAL_BASE+512,PCI_BASE+4096-300);
    o=sony_edma_consume(&bus,LOCAL_BASE,1,1,8,4096);
    assert(o.result==SONY_EDMA_FAULT && o.write_fault && o.bytes==256 && !o.local_interrupt);
    assert(!memcmp(m.pci+4096-300,m.local+512,256));
    assert(sony_edma_consume(NULL,LOCAL_BASE,1,1,8,4096).result==SONY_EDMA_BAD_INPUT);
    assert(sony_edma_consume(&bus,LOCAL_BASE,2,1,8,4096).result==SONY_EDMA_BAD_INPUT);
    assert(sony_edma_consume(&bus,LOCAL_BASE,1,2,8,4096).result==SONY_EDMA_BAD_INPUT);
    puts("PASS bounded eDMA LLI consumer: actual domain-backed bytes/guards, phase/LLP, faults/partial writes, limits; NO QEMU/original driver/CP proof");
}
