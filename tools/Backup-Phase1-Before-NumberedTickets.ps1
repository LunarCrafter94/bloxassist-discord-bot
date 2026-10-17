[CmdletBinding()]
param(
    [string]$ProjectRoot = 'D:\Repositories\Local\bloxfruits-helper-credit-bot'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Project folder not found: $ProjectRoot"
}

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$BackupRoot = Join-Path $ProjectRoot '_backups'
$Timestamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$BackupPath = Join-Path $BackupRoot "phase1-before-numbered-tickets-$Timestamp"
$SourceBackup = Join-Path $BackupPath 'source-code'
$DatabaseBackup = Join-Path $BackupPath 'database'
$ProjectFilesBackup = Join-Path $BackupPath 'project-files'

Write-Host ''
Write-Host 'BloxAssist - Phase 1 pre-installation backup' -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"
Write-Host "Backup:  $BackupPath"
Write-Host ''
Write-Host 'Before continuing, stop the bot (Ctrl+C) and close DB Browser for SQLite.' -ForegroundColor Yellow
Write-Host 'The real tokens.env/.env file will NOT be copied into this backup.' -ForegroundColor Yellow
$confirmation = Read-Host 'Type YES only after the bot and database tools are closed'
if ($confirmation -cne 'YES') {
    Write-Host 'Cancelled. No backup was created.' -ForegroundColor Yellow
    exit 1
}

New-Item -ItemType Directory -Path $SourceBackup, $DatabaseBackup, $ProjectFilesBackup -Force | Out-Null

function Get-RelativePath([string]$BasePath, [string]$FullPath) {
    $baseWithSeparator = $BasePath.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    return $FullPath.Substring($baseWithSeparator.Length)
}

function Copy-FilePreservingPath([System.IO.FileInfo]$File, [string]$DestinationRoot, [string]$RelativeTo) {
    $relativePath = Get-RelativePath -BasePath $RelativeTo -FullPath $File.FullName
    $destinationPath = Join-Path $DestinationRoot $relativePath
    $destinationDirectory = Split-Path -Parent $destinationPath
    New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
    Copy-Item -LiteralPath $File.FullName -Destination $destinationPath -Force
}

# 1) Back up every project .py file, while excluding generated environments,
# prior backups, live data, secrets, and Git internals.
$excludedPathPattern = '(?i)\\(_backups|\.venv|\.venv-old|\.git|data|private-configs)(\\|$)'
$pythonFiles = Get-ChildItem -LiteralPath $ProjectRoot -File -Recurse -Force -Filter '*.py' |
    Where-Object {
        $_.FullName -notmatch $excludedPathPattern -and
        $_.FullName -notmatch '(?i)\\(__pycache__)(\\|$)' -and
        $_.Extension -eq '.py'
    }

foreach ($file in $pythonFiles) {
    Copy-FilePreservingPath -File $file -DestinationRoot $SourceBackup -RelativeTo $ProjectRoot
}

# Also preserve the primary source package directory in case it contains
# non-Python source files (for example package metadata or text resources).
$sourcePackageDir = Join-Path $ProjectRoot 'source-files'
if (Test-Path -LiteralPath $sourcePackageDir -PathType Container) {
    Get-ChildItem -LiteralPath $sourcePackageDir -File -Recurse -Force |
        Where-Object {
            $_.FullName -notmatch '(?i)\\(__pycache__)(\\|$)' -and
            $_.Extension -notin @('.pyc', '.pyo')
        } |
        ForEach-Object {
            Copy-FilePreservingPath -File $_ -DestinationRoot $SourceBackup -RelativeTo $ProjectRoot
        }
}

# 2) Back up SQLite database files and any WAL/SHM/journal sidecars.
# Preserve each database's relative path under _backups/.../database/.
$databaseFiles = Get-ChildItem -LiteralPath $ProjectRoot -File -Recurse -Force |
    Where-Object {
        $_.FullName -notmatch '(?i)\\(_backups|\.venv|\.venv-old|\.git|private-configs)(\\|$)' -and
        $_.Name -match '(?i)\.(db|sqlite|sqlite3)(-wal|-shm|-journal)?$'
    }

