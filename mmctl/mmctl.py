#!/usr/bin/env python3
"""
mmctl.py — Interactive manager for mm.py mouse mover.
Use ↑↓ to navigate, Enter to select.
"""
import os, sys, re, subprocess, signal, time, tty, termios, threading, select, json

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


SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
MM_PY           = os.path.join(SCRIPT_DIR, 'mm.py')
LOG_FILE        = '/tmp/mm.log'
DEFAULT_MINUTES = 0.2
CONFIG_PATH     = os.path.expanduser('~/.config/espresso/config.json')
AGENT_LABEL     = 'com.espresso.watchdog'
AGENT_PLIST     = os.path.expanduser('~/Library/LaunchAgents/com.espresso.watchdog.plist')
AGENT_LOG       = '/tmp/espresso-agent.log'

ITEMS_NOT_RUNNING = ['run',  'quit', 'interval', 'lock_toggle', 'schedule', 'days', 'watchdog']
ITEMS_RUNNING     = ['stop', 'quit', 'interval', 'lock_toggle', 'schedule', 'days', 'watchdog']

DAY_NAMES = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']


# ── config ─────────────────────────────────────────────────────────────────

def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    return {
        'start_time': cfg.get('start_time'),
        'end_time':   cfg.get('end_time'),
        'days':       cfg.get('days'),
        'interval':   cfg.get('interval'),
        'lock_only':  cfg.get('lock_only'),
    }


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2)


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

        tokens = parts[10].split()
        if not tokens or not os.path.basename(tokens[0]).lower().startswith('python'):
            continue

        script_idx = None
        for i, tok in enumerate(tokens[1:], 1):
            if os.path.basename(tok) == 'mm.py':
                script_idx = i
                break

        if script_idx is None:
            continue

        minutes    = DEFAULT_MINUTES
        lock_only  = True
        start_time = None
        end_time   = None
        days       = None
        rest       = tokens[script_idx + 1:]
        j = 0
        while j < len(rest):
            tok = rest[j]
            if tok == '--always':
                lock_only = False
            elif tok == '--start' and j + 1 < len(rest):
                j += 1
                start_time = rest[j]
            elif tok == '--end' and j + 1 < len(rest):
                j += 1
                end_time = rest[j]
            elif tok == '--days' and j + 1 < len(rest):
                j += 1
                try:
                    days = [int(d) for d in rest[j].split(',') if d.strip()]
                except ValueError:
                    pass
            else:
                try:
                    minutes = float(tok)
                except ValueError:
                    pass
            j += 1

        try:
            pid = int(parts[1])
        except ValueError:
            continue

        if pid == my_pid:
            continue

        procs.append({
            'pid': pid, 'param': minutes, 'lock_only': lock_only,
            'start_time': start_time, 'end_time': end_time, 'days': days,
        })

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


def fmt_schedule(start_time, end_time):
    if start_time and end_time:
        return f"{start_time}→{end_time}"
    return "always"


def fmt_days(days):
    if days is None:
        return "all"
    if not days:
        return "none"
    return " ".join(DAY_NAMES[d] for d in sorted(days))


LOGO = [
    " _____ _____ _____ _____ _____ _____ _____ _____ ",
    "|   __|   __|  _  | __  |   __|   __|   __|     |",
    "|   __|__   |   __|    -|   __|__   |__   |  |  |",
    "|_____|_____|__|  |__|__|_____|_____|_____|_____|",
]

