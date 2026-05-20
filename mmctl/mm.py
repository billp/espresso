#!/usr/bin/env python3
"""
mm.py — Mouse mover daemon. Managed by mmctl.py.
Args: [minutes] [--always]
  minutes  : interval between cycles (default 0.2)
  --always : move mouse even when screen is not locked
"""
import ctypes, sys, time, random, subprocess

_cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')


class CGPoint(ctypes.Structure):
    _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [('width', ctypes.c_double), ('height', ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [('origin', CGPoint), ('size', CGSize)]


_cg.CGMainDisplayID.restype = ctypes.c_uint32
_cg.CGMainDisplayID.argtypes = []

_cg.CGDisplayBounds.restype = CGRect
_cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]

_cg.CGEventCreate.restype = ctypes.c_void_p
_cg.CGEventCreate.argtypes = [ctypes.c_void_p]

_cg.CGEventGetLocation.restype = CGPoint
_cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]

_cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
_cg.CGEventCreateMouseEvent.argtypes = [
    ctypes.c_void_p,
    ctypes.c_uint32,
    CGPoint,
    ctypes.c_uint32,
]

_cg.CGEventPost.restype = None
_cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]

_cg.CFRelease.restype = None
_cg.CFRelease.argtypes = [ctypes.c_void_p]

kCGEventMouseMoved = 5
kCGHIDEventTap = 0
kCGMouseButtonLeft = 0


def is_locked():
    r = subprocess.run(
        '/usr/sbin/ioreg -c IORegistryEntry | grep IOConsoleLocked',
        shell=True, capture_output=True, text=True,
    )
    return 'Yes' in r.stdout


def get_mouse_pos():
    evt = _cg.CGEventCreate(None)
    pos = _cg.CGEventGetLocation(evt)
    _cg.CFRelease(evt)
    return pos


def move_mouse(x, y):
    pt = CGPoint(x, y)
    evt = _cg.CGEventCreateMouseEvent(None, kCGEventMouseMoved, pt, kCGMouseButtonLeft)
    _cg.CGEventPost(kCGHIDEventTap, evt)
    _cg.CFRelease(evt)


def main():
    minutes = 0.2
    always_mode = False

    for arg in sys.argv[1:]:
        if arg == '--always':
            always_mode = True
        else:
            try:
                minutes = float(arg)
            except ValueError:
                pass

    display = _cg.CGMainDisplayID()
    bounds = _cg.CGDisplayBounds(display)
    width = bounds.size.width
    height = bounds.size.height
    interval = minutes * 60

    while True:
        if not always_mode and not is_locked():
            time.sleep(interval)
            continue

        cur = get_mouse_pos()

        for _ in range(10):
            nx = max(0.0, min(width - 1, cur.x + random.uniform(-5.0, 5.0)))
            ny = max(0.0, min(height - 1, cur.y + random.uniform(-5.0, 5.0)))
            move_mouse(nx, ny)
            time.sleep(0.05)

        move_mouse(cur.x, cur.y)
        time.sleep(interval)


if __name__ == '__main__':
    main()
