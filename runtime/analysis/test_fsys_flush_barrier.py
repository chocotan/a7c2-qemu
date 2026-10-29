from pathlib import Path
import re
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
static int console_fd,console_failure,console_opens,console_writes,console_closes,last_trace_errno;
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
 assert(drive=='A' && errno==last_trace_errno);flushes++;
 if((mode==15 || mode==17) && flushes==2){
  unsigned long long seq=active_seq;active_seq=123;assert(exists("cancelled"));active_seq=seq;
 }
 if(mode==2)pause_guest();
 int rc=mode==5?-9:0;
 dprintf(console_fd,"TEST_ORIGINAL_FLUSH seq=%llu rc=%d\n",active_seq,rc);
 errno=47;return rc;
}
static void *lookup(void *h,const char *name){
 (void)h;
 if(!strcmp(name,"Fsys_Mount"))return original_mount;
 if(!strcmp(name,"Fsys_FlushVolume"))return original_flush;
 abort();
}
static void *fake_dlvsym(void *h,const char *name,const char *v){(void)h;(void)name;(void)v;return lookup;}
static int fake_open(const char *path,int flags,...){
 if(!strcmp(path,"/dev/console")){
  assert(flags==1);console_opens++;errno=94;
  return console_failure==1?-1:9000;
 }
 char real[512];mapped(path,real);
 if(strstr(path,".reply.new") && flushes)assert(errno==47);
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
 if(fd==9000){
  assert(n>1 && n<240);console_writes++;
  long rc=console_failure==2?-1:write(console_fd,data,n-(console_failure==3));
  errno=95;return rc;
 }
 if(fd==ack_fd){
  ack_attempts++;
  if(ack_failures){ack_failures--;errno=ENOSPC;return -1;}
 }
 if(mode==7){assert(n>1);return write(fd,data,n-1);}
 return write(fd,data,n);
}
static int fake_fsync(int fd){if(mode==8){errno=EIO;return -1;}return fsync(fd);}
static int fake_close(int fd){
 if(fd==9000){console_closes++;errno=96;return console_failure==4?-1:0;}
 if(fd==ack_fd)ack_fd=-1;
 int rc=close(fd);if(mode==9 && flushes){errno=EIO;return -1;}return rc;
}
static int fake_rename(const char *a,const char *b){
 char first[512],second[512];mapped(a,first);mapped(b,second);
 if(mode==10){errno=EIO;return -1;}
 int rc=rename(first,second),error=errno;
 if(!rc && strstr(b,".reply"))dprintf(console_fd,"TEST_REPLY_RENAME seq=%llu\n",active_seq);
 errno=error;return rc;
}
static int fake_getpid(void){return current_pid;}
static long fake_syscall(long number,...){assert(number==178);last_trace_errno=errno;errno=93;return 5678;}
static int fake_printf(const char *format,...){
 va_list args;va_start(args,format);
 int rc=vprintf(format,args);va_end(args);errno=91;return rc;
}
static int fake_fflush(void *stream){(void)stream;errno=92;return 0;}
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
#define syscall fake_syscall
#define printf fake_printf
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
 assert(argc==5);mode=atoi(argv[1]);directory=argv[2];unsetenv("A7C2_FILE_MEDIA_TEST");
 console_failure=mode==21?1:atoi(argv[3]);
 char console_path[512];snprintf(console_path,sizeof console_path,"%s/console",directory);
 console_fd=open(console_path,O_WRONLY|O_CREAT|O_TRUNC,0600);assert(console_fd>=0);
 if(atoi(argv[4]))assert(freopen("/dev/null","w",stdout));
 char drive;assert(!Fsys_Mount("/nondev/rm2",0x300,&drive,0));request(123);
 if(mode==0 || mode==2 || mode==3 || mode==4){
  pthread_t thread;assert(!pthread_create(&thread,0,worker,0));wait_paused();
  if(mode==0){assert(stops==1 && exists("reply"));cancel();continues++;}
  if(mode==2){
   assert(!exists("reply"));int opened=request_opens;
   errno=37;
   for(int i=0;i<1000;i++)file_media_flush_pending();
   assert(errno==37 && request_opens==opened && busy==1 && flushes==1 && !exists("reply"));
   cancel();request(124);active_seq=123;
  }
  if(mode==3){assert(exists("reply") && !stops);cancel();}
  if(mode==4){assert(exists("reply") && !stops);cancel(); /* Early CONT is not recovery. */}
  release_guest();assert(!pthread_join(thread,0));
  if(mode==4){assert(stops==1);continues++;}
 }else{
  if(mode==1 || (mode>=14 && mode<=21))cancel();
  if(mode==19){
   busy=1;errno=37;
   for(int i=0;i<1000;i++)file_media_flush_pending();
   assert(errno==37 && busy==1 && !request_opens && !flushes && !previous);
   assert(!exists("reply") && !exists("cancelled"));busy=0;
  }
  if(mode==20){
   char path[512];snprintf(path,sizeof path,"%s/sd-flush.request",directory);
   int fd=open(path,O_WRONLY|O_TRUNC);assert(fd>=0);
   assert(write(fd,"123 invalid\n",12)==12);assert(!close(fd));
   for(int i=0;i<1000;i++)file_media_flush_pending();
   request(0);
   for(int i=0;i<1000;i++)file_media_flush_pending();
   assert(!flushes && !previous && !busy && !stops && !exists("reply"));
   request(123);
  }
  if(mode==14 || mode==15)ack_failures=mode==14?1:3;
  if(mode>=16 && mode<=18){
   file_media_flush_cancel_retry();
   assert(!request_opens && !flushes && !ack_attempts && !stops && !continues);
   ack_failures=mode==18?40:1;
  }
  if(mode==12)mounted_media_drive=0;
  if(mode==13){current_pid=4321;errno=37;}
  file_media_flush_pending();
  if(mode==13)assert(errno==37);
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
 assert(exists("cancelled")==!!(mode==0 || mode==1 || mode==2 || mode==3 || mode==4 || mode==11 || mode>=19));
 if(mode==13)assert(!request_opens && !previous && !busy);
 if(mode==0 || mode==4)check_cancelled(123);
 if(exists("reply")){
  char path[512],text[200];snprintf(path,sizeof path,"%s/sd-flush.123.reply",directory);
  int fd=open(path,O_RDONLY);assert(fd>=0);long n=read(fd,text,sizeof text-1);assert(n>0);text[n]=0;close(fd);
  assert(strstr(text,"SD_FSYS_FLUSH seq=123 pid=1234 drive="));
  assert(strstr(text,mode==5?"rc=-9\n":mode==12?"rc=-1021\n":"rc=0\n"));
 }
 int old_flushes=flushes;
 if(mode!=2)for(int i=0;i<1000;i++)file_media_flush_pending();
 assert(flushes==old_flushes);
 assert(console_opens==((mode==12?2:mode==13?0:4)+(mode==2 || mode==13 || mode==19)));
 assert(console_writes==(console_failure==1?0:console_opens));
 assert(console_closes==console_writes);
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
                 "timer_persistent_ENOSPC_log_throttle_then_recovery",
                 "busy_polls_do_not_read_request_or_clear_owner",
                 "invalid_and_duplicate_polls_do_not_emit_stages",
                 "diagnostic_output_failure_preserves_protocol"]
        with tempfile.TemporaryDirectory() as name:
            binary = Path(name) / 'test'
            subprocess.run(['cc', '-x', 'c', '-', str(HERE/'fsys-write-trace.c'), '-I', str(HERE), '-o', str(binary),
                            '-Wall', '-Wextra', '-Werror', '-pthread',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'],
                           input=source, text=True, capture_output=True, check=True)
            scenarios = [(mode, label, 1 if mode == 21 else 0, False)
                         for mode, label in enumerate(modes)]
            scenarios += [(mode, modes[mode], failure, True)
                          for mode in (0, 5, 6, 13, 19) for failure in range(5)]
            for mode, label, failure, null_stdout in scenarios:
                with self.subTest(mode=label, console_failure=failure, stdout_null=null_stdout), tempfile.TemporaryDirectory() as files:
                    completed = subprocess.run([str(binary), str(mode), files, str(failure), str(int(null_stdout))],
                                               capture_output=True, timeout=10)
                    self.assertEqual(completed.returncode, 0, completed.stderr.decode())
                    if null_stdout:
                        self.assertEqual(completed.stdout, b'')
                    console = (Path(files) / 'console').read_text('ascii')
                    # A short console write omits only its last byte, the newline.
                    records = re.split(r'(?=SD_FSYS_FLUSH_STAGE |SD_FSYS_FLUSH_ADMISSION_BLOCKED |'
                                       r'TEST_ORIGINAL_FLUSH |TEST_REPLY_RENAME )', console)
                    lines = []
                    for record in filter(None, records):
                        self.assertEqual(record.endswith('\n'), failure != 3 or record.startswith('TEST_'))
                        lines.append(record.removesuffix('\n'))
                    events = []
                    for line in lines:
                        if line.startswith('SD_FSYS_FLUSH_STAGE '):
                            match = re.fullmatch(
                                r'SD_FSYS_FLUSH_STAGE stage=(\w+) seq=(\d+) pid=1234 tid=5678 '
                                r'drive=(\d+) (\w+)=(-?\d+) errno=(\d+)', line)
                            self.assertIsNotNone(match, line)
                            stage, seq, drive, field, value, error = match.groups()
                            self.assertEqual(int(drive), 0 if mode == 12 else 65)
                            if stage == 'after':
                                self.assertEqual(int(error), 47)  # The original errno survived diagnostics.
                            if stage == 'reply' and mode in (6, 8, 9, 10):
                                self.assertEqual(int(error), 28 if mode == 6 else 5)
                            events.append((stage, int(seq), field, int(value)))
                        elif line.startswith('TEST_ORIGINAL_FLUSH '):
                            match = re.fullmatch(r'TEST_ORIGINAL_FLUSH seq=(\d+) rc=(-?\d+)', line)
                            events.append(('original', int(match[1]), 'rc', int(match[2])))
                        elif line.startswith('TEST_REPLY_RENAME '):
                            seq = int(line.removeprefix('TEST_REPLY_RENAME seq='))
                            events.append(('rename', seq))
                    expected = []
                    sequences = [] if mode == 13 else [123, 124] if mode in (2, 15, 17) else [123]
                    for seq in sequences:
                        if failure not in (1, 2):
                            expected.append(('accepted', seq, 'admitted', 1))
                        if mode != 12:
                            rc = -9 if mode == 5 else 0
                            if failure not in (1, 2):
                                expected.append(('before', seq, 'calling', 1))
                            expected.append(('original', seq, 'rc', rc))
                            if failure not in (1, 2):
                                expected.append(('after', seq, 'rc', rc))
                        stored = int(mode not in (6, 7, 8, 9, 10))
                        if stored:
                            expected.append(('rename', seq))
                        if failure not in (1, 2):
                            expected.append(('reply', seq, 'stored', stored))
                    self.assertEqual(events, expected)
                    blocked = [line for line in lines if line.startswith('SD_FSYS_FLUSH_ADMISSION_BLOCKED ')]
                    if mode in (2, 13, 19) and failure not in (1, 2):
                        pid = 4321 if mode == 13 else 1234
                        self.assertEqual(blocked, [f'SD_FSYS_FLUSH_ADMISSION_BLOCKED pid={pid} tid=5678 '
                                                   f'mounted_owner_pid=1234 busy={0 if mode == 13 else 1}'])
                    else:
                        self.assertEqual(blocked, [])
                    failures = completed.stdout.decode('ascii').splitlines()
                    self.assertTrue(all(line.startswith('SD_FSYS_CANCELLED_FAILED ') for line in failures))
                    if mode in (14, 15, 16, 17, 18):
                        count = 3 if mode == 15 else 10 if mode == 18 else 1
                        self.assertEqual(failures, ['SD_FSYS_CANCELLED_FAILED seq=123 errno=28'] * count)
                    else:
                        self.assertEqual(failures, [])
                    self.assertEqual(len(lines), len(events) + len(blocked))


if __name__ == '__main__':
    unittest.main()
