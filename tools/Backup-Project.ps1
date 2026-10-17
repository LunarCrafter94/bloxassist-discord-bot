[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Project root does not exist: $ProjectRoot"
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

foreach ($required in @('RunBot.py', 'source-files', 'requirements.txt')) {
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $required))) {
        throw "Expected project item was not found: $required"
    }
}

Write-Host ''
Write-Host 'Blox Fruits Helper Credit Bot — project backup' -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"
Write-Host 'Stop the bot with Ctrl+C and close DB Browser for SQLite or other database tools.' -ForegroundColor Yellow
Write-Host 'This script copies files. It does not move or delete your working files.' -ForegroundColor Cyan
Write-Host 'The real token file and other non-example environment files are excluded.' -ForegroundColor Yellow
$confirmation = Read-Host 'Type YES only after the bot and database tools are closed'
if ($confirmation -cne 'YES') {
    Write-Host 'Cancelled. No backup was created.' -ForegroundColor Yellow
    exit 1
}

$stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$backupRoot = Join-Path $ProjectRoot "_backups\project-$stamp"
if (Test-Path -LiteralPath $backupRoot) {
    throw "Backup destination already exists; refusing to overwrite it: $backupRoot"
}
$sourceRoot = Join-Path $backupRoot 'project-files'
$databaseRoot = Join-Path $backupRoot 'database'
New-Item -ItemType Directory -Force -Path $sourceRoot, $databaseRoot | Out-Null

function Copy-TreeSafely([string]$RelativePath) {
    $sourcePath = Join-Path $ProjectRoot $RelativePath
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) { return }
    $files = Get-ChildItem -LiteralPath $sourcePath -File -Recurse -Force
    foreach ($file in $files) {
        $relativeFile = $file.FullName.Substring($ProjectRoot.Length).TrimStart([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
        # Do not exclude a nested directory named 'data' under tests; it may contain fixtures.
        if ($relativeFile -match '(^|[\\/])__pycache__([\\/]|$)') { continue }
        if ($file.Name -match '^(?i:tokens\.env)$') { continue }
        if ($file.Name -match '^(?i:\.env(?:\..*)?)$' -and $file.Name -notmatch '^(?i:\.env\.example)$') { continue }
        if ($file.Name -match '^(?i:.*\.(db|sqlite|sqlite3)(-wal|-shm|-journal)?)$') { continue }
        if ($file.Extension -in @('.pyc', '.pyo', '.log')) { continue }
        $destination = Join-Path $sourceRoot $relativeFile
        $destinationDirectory = Split-Path -Parent $destination
        New-Item -ItemType Directory -Force -Path $destinationDirectory | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination
    }
}

# Copy known project areas while filtering secrets, generated files and databases.
foreach ($relativePath in @('source-files', 'tests', 'tools', 'docs', 'assets', '.vscode')) {
    Copy-TreeSafely -RelativePath $relativePath
}
foreach ($fileName in @('RunBot.py', '.gitignore', 'README.md', 'CHANGELOG.md', 'INSTALL.md', 'requirements.txt', 'pyproject.toml')) {
    $source = Join-Path $ProjectRoot $fileName
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $sourceRoot $fileName)
    }
}
$examplePath = Join-Path $ProjectRoot 'private-configs\tokens.env.example'
if (Test-Path -LiteralPath $examplePath -PathType Leaf) {
    $privateTemplateDirectory = Join-Path $sourceRoot 'private-configs'
    New-Item -ItemType Directory -Force -Path $privateTemplateDirectory | Out-Null
    Copy-Item -LiteralPath $examplePath -Destination $privateTemplateDirectory
}

$dataPath = Join-Path $ProjectRoot 'data'
if (Test-Path -LiteralPath $dataPath -PathType Container) {
    $backupDataPath = Join-Path $databaseRoot 'data'
    New-Item -ItemType Directory -Force -Path $backupDataPath | Out-Null
    Get-ChildItem -LiteralPath $dataPath -Force | Copy-Item -Destination $backupDataPath -Recurse
} else {
    Set-Content -LiteralPath (Join-Path $databaseRoot 'NO-DATA-DIRECTORY.txt') -Value 'No data directory existed at backup time.' -Encoding utf8
    Write-Warning 'No data directory was found. This checkpoint contains no live server databases.'
}

# Create a SHA-256 inventory after copying; the manifest does not hash itself.
$manifestPath = Join-Path $backupRoot 'manifest.csv'
$manifest = Get-ChildItem -LiteralPath $backupRoot -File -Recurse -Force |
    Where-Object { $_.FullName -ne $manifestPath } |
    ForEach-Object {
        [PSCustomObject]@{
            RelativePath = $_.FullName.Substring($backupRoot.Length + 1)
            LengthBytes  = $_.Length
            SHA256       = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    }
$manifest | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding utf8

$totalFiles = (Get-ChildItem -LiteralPath $backupRoot -File -Recurse -Force | Measure-Object).Count
$totalBytes = (Get-ChildItem -LiteralPath $backupRoot -File -Recurse -Force | Measure-Object -Property Length -Sum).Sum
Write-Host ''
Write-Host 'Backup finished.' -ForegroundColor Green
Write-Host "Destination: $backupRoot"
Write-Host "Files: $totalFiles"
Write-Host "Size: $([math]::Round($totalBytes / 1MB, 2)) MB"
Write-Host "Manifest: $manifestPath"
Write-Host 'Review the destination and manifest. The real token file was not copied.' -ForegroundColor Yellow
