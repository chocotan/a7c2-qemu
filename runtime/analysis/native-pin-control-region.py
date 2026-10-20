"""Declare the finite pin-control RAM owner on the final native DTB."""
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'device-models/pin-buffer-region.py'))
PROFILE = 'fullsystem.pin-control-memory=1'


def reserve(fdt, buffer, command_line):
    API['validate_final_command'](command_line)
    API['add_dtb_reservation'](fdt, buffer, command_line)
