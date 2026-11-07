from pathlib import Path
import runpy
import tempfile
import unittest

API=runpy.run_path(str(Path(__file__).resolve().parent/'run-full-system.py'))


class PlannedCommandTest(unittest.TestCase):
    def test_guest_readback_requires_hash_and_success(self):
        expected='a'*64
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            response=('SHA2-256(/marker)= '+expected+'\nMENU_DIAG_COMMAND_DONE_test:0\n').encode()
            rows=API['verify_guest_overwrite'](lambda command,timeout:response,[{'path':'/marker','sha256':expected}],out)
            self.assertTrue(rows[0]['verified'])
            failed=response.replace(b':0\n',b':1\n')
            with self.assertRaisesRegex(RuntimeError,'readback differs'):
                API['verify_guest_overwrite'](lambda command,timeout:failed,[{'path':'/marker','sha256':expected}],out)

    def test_wrong_guest_hash_stops_before_second_file(self):
        calls=[]
        def run(command,timeout):
            calls.append(command)
            return ('SHA2-256(/marker)= '+'b'*64+'\nMENU_DIAG_COMMAND_DONE_test:0\n').encode()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                API['verify_guest_overwrite'](run,[{'path':'/one','sha256':'a'*64},{'path':'/two','sha256':'a'*64}],Path(directory))
        self.assertEqual(len(calls),1)

    def test_protocol_loss_stops_before_later_step(self):
        calls=[]
        def run(command,timeout):
            calls.append(command)
            raise RuntimeError('missing completion marker')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'key-plan.log'
            with self.assertRaisesRegex(RuntimeError,'completion marker'):
                for at,command in ((30,'first'),(35,'must not run')):
                    API['execute_planned_command'](run,at,command,path)
            self.assertEqual(calls,['first'])
            self.assertIn('missing completion marker',path.read_text())
            self.assertNotIn('must not run',path.read_text())


if __name__=='__main__':unittest.main()
