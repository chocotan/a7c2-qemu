/* SPDX-License-Identifier: MIT */
#include "cp-parameter-state.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static void fixture(unsigned char p[CP_PARAMETER_BATCH_BYTES]) {
    for (size_t i = 0; i < CP_PARAMETER_BATCH_BYTES; i++) p[i] = (unsigned char)(i * 37u + 19u);
    p[0] = 5; p[2] = 0x63; p[3] = 0x40;
    for (size_t i = 0; i < CP_PARAMETER_BATCH_SLOTS; i++) {
        const struct cp_parameter_batch_slot *s = &cp_parameter_batch_slots[i];
        p[s->offset] = 5;
        p[s->offset + 2u] = (unsigned char)s->opcode;
        p[s->offset + 3u] = (unsigned char)(s->opcode >> 8);
    }
}

static int consume(struct cp_parameter_state *s, const void *p) {
    return cp_parameter_state_consume(s, CP_PARAMETER_BATCH_SOURCE,
                                      CP_PARAMETER_BATCH_TARGET, p, CP_PARAMETER_BATCH_BYTES);
}

static bool bit(const uint64_t *mask, size_t slot) {
    return (mask[slot / 64u] & (UINT64_C(1) << (slot % 64u))) != 0;
}

static unsigned count(const uint64_t *mask) {
    unsigned n = 0;
    for (size_t i = 0; i < CP_PARAMETER_BATCH_SLOTS; i++) n += bit(mask, i);
    return n;
}

static void unchanged(const struct cp_parameter_state *s, const struct cp_parameter_state *old) {
    assert(memcmp(s, old, sizeof(*s)) == 0);
}

