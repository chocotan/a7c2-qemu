/* Branch coverage for the real static 0x8da97e transcription (derive_4080).
 * Including the device source keeps every input path inside the model: seeds
 * go straight into the tracked parameter area, so branch selectors that no
 * public command can set are still exercised exactly as the helper sees them. */
#define _GNU_SOURCE
#include "cp-background-device.c"
#include <stdio.h>
#include <stdlib.h>
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1); } } while (0)
static void reset(void) { memset(&config,0,sizeof config); }
static void seed_word(unsigned off,uint32_t v) {
    for(unsigned i=0;i<4;i++) { config.value[off+i]=(unsigned char)(v>>(8*i));config.known[off+i]=1; }
}
static void seed_byte(unsigned off,unsigned v) { config.value[off]=(unsigned char)v;config.known[off]=1; }
static void drop_word(unsigned off) { for(unsigned i=0;i<4;i++)config.known[off+i]=0; }
static uint32_t word(unsigned off) { return u32(config.value+off); }
static void check_out(unsigned k22c,uint32_t v22c,unsigned k230,uint32_t v230,
                      unsigned k234,uint32_t v234,unsigned k218,uint32_t v218) {
    struct derived4080 out;derive_4080(&out);
    CHECK(out.known[0]==k22c && (!k22c || word(0x22c)==v22c));
    CHECK(out.known[1]==k230 && (!k230 || word(0x230)==v230));
    CHECK(out.known[2]==k234 && (!k234 || word(0x234)==v234));
    CHECK(out.known[3]==k218 && (!k218 || config.value[0x218]==(unsigned char)v218));
    CHECK(config.known[0x22c]==k22c && config.known[0x230]==k230 &&
          config.known[0x234]==k234 && config.known[0x218]==k218);
    return;
}
int main(void) {
    /* branch 1: selector W21c==1, constants 2/2/2, B218=(W214==1) */
    for(unsigned v=0;v<256;v++) {
        reset();seed_word(0x21c,1);seed_word(0x214,v);
        check_out(1,2,1,2,1,2,1,v==1);
    }
    reset();seed_word(0x21c,1);seed_word(0x214,0x100);check_out(1,2,1,2,1,2,1,0);
    reset();seed_word(0x21c,1);drop_word(0x214);check_out(1,2,1,2,1,2,0,0);
    /* branch 2: W21c!=1 (known), B2a4==2 -> all zeros */
    reset();seed_word(0x21c,2);seed_byte(0x2a4,2);seed_word(0x214,1);seed_word(0x1fc,1);
    check_out(1,0,1,0,1,0,1,0);
    /* branch 3: W21c known!=1, B2a4 known!=2 */
    reset();seed_word(0x21c,0);seed_byte(0x2a4,0);
    for(unsigned v=0;v<256;v++) { /* W1fc sweep drives both sides of ==1 */
        seed_word(0x1fc,v);
        if(v==1)check_out(0,0,0,0,0,0,0,0); /* B228 unknown -> selector unknown */
        else check_out(1,0,0,0,0,0,0,0);
    }
    for(unsigned v=0;v<256;v++) { /* B228 selects W224 vs W200 */
        reset();seed_word(0x21c,3);seed_byte(0x2a4,7);seed_word(0x1fc,1);seed_word(0x224,v);seed_word(0x200,v^1);
        seed_byte(0x228,1);check_out(1,v==1,0,0,0,0,0,0);
        seed_byte(0x228,0);check_out(1,(v^1)==1,0,0,0,0,0,0);
        seed_byte(0x228,0xff);check_out(1,v==1,0,0,0,0,0,0);
    }
    for(unsigned a=0;a<256;a++)for(unsigned b=0;b<256;b++) { /* W208/W204 -> W230 */
        reset();seed_word(0x21c,9);seed_byte(0x2a4,1);seed_word(0x208,a);seed_word(0x204,b);
        check_out(0,0,1,a==1?(b==2?3:b==1?1:0):0,0,0,0,0);
    }
    for(unsigned a=0;a<256;a++)for(unsigned b=0;b<256;b++) { /* W20c/W210 -> W234 and B218 */
        reset();seed_word(0x21c,9);seed_byte(0x2a4,1);seed_word(0x20c,a);seed_word(0x210,b);
        check_out(0,0,0,0,1,(a==1)&&(b==1),1,(a==1)&&(b==1));
    }
    /* selector or dependency unknown -> derived stores unknown, stale values kept */
    reset();seed_word(0x214,1);check_out(0,0,0,0,0,0,0,0);
    reset();seed_word(0x21c,2);check_out(0,0,0,0,0,0,0,0); /* B2a4 unknown */
    reset();seed_word(0x21c,2);seed_byte(0x2a4,2);derive_4080(&(struct derived4080){0});
    CHECK(config.known[0x22c]&&word(0x22c)==0);drop_word(0x21c);derive_4080(&(struct derived4080){0});
    CHECK(!config.known[0x22c]&&!config.known[0x230]&&!config.known[0x234]&&!config.known[0x218]);
    CHECK(word(0x22c)==0); /* unknown keeps bytes, never fabricates a baseline */
    reset();seed_word(0x21c,2);seed_byte(0x2a4,1);seed_word(0x1fc,1);seed_word(0x200,1);seed_word(0x204,2);
    seed_word(0x208,1);seed_word(0x20c,1);seed_word(0x210,1);
    check_out(0,0,1,3,1,1,1,1); /* full branch 3 with only B228 unknown */
    seed_byte(0x228,0);check_out(1,1,1,3,1,1,1,1);
    reset();seed_word(0x21c,2);seed_byte(0x2a4,1);seed_word(0x1fc,1);seed_byte(0x228,1);seed_word(0x224,1);
    check_out(1,1,0,0,0,0,0,0);
    /* partial words are unknown words */
    reset();seed_word(0x21c,1);seed_word(0x214,1);config.known[0x215]=0;
    check_out(1,2,1,2,1,2,0,0);
    reset();seed_word(0x21c,2);seed_byte(0x2a4,1);seed_word(0x1fc,1);seed_byte(0x228,1);seed_word(0x224,5);
    config.known[0x225]=0;check_out(0,0,0,0,0,0,0,0);
    reset();seed_word(0x21c,2);seed_byte(0x2a4,1);seed_word(0x208,1);seed_word(0x204,2);config.known[0x206]=0;
    check_out(0,0,0,0,0,0,0,0);
    reset();seed_word(0x21c,2);seed_byte(0x2a4,1);seed_word(0x20c,1);seed_word(0x210,1);config.known[0x20d]=0;
    check_out(0,0,0,0,0,0,0,0);
    printf("{\"case\":\"derive4080\",\"branches\":[1,2,3],\"unknown_paths\":true,\"completion\":false}\n");
    return 0;
}
