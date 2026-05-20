#!/usr/bin/env python3
"""build.py — Generate install.sh by bundling mmctl/mm.py + mmctl/mmctl.py."""
import os, re, subprocess, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MM_SRC     = os.path.join(SCRIPT_DIR, 'mmctl', 'mm.py')
MMCTL_SRC  = os.path.join(SCRIPT_DIR, 'mmctl', 'mmctl.py')
INSTALL_SH = os.path.join(SCRIPT_DIR, 'install.sh')


# ── version ────────────────────────────────────────────────────────────────

def read_version():
    if not os.path.exists(INSTALL_SH):
        return '0.0.0'
    with open(INSTALL_SH) as f:
        for line in f:
            m = re.match(r'^__version__ = "([^"]+)"', line)
            if m:
                return m.group(1)
    return '0.0.0'


def bump_version(v):
    parts = v.split('.')
    parts[-1] = str(int(parts[-1]) + 1)
    return '.'.join(parts)


# ── source transformations ─────────────────────────────────────────────────

def strip_shebang(src):
    return re.sub(r'^#!.*\n', '', src)


def strip_docstring(src):
    return re.sub(r'^\s*""".*?"""\s*\n', '', src, flags=re.DOTALL)


def strip_top_imports(src):
    return re.sub(r'^import [^\n]+\n', '', src, flags=re.MULTILINE)


def strip_main_guard(src):
    return re.sub(r"\nif __name__ == ['\"]__main__['\"]:\s*\n.*", '', src, flags=re.DOTALL)


def indent4(src):
    return '\n'.join('    ' + l if l.strip() else '' for l in src.splitlines())


# Replacement for find_mm_processes — detects self launched with --daemon flag
BUNDLE_FIND_MM = '''\
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

    return procs'''


LOGO_CONST = '''\
LOGO = [
    " _____ _____ _____ _____ _____ _____ _____ _____ ",
    "|   __|   __|  _  | __  |   __|   __|   __|     |",
    "|   __|__   |   __|    -|   __|__   |__   |  |  |",
    "|_____|_____|__|  |__|__|_____|_____|_____|_____|",
]

'''


def build_daemon(src):
    src = strip_shebang(src)
    src = strip_docstring(src)
    src = strip_top_imports(src)
    src = strip_main_guard(src)
    src = src.replace('def main():', 'def _daemon_main():')
    return src.strip()


def build_manager(src):
    src = strip_shebang(src)
    src = strip_docstring(src)
    src = strip_top_imports(src)
    src = strip_main_guard(src)

    # Remove SCRIPT_DIR and MM_PY globals
    src = re.sub(r'^SCRIPT_DIR\s*=.*\n', '', src, flags=re.MULTILINE)
    src = re.sub(r'^MM_PY\s*=.*\n',      '', src, flags=re.MULTILINE)

    # Update log file path
    src = src.replace('/tmp/mm.log', '/tmp/espresso.log')

    # Add SCRIPT_SELF / SCRIPT_NAME after DEFAULT_MINUTES
    src = src.replace(
        'DEFAULT_MINUTES = 0.2\n',
        'DEFAULT_MINUTES = 0.2\n'
        'SCRIPT_SELF     = os.path.abspath(sys.argv[0])\n'
        'SCRIPT_NAME     = os.path.basename(SCRIPT_SELF)\n',
    )

    # Replace find_mm_processes with bundle-compatible version
    src = re.sub(
        r'def find_mm_processes\(\):.*?(?=\n\n\n#|\n\ndef )',
        BUNDLE_FIND_MM,
        src,
        flags=re.DOTALL,
    )

    # Update launch_mm to launch self with --daemon
    src = src.replace(
        "args = [sys.executable, MM_PY, str(minutes)]",
        "args = [sys.executable, SCRIPT_SELF, '--daemon', str(minutes)]",
    )

    # Remove MM_PY existence check
    src = re.sub(
        r'\n[ \t]+if not os\.path\.exists\(MM_PY\):.*?continue\n',
        '\n',
        src,
        flags=re.DOTALL,
    )

    # Rename main to _manager_main
    src = src.replace('def main():', 'def _manager_main():')

    return src.strip()


