<#
.SYNOPSIS
  Pull the local Ollama models this project uses (D1). Idempotent.

.DESCRIPTION
  Always pulls gemma4:12b and bge-m3. With -Baselines it also pulls the plan 04
  benchmark baselines (DFM-Mimir, qwen2.5:14b). Models that are already present
  are skipped. Afterwards it builds the ajs-gemma alias from
  infra/ollama/Gemma.Modelfile (if present) and prints `ollama list`.

.EXAMPLE
  scripts/pull-models.ps1
  scripts/pull-models.ps1 -Baselines
#>
param(
    [switch]$Baselines
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Modelfile = Join-Path $RepoRoot 'infra\ollama\Gemma.Modelfile'

$models = @('gemma4:12b', 'bge-m3')
if ($Baselines) {
    $models += 'hf.co/danish-foundation-models/DFM-Mimir-GGUF:Q4_K_M', 'qwen2.5:14b'
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Error 'ollama is not on PATH. Install Ollama for Windows first.'
    exit 1
}

# `ollama list` names untagged models as <name>:latest.
$installed = & ollama list | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] }

foreach ($m in $models) {
    $name = if ($m -match ':') { $m } else { "${m}:latest" }
    if ($installed -contains $name) {
        Write-Host "present  $m"
        continue
    }
    Write-Host "pulling  $m"
    & ollama pull $m
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ollama pull $m failed (exit $LASTEXITCODE)"
        exit 1
    }
}

if (Test-Path $Modelfile) {
    Write-Host 'creating ajs-gemma from infra/ollama/Gemma.Modelfile'
    & ollama create ajs-gemma -f $Modelfile
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ollama create ajs-gemma failed (exit $LASTEXITCODE)"
        exit 1
    }
}

& ollama list
exit 0
