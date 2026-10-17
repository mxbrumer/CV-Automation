<#
.SYNOPSIS
  End-to-end check (plans 14, 15): Add job -> analysis -> gate 1 -> generation, on a throwaway
  DATA_ROOT.

.DESCRIPTION
  Runs the whole Docker stack against a separate DATA_ROOT (default C:\dev\JobSearchData-e2e):
  fresh Postgres, LangFlow, Phoenix and blob folders, with the profile seeded from
  docs/profile-examples/*.example.md. Your real DATA_ROOT (infra/.env) is not read or written
  by the stack during the run, so no reset is needed.

  The jobs are scripts/e2e/jobs.json (synthetic, 4 postings), sent to POST /postings the way the
  Add job form sends them. Expected outcome:
    1 duplicate  (second copy of the Nordlys posting, same URL: refused with 409 same_url)
    1 low_match  (nurse posting)
    2 awaiting_match_review -> approve Nordlys (generated), decline Fjordbyg (match_declined)
    the approved posting has cv, cover letter and recruiter email, with the two PDFs on disk.

  Afterwards the real stack is brought back up on your own DATA_ROOT unless -NoRestore.

.EXAMPLE
  scripts/e2e.ps1
  scripts/e2e.ps1 -NoRestore -TimeoutMin 60
#>
param(
    [string]$DataRoot = 'C:/dev/JobSearchData-e2e',
    [int]$TimeoutMin = 45,
    [switch]$NoRestore
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib-langflow.ps1')

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Dev = Join-Path $PSScriptRoot 'dev.ps1'
$JobsFile = Join-Path $PSScriptRoot 'e2e\jobs.json'
$Api = 'http://127.0.0.1:8000/api/v1'

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$Name, [bool]$Ok, [string]$Detail = '') {
    $results.Add([pscustomobject]@{ Check = $Name; Result = $(if ($Ok) { 'PASS' } else { 'FAIL' }); Detail = $Detail })
    $color = if ($Ok) { 'Green' } else { 'Red' }
    Write-Host ("[{0}] {1} {2}" -f ($(if ($Ok) { 'PASS' } else { 'FAIL' })), $Name, $Detail) -ForegroundColor $color
}

# Refuse to run against the real data folder: this script is meant to leave it alone.
$realRoot = (Get-DotEnvValue 'DATA_ROOT')
if ($realRoot -and ([IO.Path]::GetFullPath($DataRoot).TrimEnd('\') -eq [IO.Path]::GetFullPath($realRoot).TrimEnd('\'))) {
    throw "DataRoot must differ from the DATA_ROOT in infra/.env ($realRoot)."
}
$DataRoot = [IO.Path]::GetFullPath($DataRoot).TrimEnd('\')

$backendKey = Get-DotEnvValue 'BACKEND_API_KEY'
if (-not $backendKey) { throw 'BACKEND_API_KEY missing in infra/.env' }
$headers = @{ 'X-API-Key' = $backendKey }

function Get-Postings {
    (Invoke-RestMethod -Headers $headers -Uri "$Api/postings?page_size=100&sort=recent").items
}

# POST /postings; returns the HTTP status and the parsed body (a 409 is an answer, not an error).
function Add-Job($Job) {
    $bytes = [Text.Encoding]::UTF8.GetBytes(($Job | ConvertTo-Json -Compress))
    try {
        $created = Invoke-RestMethod -Headers $headers -Method Post -Uri "$Api/postings" `
            -ContentType 'application/json; charset=utf-8' -Body $bytes
        return [pscustomobject]@{ Status = 201; Body = $created }
    }
    catch {
        $response = $_.Exception.Response
        if (-not $response) { throw }
        $body = if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message | ConvertFrom-Json } else { $null }
        return [pscustomobject]@{ Status = [int]$response.StatusCode; Body = $body }
    }
}

function Wait-Until([string]$What, [scriptblock]$Done, [int]$Minutes) {
    $deadline = (Get-Date).AddMinutes($Minutes)
    while ((Get-Date) -lt $deadline) {
        if (& $Done) { return $true }
        Start-Sleep -Seconds 15
    }
    Write-Host "Timed out after $Minutes min waiting for: $What" -ForegroundColor Yellow
    return $false
}

$env:DATA_ROOT = $DataRoot
# PowerShell deletes an env var set to '' instead of emptying it, and compose would then fall back
# to the real value in infra/.env. So the first start gets a key that cannot work.
$env:LANGFLOW_API_KEY = 'e2e-pending'
try {
    # 1. Ollama must be up on the host (D2); the pipeline cannot run without it.
    try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 | Out-Null }
    catch { throw 'Ollama is not reachable on 127.0.0.1:11434. Start it first.' }

    # 2. Fresh data root: stop the stack, then clear the database and app folders of the e2e root.
    # Only a folder named JobSearchData-e2e is ever cleared, and the profile is never touched.
    if ((Split-Path -Leaf $DataRoot) -ne 'JobSearchData-e2e') {
        throw "Refusing to clear '$DataRoot': the e2e data root must be named JobSearchData-e2e."
    }
    & $Dev down
    if ($LASTEXITCODE -ne 0) { throw 'dev.ps1 down failed' }
    foreach ($dir in 'postgres', 'backups', 'phoenix', 'langflow', 'applications') {
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $DataRoot $dir)
    }

    # 3. Seed the profile from the example stubs (never the real profile).
    foreach ($dir in 'postgres', 'backups', 'phoenix', 'langflow', 'applications', 'profile', 'evals') {
        New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot $dir) | Out-Null
    }
    # The example CV is a template with placeholder experience, so the rubric scores the fixture
    # jobs low. A synthetic candidate (not a real person) matches them instead. Written only into
    # the e2e data root.
    @'
# Test Candidate

test.candidate@example.com | Aarhus, Denmark

Synthetic CV for the end-to-end test only. Not a real person.

## Overview

- **Education level:** Master's degree in computer science
- **Languages:** English (Native), Danish (Beginner)

## Skills

Python | SQL | PostgreSQL | Apache Airflow | dbt | Docker | Git | Data modelling | Data quality testing

## Experience

### Northwind Data - Data Engineer
*Jan 2022 - present*

- Built and ran batch pipelines in Python and SQL, orchestrated with Apache Airflow, loading a PostgreSQL warehouse.
- Modelled dimensional tables for analysts and wrote tests for every transformation.
- Added alerting to the pipelines, cutting failed-run response time from days to hours.

### Contoso Logistics - Junior Data Analyst
*Jul 2019 - Dec 2021*

- Wrote SQL reports and dashboards for operations teams.
- Automated recurring data imports with Python scripts under Git and code review.

## Education

### Aarhus University - MSc Computer Science
*2017 - 2019*

- Thesis on data quality monitoring in streaming systems.
'@ | ForEach-Object { [IO.File]::WriteAllText((Join-Path $DataRoot 'profile\cv.md'), ($_ -replace "`r`n", "`n"), (New-Object Text.UTF8Encoding($false))) }
    Copy-Item -Force (Join-Path $RepoRoot 'docs\profile-examples\cover_letter_template.example.md') (Join-Path $DataRoot 'profile\cover_letter_template.md')
    Copy-Item -Force (Join-Path $RepoRoot 'docs\profile-examples\recruiter_email_template.example.md') (Join-Path $DataRoot 'profile\recruiter_email_template.md')
    Write-Host "Seeded $DataRoot\profile from docs/profile-examples."

    # 4-5. Stack up. No job is added before the LangFlow key exists.
    & $Dev up
    if ($LASTEXITCODE -ne 0) { throw 'dev.ps1 up failed' }

    # 6. LangFlow API key for the backend (the reset-free equivalent of plan 08's manual step).
    $auth = Get-LangflowAuth
    $keyName = 'e2e-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
    $created = Invoke-RestMethod -Method Post -Headers $auth -ContentType 'application/json' `
        -Uri "$(Get-LangflowUrl)/api/v1/api_key/" -Body (@{ name = $keyName } | ConvertTo-Json)
    if (-not $created.api_key) { throw 'LangFlow did not return an API key' }
    Check 'LangFlow API key created' $true

    # 7. Flows and global variables.
    & (Join-Path $PSScriptRoot 'import-flows.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'import-flows.ps1 failed' }
    Check 'flows imported' $true

    # 8. Restart the backend with the key.
    $env:LANGFLOW_API_KEY = $created.api_key
    & $Dev up
    if ($LASTEXITCODE -ne 0) { throw 'dev.ps1 up (with key) failed' }

    # 9. Add the 4 jobs as the form does. Each 201 starts an analysis run in the background; a
    # run that finds the lock taken is skipped, and the running one picks the posting up.
    $jobs = Get-Content -Raw -Encoding UTF8 $JobsFile | ConvertFrom-Json
    $answers = @(foreach ($job in $jobs) {
            $job | Add-Member -NotePropertyName force -NotePropertyValue $false -PassThru | Out-Null
            Add-Job $job
        })
    $createdCount = @($answers | Where-Object Status -eq 201).Count
    $refused = @($answers | Where-Object Status -eq 409)
    Check '3 jobs added (201)' ($createdCount -eq 3) "got $(($answers | ForEach-Object Status) -join ', ')"
    $sameUrl = ($refused.Count -eq 1) -and ($refused[0].Body.reason -eq 'same_url')
    Check '1 duplicate refused (409)' $sameUrl "409s: $($refused.Count), reason: $($refused | ForEach-Object { $_.Body.reason })"

    # 10. Wait for the analysis of the 3 stored postings to settle.
    $settled = Wait-Until 'analysis of 3 postings' {
        $items = Get-Postings
        Write-Host ("  {0} postings: {1}" -f $items.Count, (($items | Group-Object status | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ', '))
        $items.Count -ge 3 -and -not ($items | Where-Object { $_.status -in 'new', 'analyzed' })
    } $TimeoutMin
    $items = Get-Postings
    Check '3 postings stored' ($items.Count -eq 3) "found $($items.Count)"
    Check 'analysis settled' $settled

    $lows = @($items | Where-Object status -eq 'low_match').Count
    $awaiting = @($items | Where-Object status -eq 'awaiting_match_review')
    Check '1 low_match' ($lows -eq 1) "found $lows"
    Check '2 awaiting gate 1' ($awaiting.Count -eq 2) "found $($awaiting.Count)"

    $nordlys = $awaiting | Where-Object company -eq 'Nordlys Analytics' | Select-Object -First 1
    $fjordbyg = $awaiting | Where-Object company -eq 'Fjordbyg Data ApS' | Select-Object -First 1
    if (-not $nordlys -or -not $fjordbyg) { throw 'expected Nordlys Analytics and Fjordbyg Data ApS to await review' }

    # 11. Gate 1: approve one match, decline the other.
    $body = { param($d) @{ decision = $d } | ConvertTo-Json }
    Invoke-RestMethod -Headers $headers -Method Post -ContentType 'application/json' `
        -Uri "$Api/postings/$($nordlys.posting_id)/match-decision" -Body (& $body 'approve') | Out-Null
    Invoke-RestMethod -Headers $headers -Method Post -ContentType 'application/json' `
        -Uri "$Api/postings/$($fjordbyg.posting_id)/match-decision" -Body (& $body 'decline') | Out-Null

    # 12. Generation runs in the background, started by the approval.
    $generated = Wait-Until 'generation of the approved posting' {
        $p = Invoke-RestMethod -Headers $headers -Uri "$Api/postings/$($nordlys.posting_id)"
        Write-Host "  approved posting status: $($p.status)"
        $p.status -in 'generated', 'error'
    } $TimeoutMin
    $final = Invoke-RestMethod -Headers $headers -Uri "$Api/postings/$($nordlys.posting_id)"
    Check 'approved posting generated' ($final.status -eq 'generated') "status $($final.status)"
    Check 'generation finished in time' $generated

    $declined = @(Get-Postings | Where-Object status -eq 'match_declined').Count
    Check '1 match_declined' ($declined -eq 1) "found $declined"

    # 13. Artifacts: text for all three kinds, and the two PDFs on disk.
    foreach ($kind in 'cv', 'cover_letter', 'recruiter_email') {
        $ok = $false
        try {
            $art = Invoke-RestMethod -Headers $headers -Uri "$Api/postings/$($nordlys.posting_id)/artifacts/$kind"
            $ok = [bool]$art.markdown
        } catch { $ok = $false }
        Check "artifact $kind" $ok
    }
    $pdfs = @(Get-ChildItem -Path (Join-Path $DataRoot 'applications') -Recurse -Filter '*.pdf' -ErrorAction SilentlyContinue)
    $hasCv = [bool]($pdfs | Where-Object Name -like 'cv*.pdf')
    $hasLetter = [bool]($pdfs | Where-Object Name -like 'cover_letter*.pdf')
    Check 'CV and cover letter PDFs on disk' ($hasCv -and $hasLetter) "found $($pdfs.Count) PDF(s)"
}
catch {
    Write-Host "Failure at:`n$($_.ScriptStackTrace)" -ForegroundColor Yellow
    Check 'run completed' $false $_.Exception.Message
}
finally {
    Remove-Item Env:DATA_ROOT, Env:LANGFLOW_API_KEY -ErrorAction SilentlyContinue
    if (-not $NoRestore) {
        Write-Host 'Restoring the stack on your own DATA_ROOT...'
        & $Dev up
    }
}

$results | Format-Table -AutoSize | Out-Host
$failed = @($results | Where-Object Result -eq 'FAIL').Count
if ($failed -gt 0) {
    Write-Host "$failed check(s) failed." -ForegroundColor Red
    exit 1
}
Write-Host 'e2e passed.' -ForegroundColor Green
