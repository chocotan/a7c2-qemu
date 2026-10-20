#!/usr/bin/env python3
"""Real two-ON/OFF SD check; seed must contain the firmware-created database/XML."""
import argparse
import json
import os
from pathlib import Path
import time
from menu_control import VM
from sd_transport import card_source,digest_fd


def sha(path):
    with card_source(path) as fd:return digest_fd(fd)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed',type=Path,required=True)
    args=parser.parse_args();initial=args.seed.absolute()
    os.environ['A7C2_SD_IMAGE']=str(initial)
    original=sha(initial);expected=initial
    vm=VM(native_display='none',natural_boot=True)
    def wait_state(wanted,seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            state=vm.status()
            if state['state']=='error':raise RuntimeError(state['error']+' '+state['log'])
            if wanted=='exited' and state['state']=='running' and state['sd_export'] and not state['sd_export'].get('ok'):
                raise RuntimeError(str(state['sd_export']))
            if state['state']==wanted:return state
            time.sleep(.1)
        raise TimeoutError(str(vm.status()))
    try:
        for cycle in (1,2):
            source_sha=sha(expected);vm.start();state=wait_state('running',420)
            run=Path(state['run']);proof={'ok':False,'cycle':cycle,'same_VM_object':True,'seed_sha256':source_sha}
            try:
                manifest=json.loads((run/'runtime-manifest.json').read_text())
                assert manifest['virtual_sd_seed']==str(expected)
                assert manifest['virtual_sd_seed_sha256']==source_sha
                assert manifest['selected_initramfs_verified_files']['simulation/sd-card.fat']==source_sha
                log=(run/'console.log').read_text(errors='replace')
                for name in ('DATABASE/DATABASE.BIN','M4ROOT/MEDIAPRO.XML'):
                    assert any('op=Open path=A:/PRIVATE/'+name in line and 'result=0 ' in line for line in log.splitlines()),'seed lacks opened original '+name
                assert not any('op=Write' in line and 'flags=0x939000' in line for line in log.splitlines())
                vm.stop();state=wait_state('exited',180)
                card=run/'SD/card.img';saved=json.loads((run/'SD/export.json').read_text())
                assert state['sd_export']['ok'] and saved['ok'] and saved['fsck_rc']==0
                assert sha(card)==saved['sha256'] and vm.card_seed==card and sha(initial)==original
                proof.update(ok=True,original_database_opened=True,original_database_not_recreated=True,
                             OFF_saved_card=True,saved_sha256=saved['sha256'],original_input_unchanged=True)
                expected=card
                print('SAME_CONSOLE_SD_CYCLE_PASS',run,json.dumps(proof),flush=True)
            except BaseException as error:
                proof['error']=f'{type(error).__name__}: {error}'
                raise
            finally:(run/'sd-console-cycle-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    finally:vm.close()


if __name__=='__main__':main()
