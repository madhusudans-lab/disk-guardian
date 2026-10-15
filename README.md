# Disk Guardian

Free, open-source disk cleaner for Windows 10 and 11. It keeps **every drive** (C:, D:, E: ...)
free of junk in the background, warns you with a notification when a drive runs low, and never
deletes your own files directly: anything personal goes to a quarantine you can restore for 7 days.

No account, no ads, no telemetry, no internet needed. MIT licensed.

## Install

1. Download `DiskGuardian-Setup-x.y.z.exe` from the [Releases](../../releases) page.
2. Run it. No administrator rights are needed; it installs only for you.
3. Windows may show **"Windows protected your PC"**. That happens because the program is not
   code-signed (signing costs money and this project is free). Click **More info**, then **Run anyway**.
   To check the download, compare its SHA-256 with the `.sha256` file next to it:
   `Get-FileHash .\DiskGuardian-Setup-x.y.z.exe`

**Requirements:** 64-bit Windows 10 version 1809 or newer, or Windows 11. Nothing else.

## Everyday use

You do not have to do anything. Every 6 hours (and a few minutes after you log in) Disk Guardian
quietly deletes safe junk on all drives, empties quarantine older than 7 days, and checks free space.
It only shows a notification when something needs your attention.

Start menu > **Disk Guardian**:

| Shortcut | What it does |
|---|---|
| Disk status | Free space on every drive, as a notification |
| Clean junk now | Deletes safe junk right away |
| Clean caches | Clears browser, app, game and download caches (they rebuild themselves) |
| Deep clean (administrator) | Also cleans Windows' own temp and update files; asks for permission |
| Open report | What uses space on your drives: biggest folders, big files, what can go |
| Open quarantine | Files Disk Guardian moved aside |
| Settings | Opens the settings file in Notepad |
| Uninstall Disk Guardian | Removes it (you choose whether to keep your quarantine) |

## What gets cleaned

| Kind | When | Examples |
|---|---|---|
| **Safe junk** | Automatically | Crash dumps, temp files older than 3 days, thumbnail cache. With Deep clean: Windows temp, Windows Update leftovers, Delivery Optimization cache, error reports |
| **Caches** | Only when you ask | Chrome, Edge, Brave, Firefox, Opera, Vivaldi caches (logins, passwords and history are **not** touched); VS Code/Cursor caches; Discord and Adobe media caches; DirectX/NVIDIA/AMD shader caches; Steam shader caches on any drive; npm, pip, yarn, pnpm, uv, Gradle, NuGet caches; Recycle Bin |
| **Needs review** | Never automatically | Installers in Downloads older than 30 days, unused AI models, idle `node_modules`/`.venv` folders: moved to the quarantine only when you ask. `Windows.old` and Windows upgrade leftovers are only reported, with the right way to remove them (Settings > System > Storage) |

Caches cost nothing to clear but things may be a little slower once while they refill.

## What is never touched

