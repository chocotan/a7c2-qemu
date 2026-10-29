/* SPDX-License-Identifier: MIT */
#include "adf-aip-input-config.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

/* Independent public-view/ROM goldens for the original 51bec4 stores, not model output. */
static const struct golden { unsigned int offset, value; } after03[] = {
    {0x000,0},{0x004,0x83},{0x008,3},{0x00c,3},{0x010,3},{0x014,0},{0x018,0},
    {0x060,0},{0x064,0},{0x068,0},{0x06c,0},{0x070,0},{0x074,0},{0x078,0},{0x094,1},
    {0x1c0,0},{0x1d4,0xff800000U},{0x1d8,0x002c0000},{0x1dc,0x4400},
    {0x1e0,0x80},{0x1e4,1},{0x1e8,0x40},{0x1ec,0x8c000},{0x1f0,0xe000},
    {0x1f4,0xff800000U},{0x1f8,0x80},{0x1fc,0xfe000000U},{0x200,0x40},
    {0x204,0xb40},{0x208,0x38},{0x20c,0xf6000000U},{0x210,0x20},
    {0x214,0x38},{0x218,0x38},{0x21c,0x04300000},{0x220,0},{0x224,0x80},
    {0x240,0},{0x248,0xe6},{0x250,0x2b},{0x258,0xe0},{0x25c,0x2b},{0x264,0xe0},
    {0x268,0x2b},{0x270,0x40},{0x274,0x80},{0x278,0x10},{0x27c,0x04110411},
    {0x280,0xffffff01U},{0x284,0x400},{0x288,0x400},{0x28c,0x40},{0x290,0x1200},
    {0x294,0xffffea00U},{0x298,0x15},{0x29c,0},{0x2a0,0},{0x2c0,0},
    {0x2c4,0x80},{0x2c8,0x80},{0x2cc,0x80},{0x2d0,0},{0x2d4,0},{0x2d8,0},
    {0x2dc,0x33},{0x2e0,0xca},{0x2e4,0x36},{0x2e8,0},{0x2ec,0x33},{0x2f0,0x36},
    {0x2f4,0x36},{0x2f8,0},{0x2fc,0x33},{0x300,0xbd},{0x304,0xd9},{0x308,0},
    {0x30c,0x33},{0x310,0x43},{0x314,0xd9},{0x318,0},{0x31c,0x33},{0x320,0},
    {0x324,0x4d},{0x328,0},{0x32c,0x7f},{0x330,0},{0x334,0},{0x338,0},
    {0x360,0},{0x364,0},{0x368,0},{0x36c,0},{0x370,0},{0x374,0},{0x378,0},{0x37c,0},
    {0x380,0},{0x384,0},{0x388,0},{0x38c,0},{0x390,0},{0x394,0},{0x398,0},{0x39c,0},
    {0x3a0,0},{0x3a4,0},{0x3a8,0},{0x3ac,0}
};
static const struct golden after02_changes[] = {
    {0x008,0},{0x00c,1},{0x064,1},{0x068,8},{0x06c,8},{0x070,1},{0x074,1},{0x078,1},
    {0x098,0x80},{0x09c,0},{0x1c0,3},{0x1c4,0x300},{0x1c8,0x300},
    {0x1d4,0xffc00000U},{0x1f4,0xffc00000U},{0x1fc,0xff380000U},{0x200,0x57},
    {0x208,0x90},{0x210,0},{0x21c,0x04a00000},{0x240,1},{0x248,0},
    {0x250,0x40},{0x258,0},{0x25c,0x40},{0x264,0},{0x268,0},{0x270,0},
    {0x274,0xd},{0x290,0xa7b},{0x294,0xfffff182U},
    {0x2dc,0x7f},{0x2e0,0},{0x2e4,0},{0x2ec,0},{0x2f0,0x7f},{0x2f4,0},
    {0x2fc,0},{0x300,0},{0x304,0},{0x30c,0},{0x310,0},{0x314,0},{0x31c,0},{0x324,0},{0x32c,0},
    {0x360,0x14},{0x364,0x14},{0x368,0x14},{0x36c,0x14},{0x370,0x14},{0x374,8},
    {0x378,9},{0x37c,0x14},{0x380,0x14},{0x384,0x14},{0x388,0x14},{0x38c,0x15},
    {0x390,0x16},{0x394,0x14},{0x398,0x14},{0x39c,0x15},
    {0x3a0,0x16},{0x3a4,0x14},{0x3a8,0x14},{0x3ac,0x14}
};
static const unsigned char canonical[44] = {
    2,0,0,0,44,0,0,0,0,1,8,8,0xf7,0x1f,1,0x20,0x14,0x14,0x14,0x14,
    0x14,8,9,0x14,0x14,0x14,0x14,0x15,0x16,0x14,0x14,0x15,
    0x16,0x14,0x14,0x14,0,0,0,0,0x21,0x11,0x21,0x43
};
static const unsigned int cached02[9] = {
    0x08080100,0x20011ff7,0x14141414,0x14090814,0x15141414,
    0x15141416,0x14141416,0,0x43211121
};
static unsigned long long hash_u32(unsigned long long hash,unsigned int value)
{
    for (unsigned int i=0;i<4;i++) { hash=(hash^(value&255))*0x100000001b3ULL;value>>=8; }
    return hash;
}
static void start(struct full_adf_aip_input_config *s,struct full_adf_public_config *config,
                   const struct full_adf_public_config *loaded,unsigned int reset[236],unsigned int pattern)
{
    memset(s,0,sizeof *s);memcpy(config,loaded,sizeof *config);
    for (unsigned int i=0;i<236;i++) reset[i]=pattern ? pattern+i : 0;
    assert(!full_adf_aip_input_config_init(s,config,1,reset));
    assert(s->known==1 && s->identity==s && s->public_config==config && s->asset_identity==config);
    assert(s->selector==2 && s->capability_word8==1 && !s->source && !s->active);
    assert(!s->software14 && !s->software18 && !s->flag3c && !s->stage && !s->fault);
    assert(!memcmp(s->registers,reset,sizeof s->registers) && config->queries==loaded->queries+1);
}
static void prepare(struct full_adf_aip_input_config *s,struct full_adf_public_config *config,
                     const struct full_adf_public_config *loaded,unsigned int reset[236],unsigned int through03)
{
    unsigned char raw[44];
    start(s,config,loaded,reset,0xa5000000U);
    assert(!full_adf_aip_input_config_make02(s,raw,sizeof raw) && !memcmp(raw,canonical,44));
    if (through03) assert(!full_adf_aip_input_config_consume03(s,0));
}
static void preserved_fault(const struct full_adf_aip_input_config *s,
                            const struct full_adf_aip_input_config *before)
{
    assert(s->fault==1 && s->stage==before->stage && s->builds==before->builds &&
           s->applies03==before->applies03 && s->applies02==before->applies02);
    assert(s->writes==before->writes && s->readbacks==before->readbacks);
    assert(!memcmp(s->registers,before->registers,sizeof s->registers));
    assert(!memcmp(s->cache,before->cache,sizeof s->cache));
    assert(!memcmp(s->trace,before->trace,sizeof s->trace));
}
static void success(const struct full_adf_public_config *loaded,unsigned int pattern)
{
    struct full_adf_public_config config;
    struct full_adf_aip_input_config s;
    unsigned int reset[236],expected[236];unsigned char raw[46];
    memset(raw,0xa5,sizeof raw);start(&s,&config,loaded,reset,pattern);
    assert(!full_adf_aip_input_config_make02(&s,raw+1,44));
    assert(raw[0]==0xa5 && raw[45]==0xa5 && !memcmp(raw+1,canonical,44));
    assert(s.builds==1 && s.stage==1 && !s.writes && !s.applies03 && !s.applies02);
    assert(!full_adf_aip_input_config_consume03(&s,0));
    memcpy(expected,reset,sizeof expected);
    for (unsigned int i=0;i<sizeof after03/sizeof *after03;i++) expected[after03[i].offset/4]=after03[i].value;
    expected[0x100/4]|=0xfffff;
    for (unsigned int i=0;i<236;i++) assert(s.registers[i]==expected[i]);
    assert(!s.cache[0] && !s.cache[8] && s.flag3c==1 && s.stage==2 && !s.busy && !s.fault);
    assert(s.applies03==1 && !s.applies02 && s.writes==109 && s.readbacks==109 && s.public_reads==79);
    assert(s.register_reads==117 && s.public_read_hash==0x317111d09296370cULL);
    assert(!full_adf_aip_input_config_consume02(&s,raw+1,44));
    for (unsigned int i=0;i<sizeof after02_changes/sizeof *after02_changes;i++)
        expected[after02_changes[i].offset/4]=after02_changes[i].value;
    for (unsigned int i=0;i<236;i++) {
        if (s.registers[i]!=expected[i]) fprintf(stderr,"register %x got %08x expected %08x\n",4*i,s.registers[i],expected[i]);
        assert(s.registers[i]==expected[i]);
    }
    assert(!memcmp(s.cache,cached02,sizeof cached02));
    assert(s.applies03==1 && s.applies02==1 && s.stage==3 && !s.busy && !s.fault && s.flag3c==1);
    assert(s.writes==222 && s.readbacks==222 && s.public_reads==131 && s.register_reads==236);
    assert(config.queries==loaded->queries+2+s.public_reads && s.public_read_hash==0x9fea4813aa05a5bdULL);
    for (unsigned int i=0;i<236;i++) assert(reset[i]==(pattern ? pattern+i : 0));
    struct full_adf_aip_input_config live;memcpy(&live,&s,sizeof live);
    unsigned long long queries=config.queries;
    assert(full_adf_aip_input_config_init(&s,&config,1,reset)==-1021);
    assert(!memcmp(&s,&live,sizeof s) && config.queries==queries);
    unsigned long long hash=0xcbf29ce484222325ULL;
    for (unsigned int i=0;i<s.writes;i++) {
        const struct full_adf_aip_input_config_write *w=&s.trace[i];
        assert(w->address>=0xf48a2000U && w->address<=0xf48a23acU && !(w->address&3));
        assert(w->value==w->readback);
        hash=hash_u32(hash,w->address);hash=hash_u32(hash,w->value);
    }
    assert(hash==s.write_hash);
    if (!pattern) printf("AIP_INPUT_PUBLIC_HASH=%016llx\nAIP_INPUT_REGISTER_HASH=%016llx\nAIP_INPUT_WRITE_HASH=%016llx\n",
        s.public_read_hash,s.register_read_hash,s.write_hash);
    struct full_adf_aip_input_config before;memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_consume02(&s,raw+1,44)==-1021);preserved_fault(&s,&before);
}
static void rejection_tests(const struct full_adf_public_config *loaded)
{
    struct full_adf_public_config config,empty={0};
    struct full_adf_aip_input_config s,before;
    unsigned int reset[236]={0};unsigned char out[64];
    memset(&s,0,sizeof s);memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_init(&s,&empty,1,reset)==-1021 && !memcmp(&s,&before,sizeof s));
    for (unsigned int cap=0;cap<9;cap++) if (cap!=1) {
        config=*loaded;memset(&s,0,sizeof s);
        assert(full_adf_aip_input_config_init(&s,&config,cap,reset)==-1021 && !memcmp(&s,&before,sizeof s));
        assert(!memcmp(&config,loaded,sizeof config));
    }
    assert(full_adf_aip_input_config_init(0,&config,1,reset)==-1021);
    assert(full_adf_aip_input_config_init(&s,0,1,reset)==-1021);
    assert(full_adf_aip_input_config_init(&s,&config,1,0)==-1021);
    for (unsigned long i=0;i<sizeof s;i++) {
        memset(&s,0,sizeof s);((unsigned char *)&s)[i]=1;memcpy(&before,&s,sizeof before);
        assert(full_adf_aip_input_config_init(&s,&config,1,reset)==-1021 && !memcmp(&s,&before,sizeof s));
    }
    for (unsigned int length=0;length<64;length++) if (length!=44) {
        start(&s,&config,loaded,reset,0);memcpy(&before,&s,sizeof before);memset(out,0xa5,sizeof out);
        assert(full_adf_aip_input_config_make02(&s,out,length)==-1021);preserved_fault(&s,&before);
        for (unsigned int i=0;i<sizeof out;i++) assert(out[i]==0xa5);
    }
    start(&s,&config,loaded,reset,0);memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_make02(&s,0,44)==-1021);preserved_fault(&s,&before);
    start(&s,&config,loaded,reset,0);memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_make02(&s,s.registers,44)==-1021);preserved_fault(&s,&before);
    start(&s,&config,loaded,reset,0);memcpy(&before,&s,sizeof before);
    struct full_adf_public_config public_before=config;
    assert(full_adf_aip_input_config_make02(&s,&config,44)==-1021);preserved_fault(&s,&before);
    assert(!memcmp(&config,&public_before,sizeof config));
    prepare(&s,&config,loaded,reset,0);memcpy(&before,&s,sizeof before);memset(out,0xa5,sizeof out);
    assert(full_adf_aip_input_config_make02(&s,out,44)==-1021);preserved_fault(&s,&before);
    for (unsigned int i=0;i<sizeof out;i++) assert(out[i]==0xa5);
    start(&s,&config,loaded,reset,0);memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_consume03(&s,0)==-1021);preserved_fault(&s,&before);
    prepare(&s,&config,loaded,reset,0);memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_consume02(&s,canonical,44)==-1021);preserved_fault(&s,&before);
    prepare(&s,&config,loaded,reset,0);memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_consume03(&s,1)==-1021);preserved_fault(&s,&before);
    prepare(&s,&config,loaded,reset,1);memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_consume03(&s,0)==-1021);preserved_fault(&s,&before);
    for (unsigned int length=0;length<64;length++) if (length!=44) {
        prepare(&s,&config,loaded,reset,1);memcpy(&before,&s,sizeof before);
        assert(full_adf_aip_input_config_consume02(&s,canonical,length)==-1021);preserved_fault(&s,&before);
    }
    prepare(&s,&config,loaded,reset,1);memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_consume02(&s,0,44)==-1021);preserved_fault(&s,&before);
    for (unsigned int i=0;i<44;i++) {
        prepare(&s,&config,loaded,reset,1);memcpy(out,canonical,44);out[i]^=1;
        memcpy(&before,&s,sizeof before);
        assert(full_adf_aip_input_config_consume02(&s,out,44)==-1021);preserved_fault(&s,&before);
    }
    puts("ADF_AIP_INPUT_CONFIG_SEQUENCE_PACKET_FAULT_PRESERVATION_PASS");
}
static void tamper_tests(const struct full_adf_public_config *loaded)
{
    struct full_adf_public_config config;
    struct full_adf_aip_input_config s,before;
    unsigned int reset[236];unsigned char out[44];
    for (unsigned int stage=0;stage<3;stage++) {
        for (unsigned int i=0;i<393;i++) {
            start(&s,&config,loaded,reset,0xa5000000U);
            if (stage) assert(!full_adf_aip_input_config_make02(&s,out,44));
            if (stage==2) assert(!full_adf_aip_input_config_consume03(&s,0));
            config.aip_values[i]^=1;memcpy(&before,&s,sizeof before);memset(out,0xa5,sizeof out);
            int rc=stage==0 ? full_adf_aip_input_config_make02(&s,out,44) :
                (stage==1 ? full_adf_aip_input_config_consume03(&s,0) : full_adf_aip_input_config_consume02(&s,canonical,44));
            assert(rc==-1021);preserved_fault(&s,&before);
            if (!stage) for (unsigned int j=0;j<44;j++) assert(out[j]==0xa5);
            assert(full_adf_aip_input_config_make02(&s,out,44)==-1021);
        }
    }
    start(&s,&config,loaded,reset,0);config.aip_known[1]=0xff;memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_make02(&s,out,44)==-1021);preserved_fault(&s,&before);
    prepare(&s,&config,loaded,reset,0);config.queries=~0ULL;memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_consume03(&s,0)==-1021);preserved_fault(&s,&before);
    for (unsigned int i=0;i<236;i++) {
        prepare(&s,&config,loaded,reset,0);s.registers[i]^=1;memcpy(&before,&s,sizeof before);
        assert(full_adf_aip_input_config_consume03(&s,0)==-1021);preserved_fault(&s,&before);
    }
    for (unsigned int i=0;i<9;i++) {
        prepare(&s,&config,loaded,reset,0);s.cache[i]=1;memcpy(&before,&s,sizeof before);
        assert(full_adf_aip_input_config_consume03(&s,0)==-1021);preserved_fault(&s,&before);
    }
    prepare(&s,&config,loaded,reset,0);memcpy(&before,&s,sizeof before);
    struct full_adf_aip_input_config copy;memcpy(&copy,&s,sizeof copy);
    assert(full_adf_aip_input_config_consume03(&copy,0)==-1021);
    assert(!memcmp(&s,&before,sizeof s));
    prepare(&s,&config,loaded,reset,0);
    struct full_adf_public_config other=config;s.public_config=&other;memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_consume03(&s,0)==-1021);preserved_fault(&s,&before);
    prepare(&s,&config,loaded,reset,0);s.active=1;memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_consume03(&s,0)==-1021);preserved_fault(&s,&before);
    prepare(&s,&config,loaded,reset,0);s.source=1;memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_consume03(&s,0)==-1021);preserved_fault(&s,&before);
    prepare(&s,&config,loaded,reset,0);s.software14=1;memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_consume03(&s,0)==-1021);preserved_fault(&s,&before);
    prepare(&s,&config,loaded,reset,0);s.software18=1;memcpy(&before,&s,sizeof before);
    assert(full_adf_aip_input_config_consume03(&s,0)==-1021);preserved_fault(&s,&before);
    puts("ADF_AIP_INPUT_CONFIG_PUBLIC_OWNER_REGISTER_TAMPER_REJECTED_PASS");
}
static void partial_failure_tests(const struct full_adf_public_config *loaded)
{
    struct full_adf_public_config config;
    struct full_adf_aip_input_config s,before;
    unsigned int reset[236];unsigned char out[44];
    for (unsigned int second=0;second<2;second++) {
        prepare(&s,&config,loaded,reset,second);memcpy(&before,&s,sizeof before);
        config.queries=~0ULL-20;
        int rc=second ? full_adf_aip_input_config_consume02(&s,canonical,44) :
            full_adf_aip_input_config_consume03(&s,0);
        assert(rc==-1021 && s.fault==1 && s.busy==1 && s.stage==before.stage);
        assert(s.applies03==before.applies03 && s.applies02==before.applies02 && config.queries==~0ULL);
        assert(s.public_reads==before.public_reads+20 && s.writes>before.writes && s.readbacks==s.writes);
        assert(!memcmp(s.trace,before.trace,before.writes*sizeof *s.trace));
        memcpy(&before,&s,sizeof before);memset(out,0xa5,sizeof out);
        assert(full_adf_aip_input_config_make02(&s,out,44)==-1021);preserved_fault(&s,&before);
        assert(s.busy==1);
        for (unsigned int i=0;i<44;i++) assert(out[i]==0xa5);
        memcpy(&before,&s,sizeof before);
        assert(full_adf_aip_input_config_init(&s,&config,1,reset)==-1021 && !memcmp(&s,&before,sizeof s));
    }
    puts("ADF_AIP_INPUT_CONFIG_PARTIAL_WRITE_FAILURE_LATCHED_NOT_COMPLETED_PASS");
}
int main(int argc,char **argv)
{
    assert(argc==2);
    int fd=open(argv[1],O_RDONLY);assert(fd>=0);
    struct full_adf_public_config loaded={0};
    assert(!full_adf_public_config_load(&loaded,fd));assert(!close(fd));
    success(&loaded,0);success(&loaded,0xa5000000U);success(&loaded,0x5af00000U);
    puts("ADF_AIP_INPUT_CONFIG_ORIGINAL_SEED_BOTH_APPLIES_GOLDEN_ALL_REGISTERS_PASS");
    rejection_tests(&loaded);tamper_tests(&loaded);partial_failure_tests(&loaded);
    assert(full_adf_aip_input_config_make02(0,0,0)==-1021);
    assert(full_adf_aip_input_config_consume03(0,0)==-1021);
    assert(full_adf_aip_input_config_consume02(0,canonical,44)==-1021);
    return 0;
}
