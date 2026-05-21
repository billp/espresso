#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${HOME}/.local/bin"
SCRIPT_NAME="espresso"
DEST="${INSTALL_DIR}/${SCRIPT_NAME}"
VERSION="0.0.16"

mkdir -p "${INSTALL_DIR}"

# ── version check ──────────────────────────────────────────────────────────
if [ -f "${DEST}" ]; then
    OLD_VERSION=$(grep -m1 '^__version__ = ' "${DEST}" 2>/dev/null | grep -o '"[^"]*"' | tr -d '"' || true)
    if [ "${VERSION}" = "${OLD_VERSION}" ]; then
        echo "Already up to date (v${VERSION})"
        exit 0
    fi
fi

cat > "${DEST}" << 'END_OF_SCRIPT'
#!/usr/bin/env python3
"""espresso — Mouse Mover. No args: TUI manager. --daemon [minutes] [--always]: background process."""
__version__ = "0.0.16"
import os, sys, ctypes, time, random, subprocess, signal

_DAEMON_MODE = '--daemon' in sys.argv
if _DAEMON_MODE:
    sys.argv = [a for a in sys.argv if a != '--daemon']


# ── CoreGraphics / daemon ──────────────────────────────────────────────────

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


def _daemon_main():
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


# ── TUI manager ────────────────────────────────────────────────────────────

