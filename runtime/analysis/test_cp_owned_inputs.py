from pathlib import Path
import hashlib
import os
import subprocess

HERE = Path(__file__).resolve().parent


def test_actual_owned_inputs_helper_consumes_public_stage_and_parameter_copy(tmp_path):
    source = (HERE/'menu-observe.c').read_text()
    helper = source[source.index('static int cp_owned_bootstrap_inputs(void) {'):
                    source.index('static int cp_owned_start_provider(')]
    seed = HERE/'menu-root/seed-backup.bin'
    raw = seed.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
    frozen = tmp_path/'frozen.bin'
    data = bytearray(raw)
    data[0xed000+9] = 1
    frozen.write_bytes(data)
    fixture = r'''
#define _GNU_SOURCE
#include "cp-property-stage-file.h"
#include "cp-parameter-view.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static const char *file;
static unsigned logs;
static int config_fail;
static struct cp_start_state_provider cp_owned_start_state;
static struct cp_parameter_state cp_owned_parameters;
static struct cp_parameter_view cp_owned_parameter_view;
static struct cp_property_stage cp_owned_property_stage;
static struct cp_parameter_import cp_owned_parameter_import;
static void record(const char *prefix,const char *text) {
    assert(!strcmp(prefix,"NATIVE_CP_OWNED_INPUTS "));
    assert(strstr(text,"source=public-CP-initial-stage ") && strstr(text,"repository_fallback=0 frozen_stage_used=0"));
    assert(strstr(text,"initialization_complete=0 original_CP=0 data_3003_known=0 capture=0"));
    if(strstr(text,"stage_rc=0 profile_rc=0")) {
        assert(strstr(text,"mode_property_consumed=1 mode=1 profile_property_consumed=1 profile=0"));
        if(config_fail) assert(strstr(text,"config_chain_rc=-5 local_flagb_known=0"));
        else assert(strstr(text,"config_chain_rc=0 local_flagb_known=1 local_flagb=0 constructor_sequence=8 config_copy_sequence=10 bank3_sequence=12 flagb_store_sequence=14"));
    } else assert(strstr(text,"mode_property_consumed=0") && strstr(text,"profile_property_consumed=0"));
    logs++;errno=77;
}
extern int __real_open(const char *,int,...);
int __wrap_open(const char *path,int flags,...) {
    assert(!strcmp(path,"/seed-backup.bin") && flags==0);
    return __real_open(file,flags);
}
int __real_cp_parameter_view_consume_config_copy(struct cp_parameter_view *,
    const struct cp_start_state_guard *,enum cp_parameter_view_config_copy_event,
    const struct cp_start_state_span *);
int __wrap_cp_parameter_view_consume_config_copy(struct cp_parameter_view *owner,
    const struct cp_start_state_guard *guard,enum cp_parameter_view_config_copy_event event,
    const struct cp_start_state_span *span) {
    if(config_fail){errno=EIO;return -EIO;}
    return __real_cp_parameter_view_consume_config_copy(owner,guard,event,span);
}
'''
    main = r'''
int main(int argc,char **argv) {
    assert(argc==3);file=argv[1];int bad=atoi(argv[2]);config_fail=(bad==2);
    assert(!cp_start_state_provider_init(&cp_owned_start_state));
    assert(!cp_parameter_state_init(&cp_owned_parameters,true));
    assert(!cp_parameter_state_consume_common_stores(&cp_owned_parameters));
    errno=31;int rc=cp_owned_bootstrap_inputs();assert(errno==31 && logs==1);
    if(bad==1) {
        assert(rc<0);
        assert(!cp_owned_parameter_view.copy_consumed && !cp_owned_parameter_view.bank0_bound);
        assert(!cp_owned_start_state.property_delivered && !cp_owned_start_state.data.known_mask);
    } else if(bad==2) {
        assert(rc==-EIO);
        assert(cp_owned_parameter_view.copy_consumed && cp_owned_parameter_view.bank0_bound);
        assert(cp_owned_parameter_view.constructor_store_sequence==8);
        assert(cp_owned_parameter_view.config_copy_event==CP_PARAMETER_VIEW_CONFIG_COPY_NONE);
        assert(!cp_owned_parameter_view.bank3_bound && !cp_owned_parameter_view.flagb_known);
        assert(cp_owned_start_state.property_delivered && !cp_owned_start_state.data.known_mask);
    } else {
        assert(!rc);
        struct cp_start_state_guard guard={(uint32_t)getpid(),2,2,CP_START_STATE_ORIGIN_VIRTUAL_SOURCE,1};
        struct cp_property_stage_readback property;
        assert(!cp_property_stage_snapshot(&cp_owned_property_stage,&guard,&property));
        assert(property.mode==1 && property.profile_known && property.context[4]==0);
        assert(cp_owned_parameter_import.properties_consumed && cp_owned_parameter_import.defaults_selected && !cp_owned_parameter_import.import_selected);
        unsigned local_known=0;
        for(size_t i=0;i<CP_PARAMETER_STATE_IMAGE_BYTES;++i)
            local_known+=(cp_owned_parameters.known_mask[i/8]>>(i%8))&1u;
        assert(local_known==2913);
        unsigned char actual[4];
        assert(!cp_parameter_state_read(&cp_owned_parameters,0x28,actual,4) && actual[0]==5);
        assert(!cp_parameter_state_read(&cp_owned_parameters,0xd5c,actual,4) && !actual[0]);
        assert(cp_owned_start_state.property_delivered && cp_owned_start_state.context[4]==0);
        assert(cp_owned_start_state.data.predicate_known_mask==1 && !cp_owned_start_state.data.known_mask);
        assert(cp_owned_parameter_view.copy_consumed && cp_owned_parameter_view.bank0_bound);
        assert(cp_owned_parameter_view.copy_sequence==4 && cp_owned_parameter_view.bank_sequence==6);
        unsigned char bytes[CP_PARAMETER_VIEW_OVERRIDE_BYTES],known[CP_PARAMETER_VIEW_OVERRIDE_BYTES];
        guard.sequence_before=guard.sequence_after=14;
        struct cp_parameter_view_flagb_readback flagb;
        assert(!cp_parameter_view_copy_flagb(&cp_owned_parameter_view,&guard,&flagb));
        assert(flagb.config_word==2 && flagb.flagb==0);
        assert(flagb.constructor_store_sequence==8 && flagb.config_copy_sequence==10);
        assert(flagb.bank3_sequence==12 && flagb.flagb_store_sequence==14);
        assert(!cp_parameter_view_copy_override_span(&cp_owned_parameter_view,&guard,bytes,sizeof bytes,known,sizeof known));
        assert(known[0x1c8]==1 && bytes[0x1c8]==0 && known[0]==0);
        assert(!cp_parameter_state_init(&cp_owned_parameters,true));
        unsigned char preserved=bytes[0x1c8];
        assert(!cp_parameter_view_copy_override_span(&cp_owned_parameter_view,&guard,bytes,sizeof bytes,known,sizeof known));
        assert(known[0x1c8]==1 && bytes[0x1c8]==preserved);
    }
    return 0;
}
'''
    path = tmp_path/'owned-inputs.c'
    path.write_text(fixture + helper + main)
    binary = tmp_path/'owned-inputs'
    models = HERE/'device-models'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', '-I', str(models),
                    str(path), *(str(models/name) for name in ('cp-parameter-batch.c', 'cp-parameter-state.c',
                        'cp-parameter-view.c', 'cp-property-stage.c', 'cp-property-stage-file.c', 'cp-parameter-import.c',
                        'cp-start-state-provider.c', 'cp-start-state-data.c')),
                    '-Wl,--wrap=open', '-Wl,--wrap=cp_parameter_view_consume_config_copy', '-o', str(binary)], check=True)
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1')
    for filename, bad in ((seed,0),(frozen,1),(tmp_path/'absent.bin',1),(seed,2)):
        subprocess.run([str(binary), str(filename), str(bad)], check=True, env=env, timeout=15)
