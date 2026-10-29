"""One explicit multi-command diagnostic profile; no CP business/capture claims."""
import pytest

import backup_profile as backup
from test_bb_set_mode_profile import bb_constructor, clean_guest_environment, load_script, menu_probe_setup
from test_cp_capture_format_profile import host_environment

PROFILE = 'diagnostic-cp-startup-controls-v1'
HOST = 'A7C2_CP_CAPTURE_FORMAT'
GUEST = 'MENU_CP_CAPTURE_FORMAT'


def test_exact_batch_selection_and_typed_guest_contract(tmp_path):
    launcher = load_script('startup_controls_batch_launcher', 'start-menu.py')
    env = host_environment(tmp_path)
    env[HOST] = PROFILE
    selected = launcher.profile_environment(env, natural_boot=True)
    selected.update(MENU_BACKUP_SYNC=backup.PROFILE, SEED_BACKUP='alllang',
                    A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    guest = clean_guest_environment(menu_probe_setup(selected))
    assert guest[GUEST] == PROFILE and HOST not in guest
    fields = backup.cp_capture_format_profile_fields(PROFILE)
    assert fields['cp_capture_format_diagnostic_only'] == 1
    assert fields['cp_capture_format_startup_commands'] == [
        {'command': 0x4014, 'request_bytes': 24, 'response_bytes': 12},
        {'command': 0x40c8, 'request_bytes': 328, 'response_bytes': 12},
        {'command': 0x4057, 'request_bytes': 12, 'response_bytes': 12}]
    for name in ('business_applied', 'source_dependencies_closed', 'published',
                 'generation_advanced', 'native_verified', 'EE_verified', 'capture_verified'):
        assert fields['cp_capture_format_' + name] is False
    for predecessor in ('A7C2_CP_NOTIFICATION_CONTROL', 'A7C2_CP302C_DIAGNOSTIC',
                        'A7C2_PINMEM_HDMI_VIDEO_CONNECT', 'A7C2_PINMEM_OSD_CONNECT'):
        bad = dict(env)
        bad.pop(predecessor)
        with pytest.raises(ValueError):
            launcher.profile_environment(bad, natural_boot=True)
    for change in ({GUEST: 'unknown'}, {HOST: PROFILE + ' '},
                   {'A7C2_CP302C_NO_TRANSITION': 'virtual-cp302c-current0-no-transition-v1'}):
        with pytest.raises(ValueError):
            launcher.profile_environment({**env, **change}, natural_boot=True)
    with pytest.raises(ValueError):
        launcher.profile_environment(env, natural_boot=False)


@pytest.mark.parametrize('failure', ['', 'owner', 'missing-notification', 'missing-402d-owner'])
def test_actual_batch_constructor(tmp_path, bb_constructor, failure):
    launcher = load_script('startup_controls_batch_constructor', 'start-menu.py')
    env = host_environment(tmp_path)
    env[HOST] = PROFILE
    selected = launcher.profile_environment(env, natural_boot=True)
    selected.update(MENU_BACKUP_SYNC=backup.PROFILE, SEED_BACKUP='alllang',
                    A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    guest = clean_guest_environment(menu_probe_setup(selected))
    if failure == 'owner':
        guest['FIXTURE_CP_STARTUP_OWNER_FAIL'] = '1'
    elif failure == 'missing-notification':
        guest.pop('MENU_CP_NOTIFICATION_CONTROL')
    elif failure == 'missing-402d-owner':
        guest['FIXTURE_CP_CAPTURE_FORMAT_OWNER_FAIL'] = '1'
    text = bb_constructor(guest)
    result = next(line for line in text.splitlines() if line.startswith('RESULT '))
    fields = dict(part.split('=', 1) for part in result.split()[1:])
    assert fields['startup'] == ('1' if not failure else '0')
    assert fields['startup_init'] == ('1' if failure in ('', 'owner') else '0')
    logs = [line for line in text.splitlines() if line.startswith('NATIVE_CP_STARTUP_DIAGNOSTIC_PROFILE ')]
    assert len(logs) == 1 and 'business_applied=0 published=0 generation=0' in logs[0]
