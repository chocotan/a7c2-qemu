"""GNU patch auto-direction must not masquerade as an already applied RC patch."""
from pathlib import Path
import shutil
import subprocess

HERE=Path(__file__).resolve().parent


def test_forced_reverse_detects_and_stages_both_patches(tmp_path):
    source=HERE/'../../source/build/qemu-pcidma-work/qemu-11.1.2'
    for relative in ('hw/arm/virt.c','hw/misc/meson.build','hw/intc/arm_gic_common.c','include/hw/intc/arm_gic_common.h',
                     'hw/misc/sony-pcidma/sony_regfile.c'):
        destination=tmp_path/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/relative,destination)

    def patch(name,reverse=False,dry=False):
        command=['patch','--batch','--force','--fuzz=0','-p1','-d',str(tmp_path)]
        if reverse:command+=['--reverse']
        if dry:command+=['--dry-run']
        with (HERE/'device-models'/f'{name}.patch').open('rb') as data:
            return subprocess.run(command,stdin=data,capture_output=True)

    for name in ('sa-reference-complete','sa-data-only','regfile-trace-only','sa-trace','cp-config-page','gic-loader-handoff','gic-readback','rc-data','rc-board'):
        if patch(name,reverse=True,dry=True).returncode==0:
            assert patch(name,reverse=True).returncode==0
    for name in ('rc-board','rc-data','gic-readback','gic-loader-handoff','cp-config-page','sa-trace','regfile-trace-only','sa-data-only','sa-reference-complete'):
        assert patch(name,reverse=True,dry=True).returncode!=0
        assert patch(name,dry=True).returncode==0
        assert patch(name).returncode==0
        assert patch(name,reverse=True,dry=True).returncode==0
    text=(tmp_path/'hw/arm/virt.c').read_text()
    assert text.count('SONY_RC_REFERENCE_V1 packing=unverified engines=B,C')==1
    assert text.count('SONY_RC_BOARD_V2 gpex_spi_base=244')==1
    assert text.count('SONY_GIC_HANDOFF_V1 spi-default=cpu0')==1
    assert (tmp_path/'hw/intc/arm_gic_common.c').read_text().count('"sony-debug-state"')==1
    for name in ('rc-board','rc-data','gic-readback','gic-loader-handoff','cp-config-page','sa-trace','regfile-trace-only','sa-data-only','sa-reference-complete'):
        assert patch(name,reverse=True,dry=True).returncode==0,name
