#!/usr/bin/env python3
"""Owned serial command framing; kernel output may surround an exact nonce tag."""
import re
import secrets
import time


def completion(data,marker):
    # Echo contains the literal :%s, never a numeric RC. The unpredictable tag
    # is the boundary; a newline is not, because printk/TTY output can interleave.
    nonce=marker.rsplit(b'_',1)[-1]
    return re.search(re.escape(marker)+rb':([0-9]+):END_'+re.escape(nonce),data)


def serial_command(proc,console,command,timeout=90,monitor=None,cleanup=False):
    if monitor is None and not cleanup:
        from menu_live import FirmwareMonitor
        monitor=FirmwareMonitor(console)
    if not cleanup:monitor.check()
    marker=('MENU_DIAG_COMMAND_DONE_'+secrets.token_hex(12)).encode()
    with console.open('rb') as reader:
        reader.seek(0,2)
        frame=marker+b':%s:END_'+marker.rsplit(b'_',1)[-1]
        # Repeat only the completed receipt, NEVER the command. A closing nonce
        # disambiguates the RC even when a kernel word touches its last digit.
        proc.stdin.write(command.encode()+b"; rc=$?; printf '\\n"+b'\\n'.join([frame]*3)+b"\\n' \"$rc\" \"$rc\" \"$rc\"\n")
        proc.stdin.flush()
        data=bytearray();deadline=None if timeout is None else time.monotonic()+timeout
        while deadline is None or time.monotonic()<deadline:
            if not cleanup:monitor.check()
            data.extend(reader.read(65536))
            if len(data)>8*1024**2:raise RuntimeError('Single serial response exceeded its explicit bound')
            if b'Exception>' in data:raise RuntimeError('Original firmware entered exception monitor')
            match=completion(data,marker)
            if match:
                if int(match[1]):raise RuntimeError('Guest command failed, return code '+match[1].decode())
                # Preserve all raw bytes. Supply a separate copy of the EXACT
                # observed token to downstream line-based receipt parsers.
                return bytes(data)+b'\n'+match[0].split(b':END_',1)[0]+b'\n'
            if proc.poll() is not None:raise RuntimeError('Owned VM exited before command completion')
            time.sleep(.05)
    raise TimeoutError('Serial completion tag missing; stop this owned session')
