<#
.SYNOPSIS
  Manage the local Docker stack (infra/docker-compose.yml).

.EXAMPLE
  scripts/dev.ps1 up              # start and wait until healthy
  scripts/dev.ps1 logs langflow   # follow logs of one service
  scripts/dev.ps1 reset-db        # drop and recreate both databases (asks first)
  scripts/dev.ps1 backup          # pg_dump both DBs to DATA_ROOT/backups/<date>.sql
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'logs', 'ps', 'reset-db', 'backup')]
    [string]$Command = 'ps',

    [Parameter(Position = 1)]
    [string]$Service,

    # Skip the reset-db confirmation prompt (for scripts such as e2e.ps1).
    [switch]$Force
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $RepoRoot 'infra\docker-compose.yml'
$EnvFile = Join-Path $RepoRoot 'infra\.env'

function Invoke-Compose {
    & docker compose -f $ComposeFile @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($args -join ' ') failed (exit $LASTEXITCODE)" }
}

function Test-DockerDaemon {
    & docker info --format '{{.ServerVersion}}' *> $null
    return ($LASTEXITCODE -eq 0)
}

function Start-DockerDaemon {
    if (Test-DockerDaemon) { return }
    $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (-not (Test-Path $exe)) { throw "Docker daemon is not running and Docker Desktop was not found at $exe" }
    Write-Host 'Starting Docker Desktop...'
    Start-Process $exe | Out-Null
    $deadline = (Get-Date).AddMinutes(4)
    while (-not (Test-DockerDaemon)) {
        if ((Get-Date) -gt $deadline) { throw 'Docker daemon did not become ready within 4 minutes.' }
        Start-Sleep -Seconds 3
    }
    Write-Host 'Docker is ready.'
}

function Get-DotEnvValue([string]$Name) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match "^\s*$Name\s*=\s*(.*?)\s*$") { return $Matches[1].Trim('"', "'") }
    }
    return $null
}

function Initialize-Stack {
    if (-not (Test-Path $EnvFile)) {
        throw "Missing infra/.env. Copy infra/.env.example to infra/.env and fill in the values."
    }
    & (Join-Path $PSScriptRoot 'init-data-root.ps1') -DataRoot (Get-DotEnvValue 'DATA_ROOT')
    if ($LASTEXITCODE -ne 0) { throw 'init-data-root.ps1 failed' }
    Start-DockerDaemon
}

try {
    switch ($Command) {
        'up' {
            Initialize-Stack
            Invoke-Compose up -d --wait
            Invoke-Compose ps
        }
        'down' {
            Start-DockerDaemon
            Invoke-Compose down
        }
        'logs' {
            Start-DockerDaemon
            if ($Service) { Invoke-Compose logs -f --tail 200 $Service }
            else { Invoke-Compose logs -f --tail 200 }
        }
        'ps' {
            Start-DockerDaemon
            Invoke-Compose ps
        }
        'reset-db' {
            Initialize-Stack
            if (-not $Force) {
                Write-Host 'This DROPS the app database and the LangFlow database (flows, users, API keys).' -ForegroundColor Yellow
                $answer = Read-Host "Type 'reset' to continue"
                if ($answer -ne 'reset') { Write-Host 'Aborted.'; exit 1 }
            }
            Invoke-Compose up -d --wait postgres
            # Stop every client of the DBs; `stop` ignores services that are not running.
            Invoke-Compose --profile app stop langflow backend frontend
            # Single-quoted: $POSTGRES_USER expands inside the container.
            Invoke-Compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d postgres -f /scripts/reset-databases.sql'
            Invoke-Compose up -d --wait
            Write-Host 'Databases recreated.'
        }
        'backup' {
            Initialize-Stack
            Invoke-Compose up -d --wait postgres
            $name = "$(Get-Date -Format 'yyyy-MM-dd_HHmmss').sql"
            # Dump inside the container to the mounted backups dir, so PowerShell never re-encodes the output.
            Invoke-Compose exec -T postgres sh /scripts/backup.sh "/backups/$name"
            Write-Host "Backup written to $(Join-Path (Get-DotEnvValue 'DATA_ROOT') "backups\$name")"
        }
    }
}
catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
