# Disk Guardian (public) — design

Date: 2026-10-12 · Status: draft for review

## 1. Goal

A free, open-source disk-space agent that anyone can install on a Windows 10 or 11 PC with
a normal `setup.exe`. It keeps the system drive clean in the background, warns with a Windows
notification when space runs low, and never deletes a user's real files without a restorable
quarantine. Building, shipping and running it costs nothing.

**Done means:** a `DiskGuardian-Setup-x.y.z.exe` that, on a 64-bit Windows 10 or 11 PC with no
Python installed, installs without admin rights, registers the background task, shows a toast
when free space is below the threshold, offers Start-menu actions, and uninstalls cleanly.

### What the user said
- Public release for anyone; Windows only; must work on Windows 10 and 11.
- Full installer wizard (Start menu, uninstall from Settings).
- AI optional, bring-your-own. Alerts by Windows toast only.
- Simple, and it must cost nothing.
- The owner's existing `~/storage-cleaner` stays untouched; this is a separate project.
- Use DeepSeek Harness / DeerFlow / Hermes where they make the work cheaper.

### Assumptions (made by Claude, open to correction)
- No tray app; Start-menu shortcuts plus toasts are the whole UI.
- 64-bit (x64) only. ARM64 Windows 11 runs it under emulation; 32-bit Windows 10 is unsupported.
- English only for v1.
- Unsigned binaries (code signing is the only part that costs money). The README explains the
  SmartScreen "Run anyway" step.
- No auto-update in v1; users download the new setup.exe, which upgrades in place.

## 2. Non-goals

Tray app or GUI windows; macOS/Linux; code signing; auto-update; telemetry of any kind;
Telegram/e-mail/webhook alerts; links to Hermes, DeerFlow or Jarvis; a Windows service.

## 3. Architecture

```
setup.exe (Inno Setup, per-user, no admin)
  installs  %LOCALAPPDATA%\Programs\DiskGuardian\
              diskguardian.exe      console CLI   (power users)
              diskguardian-w.exe    windowed      (task + shortcuts; never flashes a console)
              rules.json            default rules (read-only, replaced on upgrade)
  creates   Task Scheduler task "DiskGuardian"  -> diskguardian-w.exe watch
              triggers: at logon (+5 min delay) and every 6 h; runs as the user, no elevation
            Start menu: Disk status · Clean junk now · Deep clean (administrator) ·
                        Open report · Quarantine folder · Settings · Uninstall
data       %LOCALAPPDATA%\DiskGuardian\
              config.json  user-rules.json  state\  reports\  quarantine\  logs\
```

Both executables come from one Python package built by PyInstaller (`--onedir` for fast start
and fewer antivirus false positives). Standard library only at runtime.

### Source layout (package `diskguardian`)

