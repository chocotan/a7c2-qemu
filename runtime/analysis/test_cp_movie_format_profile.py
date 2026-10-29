"""Exact4000 diagnostic profile; host tests are not original CP/capture proof."""
import pytest

import backup_profile as backup
from test_bb_set_mode_profile import bb_constructor, clean_guest_environment, load_script, menu_probe_setup
from test_cp_capture_format_profile import host_environment

PROFILE = 'diagnostic-cp-movie-format-v1'
HOST = 'A7C2_CP_CAPTURE_FORMAT'
GUEST = 'MENU_CP_CAPTURE_FORMAT'


def selected_guest(tmp_path, profile=PROFILE):
    launcher = load_script('movie_format_launcher', 'start-menu.py')
    env = host_environment(tmp_path)
    env[HOST] = profile
    selected = launcher.profile_environment(env, natural_boot=True)
    selected.update(MENU_BACKUP_SYNC=backup.PROFILE, SEED_BACKUP='alllang',
                    A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    return launcher, env, clean_guest_environment(menu_probe_setup(selected))


def test_exact_movie_format_selection_and_data_boundary(tmp_path):
    launcher, env, guest = selected_guest(tmp_path)
    assert guest[GUEST] == PROFILE and HOST not in guest
    fields = backup.cp_capture_format_profile_fields(PROFILE)
    expected = {'profile': PROFILE, 'movie_format_profile': PROFILE,
                'movie_format_command': 0x4000, 'movie_format_request_type': 5,
                'movie_format_request_bytes': 20, 'movie_format_response_bytes': 12,
                'movie_format_body_hex': '050100000000000000000100',
                'movie_format_before_oneway_4072': True,
                'ee_diagnostic_profile': backup.FULL_CP_EE_DIAGNOSTIC_PROFILE}
    for name, value in expected.items():
        actual = fields['cp_capture_format_' + name]
        assert type(actual) is type(value) and actual == value
    assert len(bytes.fromhex(expected['movie_format_body_hex'])) == 12
    for name in ('data_reply_3003_supported', 'snapshot_2040_supported', 'business_applied',
                 'source_dependencies_closed', 'published', 'generation_advanced',
                 'native_verified', 'EE_verified', 'capture_verified'):
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


@pytest.mark.parametrize('failure', ['', 'movie-owner', 'ee-owner', 'startup-owner',
                                     'format-owner', 'notification'])
def test_actual_movie_constructor_requires_full_chain(tmp_path, bb_constructor, failure):
    _, _, guest = selected_guest(tmp_path)
    for condition, key in (('movie-owner', 'FIXTURE_CP_MOVIE_FORMAT_OWNER_FAIL'),
                           ('ee-owner', 'FIXTURE_CP_EE_OWNER_FAIL'),
                           ('startup-owner', 'FIXTURE_CP_STARTUP_OWNER_FAIL'),
                           ('format-owner', 'FIXTURE_CP_CAPTURE_FORMAT_OWNER_FAIL')):
        if failure == condition:
            guest[key] = '1'
    if failure == 'notification':
        guest.pop('MENU_CP_NOTIFICATION_CONTROL')
    text = bb_constructor(guest)
    fields = dict(part.split('=', 1) for part in next(
        line for line in text.splitlines() if line.startswith('RESULT ')).split()[1:])
    assert fields['movie_format'] == ('0' if failure else '1')
    assert fields['movie_format_init'] == ('1' if failure in ('', 'movie-owner') else '0')
    assert fields['ee_controls'] == ('0' if failure else '1')
    assert fields['ee_controls_init'] == ('1' if failure in ('', 'movie-owner', 'ee-owner') else '0')
    logs = [line for line in text.splitlines() if line.startswith('NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE ')]
    assert len(logs) == 1 and 'data_3003_supported=0 business_applied=0' in logs[0]
    assert 'published=0 generation=0 native_verified=0 EE_verified=0 capture_verified=0' in logs[0]


@pytest.mark.parametrize('profile', ['', backup.FULL_CP_CAPTURE_FORMAT_PROFILE,
                                     backup.FULL_CP_STARTUP_DIAGNOSTIC_PROFILE,
                                     backup.FULL_CP_EE_DIAGNOSTIC_PROFILE])
def test_prior_profiles_do_not_initialize_movie_owner(tmp_path, bb_constructor, profile):
    _, _, guest = selected_guest(tmp_path, profile)
    text = bb_constructor(guest)
    assert 'movie_format=0 movie_format_init=0' in text
    assert not any(line.startswith('NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE ') for line in text.splitlines())