def _item_label(key, lock_only, minutes, selected, cfg=None, avail=42):
    """Build the label for a menu item. Options right-align their bracket value."""
    if cfg is None:
        cfg = {}

    # ── action items (no bracket) ──
    if key in ('run', 'stop', 'quit'):
        text = {'run': '▶ Start', 'stop': '■ Stop', 'quit': '✕ Quit'}[key]
        return (f"{BOLD}{WHITE}{text}{RESET}" if selected else f"{GRAY}{text}{RESET}")

    # ── option items: label left, bracket right ──
    if key == 'interval':
        lbl = (f"{BOLD}{WHITE}Interval{RESET} {GRAY}(seconds){RESET}" if selected
               else f"{GRAY}Interval (seconds){RESET}")
        val_raw = f"[{fmt_secs(minutes)}]"
        cb  = f"{BOLD}{CYAN}{val_raw}{RESET}" if selected else f"{CYAN}{val_raw}{RESET}"

    elif key == 'lock_toggle':
        lbl = (f"{BOLD}{WHITE}Lock screen only{RESET}" if selected
               else f"{GRAY}Lock screen only{RESET}")
        tick    = 'x' if lock_only else ' '
        val_raw = f"[{tick}]"
        if lock_only:
            cb = f"{BOLD}{GREEN}{val_raw}{RESET}" if selected else f"{GREEN}{val_raw}{RESET}"
        else:
            cb = f"{DIM}{val_raw}{RESET}"

    elif key == 'schedule':
        lbl = (f"{BOLD}{WHITE}Schedule{RESET}" if selected else f"{GRAY}Schedule{RESET}")
        val_raw = f"[{fmt_schedule(cfg.get('start_time'), cfg.get('end_time'))}]"
        cb  = f"{BOLD}{CYAN}{val_raw}{RESET}" if selected else f"{CYAN}{val_raw}{RESET}"

    elif key == 'days':
        lbl = (f"{BOLD}{WHITE}Active days{RESET}" if selected else f"{GRAY}Active days{RESET}")
        val_raw = f"[{fmt_days(cfg.get('days'))}]"
        cb  = f"{BOLD}{CYAN}{val_raw}{RESET}" if selected else f"{CYAN}{val_raw}{RESET}"

    elif key == 'watchdog':
        lbl = (f"{BOLD}{WHITE}Watchdog{RESET} {GRAY}(auto-restart){RESET}" if selected
               else f"{GRAY}Watchdog (auto-restart){RESET}")
        on      = agent_installed()
        tick    = 'x' if on else ' '
        val_raw = f"[{tick}]"
        if on:
            cb = f"{BOLD}{GREEN}{val_raw}{RESET}" if selected else f"{GREEN}{val_raw}{RESET}"
        else:
            cb = f"{DIM}{val_raw}{RESET}"

    pad = ' ' * max(2, avail - vlen(lbl) - vlen(cb))
    return f"{lbl}{pad}{cb}"


def draw(procs, lock_only, minutes, sel_idx, flash=None, cfg=None):
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
        lines.append(f"  {'Interval':<10}{WHITE}{fmt_param(p['param'])}{RESET}")
        lines.append(f"  {'Mode':<10}{gray(mode_str)}")
        sched_str = fmt_schedule(cfg.get('start_time') if cfg else None,
                                 cfg.get('end_time')   if cfg else None)
        days_str  = fmt_days(cfg.get('days') if cfg else None)
        lines.append(f"  {'Schedule':<10}{gray(sched_str)}")
        lines.append(f"  {'Days':<10}{gray(days_str)}")
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
        # prefix "  {arrow} " = 4 visual chars; leave 2 chars margin inside border
        avail   = W - 4 - 2
        label   = _item_label(key, lock_only, minutes, sel, cfg, avail)
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
        if key in ('interval', 'lock_toggle', 'schedule', 'days', 'watchdog'):
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
                    if ch3 == 'C': return 'RIGHT'
                    if ch3 == 'D': return 'LEFT'
                    return 'IGNORE'  # other escape sequences
            return 'ESC'
        if ch in ('\r', '\n'):     return 'ENTER'
        if ch == ' ':              return 'SPACE'
        if ch in ('\x03', '\x04'): return 'QUIT'
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def edit_interval(current):
    """Spinbox interval editor. Returns (minutes, cancelled)."""
    secs = max(1, round(current * 60))

    def _draw():
        sys.stdout.write("\033[2J\033[H")
        print()
        for logo_line in LOGO:
            print(f"  {CYAN}{logo_line}{RESET}")
        print()
        print(f"  {DIM}interval{RESET}")
        W = 54
        print(f"  {GRAY}┌{'─' * W}┐{RESET}")
        print(f"  {GRAY}│{RESET}{' ' * W}{GRAY}│{RESET}")

        val_str = f"[ {secs} sec ]"
        val_col = f"{BOLD}{CYAN}{val_str}{RESET}"
        pad_l   = (W - len(val_str)) // 2
        row     = ' ' * pad_l + val_col
        print(f"  {GRAY}│{RESET}{rpad(row, W)}{GRAY}│{RESET}")
        print(f"  {GRAY}│{RESET}{' ' * W}{GRAY}│{RESET}")

        hint = f"   {GRAY}↑↓ ±1 sec   ←→ ±10 sec   Enter save   Esc cancel{RESET}"
        print(f"  {GRAY}│{RESET}{rpad(hint, W)}{GRAY}│{RESET}")
        print(f"  {GRAY}└{'─' * W}┘{RESET}")
        sys.stdout.flush()

    sys.stdout.write(HIDE_CURSOR)
    sys.stdout.flush()
    while True:
        _draw()
        key = read_key()
        if key == 'UP':
            secs = min(secs + 1, 3600)
        elif key == 'DOWN':
            secs = max(secs - 1, 1)
        elif key == 'RIGHT':
            secs = min(secs + 10, 3600)
        elif key == 'LEFT':
            secs = max(secs - 10, 1)
        elif key == 'ENTER':
            return secs / 60, False
        elif key in ('ESC', 'q', 'Q', 'QUIT'):
            return current, True


