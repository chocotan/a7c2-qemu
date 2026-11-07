#!/usr/bin/env python3
"""Media admission and read-only query failure tests; no original kernel launched."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/'p1-media-init-probe.py'))


def evidence():
    return (b'UPDATE_MEDIA_QUERY pid=123 uid=0 euid=0 gid=0 egid=0 readonly=1\n'
        + b'UPDATE_MEDIA_QUERY_UIPC original_rc=0\n'
        + ''.join(f'UPDATE_MEDIA_BACKUP id={i:06x} size=1 rc=1 value=00\n' for i in M['IDS']).encode()
        + ('UPDATE_MEDIA_PATH id=4b0002 size=24 rc=24 hex='+ (b'/nondev/rm2'+b'\0'*13).hex()+'\n').encode()
        + b'UPDATE_MEDIA_QUERY_RESULT rc=0\nUPDATE_MEDIA_GUARD rc=0\n')


class Media(unittest.TestCase):
    def test_query_requires_all_actual_values_once_and_original_path(self):
        self.assertTrue(M['query_evidence'](evidence())['original_readback_verified'])
        for raw in (evidence()+evidence(), evidence().replace(b'value=00',b'value=01',1),
                    evidence().replace(b'size=1 rc=1',b'size=-1 rc=-999',1),
                    evidence().replace(b'size=1 rc=1',b'size=1 rc=-1',1),
                    evidence().replace(b'size=1 rc=1',b'size=1 rc=0',1),
                    evidence().replace(b'uid=0',b'uid=1',1),
                    evidence().replace(b'2f6e6f6e6465762f726d32',b'2f6e6f6e6465762f726d33'),
                    evidence().replace(b'UPDATE_MEDIA_GUARD rc=0\n',b'')):
            self.assertFalse(M['query_evidence'](raw)['original_readback_verified'])

    def test_original_api_helper_reads_only_and_rejects_size_value_rc_path_failures(self):
        prefix=M['QUERY_SOURCE'].split('extern int __libc_start_main')[0]
        stubs=r'''
#include <stdlib.h>
#include <string.h>
int getpid(void){return 123;}
int getuid(void){return getenv("NONROOT")!=0;}
int geteuid(void){return 0;} int getgid(void){return 0;} int getegid(void){return 0;}
int u_uipc_init(void){return getenv("BADUIPC") ? -9 : 0;}
int Backup_get_datasize(unsigned id){return getenv("BADSIZE") ? 2 : id==0x4b0002 ? 24 : 1;}
int Backup_read(unsigned id, void *p){
 if(getenv("BADRC")) return -7;
 if(id==0x4b0002) {memset(p,0,24); memcpy(p,"/nondev/rm2",11); if(getenv("BADPATH")) ((char*)p)[10]='3';}
 else *(unsigned char*)p=getenv("BADVALUE")?1:0;
 return getenv("ZERORC") ? 0 : id==0x4b0002 ? 24 : 1;
}
int main(int argc,char **argv){return run(argc,argv);}
'''
        with tempfile.TemporaryDirectory() as d:
            d=Path(d); (d/'query.c').write_text(prefix+stubs)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',d/'query.c','-o',d/'query'],check=True,capture_output=True)
            result=subprocess.run([d/'query'],capture_output=True,env={'PATH':os.defpath})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(M['query_evidence'](result.stdout+b'UPDATE_MEDIA_GUARD rc=0\n')['original_readback_verified'])
            for key in ('NONROOT','BADUIPC','BADSIZE','BADRC','ZERORC','BADVALUE','BADPATH'):
                result=subprocess.run([d/'query'],capture_output=True,env={'PATH':os.defpath,key:'1'})
                self.assertNotEqual(result.returncode,0,key)
                self.assertFalse(M['query_evidence'](result.stdout)['original_readback_verified'])

    def test_new_profile_cannot_be_enabled_with_only_an_allowlist(self):
        u=runpy.run_path(str(HERE/'update-boot.py'))
        self.assertEqual(len(u['RESOURCE_MODULES']),7)
        with self.assertRaisesRegex(ValueError,'requires explicit original_resources'):
            u['build']('/absent','/absent','/absent',mode='official',media_resources='/forged.json')


if __name__=='__main__':unittest.main()
