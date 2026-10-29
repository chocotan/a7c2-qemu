"""Exercise the delivered C audit block with bounded original-message fixtures."""
from pathlib import Path
import re
import subprocess

import pytest

HERE=Path(__file__).resolve().parent


@pytest.fixture(scope='module')
def audit_binary(tmp_path_factory):
    observer=(HERE/'menu-observe.c').read_text()
    start=observer.index('    if((id==FULL_HDMI_CP || id==FULL_PINMEM_CP) && same_name(getenv("MENU_PINMEM_PEER_CONNECT")')
    end=observer.index('    /* History sees every PinMem input,',start)
    definitions=[]
    for name,header in [('FULL_HDMI_CP','hdmi-device.h'),('FULL_PINMEM_CP','pinmem-device.h'),
                        ('FULL_PINMEM_PEER_CONNECTIONS_PROFILE','scalar-connection.h')]:
        definitions.append(re.search(r'^#define '+name+r' .+$',
            (HERE/'device-models'/header).read_text(),re.MULTILINE)[0])
    directory=tmp_path_factory.mktemp('hdmi-input-audit')
    source=directory/'audit.c'
    source.write_text('\n'.join(definitions)+r'''
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static unsigned char payload[5000];
static unsigned int length,size_calls,source_calls;
static int enabled=1;
static unsigned int fixture_size(void *p) {assert(p==payload);size_calls++;return length;}
static unsigned int fixture_source(void *p) {assert(p==payload);source_calls++;return 0x82d00001u;}
static unsigned int (*real_msg_size)(void *)=fixture_size;
static unsigned int (*real_get_source)(void *)=fixture_source;
static const char *fixture_getenv(const char *name) {
    assert(!strcmp(name,"MENU_PINMEM_PEER_CONNECT"));
    return enabled?FULL_PINMEM_PEER_CONNECTIONS_PROFILE:0;
}
static long fixture_syscall(long number) {assert(number==178);return 77;}
static int same_name(const char *a,const char *b) {return a && b && !strcmp(a,b);}
static void record(const char *tag,const char *text) {printf("%s%s\n",tag,text);}
#define getenv fixture_getenv
#define syscall fixture_syscall
static void audit(unsigned int id,void *message) {
'''+observer[start:end]+r'''
}
int main(int argc,char **argv) {
    assert(argc==4);char *end;
    unsigned long value=strtoul(argv[2],&end,10);assert(!*end && value<=sizeof payload);length=(unsigned int)value;
    value=strtoul(argv[3],&end,0);assert(!*end && value<=UINT_MAX);unsigned int destination=(unsigned int)value;
    void *message=payload;
    if(!strcmp(argv[1],"off"))enabled=0;
    else if(!strcmp(argv[1],"null"))message=0;
    else if(!strcmp(argv[1],"missing-size"))real_msg_size=0;
    else if(!strcmp(argv[1],"missing-source"))real_get_source=0;
    else assert(!strcmp(argv[1],"normal"));
    for(unsigned int i=0;i<length;i++)payload[i]=(unsigned char)(i*53u+7u);
    audit(destination,message);audit(destination,message);
    printf("CALLS size=%u source=%u\n",size_calls,source_calls);return 0;
}
''')
    binary=directory/'audit'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic',str(source),'-o',str(binary)],
                   check=True,capture_output=True,text=True,timeout=20)
    return binary


def execute(binary,mode='normal',length=263,destination=0x909a015a):
    output=subprocess.run([str(binary),mode,str(length),hex(destination)],check=True,
                          capture_output=True,text=True,timeout=5).stdout.splitlines()
    parse=lambda line:dict(part.split('=',1) for part in line.split()[1:])
    headers=[parse(line) for line in output if line.startswith(('FULL_HDMI_INPUT_AUDIT ','FULL_PINMEM_INPUT_AUDIT '))]
    bodies=[parse(line) for line in output if line.startswith(('FULL_HDMI_INPUT_AUDIT_BYTES ','FULL_PINMEM_INPUT_AUDIT_BYTES '))]
    return headers,bodies,parse(output[-1])


@pytest.mark.parametrize('destination',[0x909a015a,0x90590818])
@pytest.mark.parametrize('length',[0,263,4096])
def test_all_admitted_bytes_and_sequence_roundtrip(audit_binary,length,destination):
    headers,bodies,calls=execute(audit_binary,length=length,destination=destination)
    assert [row['sequence'] for row in headers]==['1','2']
    assert calls=={'size':'2','source':'2'}
    for header in headers:
        assert header['bytes']==str(length) and header['source']=='0x82d00001'
        assert header['size_known']==header['source_known']==header['bytes_complete']==header['complete']=='1'
        assert header['state_verified']==header['capture_verified']=='0'
        selected=[row for row in bodies if row['sequence']==header['sequence']]
        decoded=bytes.fromhex(''.join(row['raw'] for row in selected))
        assert decoded==bytes((i*53+7)&255 for i in range(length))
        assert [int(row['offset']) for row in selected]==list(range(0,length,128))
        assert all(len(bytes.fromhex(row['raw']))==int(row['bytes'])<=128 for row in selected)


@pytest.mark.parametrize('mode,length,expected',[
    ('normal',4097,{'size_known':'1','source_known':'1','bytes_complete':'0','complete':'0'}),
    ('null',263,{'size_known':'0','source_known':'0','bytes_complete':'0','complete':'0'}),
    ('missing-size',263,{'size_known':'0','source_known':'1','bytes_complete':'0','complete':'0'}),
    ('missing-source',263,{'size_known':'1','source_known':'0','bytes_complete':'1','complete':'0'}),
])
def test_unknown_or_oversize_input_cannot_be_a_complete_history(audit_binary,mode,length,expected):
    headers,bodies,_=execute(audit_binary,mode,length)
    assert len(headers)==2
    assert all(all(row[name]==value for name,value in expected.items()) for row in headers)
    assert bool(bodies)==(expected['bytes_complete']=='1' and length>0)


@pytest.mark.parametrize('mode,destination',[('off',0x909a015a),('normal',0x909a015b)])
def test_default_off_and_unrelated_destination_have_no_message_reads(audit_binary,mode,destination):
    headers,bodies,calls=execute(audit_binary,mode=mode,destination=destination)
    assert not headers and not bodies and calls=={'size':'0','source':'0'}