def edit_schedule(start_time, end_time):
    """Spinbox time-range picker. Returns (start_str, end_str, cancelled)."""
    # Parse into [sh, sm, eh, em]
    def _parse(s):
        if s:
            try:
                h, m = s.split(':')
                return int(h), int(m)
            except Exception:
                pass
        return 9, 0

    sh, sm = _parse(start_time)
    eh, em = _parse(end_time)
    fields = [sh, sm, eh, em]   # 0=start-h 1=start-m 2=end-h 3=end-m
    fi     = 0                   # focused field index

    FIELD_MAX = [23, 59, 23, 59]

    def _draw():
        def _fld(idx):
            val = f"{fields[idx]:02d}"
            if idx == fi:
                return f"{BOLD}{CYAN}[ {val} ]{RESET}"
            return f"{GRAY}[ {val} ]{RESET}"

        sys.stdout.write("\033[2J\033[H")
        print()
        for logo_line in LOGO:
            print(f"  {CYAN}{logo_line}{RESET}")
        print()
        print(f"  {DIM}schedule{RESET}")
        W = 54
        print(f"  {GRAY}┌{'─' * W}┐{RESET}")
        print(f"  {GRAY}│{RESET}{' ' * W}{GRAY}│{RESET}")

        s_row = f"   {WHITE}Start{RESET}   {_fld(0)} {GRAY}:{RESET} {_fld(1)}"
        e_row = f"   {WHITE}End  {RESET}   {_fld(2)} {GRAY}:{RESET} {_fld(3)}"
        print(f"  {GRAY}│{RESET}{rpad(s_row, W)}{GRAY}│{RESET}")
        print(f"  {GRAY}│{RESET}{rpad(e_row, W)}{GRAY}│{RESET}")
        print(f"  {GRAY}│{RESET}{' ' * W}{GRAY}│{RESET}")

        hint = f"   {GRAY}↑↓ adjust  Tab next field  Enter save  Esc cancel{RESET}"
        print(f"  {GRAY}│{RESET}{rpad(hint, W)}{GRAY}│{RESET}")
        print(f"  {GRAY}└{'─' * W}┘{RESET}")
        sys.stdout.flush()

    sys.stdout.write(HIDE_CURSOR)
    while True:
        _draw()
        key = read_key()
        if key == 'UP':
            fields[fi] = (fields[fi] + 1) % (FIELD_MAX[fi] + 1)
        elif key == 'DOWN':
            fields[fi] = (fields[fi] - 1) % (FIELD_MAX[fi] + 1)
        elif key in ('\t', 'RIGHT'):
            fi = (fi + 1) % 4
        elif key == 'LEFT':
            fi = (fi - 1) % 4
        elif key == 'ENTER':
            s = f"{fields[0]:02d}:{fields[1]:02d}"
            e = f"{fields[2]:02d}:{fields[3]:02d}"
            return s, e, False
        elif key in ('ESC', 'q', 'Q', 'QUIT'):
            return start_time, end_time, True


