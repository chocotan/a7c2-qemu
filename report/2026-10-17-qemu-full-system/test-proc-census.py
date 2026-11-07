#!/usr/bin/env python3
"""Run the actual census coordinator against an explicit host proc fixture."""
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class ProcCensusCoordinator(unittest.TestCase):
    def fixture(self, samples, fail=False):
        with tempfile.TemporaryDirectory(prefix='proc-census-host-only-') as temporary:
            root=Path(temporary);proc=root/'proc/123';proc.mkdir(parents=True)
            (proc/'comm').write_text('im.elf\n')
            (proc/'maps').write_text('70000000-71000000 r-xp 00000000 07:0b 1 /usr/lib/appFw.so\n')
            names=('AppFw','IWrapperImaging','IWrapperUPM','SeqThreadPool0','SeqThreadPool1','SeqThreadPool2','SeqThreadPool3','SeqQueueCommon')
            for tid,name in enumerate(names,200):
                task=proc/'task'/str(tid);task.mkdir(parents=True);(task/'comm').write_text(name+'\n')
            simulation=root/'simulation';simulation.mkdir();log=root/'log';log.mkdir()
            helper=simulation/'host-census.sh'
            helper.write_text('#!/bin/sh\necho "HOST_FIXTURE_CENSUS pid=$1 base=$2"\necho FULLSYSTEM_STACK_CENSUS_DONE count=8 failures='+('1' if fail else '0')+'\necho FULLSYSTEM_AUTO_STACKS_DONE='+('1' if fail else '0')+'\nexit '+('1' if fail else '0')+'\n')
            helper.chmod(0o755)
            source=(HERE/'guest/proc-census.sh').read_text()
            source=source.replace('/proc/',str(root/'proc')+'/').replace('/simulation/',str(simulation)+'/')
            source=source.replace('/log/qemu/',str(log)+'/').replace('> /dev/kmsg','>> "'+str(root/'kmsg')+'"')
            source=source.replace('sleep 30',': HOST_FIXTURE_NO_SLEEP').replace('sleep 1',': HOST_FIXTURE_NO_SLEEP')
            script=root/'coordinator.sh';script.write_text(source)
            result=subprocess.run(['/bin/sh',str(script),'0',str(samples)],capture_output=True,timeout=5)
            return result,(root/'kmsg').read_text(),list(log.iterdir())

    def test_two_samples_same_identity_and_single_final_result(self):
        result,log,leftovers=self.fixture(2)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(log.count('HOST_FIXTURE_CENSUS pid=123 base=0x70000000'),2)
        self.assertIn('SAMPLE_DONE sample=1 pid=123 rc=0 output_rc=0',log)
        self.assertIn('SAMPLE_DONE sample=2 pid=123 rc=0 output_rc=0',log)
        self.assertEqual(log.count('FULLSYSTEM_AUTO_STACKS_DONE='),1)
        self.assertTrue(log.endswith('FULLSYSTEM_AUTO_STACKS_DONE=0\n'))
        self.assertEqual(leftovers,[])

    def test_failure_not_hidden_by_successful_output_pipeline(self):
        result,log,leftovers=self.fixture(2,True)
        self.assertEqual(result.returncode,2)
        self.assertIn('rc=1 output_rc=0',log)
        self.assertTrue(log.endswith('FULLSYSTEM_AUTO_STACKS_DONE=2\n'))
        self.assertEqual(leftovers,[])


if __name__=='__main__':unittest.main()
