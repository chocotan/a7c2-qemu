from pathlib import Path
import hashlib
import os
import subprocess

HERE=Path(__file__).resolve().parent


def test_actual_public_stage_selects_source_defaults_atomically(tmp_path):
    seed=HERE/'menu-root/seed-backup.bin'
    assert hashlib.sha256(seed.read_bytes()).hexdigest()=='3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
    code=tmp_path/'import.c'
    code.write_text(r'''
#include "cp-parameter-import.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(int argc,char **argv) {
 assert(argc==2);FILE *f=fopen(argv[1],"rb");assert(f);
 unsigned char *seed=malloc(2390264);assert(seed && fread(seed,1,2390264,f)==2390264);
 assert(fgetc(f)==EOF && !fclose(f));unsigned char *stage=seed+0xed000;
 struct cp_property_stage owner;assert(!cp_property_stage_init(&owner));
 struct cp_start_state_guard guard={(uint32_t)getpid(),2,2,CP_START_STATE_ORIGIN_HOST_TEST,1};
 struct cp_parameter_import out,before;memset(&out,0xa5,sizeof out);before=out;
 assert(cp_parameter_import_inspect(&owner,&guard,stage,CP_PROPERTY_STAGE_BYTES,&out)==-ESTALE);
 assert(!memcmp(&out,&before,sizeof out));
 assert(!cp_property_stage_consume(&owner,&guard,CP_PROPERTY_STAGE_SOURCE_CP_INITIAL_STAGE,stage,CP_PROPERTY_STAGE_BYTES));
 assert(!cp_parameter_import_inspect(&owner,&guard,stage,CP_PROPERTY_STAGE_BYTES,&out));
 assert(out.header==0 && out.flags==0 && out.properties_consumed && out.defaults_selected && !out.import_selected);
 assert(out.source_sequence==2 && out.origin==CP_START_STATE_ORIGIN_HOST_TEST && out.stage_fnv1a64==CP_PROPERTY_STAGE_FNV1A64);
 before=out;
 stage[9]=1;
 assert(cp_parameter_import_inspect(&owner,&guard,stage,CP_PROPERTY_STAGE_BYTES,&out)==-EILSEQ && !memcmp(&out,&before,sizeof out));
 stage[9]=0;stage[0x333f4]=0x68;
 assert(cp_parameter_import_inspect(&owner,&guard,stage,CP_PROPERTY_STAGE_BYTES,&out)==-EILSEQ && !memcmp(&out,&before,sizeof out));
 stage[0x333f4]=0;
 guard.sequence_before=guard.sequence_after=4;
 assert(cp_parameter_import_inspect(&owner,&guard,stage,CP_PROPERTY_STAGE_BYTES,&out)==-ESTALE && !memcmp(&out,&before,sizeof out));
 guard.sequence_before=guard.sequence_after=2;
 assert(cp_parameter_import_inspect(&owner,&guard,stage,CP_PROPERTY_STAGE_BYTES-1,&out)==-EMSGSIZE);
 assert(cp_parameter_import_inspect(&owner,&guard,stage,CP_PROPERTY_STAGE_BYTES,(void *)stage)==-EINVAL);
 assert(cp_parameter_import_inspect(&owner,&guard,stage,CP_PROPERTY_STAGE_BYTES,(void *)&owner)==-EINVAL);
 assert(cp_parameter_import_inspect(&owner,&guard,stage,CP_PROPERTY_STAGE_BYTES,(void *)&guard)==-EINVAL);
 assert(cp_parameter_import_inspect(&owner,&guard,stage,CP_PROPERTY_STAGE_BYTES,NULL)==-EINVAL);
 assert(!memcmp(&out,&before,sizeof out));free(seed);return 0;
}
''')
    models=HERE/'device-models';binary=tmp_path/'import'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic','-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer','-no-pie','-I',str(models),str(code),
                    *(str(models/name) for name in ('cp-parameter-import.c','cp-property-stage.c',
                        'cp-start-state-provider.c','cp-start-state-data.c')),'-o',str(binary)],check=True)
    subprocess.run([str(binary),str(seed)],check=True,timeout=15,
                   env=dict(os.environ,ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