def edit_days(days):
    """Day-of-week multi-selector. Returns (days_list_or_none, cancelled)."""
    selected = set(days) if days is not None else set(range(7))
    fi       = 0   # focused day index (0-6)

    def _draw():
        sys.stdout.write("\033[2J\033[H")
        print()
        for logo_line in LOGO:
            print(f"  {CYAN}{logo_line}{RESET}")
        print()
        print(f"  {DIM}active days{RESET}")
        W = 54
        print(f"  {GRAY}┌{'─' * W}┐{RESET}")
        print(f"  {GRAY}│{RESET}{' ' * W}{GRAY}│{RESET}")

        cells = []
        for d in range(7):
            tick = 'x' if d in selected else ' '
            name = DAY_NAMES[d]
            if d == fi:
                cell = f"{BOLD}{CYAN}[{tick}] {name}{RESET}"
            elif d in selected:
                cell = f"{GREEN}[{tick}]{RESET} {GRAY}{name}{RESET}"
            else:
                cell = f"{DIM}[{tick}] {name}{RESET}"
            cells.append(cell)

        row1 = "   " + "  ".join(cells[:4])
        row2 = "   " + "  ".join(cells[4:])
        print(f"  {GRAY}│{RESET}{rpad(row1, W)}{GRAY}│{RESET}")
        print(f"  {GRAY}│{RESET}{rpad(row2, W)}{GRAY}│{RESET}")
        print(f"  {GRAY}│{RESET}{' ' * W}{GRAY}│{RESET}")

        hint = f"   {GRAY}← → navigate  Space toggle  Enter save  Esc cancel{RESET}"
        print(f"  {GRAY}│{RESET}{rpad(hint, W)}{GRAY}│{RESET}")
        print(f"  {GRAY}└{'─' * W}┘{RESET}")
        sys.stdout.flush()

    sys.stdout.write(HIDE_CURSOR)
    while True:
        _draw()
        key = read_key()
        if key == 'RIGHT':
            fi = (fi + 1) % 7
        elif key == 'LEFT':
            fi = (fi - 1) % 7
        elif key == 'DOWN':
            fi = min(fi + 4, 6) if fi < 4 else fi - 4
        elif key == 'UP':
            fi = fi - 4 if fi >= 4 else min(fi + 4, 6)
        elif key == 'SPACE':
            if fi in selected:
                selected.discard(fi)
            else:
                selected.add(fi)
        elif key == 'ENTER':
            result = sorted(selected) if len(selected) < 7 else None
            return result, False
        elif key in ('ESC', 'q', 'Q', 'QUIT'):
            return days, True


# ── actions ────────────────────────────────────────────────────────────────

def launch_mm(minutes, lock_only, cfg=None):
    """Launch mm.py in background. Returns (ok: bool, pid_or_msg)."""
    if cfg is None:
        cfg = {}
    args = [sys.executable, MM_PY, str(minutes)]
    if not lock_only:
        args.append('--always')
    if cfg.get('start_time') and cfg.get('end_time'):
        args += ['--start', cfg['start_time'], '--end', cfg['end_time']]
    if cfg.get('days') is not None:
        args += ['--days', ','.join(str(d) for d in cfg['days'])]
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


def ensure_running():
    """Start the daemon with last-saved settings if it isn't already running.

    Used by the watchdog LaunchAgent (`espresso --ensure`)."""
    if find_mm_processes():
        return
    cfg       = load_config()
    minutes   = cfg['interval']  if cfg['interval']  is not None else DEFAULT_MINUTES
    lock_only = cfg['lock_only'] if cfg['lock_only'] is not None else False
    launch_mm(minutes, lock_only, cfg)


# ── watchdog LaunchAgent ─────────────────────────────────────────────────────

def agent_installed():
    """True if the watchdog LaunchAgent plist is present."""
    return os.path.exists(AGENT_PLIST)


def _agent_plist_xml():
    """Build the LaunchAgent plist that runs `espresso --ensure` every 60s."""
    espresso = os.path.abspath(sys.argv[0])
    py_dir   = os.path.dirname(os.path.abspath(sys.executable))
    path_env = ':'.join([
        os.path.expanduser('~/.local/bin'), py_dir,
        '/opt/homebrew/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin',
    ])
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{espresso}</string>
        <string>--ensure</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{path_env}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>StandardOutPath</key>
    <string>{AGENT_LOG}</string>
    <key>StandardErrorPath</key>
    <string>{AGENT_LOG}</string>
