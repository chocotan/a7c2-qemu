/* SPDX-License-Identifier: MIT */
/* Host ownership/lifecycle checks only; does not execute Sony instructions. */
#define memset raw_test_memset
#include "functional-capture-raw-writer.c"
#undef memset
#include <assert.h>
static int stale,fault_code,destroyed;
static int info_ready,native_result,native_calls,native_entries,native_returns;
static uint8_t test_info[CAPTURE_RAW_INFO_BYTES];
static uintptr_t test_base=0x40000000;
static unsigned char header_bytes[256];
static struct capture_output_span test_header;
int capture_output_memory_span(struct capture_output_memory *o,enum capture_output_role role,struct capture_output_span *span){
    if(o!=(void *)1 || role!=CAPTURE_OUT_HEADER)return -ESTALE;
    *span=test_header;return 0;
}
int functional_capture_raw_writer_current(struct capture_output_memory *o,uint64_t *j,uintptr_t *b,uint64_t *g){
    if(o!=(void *)1)return -ESTALE;
    *j=7;*b=test_base;*g=stale?9:8;return 0;
}
void functional_capture_raw_writer_fault(int rc){fault_code=rc;}
int capture_output_memory_raw_info(struct capture_output_memory *o,uint8_t out[CAPTURE_RAW_INFO_BYTES]){
    if(o!=(void *)1 || !info_ready)return -ENODATA;
    memcpy(out,test_info,sizeof test_info);return 0;
}
void functional_capture_raw_native_event(struct capture_output_memory *o,uint64_t j,uintptr_t b,uint64_t g,int returning,int result){
    assert(o==(void *)1 && j==7 && b==test_base && g==8 && !stale);
    if(returning){++native_returns;if(result)functional_capture_raw_writer_fault(-EREMOTEIO);}
    else ++native_entries;
}
static int native_record(const void *input,void *output){
    assert(input && output==(void *)2);++native_calls;
    writer.armed=0; /* Native destruction happens before the wrapper returns. */
    errno=EINTR;return native_result;
}
static void store(void *p,uintptr_t v){memcpy(p,&v,8);}
static void native_destroy(void *raw){
    unsigned char *app=(void *)(uintptr_t)read64((char *)raw+0x1488);
    const unsigned char original[24]={2,1,0,0,3};
    assert(read64(raw)==test_base+0x2fb6e0);
    assert(!lease.active && !memcmp(app+0x1a38,original,24));
    assert(!writer.raw && !writer.armed);
    free((void *)(uintptr_t)read64(app+0x1850));
    free(app);free(raw);++destroyed;
}
int main(void){
    assert(real_set); /* Safe constructor resolves the default libc fast path. */
    unsigned char *raw=calloc(1,0x14d8),*app=calloc(1,0x26e0);assert(raw && app);
    store(raw,test_base+0x2fb6e0);store(raw+0x1488,(uintptr_t)app);
    writer.output=(void *)1;writer.job=7;writer.generation=8;writer.base=test_base;
    writer.pid=getpid();writer.armed=1;writer.raw=raw;
    assert(owns(NULL,7,raw,app)==1);
    assert(functional_capture_raw_native_writer_ready((void *)1)==-ENODATA);
    assert(functional_capture_raw_native_writer_ready((void *)2)==-ESTALE);
    assert(!owns(NULL,8,raw,app));stale=1;assert(!owns(NULL,7,raw,app));stale=0;
    writer.failed=-EIO;assert(!owns(NULL,7,raw,app));writer.failed=0;
    store(raw+0x1488,0);assert(!owns(NULL,7,raw,app));
    unsigned char bytes[4]={0};assert(raw_test_memset(bytes,0x81,4)==bytes);
    for(unsigned i=0;i<4;++i)assert(bytes[i]==0x81);
    free(app);free(raw);
    unsigned char *base=calloc(1,0x300000);assert(base);test_base=(uintptr_t)base;
    const unsigned char pin[16]={0xe0,0x03,0x14,0xaa,0x02,0x41,0x81,0xd2,0x01,0x00,0x80,0x52,0x6f,0x15,0xf8,0x97};
    const unsigned char original[24]={2,1,0,0,3};
    memcpy(base+0x277c58,pin,16);memcpy(base+0x2deeb0,original,24);
    store(base+0x2fb6e0,(uintptr_t)native_destroy);store(base+0x2fb6e8,(uintptr_t)native_destroy);
    store(base+0x2fb6f8,test_base+0x268f5c);
    store(base+0x2fbd30,test_base+0x277b7c);store(base+0x2fbd38,test_base+0x278af0);
    for(unsigned slot=0;slot<2;++slot){
        raw=calloc(1,0x14d8);app=calloc(1,0x26e0);assert(raw && app);
        store(raw,test_base+0x2fb6e0);store(raw+0x1488,(uintptr_t)app);
        store(app,test_base+0x2fbcf0);memcpy(app+0x1a38,original,24);
        writer.base=test_base;writer.raw=raw;writer.armed=1;writer.prepared=writer.completed=0;
        assert(!install_shadow(raw));
        assert(read64(raw)==(uintptr_t)&writer.shadow[2]);
        assert(read64(base+0x2fb6e0)==(uintptr_t)native_destroy);
        struct raw_template_scope scope={.libmpr_base=test_base,.job=7,.raw_object=raw,
            .pid=getpid(),.owns=owns,.context=&writer};
        assert(!raw_template_after_memset(&lease,&scope,app+0x1be8,0,0xa08,test_base+0x277c68));
        writer.prepared=1;
        assert(!functional_capture_raw_native_writer_ready((void *)1));
        if(!slot){
            stale=1;raw_destroy_complete(raw);
            assert(fault_code==-ESTALE && lease.active && !destroyed);
            assert(read64(raw)==(uintptr_t)&writer.shadow[2]);
            stale=0;writer.failed=0;fault_code=0;
            app[0x1a40]=2;raw_destroy_complete(raw);
            assert(fault_code==-EPROTO && lease.active && !destroyed);
            assert(read64(raw)==(uintptr_t)&writer.shadow[2]);
            app[0x1a40]=1;writer.failed=0;fault_code=0;
        }else{
            unsigned char *ifd=calloc(1,0x1c8);assert(ifd);
            store(app+0x1850,(uintptr_t)ifd);
            store(ifd+56,(uintptr_t)header_bytes);ifd[72]=2;
            test_header.cpu=(uintptr_t)header_bytes;test_header.capacity=sizeof header_bytes;
            for(unsigned i=0;i<3;++i){
                unsigned char *e=app+0x19f0+24*i;
                e[0]=(unsigned char)(0xfe + i);e[8]=1;
            }
            const unsigned char inline14[12]={2,1,3,0,1,0,0,0,14,0,0,0};
            memcpy(header_bytes+38,inline14,sizeof inline14);
            store(app+0x1a48,(uintptr_t)(header_bytes+46));
            assert(!serialized_short14() && lease.serialized_short14==(uintptr_t)(header_bytes+46));
            header_bytes[38]^=1;
            assert(serialized_short14()==-EPROTO && !lease.serialized_short14);
            header_bytes[38]^=1;header_bytes[46]=13;
            assert(serialized_short14()==-EPROTO && !lease.serialized_short14);
            header_bytes[46]=14;
            test_header.capacity=49;
            assert(serialized_short14()==-ERANGE && !lease.serialized_short14);
            test_header.capacity=sizeof header_bytes;
            store(app+0x1a48,(uintptr_t)(header_bytes+48));
            assert(!serialized_short14());
            assert(raw_template_restore(&lease,&scope)==-EPROTO && lease.active);
            store(app+0x1a48,(uintptr_t)(header_bytes+46));
        }
        void (*destroy)(void *);uintptr_t address=writer.shadow[2+slot];memcpy(&destroy,&address,sizeof destroy);
        destroy(raw);
        assert(destroyed==(int)slot+1 && writer.completed && !lease.active);
        /* Objects have been freed: receipt must not inspect either allocation. */
        assert(!functional_capture_raw_native_writer_ready((void *)1));
        stale=1;assert(functional_capture_raw_native_writer_ready((void *)1)==-ESTALE);stale=0;
    }
    assert(!fault_code);free(base);
    test_base=(uintptr_t)native_record-0xeb260;writer.base=test_base;
    real_record=native_record;info_ready=1;
    raw_test_memset(test_info,0x5a,sizeof test_info);
    uint8_t input[0x20]={0};store(input+0x18,(uintptr_t)test_info);
    for(unsigned pass=0;pass<5;++pass){
        writer.armed=1;writer.failed=0;writer.pid=getpid();native_result=pass?3:0;fault_code=0;
        if(pass==2)stale=1;
        if(pass==3)writer.pid=getpid()+1;
        if(pass==4){static uint8_t wrong[CAPTURE_RAW_INFO_BYTES];store(input+0x18,(uintptr_t)wrong);}
        int entries=native_entries,returns=native_returns;
        errno=0;assert(raw_record(input,(void *)2)==native_result && errno==EINTR);
        assert(native_calls==(int)pass+1);
        assert(native_entries==entries+(pass<2) && native_returns==returns+(pass<2));
        assert(fault_code==(pass==1?-EREMOTEIO:0));stale=0;
    }
    return 0;
}
