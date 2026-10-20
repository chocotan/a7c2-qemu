from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class ConfirmInput(unittest.TestCase):
    def test_original_callback_tap_waits_for_observed_error(self):
        source=(HERE/'menu-observe.c').read_text()
        function='static void try_inject_key(void) {'+source.split('static void try_inject_key(void) {',1)[1].split('\nstatic void try_open_set(',1)[0]
        fixture=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#define syscall(...) 101L
static unsigned long appfw_base;
static unsigned int inject_key_done,card_error_rendered,last_input_screen,create_screen_returned=1,create_screen_active,ui_thread_id=101;
static unsigned int auto_last_screen_gen,auto_steps,create_screen_calls;
static unsigned int calls;
static unsigned char events[2][32];
static void record(const char *prefix,const char *text){assert(prefix && text);}
static void callback(int kind,const void *data){assert(!kind && calls<2);memcpy(events[calls++],data,32);}
'''
        checks=r'''
int main(void) {
    appfw_base=(unsigned long)callback-0x17988b4UL;
    setenv("MENU_INJECT_KEY","confirm-pressrelease",1);
    try_inject_key();assert(!calls && !inject_key_done);
    card_error_rendered=1;ui_thread_id=102;
    try_inject_key();assert(!calls && !inject_key_done);
    ui_thread_id=101;try_inject_key();
    assert(calls==2 && inject_key_done && events[0][0]==0xac && events[0][1]==1);
    assert(events[0][8]==1 && !events[1][8]);
    unsigned char expected[32]={0};expected[0]=0xac;expected[1]=1;expected[8]=1;
    assert(!memcmp(events[0],expected,32));expected[8]=0;assert(!memcmp(events[1],expected,32));
    try_inject_key();assert(calls==2);
    inject_key_done=0;calls=0;card_error_rendered=0;setenv("MENU_INJECT_KEY","pressrelease",1);
    try_inject_key();assert(calls==2 && events[0][0]==0xab && events[0][8]==1 && !events[1][8]);
    inject_key_done=0;calls=0;setenv("MENU_INJECT_KEY","invalid",1);
    try_inject_key();assert(!calls);
    inject_key_done=0;setenv("MENU_INJECT_KEY","language-pressrelease",1);
    try_inject_key();assert(!calls && !inject_key_done);
    last_input_screen=0x12d;try_inject_key();assert(calls==2 && events[0][0]==0xac);
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            binary=Path(temporary)/'confirm'
            subprocess.run(['cc','-x','c','-','-o',str(binary),'-Wall','-Wextra','-Werror',
                            '-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie'],
                           input=fixture+function+checks,text=True,capture_output=True,check=True)
            subprocess.run([str(binary)],capture_output=True,check=True,timeout=20)


if __name__=='__main__':unittest.main()
