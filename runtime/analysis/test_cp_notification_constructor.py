"""Actual constructor execution for the finite notification-off virtual owner."""
import pytest

from test_bb_set_mode_profile import bb_constructor, clean_guest_environment, menu_probe_setup
from test_cp302c_no_transition_profile import selected_host

PROFILE = 'virtual-cp-notification-mode0-v1'
DIAGNOSTIC = 'diagnostic-cp302c-reply-only-v1'


@pytest.mark.parametrize('failure', ['', 'off', 'unknown', 'missing-diagnostic',
                                     'strict-conflict', 'owner', 'prior-owner', 'video'])
def test_actual_notification_constructor_requires_diagnostic_owner(tmp_path, bb_constructor, failure):
    host = selected_host(tmp_path)
    host.pop('A7C2_CP302C_NO_TRANSITION')
    host.pop('MENU_CP302C_NO_TRANSITION')
    host.update(A7C2_CP302C_DIAGNOSTIC=DIAGNOSTIC, MENU_CP302C_DIAGNOSTIC=DIAGNOSTIC,
                A7C2_CP_NOTIFICATION_CONTROL=PROFILE, MENU_CP_NOTIFICATION_CONTROL=PROFILE)
    guest = clean_guest_environment(menu_probe_setup(host))
    assert guest['MENU_CP_NOTIFICATION_CONTROL'] == PROFILE
    if failure == 'off':
        guest.pop('MENU_CP_NOTIFICATION_CONTROL')
    elif failure == 'unknown':
        guest['MENU_CP_NOTIFICATION_CONTROL'] = 'unknown'
    elif failure == 'missing-diagnostic':
        guest.pop('MENU_CP302C_DIAGNOSTIC')
    elif failure == 'strict-conflict':
        guest['MENU_CP302C_NO_TRANSITION'] = 'virtual-cp302c-current0-no-transition-v1'
    elif failure == 'owner':
        guest['FIXTURE_CP_NOTIFICATION_OWNER_FAIL'] = '1'
    elif failure == 'video':
        guest.pop('MENU_PINMEM_HDMI_VIDEO_CONNECT')
    text = bb_constructor(guest, cp302c_owner_rc=-1021 if failure == 'prior-owner' else 0)
    result = next(line for line in text.splitlines() if line.startswith('RESULT '))
    fields = dict(item.split('=', 1) for item in result.split()[1:])
    assert fields['notification'] == ('1' if not failure else '0')
    assert fields['notification_init'] == ('1' if failure in ('', 'owner') else '0')
    logs = [line for line in text.splitlines() if line.startswith('NATIVE_CP_NOTIFICATION_PROFILE ')]
    if failure == 'off':
        assert not logs
    else:
        assert len(logs) == 1 and 'before_any_input=1' in logs[0]
        assert 'native_verified=0 EE_verified=0 capture_verified=0' in logs[0]
        if not failure:
            assert 'virtual_mode_policy=1 notification_mode=0' in logs[0]
