#!/usr/bin/env python3
"""
mm.py — Mouse mover daemon. Managed by mmctl.py.
Args: [minutes] [--always] [--start HH:MM] [--end HH:MM] [--days 0,1,2,3,4]
  minutes    : interval between cycles (default 0.2)
  --always   : move mouse even when screen is not locked
  --start    : start of active time window (24h HH:MM)
  --end      : end of active time window (24h HH:MM)
  --days     : comma-separated weekday numbers (0=Mon … 6=Sun)
"""
import ctypes, sys, time, random, subprocess
from datetime import datetime

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


def _parse_hhmm(s):
    """Parse 'HH:MM' string into (hour, minute) tuple, or None on failure."""
    try:
        h, m = s.split(':')
        return (int(h), int(m))
    except Exception:
        return None


def is_within_schedule(start_hm, end_hm, allowed_days):
    """Return True if current time/day falls within the configured schedule."""
    now = datetime.now()
    if allowed_days is not None and now.weekday() not in allowed_days:
        return False
    if start_hm is not None and end_hm is not None:
        cur = now.hour * 60 + now.minute
        s   = start_hm[0] * 60 + start_hm[1]
        e   = end_hm[0]   * 60 + end_hm[1]
        if s <= e:
            return s <= cur <= e
        else:  # overnight range e.g. 22:00–06:00
            return cur >= s or cur <= e
    return True


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
    minutes      = 0.2
    always_mode  = False
    start_hm     = None
    end_hm       = None
    allowed_days = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--always':
            always_mode = True
        elif a == '--start' and i + 1 < len(args):
            i += 1
            start_hm = _parse_hhmm(args[i])
        elif a == '--end' and i + 1 < len(args):
            i += 1
            end_hm = _parse_hhmm(args[i])
        elif a == '--days' and i + 1 < len(args):
            i += 1
            try:
                allowed_days = [int(d) for d in args[i].split(',') if d.strip()]
            except ValueError:
                pass
        else:
            try:
                minutes = float(a)
            except ValueError:
                pass
        i += 1

    display  = _cg.CGMainDisplayID()
    bounds   = _cg.CGDisplayBounds(display)
    width    = bounds.size.width
    height   = bounds.size.height
    interval = minutes * 60

    while True:
        if not always_mode and not is_locked():
            time.sleep(interval)
            continue

        if not is_within_schedule(start_hm, end_hm, allowed_days):
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
