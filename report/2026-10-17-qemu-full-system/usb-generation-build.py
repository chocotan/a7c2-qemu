#!/usr/bin/env python3
"""Build the bounded USB observer release using the unchanged flash builder."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_contract():
    value = json.loads((HERE / 'usb-generation-source-contract.json').read_text())
    parent = HERE / 'persistent-flash/build.py'
    if (value.get('schema') != 'a7c2.usb-generation-source-delta.v1' or parent.is_symlink() or
            not parent.is_file() or digest(parent) != value['parent_build_sha256']):
        raise ValueError('USB observer release parent differs')
    builder = runpy.run_path(str(parent))
    if (builder['USB_PUBLIC'] != value['parent_public_sha256'] or
            builder['USB_BASELINE'] != value['baseline_identity'] or
            set(value['build_public_sha256']) != set(builder['USB_PUBLIC'])):
        raise ValueError('USB observer release changes the baseline or source scope')
    core = {'persistent-flash/flash-core.h', 'persistent-flash/flash-core.c', 'persistent-flash/flash-qemu.c'}
    if set(value['persistent_model_sha256']) != core:
        raise ValueError('USB observer release must retain all three flash sources')
    for name, expected in {**value['build_public_sha256'], **value['persistent_model_sha256']}.items():
        path = HERE / name
        if (not re.fullmatch('[0-9a-f]{64}', expected) or path.is_symlink() or
                not path.is_file() or digest(path) != expected):
            raise ValueError('USB observer release source differs: ' + name)
    return value


def build(template, output):
    contract = source_contract()
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('USB observer build output must be fresh')
    output.mkdir(mode=0o700, parents=True)
    builder = runpy.run_path(str(HERE / 'persistent-flash/build.py'))
    # New reviewed source pins; upstream baseline and the old builder stay immutable.
    builder['build_qemu'].__globals__['USB_PUBLIC'] = contract['build_public_sha256']
    try:
        result = builder['build_qemu'](Path(template), output, production=True, usb_device=True)
        if source_contract() != contract:
            raise ValueError('USB observer release changed while building')
        result.update(status='compiled', generation_observer_release=contract)
        (output / 'qemu-result.json').write_text(json.dumps(result, indent=2) + '\n')
        return result
    except BaseException as error:
        (output / 'failure.json').write_text(json.dumps(dict(error=repr(error), guest_started=False), indent=2) + '\n')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.template, arguments.output), indent=2))