| Module | One job |
|---|---|
| `paths.py` | Resolve install dir, data dir, system drive (`%SystemDrive%`, never hard-coded `C:`); env override `DISKGUARDIAN_HOME` for tests |
| `config.py` | Load/merge defaults + `config.json`; validate thresholds |
| `rules.py` | Load `rules.json` + optional `user-rules.json`; expand env vars and globs; size each rule |
| `safety.py` | The refusal list: system folders, user profile roots, the app's own data dir, anything outside allowed roots. Every delete and quarantine goes through `safety.check(path)` |
| `cleaner.py` | Execute a tier (`safe`/`cache`) — dry run unless `yes=True`; skips locked files; never follows junctions/symlinks |
| `quarantine.py` | Move to quarantine with manifest, list, restore, purge after `quarantine_days` |
| `scan.py` | Full scan: rule sizes, biggest folders, big files, idle dev folders, duplicates; writes `reports\latest.md` and `history.jsonl` |
| `notify.py` | Toast via PowerShell + WinRT using AppUserModelID `DiskGuardian.Agent` (set on the Start-menu shortcut by Inno); falls back to the PowerShell AppID |
| `ai.py` | Optional OpenAI-compatible chat call via `urllib` (works with Ollama, OpenRouter, Groq, Gemini, Anthropic's OpenAI-compatible endpoint, any local proxy). Off when not configured |
| `watch.py` | Background cycle: auto-clean safe tier, purge expired quarantine, quick rescan, toast only on news |
| `cli.py` | argparse commands (below); `diskguardian-w` uses the same entry point with output redirected to the log and results shown as a toast |

### Commands

`status` · `scan [--quick]` · `clean --tier safe|cache|all [--only ids] [--yes]` ·
`dev [--yes]` · `big` · `dupes [roots] [--min-mb N]` · `explain <path>` · `advise` ·
`quarantine <paths> [--yes]` · `qlist` · `restore <batch>` · `purge [--batch id] [--yes]` ·
`history` · `watch` · `config [key value]` · `task install|remove|status`.
Every destructive command is a dry run unless `--yes` is given.

## 4. Rules and tiers

Taken from the current tool and generalised (no owner-specific entries):

| Tier | Behaviour | Rules |
|---|---|---|
| safe | Deleted; the background task runs it automatically | crash dumps, user temp > 3 days, thumbnail cache, WSL crash dumps and stale swap; admin-only: Windows temp, Windows Update download cache, error reports, **Delivery Optimization cache** |
| cache | Deleted only when the user asks; re-downloads later | Chrome/Edge/Brave/Firefox caches, VS Code/Cursor/Windsurf caches, npm/pip/yarn/gradle/nuget caches, `pnpm store prune` / `uv cache prune` when present, Recycle Bin |
| review | Never deleted; quarantine only, after explicit `--yes` | old installers in Downloads, Hugging Face models, idle `node_modules`/`.venv`, **`Windows.old`** (admin; report only — points the user to Windows "Storage Sense", since its ACLs block a normal move) |

Admin-only rules are skipped silently by the background task and run by the
*Deep clean (administrator)* shortcut, which relaunches elevated with UAC.
DeerFlow (Claude as fallback) is asked short questions to find other common junk locations on
typical Windows 10/11 PCs; anything added must be safe or cache tier with a clear source.

## 5. Safety (the part that must not fail)

- `safety.check` refuses: `%SystemRoot%` and `Program Files*` (except the explicit admin
  temp/update paths in rules), `ProgramData` except listed subpaths, drive roots, the user
  profile root and its Documents/Desktop/Pictures/Videos/Music/OneDrive folders for automatic
  rules, `.ssh`, `.gnupg`, `.aws`, the app's own data folder.
- Paths are normalised (case, `..`, short 8.3 names, `\\?\` prefixes) before checking.
- Junctions and symlinks are never followed or deleted through.
- A rule that expands to more than a configured file count or size cap (default 50 GB) aborts
  and is logged instead of running.
- Quarantine moves within the same drive (fast rename); cross-drive targets are refused rather
  than copied.
- Quarantine frees space only on purge; status and toasts say so.

## 6. Notifications

The `watch` cycle toasts only when: free space drops below `warn_free_gb` (default 15) or
`critical_free_gb` (default 8) — once per day per level; usage grew by more than
`growth_alert_gb` since the last week; a weekly digest (optional, off by default). Toast text
says how much safe junk was cleaned and suggests the *Clean junk now* shortcut.

## 7. AI (optional, free options)

Config `ai.base_url`, `ai.model`, key from `ai.api_key` or env `DISKGUARDIAN_AI_KEY`.
`explain <path>` sends only the path, its size and a top-level listing (names and sizes, no file
contents). `advise` sends the scan summary. Both are read-only and cache their answers in
`state\knowledge.json`. Without AI, `explain` answers from the built-in rule descriptions and a
small table of well-known folders; `advise` prints the rule-based recommendations. The README
lists free setups: Ollama (local), OpenRouter free models, Groq, Gemini.

## 8. Installer (Inno Setup 6, free)

`PrivilegesRequired=lowest` (no UAC), install to `{localappdata}\Programs\DiskGuardian`,
Start-menu group with `AppUserModelID: DiskGuardian.Agent`, post-install runs
`diskguardian task install` and an initial quick scan, uninstall runs `task remove` and asks
whether to delete `%LOCALAPPDATA%\DiskGuardian` (warns if quarantine is not empty).
`MinVersion=10.0.17763` (Windows 10 1809, the oldest still common build),
`ArchitecturesAllowed=x64compatible`.

## 9. Build and release (free)

- `build.ps1`: venv → PyInstaller (`diskguardian.spec`) → Inno Setup `iscc` → `dist\`.
- GitHub Actions on `windows-latest` (free for public repos): run tests, build, attach
  `setup.exe` + SHA-256 to a GitHub Release on tag `v*`.
- Publishing to GitHub needs the owner's go-ahead and `gh auth login`; v1 can be built and
  tested locally first.

## 10. Testing

- Unit tests (`unittest`, stdlib) with a fake home and fake drive under a temp dir via
  `DISKGUARDIAN_HOME` — no test ever touches real user folders.
- Safety tests: every refused path class, junction/symlink traversal, 8.3 names, size cap.
- Port the relevant checks from the current `selftest.py`.
- Smoke test of the built exe: `status`, `scan --quick`, dry-run `clean`.
- Manual acceptance on this PC (Windows 11): install, task present, forced low-space toast
  (`warn_free_gb` set above current free), shortcuts, uninstall leaves nothing.
- Windows 10 acceptance: a free VirtualBox VM with the free Windows 10 ISO (runs unactivated),
  or a friend's PC. This is a manual step for the owner.

## 11. Who builds what

| Work | Agent |
|---|---|
| Engine refactor, `safety.py`, review of everything | Claude Code |
| Inno Setup script, PyInstaller spec, `build.ps1`, GitHub Actions workflow, README, extra tests | DeepSeek Harness (free models), reviewed by Claude; Claude takes over if dsh is not working |
| Research on common Windows 10/11 junk locations | DeerFlow (short `flash` questions), Claude fallback |
| — | Hermes not used; the product does not depend on it |

## 12. Open questions

- Product name: "Disk Guardian" may clash with existing software; check before publishing.
