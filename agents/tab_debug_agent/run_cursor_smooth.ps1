param(
  [Parameter(Mandatory = $false)]
  [string]$Url = "http://localhost:3000/play?id=joe-satriani-if-could-fly-v2&debugCursor=1",

  [Parameter(Mandatory = $false)]
  [string]$Task = "cursor-glide-quality",

  [Parameter(Mandatory = $false)]
  [ValidateSet(0, 1)]
  [int]$Headless = 1,

  [Parameter(Mandatory = $false)]
  [int]$Iterations = 4,

  [Parameter(Mandatory = $false)]
  [double]$MinImprovement = 5.0,

  [Parameter(Mandatory = $false)]
  [int]$HmrDelaySec = 5,

  [Parameter(Mandatory = $false)]
  [int]$RunTimeoutSec = 180,

  [Parameter(Mandatory = $false)]
  [switch]$JsonOnly,

  [Parameter(Mandatory = $false)]
  [string]$OutputDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..\..")).Path
$agentPath = Join-Path $scriptDir "cursor_smooth_agent.py"

if (-not (Test-Path $agentPath)) {
  throw "cursor_smooth_agent.py not found at: $agentPath"
}

$argsList = @(
  $agentPath,
  "--url", $Url,
  "--task", $Task,
  "--headless", "$Headless",
  "--iterations", "$Iterations",
  "--min-improvement", "$MinImprovement",
  "--hmr-delay-sec", "$HmrDelaySec",
  "--run-timeout-sec", "$RunTimeoutSec"
)

if ($JsonOnly.IsPresent) {
  $argsList += "--json-only"
}
if ($OutputDir) {
  $argsList += @("--output-dir", $OutputDir)
}

Push-Location $repoRoot
try {
  Write-Host ("[cursor-smooth] Starting autonomous cursor smoothness agent") -ForegroundColor Cyan
  Write-Host ("[cursor-smooth] url=$Url  task=$Task  headless=$Headless  iterations=$Iterations") -ForegroundColor Gray
  Write-Host ("[cursor-smooth] HMR delay=${HmrDelaySec}s  min-improvement=${MinImprovement}pts") -ForegroundColor Gray
  Write-Host ""

  & python @argsList
  $exitCode = $LASTEXITCODE

  if ($exitCode -eq 0) {
    Write-Host "" 
    Write-Host "[cursor-smooth] PASS — cursor is smooth." -ForegroundColor Green
  } else {
    Write-Host ""
    Write-Host "[cursor-smooth] FAIL — smoothness issues remain. Check the report above." -ForegroundColor Yellow
  }
  exit $exitCode
}
finally {
  Pop-Location
}
