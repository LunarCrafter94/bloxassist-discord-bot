$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $ProjectRoot

$PythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Virtual environment Python was not found: $PythonPath"
}

Write-Host 'Checking Python source syntax...'
& $PythonPath -m compileall -q RunBot.py source-files tests
if ($LASTEXITCODE -ne 0) {
    throw 'Python compilation check failed.'
}

Write-Host 'Running database isolation and transaction-safety tests...'
& $PythonPath -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) {
    throw 'Database and transaction tests failed.'
}

Write-Host 'Phase 2 verification passed. The bot was not started and no live database was intentionally touched.' -ForegroundColor Green
