from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

BASE = Path(__file__).resolve().parent


class GuiModelStoreTests(unittest.TestCase):
    def test_commit_before_free_and_failures(self):
        fixture = r'''
#include "gui-model-store.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static unsigned int stop, received, freed, saved;
static int mode, live;
static unsigned char packet[748], snapshot[GUI_MODEL_STORE_BYTES];
static unsigned int word(const unsigned char *p) { unsigned int n;memcpy(&n,p,4);return n; }
static void put(unsigned int at,unsigned int n){memcpy(packet+at,&n,4);}
static int receive(unsigned int q,void **p,long timeout){
 assert(q==GUI_MODEL_QUEUE && timeout==1000);received++;
 if(mode==4)return -1022;
 if(mode==5)return -2;
 *p=packet;live=1;return 0;
}
static unsigned int size(void *p){assert(p==packet && live);return sizeof packet;}
static int release(unsigned int q,void *p){assert(q==GUI_MODEL_QUEUE && p==packet && live);freed++;live=0;return mode==3?-1:0;}
static int persist(const char *path,const unsigned char *raw,unsigned long n){
 assert(!strcmp(path,"snapshot") && live && n==GUI_MODEL_STORE_BASE_BYTES+sizeof packet);saved++;
 memcpy(snapshot,raw,n);return mode==2?-1:0;
}
static void logline(const char *tag,const char *line){assert(tag && line);}
int main(int argc,char **argv){
 assert(argc==2);mode=atoi(argv[1]);
 unsigned int types[]={0x10,0x15,0x16,0x19,0x1a,0x1b},sizes[]={0x274,12,20,12,4,16},off=8;
 put(4,sizeof packet-8);
 for(unsigned int i=0;i<6;i++){put(off,types[i]);put(off+4,sizes[i]);memset(packet+off+8,i+1,sizes[i]);off+=8+sizes[i];}
 assert(off==sizeof packet);
 if(mode==1)put(4,0);
 struct gui_model_store state={0};
 struct gui_model_store_ops ops={receive,size,release,persist,logline,&stop};
 int rc=gui_model_store_step(&state,&ops,"snapshot");
 assert(!live && received==1);
 if(mode==0){
  assert(!rc && !state.failed && freed==1 && saved==1 && state.packets==1 && state.changed==63);
  assert(!memcmp(snapshot,"GMDL0003",8) && word(snapshot+24)==63 && word(snapshot+28)==63);
  assert(word(snapshot+32)==4 && word(snapshot+44)==125 && word(snapshot+48)==100);
  assert(!gui_model_store_step(&state,&ops,"snapshot"));
  assert(state.packets==2 && !state.changed && freed==2 && saved==2);
  for(unsigned int i=0;i<6;i++)assert(state.generations[i]==2);
  packet[16]^=1;
  assert(!gui_model_store_step(&state,&ops,"snapshot"));assert(state.changed==1 && freed==3);
  put(8,0xaabbccdd);
  assert(!gui_model_store_step(&state,&ops,"snapshot") && state.packets==4 && freed==4);
  assert(!memcmp(snapshot+GUI_MODEL_STORE_PREFIX_BYTES,packet,sizeof packet));
  stop=1;assert(gui_model_store_step(&state,&ops,"snapshot")==-1 && received==4);
 }else if(mode==4){assert(!rc && !state.failed && !state.packets && !freed && !saved);}
 else {
  assert(rc==-1 && state.failed && freed==(mode==5?0:1));
  assert(saved==((mode==2 || mode==3)?1:0));
  assert(state.packets==(mode==3?1:0));
  assert(gui_model_store_step(&state,&ops,"snapshot")==-1 && received==1);
 }
}
'''
        compiler = shutil.which('clang') or shutil.which('cc')
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory() as name:
            binary = Path(name) / 'check'
            subprocess.run([compiler, '-x', 'c', '-', str(BASE / 'gui-model-store.c'),
                            str(BASE / 'gui-model-wire.c'), '-I', str(BASE), '-o', str(binary),
                            '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined'],
                           input=fixture, text=True, check=True, capture_output=True)
            for mode in range(6):
                with self.subTest(mode=mode):
                    subprocess.run([str(binary), str(mode)], capture_output=True,
                                   check=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
