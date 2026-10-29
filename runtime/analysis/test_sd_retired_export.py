import pytest

from sd_flush_barrier import BarrierError, _reply


def test_original_retirement_is_distinct_from_a_flush_result():
    evidence=_reply(lambda *a,**kw: b'SD_FSYS_RETIRED seq=12 pid=217 drive=65 mask=0 unmount_rc=0\n',
                    '12',cleanup=False)
    assert evidence=={'pid':217,'drive':65,'rc':0,'kind':'retired','mask':0}


@pytest.mark.parametrize('data',[
    b'SD_FSYS_RETIRED seq=12 pid=217 drive=65 mask=1 unmount_rc=0\n',
    b'SD_FSYS_RETIRED seq=12 pid=217 drive=64 mask=0 unmount_rc=0\n',
    b'SD_FSYS_RETIRED seq=12 pid=217 drive=65 mask=67108864 unmount_rc=0\n',
    b'SD_FSYS_RETIRED seq=12 pid=217 drive=65 mask=0 unmount_rc=0\nSD_FSYS_FLUSH seq=12 pid=217 drive=65 rc=0\n',
])
def test_missing_or_contradictory_retirement_is_rejected(data):
    with pytest.raises(BarrierError):_reply(lambda *a,**kw:data,'12',cleanup=False)