foreach ($file in $databaseFiles) {
    Copy-FilePreservingPath -File $file -DestinationRoot $DatabaseBackup -RelativeTo $ProjectRoot
}

# 3) Back up safe project-level files and selected support folders.
$safeRootFiles = @(
    '.gitignore',
    'README.md',
    'PHASE1_INSTALL.md',
    'pyproject.toml',
    'requirements.txt',
    'tokens.env.example',
    '.env.example'
)
foreach ($name in $safeRootFiles) {
    $path = Join-Path $ProjectRoot $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Copy-Item -LiteralPath $path -Destination (Join-Path $ProjectFilesBackup $name) -Force
    }
}

foreach ($directoryName in @('.vscode', 'docs', 'assets', 'tools')) {
    $sourceDirectory = Join-Path $ProjectRoot $directoryName
    if (Test-Path -LiteralPath $sourceDirectory -PathType Container) {
        $destinationDirectory = Join-Path $ProjectFilesBackup $directoryName
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
        Get-ChildItem -LiteralPath $sourceDirectory -File -Recurse -Force |
            Where-Object {
                $_.FullName -notmatch '(?i)\\(__pycache__)(\\|$)' -and
                $_.Extension -notin @('.pyc', '.pyo', '.log')
            } |
            ForEach-Object {
                Copy-FilePreservingPath -File $_ -DestinationRoot $ProjectFilesBackup -RelativeTo $ProjectRoot
            }
    }
}

# Include safe environment template(s) from private-configs, but never tokens.env.
$privateConfigDir = Join-Path $ProjectRoot 'private-configs'
if (Test-Path -LiteralPath $privateConfigDir -PathType Container) {
    Get-ChildItem -LiteralPath $privateConfigDir -File -Force |
        Where-Object { $_.Name -match '(?i)\.env\.example$' } |
        ForEach-Object {
            Copy-FilePreservingPath -File $_ -DestinationRoot $ProjectFilesBackup -RelativeTo $ProjectRoot
        }
}

# 4) Write a SHA-256 manifest so the backup can be inventoried and checked later.
$manifestPath = Join-Path $BackupPath 'manifest.csv'
$manifestRows = Get-ChildItem -LiteralPath $BackupPath -File -Recurse -Force |
    Where-Object { $_.FullName -ne $manifestPath } |
    ForEach-Object {
        [PSCustomObject]@{
            RelativePath = Get-RelativePath -BasePath $BackupPath -FullPath $_.FullName
            LengthBytes  = $_.Length
            SHA256       = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    }
$manifestRows | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding UTF8

# 5) Report results.
$sourceCount = (Get-ChildItem -LiteralPath $SourceBackup -File -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object).Count
$databaseCount = (Get-ChildItem -LiteralPath $DatabaseBackup -File -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object).Count
$projectFileCount = (Get-ChildItem -LiteralPath $ProjectFilesBackup -File -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object).Count
$totalBytes = (Get-ChildItem -LiteralPath $BackupPath -File -Recurse -Force | Measure-Object -Property Length -Sum).Sum

Write-Host ''
Write-Host 'Backup completed.' -ForegroundColor Green
Write-Host "Location:       $BackupPath"
Write-Host "Source files:   $sourceCount"
Write-Host "Database files: $databaseCount"
Write-Host "Project files:  $projectFileCount"
Write-Host "Total size:     $([math]::Round($totalBytes / 1KB, 2)) KB"
Write-Host "Manifest:       $manifestPath"
Write-Host ''
Write-Host 'Excluded: tokens.env/.env, .venv, .venv-old, Git internals, existing _backups.' -ForegroundColor Yellow
Write-Host 'This script COPIES files; it does not move or delete your working files.' -ForegroundColor Cyan

if ($sourceCount -eq 0) {
    Write-Warning 'No Python source files were found in the expected project layout.'
}
if ($databaseCount -eq 0) {
    Write-Warning 'No database files were found. Confirm whether the bot has initialized a guild database yet.'
}
