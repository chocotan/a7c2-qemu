from pathlib import Path
import os
import subprocess

HERE = Path(__file__).resolve().parent / 'device-models'


def test_source_bound_parameter_ingress(tmp_path):
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')

    def run(argv):
        result = subprocess.run(list(map(str, argv)), cwd=tmp_path, env=environment,
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f'{argv}: rc={result.returncode}\n{result.stdout}\n{result.stderr}')

    binary = tmp_path / 'cp-opcode-batch'
    run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
         '-DNDEBUG', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
         '-no-pie', '-pthread',
         *[HERE / name for name in ('cp-sync-resources.c', 'cp-cold-control.c',
                                   'cp-background-device.c', 'test_cp_opcode_batch.c')],
         '-o', binary])
    for opcode in (0x4001, 0x401c, 0x402a, 0x4043, 0x4051, 0x4084, 0x409c, 0x4003, 0x4022, 0x4028, 0x40af,
                   0x40b8, 0x40c5, 0x40d1, 0x40ed, 0x40fb, 0x4102, 0x4139, 0x4177, 0x40ee, 0x4083, 0x4048, 0x4167, 0x414a, 0x400f, 0x4147, 0x40d3, 0x4151, 0x4080, 0x40a1, 0x40b6, 0x40b4, 0x40a3, 0x4002, 0x400a, 0x400b, 0x400c, 0x400d, 0x4010, 0x4012, 0x4013, 0x4017, 0x401e, 0x402f, 0x403a, 0x4044, 0x4049, 0x404f, 0x405a, 0x405b, 0x4061, 0x4064, 0x406e, 0x4079, 0x407b, 0x407d, 0x4088, 0x40a4, 0x40a9, 0x40b3, 0x40b7, 0x40c3, 0x40c4, 0x40c7, 0x40ce, 0x40d4, 0x40dc, 0x40e4, 0x40e6, 0x40f1, 0x40fc, 0x40fd, 0x40fe, 0x4100, 0x4101, 0x4105, 0x4137, 0x4138, 0x413a, 0x413d, 0x413e, 0x4141, 0x4142, 0x4145, 0x4146, 0x414c, 0x414f, 0x415c, 0x4161, 0x4163, 0x4166, 0x4169, 0x416a, 0x416c):
        for case in ('values', 'reject', 'free-failure', 'reentrant', 'fork'):
            run([binary, case, hex(opcode)])
    run([binary, 'wire40ee', '0x40ee'])
    run([binary, 'wire4048', '0x4048'])
    run([binary, 'wire4167', '0x4167'])
    run([binary, 'wire414a', '0x414a'])
    run([binary, 'wire400f', '0x400f'])
    run([binary, 'wire4147', '0x4147'])
    run([binary, 'wire40d3', '0x40d3'])
    derive = tmp_path / 'cp-derive4080'
    run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
         '-DNDEBUG', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
         '-no-pie', '-pthread',
         *[HERE / name for name in ('cp-sync-resources.c', 'cp-cold-control.c',
                                   'test_cp_derive4080.c')],
         '-o', derive])
    run([derive])
    run([binary, 'wire4080', '0x4080'])
    run([binary, 'wire40a1', '0x40a1'])
    run([binary, 'wire40b6', '0x40b6'])
    run([binary, 'wire40b4', '0x40b4'])
    run([binary, 'wire40a3', '0x40a3'])
    run([binary, 'wire4151', '0x4151'])
    for case in ('all-opcodes', 'sticky', 'concurrent'):
        run([binary, case])
