"""Execute the actual central-CP audit before its first transport return."""
from pathlib import Path
import re
import subprocess

import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope='module')
def audit_binary(tmp_path_factory):
    observer = (HERE / 'menu-observe.c').read_text()
    start = observer.index('static void audit_cp_background_input(')
    end = observer.index('/* Bisect: the osal_snd_sync_direct', start)
    assert '#if 0\nint osal_snd_sync_direct(' in observer
    entries = []
    for name, kind in (('osal_snd_msg', 'async'), ('osal_snd_sync_msg', 'sync')):
        match = re.search(r'^int ' + name + r'\(unsigned int id, void \*message\) \{\n    ([^\n]+)', observer, re.M)
        assert match and match[1] == f'audit_cp_background_input(id,message,"{kind}",__builtin_return_address(0));'
        entries.append(match[0] + '\n    return 0;\n}\n')
    assert start < observer.index('full_vef_resource_send_enter(', observer.index('int osal_snd_msg('))
    path = tmp_path_factory.mktemp('central-cp-audit')
    source = path / 'audit.c'
    source.write_text(r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#define NATIVE_CP_BACKGROUND_SID 0x90030001u
static unsigned char payload[5000],before[5000];
static unsigned int length,size_calls,source_calls,history_calls;
static int enabled=1,cp302c_no_transition_enabled;
static int native_cp302c_observe_input(unsigned int id,const void *p,unsigned int source,unsigned int bytes,const char *entry){
 assert(id==NATIVE_CP_BACKGROUND_SID && p==payload && source==0x80020002 && bytes==length && entry);
 history_calls++;errno=EDOM;return -1021;
}
static unsigned int fixture_size(void *p){assert(p==payload);size_calls++;errno=EDOM;return length;}
static unsigned int fixture_source(void *p){assert(p==payload);source_calls++;errno=ERANGE;return 0x80020002u;}
static unsigned int (*real_msg_size)(void *)=fixture_size,(*real_get_source)(void *)=fixture_source;
static const char *fixture_getenv(const char *name){assert(!strcmp(name,"MENU_CP_BACKGROUND"));return enabled?"virtual-mode3-cold-v1":NULL;}
static int same_name(const char *a,const char *b){return a && b && !strcmp(a,b);}
static long fixture_syscall(long n){assert(n==178);return 77;}
static void record(const char *tag,const char *text){printf("%s%s\n",tag,text);errno=EIO;}
#define getenv fixture_getenv
#define syscall fixture_syscall
''' + observer[start:end] + '\n'.join(entries) + r'''
static const char *entry_kind;
static void audit(unsigned int id,void *message){
 if(!strcmp(entry_kind,"async"))osal_snd_msg(id,message);
 else {assert(!strcmp(entry_kind,"sync"));osal_snd_sync_msg(id,message);}
}
int main(int argc,char **argv){
 assert(argc==5);entry_kind=argv[4];char *end;unsigned long n=strtoul(argv[2],&end,10);assert(!*end && n<=sizeof payload);length=(unsigned int)n;
 unsigned int destination=(unsigned int)strtoul(argv[3],&end,0);assert(!*end);void *message=payload;
 if(!strcmp(argv[1],"history"))cp302c_no_transition_enabled=1;
 else if(!strcmp(argv[1],"off"))enabled=0;
 else if(!strcmp(argv[1],"null"))message=NULL;
 else if(!strcmp(argv[1],"missing-size"))real_msg_size=NULL;
 else if(!strcmp(argv[1],"missing-source"))real_get_source=NULL;
 else assert(!strcmp(argv[1],"normal"));
 for(unsigned int i=0;i<sizeof payload;i++)payload[i]=(unsigned char)(i*29+7);
 if(length==16 && strcmp(entry_kind,"async")){payload[0]=5;payload[1]=0;payload[2]=0x3d;payload[3]=0x40;}
 memcpy(before,payload,sizeof before);errno=EINTR;audit(destination,message);assert(errno==EINTR);audit(destination,message);assert(errno==EINTR);
 assert(!memcmp(before,payload,sizeof payload));assert(history_calls==(cp302c_no_transition_enabled?2u:0u));
 printf("CALLS size=%u source=%u\n",size_calls,source_calls);return 0;
}
''')
    binary = path / 'audit'
    result = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                             '-fsanitize=address,undefined', '-fno-pie', '-no-pie', str(source), '-o', str(binary)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


def execute(binary, mode, size, destination=0x90030001, entry='async'):
    result = subprocess.run([str(binary), mode, str(size), hex(destination), entry], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    headers, bodies, calls = [], [], None
    for line in result.stdout.splitlines():
        tag, *parts = line.split()
        record = dict(item.split('=', 1) for item in parts)
        if tag == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT':
            headers.append(record)
        elif tag == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES':
            bodies.append(record)
        elif tag == 'CALLS':
            calls = record
    return headers, bodies, calls


@pytest.mark.parametrize('size', [0, 12, 24, 64, 184, 4096])
def test_original_long_and_short_inputs_are_fully_reconstructed(audit_binary, size):
    headers, bodies, calls = execute(audit_binary, 'normal', size)
    assert calls == {'size': '2', 'source': '2'}
    assert [r['sequence'] for r in headers] == ['1', '2']
    for head in headers:
        assert head['complete'] == head['bytes_complete'] == head['source_known'] == head['size_known'] == '1'
        assert head['source'] == '0x80020002' and head['destination'] == '0x90030001'
        assert head['consumed'] == head['state_verified'] == head['capture_verified'] == '0'
        parts = [r for r in bodies if r['sequence'] == head['sequence']]
        data = bytes.fromhex(''.join(r['raw'] for r in parts))
        assert data == bytes((i*29+7)&255 for i in range(size))
        assert [int(r['offset']) for r in parts] == list(range(0, size, 128))
        assert all(0 < int(r['bytes']) <= 128 for r in parts)


@pytest.mark.parametrize('entry', ['sync'])
@pytest.mark.parametrize('size', [16, 184])
def test_sync_release_and_long_input_are_observed_before_early_returns(audit_binary, entry, size):
    destination = 0x90040193 if size == 16 else 0x90030001
    heads, bodies, calls = execute(audit_binary, 'normal', size, destination, entry=entry)
    assert calls == {'size': '2', 'source': '2'}
    assert [r['sequence'] for r in heads] == ['1', '2']
    for head in heads:
        assert head['entry'] == entry and head['complete'] == '1'
        assert head['destination'] == hex(destination)
        assert head['consumed'] == head['state_verified'] == '0'
        parts = [r for r in bodies if r['sequence'] == head['sequence']]
        actual = bytes.fromhex(''.join(r['raw'] for r in parts))
        expected = bytearray((i*29+7)&255 for i in range(size))
        if size == 16:
            expected[:4] = bytes.fromhex('05003d40')
        assert actual == bytes(expected)


@pytest.mark.parametrize('mode,size,complete,size_known,source_known,bytes_complete', [
    ('normal', 4097, '0', '1', '1', '0'), ('null', 184, '0', '0', '0', '0'),
    ('missing-size', 184, '0', '0', '1', '0'), ('missing-source', 184, '0', '1', '0', '1'),
])
def test_incomplete_history_is_explicit(audit_binary, mode, size, complete, size_known, source_known, bytes_complete):
    heads, bodies, _ = execute(audit_binary, mode, size)
    for head in heads:
        assert (head['complete'], head['size_known'], head['source_known'], head['bytes_complete']) == (complete, size_known, source_known, bytes_complete)
    assert bool(bodies) is (bytes_complete == '1')


@pytest.mark.parametrize('entry', ['async', 'sync'])
def test_history_observer_gets_original_complete_input_without_transport_effect(audit_binary, entry):
    heads, bodies, calls = execute(audit_binary, 'history', 184, entry=entry)
    assert calls == {'size':'2', 'source':'2'} and len(heads) == 2 and len(bodies) == 4
    assert all(head['entry'] == entry and head['consumed'] == head['state_verified'] == '0' for head in heads)


@pytest.mark.parametrize('mode,destination', [('off', 0x90030001), ('normal', 0x90030002)])
def test_default_off_and_foreign_endpoints_do_not_read(audit_binary, mode, destination):
    heads, bodies, calls = execute(audit_binary, mode, 184, destination)
    assert not heads and not bodies and calls == {'size': '0', 'source': '0'}
