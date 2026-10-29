import pytest
from sa_program_evidence import verify,HERE


def test_loaded_program_requires_full_window_and_pinned_original(tmp_path):
    package=HERE/'menu-root/usr/sabin/sa_sabin_mp_cam_post.bin'
    if not package.exists():pytest.skip('Original firmware is not distributed')
    raw=package.read_bytes()
    (tmp_path/'sa2-program.bin').write_bytes(raw[0x8000:0xa000])
    proof=verify(tmp_path)
    assert proof['loaded_nv12_program_identity_verified'] and proof['program_name']=='NV12CONV0x02'
    assert not proof['program_execution_verified'] and not proof['pixel_transform_verified']
    broken=bytearray(raw[0x8000:0xa000]);broken[0x901]^=1
    (tmp_path/'sa2-program.bin').write_bytes(broken)
    assert not verify(tmp_path)['loaded_nv12_program_identity_verified']
    (tmp_path/'sa2-program.bin').write_bytes(raw[0x8000:0x9fff])
    assert not verify(tmp_path)['loaded_nv12_program_identity_verified']
    altered=tmp_path/'altered-package.bin';altered.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
    with pytest.raises(ValueError,match='identity'):verify(tmp_path,altered)
