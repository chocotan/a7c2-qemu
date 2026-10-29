"""Independent Python oracle for a declared YUYV-to-NV12 reference operation."""
import ctypes
from pathlib import Path
import subprocess


def test_asymmetric_bytes_padding_rounding_bounds_and_no_writes(tmp_path):
    models=Path(__file__).resolve().parent/'device-models'
    library=tmp_path/'nv12.so'
    subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',
        str(models/'nv12-reference.c'),'-o',str(library)],check=True)
    api=ctypes.CDLL(str(library)).nv12_reference_convert
    api.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_uint32,
        ctypes.c_uint32,ctypes.c_void_p,ctypes.c_size_t];api.restype=ctypes.c_int
    width,height,stride=10,6,24
    rows=[];expected_y=[];chroma=[]
    for row in range(height):
        groups=[];row_chroma=[]
        for pair in range(width//2):
            y0=(row*31+pair*7)&255;y1=(row*43+pair*11+1)&255
            cb=(row*13+pair*17)&255;cr=(row*19+pair*23+2)&255
            groups.extend([y0,cb,y1,cr]);expected_y.extend([y0,y1]);row_chroma.extend([cb,cr])
        rows.append(bytes(groups)+bytes([0x5a])*(stride-width*2));chroma.append(row_chroma)
    expected=bytes(expected_y)+bytes((chroma[row][column]+chroma[row+1][column]+1)//2
        for row in range(0,height,2) for column in range(width))
    source=ctypes.create_string_buffer(b''.join(rows));before=source.raw
    output=ctypes.create_string_buffer(bytes([0xa5])*(len(expected)+32))
    target=ctypes.addressof(output)+16
    assert api(source,len(rows)*stride,width,height,stride,target,len(expected))==0
    assert output.raw[16:16+len(expected)]==expected and source.raw==before
    assert output.raw[:16]==output.raw[16+len(expected):16+len(expected)+16]==bytes([0xa5])*16
    for w,h,pitch,srcsize,dstsize in ((0,height,stride,len(before),len(expected)),
        (width-1,height,stride,len(before),len(expected)),(width,height-1,stride,len(before),len(expected)),
        (width,height,width*2-1,len(before),len(expected)),
        (width,height,stride,(height-1)*stride+width*2-1,len(expected)),
        (width,height,stride,len(before),len(expected)-1)):
        saved=output.raw
        assert api(source,srcsize,w,h,pitch,target,dstsize)==-1 and output.raw==saved
    assert api(source,len(before),width,height,stride,source,len(before))==-1
    assert source.raw==before


def test_actual_c_reference_under_sanitizers(tmp_path):
    models=Path(__file__).resolve().parent/'device-models'
    harness=tmp_path/'main.c';harness.write_text('''
#include <assert.h>
#include <string.h>
#include "nv12-reference.h"
int main(void){unsigned char source[16]={1,10,2,20,3,11,4,21,5,13,6,25,7,14,8,26};
 unsigned char output[20];memset(output,0xa5,sizeof output);
 assert(!nv12_reference_convert(source,16,4,2,8,output,12));
 const unsigned char expected[]={1,2,3,4,5,6,7,8,12,23,13,24};
 assert(!memcmp(output,expected,12));for(int i=12;i<20;i++)assert(output[i]==0xa5);
 assert(nv12_reference_convert(source,15,4,2,8,output,12)==-1);return 0;}
''')
    binary=tmp_path/'nv12'
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-no-pie',
        '-I',str(models),str(harness),str(models/'nv12-reference.c'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
