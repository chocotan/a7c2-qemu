"""Pin natural-start prologues and the independent, safe probe gate."""
import os
from pathlib import Path
import struct
import subprocess

HERE = Path(__file__).resolve().parent
IMAGE = HERE / 'menu-root/usr/lib/appFw.so'
SHA = '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'


def test_original_prologues_match_replayed_words():
    if not IMAGE.exists():
        import pytest
        pytest.skip('Original appFw is not distributed')
    import hashlib
    raw = IMAGE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA
    expected = {
        0x33aa0d0: (0xa9b67bfd, 0x910003fd, 0xa90363f7, 0x9101c3b7),
        0x339d44c: (0xd13a03ff, 0xa9ba7bfd, 0x910003fd, 0xa90153f3),
        0x305b9b0: (0xa9446bf9, 0xa94573fb, 0xa8d47bfd, 0xd65f03c0),
        0x359e8b8: (0xf9401bf7, 0xa94153f3, 0xb90002a0, 0xa9425bf5),
        0x305be24: (0xb940f3a3, 0x52803322, 0xaa1403e1, 0x17fffed1),
        0x305b970: (0xaa1503e1, 0x9000c320, 0x912e8c00, 0x941892d3),
    }
    for address, words in expected.items():
        assert struct.unpack_from('<4I', raw, address) == words


def test_gate_is_validated_and_does_not_enable_legacy_entry_bundle():
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('MENU_', 'A7C2_', 'QEMU_', 'SONY_'))}
    result = subprocess.run(['python3', str(HERE / 'qemu-menu-probe.py')],
                            env=dict(env, MENU_NATURAL_START_TRACE='2'),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and 'must be 1 or unset' in result.stderr
    source = (HERE / 'menu-observe.c').read_text()
    assert 'if (getenv("MENU_NATURAL_START_TRACE"))' in source
    assert 'install_natural_start_trace(appfw_base);' in source
    assert 'install_run_i_return_probe(appfw_base);' in source
    assert '"UPM model error 0x359e8b8"' in source
    assert '"boot fatal line 409 0x305be24"' in source
    assert 'boot_fatal_409_continue = (void *)(base + 0x305b974UL);' in source
    assert 'boot_fatal_common_continue = (void *)(base + 0x305b980UL);' in source
    assert 'boot_fatal_format_page = (void *)(base + 0x48bf000UL);' in source
    assert 'boot_fatal_logger = (void *)(base + 0x36804c8UL);' in source
    assert 'if (getenv("MENU_ENTRY_PROBES")) install_boot_entry_probes(appfw_base);' in source


def test_enter_still_mode_is_explicit_and_precedes_shutter():
    source = (HERE / 'check-natural-gtk-input.py').read_text()
    assert "--enter-still-mode requires --natural-shutter" in source
    block = source.index("if '--enter-still-mode' in sys.argv:")
    assert source.index("action('MODE_STILL',True)", block) < source.index("if '--natural-shutter' in sys.argv:", block)
    assert "capture('enter-still-mode','any')" in source
    assert "'mode_transition_verified':False" in source
    assert "'ee_start_verified':False" in source


def test_reenter_still_mode_uses_movie_then_still_before_shutter():
    source = (HERE / 'check-natural-gtk-input.py').read_text()
    assert "--reenter-still-mode requires --natural-shutter" in source
    block = source.index("if '--reenter-still-mode' in sys.argv:")
    movie = source.index("action('MODE_MOVIE',True)", block)
    still = source.index("action('MODE_STILL',True)", block)
    shutter = source.index("if '--natural-shutter' in sys.argv:", block)
    assert movie < still < shutter
    assert "capture('reenter-movie','any')" in source
    assert "capture('reenter-still','any')" in source
    assert "'mode_transition_verified':False" in source
    assert "'ee_start_verified':False" in source


def test_fn_nav_probe_is_bounded_and_does_not_select_a_setting():
    source = (HERE / 'check-natural-gtk-input.py').read_text()
    assert '--fn-nav-probe requires isolated Simplified-Chinese new UI firstboot' in source
    validation = source[source.index('if fn_nav_probe and'):source.index('if format_workflow and', source.index('if fn_nav_probe and'))]
    assert "'--export-sd' not in sys.argv" not in validation
    start = source.index('if fn_nav_probe:', source.index("capture('shooting-after-setup','any')"))
    end = source.index('if reviewed_prompt:', start)
    block = source[start:end]
    assert "action('FN',True)" in block
    assert "action('DOWN',False)" in block
    assert 'range(1,6 if fn_silent_enter else 7)' in block
    navigation = block[:block.index('if fn_silent_enter:')]
    assert 'ENTER' not in navigation
    assert block.count("action('ENTER',False)") == 2
    assert "capture('silent-on-selected','any')" in block
    assert "capture('silent-enabled','any')" in block
    assert 'shutter_cycle' not in block
    assert "'silent_mode_selected':False" in block
    assert "'setting_write_verified':False" in block
    assert "if fn_silent_enter:" in block
    assert "capture('silent-enter','any')" in block


def test_natural_start_enables_only_the_safe_shooting_gate_probe():
    source = (HERE / 'menu-observe.c').read_text()
    start = source.index('if (getenv("MENU_NATURAL_START_TRACE"))')
    end = source.index('if (getenv("MENU_SYNC_MSG_HOOK"))', start)
    block = source[start:end]
    assert 'install_shooting_probe(appfw_base);' in block
    assert 'install_boot_entry_probes(appfw_base);' not in block


def test_silent_mode_shutter_uses_original_selection_then_natural_sequence():
    source = (HERE / 'check-natural-gtk-input.py').read_text()
    assert '--silent-mode-shutter requires isolated --natural-shutter without mode probes' in source
    start = source.index("if '--silent-mode-shutter' in sys.argv:")
    end = source.index("if '--natural-shutter' in sys.argv:", start)
    block = source[start:end]
    assert "action('FN',True)" in block
    assert 'range(1,6)' in block
    assert block.count("action('ENTER',False)") == 2
    assert block.count("action('UP',False)") == 1
    assert "action('MENU',True)" not in block
    assert "capture('silent-enabled','any')" in block
    assert "capture('silent-shooting','any')" in block
    assert "'setting_write_verified':False" in block
    assert "'still_capture_verified':False" in block


def test_application_init_return_is_handle_not_error_pointer():
    if not IMAGE.exists():
        import pytest
        pytest.skip('Original appFw is not distributed')
    raw = IMAGE.read_bytes()
    # 0x1796918 ends after strncpy/log handling; it never constructs an error result.
    assert struct.unpack_from('<I', raw, 0x17969e0)[0] == 0x97fb25a8  # bl PLT strncpy
    assert struct.unpack_from('<I', raw, 0x1796a10)[0] == 0xd65f03c0
    assert struct.unpack_from('<I', raw, 0x36ec340)[0] == 0xf94033a0  # return OSAL output handle
    source = (HERE / 'menu-observe.c').read_text()
    assert 'static void *(*real_application_init)(void *);' in source
    assert 'void *result = real_application_init(argument);' in source
    assert 'record("RETURN_HANDLE ", init_result);' in source
    assert 'result ? "RETURN_NONZERO " : "RETURN_ZERO "' not in source
