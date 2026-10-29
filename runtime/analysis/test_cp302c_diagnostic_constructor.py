"""Execute the actual constructor for diagnostic mode; no native capture claim."""
import pytest

from test_bb_set_mode_profile import bb_constructor, clean_guest_environment, menu_probe_setup
from test_cp302c_no_transition_profile import selected_host

PROFILE = 'diagnostic-cp302c-reply-only-v1'
HOST = 'A7C2_CP302C_DIAGNOSTIC'
GUEST = 'MENU_CP302C_DIAGNOSTIC'


@pytest.mark.parametrize('failure', ['', 'off', 'owner', 'bind', 'video', 'osd', 'audio',
                                     'strict-conflict', 'unknown'])
def test_actual_diagnostic_constructor_keeps_state_unknown(tmp_path, bb_constructor, failure):
    host = selected_host(tmp_path)
    host.pop('A7C2_CP302C_NO_TRANSITION')
    host.pop('MENU_CP302C_NO_TRANSITION')
    host.update({HOST: PROFILE, GUEST: PROFILE})
    guest = clean_guest_environment(menu_probe_setup(host))
    assert guest[GUEST] == PROFILE
    if failure == 'off':
        guest.pop(GUEST)
    elif failure == 'strict-conflict':
        guest['MENU_CP302C_NO_TRANSITION'] = 'virtual-cp302c-current0-no-transition-v1'
    elif failure == 'unknown':
        guest[GUEST] = 'unknown'
    elif failure == 'bind':
        guest['FIXTURE_CP302C_BIND_FAIL'] = '1'
    elif failure in ('video', 'osd', 'audio'):
        guest.pop({'video': 'MENU_PINMEM_HDMI_VIDEO_CONNECT',
                   'osd': 'MENU_PINMEM_OSD_CONNECT',
                   'audio': 'MENU_ADF_HDMI_AUDIO_CONNECT'}[failure])
    output = bb_constructor(guest, cp302c_owner_rc=-1021 if failure == 'owner' else 0)
    result = next(line for line in output.splitlines() if line.startswith('RESULT '))
    fields = dict(item.split('=', 1) for item in result.split()[1:])
    assert fields['cp302c'] == fields['diagnostic'] == ('1' if not failure else '0')
    assert fields['diagnostic_init'] == ('1' if failure in ('', 'owner', 'bind') else '0')
    profiles = [line for line in output.splitlines()
                if line.startswith('NATIVE_CP302C_DIAGNOSTIC_PROFILE ')]
    if failure == 'off':
        assert not profiles
    else:
        assert len(profiles) == 1
        assert 'history_valid=0 current_known=0' in profiles[0]
        assert 'mode_transition_verified=0' in profiles[0]
        assert 'capture_verified=0' in profiles[0]
        assert 'no_transition_only=0' in profiles[0]
        if not failure:
            assert 'diagnostic_only=1' in profiles[0]
    assert not any(line.startswith('NATIVE_CP302C_NOCONVERT_PROFILE ') for line in output.splitlines())
