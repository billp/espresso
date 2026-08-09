#!/usr/bin/env python3
"""
mm.py — Mouse mover daemon. Managed by mmctl.py.
Args: [minutes] [--always] [--start HH:MM] [--end HH:MM] [--days 0,1,2,3,4]
  minutes    : idle time required before a cycle (default 0.2)
  --always   : move mouse even when screen is not locked
  --start    : start of active time window (24h HH:MM)
  --end      : end of active time window (24h HH:MM)
  --days     : comma-separated weekday numbers (0=Mon … 6=Sun)

The interval is an idle timer: any real user input (mouse or keyboard)
restarts it, and a cycle already in progress is abandoned the moment the
cursor moves on its own.
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

try:
    _cg.CGEventSourceSecondsSinceLastEventType.restype = ctypes.c_double
    _cg.CGEventSourceSecondsSinceLastEventType.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
except AttributeError:  # not available — fall back to cursor tracking alone
    _cg.CGEventSourceSecondsSinceLastEventType = None

kCGEventMouseMoved = 5
kCGHIDEventTap = 0
kCGMouseButtonLeft = 0
kCGEventSourceStateHIDSystemState = 1
kCGAnyInputEventType = 0xFFFFFFFF

# Cursor jumps smaller than this are treated as rounding noise, not the user.
MOVE_EPSILON = 2.0


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


def seconds_since_input():
    """Seconds since the last HID input event, or None if unavailable."""
    if _cg.CGEventSourceSecondsSinceLastEventType is None:
        return None
    try:
        return _cg.CGEventSourceSecondsSinceLastEventType(
            kCGEventSourceStateHIDSystemState, kCGAnyInputEventType)
    except Exception:
        return None


def moved(a, b):
    return abs(a.x - b.x) > MOVE_EPSILON or abs(a.y - b.y) > MOVE_EPSILON


def jiggle(origin, width, height):
    """Nudge the cursor and put it back. Returns False if the user took over."""
    last = origin
    for _ in range(10):
        if moved(get_mouse_pos(), last):
            return False
        nx = max(0.0, min(width - 1, origin.x + random.uniform(-5.0, 5.0)))
        ny = max(0.0, min(height - 1, origin.y + random.uniform(-5.0, 5.0)))
        move_mouse(nx, ny)
        last = CGPoint(nx, ny)
        time.sleep(0.05)

    if moved(get_mouse_pos(), last):
        return False
    move_mouse(origin.x, origin.y)
    return True


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
    poll     = min(5.0, max(1.0, interval / 4.0))

    resting  = get_mouse_pos()      # where the cursor was left after the last cycle
    deadline = time.monotonic() + interval

    while True:
        time.sleep(poll)
        now = time.monotonic()

        cur = get_mouse_pos()
        if moved(cur, resting):     # the user is driving — start the wait over
            resting  = cur
            deadline = now + interval
            continue
        resting = cur

        idle = seconds_since_input()
        if idle is not None and idle < interval:
            deadline = max(deadline, now + (interval - idle))

        if now < deadline:
            continue

        # only worth the ioreg call once the idle timer has actually run out
        if not always_mode and not is_locked():
            deadline = now + interval
            continue

        if not is_within_schedule(start_hm, end_hm, allowed_days):
            deadline = now + interval
            continue

        jiggle(get_mouse_pos(), width, height)
        resting  = get_mouse_pos()
        deadline = time.monotonic() + interval


if __name__ == '__main__':
    main()
