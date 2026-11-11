import importlib.util
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('gpio17_static_verify',Path(__file__).with_name('verify-gpio17.py'))
verify=importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def test_gpio17_input_projection_preserves_unwritten_bits():
    rows=[dict(offset=0x04,value=8),dict(offset=0x08,value=0xfff357),
          dict(offset=0x24,value=0xfff357),dict(offset=0x28,value=8)]
    low,high=verify.fold(rows,0),verify.fold(rows,0xffffffff)
    assert low['dir']==8 and high['dir']==0xff000ca8
    assert low['inen']==0xfff357 and high['inen']==0xfffffff7
    assert low['dir'] & 4 == high['dir'] & 4 == 0
    assert low['inen'] & high['inen'] & 4 == 4
    assert low['wdata']==0 and high['wdata']==0xffffffff
    assert 'rdata' not in low and 'rdata' not in high


@pytest.mark.parametrize('offset,value',[(0x10,4),(0x14,4),(0x44,0x100000000)])
def test_unknown_input_or_nonuint32_write_rejected(offset,value):
    with pytest.raises(ValueError):
        verify.fold([dict(offset=offset,value=value)],0)


def test_untrusted_cp_input_rejected(tmp_path):
    cp,pp=tmp_path/'cp',tmp_path/'pp'
    cp.write_bytes(b'wrong CP')
    pp.write_bytes(b'wrong PP')
    with pytest.raises(ValueError,match='identity'):
        verify.verify(cp,pp)
