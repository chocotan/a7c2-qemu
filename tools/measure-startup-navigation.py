#!/usr/bin/env python3
"""Measure real startup-language navigation on an owned 1360x930 product window.

This uses X11 pixels, not button highlights; it never claims capture or full boot.
"""
import argparse
import atexit
import ctypes
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time

from PIL import Image, ImageChops


class LCDRegion:
    def __init__(self, display, window):
        self.lib = ctypes.CDLL('libX11.so.6')
        class XImage(ctypes.Structure):
            _fields_ = [('width',ctypes.c_int),('height',ctypes.c_int),('xoffset',ctypes.c_int),
                        ('format',ctypes.c_int),('data',ctypes.c_void_p),('byte_order',ctypes.c_int),
                        ('bitmap_unit',ctypes.c_int),('bitmap_bit_order',ctypes.c_int),('bitmap_pad',ctypes.c_int),
                        ('depth',ctypes.c_int),('bytes_per_line',ctypes.c_int),('bits_per_pixel',ctypes.c_int),
                        ('red_mask',ctypes.c_ulong),('green_mask',ctypes.c_ulong),('blue_mask',ctypes.c_ulong)]
        self.lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.lib.XOpenDisplay.restype = ctypes.c_void_p
        self.lib.XGetImage.argtypes = [ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_int,
                                      ctypes.c_uint,ctypes.c_uint,ctypes.c_ulong,ctypes.c_int]
        self.lib.XGetImage.restype = ctypes.POINTER(XImage)
        self.lib.XDestroyImage.argtypes = [ctypes.POINTER(XImage)]
        self.lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.display = self.lib.XOpenDisplay(display.encode())
        if not self.display:raise RuntimeError('Cannot open owned X display')
        self.window = int(window,0)
        atexit.register(self.close)

    def close(self):
        if self.display:
            self.lib.XCloseDisplay(self.display); self.display = None

    def read(self):
        image = self.lib.XGetImage(self.display,self.window,229,289,584,438,ctypes.c_ulong(-1).value,2)
        if not image:raise RuntimeError('Cannot read original LCD window pixels')
        try:
            value = image.contents
            if ((value.width,value.height,value.depth,value.bits_per_pixel,value.byte_order,
                 value.red_mask,value.green_mask,value.blue_mask) !=
                    (584,438,24,32,0,0xff0000,0xff00,0xff) or value.bytes_per_line!=584*4):
                raise ValueError('Unverified XImage pixel layout')
            raw = ctypes.string_at(value.data,value.bytes_per_line*value.height)
            return Image.frombytes('RGB',(584,438),raw,'raw','BGRX')
        finally:self.lib.XDestroyImage(image)


def orange(image):
    r, g, b = image.crop((50, 50, image.width-50, image.height-35)).split()
    mask = ImageChops.multiply(r.point([255 if v>140 else 0 for v in range(256)]),
                              g.point([255 if 20<v<115 else 0 for v in range(256)]))
    mask = ImageChops.multiply(mask,b.point([255 if v<70 else 0 for v in range(256)]))
    raw = mask.tobytes(); width = mask.width
    counts = [raw[y*width:(y+1)*width].count(b'\xff') for y in range(mask.height)]
    count = sum(counts)
    return (50+sum(y*n for y,n in enumerate(counts))/count,count) if count>1200 else None


def focused_pixels(image):
    selected = orange(image)
    if selected is None:
        return None
    center = int(selected[0])
    return hashlib.sha256(image.crop((70, center-22, image.width-70, center+22)).tobytes()).hexdigest()


def native(path):
    before = path.stat()
    with Image.open(path) as image:
        rgb = image.convert('RGB'); rgb.load()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Frame write still in progress')
    if rgb.size != (640, 480):
        raise ValueError('Wrong native LCD geometry')
    return rgb


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--display', required=True)
    parser.add_argument('--window', required=True); parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    args.output.mkdir(mode=0o700)
    env = dict(os.environ, DISPLAY=args.display)
    def mouse(x, y, operation):
        argv = ['xdotool', 'mousemove', '--window', args.window, str(x), str(y), operation, '1']
        subprocess.run(argv, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    region = LCDRegion(args.display,args.window)
    visible = region.read
    deadline = time.monotonic() + 30
    while focused_pixels(visible()) is None:
        if time.monotonic() >= deadline:
            raise TimeoutError('Original LCD focus did not become visible; no input sent')
        time.sleep(.05)
    rows = []
    for index in range(12):
        name, y = ('DOWN', 506) if index % 2 == 0 else ('UP', 404)
        before = visible(); old = focused_pixels(before)
        try: old_native = focused_pixels(native(args.run/'lcd-continuous.ppm'))
        except (OSError, ValueError): old_native = None
        if old is None:raise ValueError('Original LCD language focus not present')
        before.save(args.output/('%02d-before.png'%index))
        subprocess.run(['xdotool','mousemove','--window',args.window,'1174',str(y)],
                       env=env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        started = time.monotonic()
        click = subprocess.Popen(['xdotool','mousedown','1','sleep','0.05','mouseup','1'],
                                 env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        first_native = first_window = candidate = confirmed = None; stable = 0
        try:
            while time.monotonic() - started < 3:
                released = click.poll() is not None
                if released and click.returncode != 0:
                    raise RuntimeError('Owned mouse press/release script failed')
                try:
                    frame = native(args.run/'lcd-continuous.ppm'); selected = focused_pixels(frame)
                    if selected is not None and old_native is not None and selected != old_native and first_native is None:
                        first_native = time.monotonic()
                except (OSError,ValueError):pass
                screen = visible(); selected = focused_pixels(screen)
                if selected is not None and selected != old:
                    stable += 1
                    if candidate is None:candidate = time.monotonic()
                    if stable >= 2 and first_window is None:
                        first_window, confirmed = candidate, time.monotonic()
                        screen.save(args.output/('%02d-%s.png'%(index,name)))
                else:stable = 0; candidate = None
                if released and first_window is not None:break
                time.sleep(.003)
        finally:
            try:click.wait(timeout=3)
            finally:
                mouse(1174, y, 'mouseup')
                click.stderr.close()
        if first_window is None:raise ValueError('No matching original LCD focus response: '+name)
        row = dict(index=index, key=name, started_monotonic_ns=int(started*1e9),
                   publish_to_native_ms=(first_native-started)*1000 if first_native else None,
                   publish_to_window_ms=(first_window-started)*1000,
                   stable_confirmation_ms=(confirmed-started)*1000, press_release_hold_ms=50)
        rows.append(row); print(json.dumps(row),flush=True); time.sleep(.15)
    values = [row['publish_to_window_ms'] for row in rows]
    result = dict(schema='a7c2-product-original-startup-navigation-latency-v1',scope='language-list original focus and real GTK window',
        samples=rows,observation_backend='X11 XGetImage of actual LCD window region',
        release_scheduler='owned xdotool sleep 0.05 independent of pixel sampling',
        window_median_ms=statistics.median(values),window_max_ms=max(values),
        all_samples_under_100ms=all(v<100 for v in values),native_frames_generated_on_host=False,
        capture_verified=False,full_boot_verified=False)
    (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result),flush=True)


if __name__ == '__main__':main()