static void boundaries(void) {
    struct cp_parameter_state s, old;
    unsigned char p[CP_PARAMETER_BATCH_BYTES], unaligned[CP_PARAMETER_BATCH_BYTES + 1u], output[32];
    fixture(p);
    assert(cp_parameter_state_init(&s, true) == 0);
    old = s;
    memset(output, 0x9b, sizeof(output));
    assert(cp_parameter_state_read(&s, 0, output, sizeof(output)) == -ENODATA);
    for (size_t i = 0; i < sizeof(output); i++) assert(output[i] == 0x9b);
    assert(consume(NULL, p) == -EINVAL);
    assert(consume(&s, NULL) == -EINVAL);
    assert(consume(&s, &s) == -EINVAL);
    assert(consume(&s, s.batch.bytes) == -EINVAL);
    assert(consume(&s, s.bytes) == -EINVAL);
    assert(consume(&s, s.known_mask) == -EINVAL);
    assert(consume(&s, (const void *)(UINTPTR_MAX - 1u)) == -EINVAL);
    for (size_t n = 0; n <= CP_PARAMETER_BATCH_BYTES + 1u; n++) {
        if (n == CP_PARAMETER_BATCH_BYTES) continue;
        assert(cp_parameter_state_consume(&s, CP_PARAMETER_BATCH_SOURCE,
            CP_PARAMETER_BATCH_TARGET, p, n) == -EMSGSIZE);
        unchanged(&s, &old);
    }
    assert(cp_parameter_state_consume(&s, 0, CP_PARAMETER_BATCH_TARGET, p, sizeof(p)) == -EPERM);
    assert(cp_parameter_state_consume(&s, CP_PARAMETER_BATCH_SOURCE, 0, p, sizeof(p)) == -EPERM);
    unchanged(&s, &old);
    for (size_t i = 0; i < CP_PARAMETER_BATCH_SLOTS; i++) {
        const struct cp_parameter_batch_slot *slot = &cp_parameter_batch_slots[i];
        p[slot->offset] ^= 1u;
        assert(consume(&s, p) == -EPROTO); unchanged(&s, &old);
        p[slot->offset] ^= 1u;
        p[slot->offset + 2u] ^= 1u;
        assert(consume(&s, p) == -EPROTO); unchanged(&s, &old);
        p[slot->offset + 2u] ^= 1u;
        p[slot->offset + 3u] ^= 1u;
        assert(consume(&s, p) == -EPROTO); unchanged(&s, &old);
        p[slot->offset + 3u] ^= 1u;
    }
    for (size_t i = 0; i < 4; i++) {
        if (i == 1) continue;
        p[i] ^= 1u;
        assert(consume(&s, p) == -EPROTO); unchanged(&s, &old);
        p[i] ^= 1u;
    }
    assert(cp_parameter_state_read(&s, 0, NULL, 1) == -EINVAL);
    assert(cp_parameter_state_read(&s, 0, output, 0) == -EINVAL);
    assert(cp_parameter_state_read(&s, CP_PARAMETER_STATE_IMAGE_BYTES, output, 1) == -EINVAL);
    assert(cp_parameter_state_read(&s, 0, output, SIZE_MAX) == -EINVAL);
    assert(cp_parameter_state_read(&s, 0, s.bytes, 1) == -EINVAL);
    assert(cp_parameter_state_read(&s, 0, (void *)(UINTPTR_MAX - 1u), 8) == -EINVAL);
    unchanged(&s, &old);
    memcpy(unaligned + 1, p, sizeof(p));
    assert(consume(&s, unaligned + 1) == CP_PARAMETER_STATE_PARTIAL);
    assert(memcmp(s.batch.bytes, p, sizeof(p)) == 0);
    assert(count(s.config_consumed) == 170);
    assert(count(s.semantic_complete) == 168);
    assert(!s.batch.semantic_applied);
    assert(memcmp(s.batch.semantic_consumed, s.semantic_complete, sizeof(s.semantic_complete)) == 0);
    assert(bit(s.config_consumed, 3) && !bit(s.semantic_complete, 3));
    assert(!bit(s.config_consumed, 15) && !bit(s.semantic_complete, 15));
    assert(cp_parameter_state_read(&s, CP_PARAMETER_STATE_OVERRIDE_MODE_OFFSET, output, 1) == -ENODATA);
    assert(cp_parameter_state_read(&s, 0x1f4, output, 1) == -ENODATA);
    old = s;
    assert(consume(&s, p) == -EBUSY); unchanged(&s, &old);
    {
        pid_t pid = fork(); int status;
        assert(pid >= 0);
        if (pid == 0) {
            assert(cp_parameter_state_read(&s, 0x690, output, 4) == -ECHILD);
            assert(consume(&s, p) == -ECHILD);
            _exit(0);
        }
        assert(waitpid(pid, &status, 0) == pid && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    }
    assert(cp_parameter_state_init(&s, false) == 0);
    old = s;
    assert(consume(&s, p) == -EACCES); unchanged(&s, &old);
    assert(cp_parameter_state_read(&s, 0x690, output, 4) == -EACCES);
    memset(&s, 0, sizeof(s)); old = s;
    assert(consume(&s, p) == -EINVAL); unchanged(&s, &old);
}

static void decode_domains(void) {
    struct cp_parameter_state s;
    unsigned char p[CP_PARAMETER_BATCH_BYTES], out[4];
    for (unsigned v = 0; v < 256; v++) {
        fixture(p);
        p[cp_parameter_batch_slots[24].offset + 8u] = (unsigned char)v;
        p[cp_parameter_batch_slots[67].offset + 8u] = (unsigned char)v;
        p[cp_parameter_batch_slots[155].offset + 8u] = (unsigned char)v;
        p[cp_parameter_batch_slots[167].offset + 8u] = (unsigned char)v;
        p[cp_parameter_batch_slots[167].offset + 9u] = (unsigned char)v;
        p[cp_parameter_batch_slots[167].offset + 10u] = 0;
        p[cp_parameter_batch_slots[167].offset + 11u] = (unsigned char)v;
        p[cp_parameter_batch_slots[167].offset + 12u] = (unsigned char)v;
        assert(cp_parameter_state_init(&s, true) == 0);
        assert(consume(&s, p) == CP_PARAMETER_STATE_PARTIAL);
        assert(cp_parameter_state_read(&s, 0x574, out, 1) == 0 && out[0] == (v != 0));
        assert(cp_parameter_state_read(&s, 0xbb8, out, 1) == 0 && out[0] == (v == 1));
        assert(cp_parameter_state_read(&s, 0x64, out, 4) == 0);
        for (size_t i = 0; i < 4; i++) assert(out[i] == (v != 0));
        assert(cp_parameter_state_read(&s, 0x2f8, out, 4) == 0 && out[0] == v && !out[1] && !out[2] && !out[3]);
        memset(out, 0xa9, sizeof(out));
        if (v == 0) {
            assert(cp_parameter_state_read(&s, 0x2f4, out, 4) == 0);
            assert(!out[0] && !out[1] && !out[2] && !out[3]);
        } else {
            assert(cp_parameter_state_read(&s, 0x2f4, out, 4) == -ENODATA);
            for (size_t i = 0; i < 4; i++) assert(out[i] == 0xa9);
        }
    }
}

static void reset_store(void) {
    struct cp_parameter_state s, old;
    unsigned char output[8], packet[CP_PARAMETER_BATCH_BYTES];
    assert(cp_parameter_state_init(&s, true) == 0);
    memset(s.bytes, 0xa5, sizeof(s.bytes));
    assert(cp_parameter_state_read(&s, 0x1c8, output, sizeof(output)) == -ENODATA);
    old = s;
    assert(cp_parameter_state_consume_reset_store(&s) == 0);
    for (size_t i = 0; i < sizeof(s.bytes); ++i) {
        bool reset = i >= 0x1c8 && i < 0x1d0;
        assert(s.bytes[i] == (reset ? 0 : 0xa5));
        assert(((s.known_mask[i/8] >> (i%8)) & 1u) == reset);
    }
    assert(!memcmp(&s.batch,&old.batch,sizeof(s.batch)));
    assert(!memcmp(s.config_consumed,old.config_consumed,sizeof(s.config_consumed)));
    assert(!memcmp(s.semantic_complete,old.semantic_complete,sizeof(s.semantic_complete)));
    assert(!s.batch.staged && !s.batch.semantic_applied);
    assert(cp_parameter_state_read(&s,0x1c8,output,sizeof(output)) == 0);
    for (size_t i = 0; i < sizeof(output); ++i) assert(!output[i]);
    assert(cp_parameter_state_read(&s,0x1c7,output,1) == -ENODATA);
    assert(cp_parameter_state_read(&s,0x1d0,output,1) == -ENODATA);
    old = s;
    assert(cp_parameter_state_consume_reset_store(&s) == -EBUSY); unchanged(&s,&old);
    fixture(packet);
    assert(consume(&s,packet) == CP_PARAMETER_STATE_PARTIAL);
    assert(cp_parameter_state_read(&s,0x1c8,output,sizeof(output)) == 0);
    for (size_t i = 0; i < sizeof(output); ++i) assert(!output[i]);
    old = s;
    assert(cp_parameter_state_consume_reset_store(&s) == -EBUSY); unchanged(&s,&old);
    assert(cp_parameter_state_init(&s,true) == 0);
    {
        pid_t pid = fork(); int status;
        assert(pid >= 0);
        if (!pid) { assert(cp_parameter_state_consume_reset_store(&s) == -ECHILD); _exit(0); }
        assert(waitpid(pid,&status,0) == pid && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    }
    assert(cp_parameter_state_init(&s,false) == 0); old=s;
    assert(cp_parameter_state_consume_reset_store(&s) == -EACCES); unchanged(&s,&old);
    memset(&s,0,sizeof(s)); old=s;
    assert(cp_parameter_state_consume_reset_store(&s) == -EINVAL); unchanged(&s,&old);
    assert(cp_parameter_state_consume_reset_store(NULL) == -EINVAL);
}

static void common_stores(void) {
    struct cp_parameter_state s, old;
    unsigned char packet[CP_PARAMETER_BATCH_BYTES], out[8];
    unsigned known=0;
    assert(cp_parameter_state_init(&s,true)==0);
    memset(s.bytes,0xa5,sizeof(s.bytes)); old=s;
    assert(cp_parameter_state_consume_common_stores(&s)==0);
    for(size_t i=0;i<sizeof(s.bytes);++i) {
        if(s.known_mask[i/8]&(1u<<(i%8))) known++;
        else assert(s.bytes[i]==0xa5);
    }
    assert(known==CP_PARAMETER_STATE_COMMON_LOCAL_BYTES && known==694);
    assert(!memcmp(&s.batch,&old.batch,sizeof(s.batch)));
    assert(!memcmp(s.config_consumed,old.config_consumed,sizeof(s.config_consumed)));
    assert(!memcmp(s.semantic_complete,old.semantic_complete,sizeof(s.semantic_complete)));
    assert(cp_parameter_state_read(&s,0x1c8,out,8)==0);
    for(unsigned i=0;i<8;++i)assert(!out[i]);
    assert(cp_parameter_state_read(&s,0x214,out,4)==0 && out[0]==2 && !out[1] && !out[2] && !out[3]);
    assert(cp_parameter_state_read(&s,0x668,out,4)==0 && out[0]==5 && !out[1] && !out[2] && !out[3]);
    assert(cp_parameter_state_read(&s,0xd5c,out,4)==0 && out[0]==1 && !out[1] && !out[2] && !out[3]);
    assert(cp_parameter_state_read(&s,0,out,4)==-ENODATA);
    old=s;
    assert(cp_parameter_state_consume_common_stores(&s)==-EBUSY);unchanged(&s,&old);
    assert(cp_parameter_state_consume_reset_store(&s)==-EBUSY);unchanged(&s,&old);
    fixture(packet);assert(consume(&s,packet)==CP_PARAMETER_STATE_PARTIAL);
    assert(cp_parameter_state_read(&s,0x1c8,out,8)==0);
    old=s;assert(cp_parameter_state_consume_common_stores(&s)==-EBUSY);unchanged(&s,&old);
    assert(cp_parameter_state_init(&s,true)==0);assert(cp_parameter_state_consume_reset_store(&s)==0);
    old=s;assert(cp_parameter_state_consume_common_stores(&s)==-EBUSY);unchanged(&s,&old);
    assert(cp_parameter_state_init(&s,true)==0);
    { pid_t pid=fork();int status;assert(pid>=0);
      if(!pid){assert(cp_parameter_state_consume_common_stores(&s)==-ECHILD);_exit(0);}
      assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status)); }
    assert(cp_parameter_state_init(&s,false)==0);old=s;
    assert(cp_parameter_state_consume_common_stores(&s)==-EACCES);unchanged(&s,&old);
    memset(&s,0,sizeof(s));old=s;
    assert(cp_parameter_state_consume_common_stores(&s)==-EINVAL);unchanged(&s,&old);
    assert(cp_parameter_state_consume_common_stores(NULL)==-EINVAL);
}

