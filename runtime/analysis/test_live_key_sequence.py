from pathlib import Path
import subprocess
import tempfile
import unittest

BASE = Path(__file__).resolve().parent


class SequenceWidth(unittest.TestCase):
    def test_original_worker_keeps_64bit_sequence_and_pending_event(self):
        source = (BASE / 'menu-observe.c').read_text()
        worker = source[source.index('static void *live_key_worker('):
                        source.index('static void start_live_key_worker(')]
        fixture = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
static unsigned long long live_key_last_seq;
static unsigned int live_key_code,live_key_status;
static volatile unsigned int live_key_pending,live_key_stop;
static unsigned int iteration,events;
static const char *lines[]={"30 1 4294967295", "30 0 4294967296", "3 1 4294967297", "3 0 4294967298"};
static char *fake_getenv(const char *s){(void)s;return "/tmp/menu-key.request";}
static int fake_open(const char *p,int flags){assert(!strcmp(p,"/tmp/menu-key.request") && !flags);return 7;}
static long fake_read(int fd,char *p,unsigned long n){assert(fd==7 && n>40);strcpy(p,lines[iteration]);return strlen(p);}
static int fake_close(int fd){assert(fd==7);return 0;}
static int fake_getpid(void){return 9;}
static void record(const char *tag,const char *text){assert(!strcmp(tag,"KEY_INJECT ") && strstr(text,"queued pid=9"));events++;}
static int fake_sleep(unsigned int n){
 assert(n==20000);
 if(iteration==0){assert(live_key_pending && live_key_last_seq==4294967295ULL);}
 if(iteration==1){assert(live_key_status==1 && live_key_last_seq==4294967295ULL && events==1);live_key_pending=0;}
 if(iteration==2){assert(live_key_pending && live_key_last_seq==4294967297ULL && live_key_code==3);live_key_pending=0;}
 if(iteration==3){assert(live_key_last_seq==4294967298ULL && !live_key_status);live_key_stop=1;}
 iteration++;return 0;
}
#define getenv fake_getenv
#define open fake_open
#define read fake_read
#define close fake_close
#define getpid fake_getpid
#define usleep fake_sleep
'''
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'sequence'
            compiled = subprocess.run(['cc', '-x', 'c', '-', '-Wall', '-Wextra', '-Werror',
                                       '-fsanitize=address,undefined', '-no-pie', '-o', str(binary)],
                                      input=fixture + worker + '\nint main(void){live_key_worker(0);assert(events==3);}\n',
                                      capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
