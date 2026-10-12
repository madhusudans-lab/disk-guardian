# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 6 spec. From the repo root:
#   pyinstaller packaging/diskguardian.spec --distpath dist --workpath build --noconfirm
# Builds ONE onedir folder dist/DiskGuardian holding both programs, which share the runtime:
#   diskguardian.exe     console CLI
#   diskguardian-w.exe   windowed: scheduled task and Start-menu shortcuts (never flashes a console)
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(SPECPATH, "icon.ico")
DATAS = [(os.path.join(ROOT, "src", "diskguardian", "data", "rules.json"), os.path.join("diskguardian", "data"))]
VERSION = os.path.join(SPECPATH, "version_info.txt")


def analysis(script):
    return Analysis([os.path.join(SPECPATH, script)], pathex=[os.path.join(ROOT, "src")], datas=DATAS,
                    excludes=["tkinter", "unittest", "pydoc", "test"], noarchive=False)


cli_a = analysis("entry_cli.py")
gui_a = analysis("entry_gui.py")


def exe(a, name, console):
    return EXE(PYZ(a.pure), a.scripts, [], exclude_binaries=True, name=name, console=console,
               icon=ICON, upx=False, version=VERSION if os.path.exists(VERSION) else None)


coll = COLLECT(exe(cli_a, "diskguardian", True), exe(gui_a, "diskguardian-w", False),
               cli_a.binaries, cli_a.datas, gui_a.binaries, gui_a.datas,
               name="DiskGuardian", upx=False)
