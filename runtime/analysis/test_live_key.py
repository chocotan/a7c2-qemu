"""Experimental mailbox parser only; normal natural boot uses inject-key --app."""
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class LiveKey(unittest.TestCase):
    def test_mailbox_rejects_invalid_and_replayed_requests(self):
        source = (HERE / 'menu-observe.c').read_text()
        worker = source[source.index('static void *live_key_worker('):source.index('static void start_live_key_worker(')]
        fixture = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static unsigned long long live_key_last_seq;
static unsigned int live_key_code,live_key_status;
static volatile unsigned int live_key_pending,live_key_stop;
static unsigned int iteration,events;
static const char *requests[]={"1ac 2 10\n","99 1 10\n","broken\n","3 1 11\n","30 0 11\n","1ac 0 12\n"};
static int fake_open(const char *path,int flags){assert(!strcmp(path,"/tmp/menu-key.request") && !flags);return 3;}
static long fake_read(int fd,void *data,size_t bytes){assert(fd==3);size_t n=strlen(requests[iteration]);assert(n<=bytes);memcpy(data,requests[iteration],n);return n;}
static int fake_close(int fd){assert(fd==3);return 0;}
static void record(const char *tag,const char *text){assert(tag && text);events++;}
static int fake_usleep(unsigned int usec){
 assert(usec==20000);
 if(iteration==3){assert(live_key_pending && live_key_code==3 && live_key_status==1 && live_key_last_seq==11);live_key_pending=0;}
 else if(iteration==5){assert(live_key_pending && live_key_code==0x1ac && !live_key_status && live_key_last_seq==12);live_key_pending=0;}
 else assert(!live_key_pending);
 if(++iteration==6)live_key_stop=1;
 return 0;
}
#define open fake_open
#define read fake_read
#define close fake_close
#define usleep fake_usleep
'''
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / 'check'
            subprocess.run(['cc', '-x', 'c', '-', '-o', str(binary), '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'],
                           input=fixture + worker + '\nint main(void){setenv("MENU_LIVE_KEY_FILE","/tmp/menu-key.request",1);live_key_worker(0);assert(events==2);}\n',
                           text=True, capture_output=True, check=True)
            subprocess.run([str(binary)], capture_output=True, check=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
