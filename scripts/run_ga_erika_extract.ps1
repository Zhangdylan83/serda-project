[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [string]$OutputRoot,
    [string]$PythonPath
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Package = (Resolve-Path -LiteralPath $PackagePath).Path
if (-not (Test-Path -LiteralPath (Join-Path $Package 'run_manifest.json'))) { throw 'Frozen run_manifest.json not found.' }
if (-not (Test-Path -LiteralPath (Join-Path $Package 'sample_manifest.csv'))) { throw 'Frozen sample_manifest.csv not found.' }
if (-not $PythonPath) { $PythonPath = Join-Path $RepoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'SERDA .venv Python not found. Use -PythonPath for the existing approved environment.' }
if (-not $OutputRoot) { $OutputRoot = Split-Path -Parent $Package }
# Default is a new sibling of the existing approved SERDA package; no PHI is copied to Git.
$OutputRoot = (Resolve-Path -LiteralPath $OutputRoot).Path
$RunName = 'ga_schema_v1_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + ([guid]::NewGuid().ToString('N').Substring(0,8))
$Output = Join-Path $OutputRoot $RunName
$Config = Join-Path $RepoRoot 'configs\serda_ga_erika.yaml'
Push-Location $RepoRoot
try {
    & $PythonPath -c 'import yaml, jsonschema; from jsonschema import Draft202012Validator'
    if ($LASTEXITCODE -ne 0) { throw 'Missing dependencies. Install updated requirements.txt using approved SERDA setup before running.' }
    & $PythonPath -m serda_pipeline.ga_frozen_extract --package $Package --output-dir $Output --config $Config
    if ($LASTEXITCODE -ne 0) { throw 'Extraction failed. No clinical evaluation is implied; see the safe error above.' }
    Write-Host ('Review: ' + (Join-Path $Output 'review.html'))
    Write-Host 'Original package and baseline unchanged. All results must remain in SERDA.'
} finally { Pop-Location }
