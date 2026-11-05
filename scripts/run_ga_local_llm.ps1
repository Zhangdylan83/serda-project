[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$PythonPath,
    [string]$PackagePath,
    [switch]$AuthorizePatientInference,
    [string]$SyntheticPassRun
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) { $PythonPath = Join-Path $RepoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Existing approved Python environment not found; use -PythonPath.' }
$Destination = [IO.Path]::GetFullPath($OutputRoot)
if (-not (Test-Path -LiteralPath $Destination -PathType Container)) { throw 'OutputRoot must be an existing approved directory.' }
if ([IO.Path]::GetPathRoot($Destination).TrimEnd('\') -ine 'Z:') { throw 'OutputRoot must be an existing approved project directory on Z:, not Desktop or UNC.' }
if ($PackagePath -and (-not $AuthorizePatientInference -or -not $SyntheticPassRun)) {
    throw 'Patient inference is a separately authorized step. First run synthetic mode successfully, then supply explicit authorization and its run directory.'
}
if (-not $PackagePath -and ($AuthorizePatientInference -or $SyntheticPassRun)) { throw 'Authorization arguments require an explicit frozen package.' }
$Mode = if ($PackagePath) { 'package' } else { 'synthetic' }
$RunName = 'ga_local_llm_' + $Mode + '_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + ([guid]::NewGuid().ToString('N').Substring(0,8))
$Output = Join-Path $Destination $RunName
$Arguments = @('-m','serda_pipeline.ga_local_llm','--config',(Join-Path $RepoRoot 'configs\serda_ga_llm.yaml'),'--output-dir',$Output)
if ($PackagePath) {
    $Arguments += @('--package',(Resolve-Path -LiteralPath $PackagePath).Path,'--authorize-patient-inference','--synthetic-pass-run',(Resolve-Path -LiteralPath $SyntheticPassRun).Path)
}
Push-Location $RepoRoot
try {
    & $PythonPath -c 'import yaml, jsonschema; import serda_pipeline.ga_local_llm'
    if ($LASTEXITCODE -ne 0) { throw 'Python dependencies missing; use the approved offline requirements installation process.' }
    & $PythonPath @Arguments
    $ExperimentExit = $LASTEXITCODE
    Write-Host ('Local result directory: ' + $Output)
    if ($ExperimentExit -ne 0) { throw 'Synthetic checks or inference failed; inspect local reports. Do not proceed to patient inference.' }
    Write-Host ('Review: ' + (Join-Path $Output 'review.html'))
    Write-Host 'Source package and Regex baseline were not modified. Server process has been stopped.'
} finally { Pop-Location }
