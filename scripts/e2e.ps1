<#
.SYNOPSIS
  End-to-end check (plan 14): feed -> analysis -> gate 1 -> generation, on a throwaway DATA_ROOT.

.DESCRIPTION
  Runs the whole Docker stack against a separate DATA_ROOT (default C:\dev\JobSearchData-e2e):
  fresh Postgres, LangFlow, Phoenix and blob folders, with the profile seeded from
  docs/profile-examples/*.example.md. Your real DATA_ROOT (infra/.env) is not read or written
  by the stack during the run, so no reset is needed.

  The feed is scripts/e2e/www/feed.xml (synthetic, 4 postings), served on 127.0.0.1:8765.
  Expected outcome:
    1 duplicate  (second copy of the Nordlys posting)
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
    [int]$FixturePort = 8765,
    [int]$TimeoutMin = 45,
    [switch]$NoRestore
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib-langflow.ps1')

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Dev = Join-Path $PSScriptRoot 'dev.ps1'
$WwwRoot = Join-Path $PSScriptRoot 'e2e\www'
$Api = 'http://127.0.0.1:8000/api/v1'
$FeedUrl = "http://host.docker.internal:$FixturePort/feed.xml"

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

function Wait-Until([string]$What, [scriptblock]$Done, [int]$Minutes) {
    $deadline = (Get-Date).AddMinutes($Minutes)
    while ((Get-Date) -lt $deadline) {
        if (& $Done) { return $true }
        Start-Sleep -Seconds 15
    }
    Write-Host "Timed out after $Minutes min waiting for: $What" -ForegroundColor Yellow
    return $false
}

$fixture = $null
$env:DATA_ROOT = $DataRoot
# PowerShell deletes an env var set to '' instead of emptying it, and compose would then fall back
# to the real values in infra/.env. So the first start gets a feed and key that cannot work.
$env:JOBINDEX_FEEDS = "http://host.docker.internal:9/no-feed.xml"
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

    # 4. Feed fixture on the host; the worker reaches it through host.docker.internal.
    $py = Find-Python
    $pyArgs = if ($py -eq 'py') { @('-3') } else { @() }
    $fixture = Start-Process -PassThru -WindowStyle Hidden -FilePath $py -ArgumentList ($pyArgs + @(
            '-m', 'http.server', "$FixturePort", '--bind', '127.0.0.1', '--directory', $WwwRoot))
    Start-Sleep -Seconds 2

    # 5. Stack up with no feed yet, so nothing is polled before the LangFlow key exists.
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

    # 8. Restart backend and worker with the key and the fixture feed.
    $env:LANGFLOW_API_KEY = $created.api_key
    $env:JOBINDEX_FEEDS = $FeedUrl
    & $Dev up
    if ($LASTEXITCODE -ne 0) { throw 'dev.ps1 up (with key and feed) failed' }
    # The worker runs in a container: the fixture must be reachable from there, or nothing is ingested.
    $probe = cmd /c "docker exec ajs-worker-1 python -c ""import urllib.request,sys; sys.stdout.write(str(urllib.request.urlopen('$FeedUrl', timeout=10).status))"" 2>&1"
    if ("$probe" -ne '200') { throw "worker cannot reach the fixture feed at $FeedUrl (got: $probe)" }
    Check 'worker reaches fixture feed' $true
    Invoke-RestMethod -Headers $headers -Method Post -Uri "$Api/workflow/poll" | Out-Null

    # 9. Wait for the analysis of the 3 stored postings to settle. The 4th feed item is a
    # duplicate: it is never stored, so it only shows in the run logs.
    $settled = Wait-Until 'analysis of 3 postings' {
        $items = Get-Postings
        Write-Host ("  {0} postings: {1}" -f $items.Count, (($items | Group-Object status | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ', '))
        $items.Count -ge 3 -and -not ($items | Where-Object { $_.status -in 'new', 'analyzed', 'needs_manual_text' })
    } $TimeoutMin
    $items = Get-Postings
    Check 'feed stored 3 postings' ($items.Count -eq 3) "found $($items.Count)"
    Check 'analysis settled' $settled

    # A duplicate is stopped before a row is stored, and the backend does not log it at INFO, so
    # check it from the data: the feed has 4 items, the copy (e2e000002) must not be stored.
    $stored = @($items | ForEach-Object source_url)
    $dups = 4 - $stored.Count
    $copyStored = [bool]($stored | Where-Object { $_ -like '*e2e000002' })
    $lows = @($items | Where-Object status -eq 'low_match').Count
    $awaiting = @($items | Where-Object status -eq 'awaiting_match_review')
    Check '1 duplicate stopped' (($dups -eq 1) -and -not $copyStored) "feed items not stored: $dups, copy stored: $copyStored"
    Check '1 low_match' ($lows -eq 1) "found $lows"
    Check '2 awaiting gate 1' ($awaiting.Count -eq 2) "found $($awaiting.Count)"

    $nordlys = $awaiting | Where-Object company -eq 'Nordlys Analytics' | Select-Object -First 1
    $fjordbyg = $awaiting | Where-Object company -eq 'Fjordbyg Data ApS' | Select-Object -First 1
    if (-not $nordlys -or -not $fjordbyg) { throw 'expected Nordlys Analytics and Fjordbyg Data ApS to await review' }

    # 10. Gate 1: approve one match, decline the other.
    $body = { param($d) @{ decision = $d } | ConvertTo-Json }
    Invoke-RestMethod -Headers $headers -Method Post -ContentType 'application/json' `
        -Uri "$Api/postings/$($nordlys.posting_id)/match-decision" -Body (& $body 'approve') | Out-Null
    Invoke-RestMethod -Headers $headers -Method Post -ContentType 'application/json' `
        -Uri "$Api/postings/$($fjordbyg.posting_id)/match-decision" -Body (& $body 'decline') | Out-Null

    # 11. Generation runs in the background (and on the worker tick) until generated.
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

    # 12. Artifacts: text for all three kinds, and the two PDFs on disk.
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
    if ($fixture -and -not $fixture.HasExited) { Stop-Process -Id $fixture.Id -Force }
    Remove-Item Env:DATA_ROOT, Env:JOBINDEX_FEEDS, Env:LANGFLOW_API_KEY -ErrorAction SilentlyContinue
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