static void common_file(const char *destination) {
    struct cp_parameter_state s;
    assert(cp_parameter_state_init(&s,true)==0);
    memset(s.bytes,0xa5,sizeof(s.bytes));
    assert(cp_parameter_state_consume_common_stores(&s)==0);
    FILE *f=fopen(destination,"wb");assert(f);
    assert(fwrite(s.bytes,1,sizeof(s.bytes),f)==sizeof(s.bytes));
    assert(fwrite(s.known_mask,1,sizeof(s.known_mask),f)==sizeof(s.known_mask));
    assert(fclose(f)==0);
}

static struct cp_parameter_import defaults_decision(void) {
    struct cp_parameter_import d={0};
    d.source_sequence=2;d.stage_fnv1a64=CP_PROPERTY_STAGE_FNV1A64;
    d.origin=CP_START_STATE_ORIGIN_HOST_TEST;d.properties_consumed=d.defaults_selected=1;
    return d;
}
static void default_stores(void) {
    struct cp_parameter_state s,old;
    struct cp_parameter_import decision=defaults_decision(),bad;
    unsigned char out[8],packet[CP_PARAMETER_BATCH_BYTES];
    assert(cp_parameter_state_init(&s,true)==0);old=s;
    assert(cp_parameter_state_consume_default_stores(&s,&decision)==-EBUSY);unchanged(&s,&old);
    assert(cp_parameter_state_consume_common_stores(&s)==0);old=s;
    for(unsigned i=0;i<10;++i) {
        bad=decision;
        switch(i) {case 0:bad.properties_consumed=0;break;case 1:bad.defaults_selected=0;break;
        case 2:bad.import_selected=1;break;case 3:bad.stage_fnv1a64^=1;break;
        case 4:bad.source_sequence=3;break;case 5:bad.origin=CP_START_STATE_ORIGIN_NONE;break;
        case 6:bad.header=0xd68;bad.flags=4;break;case 7:bad.properties_consumed=2;break;
        case 8:bad.flags=4;break;default:bad.header=1;break;}
        assert(cp_parameter_state_consume_default_stores(&s,&bad)==-ENODATA);unchanged(&s,&old);
    }
    assert(cp_parameter_state_consume_default_stores(&s,(const void *)&s)==-EINVAL);unchanged(&s,&old);
    assert(cp_parameter_state_consume_default_stores(&s,NULL)==-EINVAL);unchanged(&s,&old);
    assert(cp_parameter_state_consume_default_stores(&s,&decision)==0);
    unsigned known=0;for(size_t i=0;i<CP_PARAMETER_STATE_IMAGE_BYTES;++i)known+=(s.known_mask[i/8]>>(i%8))&1u;
    assert(known==2913 && known==CP_PARAMETER_STATE_INITIAL_LOCAL_KNOWN_BYTES);
    assert(cp_parameter_state_read(&s,0,out,4)==-ENODATA);
    assert(cp_parameter_state_read(&s,0x28,out,4)==0 && out[0]==5 && !out[1] && !out[2] && !out[3]);
    assert(cp_parameter_state_read(&s,0x2c,out,4)==0 && out[0]==1);
    assert(cp_parameter_state_read(&s,0x30,out,4)==0 && out[0]==60);
    assert(cp_parameter_state_read(&s,0xd5c,out,4)==0 && !out[0] && !out[1] && !out[2] && !out[3]);
    assert(cp_parameter_state_read(&s,0x1c8,out,8)==0);for(unsigned i=0;i<8;++i)assert(!out[i]);
    assert(!s.batch.staged && !s.batch.semantic_applied && !count(s.config_consumed) && !count(s.semantic_complete));
    old=s;assert(cp_parameter_state_consume_default_stores(&s,&decision)==-EBUSY);unchanged(&s,&old);
    fixture(packet);assert(consume(&s,packet)==CP_PARAMETER_STATE_PARTIAL);
    old=s;assert(cp_parameter_state_consume_default_stores(&s,&decision)==-EBUSY);unchanged(&s,&old);
    assert(cp_parameter_state_init(&s,true)==0);assert(cp_parameter_state_consume_common_stores(&s)==0);
    {pid_t pid=fork();int status;assert(pid>=0);
     if(!pid){assert(cp_parameter_state_consume_default_stores(&s,&decision)==-ECHILD);_exit(0);}
     assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status));}
    assert(cp_parameter_state_init(&s,false)==0);old=s;
    assert(cp_parameter_state_consume_default_stores(&s,&decision)==-EACCES);unchanged(&s,&old);
}
static void defaults_file(const char *destination) {
    struct cp_parameter_state s;
    struct cp_parameter_import d=defaults_decision();
    assert(cp_parameter_state_init(&s,true)==0);memset(s.bytes,0xa5,sizeof(s.bytes));
    assert(cp_parameter_state_consume_common_stores(&s)==0);
    assert(cp_parameter_state_consume_default_stores(&s,&d)==0);
    FILE *f=fopen(destination,"wb");assert(f);
    assert(fwrite(s.bytes,1,sizeof(s.bytes),f)==sizeof(s.bytes));
    assert(fwrite(s.known_mask,1,sizeof(s.known_mask),f)==sizeof(s.known_mask));assert(!fclose(f));
}
static void packet_file(const char *path, const char *destination, int with_common) {
    struct cp_parameter_state s;
    unsigned char input[CP_PARAMETER_BATCH_BYTES], output;
    FILE *f = fopen(path, "rb");
    assert(f && fread(input, 1, sizeof(input), f) == sizeof(input));
    assert(fgetc(f) == EOF && fclose(f) == 0);
    assert(cp_parameter_state_init(&s, true) == 0);
    if(with_common)assert(cp_parameter_state_consume_common_stores(&s)==0);
    if(with_common==2){struct cp_parameter_import d=defaults_decision();assert(!cp_parameter_state_consume_default_stores(&s,&d));}
    assert(consume(&s, input) == CP_PARAMETER_STATE_PARTIAL);
    assert(memcmp(input, s.batch.bytes, sizeof(input)) == 0);
    if(with_common)assert(cp_parameter_state_read(&s,0x1c8,&output,1)==0 && output==0);
    else assert(cp_parameter_state_read(&s, 0x1c8, &output, 1) == -ENODATA);
    f = fopen(destination, "wb"); assert(f);
    assert(fwrite(s.bytes, 1, sizeof(s.bytes), f) == sizeof(s.bytes));
    assert(fwrite(s.known_mask, 1, sizeof(s.known_mask), f) == sizeof(s.known_mask));
    for (size_t i = 0; i < CP_PARAMETER_BATCH_SLOTS; i++) {
        assert(fputc(bit(s.config_consumed, i) ? 1 : 0, f) != EOF);
        assert(fputc(bit(s.semantic_complete, i) ? 1 : 0, f) != EOF);
    }
    assert(fclose(f) == 0);
}

