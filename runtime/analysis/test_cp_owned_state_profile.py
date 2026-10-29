"""Unified owned state must preserve source gaps and exact predecessor admission."""
import pytest

import backup_profile as backup
from test_bb_set_mode_profile import bb_constructor, clean_guest_environment, load_script, menu_probe_setup
from test_cp_capture_format_profile import host_environment

PROFILE = 'virtual-cp-owned-state-v1'


def selected(tmp_path):
    launcher = load_script('owned_camera_state_launcher', 'start-menu.py')
    env = host_environment(tmp_path)
    env['A7C2_CP_CAPTURE_FORMAT'] = PROFILE
    host = launcher.profile_environment(env, natural_boot=True)
    host.update(MENU_BACKUP_SYNC=backup.PROFILE, SEED_BACKUP='alllang',
                A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    return launcher, env, clean_guest_environment(menu_probe_setup(host))


def test_owned_state_exact_transport_and_no_bootstrap_readiness(tmp_path):
    launcher, env, guest = selected(tmp_path)
    assert guest['MENU_CP_CAPTURE_FORMAT'] == PROFILE
    assert 'A7C2_CP_CAPTURE_FORMAT' not in guest
    fields = backup.cp_capture_format_profile_fields(PROFILE)
    assert fields['cp_capture_format_owned_state_constructor_known_fields'] == 0
    assert fields['cp_capture_format_owned_state_property_input_policy'] == 'explicit-public-CP-initial-stage-before-freeze'
    assert fields['cp_capture_format_owned_state_property_stage_sha256'] == backup.PRIMARY_SHA
    assert fields['cp_capture_format_owned_state_parameter_local_store_bytes'] == 694
    assert fields['cp_capture_format_owned_state_parameter_default_store_bytes'] == 2223
    assert fields['cp_capture_format_owned_state_parameter_initial_local_known_bytes'] == 2913
    assert fields['cp_capture_format_owned_state_override_input_policy'] == 'owned-d64-copy-then-explicit-bank0-binding'
    assert fields['cp_capture_format_owned_state_full_blocks'] == 76
    assert fields['cp_capture_format_owned_state_provider_policy'] == 'actual-consumed-inputs-only-no-defaults-no-secondary-fallback'
    for name in ('business_applied', 'published', 'generation_advanced', 'native_verified',
                 'EE_verified', 'capture_verified', 'data_reply_3003_supported', 'snapshot_2040_supported'):
        assert fields['cp_capture_format_' + name] is False
    for key in ('A7C2_CP_NOTIFICATION_CONTROL', 'A7C2_CP302C_DIAGNOSTIC',
                'A7C2_PINMEM_HDMI_VIDEO_CONNECT', 'A7C2_PINMEM_OSD_CONNECT'):
        bad = dict(env)
        bad.pop(key)
        with pytest.raises(ValueError):
            launcher.profile_environment(bad, natural_boot=True)
    for changes in ({'MENU_CP_CAPTURE_FORMAT': 'unknown'},
                    {'A7C2_CP_CAPTURE_FORMAT': PROFILE + ' '},
                    {'A7C2_CP302C_NO_TRANSITION': backup.FULL_CP302C_NO_TRANSITION_PROFILE}):
        with pytest.raises(ValueError):
            launcher.profile_environment({**env, **changes}, natural_boot=True)


@pytest.mark.parametrize('failure', ['', 'PROVIDER', 'PARAMETER', 'RESET', 'COMMON', 'INPUTS', 'PUBLICATION', 'MOVIE'])
def test_owned_state_actual_constructor_never_promotes_data(tmp_path, bb_constructor, failure):
    _, _, guest = selected(tmp_path)
    if failure == 'MOVIE':
        guest['FIXTURE_CP_MOVIE_FORMAT_OWNER_FAIL'] = '1'
    elif failure:
        guest['FIXTURE_CP_OWNED_' + failure + '_FAIL'] = '1'
    text = bb_constructor(guest)
    values = dict(part.split('=', 1) for part in next(
        line for line in text.splitlines() if line.startswith('RESULT ')).split()[1:])
    assert values['owned_state'] == ('1' if not failure else '0')
    assert values['owned_state_init'] == ('1' if failure in ('', 'PUBLICATION') else '0')
    line = next(line for line in text.splitlines() if line.startswith('NATIVE_CP_OWNED_STATE_PROFILE '))
    assert 'constructor_data_known=0' in line and 'repository_fallback=0' in line
    reset_consumed = failure in ('', 'INPUTS', 'PUBLICATION')
    assert ('parameter_reset_store_consumed=' + ('1' if reset_consumed else '0')) in line
    assert ('parameter_reset_bytes=' + ('8' if reset_consumed else '0')) in line
    assert ('parameter_common_local_bytes=' + ('694' if reset_consumed else '0') + ' initialization_complete=0') in line
    assert 'business_applied=0 published=0 EE=0 frame=0 capture=0' in line
