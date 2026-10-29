[CmdletBinding()]
param(
    [string]$DataDir = 'Z:\PHI',
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$RosterPath,
    [string]$PythonPath
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) { $PythonPath = Join-Path $RepoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Existing SERDA .venv Python not found; use -PythonPath.' }
$Source = (Resolve-Path -LiteralPath $DataDir).Path
$Destination = (Resolve-Path -LiteralPath $OutputRoot).Path
$RunName = 'mrn_coverage_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + ([guid]::NewGuid().ToString('N').Substring(0,8))
$Output = Join-Path $Destination $RunName
$Config = Join-Path $RepoRoot 'configs\serda_ga_erika.yaml'
$Arguments = @('-m','serda_pipeline.patient_coverage','--data-dir',$Source,'--output-dir',$Output,'--config',$Config)
if ($RosterPath) { $Arguments += @('--roster',(Resolve-Path -LiteralPath $RosterPath).Path) }
Push-Location $RepoRoot
try {
    & $PythonPath @Arguments
    $AuditExit = $LASTEXITCODE
    Write-Host ('Report location: ' + $Output)
    Write-Host 'Only aggregate/ is a candidate for sharing. restricted_SERDA_ONLY/ must remain in restricted SERDA storage.'
    if ($AuditExit -ne 0) { throw 'Coverage is incomplete or failed; inspect execution_report.json if created. Do not interpret unavailable counts as zero.' }
} finally { Pop-Location }
