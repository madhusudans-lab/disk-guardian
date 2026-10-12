"""The Task Scheduler entry that runs `watch`: at logon (+5 min) and every 6 hours, as the
current user, no elevation, never two at once, also on battery."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def name():
    return "Disk Guardian (%s)" % os.environ.get("USERNAME", "user")


def command():
    """(program, arguments) that run one watch cycle without a console window."""
    if getattr(sys, "frozen", False):
        w = Path(sys.executable).with_name("diskguardian-w.exe")
        return str(w), "watch"
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return str(pyw if pyw.exists() else sys.executable), "-m diskguardian.gui_entry watch"


def xml(program, args, user):
    return """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Disk Guardian: cleans junk on every drive and warns when space runs low.</Description></RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId><Delay>PT5M</Delay></LogonTrigger>
    <TimeTrigger><Enabled>true</Enabled><StartBoundary>2026-01-01T00:00:00</StartBoundary>
      <Repetition><Interval>PT6H</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition></TimeTrigger>
  </Triggers>
  <Principals><Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author"><Exec><Command>{program}</Command><Arguments>{args}</Arguments></Exec></Actions>
</Task>
""".format(user=escape(user), program=escape(program), args=escape(args))


def _schtasks(*args):
    r = subprocess.run(["schtasks"] + list(args), capture_output=True, text=True, creationflags=_NO_WINDOW)
    return r.returncode, (r.stdout + r.stderr).strip()


def install(out=print):
    user = "%s\\%s" % (os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", ""))
    program, args = command()
    fd, tmp = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        Path(tmp).write_text(xml(program, args, user), encoding="utf-16")
        code, msg = _schtasks("/Create", "/F", "/TN", name(), "/XML", tmp)
    finally:
        os.unlink(tmp)
    out(("Installed scheduled task '%s'." % name()) if code == 0 else "Could not install the task: %s" % msg)
    return code


def remove(out=print):
    code, msg = _schtasks("/Delete", "/F", "/TN", name())
    out(("Removed scheduled task '%s'." % name()) if code == 0 else "No task removed: %s" % msg)
    return 0


def status(out=print):
    code, msg = _schtasks("/Query", "/TN", name(), "/V", "/FO", "LIST")
    if code != 0:
        out("Scheduled task '%s' is not installed. Run: diskguardian task install" % name())
        return 1
    keep = ("TaskName", "Status", "Next Run Time", "Last Run Time", "Last Result", "Task To Run")
    for line in msg.splitlines():
        if line.split(":")[0].strip() in keep:
            out(line)
    return 0
