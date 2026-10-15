<#
.SYNOPSIS
  Shared helpers for export-flows.ps1 and import-flows.ps1 (dot-source this file).
  Reads infra/.env the same way dev.ps1 does; secrets are never printed.
#>
$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $RepoRoot 'infra\.env'
$FlowsDir = Join-Path $RepoRoot 'langflow\flows'
$NormalizeTool = Join-Path $RepoRoot 'langflow\tools\normalize_flow.py'

function Get-DotEnvValue([string]$Name) {
    if (-not (Test-Path $EnvFile)) { throw "Missing infra/.env (copy infra/.env.example)." }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match "^\s*$Name\s*=\s*(.*?)\s*$") { return $Matches[1].Trim('"', "'") }
    }
    return $null
}

function Get-LangflowUrl {
    if ($env:LANGFLOW_URL) { return $env:LANGFLOW_URL.TrimEnd('/') }
    return 'http://127.0.0.1:7860'
}

# Logs in as the superuser from infra/.env and returns the Authorization header.
function Get-LangflowAuth {
    $user = Get-DotEnvValue 'LANGFLOW_SUPERUSER'
    $password = Get-DotEnvValue 'LANGFLOW_SUPERUSER_PASSWORD'
    if (-not $user -or -not $password) { throw 'LANGFLOW_SUPERUSER / LANGFLOW_SUPERUSER_PASSWORD missing in infra/.env' }
    $token = Invoke-RestMethod -Method Post -Uri "$(Get-LangflowUrl)/api/v1/login" `
        -ContentType 'application/x-www-form-urlencoded' -Body @{ username = $user; password = $password }
    return @{ Authorization = "Bearer $($token.access_token)" }
}

# Invoke-WebRequest in Windows PowerShell 5.1 decodes JSON without a charset as ISO-8859-1; read the bytes.
function Read-ResponseText($Response) {
    $stream = $Response.RawContentStream
    $stream.Position = 0
    $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
    return $reader.ReadToEnd()
}

function Find-Python {
    foreach ($candidate in 'python', 'py') {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) { return $candidate }
    }
    throw 'python (3.10+) is needed to normalize flow JSON; install it or add it to PATH.'
}
