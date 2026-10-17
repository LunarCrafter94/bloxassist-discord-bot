param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Project root does not exist: $ProjectRoot"
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
foreach ($relativePath in @('RunBot.py', 'source-files', 'requirements.txt', '.gitignore')) {
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $relativePath))) {
        throw "Expected Phase 2 item was not found: $relativePath"
    }
}

Write-Host "Project to back up: $ProjectRoot"
Write-Host 'Stop the bot with Ctrl+C and close DB Browser for SQLite before continuing.'
Write-Host 'The actual private-configs\tokens.env is deliberately excluded from this backup.'
$confirmation = Read-Host 'Type YES after the bot and SQLite tools are closed'
if ($confirmation -cne 'YES') {
    Write-Host 'Cancelled. No files were copied.'
    exit 1
}

$stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$backupRoot = Join-Path $ProjectRoot "_backups\phase2-before-phase3-$stamp"
$sourceBackup = Join-Path $backupRoot 'source-code'
$databaseBackup = Join-Path $backupRoot 'database'
$projectBackup = Join-Path $backupRoot 'project-files'
New-Item -ItemType Directory -Force -Path $sourceBackup, $databaseBackup, $projectBackup | Out-Null

Copy-Item -LiteralPath (Join-Path $ProjectRoot 'RunBot.py') -Destination $sourceBackup
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'source-files') -Destination $sourceBackup -Recurse
foreach ($relativePath in @('tests', 'tools')) {
    $sourcePath = Join-Path $ProjectRoot $relativePath
    if (Test-Path -LiteralPath $sourcePath -PathType Container) {
        Copy-Item -LiteralPath $sourcePath -Destination $sourceBackup -Recurse
    }
}
$dataPath = Join-Path $ProjectRoot 'data'
if (Test-Path -LiteralPath $dataPath -PathType Container) {
    Copy-Item -LiteralPath $dataPath -Destination $databaseBackup -Recurse
} else {
    Set-Content -LiteralPath (Join-Path $databaseBackup 'NO-DATA-DIRECTORY.txt') `
        -Value 'No data directory existed at backup time.' -Encoding utf8
    Write-Warning 'No data directory was found; source files were backed up but no live guild databases were copied.'
}
foreach ($relativePath in @('.gitignore', 'README.md', 'requirements.txt', 'pyproject.toml', 'PHASE1_INSTALL.md', 'PHASE2_INSTALL.md', 'PHASE2_CHANGELOG.md', 'PHASE3_INSTALL.md', '.vscode', 'docs', 'assets')) {
    $sourcePath = Join-Path $ProjectRoot $relativePath
    if (Test-Path -LiteralPath $sourcePath) {
        Copy-Item -LiteralPath $sourcePath -Destination $projectBackup -Recurse
    }
}
$examplePath = Join-Path $ProjectRoot 'private-configs\tokens.env.example'
if (Test-Path -LiteralPath $examplePath) {
    $privateTemplateDir = Join-Path $projectBackup 'private-configs'
    New-Item -ItemType Directory -Force -Path $privateTemplateDir | Out-Null
    Copy-Item -LiteralPath $examplePath -Destination $privateTemplateDir
}
$inventory = Get-ChildItem -LiteralPath $backupRoot -Recurse -File | ForEach-Object {
    [pscustomobject]@{
        RelativePath = $_.FullName.Substring($backupRoot.Length + 1)
        LengthBytes  = $_.Length
        SHA256       = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
}
$inventory | Export-Csv -LiteralPath (Join-Path $backupRoot 'manifest.csv') -NoTypeInformation -Encoding utf8
Write-Host ''
Write-Host 'Phase 2 checkpoint created:' -ForegroundColor Green
Write-Host $backupRoot
Write-Host 'The working files were copied, not moved or deleted.'
