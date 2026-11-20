from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('cc'), reason='Host C compiler required')
def test_bt_diagnostic_hook_and_map_boundaries(tmp_path):
    text = (Path(__file__).parent/'menu-observe.c').read_text()
    hook = text[text.index('void observe_bt_error_place(void *self,'):text.index('/* appFw reaches uxengine_init2')]
    start = text.index('static int bt_map_line_matches(')
    mapper = text[start:text.index('static void patch_bt_null_load(', start)]
    source = tmp_path/'bt.c'
    source.write_text(r'''#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#define syscall(...) (99L)
static int forwarded;
static void original(void *self,unsigned short group,unsigned int line) {
    (void)self; assert(group==3 && line==7); forwarded++;
}
static void (*real_bt_error_place)(void *,unsigned short,unsigned int)=original;
static void *lookup(void *h,const char *s) {(void)h;(void)s;return NULL;}
static void *(*real_dlsym)(void *,const char *)=lookup;
static int (*real_dladdr)(const void *, Dl_info *)=NULL;
static int same_name(const char *a,const char *b) {return a && !strcmp(a,b);}
static void record(const char *tag,const char *message) {(void)tag;(void)message;}
static void patch_bt_null_load(void) {}
''' + hook + '\n' + mapper + r'''
int main(void) {
    assert(bt_patch_enter()); assert(!bt_patch_enter()); bt_patch_leave();
    assert(bt_patch_enter()); bt_patch_leave();
    unsetenv("MENU_VIRTUAL_UPM_PROFILE"); unsetenv("MENU_OBSERVE_SELFTEST");
    observe_bt_error_place(NULL,3,7); assert(forwarded==1);
    setenv("MENU_VIRTUAL_UPM_PROFILE","diagnostic-v1",1);
    observe_bt_error_place(NULL,3,7); assert(forwarded==1);
    setenv("MENU_OBSERVE_SELFTEST","1",1);
    observe_bt_error_place(NULL,3,7); assert(forwarded==2);
    unsetenv("MENU_OBSERVE_SELFTEST"); real_bt_error_place=NULL;
    observe_bt_error_place((void *)1,3,7);
    unsetenv("MENU_VIRTUAL_UPM_PROFILE");
    pid_t child=fork(); assert(child>=0);
    if(!child){struct rlimit limit={0,0};assert(!setrlimit(RLIMIT_CORE,&limit));
               observe_bt_error_place((void *)1,3,7);_exit(0);}
    int status; assert(waitpid(child,&status,0)==child && WIFSIGNALED(status));
    const char *maps="1000-2000 r-xp 0000 00:00 0 /usr/lib/other.so\n"
                     "2000-5000 r-xp 0000 00:00 0 /usr/lib/libBTUtils.so\n";
    const char *next=strchr(maps,'\n'); assert(next);
    assert(!bt_map_line_matches(maps,(size_t)(next-maps)));
    const char *bt=next+1; next=strchr(bt,'\n'); assert(next);
    assert(bt_map_line_matches(bt,(size_t)(next-bt)));
    const char *wrong="2000-5000 r-xp 0000 00:00 0 /tmp/libBTUtils.so";
    assert(!bt_map_line_matches(wrong,strlen(wrong)));
    const char *deleted="2000-5000 r-xp 0000 00:00 0 /usr/lib/libBTUtils.so (deleted)";
    assert(!bt_map_line_matches(deleted,strlen(deleted)));
    return 0;
}
''')
    binary = tmp_path/'bt'
    result = subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],
                            capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    subprocess.run([str(binary)],check=True,timeout=10)


def test_assert_observer_does_not_walk_untrusted_stack():
    text = (Path(__file__).parent/'menu-observe.c').read_text()
    body = text[text.index('void __assert_fail('):text.index('/* date_time_add_seconds')]
    assert '__builtin_return_address(0)' in body
    assert '__builtin_frame_address' not in body
    probe = text[text.index('void capture_assert_call('):text.index('__asm__(', text.index('void capture_assert_call('))]
    assert 'format_string_at' not in probe and '*(unsigned long *)' not in probe


@pytest.mark.skipif(not shutil.which('cc'), reason='Host C compiler required')
def test_upm_diagnostic_match_rejects_unknown_and_malformed_messages(tmp_path):
    text = (Path(__file__).parent / 'menu-observe.c').read_text()
    start = text.index('static int upm_diagnostic_match(')
    end = text.index('static int upm_diagnostic_enabled(', start)
    enabled_start = text.index('static int upm_diagnostic_enabled(', end)
    enabled_end = text.index('int osal_snd_sync_msg(', enabled_start)
    source = tmp_path / 'upm.c'
    source.write_text('''#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static int same_name(const char *a, const char *b) { return a && !strcmp(a, b); }
''' + text[start:end] + text[enabled_start:enabled_end] + '''
int main(void) {
    unsetenv("MENU_VIRTUAL_UPM_PROFILE");
    unsetenv("MENU_OBSERVE_SELFTEST");
    assert(!upm_diagnostic_enabled());
    setenv("MENU_VIRTUAL_UPM_PROFILE", "wrong", 1);
    assert(!upm_diagnostic_enabled());
    setenv("MENU_VIRTUAL_UPM_PROFILE", "diagnostic-v1", 1);
    assert(upm_diagnostic_enabled());
    setenv("MENU_OBSERVE_SELFTEST", "1", 1);
    assert(!upm_diagnostic_enabled());
    unsigned char info[40] = {0x11, 0x01, 0x92, 0x00};
    unsigned char battery[8] = {0x12, 0x01, 0x92, 0x00};
    assert(upm_diagnostic_match(0x80924127u, info, 40, 1));
    assert(!upm_diagnostic_match(0x80924127u, info, 8, 1));
    assert(!upm_diagnostic_match(0x80924127u, 0, 40, 1));
    assert(!upm_diagnostic_match(0x80924126u, info, 40, 1));
    assert(!upm_diagnostic_match(0x80924127u, info, 40, 0));
    info[0] = 0xff;
    assert(!upm_diagnostic_match(0x80924127u, info, 40, 1));
    assert(upm_diagnostic_match(0x809208d0u, battery, 8, 0));
    assert(!upm_diagnostic_match(0x809208d0u, battery, 8, 1));
    return 0;
}
''')
    binary = tmp_path / 'upm'
    result = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                             str(source), '-o', str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    subprocess.run([str(binary)], check=True, timeout=10)
