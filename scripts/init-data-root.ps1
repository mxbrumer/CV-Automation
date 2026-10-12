<#
.SYNOPSIS
  Create the DATA_ROOT folder tree used by the Docker stack (D6). Idempotent.

.DESCRIPTION
  DATA_ROOT is resolved from, in order: the -DataRoot parameter, the DATA_ROOT
  environment variable, DATA_ROOT in infra/.env, then C:\dev\JobSearchData.
  Refuses paths inside OneDrive or inside the repo.
#>
param(
    [string]$DataRoot
)

$RepoRoot = Split-Path -Parent $PSScriptRoot

function Get-DotEnvValue([string]$Path, [string]$Name) {
    if (-not (Test-Path $Path)) { return $null }
    foreach ($line in Get-Content $Path) {
        if ($line -match "^\s*$Name\s*=\s*(.*?)\s*$") { return $Matches[1].Trim('"', "'") }
    }
    return $null
}

if (-not $DataRoot) { $DataRoot = $env:DATA_ROOT }
if (-not $DataRoot) { $DataRoot = Get-DotEnvValue (Join-Path $RepoRoot 'infra\.env') 'DATA_ROOT' }
if (-not $DataRoot) { $DataRoot = 'C:\dev\JobSearchData' }

$full = [System.IO.Path]::GetFullPath($DataRoot).TrimEnd('\')
$forbidden = @($RepoRoot, $env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial) | Where-Object { $_ }
foreach ($root in $forbidden) {
    $r = [System.IO.Path]::GetFullPath($root).TrimEnd('\')
    if ($full -eq $r -or $full.StartsWith("$r\", [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Error "DATA_ROOT '$full' is inside '$r'. It must stay outside OneDrive and the repo (D6)."
        exit 1
    }
}

$subdirs = 'applications', 'profile', 'postgres', 'phoenix', 'langflow', 'backups'
foreach ($d in $subdirs) {
    $p = Join-Path $full $d
    if (-not (Test-Path $p)) {
        New-Item -ItemType Directory -Path $p | Out-Null
        Write-Host "created $p"
    }
}
Write-Host "DATA_ROOT ready: $full"
exit 0
