param([string]$Python = 'py', [switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$packageRoot = $PSScriptRoot
$buildRoot = Join-Path $packageRoot 'Build'
$venvPython = Join-Path $buildRoot 'venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($Python -eq 'py') { & $Python -3.12 -m venv (Join-Path $buildRoot 'venv') }
    else { & $Python -m venv (Join-Path $buildRoot 'venv') }
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 environment creation failed.' }
}
& $venvPython -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Requires Python 3.12 x64'"
if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python version.' }
if (-not $SkipInstall) {
    & $venvPython -m pip install -r (Join-Path $packageRoot 'Source/requirements-windows-lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
$env:QT_QPA_PLATFORM = 'offscreen'
& $venvPython -m unittest discover -s (Join-Path $packageRoot 'Source') -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Regression tests failed.' }
Remove-Item Env:QT_QPA_PLATFORM
& $venvPython -m PyInstaller --noconfirm --distpath (Join-Path $packageRoot 'Portable') --workpath (Join-Path $buildRoot 'work') (Join-Path $packageRoot 'Source/MIR Cleanup Windows.spec')
if ($LASTEXITCODE -ne 0) { throw 'Windows packaging failed.' }
Write-Host 'Build complete. Run the packaged verification before distributing.'
