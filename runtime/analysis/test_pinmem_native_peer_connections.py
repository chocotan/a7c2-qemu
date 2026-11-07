"""Native edges8/9 reuse the seven real host providers; no VM/frame claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import re
import subprocess

import pytest

from test_adf_set_input_device import public_adf_input_seed
from test_infrabb_vef_connection import FLAGS, ENV, BB_BACKENDS
from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
BACKENDS = [*BB_BACKENDS, 'pin-buffer-owner', 'pin-buffer-wire', 'pin-format',
            'pin-registry-core', 'adf-device', 'vef-device', 'pinmem-device',
            'pin-connection', 'vef-path-device', 'infraimaging-format',
            'imaging-pin-connection', 'imaging-control-connection',
            'imaging-adf-connection', 'infrabb-vef-format', 'infrabb-vef-connection',
            'infrabb-vef-control-connection', 'vef-pinmem-input-connection',
            'vef-pinmem-control-connection', 'scalar-device', 'scalar-connection',
            'adf-connection', '../dmm-service']
DEFINES = ['-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST',
           '-DFULL_ADF_SET_OUTPUT_TEST', '-DFULL_VEF_TEST',
           '-Wl,--wrap=full_adf_set_input_claim_output',
           '-Wl,--wrap=full_vef_path_snapshot']
CASES = ['normal', 'dynamic-caller', 'uninitialized', 'predecessor-no-ap-free',
         'disabled-or-unrelated', 'bad-wire',
         'live-source-get', 'live-peer-get', 'resource-busy', 'guard-recheck', 'inline-free',
         'send-fail', 'inline-send-fail', 'request-free-fail', 'reply-free-fail',
         'wrong-owner', 'foreign-thread-free', 'recursive', 'recursive-free',
         'queued-fault', 'fork-held', 'in-flight-send-fail', 'in-flight-free-fail',
         'reuse-before-free-return', 'missing-receive-ticket', 'forged-receive-ticket',
         'reuse-unobserved-allocation', 'reuse-unobserved-receive', 'reuse-stale-ticket',
         'cleanup-fail', 'duplicate-event', 'request-mutated',
         *[f'alloc-fail-{n}' for n in range(1, 4)],
         *[f'alloc-short-{n}' for n in range(1, 4)],
         'alloc-alias-1', 'alloc-alias-2', 'alloc-alias-3',
         *[f'event-{n}' for n in range(1, 12)]]


@pytest.fixture(scope='module')
def native_peer_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('pinmem-native-peers')
    for source in ['scalar-connection', 'adf-connection']:
        built = subprocess.run(FLAGS + ['-c', str(MODEL / (source + '.c')),
            '-o', str(directory / (source + '.o'))], capture_output=True,
            text=True, timeout=30)
        assert built.returncode == 0, built.stdout + built.stderr
    binary = directory / 'model'
    built = subprocess.run(FLAGS + DEFINES + [
        *[str(MODEL / (name + '.c')) for name in BACKENDS],
        str(HERE / 'infrabb-registry.c'),
        str(MODEL / 'test-pinmem-native-peer-connections.c'), '-o', str(binary)],
        capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('edge', ['scalar', 'adf'])
def test_native_pinmem_peer_connections(native_peer_binary, public_adf_input_seed,
                                       edge, case):
    if public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    argument = ('adf-' if edge == 'adf' else '') + case
    result = subprocess.run([str(native_peer_binary), argument,
                             str(public_adf_input_seed)], capture_output=True,
                            text=True, timeout=35, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PINMEM_NATIVE_PEER_CONNECTIONS_HOST_TEST_PASS' in result.stdout
    if case.startswith('reuse-'):
        proof = next(line for line in result.stdout.splitlines()
                     if line.startswith('PINMEM_NATIVE_POST_FREE_REUSE '))
        fields = dict(part.split('=', 1) for part in proof.split()[1:])
        assert fields['case'] == case
        if case == 'reuse-unobserved-allocation':
            assert fields['generation_b'] == '0'
        else:
            assert int(fields['generation_b']) > int(fields['generation_a']) > 0
        if case in ['reuse-unobserved-allocation', 'reuse-unobserved-receive']:
            assert fields['ticket_b'] == '0'
        else:
            assert int(fields['ticket_a']) > 0 and int(fields['ticket_b']) > 0
            assert fields['ticket_a'] != fields['ticket_b']
        blocked = case != 'reuse-before-free-return'
        assert all(fields[key] == value for key, value in {
            'A_free': '1', 'B_free': '1', 'foreign_claimed': str(int(blocked)),
            'faults': str(int(blocked)), 'ap_consumed': '1',
            'clean_completion': str(int(not blocked)), 'capture_verified': '0'}.items())
    if case in ['missing-receive-ticket', 'forged-receive-ticket']:
        assert 'PINMEM_NATIVE_BAD_TICKET ' in result.stdout
        assert 'actual_free=0 still_owned=1 capture_verified=0' in result.stdout
    if case in ['normal', 'dynamic-caller', 'inline-free', 'recursive', 'fork-held']:
        prefix = 'FULL_' + edge.upper() + '_CONNECT_'
        tags = ['REQUEST ', 'PEER_REQUEST ', 'PEER_REPLY ', 'EVENT6_ENQUEUED ',
                'EVENT6_CONSUMED ', 'YC_DIRECTION_CHECK ', 'REPLY_QUEUED ',
                'REQUEST_FREE ', 'STATE_READBACK ']
        positions = [result.stdout.index(prefix + tag) for tag in tags]
        assert positions == sorted(positions)
        lines = [line for line in result.stdout.splitlines()
                 if any(line.startswith(prefix + tag) for tag in
                        ['PEER_REQUEST ', 'PEER_REPLY ', 'REPLY_QUEUED '])]
        packets = [bytes.fromhex(re.search(r'raw=([0-9a-f]+)', line)[1])
                   for line in lines]
        assert [len(packet) for packet in packets] == [64, 72, 56]
        source = [0, 2, 1 if edge == 'scalar' else 2, 0x90590818]
        peer = [0, 1, 4 if edge == 'scalar' else 0,
                0x91670464 if edge == 'scalar' else 0x9058003f]
        key = lambda values: b''.join(v.to_bytes(4, 'little') for v in values)
        assert packets[0][32:] == packets[1][32:64] == key(source + peer)
        assert packets[1][64:] == bytes(8)
        assert packets[2][32:] == key(source) + bytes(8)
        assert all(packet[:4] == bytes(4) for packet in packets)
        assert 'parameter_bytes=12 cleared_bytes=12' in result.stdout
        assert 'original_CP_event_pointer_identity_verified=0' in result.stdout
        assert 'original_RTOS_scheduling_verified=0' in result.stdout
    prefix = 'FULL_' + edge.upper() + '_CONNECT_'
    rejected = [line for line in result.stdout.splitlines()
                if line.startswith(prefix + 'RELEASE_REJECT_FAULT ')]
    assert len(rejected) == int(case in ['wrong-owner', 'queued-fault', 'recursive-free'])
    if rejected:
        fields = dict(part.split('=', 1) for part in rejected[0].split()[1:])
        reentrant = case == 'recursive-free'
        assert fields['reason'] == ('release-inflight' if reentrant else 'wrong-destination')
        assert fields['pid'] == fields['owner_pid'] and fields['tid'] == fields['sender']
        assert fields['reply'] == fields['live']
        assert int(fields['destination'], 0) == (int(fields['expected'], 0) ^ int(not reentrant))
        assert fields['inflight'] == str(int(reentrant))
        assert fields['phase'] == '1' and fields['event6_inflight'] == '0'
        assert fields['faults'] == '1' and fields['rc'] == '-1021'
    failed_send = [line for line in result.stdout.splitlines()
                   if line.startswith(prefix + 'SEND_RELEASE_FAULT ')]
    assert len(failed_send) == int(case in ['inline-send-fail', 'in-flight-send-fail', 'in-flight-free-fail'])
    if failed_send:
        fields = dict(part.split('=', 1) for part in failed_send[0].split()[1:])
        assert fields['reason'] == 'send-failed-after-release' and fields['send_rc'] == '-61'
        assert fields['pid'] == fields['owner_pid'] and fields['tid'] == fields['sender']
        assert fields['destination'] == fields['expected']
        assert fields['phase'] == '1' and fields['busy'] == '1' and fields['queued'] == '0'
        assert fields['inflight'] == str(int(case != 'inline-send-fail'))


@pytest.mark.parametrize('mode', ['', '-wrong-owner', '-inflight'])
def test_retired_scalar_address_reused_by_adf(native_peer_binary, public_adf_input_seed, mode):
    if public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    result = subprocess.run([str(native_peer_binary), 'adf-retired-reuse' + mode,
                             str(public_adf_input_seed)], capture_output=True,
                            text=True, timeout=35, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PINMEM_NATIVE_RETIRED_REUSE_SAME_ADDRESS ' in result.stdout
    assert 'PINMEM_NATIVE_PEER_CONNECTIONS_HOST_TEST_PASS' in result.stdout
    final = [re.search(r'pointer=(\S+)', line)[1]
             for line in result.stdout.splitlines()
             if line.startswith(('FULL_SCALAR_CONNECT_REPLY_QUEUED ',
                                 'FULL_ADF_CONNECT_REPLY_QUEUED '))]
    assert len(final) == 2 and final[0] == final[1]
    rejected = [line for line in result.stdout.splitlines()
                if line.startswith('FULL_ADF_CONNECT_RELEASE_REJECT_FAULT ')]
    assert len(rejected) == int(bool(mode))
    if rejected:
        fields = dict(part.split('=', 1) for part in rejected[0].split()[1:])
        assert fields['reason'] == ('wrong-destination' if mode == '-wrong-owner' else 'release-inflight')
        assert fields['inflight'] == str(int(mode == '-inflight'))
        assert fields['reply'] == fields['live'] == final[1]
        assert fields['pid'] == fields['owner_pid'] and fields['tid'] == fields['sender']
        assert fields['phase'] == '1' and fields['faults'] == '1'
    freed = next(line for line in result.stdout.splitlines()
                 if line.startswith('FULL_ADF_CONNECT_NATIVE_REPLY_FREE '))
    assert f'rc=0 faults={int(bool(mode))} ap_consumed=1' in freed


def test_foreign_seventh_reply_free_cannot_admit_eighth(native_peer_binary, public_adf_input_seed):
    test_native_pinmem_peer_connections(native_peer_binary,public_adf_input_seed,
                                       'scalar','predecessor-foreign-thread-free')


@pytest.mark.parametrize('source', ['scalar', 'adf'])
def test_existing_legacy_dispatchers(tmp_path, source):
    binary = tmp_path / source
    files = ['pin-registry-core', 'vef-device', 'pinmem-device', 'scalar-device',
             'adf-device', 'pin-buffer-owner', 'pin-buffer-wire', 'pin-connection',
             'pin-format', 'scalar-connection', 'adf-connection',
             'test-' + source + '-connection']
    # Legacy fixtures predate the native strict formatting; production files
    # and all new tests compile separately without suppressions above.
    built = subprocess.run(FLAGS + ['-Wno-misleading-indentation',
        '-DFULL_VEF_TEST', '-DPIN_CONTROL_TEST', '-DFULL_PIN_CONNECTION_TEST',
        *[str(MODEL / (name + '.c')) for name in files], '-o', str(binary)],
        capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True,
                            timeout=20, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert ('SECOND_EDGE_' if source == 'scalar' else 'THIRD_EDGE_') in result.stdout


def test_actual_peer_allocation_and_receive_boundaries(tmp_path):
    """Compile actual wrapper fragments later; this draft worker never runs it."""
    source = (HERE / 'menu-observe.c').read_text()
    ticket = next(line for line in source.splitlines()
                  if line.startswith('static _Thread_local struct') and 'functional_cp_parameter_bank_ticket' in line)
    receive = source[source.index('static void native_pin_peer_received('):
                     source.index('/* The shipped OSAL exports this low-level receive')]
    allocate = function(source, 'native_pin_peer_allocated')
    low_start = source.index('int u_osal_rcv_msg_tmo(')
    low = source[low_start:source.index('int osal_rcv_msg_tmo(', low_start)]
    public_start = source.index('int osal_rcv_msg_tmo(')
    outer_start = source.index('    unsigned int outer=native_receive_depth++;', public_start)
    outer = source[outer_start:source.index('\n    if (!result', outer_start)]
    allocation_start = source.index(
        '    int result=real_allocate_msg(id, message, size, count),saved_errno=',
        source.index('int osal_valloc_msg_wait('))
    allocation = source[allocation_start:source.index('\n}', allocation_start)]
    fixture = tmp_path / 'actual-boundaries.c'
    fixture.write_text(r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
#define syscall(...) 29L
static unsigned int pinmem_peer_connections_used=1,allocations[3],receives[3];
static unsigned int hdmi,cp,actual_allocations,actual_receives,sdk;
static void native_movie_format_allocated(unsigned int id,void **p,int rc,unsigned int count){
 (void)id;(void)p;(void)rc;(void)count;
}
static void native_crank_allocated(unsigned int id,void **p,int rc,unsigned int count){
 (void)id;(void)p;(void)rc;(void)count;
}
static _Thread_local unsigned int native_receive_depth;
static int slot,result_code;
static void record(const char *tag,const char *text){assert(tag && text);errno=EIO;}
#define OBSERVERS(name,index) \
static unsigned long long name##_observe_allocate(unsigned int id,void *p){assert(id==16 && p==&slot);return ++allocations[index];} \
static unsigned long long name##_observe_receive(unsigned int id,void *p){assert(id==16 && p==&slot);return ++receives[index];}
OBSERVERS(full_scalar_connection,0)
OBSERVERS(full_adf_connection,1)
OBSERVERS(full_pinmem_drawinfo_connection,2)
static void native_hdmi_video_received(unsigned int id,void **p,int rc){assert(id==16 && p);(void)rc;hdmi++;}
static void native_cp_state_received(unsigned int id,void **p,int rc){assert(id==16 && p);(void)rc;cp++;}
static int fake_receive(unsigned int id,void **p,long timeout){assert(id==16 && p && timeout==27);actual_receives++;*p=&slot;errno=ERANGE;return result_code;}
static int fake_allocate(unsigned int id,void **p,unsigned int bytes,unsigned int count){assert(id==16 && p && bytes==56 && count);actual_allocations++;*p=&slot;errno=ERANGE;return result_code;}
static void native_face_sdk_observation(unsigned int op,unsigned int id,void *p,unsigned int bytes,int rc,void *caller){assert(op==1 && id==16 && bytes==56 && caller);(void)p;(void)rc;sdk++;errno=EIO;}
static int (*real_u_rcv_msg_tmo)(unsigned int,void **,long)=fake_receive;
static int (*real_rcv_msg_tmo)(unsigned int,void **,long);
static int (*real_allocate_msg)(unsigned int,void **,unsigned int,unsigned int)=fake_allocate;
''' + ticket + '\n' + receive + allocate + low + '''
static int nested_public(unsigned int id,void **p,long timeout){return u_osal_rcv_msg_tmo(id,p,timeout);}
static int observed_public(unsigned int id,void **message,long timeout){
''' + outer + '''
    return result;
}
static int observed_allocate(unsigned int id,void **message,unsigned int size,unsigned int count){
''' + allocation + r'''
}
int main(void){
    real_rcv_msg_tmo=nested_public;void *p=0;
    functional_cp_parameter_bank_ticket.pointer=&slot;
    functional_cp_parameter_bank_ticket.destination=16;
    functional_cp_parameter_bank_ticket.transaction=UINT64_C(0x100000003);
    errno=EINTR;assert(!observed_allocate(16,&p,56,1) && errno==ERANGE);
    assert(!functional_cp_parameter_bank_ticket.pointer && !functional_cp_parameter_bank_ticket.destination && !functional_cp_parameter_bank_ticket.transaction);
    for(unsigned int i=0;i<3;i++)assert(allocations[i]==1);
    functional_cp_parameter_bank_ticket.pointer=&slot;
    functional_cp_parameter_bank_ticket.destination=16;
    functional_cp_parameter_bank_ticket.transaction=UINT64_C(0x100000003);
    result_code=-5;assert(observed_allocate(16,&p,56,1)==-5 && errno==ERANGE);
    result_code=0;assert(!observed_allocate(16,&p,56,2) && errno==ERANGE);
    native_pin_peer_allocated(16,0,0,1);p=0;native_pin_peer_allocated(16,&p,0,1);
    assert(functional_cp_parameter_bank_ticket.pointer==&slot && functional_cp_parameter_bank_ticket.destination==16 && functional_cp_parameter_bank_ticket.transaction==UINT64_C(0x100000003));
    for(unsigned int i=0;i<3;i++)assert(allocations[i]==1);
    assert(actual_allocations==3 && sdk==3);
    assert(!observed_public(16,&p,27) && errno==ERANGE && !native_receive_depth);
    for(unsigned int i=0;i<3;i++)assert(receives[i]==1);
    assert(hdmi==1 && cp==1 && actual_receives==1);
    assert(!u_osal_rcv_msg_tmo(16,&p,27) && errno==ERANGE);
    for(unsigned int i=0;i<3;i++)assert(receives[i]==2);
    result_code=-7;assert(observed_public(16,&p,27)==-7 && errno==ERANGE);
    result_code=0;pinmem_peer_connections_used=0;
    assert(!observed_public(16,&p,27) && !observed_allocate(16,&p,56,1));
    assert(!functional_cp_parameter_bank_ticket.pointer && !functional_cp_parameter_bank_ticket.destination && !functional_cp_parameter_bank_ticket.transaction);
    pinmem_peer_connections_used=1;native_pin_peer_received(16,0,0);p=0;native_pin_peer_received(16,&p,0);
    for(unsigned int i=0;i<3;i++)assert(receives[i]==2 && allocations[i]==1);
    assert(!native_receive_depth && actual_receives==4 && actual_allocations==4);
    puts("PIN_PEER_ACTUAL_BOUNDARIES_PASS");return 0;
}
''')
    binary = tmp_path / 'actual-boundaries'
    built = subprocess.run(FLAGS + [str(fixture), '-o', str(binary)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True,
                            timeout=15, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PIN_PEER_ACTUAL_BOUNDARIES_PASS' in result.stdout


def test_actual_peer_free_origin_keeps_route_and_errno(tmp_path):
    source = (HERE / 'menu-observe.c').read_text()
    start = source.index('    if (__atomic_load_n(&pinmem_peer_connections_used,',
                         source.index('int osal_free_msg('))
    end = source.index('    if (__atomic_load_n(&adf_hdmi_audio_connection_used,', start)
    branch = source[start:end]
    fixture = tmp_path / 'actual-free-origin.c'
    fixture.write_text(r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#define syscall(...) 29L
static unsigned int pinmem_peer_connections_used=1,calls[3],records;
static int chosen,returned;
static int storage;
static int original_free(unsigned int id,void *p){assert(id==16 && p==&storage);return -7;}
static int (*real_free_msg)(unsigned int,void *)=original_free;
static void record(const char *tag,const char *text){
    assert(!strcmp(tag,"PIN_PEER_NATIVE_FREE_ORIGIN "));
    assert(strstr(text,"pointer=0x") && strstr(text,"destination=0x10 caller=0x"));
    assert(strstr(text,"caller_module_identity_verified=0 capture_verified=0"));
    records++;errno=EIO;
}
static int release_at(unsigned int which,unsigned int id,void *p,int (*free_fn)(unsigned int,void *),void (*logger)(const char *,const char *),int *rc){
    assert(id==16 && p==&storage && free_fn==original_free && logger==record);
    calls[which]++;
    if((int)which!=chosen)return 0;
    *rc=returned;errno=ERANGE;return 1;
}
#define RELEASE(name,index) \
static int name(unsigned int id,void *p,int (*f)(unsigned int,void *),void (*r)(const char *,const char *),int *rc){return release_at(index,id,p,f,r,rc);}
RELEASE(full_scalar_connection_release,0)
RELEASE(full_adf_connection_release,1)
RELEASE(full_pinmem_drawinfo_connection_release,2)
static __attribute__((noinline)) int actual_branch(unsigned int id,void *message){
    int vdf_result=-999;
''' + branch + r'''
    return 777;
}
int main(void){
    for(chosen=0;chosen<3;chosen++)for(unsigned int failure=0;failure<2;failure++){
        memset(calls,0,sizeof calls);records=0;returned=failure?-1021:0;
        assert(actual_branch(16,&storage)==returned && errno==ERANGE && records==1);
        for(unsigned int i=0;i<3;i++)assert(calls[i]==(unsigned int)((int)i<=chosen));
    }
    memset(calls,0,sizeof calls);records=0;chosen=3;errno=EINTR;
    assert(actual_branch(16,&storage)==777 && errno==EINTR && !records);
    for(unsigned int i=0;i<3;i++)assert(calls[i]==1);
    pinmem_peer_connections_used=0;memset(calls,0,sizeof calls);errno=EINVAL;
    assert(actual_branch(16,&storage)==777 && errno==EINVAL && !records);
    for(unsigned int i=0;i<3;i++)assert(!calls[i]);
    puts("PIN_PEER_ACTUAL_FREE_ORIGIN_PASS");return 0;
}
''')
    binary = tmp_path / 'actual-free-origin'
    built = subprocess.run(FLAGS + [str(fixture), '-o', str(binary)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True,
                            timeout=15, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PIN_PEER_ACTUAL_FREE_ORIGIN_PASS' in result.stdout

