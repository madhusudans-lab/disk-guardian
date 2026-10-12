"""Windows toast notifications through PowerShell + WinRT (Windows 10 1607+). Best effort, never raises.

Toasts show "Disk Guardian" as the sender when the installer's Start-menu shortcut (which carries
AppUserModelID DiskGuardian.Agent) exists; otherwise they fall back to PowerShell's id.
DISKGUARDIAN_NO_TOAST=1 records toasts to state/toasts.log instead (tests, headless use).
"""
import os
import subprocess
from pathlib import Path

from diskguardian import paths
from diskguardian.util import log, now

APP_ID = "DiskGuardian.Agent"
PS_APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"


def _esc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "''"))


def app_id():
    start = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Disk Guardian"
    return APP_ID if start.is_dir() else PS_APP_ID


def toast(title, text):
    if os.environ.get("DISKGUARDIAN_NO_TOAST"):
        try:
            paths.state_dir().mkdir(parents=True, exist_ok=True)
            with (paths.state_dir() / "toasts.log").open("a", encoding="utf-8") as f:
                f.write("%s\t%s\t%s\n" % (now().isoformat(timespec="seconds"), title, text))
        except OSError:
            pass
        return True
    xml = ('<toast><visual><binding template="ToastGeneric"><text>%s</text><text>%s</text></binding></visual></toast>'
           % (_esc(title), _esc(text[:300])))
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
          "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] > $null;"
          "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
          "$x.LoadXml('%s');"
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('%s').Show("
          "[Windows.UI.Notifications.ToastNotification]::new($x))") % (xml, app_id())
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps],
                           capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            log("toast failed: %s" % (r.stderr or b"")[:300].decode("utf-8", "replace"))
            return False
        return True
    except (OSError, subprocess.SubprocessError) as e:
        log("toast failed: %s" % e)
        return False
