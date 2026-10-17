$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Local Python environment not found: $python. Create .venv first or adjust this script."
}
& $python -m compileall -q RunBot.py source-files tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation check failed." }
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Unit tests failed." }
Write-Host "Phase 1 verification passed. No bot was started and no live database was touched."
