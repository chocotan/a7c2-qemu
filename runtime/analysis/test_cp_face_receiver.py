from pathlib import Path
import os
import subprocess

HERE = Path(__file__).resolve().parent


def test_face_result_receiver(tmp_path):
    binary = tmp_path / 'face-receiver'
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')
    sources = HERE / 'device-models'
    command = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', '-pthread',
               sources / 'cp-sync-resources.c', sources / 'cp-cold-control.c',
               sources / 'test_cp_face_receiver.c', '-o', binary]
    for argv in [command] + [[binary, case] for case in
                            ('wire', 'sequence', 'reject', 'reentrant', 'free-failure', 'overflow', 'fork')]:
        result = subprocess.run(list(map(str, argv)), cwd=tmp_path, env=environment,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f'{argv}: {result.stdout}\n{result.stderr}'


def test_face_result_receiver_wiring():
    text = (HERE / 'menu-observe.c').read_text()
    start = text.index('if ((id==NATIVE_CP_BACKGROUND_SID || id==NATIVE_CP_CAPTURE_SID ||')
    route = text[start:text.index('if (id == NATIVE_DMM_UNIT_SID', start)]
    assert '(id==NATIVE_CP_FACE_SID && functional_camera_enabled)' in route
    assert 'same_name(getenv("MENU_CP_BACKGROUND"),"virtual-mode3-cold-v1")' in route
    face_send = 'native_functional_face_send(id,message,__builtin_return_address(0),&result)'
    background = 'native_cp_background_dispatch(id,message,&io,1,&result)'
    assert route.index(face_send) < route.index(background)
    handler = text[text.index('static int native_functional_face_send('):
                   text.index('static void native_functional_face_received(')]
    # Index7's 12-byte wire must fall through to its existing receiver.
    assert 'id==NATIVE_CP_FACE_SID && bytes==24' in handler
    assert '((const unsigned char *)message)[1]==6' in handler
    assert 'if(!list && (id!=FUNCTIONAL_FACE_DMM_CP || bytes!=40))return 0;' in handler
    assert 'functional_face_original_caller(op,caller,' in handler
    assert 'case 6:expected=0x3535a68;instruction=0x9784a41b;break;' in text
    logger = text[text.index('static void record(const char *prefix, const char *name) {'):]
    assert '"NATIVE_CP_FACE_"' in logger[:logger.index('for (unsigned int i = 0; i < sizeof mirrored')]
