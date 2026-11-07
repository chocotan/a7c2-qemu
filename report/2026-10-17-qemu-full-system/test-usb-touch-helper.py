#!/usr/bin/env python3
"""Public source-contract tests; no VM, firmware image or private log dependency."""
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SCOPE = runpy.run_path(str(HERE / 'usb-touch-scope.py'))


class TouchScope(unittest.TestCase):
    def test_default_and_unknown_selections(self):
        self.assertIsNone(SCOPE['prepare']())
        for profile in ('', False, 0, 'guess'):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                SCOPE['prepare'](profile, HERE / 'absent-ap', HERE / 'absent-cp')
        with self.assertRaises(ValueError):
            SCOPE['prepare'](None, HERE / 'absent-ap', None)

    def test_off_source_is_unchanged(self):
        original = 'static const char *mirrored[] = {0};\n'
        self.assertEqual(SCOPE['derive'](original, None), original)

    def test_profile_cannot_mint_actual_or_hardware_evidence(self):
        receipt = SCOPE['prepare']()
        self.assertIsNone(SCOPE['validate']({}, 'strict'))
        with self.assertRaises(ValueError):
            SCOPE['validate']({'usb_touch': {'profile': SCOPE['PROFILE']}},
                              'virtual-functional-camera-usb-service-v1')
    def test_combined_scope_keeps_legacy_receipt_and_binds_exact_tcin_sources(self):
        def bound(path, pin):
            return dict(path=str(path), bytes=pin[0], sha256=pin[1])
        with patch.dict(SCOPE['prepare'].__globals__, binding=bound):
            old = SCOPE['prepare'](SCOPE['PROFILE'], Path('/fixture/ap'), Path('/fixture/cp'))
            combined = SCOPE['prepare'](SCOPE['TCIN_PROFILE'], Path('/fixture/ap'), Path('/fixture/cp'))
            self.assertNotIn('tcin', old)
            self.assertEqual(set(old['model_sources']), set(SCOPE['MODELS']))
            self.assertEqual(set(combined['model_sources']), set(SCOPE['MODELS']) | set(SCOPE['TCIN_MODELS']))
            self.assertEqual(combined['assets'], old['assets'])
            self.assertEqual(combined['contract'], old['contract'])
            self.assertEqual(combined['tcin']['request_raw'], '0d2029040a0001800000')
            self.assertEqual(combined['tcin']['reply_raw'], '0d2029140c00018000000000')
            self.assertFalse(combined['tcin']['original_cp_executed'])
            self.assertFalse(combined['tcin']['hardware_tcin_verified'])
            for profile in ('strict', 'virtual-functional-camera-v1', 'virtual-functional-camera-usb-monitor-v1'):
                with self.assertRaises(ValueError):
                    SCOPE['validate']({'usb_touch': combined}, profile)
            self.assertEqual(SCOPE['validate']({'usb_touch': combined}, 'virtual-functional-camera-usb-service-v1'), combined)
            combined['tcin']['active_virtual'] = 1
            with self.assertRaises(ValueError):
                SCOPE['validate']({'usb_touch': combined}, 'virtual-functional-camera-usb-service-v1')

    def test_derived_provider_routes_and_owned_free_are_only_explicit(self):
        source = ('static const char *mirrored[] = {0};\n'
                  'int osal_free_msg(unsigned int id, void *message) {\nreturn 0; }\n'
                  'void send(void) {\n    full_file_media_before_send(id,real_dlsym,record);\n}\n')
        def plan(profile):
            return dict(schema='a7c2.usb-touch-scope.v1', profile=profile)
        old = SCOPE['derive'](source, plan(SCOPE['PROFILE']))
        self.assertNotIn('tcin', old)
        combined = SCOPE['derive'](source, plan(SCOPE['TCIN_PROFILE']))
        for text in ('#include "tcin-device.h"', 'full_tcin_dispatch(id,message,&io,1,&result)',
                     'full_tcin_release_reply(id,message,real_free_msg,record,&result)', '"FULL_TCIN_"',
                     'full_touch_panel_dispatch(id,message,&io,1,&result)',
                     'full_touch_panel_release_reply(id,message,real_free_msg,record,&result)'):
            self.assertEqual(combined.count(text), 1, text)
        self.assertEqual(combined.count('!strcmp(getenv("FULLSYSTEM_USB_TOUCH"),"virtual-config-tcin-inactive-v1")'), 2)
        for text in ('MENU_CP_BACKGROUND', 'MENU_UDATE_DISTRIBUTION', 'MENU_TCIN_DETECT', '0x3007', '0x302c'):
            self.assertNotIn(text, combined)
        with self.assertRaises(ValueError):
            SCOPE['derive'](combined, plan(SCOPE['TCIN_PROFILE']))
        with self.assertRaises(ValueError):
            SCOPE['derive'](source + source, plan(SCOPE['TCIN_PROFILE']))

    def test_profile_callers_propagate_and_pin_the_same_selection(self):
        for name in ('usb-control-start.py', 'build-full-system.py', 'guest/bootin-wrapper'):
            self.assertIn(SCOPE['TCIN_PROFILE'], (HERE / name).read_text())
        self.assertIn("'fullsystem.usb-touch='+touch_receipt['profile']", (HERE / 'persistent-camera-profile.py').read_text())
        build = (HERE / 'build-imaging.py').read_text()
        self.assertIn("for name in touch_receipt['model_sources'] if name.endswith('.c')", build)
        wrapper = (HERE / 'guest/bootin-wrapper').read_text()
        self.assertLess(wrapper.index('unset MENU_TCIN_DETECT'), wrapper.index('case "$usb_touch_count:$usb_touch_mode"'))
        self.assertIn('FULLSYSTEM_USB_TOUCH_DUPLICATE', wrapper)
        self.assertIn('FULLSYSTEM_USB_TOUCH_REQUIRES_SERVICE', wrapper)
        self.assertIn('FULLSYSTEM_USB_TOUCH_APP_IDENTITY_FAILED', wrapper)

    def test_touch_generation_published_before_native_contract_read(self):
        import ast
        tree = ast.parse((HERE / 'usb-control-start.py').read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'prepare_helpers')
        calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
        publish = [node.lineno for node in calls if isinstance(node.func, ast.Attribute)
                   and isinstance(node.func.value, ast.Name) and node.func.value.id == 'manifest_path'
                   and node.func.attr == 'write_text']
        native_read = [node.lineno for node in calls if isinstance(node.func, ast.Subscript)
                       and isinstance(node.func.value, ast.Name) and node.func.value.id == 'START'
                       and isinstance(node.func.slice, ast.Constant) and node.func.slice.value == 'prepare']
        self.assertEqual(len(publish), len(native_read) + 1)
        self.assertEqual(len(native_read), 1)
        self.assertLess(publish[0], native_read[0])
        self.assertLess(native_read[0], publish[1])
        self.assertIn("['observer_bytes'] = native.stat().st_size", (HERE / 'usb-control-start.py').read_text())
        builds = [node for node in calls if isinstance(node.func, ast.Subscript)
                  and isinstance(node.func.value, ast.Call) and isinstance(node.func.value.func, ast.Attribute)
                  and node.func.value.func.attr == 'run_path'
                  and isinstance(node.func.slice, ast.Constant) and node.func.slice.value == 'build']
        self.assertEqual(len(builds), 1)
        claim = [kw for kw in builds[0].keywords if kw.arg == 'persistent_claim']
        self.assertEqual(len(claim), 1)
        self.assertIsInstance(claim[0].value, ast.Constant)
        self.assertIs(claim[0].value.value, True)


if __name__ == '__main__':
    unittest.main()
