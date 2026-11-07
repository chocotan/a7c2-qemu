#!/usr/bin/env python3
"""Boundary tests for the full-control sweep plan.

The sweep exists so "every button and dial works" is checked rather than
assumed. These tests pin the two ways it could silently under-report: a control
the UI exports but the sweep never clicks, and geometry-addressed controls being
clicked at a point that does not select anything.
"""
import importlib.util
import math
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('check_live_ui',HERE/'check-live-ui.py')
CHECK=importlib.util.module_from_spec(spec);spec.loader.exec_module(CHECK)

# The twenty controls the UI exported when this sweep was written.
EXPORTED={'front_dial_0':[928.0,49.0],'front_dial_1':[980.0,49.0],'mode_dial':[742.0,86.0],
          'rec':[878.0,96.0],'shutter':[958.0,96.0],'power':[1019.0,86.0],
          'reartop_dial_0':[889.0,157.0],'reartop_dial_1':[945.0,157.0],
          'seg_still':[666.0,168.0],'seg_movie':[738.0,168.0],'seg_sq':[810.0,168.0],
          'menu':[623.0,232.0],'c1':[726.0,232.0],'rear_dial_0':[789.0,232.0],
          'rear_dial_1':[845.0,232.0],'af_on':[838.0,336.0],'fn':[838.0,412.0],
          'wheel':[880.0,586.0],'play':[838.0,724.0],'delete':[950.0,724.0]}


class SweepPlan(unittest.TestCase):
    def test_every_exported_control_is_covered_or_explicitly_excluded(self):
        sweep=CHECK.build_sweep(EXPORTED)
        labels={label for label,_,_,_ in sweep}
        accounted=labels|CHECK.GEOMETRY_CONTROLS|CHECK.LIFECYCLE_CONTROLS
        self.assertEqual(set(EXPORTED)-accounted,set())

    def test_a_newly_exported_control_fails_instead_of_being_skipped(self):
        with self.assertRaisesRegex(ValueError,'not covered'):
            CHECK.build_sweep({**EXPORTED,'c2':[700.0,232.0]})

    def test_button_controls_use_the_exported_centre_and_original_code(self):
        sweep=dict((label,(x,y,code)) for label,x,y,code in CHECK.build_sweep(EXPORTED))
        for name,code in CHECK.BUTTON_CODES:
            with self.subTest(control=name):
                self.assertEqual(sweep[name][:2],tuple(EXPORTED[name]))
                self.assertEqual(sweep[name][2],code)

    def test_power_and_shutter_are_left_to_their_own_acceptance(self):
        labels={label for label,_,_,_ in CHECK.build_sweep(EXPORTED)}
        for name in CHECK.LIFECYCLE_CONTROLS:
            self.assertNotIn(name,labels)

    def test_mode_positions_land_inside_the_dial_and_use_the_original_code(self):
        sweep=dict((label,(x,y,code)) for label,x,y,code in CHECK.build_sweep(EXPORTED))
        self.assertEqual(len(CHECK.MODE_ORDER),8)
        cx,cy=CHECK.MODE_DIAL_CENTER
        for index,mode in enumerate(CHECK.MODE_ORDER):
            with self.subTest(mode=mode):
                x,y,code=sweep['mode-'+mode]
                self.assertLess(math.hypot(x-cx,y-cy),CHECK.MODE_DIAL_RADIUS*1.1)
                self.assertGreater(math.hypot(x-cx,y-cy),12.0)
                self.assertEqual(code,0x7025)

    def test_the_exported_dial_centre_matches_the_geometry_the_sweep_clicks(self):
        # If the UI moves the dial and this constant is not updated, every mode
        # click would land on whatever now occupies the old point; the sweep
        # would blame the firmware for a layout change.
        self.assertEqual(tuple(EXPORTED['mode_dial']),CHECK.MODE_DIAL_CENTER)

    def test_no_mode_detent_is_clicked_inside_the_segment_selector_row(self):
        # Regression: with the dial at y=96/r=76 the AUTO detent's click point
        # (742,150.7) fell inside the 照片/录像/S&Q selector, so egui handed the
        # click to the selector (0x71c9) and 0x7025 never arrived. The build now
        # refuses that geometry, and this pins it.
        sweep=dict((label,(x,y,code)) for label,x,y,code in CHECK.build_sweep(EXPORTED))
        for mode in CHECK.MODE_ORDER:
            with self.subTest(mode=mode):
                self.assertLess(sweep['mode-'+mode][1],CHECK.SEG_ROW_TOP)
        with self.assertRaisesRegex(ValueError,'segment selector'):
            original=CHECK.MODE_DIAL_CENTER
            try:
                CHECK.MODE_DIAL_CENTER=(742.0,96.0)
                CHECK.MODE_DIAL_RADIUS=76.0
                CHECK.build_sweep(EXPORTED)
            finally:
                CHECK.MODE_DIAL_CENTER=original
                CHECK.MODE_DIAL_RADIUS=62.0

    def test_wheel_ring_clicks_land_on_the_ring_band(self):
        sweep=dict((label,(x,y,code)) for label,x,y,code in CHECK.build_sweep(EXPORTED))
        for label,leftwards in (('wheel-ring-left',True),('wheel-ring-right',False)):
            with self.subTest(ring=label):
                x,y,code=sweep[label]
                distance=math.hypot(x-880.0,y-586.0)
                self.assertGreaterEqual(distance,106.0*0.99)
                self.assertLessEqual(distance,106.0*1.10)
                self.assertEqual(code,0x1000001d)
                self.assertEqual(x<880.0,leftwards)

    def test_wheel_directions_land_inside_the_ring(self):
        sweep=dict((label,(x,y,code)) for label,x,y,code in CHECK.build_sweep(EXPORTED))
        for label,code in (('wheel-UP',0x3),('wheel-LEFT',0x15),('wheel-RIGHT',0x1af)):
            with self.subTest(direction=label):
                x,y,got=sweep[label]
                self.assertLess(math.hypot(x-880.0,y-586.0),106.0*0.99)
                self.assertEqual(got,code)


if __name__=='__main__':unittest.main()
