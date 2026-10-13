<#
.SYNOPSIS
  Export LangFlow flows into langflow/flows/<name>.json (stable key order, no secrets).

.EXAMPLE
  scripts/export-flows.ps1                       # every flow in LangFlow
  scripts/export-flows.ps1 -Name analyze_and_match
#>
param(
    [string[]]$Name
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib-langflow.ps1')

$auth = Get-LangflowAuth
$base = Get-LangflowUrl
$python = Find-Python
New-Item -ItemType Directory -Force -Path $FlowsDir | Out-Null

$headers = Invoke-RestMethod -Headers $auth -Uri "$base/api/v1/flows/?get_all=true&header_flows=true"
$selected = @($headers | Where-Object { (-not $Name) -or ($Name -contains $_.name) })
if ($Name) {
    foreach ($n in $Name) {
        if (-not ($selected | Where-Object { $_.name -eq $n })) { throw "No flow named '$n' in LangFlow." }
    }
}
if (-not $selected) { Write-Host 'No flows to export.'; return }

foreach ($flow in $selected) {
    $response = Invoke-WebRequest -UseBasicParsing -Headers $auth -Uri "$base/api/v1/flows/$($flow.id)"
    $raw = Join-Path ([System.IO.Path]::GetTempPath()) "ajs-flow-$($flow.id).json"
    [System.IO.File]::WriteAllText($raw, (Read-ResponseText $response), (New-Object System.Text.UTF8Encoding($false)))
    $target = Join-Path $FlowsDir "$($flow.name).json"
    try {
        & $python $NormalizeTool $raw $target
        if ($LASTEXITCODE -ne 0) { throw "normalize_flow.py failed for '$($flow.name)'" }
    }
    finally {
        Remove-Item -Force $raw -ErrorAction SilentlyContinue
    }
    Write-Host "exported $($flow.name) -> langflow/flows/$($flow.name).json"
}
