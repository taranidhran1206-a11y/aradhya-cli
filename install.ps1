# Aradhya Code installer for Windows (PowerShell 5.1 or 7).
#
#   irm https://raw.githubusercontent.com/taranidhran1206-a11y/unknown-project/main/docs/install.ps1 | iex
#
# Installs into its own folder (%USERPROFILE%\.aradhya\venv), so it never touches your other Python projects,
# and adds the `ara` command to your PATH. Run it again any time to update.
#
# Options (set before running):
#   $env:ARA_MINIMAL=1    skip the Gemini SDK and Pillow
#   $env:ARA_NO_SETUP=1   don't start setup at the end (run `ara setup` later)
#   $env:ARA_SOURCE=...   install from another URL or a local folder
#   $env:ARA_UNINSTALL=1  remove Aradhya Code (keeps your sessions and key in %USERPROFILE%\.aradhya)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoZip = "https://github.com/taranidhran1206-a11y/unknown-project/archive/refs/heads/main.zip"
$Source  = if ($env:ARA_SOURCE) { $env:ARA_SOURCE } else { $RepoZip }
$HomeDir = if ($env:ARA_HOME) { $env:ARA_HOME } else { Join-Path $HOME ".aradhya" }
$Venv    = Join-Path $HomeDir "venv"
$BinDir  = Join-Path $HomeDir "bin"
$Esc     = [char]27
$Dot = [char]0x25CF; $Star = [char]0x2726; $Cross = [char]0x2717; $Arrow = [char]0x2192

function Say($t)  { Write-Host $t }
function Step($t) { Write-Host "$Esc[38;2;232;181;91m$Dot$Esc[0m $t" }
function Fail($t) { Write-Host "$Esc[38;2;229;83;75m$Cross $t$Esc[0m"; throw "Aradhya Code install failed: $t" }

try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

Say ""
Say "  $Esc[38;2;232;181;91m$Star $Esc[1mAradhya Code$Esc[0m  $Esc[2minstaller$Esc[0m"
Say ""

function Remove-FromUserPath($dir) {
    $p = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($p) {
        $new = ($p -split ";" | Where-Object { $_ -and ($_.TrimEnd("\") -ne $dir.TrimEnd("\")) }) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $new, "User")
    }
}

if ($env:ARA_UNINSTALL) {
    if (Test-Path $Venv)   { Remove-Item -Recurse -Force $Venv }
    if (Test-Path $BinDir) { Remove-Item -Recurse -Force $BinDir }
    Remove-FromUserPath $BinDir
    Step "Removed Aradhya Code. Your sessions and key are still in $HomeDir (delete that folder to remove them too)."
    return
}

# -- Python ------------------------------------------------
function Find-Python {
    $candidates = @(
        @{ Exe = "py";      Args = @("-3") },
        @{ Exe = "python";  Args = @() },
        @{ Exe = "python3"; Args = @() }
    )
    foreach ($dir in @("$env:LOCALAPPDATA\Programs\Python\Python313", "$env:LOCALAPPDATA\Programs\Python\Python312",
                       "$env:LOCALAPPDATA\Programs\Python\Python311", "$env:ProgramFiles\Python313", "$env:ProgramFiles\Python312")) {
        $candidates += @{ Exe = (Join-Path $dir "python.exe"); Args = @() }
    }
    foreach ($c in $candidates) {
        try {
            $out = & $c.Exe @($c.Args + @("-c", "import sys; print(sys.version_info >= (3, 9))")) 2>$null
            if ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq "True") { return $c }
        } catch {}
    }
    return $null
}

$Py = Find-Python
if (-not $Py) {
    Say "  Python 3.9 or newer is needed and wasn't found."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        $ans = Read-Host "  Install Python 3.12 now with winget? [Y/n]"
        if ($ans -eq "" -or $ans -match "^[Yy]") {
            Step "Installing Python 3.12 (winget)..."
            winget install --exact --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Null
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
            $Py = Find-Python
        }
    }
    if (-not $Py) { Fail "Install Python from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again." }
}
$PyVer = & $Py.Exe @($Py.Args + @("--version")) 2>&1
Step "Using $PyVer"

# -- Its own environment -----------------------------------
New-Item -ItemType Directory -Force -Path $HomeDir | Out-Null
$VPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VPy)) {
    Step "Creating $Venv"
    & $Py.Exe @($Py.Args + @("-m", "venv", $Venv))
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VPy)) { Fail "Couldn't create the Python environment in $Venv." }
}
& $VPy -m pip install --quiet --disable-pip-version-check --upgrade pip 2>$null | Out-Null

$Extra = if ($env:ARA_MINIMAL) { "" } else { "[full]" }
if ($Source -like "http*") { $Pkg = "aradhya-code$Extra @ $Source" } else { $Pkg = "$Source$Extra" }
Step ("Installing Aradhya Code" + $(if ($Extra) { " (with the Gemini SDK and Pillow)" } else { "" }) + "...")
& $VPy -m pip install --quiet --disable-pip-version-check --upgrade --force-reinstall --no-deps $Pkg
if ($LASTEXITCODE -ne 0) { Fail "pip couldn't install Aradhya Code (see the error above)." }
& $VPy -m pip install --quiet --disable-pip-version-check --upgrade $Pkg
if ($LASTEXITCODE -ne 0) { Fail "pip couldn't install the dependencies (see the error above)." }

# -- The `ara` command -------------------------------------
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$AraExe = Join-Path $Venv "Scripts\ara.exe"
$Shim = "@echo off`r`n`"$AraExe`" %*`r`n"
[IO.File]::WriteAllText((Join-Path $BinDir "ara.cmd"), $Shim, (New-Object Text.UTF8Encoding($false)))
$Version = & $AraExe --version 2>$null
Step "Installed $Esc[1m$Version$Esc[0m $Arrow $BinDir\ara.cmd"

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $UserPath) { $UserPath = "" }
$OnPath = ($UserPath -split ";" | Where-Object { $_.TrimEnd("\") -eq $BinDir.TrimEnd("\") }).Count -gt 0
if (-not $OnPath) {
    [Environment]::SetEnvironmentVariable("Path", ($BinDir + ";" + $UserPath).TrimEnd(";"), "User")
}
if (-not (($env:Path -split ";") -contains $BinDir)) { $env:Path = "$BinDir;$env:Path" }

# -- Setup: her brain, sign-in, model ----------------------
# `ara setup` asks your name, lets you pick a brain (Google sign-in, OpenRouter, OpenAI, Anthropic, Ollama...),
# signs you in or takes a key, picks a model and checks she answers. Skipped if she's already set up.
$EnvFile = Join-Path $HomeDir ".env"
$HasKey = $env:GEMINI_API_KEY -or ((Test-Path $EnvFile) -and (Select-String -Path $EnvFile -Pattern "^GEMINI_API_KEY=." -Quiet))
$SetUp = Test-Path (Join-Path $HomeDir "config.json")
if (-not $env:ARA_NO_SETUP -and -not $env:ARA_NO_KEY -and -not $HasKey -and -not $SetUp) {
    Say ""
    & $AraExe setup
    if ($LASTEXITCODE -ne 0) { Say "  $Esc[2mYou can finish this later with: ara setup$Esc[0m" }
}

Say ""
Say "  $Esc[38;2;232;181;91m$Star$Esc[0m Done. Go to a project folder and run: $Esc[1mara$Esc[0m"
Say "  $Esc[2m(Already-open terminals need restarting to see it. Best in Windows Terminal.)$Esc[0m"
Say ""
