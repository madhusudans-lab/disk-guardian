# Disk Guardian build (Windows PowerShell 5.1 or PowerShell 7).
# Produces dist\DiskGuardian-Setup-<Version>.exe and its .sha256.
# Needs: Python 3.10+ and Inno Setup 6 (winget install JRSoftware.InnoSetup). Both free.
param([string]$Version = "0.1.1")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-Checked([string]$What, [scriptblock]$Block) {
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

Write-Host "== Disk Guardian build $Version"

# 1. Virtual environment
$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { & py -3 -m venv .venv } else { & python -m venv .venv }
    if (-not (Test-Path $py)) { throw "Could not create .venv (is Python 3.10+ installed?)" }
}
Invoke-Checked "pip install" { & $py -m pip install --quiet --upgrade pip "pyinstaller>=6,<7" }

# 2. Tests
$env:PYTHONPATH = "src"
Invoke-Checked "Unit tests" { & $py -m unittest discover -s tests -t . }

# 3. Icon and exe version info
Invoke-Checked "Icon" { & $py packaging\make_icon.py }
$num = ($Version -replace '[^0-9.].*$', '')
$parts = @($num.Split('.') | Where-Object { $_ -ne '' })
while ($parts.Count -lt 4) { $parts += '0' }
$tuple = ($parts[0..3] -join ', ')
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($tuple), prodvers=($tuple)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Disk Guardian contributors'),
    StringStruct('FileDescription', 'Disk Guardian'),
    StringStruct('FileVersion', '$Version'),
    StringStruct('ProductName', 'Disk Guardian'),
    StringStruct('ProductVersion', '$Version'),
    StringStruct('LegalCopyright', 'MIT License')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content -Encoding ASCII packaging\version_info.txt

# 4. PyInstaller (one folder, two programs)
foreach ($d in @("build", "dist\DiskGuardian")) { if (Test-Path $d) { Remove-Item -Recurse -Force $d } }
Invoke-Checked "PyInstaller" { & $py -m PyInstaller packaging\diskguardian.spec --distpath dist --workpath build --noconfirm --log-level WARN }
Invoke-Checked "Smoke test" { & dist\DiskGuardian\diskguardian.exe --version }

# 5. Inno Setup
$iscc = $null
$found = Get-Command iscc -ErrorAction SilentlyContinue
if ($found) { $iscc = $found.Source }
foreach ($c in @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
                 "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                 "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
    if (-not $iscc -and (Test-Path $c)) { $iscc = $c }
}
if (-not $iscc) { throw "Inno Setup 6 not found: winget install JRSoftware.InnoSetup" }
$env:DG_VERSION = $Version
Invoke-Checked "Inno Setup" { & $iscc /Q packaging\installer.iss }

# 6. Checksum
$setup = "dist\DiskGuardian-Setup-$Version.exe"
$hash = (Get-FileHash -Algorithm SHA256 $setup).Hash.ToLower()
"$hash  DiskGuardian-Setup-$Version.exe" | Set-Content -Encoding ASCII "$setup.sha256"
Write-Host "== Built $setup"
Write-Host "   SHA-256 $hash"
