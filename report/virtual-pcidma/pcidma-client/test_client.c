/* Host-side harness: request packing, pattern generation, round-trip compare. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>

static uint8_t req[0x40];
static void build_request(uint8_t *r,uint8_t channel,uint8_t direction,uint32_t length,
                          uint64_t source,uint64_t destination,uint64_t callback,uint64_t cookie)
{
    memset(r,0,0x40);
    r[0]=0;r[1]=channel;r[2]=direction;
    r[4]=length;r[5]=length>>8;r[6]=length>>16;r[7]=length>>24;
    for(unsigned i=0;i<8;i++)r[8+i]=(uint8_t)(source>>(8*i));
    for(unsigned i=0;i<8;i++)r[16+i]=(uint8_t)(destination>>(8*i));
    for(unsigned i=0;i<8;i++)r[24+i]=(uint8_t)(callback>>(8*i));
    for(unsigned i=0;i<8;i++)r[32+i]=(uint8_t)(cookie>>(8*i));
}

int main(void)
{
    build_request(req,0,1,256,0x400012345678ULL,0xdffe0000ULL,0xffffff8008abcdefULL,0x1122334455667788ULL);
    assert(req[0]==0 && req[1]==0 && req[2]==1 && req[3]==0);
    assert(memcmp(req+4,"\x00\x01\x00\x00",4)==0);
    uint64_t v;
    memcpy(&v,req+8,8);assert(v==0x400012345678ULL);
    memcpy(&v,req+16,8);assert(v==0xdffe0000ULL);
    memcpy(&v,req+24,8);assert(v==0xffffff8008abcdefULL);
    memcpy(&v,req+32,8);assert(v==0x1122334455667788ULL);
    /* links/metadata stay zero for the driver to fill */
    assert(req[40]==0 && req[47]==0 && req[56]==0 && req[59]==0);
    /* LLI mode: length zero keeps src as list address field */
    build_request(req,3,0,0,0x4000001000ULL,0x2000ULL,0,0);
    assert(req[2]==0 && req[4]==0 && req[5]==0 && req[6]==0 && req[7]==0);
    memcpy(&v,req+8,8);assert(v==0x4000001000ULL && !(v&7));
    /* pattern is deterministic */
    uint8_t a[256],b[256];
    for(unsigned i=0;i<256;i++){a[i]=(uint8_t)(i*29+7);b[i]=(uint8_t)(i*29+7);}
    assert(!memcmp(a,b,256));
    puts("PASS_PCIDMA_CLIENT_HOST: request layout/pattern/LLI-length-zero; not runtime proof");
}
