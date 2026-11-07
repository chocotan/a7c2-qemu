#!/usr/bin/env python3
"""Compare actual optional preload forwarding with an unobserved host fixture."""
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
PROVIDER = r'''
#include <errno.h>
#include <string.h>
int Backup_read(unsigned int key,void *p) {
    const unsigned char v[8]={0,0,0,1,4,0,0,0};memcpy(p,v,8);
    errno=EAGAIN;return key==0xfa007c?8:-37;
}
'''
CLIENT = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
int Backup_read(unsigned int,void *);
int main(void) {
    unsigned char bytes[8];errno=0;
    assert(Backup_read(0xfa007c,bytes)==8 && errno==EAGAIN && bytes[3]==1 && bytes[4]==4);
    assert(Backup_read(0x1234,bytes)==-37 && errno==EAGAIN);
    char buffer[128];int at=-1;
    int n=snprintf(buffer,sizeof buffer,"%s-%ld-%.2f%n","hello",17L,2.5,&at);
    assert(n==13 && at==13 && !strcmp(buffer,"hello-17-2.50"));
    printf("%d %s\n",n,buffer);return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name, source in (('provider.c', PROVIDER), ('client.c', CLIENT)):
            (root / name).write_text(source)
        subprocess.run(['clang', '-shared', '-fPIC', str(root / 'provider.c'), '-o', str(root / 'libprovider.so')], check=True)
        subprocess.run(['clang', '-fno-builtin-snprintf', str(root / 'client.c'), '-L' + str(root), '-lprovider',
                        '-Wl,-rpath,$ORIGIN', '-o', str(root / 'client')], check=True)
        observer = root / 'liro-observe.so'
        subprocess.run(['clang', '-shared', '-fPIC', '-O2', '-fno-builtin', '-Wall', '-Wextra', '-Werror',
                        '-pthread', str(HERE / 'liro-observe.c'), '-ldl', '-o', str(observer)], check=True)
        baseline = subprocess.run([str(root / 'client')], capture_output=True, check=True)
        for enabled in ('0', '1'):
            result = subprocess.run([str(root / 'client')], capture_output=True, check=True,
                                    env=dict(os.environ, LD_PRELOAD=str(observer), FULLSYSTEM_LIRO_OBSERVE=enabled))
            assert (result.stdout, result.stderr) == (baseline.stdout, baseline.stderr)
    print('LIRO_ACTUAL_PRELOAD_REAL_FORWARDING_NON_TARGET_PASS')


if __name__ == '__main__':
    main()
