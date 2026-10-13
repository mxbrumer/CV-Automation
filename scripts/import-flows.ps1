<#
.SYNOPSIS
  Restore langflow/flows/*.json into a running LangFlow (fresh install or after dev.ps1 reset-db)
  and create the global variables the flows read (values come from infra/.env).

  Flows keep their id and endpoint name, so `/api/v1/run/analyze_and_match` works right away.
  Re-running updates the flows in place (upsert by id).

.EXAMPLE
  scripts/import-flows.ps1
  scripts/import-flows.ps1 -Name analyze_and_match -SkipVariables
#>
param(
    [string[]]$Name,
    [switch]$SkipVariables
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib-langflow.ps1')

$auth = Get-LangflowAuth
$base = Get-LangflowUrl

# name -> (value, type, default). Credential values are stored encrypted by LangFlow.
function Get-VariableSpec {
    $ollama = Get-DotEnvValue 'OLLAMA_BASE_URL'
    if (-not $ollama) { $ollama = 'http://host.docker.internal:11434' }
    $agent = Get-DotEnvValue 'LLM_AGENT_MODEL'; if (-not $agent) { $agent = 'ajs-gemma' }
    $writer = Get-DotEnvValue 'LLM_WRITER_MODEL'; if (-not $writer) { $writer = 'ajs-gemma' }
    $embed = Get-DotEnvValue 'EMBED_MODEL'; if (-not $embed) { $embed = 'bge-m3' }
    $keep = Get-DotEnvValue 'LLM_KEEP_ALIVE'; if (-not $keep) { $keep = '30m' }
    return @(
        @{ name = 'OLLAMA_BASE_URL'; value = $ollama; type = 'Generic' },
        @{ name = 'LLM_AGENT_MODEL'; value = $agent; type = 'Generic' },
        @{ name = 'LLM_WRITER_MODEL'; value = $writer; type = 'Generic' },
        @{ name = 'EMBED_MODEL'; value = $embed; type = 'Generic' },
        @{ name = 'LLM_KEEP_ALIVE'; value = $keep; type = 'Generic' },
        @{ name = 'BACKEND_URL'; value = 'http://backend:8000/api/v1'; type = 'Generic' },
        @{ name = 'BACKEND_API_KEY'; value = (Get-DotEnvValue 'BACKEND_API_KEY'); type = 'Credential' }
    )
}

if (-not $SkipVariables) {
    $existing = @(Invoke-RestMethod -Headers $auth -Uri "$base/api/v1/variables/")
    foreach ($spec in Get-VariableSpec) {
        if (-not $spec.value) { throw "Value for global variable $($spec.name) is empty; set it in infra/.env." }
        $body = @{ name = $spec.name; value = $spec.value; type = $spec.type; default_fields = @() } | ConvertTo-Json
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
        $current = $existing | Where-Object { $_.name -eq $spec.name } | Select-Object -First 1
        if ($current) {
            $null = Invoke-RestMethod -Method Patch -Headers $auth -ContentType 'application/json' -Body $bytes `
                -Uri "$base/api/v1/variables/$($current.id)"
            Write-Host "updated variable $($spec.name)"
        }
        else {
            $null = Invoke-RestMethod -Method Post -Headers $auth -ContentType 'application/json' -Body $bytes `
                -Uri "$base/api/v1/variables/"
            Write-Host "created variable $($spec.name)"
        }
    }
}

$files = @(Get-ChildItem -Path $FlowsDir -Filter '*.json' -ErrorAction SilentlyContinue |
    Where-Object { (-not $Name) -or ($Name -contains $_.BaseName) })
if (-not $files) { throw "No flow files in langflow/flows$(if ($Name) { " matching $($Name -join ', ')" })." }

foreach ($file in $files) {
    $text = [System.IO.File]::ReadAllText($file.FullName, [System.Text.Encoding]::UTF8)
    $flow = $text | ConvertFrom-Json
    if (-not $flow.id) { throw "$($file.Name) has no id; re-export it with scripts/export-flows.ps1." }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($text)
    $null = Invoke-RestMethod -Method Put -Headers $auth -ContentType 'application/json; charset=utf-8' -Body $bytes `
        -Uri "$base/api/v1/flows/$($flow.id)"
    Write-Host "imported $($flow.name) ($($flow.id))"
}
