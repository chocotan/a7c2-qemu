import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import pytest


def test_power_notice_parser_rejects_short_packets_and_preserves_values():
    compiler=shutil.which('cc')
    if compiler is None:pytest.skip('host C compiler unavailable')
    source=r'''
#include <assert.h>
#include "power-notice.h"
int main(void) {
    unsigned int words[4]={91,92,93,94};
    const unsigned int packet[4]={0x00920143,7,2,1};
    assert(!power_notice_decode(0,16,words));
    for(unsigned int n=0;n<16;++n) {
        assert(!power_notice_decode(packet,n,words));
        assert(words[0]==91 && words[3]==94);
    }
    assert(power_notice_decode(packet,16,words));
    assert(words[0]==0x00920143 && words[1]==7 && words[2]==2 && words[3]==1);
    const unsigned int cancel=0x00920145;
    assert(power_notice_decode(&cancel,4,words));
    assert(words[0]==cancel && words[1]==0 && words[2]==0 && words[3]==0);
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as directory:
        test=Path(directory)/'test.c';binary=Path(directory)/'test'
        test.write_text(source)
        subprocess.run([compiler,'-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                        '-I',str(Path(__file__).parent),str(test),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