# ── install.sh template ────────────────────────────────────────────────────

BASH_HEADER = '''\
#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${HOME}/.local/bin"
SCRIPT_NAME="espresso"
DEST="${INSTALL_DIR}/${SCRIPT_NAME}"

mkdir -p "${INSTALL_DIR}"

# ── version check (skipped when piped through bash) ───────────────────────
if [ -f "$0" ]; then
    NEW_VERSION=$(grep -m1 '^__version__ = ' "$0" | grep -o '"[^"]*"' | tr -d '"')
    if [ -f "${DEST}" ]; then
        OLD_VERSION=$(grep -m1 '^__version__ = ' "${DEST}" 2>/dev/null | grep -o '"[^"]*"' | tr -d '"' || true)
        if [ "${NEW_VERSION}" = "${OLD_VERSION}" ]; then
            echo "Already up to date (v${NEW_VERSION})"
            exit 0
        fi
    fi
fi

cat > "${DEST}" << \'END_OF_SCRIPT\'
'''

PYTHON_PREAMBLE = '''\
#!/usr/bin/env python3
"""espresso — Mouse Mover. No args: TUI manager. --daemon [minutes] [--always]: background process."""
__version__ = "{version}"
import os, sys, ctypes, time, random, subprocess, signal

_DAEMON_MODE = '--daemon' in sys.argv
if _DAEMON_MODE:
    sys.argv = [a for a in sys.argv if a != '--daemon']


# ── CoreGraphics / daemon ──────────────────────────────────────────────────

'''

PYTHON_MANAGER_HEADER = '''\


# ── TUI manager ────────────────────────────────────────────────────────────

if not _DAEMON_MODE:
    import re, tty, termios, threading, select

'''

PYTHON_ENTRYPOINT = '''\


if __name__ == '__main__':
    if _DAEMON_MODE:
        _daemon_main()
    else:
        _manager_main()
'''

BASH_FOOTER = '''\
END_OF_SCRIPT

chmod +x "${DEST}"

echo "✓ Installed: ${DEST}"

case ":${PATH}:" in
    *":${INSTALL_DIR}:"*) ;;
    *) echo "  Note: add to PATH → export PATH=\\"${INSTALL_DIR}:\\$PATH\\"" ;;
esac
'''


# ── main ───────────────────────────────────────────────────────────────────

def main():
    for path in (MM_SRC, MMCTL_SRC):
        if not os.path.exists(path):
            print(f'✗ Missing source: {path}', file=sys.stderr)
            sys.exit(1)

    with open(MM_SRC)   as f: mm_src    = f.read()
    with open(MMCTL_SRC) as f: mmctl_src = f.read()

    old_version = read_version()
    new_version = bump_version(old_version)

    daemon_code  = build_daemon(mm_src)
    manager_code = indent4(build_manager(mmctl_src))

    python_script = (
        PYTHON_PREAMBLE.format(version=new_version)
        + daemon_code + '\n'
        + PYTHON_MANAGER_HEADER
        + manager_code + '\n'
        + PYTHON_ENTRYPOINT
    )

    install_sh = BASH_HEADER + python_script + BASH_FOOTER

    with open(INSTALL_SH, 'w') as f:
        f.write(install_sh)

    # Validate Python syntax of the embedded bundle (extract from heredoc)
    m = re.search(r"<< 'END_OF_SCRIPT'\n(.*)\nEND_OF_SCRIPT", install_sh, flags=re.DOTALL)
    if not m:
        print('✗ Could not locate heredoc in generated install.sh', file=sys.stderr)
        sys.exit(1)
    py_content = m.group(1)
    try:
        compile(py_content, '<bundle>', 'exec')
    except SyntaxError as e:
        print(f'✗ Syntax error in generated bundle: {e}', file=sys.stderr)
        sys.exit(1)

    print(f'✓ install.sh generated  (v{old_version} → v{new_version})')


if __name__ == '__main__':
    main()
