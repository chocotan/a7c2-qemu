#!/usr/bin/env python3
"""Build the separate read-only writer observer; never start or control a camera VM."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import time

from writer_trace import PROFILE, SCHEMA, digest, need, read_file
from writer_bundle import FALSE, HEADER_SHA256, QEMU_IMPORTS, QEMU_SHA256, source_map, validate_build, verify_actual_api

ROOT = Path(__file__).resolve().parent


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def main(args):
    need(not __import__('sys').flags.optimize, 'active assertions required')
    output = Path(args.output)
    need(output.is_absolute() and '..' not in output.parts and not output.exists() and
         output.parent.resolve(strict=True) == output.parent, 'new canonical build directory required')
    qemu, header = Path(args.qemu), Path(args.header)
    need(digest(read_file(qemu, 256 * 1024 * 1024)) == QEMU_SHA256, 'unapproved writer QEMU')
    need(digest(read_file(header, 1024 * 1024)) == HEADER_SHA256, 'unapproved writer API header')
    sources = source_map(ROOT)
    output.mkdir(mode=0o700)
    started = time.time_ns()
    commands = []

    def execute(name, command):
        with (output / (name + '.stdout')).open('xb') as stdout, \
                (output / (name + '.stderr')).open('xb') as stderr:
            result = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                    timeout=30)
        commands.append(dict(name=name, command=command, returncode=result.returncode))
        need(result.returncode == 0, name + ' failed; original output retained')
        return read_file(output / (name + '.stdout'), 128 * 1024)

    try:
        compiler = shutil.which('clang') or shutil.which('cc')
        need(compiler is not None, 'C compiler required')
        pkgconfig = shutil.which('pkg-config')
        need(pkgconfig is not None, 'pkg-config required')
        flags = execute('glib', [pkgconfig, '--cflags', '--libs', 'glib-2.0']).decode().split()
        library = output / 'scope-observer.so'
        command = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
            '-fPIC', '-shared', '-I' + str(header.parent), str(ROOT / 'scope-observer.c'),
            '-o', str(library), *flags]
        execute('compile', command)
        binary = read_file(library, 1024 * 1024)
        imports = execute('imports', ['nm', '-D', '--undefined-only', str(library)]).decode()
        actual = {line.split()[-1] for line in imports.splitlines() if 'qemu_plugin_' in line}
        need(actual == QEMU_IMPORTS, 'writer read-only QEMU import set differs')
        # The fixture was independently assembled and executed; its identity is explicit input.
        fixture = read_file(args.fixture, 1024 * 1024, args.fixture_sha256)
        proof = verify_actual_api(args.actual_api, args.actual_api_sha256, digest(binary), digest(fixture))
        compile_result = dict(command=command, returncode=0,
            source_sha256=sources['scope-observer.c'], library_sha256=digest(binary),
            stdout_sha256=digest(read_file(output / 'compile.stdout')),
            stderr_sha256=digest(read_file(output / 'compile.stderr')))
        save(output / 'compile.json', compile_result)
        need(source_map(ROOT) == sources, 'writer source changed during build')
        receipt = dict(schema='readonly_writer_build_v1', profile=PROFILE, trace_schema=SCHEMA,
            source_sha256=sources, qemu=str(qemu), qemu_sha256=QEMU_SHA256, header=str(header),
            header_sha256=HEADER_SHA256, library=str(library), library_sha256=digest(binary),
            compile_receipt_sha256=digest(read_file(output / 'compile.json')),
            qemu_imports=sorted(actual), self_owned_fixture_sha256=digest(fixture), actual_API_evidence=proof,
            started_at_ns=started, finished_at_ns=time.time_ns(), **FALSE)
        path = output / 'build-receipt.json'
        save(path, receipt)
        validate_build(ROOT, path, digest(read_file(path)), qemu)
        print(json.dumps(dict(status='WRITER_BUILD_AND_IDENTICAL_DSO_API_EVIDENCE_VERIFIED',
            receipt=str(path), sha256=digest(read_file(path)), **FALSE), indent=2))
        return 0
    except Exception as error:
        save(output / 'failure.json', dict(error_type=type(error).__name__, error=str(error),
            commands=commands, started_at_ns=started, finished_at_ns=time.time_ns(), **FALSE))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('qemu', 'header', 'output', 'actual-api', 'fixture'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--actual-api-sha256', required=True)
    parser.add_argument('--fixture-sha256', required=True)
    raise SystemExit(main(parser.parse_args()))
