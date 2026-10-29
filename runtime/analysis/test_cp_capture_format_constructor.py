"""Actual constructor for diagnostic 402d; original format processing stays unsupported."""
import pytest

from test_bb_set_mode_profile import bb_constructor, clean_guest_environment, menu_probe_setup
from test_cp_capture_format_profile import selected_host


@pytest.mark.parametrize('failure', ['', 'off', 'unknown', 'strict-value', 'notification-off',
                                     'notification-owner', 'diagnostic-off', 'owner'])
def test_actual_capture_format_constructor_requires_notification_chain(tmp_path, bb_constructor, failure):
    guest = clean_guest_environment(menu_probe_setup(selected_host(tmp_path)))
    assert guest['MENU_CP_CAPTURE_FORMAT'] == 'diagnostic-cp402d-reply-only-v1'
    if failure == 'off':
        guest.pop('MENU_CP_CAPTURE_FORMAT')
    elif failure == 'unknown':
        guest['MENU_CP_CAPTURE_FORMAT'] = 'unknown'
    elif failure == 'strict-value':
        guest['MENU_CP_CAPTURE_FORMAT'] = 'virtual-cp-capture-format-v1'
    elif failure == 'notification-off':
        guest.pop('MENU_CP_NOTIFICATION_CONTROL')
    elif failure == 'notification-owner':
        guest['FIXTURE_CP_NOTIFICATION_OWNER_FAIL'] = '1'
    elif failure == 'diagnostic-off':
        guest.pop('MENU_CP302C_DIAGNOSTIC')
    elif failure == 'owner':
        guest['FIXTURE_CP_CAPTURE_FORMAT_OWNER_FAIL'] = '1'
    text = bb_constructor(guest)
    result = next(line for line in text.splitlines() if line.startswith('RESULT '))
    fields = dict(item.split('=', 1) for item in result.split()[1:])
    assert fields['capture_format'] == ('1' if not failure else '0')
    assert fields['capture_format_init'] == ('1' if failure in ('', 'owner') else '0')
    logs = [line for line in text.splitlines()
            if line.startswith('NATIVE_CP_CAPTURE_FORMAT_DIAGNOSTIC_PROFILE ')]
    if failure == 'off':
        assert not logs
    else:
        assert len(logs) == 1 and 'before_any_input=1' in logs[0]
        assert 'business_applied=0 source_dependency_closed=0 native_verified=0 EE_verified=0 capture_verified=0' in logs[0]
        if not failure:
            assert 'diagnostic_only=1 no_publication=1' in logs[0]
