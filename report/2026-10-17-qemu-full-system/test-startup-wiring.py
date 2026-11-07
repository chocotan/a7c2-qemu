import contextlib
import io
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


class Wiring(unittest.TestCase):
    def test_real_release_hooks_and_native_sources(self):
        text=(HERE/'build-imaging.py').read_text()
        for family in ('dmm','dig_level'):
            self.assertEqual(text.count('full_'+family+'_release_reply('),1)
            self.assertEqual(text.count('full_'+family+'_dispatch('),1)
        for filename in ('dmm-device.c','dmm-device.h','dig-level-device.c','dig-level-device.h'):
            self.assertIn(filename,text)
        for prefix in ('FULL_DMM_','FULL_DIG_LEVEL_'):self.assertIn(prefix,text)

    def test_fourth_and_fifth_edge_wiring(self):
        text=(HERE/'build-imaging.py').read_text()
        for family in ('full_hdmi_connection','full_adf_audio_connection'):
            for suffix in ('_dispatch(','_release('):
                self.assertIn(family+suffix,text)
        for filename in ('hdmi-connection.c','hdmi-connection.h','adf-audio-connection.c','adf-audio-connection.h'):
            self.assertIn(filename,text)
        for prefix in ('FULL_HDMI_CONNECT_','FULL_ADFAUDIO_'):self.assertIn(prefix,text)
        runner=(HERE/'run-full-system.py').read_text()
        for flag,value in (('--hdmi-connection','control'),('--adf-audio-connection','control')):
            self.assertIn("'"+flag+"',choices=('off','"+value+"'),default='off'",runner)
        for marker in ('fullsystem.hdmi-connect=control','fullsystem.adf-audio-connect=control'):
            self.assertIn(marker,runner)
        wrapper=(HERE/'guest/bootin-wrapper').read_text()
        for environment in ('FULLSYSTEM_HDMI_CONNECTION','FULLSYSTEM_ADF_AUDIO_CONNECTION'):
            self.assertLess(wrapper.index('unset '+environment),wrapper.index('export '+environment+'='))

    def test_osd_raster_busy_retry_is_derived_not_assumed(self):
        text=(HERE/'build-imaging.py').read_text()
        self.assertIn('raster-trylock',text)
        self.assertIn('status != 16',text)
        self.assertIn('usleep(2000)',text)
        # The base snapshot must stay untouched: derivation writes to output/.
        self.assertIn("osd_derived=output/'headless-osd.c'",text)
        for anchor in ("Ambiguous OSD errno declaration anchor","Ambiguous OSD raster trylock anchor",
                       "Ambiguous OSD busy-receive anchor"):
            self.assertIn(anchor,text)
        # A busy receive must release any handle it returned and retry, not latch.
        self.assertIn('if (message) o->release(queue, message);',text)
        self.assertIn('if (result == HOSD_TIMEOUT) {',text)

    def test_guest_opt_in_clears_inherited_environment(self):
        text=(HERE/'guest/bootin-wrapper').read_text()
        for environment,parameter in [('FULLSYSTEM_DIG_LEVEL','fullsystem.dig-level=virtual'),('FULLSYSTEM_DMM','fullsystem.dmm=unit-size')]:
            self.assertLess(text.index('unset '+environment),text.index('export '+environment+'='))
            self.assertIn(parameter,text)
        runner=(HERE/'run-full-system.py').read_text()
        self.assertIn("'--dig-level',choices=('off','virtual'),default='off'",runner)
        self.assertIn("'--dmm-service',choices=('off','unit-size'),default='off'",runner)

    @unittest.skipUnless((HERE/'runtime/native-input.json').is_file(),'requires prepared fixed native input for runner import')
    def test_service_opt_in_does_not_require_until_condition(self):
        main=runpy.run_path(str(HERE/'run-full-system.py'))['main']
        globals_=main.__globals__;old=globals_['BASE']
        with tempfile.TemporaryDirectory() as directory:
            globals_['BASE']=Path(directory)
            try:
                for flags in (['--dig-level','virtual'],['--dmm-service','unit-size']):
                    error=io.StringIO()
                    with self.subTest(flags=flags),patch.object(sys,'argv',['run-full-system.py','--stage','init2',*flags]),contextlib.redirect_stderr(error):
                        with self.assertRaises(SystemExit) as stopped:main()
                    self.assertEqual(stopped.exception.code,2)
                    self.assertIn('Prepare a private dump runtime first',error.getvalue())
            finally:globals_['BASE']=old


if __name__=='__main__':unittest.main()
