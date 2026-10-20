from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

BASE = Path(__file__).resolve().parent


class GuiModelServiceTests(unittest.TestCase):
    def test_transport_ownership_concurrency_stop_and_fork(self):
        fixture = r'''
#include "gui-model-store.h"
#include <assert.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sched.h>
#include <unistd.h>
#include <sys/wait.h>
struct message {unsigned char data[748];unsigned int released;};
static unsigned int stop,done,freed,forked;
static unsigned char template[748];
static unsigned int size(void *p){assert(p);return 748;}
static int release(unsigned int q,void *p){
 assert(q==GUI_MODEL_QUEUE && !__atomic_exchange_n(&((struct message *)p)->released,1,__ATOMIC_SEQ_CST));
 __atomic_fetch_add(&freed,1,__ATOMIC_SEQ_CST);return 0;
}
static int persist(const char *path,const unsigned char *raw,unsigned long n){
 assert(!strcmp(path,GUI_MODEL_STORE_PATH) && n==GUI_MODEL_STORE_BASE_BYTES+748 && !memcmp(raw,"GMDL0003",8));
 if(!forked++){
  pid_t pid=fork();assert(pid>=0);
  if(!pid){int rc=123;assert(gui_model_service_send(GUI_MODEL_QUEUE,(void *)template,&rc)==1 && rc==-1021);_exit(0);}
  int status;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status));
 }
 return 0;
}
static void logline(const char *tag,const char *line){assert(tag && line);}
static void send_one(void){
 struct message *m=calloc(1,sizeof *m);assert(m);memcpy(m->data,template,748);
 int rc=123;assert(gui_model_service_send(GUI_MODEL_QUEUE,m->data,&rc)==1);
 if(rc){assert(rc==-1021 && !m->released);release(GUI_MODEL_QUEUE,m->data);}
 assert(m->released==1);free(m);
}
static void *sender(void *p){(void)p;for(int i=0;i<3000;i++)send_one();return 0;}
static void *stopper(void *p){
 (void)p;
 while(!__atomic_load_n(&done,__ATOMIC_ACQUIRE)){
  __atomic_store_n(&stop,1,__ATOMIC_RELEASE);sched_yield();
  __atomic_store_n(&stop,0,__ATOMIC_RELEASE);sched_yield();
 }
 return 0;
}
int main(void){
 unsigned int types[]={0x10,0x15,0x16,0x19,0x1a,0x1b},sizes[]={0x274,12,20,12,4,16},off=8,n=740;
 memcpy(template+4,&n,4);
 for(int i=0;i<6;i++){memcpy(template+off,&types[i],4);memcpy(template+off+4,&sizes[i],4);off+=8+sizes[i];}
 assert(off==748);
 struct gui_model_store_ops ops={0,size,release,persist,logline,&stop};
 int rc=123;assert(!gui_model_service_send(GUI_MODEL_QUEUE,template,&rc) && rc==123);
 assert(!gui_model_service_start(&ops));assert(gui_model_service_start(&ops)==-1);
 assert(!gui_model_service_send(1,template,&rc) && rc==123);
 assert(gui_model_service_send(GUI_MODEL_QUEUE,0,&rc)==1 && rc==-1021);
 send_one();assert(freed==1 && forked);
 pthread_t threads[4],toggle;assert(!pthread_create(&toggle,0,stopper,0));
 for(int i=0;i<4;i++)assert(!pthread_create(threads+i,0,sender,0));
 for(int i=0;i<4;i++)assert(!pthread_join(threads[i],0));
 __atomic_store_n(&done,1,__ATOMIC_RELEASE);assert(!pthread_join(toggle,0));
 assert(freed==12001);
 __atomic_store_n(&stop,1,__ATOMIC_RELEASE);
 send_one();assert(freed==12002);
}
'''
        compiler = shutil.which('clang') or shutil.which('cc')
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory() as name:
            binary = Path(name) / 'check'
            subprocess.run([compiler, '-x', 'c', '-', str(BASE / 'gui-model-store.c'),
                            str(BASE / 'gui-model-wire.c'), '-I', str(BASE), '-o', str(binary),
                            '-Wall', '-Wextra', '-Werror', '-pthread', '-fsanitize=address,undefined'],
                           input=fixture, text=True, check=True, capture_output=True)
            subprocess.run([str(binary)], capture_output=True, check=True, timeout=20)


if __name__ == '__main__':
    unittest.main()