On **every** drive: the drive root, `Windows`, `Program Files`, `ProgramData`, `Users` and every
user profile root, `System Volume Information`, `Recovery`, `Boot`, `EFI`, `$Recycle.Bin` (emptied
only through Windows' own Recycle Bin command), `pagefile.sys`, `hiberfil.sys`, `swapfile.sys`.

Your Documents, Desktop, Pictures, Videos and Music, wherever they are (also when moved to OneDrive
or another drive), plus OneDrive/Dropbox/Google Drive folders and `.ssh`/`.aws`/`.gnupg`.
On drives other than C:, nothing is deleted except locations matched by a built-in rule (for
example a Steam shader cache), so a folder like `D:\Photos` can only ever be quarantined by you, by name.

Shortcuts and junctions are never followed. A rule that suddenly matches more than 50 GB is
treated as a mistake and skipped.

## Quarantine

Quarantined files are moved, not copied, so it is instant. They stay on their own drive:
`%LOCALAPPDATA%\DiskGuardian\quarantine` for C:, and a hidden `X:\.DiskGuardian\<your user name>\quarantine`
on other drives, locked so other accounts on the PC cannot open it or plant files in it. Restore with `diskguardian restore <batch>`. **Space is freed only when the quarantine is
emptied** (automatically after 7 days, or now with `diskguardian purge --batch <id> --yes`).

## Command line

The installer puts `diskguardian.exe` in `%LOCALAPPDATA%\Programs\DiskGuardian`. Everything that
changes files is a **dry run** until you add `--yes`.

```
diskguardian status                      free space on every drive
diskguardian scan [--quick]              measure everything, write the report
diskguardian clean --tier safe|cache|all [--only id,id] [--yes]
diskguardian clean --tier review --only old-installers --yes     (to quarantine)
diskguardian dev [--yes]                 idle node_modules/.venv/... folders
diskguardian big                         biggest files on all drives
diskguardian dupes [folders] [--min-mb 50]   identical files (read-only)
diskguardian explain <folder>            what is it, can it go?
diskguardian advise                      a cleanup plan from the last scan
diskguardian quarantine <paths> [--yes]  move things aside (restorable)
diskguardian qlist | restore <batch> | purge [--batch id --yes]
diskguardian history                     free space over time
diskguardian config [key value]          e.g. config warn_free_gb 20
diskguardian task install|remove|status  the background check
```

## Settings

`diskguardian config` shows them all; the file is `%LOCALAPPDATA%\DiskGuardian\config.json`.

| Setting | Default | Meaning |
|---|---|---|
| `warn_free_gb` / `critical_free_gb` | 15 / 8 | Notify below this (capped at 10 % / 5 % of small drives) |
| `auto_clean_safe` | true | Background check deletes safe junk |
| `quarantine_days` | 7 | Days before quarantined files are deleted |
| `drives` / `exclude_drives` | "auto" / [] | Which fixed drives to manage (USB, network and CD drives are always skipped) |
| `dev_idle_days` | 45 | When a project's `node_modules` etc. count as idle |
| `full_scan_hours` | 24 | How often the background check walks all folders |

Add your own rules in `%LOCALAPPDATA%\DiskGuardian\user-rules.json` (same format as
[`rules.json`](src/diskguardian/data/rules.json)).

## Optional AI (free)

`explain` and `advise` work without AI, using built-in knowledge. To get answers about any folder,
point Disk Guardian at any OpenAI-compatible service. Free choices:

| Service | Settings |
|---|---|
| **Ollama** (runs on your PC, private, no key) | `config ai.base_url http://localhost:11434/v1` and `config ai.model llama3.2` |
| OpenRouter (free models) | `config ai.base_url https://openrouter.ai/api/v1`, `config ai.model <a model ending in :free>` |
| Groq | `config ai.base_url https://api.groq.com/openai/v1`, `config ai.model llama-3.1-8b-instant` |
| Google Gemini | `config ai.base_url https://generativelanguage.googleapis.com/v1beta/openai`, `config ai.model gemini-2.0-flash` |

Put the key in the environment variable `DISKGUARDIAN_AI_KEY` (or `config ai.api_key <key>`).
Only folder names and sizes are sent, never file contents.

## Uninstall

Settings > Apps > Disk Guardian > Uninstall (or the Start-menu shortcut). The background check and
shortcuts are removed. You are asked whether to delete the settings, reports and quarantine; if the
quarantine still holds files, the default is to keep them.

## Build from source

```
winget install JRSoftware.InnoSetup
.\build.ps1 -Version 0.1.3
```

This creates a `.venv`, runs the tests, builds `dist\DiskGuardian\` with PyInstaller and wraps it
into `dist\DiskGuardian-Setup-0.1.3.exe`. Run from source with
`$env:PYTHONPATH="src"; python -m diskguardian status`. Tests: `python -m unittest discover -s tests -t .`
(they use a fake profile and fake drives in a temp folder, never your real files).

Pushing a tag `v1.2.3` makes GitHub Actions build the installer and publish a release, free for
public repositories.

## License

MIT
