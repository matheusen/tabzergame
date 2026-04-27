param(
  [Parameter(Mandatory = $false)]
  [Alias("t")]
  [string]$TaskId,

  [Parameter(Mandatory = $false)]
  [string]$Url = "",

  [Parameter(Mandatory = $false)]
  [int]$TaskIterations = 1,

  [Parameter(Mandatory = $false)]
  [ValidateSet(0, 1)]
  [int]$Headless = 1,

  [Parameter(Mandatory = $false)]
  [ValidateSet(0, 1)]
  [int]$TabShots = 1,

  [Parameter(Mandatory = $false)]
  [int]$TabShotsMax = 8,

  [Parameter(Mandatory = $false)]
  [int]$WaitMs = 6000,

  [Parameter(Mandatory = $false)]
  [switch]$EmitCodexStdout,

  [Parameter(Mandatory = $false)]
  [switch]$CodexStdoutOnly,

  [Parameter(Mandatory = $false)]
  [switch]$KeepOpen,

  [Parameter(Mandatory = $false)]
  [string]$TaskDir = "",

  [Parameter(Mandatory = $false)]
  [string]$OutputDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..\..")).Path
$agentPath = Join-Path $scriptDir "run_agent.py"
$defaultTaskDir = Join-Path $scriptDir "tasks"

if (-not $TaskId) {
  Write-Host "TaskId is required." -ForegroundColor Yellow
  Write-Host "Available task ids:" -ForegroundColor Cyan
  Get-ChildItem -Path $defaultTaskDir -Filter "*.md" |
    Where-Object { $_.Name -ne "README.md" } |
    Sort-Object Name |
    ForEach-Object { Write-Host ("  - " + $_.BaseName) }
  Write-Host ""
  Write-Host "Example:" -ForegroundColor Cyan
  Write-Host "  .\backend\agents\tab_debug_agent\run_task.ps1 -TaskId cursor-click-accuracy"
  exit 1
}

if (-not (Test-Path $agentPath)) {
  throw "run_agent.py not found at: $agentPath"
}

$argsList = @(
  $agentPath,
  "--task", $TaskId,
  "--no-openai",
  "--task-iterations", "$TaskIterations",
  "--headless", "$Headless",
  "--tab-shots", "$TabShots",
  "--tab-shots-max", "$TabShotsMax",
  "--wait-ms", "$WaitMs"
)

if ($Url) {
  $argsList += @("--url", $Url)
}
if ($KeepOpen.IsPresent) {
  $argsList += "--keep-open"
}
if ($EmitCodexStdout.IsPresent) {
  $argsList += "--emit-codex-stdout"
}
if ($CodexStdoutOnly.IsPresent) {
  $argsList += "--codex-stdout-only"
}
if ($TaskDir) {
  $argsList += @("--task-dir", $TaskDir)
}
if ($OutputDir) {
  $argsList += @("--output-dir", $OutputDir)
}

Push-Location $repoRoot
try {
  Write-Host ("[tab-debug-task] running task='" + $TaskId + "' no-openai=1 headless=" + $Headless)
  if ($Url) {
    Write-Host ("[tab-debug-task] url override: " + $Url)
  }
  & python @argsList
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    throw "Agent exited with code $exitCode"
  }
}
finally {
  Pop-Location
}