</dict>
</plist>
'''


def install_agent():
    """Write and load the watchdog LaunchAgent. Returns (ok, msg)."""
    try:
        os.makedirs(os.path.dirname(AGENT_PLIST), exist_ok=True)
        with open(AGENT_PLIST, 'w') as f:
            f.write(_agent_plist_xml())
        uid    = os.getuid()
        target = f'gui/{uid}/{AGENT_LABEL}'
        subprocess.run(['launchctl', 'bootout', target], capture_output=True, text=True)
        r = subprocess.run(['launchctl', 'bootstrap', f'gui/{uid}', AGENT_PLIST],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return False, (r.stderr.strip() or 'bootstrap failed')
        subprocess.run(['launchctl', 'enable', target], capture_output=True, text=True)
        return True, 'watchdog installed'
    except Exception as e:
        return False, str(e)


def uninstall_agent():
    """Unload and remove the watchdog LaunchAgent. Returns (ok, msg)."""
    try:
        uid    = os.getuid()
        subprocess.run(['launchctl', 'bootout', f'gui/{uid}/{AGENT_LABEL}'],
                       capture_output=True, text=True)
        if os.path.exists(AGENT_PLIST):
            os.remove(AGENT_PLIST)
        return True, 'watchdog removed'
    except Exception as e:
        return False, str(e)


_restarting = threading.Event()
_starting   = threading.Event()
_stopping   = threading.Event()


def _busy():
    return _restarting.is_set() or _starting.is_set() or _stopping.is_set()


def _start_async(minutes, lock_only, cfg=None):
    if _busy():
        return
    def _worker():
        _starting.set()
        try:
            launch_mm(minutes, lock_only, cfg)
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


def _restart_if_running(procs, minutes, lock_only, cfg=None):
    if not procs or _busy():
        return
    def _worker():
        _restarting.set()
        try:
            stop_mm(procs)
            launch_mm(minutes, lock_only, cfg)
        finally:
            _restarting.clear()
    threading.Thread(target=_worker, daemon=True).start()


# ── main ───────────────────────────────────────────────────────────────────

def main():
    _initial  = find_mm_processes()
    cfg       = load_config()
    lock_only = _initial[0]['lock_only'] if _initial else (
                    cfg['lock_only'] if cfg['lock_only'] is not None else False)
    minutes   = _initial[0]['param']    if _initial else (
                    cfg['interval']  if cfg['interval']  is not None else DEFAULT_MINUTES)
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

            draw(procs, lock_only, minutes, sel_idx, active_flash, cfg)

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
                    cfg['lock_only'] = lock_only
                    save_config(cfg)
                    _restart_if_running(procs, minutes, lock_only, cfg)

                elif action == 'interval':
                    new_minutes, cancelled = edit_interval(minutes)
                    sys.stdout.write(HIDE_CURSOR)
                    sys.stdout.flush()
                    if not cancelled:
                        minutes = new_minutes
                        cfg['interval'] = minutes
                        save_config(cfg)
                        _restart_if_running(procs, minutes, lock_only, cfg)

                elif action == 'schedule':
                    new_start, new_end, cancelled = edit_schedule(
                        cfg.get('start_time'), cfg.get('end_time')
                    )
                    sys.stdout.write(HIDE_CURSOR)
                    sys.stdout.flush()
                    if not cancelled:
                        cfg['start_time'] = new_start
                        cfg['end_time']   = new_end
                        save_config(cfg)
                        _restart_if_running(procs, minutes, lock_only, cfg)

                elif action == 'days':
                    new_days, cancelled = edit_days(cfg.get('days'))
                    sys.stdout.write(HIDE_CURSOR)
                    sys.stdout.flush()
                    if not cancelled:
                        cfg['days'] = new_days
                        save_config(cfg)
                        _restart_if_running(procs, minutes, lock_only, cfg)

                elif action == 'watchdog':
                    if agent_installed():
                        ok, msg = uninstall_agent()
                    else:
                        ok, msg = install_agent()
                    flash = green(f'✓ {msg}') if ok else red(f'✗ {msg}')

                elif action == 'run':
                    _start_async(minutes, lock_only, cfg)

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
    if '--ensure' in sys.argv:
        ensure_running()
    elif '--install-agent' in sys.argv:
        ok, msg = install_agent()
        print(('✓ ' if ok else '✗ ') + msg)
        sys.exit(0 if ok else 1)
    elif '--uninstall-agent' in sys.argv:
        ok, msg = uninstall_agent()
        print(('✓ ' if ok else '✗ ') + msg)
        sys.exit(0 if ok else 1)
    else:
        main()
