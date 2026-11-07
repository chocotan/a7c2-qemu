#!/usr/bin/env python3
"""Observe the actual original mode writer; stop after its first Movie value."""
from pathlib import Path
import runpy

Base=runpy.run_path(str(Path(__file__).with_name('shutdown-watch.py')))['ShutdownWriteProbe']


class ModeWriteProbe(Base):
    OFFSET=0x7e5d428
    KIND='mode-write'
    STOP_VALUE=3
    LIMIT=32
    ARMED_FILE='mode-watch-armed.json'
    WRITES_FILE='mode-writes.jsonl'
    CAPTURE_FILE='mode-first-movie-write.json'
    LIMIT_FILE='mode-watch-limit.json'
    CODE_OFFSETS=(0x33aa0d0,0x33aa9e8,0x339d44c,0x339fc70,0x33a5b08,0x3546040)
