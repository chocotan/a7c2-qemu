from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('cc'),reason='Host C compiler required')
def test_only_actual_bootin_and_im_paths_enter_crypto_initialization(tmp_path):
    source=tmp_path/'scope.c'
    source.write_text('''#include <assert.h>
#include <string.h>
#include "observer-process-scope.h"
int main(void){
 const char *yes[]={"/usr/bin/bootin.elf","/usr/bin/im.elf","/simulation/bootin-original"};
 for(unsigned i=0;i<3;i++)assert(menu_crypto_process_path(yes[i],strlen(yes[i])));
 const char *no[]={"/bin/busybox","/usr/bin/create_host_key","/usr/bin/im.elf.extra","/tmp/usr/bin/im.elf","im.elf","/usr/bin/sshd",""};
 for(unsigned i=0;i<7;i++)assert(!menu_crypto_process_path(no[i],strlen(no[i])));
 assert(!menu_crypto_process_path(0,0));assert(!menu_crypto_process_path(yes[0],-1));
 assert(!menu_crypto_process_path(yes[0],strlen(yes[0])-1));
 char raw[]={'/','u','s','r','/','b','i','n','/','i','m','.','e','l','f'};
 assert(menu_crypto_process_path(raw,sizeof raw));
 assert(menu_crypto_load_request(raw,sizeof raw,"appFw.so"));
 assert(menu_crypto_load_request(yes[0],strlen(yes[0]),"/usr/lib/appFw.so"));
 assert(!menu_crypto_load_request(raw,sizeof raw,"libInfraCrypt.so"));
 assert(!menu_crypto_load_request(raw,sizeof raw,0));
 assert(!menu_crypto_load_request(no[0],strlen(no[0]),"appFw.so"));return 0;
}
''')
    executable=tmp_path/'scope'
    result=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-I',str(Path(__file__).parent),str(source),'-o',str(executable)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    subprocess.run([str(executable)],check=True,timeout=10)
