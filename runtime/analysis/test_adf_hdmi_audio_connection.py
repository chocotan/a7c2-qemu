"""Thirteenth connection, after the real first ten; finite shared HDMI byte only."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import hashlib
import re
import subprocess

import pytest

from test_adf_set_input_device import public_adf_input_seed
from test_infrabb_vef_connection import FLAGS, ENV, BB_BACKENDS
from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
EARLY = ['disabled', 'malformed', 'uninitialized', 'fork', 'missing-io', 'no-prior']
CASES = ['normal', 'dynamic-caller', 'inline-free', 'video-preserved',
         'early-then-ready', 'no-ten', 'ten-not-freed', 'live-get', 'guard-busy',
         'duplicate', 'alloc-1', 'alloc-2', 'alloc-3', 'size-alias',
         'request-alias', 'answer-alias', 'peer-status', 'peer-key', 'peer-sid',
         'request-mutated', 'marker-readback', 'request-free-fail', 'cleanup-fail',
         'send-fail', 'inline-send-fail', 'inflight-send-fail', 'inflight-free-fail',
         'wrong-owner', 'wrong-tid-free', 'reply-free-fail', 'fork-held',
         'recursive-free', 'guard-release-fault']


@pytest.fixture(scope='module')
def hdmi_marker_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp('hdmi-audio-marker') / 'model'
    build = subprocess.run(FLAGS + ['-DFULL_HDMI_TEST',
        str(MODEL / 'hdmi-device.c'), str(MODEL / 'test-hdmi.c'),
        '-o', str(binary)], capture_output=True, text=True, timeout=30)
    assert build.returncode == 0, build.stdout + build.stderr
    return binary


def test_same_hdmi_owner_connected_one_preserves_configuration(hdmi_marker_binary):
    result = subprocess.run([str(hdmi_marker_binary)], capture_output=True,
                            text=True, env=ENV, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'HDMI_SHARED_AUDIO_CONNECTED_ONE_OLD_UNKNOWN_CONFIG_PRESERVED_PASS' in result.stdout
    assert 'HDMI_FUNCTIONAL_SIGNAL_MODE_NATIVE102_12B_READBACK_ROLLBACK_STRICT_PASS' in result.stdout


@pytest.fixture(scope='module')
def hdmi_audio_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('adf-hdmi-audio-connection')
    binary = directory / 'model'
    production = subprocess.run(FLAGS + ['-c',
        str(MODEL / 'adf-hdmi-audio-connection.c'),
        '-o', str(directory / 'production.o')], capture_output=True,
        text=True, timeout=30)
    assert production.returncode == 0, production.stdout + production.stderr
    backends = [*BB_BACKENDS, 'pin-buffer-owner', 'pin-buffer-wire', 'pin-format',
                'pin-registry-core', 'adf-device', 'vef-device', 'pinmem-device',
                'scalar-device', 'pin-connection', 'vef-path-device',
                'infraimaging-format', 'imaging-pin-connection',
                'imaging-control-connection', 'imaging-adf-connection',
                'infrabb-vef-format', 'infrabb-vef-connection',
                'infrabb-vef-control-connection', 'vef-pinmem-input-connection',
                'vef-pinmem-control-connection', 'scalar-connection',
                'adf-connection', 'pinmem-drawinfo-connection',
                'hdmi-pin-device', 'hdmi-device', 'adf-hdmi-audio-connection', '../dmm-service']
    built = subprocess.run(FLAGS + [
        '-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST',
        '-DFULL_ADF_SET_OUTPUT_TEST', '-DFULL_VEF_TEST', '-DFULL_HDMI_TEST',
        '-Wl,--wrap=full_adf_set_input_claim_output',
        '-Wl,--wrap=full_vef_path_snapshot', '-Wl,--wrap=full_hdmi_snapshot',
        *[str(MODEL / (name + '.c')) for name in backends],
        str(HERE / 'infrabb-registry.c'),
        str(MODEL / 'test-adf-hdmi-audio-connection.c'), '-o', str(binary)],
        capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', EARLY + CASES)
def test_finite_audio_connection_after_real_ten(hdmi_audio_binary,
                                               public_adf_input_seed,
                                               tmp_path, case):
    if case not in EARLY and public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    seed = public_adf_input_seed if case not in EARLY else tmp_path / 'absent.bin'
    result = subprocess.run([str(hdmi_audio_binary), case, str(seed)],
                            capture_output=True, text=True, env=ENV, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ADF_HDMI_AUDIO_CONNECTION_HOST_TEST_PASS' in result.stdout
    if case in ['normal', 'dynamic-caller', 'inline-free', 'video-preserved',
                'early-then-ready', 'duplicate', 'fork-held']:
        prefix = 'FULL_ADF_HDMI_AUDIO_CONNECT_'
        tags = ['REQUEST ', 'PEER_REQUEST ', 'PEER_REPLY ',
                'HDMI_MARKER_READBACK ', 'SOURCE_COMPLETED ', 'REPLY_QUEUED ',
                'COMMIT ']
        positions = [result.stdout.index(prefix + tag) for tag in tags]
        assert positions == sorted(positions)
        for tag in tags + ['REPLY_FREE ']:
            assert result.stdout.count(prefix + tag) == 1
        packets = [bytes.fromhex(re.search(r'raw=([0-9a-f]+)', line)[1])
                   for line in result.stdout.splitlines()
                   if any(line.startswith(prefix + tag) for tag in
                          ['PEER_REQUEST ', 'PEER_REPLY ', 'REPLY_QUEUED '])]
        assert [len(p) for p in packets] == [64, 72, 56]
        assert [int.from_bytes(p[26:28], 'little') for p in packets] == [
            0x100, 0x8100, 0x8001]
        key = b''.join(n.to_bytes(4, 'little') for n in
                       [5, 2, 0, 0x9058003f, 5, 1, 0, 0x909a015a])
        assert packets[0][32:64] == packets[1][32:64] == key
        assert packets[1][64:72] == bytes(8)
        assert packets[2][32:56] == key[:16] + bytes(8)
        assert 'FIRST_TEN_PLUS_EDGE13_ELEVEN_CONNECTIONS' in result.stdout
        assert 'no_claim_for_edges11_12=1' in result.stdout
        assert 'state_identity_known=0' in result.stdout
        assert prefix + 'DMM_REQUEST ' not in result.stdout
        assert prefix + 'EVENT6_' not in result.stdout
        assert prefix + 'EVENT8_' not in result.stdout


def test_public_cp_source_windows():
    cp = HERE.parents[5] / 'analysis/system/cpapp-b.bin'
    if not cp.exists():
        pytest.skip('pinned public CP original unavailable')
    data = cp.read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
    for offset, count, expected in [
        (0x62298e, 94, '635f5ef8cf6a86916f20e6e2061316c3b52075f8bc116f9aa6e3fab2c57190fd'),
        (0x1295a2, 102, '7cd0708300cc1d448e22a003a3ade01b30c8f67c0f33ab8de5d2778d11017ea3'),
        (0x623a74, 20, 'c9fc7496ac6005ef4a615a4a7500dee10d6706311a93768c7e8acfff4706cb57'),
        (0x8f7e0, 20, '12800ed9c2c52e807860a1a6f51282342d939ee1eaea95c28091ba296ec27959'),
    ]:
        assert hashlib.sha256(data[offset:offset + count]).hexdigest() == expected


@pytest.fixture(scope='module')
def hdmi_signal_main_binary(tmp_path_factory):
    sent = function((HERE / 'menu-observe.c').read_text(), 'osal_snd_msg')
    start = sent.index('    if(functional_camera_enabled && id==FULL_HDMI_CP && message && real_msg_size')
    stop = sent.index('    if(id==FULL_HDMI_CP && pinmem_hdmi_video_connection_enabled)', start)
    fragment = sent[start:stop]
    code = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include "device-models/hdmi-device.h"
static int functional_camera_enabled=1,dispatch_calls,dispatch_rc,handled=1;
static int pinmem_hdmi_video_connection_enabled=1,predecessors_ready=1,readiness_calls;
static int cp302c_no_transition_predecessors_ready(void){readiness_calls++;return predecessors_ready;}
static unsigned int hdmi_config_used,request_bytes=12;
static unsigned char wire[16]={0,0x25,2,1,12,0,1,0,0,0,0,0};
static unsigned int request_size(void *p){assert(p==wire);return request_bytes;}
static unsigned int (*real_msg_size)(void *)=request_size;
static unsigned int real_get_source(void *p){assert(p==wire);return 0x81cf61c7;}
static int real_allocate_msg(unsigned int id,void **p,unsigned int bytes,unsigned int wait){(void)id;(void)p;(void)bytes;(void)wait;assert(0);return -1;}
static int real_free_msg(unsigned int id,void *p){(void)id;(void)p;assert(0);return -1;}
static void real_set_source(void *p,unsigned int id){(void)p;(void)id;assert(0);}
static int real_send_msg(unsigned int id,void *p){(void)id;(void)p;assert(0);return -1;}
static void record(const char *tag,const char *text){(void)tag;(void)text;assert(0);}
int full_hdmi_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,int mode,int *result){
 assert(id==FULL_HDMI_CP && p==wire && mode==FULL_HDMI_SIGNAL_MODE_FUNCTIONAL && hdmi_config_used==1);
 assert(io->size==real_msg_size && io->source==real_get_source && io->allocate==real_allocate_msg && io->release==real_free_msg && io->send==real_send_msg && io->set_source==real_set_source && io->record==record);
 dispatch_calls++;*result=dispatch_rc;return handled;
}
static int actual_send(unsigned int id,void *message){
''' + fragment + r'''
 return -999;
}
int main(int argc,char **argv){
 assert(argc==2);unsigned int id=FULL_HDMI_CP;void *p=wire;int expected=0;
 if(!strcmp(argv[1],"disabled")){functional_camera_enabled=0;expected=-999;}
 else if(!strcmp(argv[1],"wrong-destination")){id^=1;expected=-999;}
 else if(!strcmp(argv[1],"wrong-type")){wire[1]=0x24;expected=-999;}
 else if(!strcmp(argv[1],"other-command")){wire[2]=3;expected=-999;}
 else if(!strcmp(argv[1],"short-prefix")){request_bytes=3;expected=-999;}
 else if(!strcmp(argv[1],"null")){p=0;expected=-999;}
 else if(!strcmp(argv[1],"no-size")){real_msg_size=0;expected=-999;}
 else if(!strcmp(argv[1],"owner-rejected")){dispatch_rc=-1021;expected=-1021;}
 else if(!strcmp(argv[1],"not-handled")){handled=0;expected=-ENOTSUP;}
 else if(!strcmp(argv[1],"initializing-prefix")){predecessors_ready=0;wire[8]=1;expected=-999;}
 else if(!strcmp(argv[1],"before-ready-off")){predecessors_ready=0;expected=-999;}
 else if(!strcmp(argv[1],"readiness-error")){predecessors_ready=-EIO;expected=-999;}
 else if(!strcmp(argv[1],"standalone-functional")){pinmem_hdmi_video_connection_enabled=0;predecessors_ready=0;}
 else assert(!strcmp(argv[1],"functional-with-video-owner"));
 assert(actual_send(id,p)==expected);
 assert(dispatch_calls==(expected!=-999) && hdmi_config_used==(unsigned int)(expected!=-999));
 if(!strcmp(argv[1],"initializing-prefix") || !strcmp(argv[1],"before-ready-off") || !strcmp(argv[1],"readiness-error"))assert(readiness_calls==1 && !dispatch_calls);
 if(!strcmp(argv[1],"standalone-functional"))assert(!readiness_calls && dispatch_calls==1);
 puts("HDMI_SIGNAL_MODE_ACTUAL_MAIN_ROUTE_PASS");return 0;
}
'''
    folder = tmp_path_factory.mktemp('hdmi-signal-main')
    source, binary = folder / 'main.c', folder / 'main'
    source.write_text(code)
    built = subprocess.run(FLAGS + ['-I', str(HERE), str(source), '-o', str(binary)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', ['functional-with-video-owner', 'disabled', 'wrong-destination',
                                 'wrong-type', 'other-command', 'short-prefix', 'null', 'no-size',
                                 'owner-rejected', 'not-handled', 'initializing-prefix', 'before-ready-off',
                                 'readiness-error', 'standalone-functional'])
def test_functional_hdmi102_actual_main_route(hdmi_signal_main_binary, case):
    done = subprocess.run([str(hdmi_signal_main_binary), case], env=ENV,
                          capture_output=True, text=True, timeout=5)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'HDMI_SIGNAL_MODE_ACTUAL_MAIN_ROUTE_PASS' in done.stdout

