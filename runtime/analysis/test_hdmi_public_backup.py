from pathlib import Path
import hashlib
import subprocess

HERE = Path(__file__).resolve().parent


def test_actual_public_cp_bank_reader(tmp_path):
    seed = HERE / 'menu-root/seed-backup.bin'
    assert hashlib.sha256(seed.read_bytes()).hexdigest() == '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
    source = tmp_path / 'reader.c'
    source.write_text(r'''
#define _GNU_SOURCE
#include "hdmi-public-backup.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc,char **argv){
 assert(argc==3);int fd=open(argv[1],O_RDONLY),bad=open(argv[2],O_RDONLY);assert(fd>=0 && bad>=0);
 const unsigned int keys[]={0x009a0001,0x009a0009,0x009a000a,0x009a000b,0x009a000c};
 const unsigned int sizes[]={10,1,1,1,4};
 const unsigned char data[5][10]={{0x92,0x9b,0x52,0xf4,0x8d,0x72,0x96,0x8c,0xc2,0x92},{0},{1},{0},{0xe0,0x93,4,0}};
 for(unsigned int i=0;i<5;i++){
  unsigned char out[32];unsigned int n=99;memset(out,0xcc,sizeof out);
  assert(!full_hdmi_public_backup_read(fd,keys[i],out,sizeof out,&n) && n==sizes[i]);
  assert(!memcmp(out,data[i],n));for(unsigned int j=n;j<sizeof out;j++)assert(out[j]==0xcc);
  memset(out,0xcc,sizeof out);assert(!full_hdmi_public_backup_read(fd,keys[i],out,1,&n) && n==sizes[i] && out[0]==data[i][0] && out[1]==0xcc);
  assert(!full_hdmi_public_backup_read(fd,keys[i],NULL,0,&n) && n==sizes[i]);
 }
 unsigned int n=99;unsigned char byte=0xcc;
 assert(full_hdmi_public_backup_read(fd,0x010704fd,&byte,1,&n)==1 && n==0 && byte==0xcc);
 assert(full_hdmi_public_backup_read(bad,0x009a0009,&byte,1,&n)==-1021 && n==0 && byte==0xcc);
 assert(full_hdmi_public_backup_read(-1,0x009a0009,&byte,1,&n)==-1021 && n==0);
 assert(full_hdmi_public_backup_read(fd,0x920085,&byte,1,&n)==-1021 && n==0);
 assert(full_hdmi_public_backup_read(fd,0x009a0009,NULL,1,&n)==-1021 && n==0);
 assert(full_hdmi_public_backup_read(fd,0x009a0009,&byte,1,NULL)==-1021);
 assert(!close(fd) && !close(bad));puts("PASS: actual CP bank values, lengths, capacity, verified absence and bad-source refusal");return 0;
}
''')
    bad = tmp_path / 'bad.bin'
    corrupt = bytearray(seed.read_bytes())
    corrupt[0x130000] ^= 1
    bad.write_bytes(corrupt)
    binary = tmp_path / 'reader'
    result = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                             '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                             '-I', str(HERE / 'device-models'), str(source),
                             str(HERE / 'device-models/hdmi-public-backup.c'), '-o', str(binary)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(binary), str(seed), str(bad)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith('PASS: actual CP bank')
