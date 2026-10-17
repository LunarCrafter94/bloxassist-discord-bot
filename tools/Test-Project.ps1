[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $ProjectRoot
$PythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Project virtual-environment Python was not found: $PythonPath`nCreate .venv and install requirements.txt before running this check."
}

Write-Host 'Compiling Python source...' -ForegroundColor Cyan
& $PythonPath -m compileall -q RunBot.py source-files tests
if ($LASTEXITCODE -ne 0) { throw 'Python compilation check failed.' }

Write-Host 'Running automated tests...' -ForegroundColor Cyan
& $PythonPath -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Automated tests failed.' }

Write-Host 'Local verification passed. The bot was not started.' -ForegroundColor Green
Write-Host 'Automated tests do not replace live Discord workflow and permission testing.' -ForegroundColor Yellow
