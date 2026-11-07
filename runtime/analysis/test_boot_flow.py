import copy
import hashlib
import itertools
import json
from pathlib import Path
import unittest

import boot_flow as flow


def predicates(**values):
    return {**dict.fromkeys(dict(flow.EVENT_MODES), False), **values}


class SelectorTests(unittest.TestCase):
    def test_table_matches_official_adjacent_metadata(self):
        metadata = json.loads(Path(__file__).with_name('sony-boot-2.01.json').read_text())
        loader = metadata['loader']
        self.assertEqual(loader['sha256'], flow.LOADER_SHA256)
        self.assertEqual(loader['selector'], '0xfe051230')
        self.assertEqual(tuple((e['name'], e['mode']) for e in loader['events']), flow.EVENT_MODES)
        self.assertEqual([e['event_id'] for e in loader['events'][14:17]], [15, 16, 14])
        self.assertEqual(loader['default_mode'], 1)

    def test_default_cold_requires_known_scanned_predicates(self):
        route = flow.select_route(predicates())
        self.assertEqual((route['status'], route['event'], route['mode']), ('selected', 'default', 1))
        values = predicates()
        del values['cldboot']
        self.assertEqual(flow.select_route(values)['missing'], ['cldboot'])

    def test_early_group_priority_ignores_later_unknowns(self):
        for index, (event, mode) in enumerate(flow.EVENT_MODES[:6]):
            with self.subTest(event=event):
                values = {name: False for name, _ in flow.EVENT_MODES[:index]}
                values[event] = True
                self.assertEqual(flow.select_route(values),
                                 dict(status='selected', missing=[], event=event, mode=mode))
        self.assertEqual(flow.select_route(predicates(updater=True, adjust=True, hotboot=True))['mode'], 3)

    def test_unknown_priority_cannot_be_assumed_false(self):
        for values, missing in [({}, 'updater'), ({'ssboot': True}, 'updater'),
                                (predicates(updater=None, ssboot=True), 'updater'),
                                (predicates(hotboot=None, ssboot=True), 'hotboot')]:
            with self.subTest(values=values):
                route = flow.select_route(values)
                self.assertEqual((route['status'], route['mode'], route['missing']), ('unknown', None, [missing]))

    def test_late_ram_hotboot_precedes_disk_wbi(self):
        self.assertEqual(flow.select_route(predicates(hotboot=True, ssboot=True))['mode'], 2)
        self.assertEqual(flow.select_route(predicates(ssboot=True, ss_bis=True))['event'], 'ssboot')
        self.assertEqual(flow.select_route(predicates(ss_bis=True))['mode'], 11)

    def test_control_predicates_have_no_standalone_priority(self):
        values = predicates(usbchrg=True, hoff_en=True, ddr_off=True, bi_vali=True, ssboot=True)
        self.assertEqual(flow.select_route(values)['mode'], 11)
        values.update(usbchrg=None, hoff_en=None, ddr_off=None, bi_vali=None)
        self.assertEqual(flow.select_route(values)['mode'], 11)

    def test_middle_usb_override_and_keychat_inhibit(self):
        cases = [(dict(panlopn=True, usbchrg=True), 6),
                 (dict(ontimrz=True, keychat=True, hoff_en=True, ddr_off=True, bi_vali=True), 7),
                 (dict(ontimrz=True, lowbatt=True, hoff_en=True, ddr_off=True, bi_vali=True), 7),
                 (dict(keychat=True, usbchrg=True), 6)]
        for values, mode in cases:
            with self.subTest(values=values):
                self.assertEqual(flow.select_route(predicates(**values))['mode'], mode)

    def test_middle_bi_valid_selects_13_otherwise_14(self):
        for valid, mode in [(True, 13), (False, 14), (None, None)]:
            route = flow.select_route(predicates(panlopn=True, hoff_en=True, ddr_off=True, bi_vali=valid))
            self.assertEqual(route['mode'], mode)
            self.assertEqual(route['status'], 'unknown' if valid is None else 'selected')

    def test_middle_irrelevant_unknowns_do_not_block(self):
        for values in [dict(ontimrz=True, keychat=None, lowbatt=None, hoff_en=False, ddr_off=None),
                       dict(ontimrz=True, keychat=None, hoff_en=None, ddr_off=False),
                       dict(keychat=True, hoff_en=None, ddr_off=None, bi_vali=None)]:
            with self.subTest(values=values):
                self.assertEqual(flow.select_route(predicates(**values))['mode'], 7)
        self.assertEqual(flow.select_route(predicates(ontimrz=True, usbchrg=None))['missing'], ['usbchrg'])

    def test_middle_three_state_gate_against_all_boolean_completions(self):
        keys = ('usbchrg', 'keychat', 'lowbatt', 'hoff_en', 'ddr_off', 'bi_vali')
        for values in itertools.product((False, True, None), repeat=len(keys)):
            unknowns = [i for i, v in enumerate(values) if v is None]
            possible = set()
            for replacement in itertools.product((False, True), repeat=len(unknowns)):
                completed = list(values)
                for index, value in zip(unknowns, replacement):
                    completed[index] = value
                usb, key, low, hoff, off, valid = completed
                possible.add(6 if usb else (13 if valid else 14) if not (key or low) and hoff and off else 7)
            route = flow.select_route(predicates(ontimrz=True, **dict(zip(keys, values))))
            with self.subTest(values=values):
                if len(possible) == 1:
                    self.assertEqual((route['status'], route['mode']), ('selected', possible.pop()))
                else:
                    self.assertEqual(route['status'], 'unknown')
                    self.assertTrue(route['missing'])

    def test_reject_misspelled_and_non_three_state_inputs(self):
        for values in [[], {'updater': 1}, {'updater': 'false'}, {'hot_boot': True}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                flow.select_route(values)


class ResumeTests(unittest.TestCase):
    def route(self, **values):
        return flow.select_route(predicates(**values))

    def test_default_mode_is_only_a_route_not_executed_cold(self):
        result = flow.resolve_resume(self.route(), None, None, None)
        self.assertEqual((result['path'], result['status']), ('cold', 'resolved'))
        self.assertNotIn('executed', result)

    def test_ram_hotboot_does_not_need_persistent_wbi_but_needs_bound_ram(self):
        route = self.route(hotboot=True)
        result = flow.resolve_resume(route, None, None, None)
        self.assertEqual((result['path'], result['status']), ('ram-hotboot', 'unknown'))
        self.assertEqual(result['missing'], ['retained_ram_bound'])
        self.assertEqual(flow.resolve_resume(route, None, None, None, True)['status'], 'resolved')

    def test_mode11_gate_and_missing_backend(self):
        route = self.route(ssboot=True)
        cases = [(None, None, None, 'unknown', None),
                 (False, None, None, 'resolved', 'wbi-resume'),
                 (True, 0, None, 'resolved', 'wbi-resume'),
                 (True, 3, True, 'resolved', 'wbi-resume'),
                 (True, 1, False, 'resolved', 'wbi-resume'),
                 (True, None, True, 'unknown', None),
                 (True, 1, None, 'unknown', None),
                 (True, 1, True, 'unknown', 'ram-hotboot'),
                 (True, 2, True, 'unknown', 'ram-hotboot')]
        for read, ld, h, status, path in cases:
            with self.subTest(read=read, ld=ld, h=h):
                result = flow.resolve_resume(route, read, ld, h)
                self.assertEqual((result['status'], result['path']), (status, path))
        self.assertEqual(flow.resolve_resume(route, True, 2, True, True)['path'], 'ram-hotboot')
        self.assertEqual(flow.resolve_resume(route, True, None, False)['path'], 'wbi-resume')

    def test_unknown_route_and_other_modes_never_guess_cold(self):
        for route in [flow.select_route({}), self.route(adjust=True), self.route(updater=True)]:
            result = flow.resolve_resume(route, None, None, None)
            self.assertEqual(result['status'], 'unknown')
            self.assertIsNone(result['path'])

    def test_resume_input_validation(self):
        for args in [(None, None, None, None), (self.route(), 1, None, None),
                     (self.route(), True, True, None), (self.route(), True, -1, None),
                     (self.route(), True, 2**32, None), (self.route(), True, 1, 2)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                flow.resolve_resume(*args)


class CoverageTests(unittest.TestCase):
    def receipt(self, profile='original-init-cold', **kwargs):
        return flow.new_receipt(profile, bindings={'run': 'run-new', 'source_class': 'private-device-dump',
                                'kernel_sha256': '1' * 64, 'ap_sha256': '2' * 64},
                                kernel_cmdline='console=ttyAMA0 init=/sbin/init', **kwargs)

    def evidence(self, receipt, stage, **values):
        classes = receipt['bindings']['source_class']
        return dict(run=receipt['bindings']['run'], generation=receipt['generation'],
                    binding_digest=receipt['binding_digest'], source='guest',
                    source_class=classes[stage] if isinstance(classes, dict) else classes,
                    artifacts=[dict(path=stage + '.log', sha256=hashlib.sha256(stage.encode()).hexdigest())],
                    cmdline=receipt['kernel_cmdline'], **values)

    def add(self, receipt, stage, kind='guest_original', status='passed', **changes):
        evidence = self.evidence(receipt, stage)
        if kind in ('host_declared', 'host_functional'):
            evidence['source'] = 'host'
        evidence.update(changes)
        flow.record_stage(receipt, stage, execution_kind=kind, status=status, evidence=evidence)

    def complete(self, profile='original-init-cold', omit=()):
        receipt = self.receipt(profile)
        for stage in flow.STAGES:
            if stage not in omit:
                self.add(receipt, stage, kind='guest_adapter' if stage == 'backend' else 'guest_original')
        return receipt

    def test_new_receipt_has_no_execution_and_requires_identity(self):
        receipt = self.receipt()
        self.assertEqual(receipt['stages'], [])
        result = flow.evaluate(receipt)
        self.assertFalse(result['full_boot_verified'])
        self.assertFalse(any(result['stage_verified'].values()))
        self.assertTrue(result['blockers'])
        for changes in [dict(profile='unknown'), dict(generation=-1), dict(generation=True),
                        dict(bindings={}), dict(bindings={'run': 'x'}),
                        dict(bindings={'run': 'x', 'source_class': {}}), dict(kernel_cmdline=[])]:
            args = dict(profile='direct-bootin', bindings={'run': 'x', 'source_class': 'sony_original'})
            args.update(changes)
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                flow.new_receipt(**args)

    def test_language_page_or_ap_alone_is_only_partial(self):
        receipt = self.receipt('direct-bootin')
        self.add(receipt, 'ap')
        result = flow.evaluate(receipt)
        self.assertTrue(result['ap_verified'])
        self.assertFalse(result['cold_guest_chain_verified'])
        self.assertFalse(result['full_boot_verified'])
        self.assertFalse(flow.evaluate(self.complete('direct-bootin'))['full_boot_verified'])

    def test_complete_bound_original_cold_chain_can_pass(self):
        receipt = self.complete()
        result = flow.evaluate(json.loads(json.dumps(receipt)))
        self.assertTrue(result['cold_guest_chain_verified'])
        self.assertTrue(result['full_boot_verified'])
        self.assertEqual(result['blockers'], [])
        self.assertEqual(result['source_class'], 'private-device-dump')

    def test_chroot_pivot_init2_cp_and_backend_are_not_optional(self):
        for stage in ('chroot', 'pivot_root', 'old_root_unmounted', 'ram0_release', 'init2', 'cp', 'loader', 'watchdog', 'backend', 'kernelargs'):
            with self.subTest(stage=stage):
                result = flow.evaluate(self.complete(omit=(stage,)))
                self.assertFalse(result['full_boot_verified'])
                self.assertTrue(any(b.startswith(stage + ':') for b in result['blockers']))
                self.assertEqual(result['cold_guest_chain_verified'], stage not in flow.COLD_STAGES)

    def test_resume_requires_original_path_and_actual_backend(self):
        for profile, stage in [('ram-hotboot', 'ram_hotboot'), ('wbi-resume', 'wbi')]:
            for missing in (stage, 'backend', 'cp'):
                with self.subTest(profile=profile, missing=missing):
                    self.assertFalse(flow.evaluate(self.complete(profile, omit=(missing,)))['full_boot_verified'])
            self.assertTrue(flow.evaluate(self.complete(profile))['full_boot_verified'])
            self.assertFalse(flow.evaluate(self.complete(profile))['cold_guest_chain_verified'])

    def test_sd_install_needs_receiver_readback_reset_and_cold_chain(self):
        for stage in ('sd_receiver', 'sd_install', 'sd_readback', 'post_reset', 'chroot'):
            with self.subTest(stage=stage):
                self.assertFalse(flow.evaluate(self.complete('sd-update', omit=(stage,)))['full_boot_verified'])
        self.assertTrue(flow.evaluate(self.complete('sd-update'))['full_boot_verified'])

    def test_host_functional_install_is_separate_from_original_receiver(self):
        receipt = self.complete('sd-update', omit=('sd_install',))
        self.add(receipt, 'sd_install', kind='host_functional')
        result = flow.evaluate(receipt)
        self.assertTrue(result['host_functional_install_verified'])
        self.assertFalse(result['stage_verified']['sd_install'])
        self.assertFalse(result['full_boot_verified'])
        self.add(receipt, 'sd_receiver', kind='host_functional')
        self.assertFalse(flow.evaluate(receipt)['stage_verified']['sd_receiver'])

    def test_host_plan_and_argument_seed_cannot_be_guest_execution(self):
        receipt = self.receipt()
        for stage in flow.STAGES:
            self.add(receipt, stage, kind='host_declared')
        result = flow.evaluate(receipt)
        self.assertFalse(any(result['stage_verified'].values()))
        self.assertFalse(result['cold_guest_chain_verified'])
        self.assertFalse(result['full_boot_verified'])

    def test_adapter_does_not_replace_original_chroot_or_cp(self):
        receipt = self.complete()
        for stage in ('chroot', 'cp'):
            self.add(receipt, stage, kind='guest_adapter')
        result = flow.evaluate(receipt)
        self.assertTrue(result['stage_verified']['backend'])
        self.assertFalse(result['stage_verified']['chroot'])
        self.assertFalse(result['stage_verified']['cp'])
        self.assertFalse(result['full_boot_verified'])

    def test_kernelargs_requires_guest_observation_and_matches_requested_args(self):
        receipt = self.complete(omit=('kernelargs',))
        self.add(receipt, 'kernelargs', kind='host_observed', source='host')
        self.assertFalse(flow.evaluate(receipt)['stage_verified']['kernelargs'])
        self.add(receipt, 'kernelargs', kind='host_observed', cmdline='init=/bin/sh')
        self.assertFalse(flow.evaluate(receipt)['stage_verified']['kernelargs'])
        self.add(receipt, 'kernelargs', kind='host_observed')
        self.assertTrue(flow.evaluate(receipt)['full_boot_verified'])

    def test_watchdog_blacklist_blocks_full_even_if_stage_claims_passed(self):
        receipt = self.receipt()
        receipt['kernel_cmdline'] += ' initcall_blacklist=__boottime___udif_init_udif_wdt'
        receipt = flow.new_receipt(receipt['profile'], bindings=receipt['bindings'], kernel_cmdline=receipt['kernel_cmdline'])
        for stage in flow.STAGES:
            self.add(receipt, stage)
        result = flow.evaluate(receipt)
        self.assertTrue(result['cold_guest_chain_verified'])
        self.assertFalse(result['full_boot_verified'])
        self.assertTrue(any('bypassed' in b for b in result['blockers']))

    def test_reject_old_run_generation_or_binding_at_record_time(self):
        receipt = self.receipt(generation=2)
        for key, value in [('run', 'run-old'), ('generation', 1), ('generation', True), ('binding_digest', '0' * 64)]:
            evidence = self.evidence(receipt, 'ap'); evidence[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                flow.record_stage(receipt, 'ap', execution_kind='guest_original', status='passed', evidence=evidence)
        self.assertEqual(receipt['stages'], [])

    def test_evaluate_does_not_adopt_old_records_from_persisted_receipt(self):
        old = self.complete()
        current = self.receipt(generation=1)
        current['stages'] = copy.deepcopy(old['stages'])
        result = flow.evaluate(current)
        self.assertFalse(any(result['stage_verified'].values()))
        self.assertTrue(result['blockers'][0].startswith('invalid receipt:'))
        self.assertFalse(result['host_functional_install_verified'])

    def test_mutating_bindings_profile_or_generation_invalidates_receipt(self):
        for key, value in [('profile', 'wbi-resume'), ('generation', 1),
                           ('kernel_cmdline', 'init=/bin/sh'),
                           ('bindings', {'run': 'run-new', 'source_class': 'sony_original'})]:
            receipt = self.complete(); receipt[key] = value
            with self.subTest(key=key):
                self.assertFalse(flow.evaluate(receipt)['full_boot_verified'])
                with self.assertRaises(ValueError):
                    self.add(receipt, 'ap')

    def test_source_classes_are_bound_per_stage_and_never_relabel_dump(self):
        binding = self.receipt()['bindings']
        binding['source_class'] = {stage: 'sony_original' for stage in flow.STAGES}
        binding['source_class']['ap'] = 'private-device-dump'
        receipt = flow.new_receipt('original-init-cold', bindings=binding)
        self.add(receipt, 'ap')
        self.assertEqual(flow.evaluate(receipt)['source_class']['ap'], 'private-device-dump')
        evidence = self.evidence(receipt, 'ap'); evidence['source_class'] = 'sony_original'
        with self.assertRaisesRegex(ValueError, 'source_class'):
            flow.record_stage(receipt, 'ap', execution_kind='guest_original', status='passed', evidence=evidence)
        receipt['bindings']['source_class']['ap'] = 'sony_original'
        self.assertFalse(flow.evaluate(receipt)['ap_verified'])

    def test_status_retry_preserves_failures_and_later_failure_blocks(self):
        receipt = self.complete()
        self.add(receipt, 'ap', status='failed')
        self.assertFalse(flow.evaluate(receipt)['ap_verified'])
        self.add(receipt, 'ap')
        self.assertTrue(flow.evaluate(receipt)['full_boot_verified'])
        self.assertEqual([s['status'] for s in receipt['stages'] if s['stage'] == 'ap'],
                         ['passed', 'failed', 'passed'])

    def test_reject_unhashed_empty_mismatched_source_and_invalid_records(self):
        receipt = self.receipt()
        for changes in [dict(artifacts=[]), dict(artifacts=[{'path': 'x', 'sha256': 'bad'}]),
                        dict(source='host'), dict(source_class='sony_original')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.add(receipt, 'ap', **changes)
        for changes in [dict(stage='CP'), dict(execution_kind='fake'), dict(status='executed'),
                        dict(input_sha256='bad'), dict(output_sha256='bad')]:
            args = dict(stage='ap', execution_kind='guest_original', status='passed', evidence=self.evidence(receipt, 'ap'))
            args.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                flow.record_stage(receipt, **args)
        with self.assertRaises(ValueError):
            self.add(receipt, 'ap', kind='host_declared', source='guest')

    def test_malformed_receipt_blocks_instead_of_silently_passing(self):
        for receipt in [None, {}, {'bindings': 'bad'}, {'profile': [], 'bindings': {}},
                        {**self.complete(), 'stages': [{'stage': 'ap'}]}]:
            with self.subTest(receipt=receipt):
                result = flow.evaluate(receipt)
                self.assertFalse(result['full_boot_verified'])
                self.assertFalse(any(result['stage_verified'].values()))
                self.assertTrue(result['blockers'])

    def test_receipt_and_evidence_do_not_alias_caller_owned_values(self):
        bindings = self.receipt()['bindings']
        receipt = flow.new_receipt('direct-bootin', bindings=bindings)
        bindings['source_class'] = 'sony_original'
        evidence = self.evidence(receipt, 'ap')
        flow.record_stage(receipt, 'ap', execution_kind='guest_original', status='passed', evidence=evidence)
        evidence['artifacts'].clear()
        self.assertTrue(flow.evaluate(receipt)['ap_verified'])
        self.assertEqual(receipt['bindings']['source_class'], 'private-device-dump')


if __name__ == '__main__':
    unittest.main()
