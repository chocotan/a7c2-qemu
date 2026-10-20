from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent

# All signals and dynamic symbols are mocked. Guest /tmp names are redirected to
# a new temporary directory; no host TTY, /proc owner or device is used.
FIXTURE = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <pthread.h>
static int mode,flushes,stops,continues,current_pid=1234;
static int ack_fd=-1,ack_attempts,ack_failures,request_opens;
static unsigned long long active_seq;
static const char *directory;
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition=PTHREAD_COND_INITIALIZER;
static int paused,released;
static char *mapped(const char *path,char *out){
 assert(!strncmp(path,"/tmp/",5));
 int n=snprintf(out,512,"%s/%s",directory,path+5);assert(n>0 && n<512);return out;
}
static int exists(const char *suffix){
 char path[512];snprintf(path,sizeof path,"%s/sd-flush.%llu.%s",directory,active_seq,suffix);
 return access(path,F_OK)==0;
}
static void cancel(void){
 char path[512];snprintf(path,sizeof path,"%s/sd-flush.%llu.cancel",directory,active_seq);
 int fd=open(path,O_WRONLY|O_CREAT|O_EXCL,0600);assert(fd>=0);assert(!close(fd));
}
static void pause_guest(void){
 assert(!pthread_mutex_lock(&mutex));paused=1;assert(!pthread_cond_broadcast(&condition));
 while(!released)assert(!pthread_cond_wait(&condition,&mutex));
 assert(!pthread_mutex_unlock(&mutex));
}
static int original_mount(const char *p,unsigned int flags,char *d,const void *e){
 (void)p;(void)flags;(void)e;*d='A';return 0;
}
static int original_flush(unsigned char drive){
 assert(drive=='A');flushes++;
 if((mode==15 || mode==17) && flushes==2){
  unsigned long long seq=active_seq;active_seq=123;assert(exists("cancelled"));active_seq=seq;
 }
 if(mode==2)pause_guest();
 return mode==5?-9:0;
}
static void *lookup(void *h,const char *name){
 (void)h;
 if(!strcmp(name,"Fsys_Mount"))return original_mount;
 if(!strcmp(name,"Fsys_FlushVolume"))return original_flush;
 abort();
}
static void *fake_dlvsym(void *h,const char *name,const char *v){(void)h;(void)name;(void)v;return lookup;}
static int fake_open(const char *path,int flags,...){
 char real[512];mapped(path,real);
 if(!strcmp(path,"/tmp/sd-flush.request"))request_opens++;
 if(strstr(path,".cancel") && !strstr(path,".cancelled")){
  assert(exists("reply"));
  if(mode==3)pause_guest();
  if(mode==11){errno=EACCES;return -1;}
 }
 if(mode==6 && strstr(path,".reply.new")){errno=ENOSPC;return -1;}
 int fd=open(real,flags,0600);
 if(fd>=0 && strstr(path,".cancelled.new"))ack_fd=fd;
 return fd;
}
static long fake_write(int fd,const void *data,unsigned long n){
 if(fd==ack_fd){
  ack_attempts++;
  if(ack_failures){ack_failures--;errno=ENOSPC;return -1;}
 }
 if(mode==7){assert(n>1);return write(fd,data,n-1);}
 return write(fd,data,n);
}
static int fake_fsync(int fd){if(mode==8){errno=EIO;return -1;}return fsync(fd);}
static int fake_close(int fd){
 if(fd==ack_fd)ack_fd=-1;
 int rc=close(fd);if(mode==9 && flushes){errno=EIO;return -1;}return rc;
}
static int fake_rename(const char *a,const char *b){
 char first[512],second[512];mapped(a,first);mapped(b,second);
 if(mode==10){errno=EIO;return -1;}
 return rename(first,second);
}
static int fake_getpid(void){return current_pid;}
static int fake_fflush(void *stream){(void)stream;return 0;}
static int fake_kill(int pid,int signal){
 assert(pid==1234 && signal==19 && exists("reply"));
 if(mode==4)pause_guest();
 stops++; /* No real host signals. The parent waits for this exact boundary. */
 if(mode==0 || mode==4)pause_guest();
 return 0;
}
#define dlvsym fake_dlvsym
#define open fake_open
#define write fake_write
#define fsync fake_fsync
#define close fake_close
#define rename fake_rename
#define getpid fake_getpid
#define kill fake_kill
#define fflush fake_fflush
'''

MAIN = r'''
#undef open
#undef write
#undef fsync
#undef close
#undef rename
static void request(unsigned long long seq){
 char path[512],text[64];active_seq=seq;
 snprintf(path,sizeof path,"%s/sd-flush.request",directory);
 int fd=open(path,O_WRONLY|O_CREAT|O_TRUNC,0600);assert(fd>=0);
 int n=snprintf(text,sizeof text,"%llu\n",seq);assert(write(fd,text,n)==n);assert(!close(fd));
}
static void check_cancelled(unsigned long long seq){
 char path[512],text[200],expected[200];
 snprintf(path,sizeof path,"%s/sd-flush.%llu.cancelled",directory,seq);
 int fd=open(path,O_RDONLY);assert(fd>=0);
 long n=read(fd,text,sizeof text-1);assert(n>0);text[n]=0;assert(!close(fd));
 snprintf(expected,sizeof expected,"SD_FSYS_CANCELLED seq=%llu pid=1234\n",seq);
 assert(!strcmp(text,expected));
}
static void check_reply(unsigned long long seq){
 char path[512],text[200],expected[200];
 snprintf(path,sizeof path,"%s/sd-flush.%llu.reply",directory,seq);
 int fd=open(path,O_RDONLY);assert(fd>=0);
 long n=read(fd,text,sizeof text-1);assert(n>0);text[n]=0;assert(!close(fd));
 snprintf(expected,sizeof expected,"SD_FSYS_FLUSH seq=%llu pid=1234 drive=65 rc=0\n",seq);
 assert(!strcmp(text,expected));
}
static void *worker(void *unused){(void)unused;file_media_flush_pending();return 0;}
static void wait_paused(void){
 assert(!pthread_mutex_lock(&mutex));
 while(!paused)assert(!pthread_cond_wait(&condition,&mutex));
 assert(!pthread_mutex_unlock(&mutex));
}
static void release_guest(void){
 assert(!pthread_mutex_lock(&mutex));released=1;
 assert(!pthread_cond_broadcast(&condition));assert(!pthread_mutex_unlock(&mutex));
}
int main(int argc,char **argv){
 assert(argc==3);mode=atoi(argv[1]);directory=argv[2];unsetenv("A7C2_FILE_MEDIA_TEST");
 char drive;assert(!Fsys_Mount("/nondev/rm2",0x300,&drive,0));request(123);
 if(mode==0 || mode==2 || mode==3 || mode==4){
  pthread_t thread;assert(!pthread_create(&thread,0,worker,0));wait_paused();
  if(mode==0){assert(stops==1 && exists("reply"));cancel();continues++;}
  if(mode==2){assert(!exists("reply"));cancel();request(124);active_seq=123;}
  if(mode==3){assert(exists("reply") && !stops);cancel();}
  if(mode==4){assert(exists("reply") && !stops);cancel(); /* Early CONT is not recovery. */}
  release_guest();assert(!pthread_join(thread,0));
  if(mode==4){assert(stops==1);continues++;}
 }else{
  if(mode==1 || (mode>=14 && mode<=18))cancel();
  if(mode==14 || mode==15)ack_failures=mode==14?1:3;
  if(mode>=16 && mode<=18){
   file_media_flush_cancel_retry();
   assert(!request_opens && !flushes && !ack_attempts && !stops && !continues);
   ack_failures=mode==18?40:1;
  }
  if(mode==12)mounted_media_drive=0;
  if(mode==13)current_pid=4321;
  file_media_flush_pending();
 }
 if(mode>=16 && mode<=18){
  assert(errno==ENOSPC && flushes==1 && ack_attempts==1 && request_opens==1);
  assert(!exists("cancelled"));check_reply(123);
  if(mode==17){request(124);cancel();}
  int opened=request_opens;
  busy=1;file_media_flush_cancel_retry();assert(ack_attempts==1 && busy==1);busy=0;
  current_pid=4321;file_media_flush_cancel_retry();assert(ack_attempts==1);current_pid=1234;
  if(mode==18){
   for(int i=1;i<40;i++){
    file_media_flush_cancel_retry();assert(errno==ENOSPC);
    assert(!exists("cancelled") && flushes==1 && ack_attempts==i+1);
   }
  }
  file_media_flush_cancel_retry();check_cancelled(123);check_reply(123);
  assert(!cancel_pending && flushes==1 && !stops && !continues && request_opens==opened);
  assert(ack_attempts==(mode==18?41:2));
  file_media_flush_cancel_retry();assert(request_opens==opened && flushes==1);
  if(mode==17){
   assert(!exists("reply") && !exists("cancelled"));
   file_media_flush_pending();check_reply(124);check_cancelled(124);
   assert(flushes==2 && ack_attempts==3 && !stops && !continues);
  }
  return 0;
 }
 if(mode==14 || mode==15){
  assert(errno==ENOSPC);
  assert(flushes==1 && !stops && !continues && ack_attempts==1 && !exists("cancelled"));
  assert(exists("reply") && exists("cancel"));check_reply(123);
  if(mode==15){
   request(124);cancel();
   file_media_flush_pending();
   assert(flushes==1 && !stops && ack_attempts==2 && !exists("reply") && !exists("cancelled"));
   file_media_flush_pending();
   assert(flushes==1 && !stops && ack_attempts==3 && !exists("reply") && !exists("cancelled"));
   active_seq=123;assert(exists("reply") && exists("cancel") && !exists("cancelled"));
   active_seq=124;
  }
  file_media_flush_pending();check_cancelled(123);check_reply(123);
  assert(!stops && !continues && flushes==(mode==14?1:2));
  assert(ack_attempts==(mode==14?2:5));
  if(mode==15){check_cancelled(124);check_reply(124);}
  active_seq=123;assert(exists("cancel") && exists("reply"));
  request(123);file_media_flush_pending();
  assert(!stops && flushes==(mode==14?1:2) && ack_attempts==(mode==14?2:5));
  return 0;
 }
 assert(stops==((mode==0 || mode==4)?1:0));
 assert(continues==((mode==0 || mode==4)?1:0));
 assert(flushes==((mode==12 || mode==13)?0:1));
 assert(exists("reply")==!(mode==6 || mode==7 || mode==8 || mode==9 || mode==10 || mode==13));
 assert(exists("cancelled")==!!(mode==0 || mode==1 || mode==2 || mode==3 || mode==4 || mode==11));
 if(mode==0 || mode==4)check_cancelled(123);
 if(exists("reply")){
  char path[512],text[200];snprintf(path,sizeof path,"%s/sd-flush.123.reply",directory);
  int fd=open(path,O_RDONLY);assert(fd>=0);long n=read(fd,text,sizeof text-1);assert(n>0);text[n]=0;close(fd);
  assert(strstr(text,"SD_FSYS_FLUSH seq=123 pid=1234 drive="));
  assert(strstr(text,mode==5?"rc=-9\n":mode==12?"rc=-1021\n":"rc=0\n"));
 }
 int old_flushes=flushes;if(mode!=2)file_media_flush_pending();assert(flushes==old_flushes);
 if(mode==2){
  request(124);cancel();file_media_flush_pending();assert(flushes==2 && !stops);
  active_seq=123;assert(exists("cancel") && exists("cancelled"));
  request(123);file_media_flush_pending();assert(flushes==2 && !stops);
 }
 return 0;
}
'''


class FlushBarrierTests(unittest.TestCase):
    def test_sanitized_guest_interleavings_and_io_failures(self):
        source = FIXTURE + '\n#include "file-media-config.c"\n' + MAIN
        modes = ["normal_STOP_CONT", "cancel_before_start", "slow_flush_cancel",
                 "cancel_after_reply_before_lookup", "cancel_after_lookup_before_STOP",
                 "original_flush_failure", "reply_open_failure", "reply_short_write",
                 "reply_fsync_failure", "reply_close_failure", "reply_rename_failure",
                 "cancel_lookup_EACCES", "no_mounted_drive", "foreign_owner",
                 "cancelled_first_write_failure_retry", "new_request_waits_for_old_cancelled_retry",
                 "timer_only_cancelled_retry", "timer_leaves_new_request_for_pending",
                 "timer_persistent_ENOSPC_log_throttle_then_recovery"]
        with tempfile.TemporaryDirectory() as name:
            binary = Path(name) / 'test'
            subprocess.run(['cc', '-x', 'c', '-', '-I', str(HERE), '-o', str(binary),
                            '-Wall', '-Wextra', '-Werror', '-pthread',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'],
                           input=source, text=True, capture_output=True, check=True)
            for mode, label in enumerate(modes):
                with self.subTest(mode=label), tempfile.TemporaryDirectory() as files:
                    completed = subprocess.run([str(binary), str(mode), files],
                                               capture_output=True, timeout=10)
                    self.assertEqual(completed.returncode, 0, completed.stderr.decode())
                    if mode in (14, 15, 16, 17, 18):
                        failure = b'SD_FSYS_CANCELLED_FAILED seq=123 errno=28\n'
                        count = 3 if mode == 15 else 10 if mode == 18 else 1
                        self.assertEqual(completed.stdout, failure * count)


if __name__ == '__main__':
    unittest.main()