if not _DAEMON_MODE:
    import re, tty, termios, threading, select

    RESET        = "\033[0m"
    BOLD         = "\033[1m"
    DIM          = "\033[2m"
    GREEN        = "\033[32m"
    RED          = "\033[31m"
    YELLOW       = "\033[33m"
    CYAN         = "\033[36m"
    GRAY         = "\033[90m"
    WHITE        = "\033[97m"
    HIDE_CURSOR  = "\033[?25l"
    SHOW_CURSOR  = "\033[?25h"

    def green(t):  return f"{GREEN}{t}{RESET}"
    def red(t):    return f"{RED}{t}{RESET}"
    def yellow(t): return f"{YELLOW}{t}{RESET}"
    def cyan(t):   return f"{CYAN}{t}{RESET}"
    def gray(t):   return f"{GRAY}{t}{RESET}"
    def bold(t):   return f"{BOLD}{t}{RESET}"
    def dim(t):    return f"{DIM}{t}{RESET}"
    def white(t):  return f"{WHITE}{t}{RESET}"


    LOG_FILE        = '/tmp/espresso.log'
    DEFAULT_MINUTES = 0.2
    SCRIPT_SELF     = os.path.abspath(sys.argv[0])
    SCRIPT_NAME     = os.path.basename(SCRIPT_SELF)

    ITEMS_NOT_RUNNING = ['run',  'quit', 'interval', 'lock_toggle']
    ITEMS_RUNNING     = ['stop', 'quit', 'interval', 'lock_toggle']


    # ── process detection ──────────────────────────────────────────────────────

    def find_mm_processes():
        try:
            r = subprocess.run(['ps', 'aux', '-ww'], capture_output=True, text=True)
        except Exception:
            return []

        procs  = []
        my_pid = os.getpid()

        for line in r.stdout.splitlines()[1:]:
            parts = line.split(None, 10)
            if len(parts) < 11:
                continue

            cmd = parts[10]
            if '--daemon' not in cmd:
                continue

            tokens = cmd.split()
            if not tokens or not os.path.basename(tokens[0]).startswith('python'):
                continue

            if not any(os.path.basename(t) == SCRIPT_NAME for t in tokens[1:]):
                continue

            try:
                pid = int(parts[1])
            except ValueError:
                continue

            if pid == my_pid:
                continue

            minutes   = DEFAULT_MINUTES
            lock_only = True
            try:
                daemon_idx = tokens.index('--daemon')
                for tok in tokens[daemon_idx + 1:]:
                    if tok == '--always':
                        lock_only = False
                    else:
                        try:
                            minutes = float(tok)
                        except ValueError:
                            pass
            except ValueError:
                pass

            procs.append({'pid': pid, 'param': minutes, 'lock_only': lock_only})

        return procs


    # ── rendering ──────────────────────────────────────────────────────────────

    _ANSI_RE = re.compile(r'\033\[[0-9;]*m')

    def vlen(s):
        """Visual length of a string (strips ANSI codes)."""
        return len(_ANSI_RE.sub('', s))

    def rpad(s, width):
        """Right-pad s (which may contain ANSI codes) to visual width."""
        return s + ' ' * max(0, width - vlen(s))


    def fmt_param(minutes):
        return f"{minutes * 60:g} sec"


    def fmt_secs(minutes):
        return f"{minutes * 60:g}"


    LOGO = [
        " _____ _____ _____ _____ _____ _____ _____ _____ ",
        "|   __|   __|  _  | __  |   __|   __|   __|     |",
        "|   __|__   |   __|    -|   __|__   |__   |  |  |",
        "|_____|_____|__|  |__|__|_____|_____|_____|_____|",
    ]

    BRACKET_W = 6  # fixed bracket column width — keeps labels aligned across all items


    def _cb(raw, prefix):
        """Color raw bracket text and right-pad to BRACKET_W."""
        pad = ' ' * max(0, BRACKET_W - len(raw))
        return f"{prefix}{raw}{RESET}{pad}"


    def _item_label(key, lock_only, minutes, selected):
        """Build the label portion of a menu item (no arrow, no box chars)."""
        if key == 'interval':
            val = fmt_secs(minutes)
            raw = f"[{val}]"
            cb  = _cb(raw, f"{BOLD}{CYAN}" if selected else CYAN)
            lbl = (f"{BOLD}{WHITE}Interval{RESET}{GRAY} (seconds){RESET}" if selected
                   else f"{GRAY}Interval (seconds){RESET}")
            return f"{cb} {lbl}"

        if key == 'lock_toggle':
            if lock_only:
                cb = _cb("[x]", f"{BOLD}{GREEN}" if selected else GREEN)
            else:
                cb = _cb("[ ]", DIM)
            lbl = (f"{BOLD}{WHITE}Lock screen only{RESET}" if selected
                   else f"{GRAY}Lock screen only{RESET}")
            return f"{cb} {lbl}"

        text = {'run': '▶ Start', 'stop': '■ Stop', 'quit': '✕ Quit'}[key]
        return (f"{BOLD}{WHITE}{text}{RESET}" if selected
                else f"{GRAY}{text}{RESET}")


    def draw(procs, lock_only, minutes, sel_idx, flash=None):
        """Full-screen redraw."""
        is_running = bool(procs)
        items      = ITEMS_RUNNING if is_running else ITEMS_NOT_RUNNING
        W          = 46   # inner width (between the two border chars)

        lines = ["\033[2J\033[H"]
        for logo_line in LOGO:
            lines.append(f"  {CYAN}{logo_line}{RESET}")
        lines.append("")

        # ── status ──
        if _restarting.is_set():
            lines.append(f"  {'Status':<10}{gray('Restarting...')}")
        elif _starting.is_set():
            lines.append(f"  {'Status':<10}{gray('Starting...')}")
        elif _stopping.is_set():
            lines.append(f"  {'Status':<10}{gray('Stopping...')}")
        elif is_running:
            p        = procs[0]
            mode_str = "Lock screen only" if p['lock_only'] else "Always (ignore lock)"
            lines.append(f"  {'Status':<10}{green('● RUNNING')}")
            lines.append(f"  {'PID':<10}{WHITE}{p['pid']}{RESET}")
            lines.append(f"  {'Param':<10}{WHITE}{fmt_param(p['param'])}{RESET}")
            lines.append(f"  {'Mode':<10}{gray(mode_str)}")
            if len(procs) > 1:
                lines.append(f"  {yellow(f'⚠  {len(procs)} instances running')}")
        else:
            lines.append(f"  {'Status':<10}{gray('○ NOT RUNNING')}")

        lines.append("")

        if flash:
            lines.append(f"  {flash}")
            lines.append("")

        def _row(i, key):
            sel     = (i == sel_idx)
            arrow   = f"{GREEN}›{RESET}" if sel else ' '
            label   = _item_label(key, lock_only, minutes, sel)
            content = f"  {arrow} {label}"
            return f"  {GRAY}│{RESET}{rpad(content, W)}{GRAY}│{RESET}"

        # ── actions box ──
        lines.append(f"  {GRAY}┌{'─' * W}┐{RESET}")
        for i, key in enumerate(items):
            if key in ('run', 'stop', 'quit'):
                lines.append(_row(i, key))
        lines.append(f"  {GRAY}└{'─' * W}┘{RESET}")
        lines.append("")

        # ── options box ──
        lines.append(f"  {DIM}options{RESET}")
        lines.append(f"  {GRAY}┌{'─' * W}┐{RESET}")
        for i, key in enumerate(items):
            if key in ('interval', 'lock_toggle'):
                lines.append(_row(i, key))
        lines.append(f"  {GRAY}└{'─' * W}┘{RESET}")
        lines.append("")
        lines.append(f"  {GRAY}↑ ↓  navigate    Enter  select    q  quit{RESET}")

        sys.stdout.write('\n'.join(lines))
        sys.stdout.flush()


    # ── input ──────────────────────────────────────────────────────────────────

    def _rd(fd):
        """Read one byte from the raw fd, bypassing Python's buffer."""
        return os.read(fd, 1).decode('latin-1')


    def read_key(timeout=None):
        """Return a symbolic key name from stdin. Returns None on timeout."""
        if not sys.stdin.isatty():
            v = input().strip().lower()
            return v[:1] if v else 'q'

        fd  = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            # Use fd (not sys.stdin) so select sees the real OS buffer state
            if timeout is not None:
                if not select.select([fd], [], [], timeout)[0]:
                    return None
            ch = _rd(fd)
            if ch == '\x1b':
                # Arrow keys send \x1b [ A/B as one burst — 50ms is plenty
                if select.select([fd], [], [], 0.05)[0]:
                    ch2 = _rd(fd)
                    if ch2 == '[' and select.select([fd], [], [], 0.05)[0]:
                        ch3 = _rd(fd)
                        if ch3 == 'A': return 'UP'
                        if ch3 == 'B': return 'DOWN'
                        return 'IGNORE'  # left, right, or other escape sequences
                return 'ESC'
            if ch in ('\r', '\n'):     return 'ENTER'
            if ch == ' ':              return 'SPACE'
            if ch in ('\x03', '\x04'): return 'QUIT'
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


    def edit_interval(current):
        """Prompt for a new interval value. Returns (minutes, cancelled)."""
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

        for logo_line in LOGO:
            print(f"  {CYAN}{logo_line}{RESET}")
        print()
        secs = current * 60
        print(f"  Current  {CYAN}[{secs:g} sec]{RESET}")
        print()
        print(f"  New interval {gray('(seconds, e.g. 60  →  press Enter to keep current)')}")
        print(f"  → ", end='', flush=True)

        try:
            raw = input().strip()
        except (EOFError, KeyboardInterrupt):
            return current, True

        if not raw:
            return current, True  # no change, treat as cancel so we don't flash
        try:
            val = float(raw)
            if val <= 0:
                raise ValueError
            return val / 60, False
        except ValueError:
            return current, False


    # ── actions ────────────────────────────────────────────────────────────────

    def launch_mm(minutes, lock_only):
        """Launch mm.py in background. Returns (ok: bool, pid_or_msg)."""
        args = [sys.executable, SCRIPT_SELF, '--daemon', str(minutes)]
        if not lock_only:
            args.append('--always')
        try:
            with open(LOG_FILE, 'a') as log:
                proc = subprocess.Popen(
                    ['nohup'] + args,
                    stdout=log, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
            time.sleep(0.5)
            os.kill(proc.pid, 0)
            return True, proc.pid
        except ProcessLookupError:
            return False, 'process exited immediately'
        except Exception as e:
            return False, str(e)


    def stop_mm(procs):
        """Stop all mm processes. Returns combined flash message."""
        for p in procs:
            try:
                os.kill(p['pid'], signal.SIGTERM)
            except ProcessLookupError:
                pass

        time.sleep(1.0)

        parts = []
        for p in procs:
            pid = p['pid']
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGKILL)
                parts.append(green(f'✓ PID {pid} killed'))
            except ProcessLookupError:
                parts.append(green(f'✓ PID {pid} stopped'))

        return '  '.join(parts) if parts else green('✓ stopped')


    _restarting = threading.Event()
    _starting   = threading.Event()
    _stopping   = threading.Event()


    def _busy():
        return _restarting.is_set() or _starting.is_set() or _stopping.is_set()


    def _start_async(minutes, lock_only):
        if _busy():
            return
        def _worker():
            _starting.set()
            try:
                launch_mm(minutes, lock_only)
            finally:
                _starting.clear()
        threading.Thread(target=_worker, daemon=True).start()


    def _stop_async(procs):
        if _busy():
            return
        def _worker():
            _stopping.set()
            try:
                stop_mm(procs)
            finally:
                _stopping.clear()
        threading.Thread(target=_worker, daemon=True).start()


    def _restart_if_running(procs, minutes, lock_only):
        if not procs or _busy():
            return
        def _worker():
            _restarting.set()
            try:
                stop_mm(procs)
                launch_mm(minutes, lock_only)
            finally:
                _restarting.clear()
        threading.Thread(target=_worker, daemon=True).start()


    # ── main ───────────────────────────────────────────────────────────────────

    def _manager_main():
        _initial  = find_mm_processes()
        lock_only = _initial[0]['lock_only'] if _initial else False
        minutes   = _initial[0]['param']    if _initial else DEFAULT_MINUTES
        sel_idx   = 0
        flash     = None

        sys.stdout.write(HIDE_CURSOR)
        sys.stdout.flush()

        try:
            while True:
                procs      = find_mm_processes()
                is_running = bool(procs)
                items      = ITEMS_RUNNING if is_running else ITEMS_NOT_RUNNING
                sel_idx    = min(sel_idx, len(items) - 1)

                active_flash = flash
                flash = None

                draw(procs, lock_only, minutes, sel_idx, active_flash)

                timeout = 0.15 if _busy() else None
                key = read_key(timeout=timeout)
                if key is None:
                    continue  # timeout — just redraw

                if key in ('q', 'Q', 'QUIT', 'ESC'):
                    break

                elif key == 'UP':
                    sel_idx = max(0, sel_idx - 1)

                elif key == 'DOWN':
                    sel_idx = min(len(items) - 1, sel_idx + 1)

                elif key in ('ENTER', 'SPACE'):
                    action = items[sel_idx]

                    if action == 'quit':
                        break

                    elif action == 'lock_toggle':
                        lock_only = not lock_only
                        _restart_if_running(procs, minutes, lock_only)

                    elif action == 'interval':
                        new_minutes, cancelled = edit_interval(minutes)
                        sys.stdout.write(HIDE_CURSOR)
                        sys.stdout.flush()
                        if not cancelled:
                            minutes = new_minutes
                            _restart_if_running(procs, minutes, lock_only)

                    elif action == 'run':
                        _start_async(minutes, lock_only)

                    elif action == 'stop':
                        _stop_async(procs)

        except KeyboardInterrupt:
            pass

        finally:
            sys.stdout.write(SHOW_CURSOR)
            sys.stdout.flush()

        sys.stdout.write(f"\033[2J\033[H  {gray('Goodbye.')}\n\n")
        sys.stdout.flush()


if __name__ == '__main__':
    if _DAEMON_MODE:
        _daemon_main()
    else:
        _manager_main()
END_OF_SCRIPT

chmod +x "${DEST}"

echo "✓ Installed: ${DEST}"

case ":${PATH}:" in
    *":${INSTALL_DIR}:"*) ;;
    *) echo "  Note: add to PATH → export PATH=\"${INSTALL_DIR}:\$PATH\"" ;;
esac
