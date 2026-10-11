<#
.SYNOPSIS
    Verifies the deployable ZIP: build -> install -> enable -> use -> disable.

.DESCRIPTION
    1. Builds dist/Blender_LowCheck-v<version>.zip via tools/build_addon.py
    2. Extracts the ZIP into a temporary user-scripts addons directory
       (%TEMP%\lowcheck_addon_test\scripts\addons\Blender_LowCheck)
    3. Launches Blender with BLENDER_USER_SCRIPTS pointing at it
    4. tests/test_addon_install.py drives addon_utils through the whole
       discover -> enable -> use -> disable -> re-enable lifecycle
    5. Cleans up the temporary directory

.PARAMETER BlenderExe
    Path to the Blender executable. When omitted, the BLENDER_EXE
    environment variable is used.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\run_install_test.ps1 `
        -BlenderExe "C:\Program Files\Blender Foundation\Blender 3.4\blender.exe"

.EXAMPLE
    $env:BLENDER_EXE = "C:\Program Files\Blender Foundation\Blender 3.4\blender.exe"
    powershell -ExecutionPolicy Bypass -File tools\run_install_test.ps1
#>
param(
    [string]$BlenderExe = $env:BLENDER_EXE
)

$pluginDir = Split-Path -Parent $PSScriptRoot
$testScript = Join-Path $pluginDir "tests\test_addon_install.py"
$buildScript = Join-Path $PSScriptRoot "build_addon.py"
$distDir = Join-Path $pluginDir "dist"
$tempRoot = Join-Path $env:TEMP "lowcheck_addon_test"
$scriptsDir = Join-Path $tempRoot "scripts"
$addonsDir = Join-Path $scriptsDir "addons"

if ([string]::IsNullOrWhiteSpace($BlenderExe)) {
    Write-Host "ERROR: Blender executable not specified." -ForegroundColor Red
    Write-Host "       Pass -BlenderExe <path> or set the BLENDER_EXE environment variable." -ForegroundColor Red
    exit 2
}

if (-not (Test-Path $BlenderExe)) {
    Write-Host "ERROR: Blender executable not found: $BlenderExe" -ForegroundColor Red
    exit 2
}

# Native stderr output must not abort the script
$previousEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"

Write-Host "[1/5] Building the deployable ZIP"
$buildOutput = & $BlenderExe --background --factory-startup --python-exit-code 3 `
    --python $buildScript 2>&1 | Out-String
$buildExit = $LASTEXITCODE
$buildOutput -split "`r?`n" | Where-Object { $_ -match "^\[build\]" } | ForEach-Object { Write-Host $_ }
if ($buildExit -ne 0) {
    Write-Host "ERROR: build failed (exit=$buildExit)" -ForegroundColor Red
    $ErrorActionPreference = $previousEap
    exit $buildExit
}

$zipFile = Get-ChildItem -Path $distDir -Filter "Blender_LowCheck-v*.zip" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $zipFile) {
    Write-Host "ERROR: no ZIP produced in $distDir" -ForegroundColor Red
    $ErrorActionPreference = $previousEap
    exit 4
}
Write-Host "      ZIP: $($zipFile.FullName)"

Write-Host "[2/5] Preparing temporary script dir: $scriptsDir"
if (Test-Path $tempRoot) { Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $addonsDir | Out-Null

Write-Host "[3/5] Extracting the ZIP into the addons directory"
Expand-Archive -Path $zipFile.FullName -DestinationPath $addonsDir -Force
if (-not (Test-Path (Join-Path $addonsDir "Blender_LowCheck\__init__.py"))) {
    Write-Host "ERROR: extracted ZIP has an unexpected layout" -ForegroundColor Red
    $ErrorActionPreference = $previousEap
    exit 5
}

Write-Host "[4/5] Launching Blender with the temporary user-scripts dir"
$env:BLENDER_USER_SCRIPTS = $scriptsDir
$env:BLENDER_USER_CONFIG = (Join-Path $tempRoot "config")

$output = & $BlenderExe --background --factory-startup --python-exit-code 7 `
    --python $testScript 2>&1 | Out-String
$exitCode = $LASTEXITCODE
$ErrorActionPreference = $previousEap

$output -split "`r?`n" |
    Where-Object { $_ -notmatch "fake_module|NativeCommandError|CategoryInfo|FullyQualifiedErrorId|^\s*\+" -and $_.Trim() } |
    ForEach-Object { Write-Host $_ }

Write-Host "[5/5] Cleaning up"
Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue

if ($exitCode -ne 0) {
    Write-Host "Install-lifecycle test FAILED (exit=$exitCode)" -ForegroundColor Red
    exit $exitCode
}

Write-Host "Install-lifecycle test PASSED" -ForegroundColor Green
exit 0
