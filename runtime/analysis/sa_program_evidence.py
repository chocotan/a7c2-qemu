"""Pin the original loaded NV12 program by bytes; never infer its ISA/output."""
import hashlib
import json
from pathlib import Path
import struct
import sys

PACKAGE_SHA='38a99704591ce1706a0b77645f71d1b2f50750419672d1bd2280c448f2d09a12'
PAYLOAD_SHA='75c481ee17961521fd5cb2c41ab49fec79228839e47faba5d97f8ef59a5a8822'
HERE=Path(__file__).resolve().parent


def verify(run,package=None):
    package=Path(package) if package is not None else HERE/'menu-root/usr/sabin/sa_sabin_mp_cam_post.bin'
    data=package.read_bytes()
    if hashlib.sha256(data).hexdigest()!=PACKAGE_SHA:raise ValueError('SA package identity differs')
    raw=(Path(run)/'sa2-program.bin').read_bytes()
    header=data[0x8800:0x8850]
    if (struct.unpack_from('<I',header)[0]!=0x91130aaa or header[4]!=7 or header[8]>1 or
            header[0xe]!=1 or struct.unpack_from('<H',header,6)[0]!=0x50 or
            header[0x14:0x20].split(b'\0')[0]!=b'SA_NV12_0x02' or
            struct.unpack_from('<I',header,0x28)[0]!=0x100 or
            header[0x44:].split(b'\0')[0]!=b'NV12CONV0x02'):
        raise ValueError('Original NV12 bundle selection differs')
    payload=data[0x8900:0x9d00]
    if hashlib.sha256(payload).hexdigest()!=PAYLOAD_SHA:raise ValueError('Original NV12 payload differs')
    matched=len(raw)==0x2000 and raw==data[0x8000:0xa000]
    return dict(loaded_nv12_program_identity_verified=matched,
        package_sha256=PACKAGE_SHA,readback_sha256=hashlib.sha256(raw).hexdigest(),
        program_name='NV12CONV0x02',bundle_name='SA_NV12_0x02',
        package_bundle_offset=0x8800,package_program_offset=0x8900,
        readback_program_offset=0x900,payload_bytes=len(payload),payload_sha256=PAYLOAD_SHA,
        isa_verified=False,program_execution_verified=False,pixel_transform_verified=False,
        completion_verified=False)


if __name__=='__main__':
    print(json.dumps(verify(Path(sys.argv[1])),indent=2))