static void zoom_ready(struct cp_parameter_state *s) {
    unsigned char packet[CP_PARAMETER_BATCH_BYTES];
    struct cp_parameter_import d=defaults_decision();
    assert(!cp_parameter_state_init(s,true));
    memset(s->bytes,0xa5,sizeof(s->bytes));
    assert(!cp_parameter_state_consume_common_stores(s));
    assert(!cp_parameter_state_consume_default_stores(s,&d));
    fixture(packet);assert(consume(s,packet)==CP_PARAMETER_STATE_PARTIAL);
}
static int zoom_write(struct cp_parameter_state *s, const struct cp_start_state_guard *g,
    const void *p, struct cp_parameter_zoom_readback *out) {
    return cp_parameter_state_consume_zoom(s,g,CP_PARAMETER_BATCH_SOURCE,CP_PARAMETER_BATCH_TARGET,p,12,out);
}
static void zoom_domains(void) {
    struct cp_parameter_state s,old;
    struct cp_start_state_guard g={(uint32_t)getpid(),2,2,CP_START_STATE_ORIGIN_HOST_TEST,1};
    struct cp_parameter_zoom_readback out,again;
    unsigned char p[12]={5,0x9b,1,0x40,0x4c,0,0,0x80,0,2,0,2};
    zoom_ready(&s);
    memset(s.bytes+0x69c,0xa5,8);
    assert(CP_PARAMETER_BATCH_SLOTS==190);
    for(size_t i=0;i<CP_PARAMETER_BATCH_SLOTS;i++)assert(cp_parameter_batch_slots[i].opcode!=0x4001);
    assert(cp_parameter_state_read_zoom(&s,&g,&out)==-ENODATA);
    for(unsigned v=0;v<256;v++) {
        p[8]=(unsigned char)v;p[9]=(unsigned char)(255u-v);
        p[10]=(unsigned char)(v^0x80u);p[11]=(unsigned char)(v*37u);
        g.sequence_before=g.sequence_after=2u+2u*v;
        old=s;
        assert(!zoom_write(&s,&g,p,&out));
        const unsigned char expected[10]={p[8],0,0,0,p[9],p[10],0,0,0,p[11]};
        assert(!memcmp(out.fields,expected,10) && !memcmp(out.wire,p,12));
        assert(out.caller==UINT32_C(0x8000004c) && out.metadata_source==CP_PARAMETER_BATCH_SOURCE);
        assert(out.count==v+1u && out.config_consumed==1 && out.known_mask==0x3ff);
        assert(!memcmp(&s.batch,&old.batch,sizeof(s.batch)));
        assert(!memcmp(s.config_consumed,old.config_consumed,sizeof(s.config_consumed)));
        assert(!memcmp(s.semantic_complete,old.semantic_complete,sizeof(s.semantic_complete)));
        for(size_t i=0;i<sizeof(s.bytes);i++) {
            int changed=i==0x698 || (i>=0x69c && i<0x6a5);
            if(!changed)assert(s.bytes[i]==old.bytes[i]);
            unsigned known=(s.known_mask[i/8]>>(i%8))&1u;
            assert(known==(changed?1u:(old.known_mask[i/8]>>(i%8))&1u));
        }
        assert(!cp_parameter_state_read_zoom(&s,&g,&again));
        assert(!memcmp(again.fields,expected,10) && again.count==out.count);
        old=s;assert(zoom_write(&s,&g,p,&out)==-EALREADY);unchanged(&s,&old);
    }
    old=s;g.sequence_before=g.sequence_after=0;
    assert(zoom_write(&s,&g,p,&out)==-ESTALE);unchanged(&s,&old);
    g.sequence_before=g.sequence_after=514;g.source_origin=CP_START_STATE_ORIGIN_VIRTUAL_SOURCE;
    assert(zoom_write(&s,&g,p,&out)==-EXDEV);unchanged(&s,&old);
    g.source_origin=CP_START_STATE_ORIGIN_HOST_TEST;
    s.zoom.count=UINT64_MAX;old=s;
    assert(zoom_write(&s,&g,p,&out)==-EOVERFLOW);unchanged(&s,&old);
}
static void zoom_boundaries(void) {
    struct cp_parameter_state s,old;
    struct cp_start_state_guard g={(uint32_t)getpid(),2,2,CP_START_STATE_ORIGIN_HOST_TEST,1},bad;
    struct cp_parameter_zoom_readback out,previous;
    unsigned char p[13]={5,0,1,0x40,0x4c,0,0,0x80,0,2,0,2,0};
    zoom_ready(&s);old=s;memset(&out,0x9b,sizeof(out));previous=out;
    assert(zoom_write(NULL,&g,p,&out)==-EINVAL);
    assert(zoom_write(&s,NULL,p,&out)==-EINVAL);
    assert(zoom_write(&s,&g,NULL,&out)==-EINVAL);
    assert(zoom_write(&s,&g,p,NULL)==-EINVAL);
    assert(zoom_write(&s,&g,&s,&out)==-EINVAL);
    assert(zoom_write(&s,&g,s.bytes,&out)==-EINVAL);
    assert(zoom_write(&s,&g,&g,&out)==-EINVAL);
    assert(zoom_write(&s,&g,&out,&out)==-EINVAL);
    assert(zoom_write(&s,&g,(void *)(UINTPTR_MAX-1u),&out)==-EINVAL);
    assert(zoom_write(&s,(void *)&s,p,&out)==-EINVAL);
    assert(zoom_write(&s,&g,p,(void *)&s)==-EINVAL);
    assert(zoom_write(&s,&g,p,(void *)&g)==-EINVAL);
    for(size_t n=0;n<=13;n++)if(n!=12)
        assert(cp_parameter_state_consume_zoom(&s,&g,CP_PARAMETER_BATCH_SOURCE,CP_PARAMETER_BATCH_TARGET,p,n,&out)==-EMSGSIZE);
    assert(cp_parameter_state_consume_zoom(&s,&g,UINT32_C(0x8000004c),CP_PARAMETER_BATCH_TARGET,p,12,&out)==-EPERM);
    assert(cp_parameter_state_consume_zoom(&s,&g,CP_PARAMETER_BATCH_SOURCE,0,p,12,&out)==-EPERM);
    for(unsigned i=0;i<6;i++) {
        bad=g;
        switch(i) {case 0:bad.owner_pid++;break;case 1:bad.sequence_after=4;break;
        case 2:bad.sequence_before=bad.sequence_after=3;break;case 3:bad.quiescent=0;break;
        case 4:bad.quiescent=2;break;default:bad.source_origin=CP_START_STATE_ORIGIN_NONE;break;}
        assert(zoom_write(&s,&bad,p,&out)<0);
    }
    for(unsigned i=0;i<4;i++) {
        static const unsigned positions[]={0,2,3,4};
        unsigned at=positions[i];unsigned char save=p[at];p[at]=0;
        if(at==3)p[at]=0x41;
        if(at==4)p[7]=0;
        assert(zoom_write(&s,&g,p,&out)==-EPROTO);p[at]=save;p[7]=0x80;
    }
    unchanged(&s,&old);assert(!memcmp(&out,&previous,sizeof out));
    assert(!zoom_write(&s,&g,p,&out));old=s;
    s.known_mask[0x698/8]&=(unsigned char)~(1u<<(0x698%8));
    previous=out;assert(cp_parameter_state_read_zoom(&s,&g,&out)==-ENODATA);
    assert(!memcmp(&out,&previous,sizeof out));s=old;s.bytes[0x698]^=1;
    assert(cp_parameter_state_read_zoom(&s,&g,&out)==-ESTALE);s=old;
    {pid_t pid=fork();int status;assert(pid>=0);
     if(!pid){assert(zoom_write(&s,&g,p,&out)==-ECHILD);assert(cp_parameter_state_read_zoom(&s,&g,&out)==-ECHILD);_exit(0);}
     assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status));}
    zoom_ready(&s);s.common_stores_consumed=0;old=s;
    assert(zoom_write(&s,&g,p,&out)==-ENODATA);unchanged(&s,&old);
    zoom_ready(&s);s.default_stores_consumed=0;old=s;
    assert(zoom_write(&s,&g,p,&out)==-ENODATA);unchanged(&s,&old);
    zoom_ready(&s);s.batch.staged=false;old=s;
    assert(zoom_write(&s,&g,p,&out)==-ENODATA);unchanged(&s,&old);
    zoom_ready(&s);s.batch.owner_pid++;old=s;
    assert(zoom_write(&s,&g,p,&out)==-ECHILD);unchanged(&s,&old);
    assert(!cp_parameter_state_init(&s,false));old=s;
    assert(zoom_write(&s,&g,p,&out)==-EACCES);unchanged(&s,&old);
    memset(&s,0,sizeof s);old=s;assert(zoom_write(&s,&g,p,&out)==-EINVAL);unchanged(&s,&old);
}

int main(int argc, char **argv) {
    if (argc == 4 && strcmp(argv[1], "packet") == 0) packet_file(argv[2], argv[3],0);
    else if(argc==4 && strcmp(argv[1],"packet-common")==0) packet_file(argv[2],argv[3],1);
    else if(argc==4 && strcmp(argv[1],"packet-defaults")==0) packet_file(argv[2],argv[3],2);
    else if(argc==3 && strcmp(argv[1],"common")==0) common_file(argv[2]);
    else if(argc==3 && strcmp(argv[1],"defaults")==0) defaults_file(argv[2]);
    else { assert(argc == 1); boundaries(); decode_domains(); reset_store(); common_stores(); default_stores(); zoom_domains(); zoom_boundaries(); }
    return 0;
}
