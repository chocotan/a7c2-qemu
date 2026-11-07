#!/usr/bin/env python3
"""Boundary tests for the CP media-state packet probe.

The packet layout is verified (CP `cpapp-b.bin 0xb0f4a0` builds
`[02 00 00, enable, rm1, rm2, rm3]`), so these tests pin the parts that must not
drift: byte0/1/2, the 7-byte length, and the plan shape.
"""
import importlib.util
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('probe_cp_rm_notify',HERE/'probe-cp-rm-notify.py')
PROBE=importlib.util.module_from_spec(spec);spec.loader.exec_module(PROBE)


class Packets(unittest.TestCase):
    def test_every_packet_is_seven_bytes_with_the_verified_header(self):
        self.assertEqual(len(PROBE.PACKETS),3)
        for label,packet in PROBE.PACKETS:
            with self.subTest(case=label):
                self.assertEqual(len(packet),7)
                self.assertEqual(packet[0],2,'byte0 is the event type the consumer checks')
                self.assertEqual(packet[1],0,'byte1 is explicitly stored zero by the producer')
                self.assertEqual(packet[2],0,'byte2 is explicitly stored zero by the producer')

    def test_enable_candidates_cover_both_masks_and_the_state_byte_marks_presence(self):
        masks={label:packet[3] for label,packet in PROBE.PACKETS}
        self.assertIn(0x07,masks.values())
        self.assertIn(0x03,masks.values())
        # port_state is bit1 of the RM state byte: RM2 present -> 0x02.
        card=[packet for label,packet in PROBE.PACKETS if 'rm2-card' in label]
        self.assertTrue(card)
        for packet in card:
            self.assertEqual(packet[5],0x02)
            self.assertEqual(packet[4],0x00)
            self.assertEqual(packet[6],0x00)

    def test_the_command_is_the_guest_helper_with_seven_arguments(self):
        command=PROBE.packet_command(PROBE.PACKETS[0][1])
        self.assertTrue(command.startswith('/simulation/cp-rm-notify '))
        self.assertEqual(len(command.split()),8)


class Plan(unittest.TestCase):
    def test_one_publish_per_candidate_in_ascending_absolute_time(self):
        plan=PROBE.notify_plan(500.0,45.0)
        self.assertEqual(len(plan),len(PROBE.PACKETS))
        times=[float(entry.partition(':')[0]) for entry in plan]
        self.assertEqual(times,sorted(times))
        self.assertEqual(times,[500.0,545.0,590.0])
        for index,(_label,packet) in enumerate(PROBE.PACKETS):
            self.assertTrue(plan[index].endswith(PROBE.packet_command(packet)))

    def test_the_plan_entries_are_single_commands(self):
        # The runner splits the plan on ';', so a command containing ';' (for example
        # "echo label; helper ...") becomes a timestamp-less fragment and the whole
        # plan is refused -- that is how the first run of this probe (run-zn_1r4gy)
        # lost its publishes and reported an invalid experiment.
        for entry in PROBE.notify_plan(500.0,45.0):
            self.assertNotIn(';',entry)
            self.assertNotIn('$',entry)
            self.assertNotIn('&&',entry)


if __name__=='__main__':unittest.main()
