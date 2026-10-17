[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$PackageRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path

foreach ($required in @('RunBot.py', 'source-files', 'requirements.txt')) {
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $required))) {
        throw "The target does not look like the bot project; missing: $required"
    }
}
foreach ($required in @('README.md', 'CHANGELOG.md', 'INSTALL.md', 'docs', 'tools')) {
    if (-not (Test-Path -LiteralPath (Join-Path $PackageRoot $required))) {
        throw "The cleanup package is incomplete; missing: $required"
    }
}
if ($ProjectRoot -eq $PackageRoot) {
    throw 'ProjectRoot must be your working project, not the extracted cleanup package.'
}

$HistoryRoot = Join-Path $ProjectRoot 'docs\history'
$ReleaseHistory = Join-Path $HistoryRoot 'releases'
$ReferenceHistory = Join-Path $HistoryRoot 'original-reference-docs'
$ScriptHistory = Join-Path $ProjectRoot 'tools\history\legacy-release-scripts'
New-Item -ItemType Directory -Force -Path $ReleaseHistory, $ReferenceHistory, $ScriptHistory | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$PreCleanupRoot = Join-Path $HistoryRoot "pre-cleanup-$stamp"
New-Item -ItemType Directory -Force -Path $PreCleanupRoot | Out-Null

function Move-IntoArchive([string]$SourcePath, [string]$DestinationDirectory) {
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) { return }
    New-Item -ItemType Directory -Force -Path $DestinationDirectory | Out-Null
    $name = Split-Path -Leaf $SourcePath
    $destination = Join-Path $DestinationDirectory $name
    if (Test-Path -LiteralPath $destination) {
        $base = [IO.Path]::GetFileNameWithoutExtension($name)
        $ext = [IO.Path]::GetExtension($name)
        $destination = Join-Path $DestinationDirectory "$base-$stamp$ext"
    }
    Move-Item -LiteralPath $SourcePath -Destination $destination
    Write-Host "Archived: $name -> $destination" -ForegroundColor DarkGray
}

Write-Host 'This operation reorganizes documentation and old scripts only; it does not touch databases or the bot token.' -ForegroundColor Cyan
Write-Host "Target project: $ProjectRoot"
$confirmation = Read-Host 'Type MOVE to continue'
if ($confirmation -cne 'MOVE') {
    Write-Host 'Cancelled; no files were moved.' -ForegroundColor Yellow
    exit 1
}

# Preserve the previous front-page docs before installing the new versions.
foreach ($name in @('README.md', 'CHANGELOG.md', 'INSTALL.md')) {
    Move-IntoArchive (Join-Path $ProjectRoot $name) $PreCleanupRoot
}

# Move only the known historical phase/release files from the project root.
Get-ChildItem -LiteralPath $ProjectRoot -File -Filter '*.md' | Where-Object {
    $_.Name -match '^(?i:PHASE[0-9].*|PHASE[0-9]\.[0-9].*|UPDATE_0\.6\..*)$'
} | ForEach-Object {
    Move-IntoArchive $_.FullName $ReleaseHistory
}

# Archive old version-specific maintenance scripts, preserving the files.
$toolsRoot = Join-Path $ProjectRoot 'tools'
if (Test-Path -LiteralPath $toolsRoot -PathType Container) {
    Get-ChildItem -LiteralPath $toolsRoot -File | Where-Object {
        $_.Name -match '^(?i:Backup-Phase.*\.ps1|Backup-Update-.*\.ps1|Verify-Phase.*\.ps1|Move-Phase0.*\.ps1)$'
    } | ForEach-Object {
        Move-IntoArchive $_.FullName $ScriptHistory
    }
}

# Install the curated front-page docs and maintained reference docs from the staged package.
foreach ($name in @('README.md', 'CHANGELOG.md', 'INSTALL.md')) {
    Copy-Item -LiteralPath (Join-Path $PackageRoot $name) -Destination (Join-Path $ProjectRoot $name) -Force
}
$projectDocs = Join-Path $ProjectRoot 'docs'
New-Item -ItemType Directory -Force -Path $projectDocs | Out-Null
Get-ChildItem -LiteralPath (Join-Path $PackageRoot 'docs') -File -Filter '*.md' | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $projectDocs $_.Name) -Force
}

# Copy new general-purpose tools, keeping the existing project source untouched.
New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null
foreach ($name in @('Backup-Project.ps1', 'Test-Project.ps1', 'Organize-Documentation.ps1')) {
    $source = Join-Path (Join-Path $PackageRoot 'tools') $name
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $toolsRoot $name) -Force
    }
}

# Fill historical archives with supplied snapshots only where a destination is absent.
foreach ($relative in @('docs\history\releases', 'docs\history\original-reference-docs')) {
    $sourceDir = Join-Path $PackageRoot $relative
    $targetDir = Join-Path $ProjectRoot $relative
    if (Test-Path -LiteralPath $sourceDir -PathType Container) {
        Get-ChildItem -LiteralPath $sourceDir -File -Recurse -Force | ForEach-Object {
            $subPath = $_.FullName.Substring($sourceDir.Length).TrimStart([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
            $target = Join-Path $targetDir $subPath
            if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
                Copy-Item -LiteralPath $_.FullName -Destination $target
            }
        }
    }
}
$historyReadme = Join-Path (Join-Path $ProjectRoot 'docs\history') 'README.md'
$packageHistoryReadme = Join-Path (Join-Path $PackageRoot 'docs\history') 'README.md'
if (Test-Path -LiteralPath $packageHistoryReadme) {
    Copy-Item -LiteralPath $packageHistoryReadme -Destination $historyReadme -Force
}

Write-Host ''
Write-Host 'Documentation organization finished.' -ForegroundColor Green
Write-Host 'Review git status before committing. No source code, databases, token files, or live data were intentionally changed.' -ForegroundColor Yellow
Write-Host 'The previous README/CHANGELOG/INSTALL are preserved in docs/history/pre-cleanup-*.' -ForegroundColor Yellow
