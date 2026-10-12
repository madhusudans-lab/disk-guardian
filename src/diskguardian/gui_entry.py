"""Windowed entry (diskguardian-w.exe): runs from the scheduled task and the Start-menu shortcuts.
Never shows a console; results appear as a toast or in Notepad/Explorer."""
import ctypes
import io
import os
import subprocess
import sys

from diskguardian import cli, config, notify, paths, scan
from diskguardian.util import is_admin, log

TITLES = {"status": "Disk status", "clean": "Disk Guardian", "deep-clean": "Deep clean", "watch": "Disk Guardian"}


def _open(target, program=None):
    try:
        if program:
            subprocess.Popen([program, str(target)])
        else:
            os.startfile(str(target))
    except OSError as e:
        notify.toast("Disk Guardian", "Could not open %s: %s" % (target, e))


def _elevate(args):
    """Relaunch this program as administrator (UAC prompt). False if refused or impossible."""
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, " ".join(args)
    else:
        exe, params = sys.executable, "-m diskguardian.gui_entry " + " ".join(args)
    try:
        return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 0) > 32
    except (AttributeError, OSError):
        return False


def _run_cli(argv):
    lines = []
    code = cli.main(argv, out=lambda *a: lines.append(" ".join(str(x) for x in a)))
    return code, lines


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    buf = io.StringIO()
    sys.stdout = sys.stdout or buf  # a windowed exe has no console streams
    sys.stderr = sys.stderr or buf
    cmd = argv[0] if argv else "status"
    try:
        if cmd == "open-report":
            if not scan.report_path().exists():
                scan.run(quick=True, quiet=True)
            _open(scan.report_path(), "notepad.exe")
        elif cmd == "open-quarantine":
            q = paths.data_dir() / "quarantine"
            q.mkdir(parents=True, exist_ok=True)
            _open(q)
        elif cmd == "open-settings":
            config.load()
            _open(config.path(), "notepad.exe")
        elif cmd == "deep-clean":
            if not is_admin():
                if not _elevate(["deep-clean"]):
                    notify.toast("Deep clean", "Cancelled: administrator permission is needed for Windows' own temp and update files.")
                return 0
            _, lines = _run_cli(["clean", "--tier", "safe", "--yes"])
            notify.toast("Deep clean", _summary(lines))
        elif cmd == "watch":
            cli.main(["watch"], out=lambda *a: None)
        else:
            _, lines = _run_cli(argv or ["status"])
            notify.toast(TITLES.get(cmd, "Disk Guardian"), _summary(lines))
    except SystemExit as e:
        return int(e.code or 0) if isinstance(e.code, int) else 1
    except Exception as e:  # shortcuts must never show a Python traceback window
        log("gui %s failed: %r" % (argv, e))
        notify.toast("Disk Guardian", "Something went wrong (%s). Details are in the log folder." % type(e).__name__)
        return 1
    return 0


def _summary(lines):
    done = [x for x in lines if x.startswith("Done:")]
    if done:
        return done[-1][len("Done: "):].strip()
    text = " ".join(x.strip() for x in lines if x.strip() and not x.startswith("Dry run"))
    return text[:300] or "Nothing to do."


if __name__ == "__main__":
    sys.exit(main())
