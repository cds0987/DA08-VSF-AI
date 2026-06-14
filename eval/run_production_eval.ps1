param(
    [string]$EnvFile = "eval\.env.production",
    [string]$Dataset = "dataset_new",
    [int]$Limit = 30,
    [int]$Concurrency = 50,
    [int]$PerfSamples = -1,
    [int]$PerfDurationSeconds = 0,
    [switch]$Smoke,
    [switch]$Stress,
    [switch]$SkipInstall,
    [switch]$NoCopyBack
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Fail {
    param([string]$Message)
    Write-Host ""
    Write-Host "FAILED: $Message" -ForegroundColor Red
    exit 1
}

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        Fail "Missing env file: $Path. Copy eval\.env.production.example to eval\.env.production and fill it first."
    }
    Get-Content -Path $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($key -match "^[A-Za-z_][A-Za-z0-9_]*$") {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

function Require-Env {
    param([string[]]$Names)
    $missing = @()
    foreach ($name in $Names) {
        if (-not [Environment]::GetEnvironmentVariable($name, "Process")) {
            $missing += $name
        }
    }
    if ($missing.Count -gt 0) {
        Fail "Missing required values in $EnvFile`: $($missing -join ', ')"
    }
}

function Gcloud-BaseArgs {
    $args = @("--project", $env:GCP_PROJECT_ID)
    return $args
}

function Gcloud-SshArgs {
    param([string]$Command)
    $args = @("compute", "ssh", $env:GCP_VM_NAME, "--zone", $env:GCP_ZONE) + (Gcloud-BaseArgs)
    if (($env:GCP_TUNNEL_THROUGH_IAP -as [string]).ToLower() -ne "false") {
        $args += "--tunnel-through-iap"
    }
    $args += @("--command", $Command)
    return $args
}

function Gcloud-ScpArgs {
    param([string[]]$Paths, [string]$Destination, [switch]$Recurse)
    $args = @("compute", "scp")
    if ($Recurse) {
        $args += "--recurse"
    }
    $args += $Paths
    $args += $Destination
    $args += @("--zone", $env:GCP_ZONE) + (Gcloud-BaseArgs)
    if (($env:GCP_TUNNEL_THROUGH_IAP -as [string]).ToLower() -ne "false") {
        $args += "--tunnel-through-iap"
    }
    return $args
}

function Run-Gcloud {
    param([string[]]$Arguments, [string]$Label)
    Write-Host "+ gcloud $($Arguments -join ' ')" -ForegroundColor DarkGray
    & gcloud @Arguments
    if ($LASTEXITCODE -ne 0) {
        Fail "$Label failed with exit code $LASTEXITCODE"
    }
}

function Write-RemoteEnvFile {
    $keys = @(
        "USER_URL",
        "QUERY_URL",
        "DOC_URL",
        "MCP_URL",
        "SEED_ADMIN_EMAIL",
        "SEED_ADMIN_PASSWORD",
        "OPENAI_API_KEY",
        "OPENAI_EMBEDDING_MODEL",
        "JWT_SECRET_KEY",
        "JWT_ALGORITHM",
        "MCP_INTERNAL_TOKEN",
        "EVAL_PRODUCTION_READONLY",
        "EVAL_REQUIRE_INDEXED_DOCS",
        "EVAL_TOTAL_EMPLOYEES"
    )
    $lines = @()
    foreach ($key in $keys) {
        $value = [Environment]::GetEnvironmentVariable($key, "Process")
        if ($null -ne $value -and $value -ne "") {
            $escaped = $value.Replace("`r", "").Replace("`n", "")
            $lines += "$key=$escaped"
        }
    }
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) "vsf-eval-production.env"
    Set-Content -Path $tmp -Value ($lines -join "`n") -Encoding UTF8
    Run-Gcloud -Arguments (Gcloud-ScpArgs -Paths @($tmp) -Destination "$($env:GCP_VM_NAME):$($env:REMOTE_EVAL_DIR)/.env") -Label "Copy production eval env"
    Remove-Item -LiteralPath $tmp -Force
}

function Invoke-RemoteEval {
    $args = @(
        "./venv/bin/python", "run_eval.py",
        "--target", "production-vm",
        "--dataset-root", "dataset",
        "--output-root", "output",
        "--dataset", $Dataset,
        "--production-readonly",
        "--concurrency", "$Concurrency"
    )
    if ($Smoke) {
        $args += @("--limit", "1", "--perf-samples", "1", "--perf-duration-seconds", "0")
    } elseif ($Stress) {
        $stressSamples = $PerfSamples
        if ($stressSamples -lt 0) {
            $stressSamples = 100
        }
        $args += @("--limit", "$Limit", "--perf-samples", "$stressSamples", "--perf-duration-seconds", "0", "--no-ragas")
    } else {
        $args += @("--limit", "$Limit", "--perf-duration-seconds", "$PerfDurationSeconds")
        if ($PerfSamples -ge 0) {
            $args += @("--perf-samples", "$PerfSamples")
        }
    }
    $command = "cd $($env:REMOTE_EVAL_DIR) && " + ($args -join " ")
    Run-Gcloud -Arguments (Gcloud-SshArgs -Command $command) -Label "Production eval"
}

if (-not (Test-Path "eval\run_eval.py")) {
    Fail "Run this script from repo root."
}

Write-Step "Loading production eval env"
Import-DotEnv $EnvFile
Require-Env @(
    "GCP_PROJECT_ID",
    "GCP_VM_NAME",
    "GCP_ZONE",
    "REMOTE_EVAL_DIR",
    "PROD_APP_DIR",
    "USER_URL",
    "QUERY_URL",
    "DOC_URL",
    "MCP_URL",
    "SEED_ADMIN_EMAIL",
    "SEED_ADMIN_PASSWORD",
    "OPENAI_API_KEY"
)

if (-not $env:EVAL_PRODUCTION_READONLY) { $env:EVAL_PRODUCTION_READONLY = "true" }
if (-not $env:EVAL_REQUIRE_INDEXED_DOCS) { $env:EVAL_REQUIRE_INDEXED_DOCS = "true" }
if (-not $env:OPENAI_EMBEDDING_MODEL) { $env:OPENAI_EMBEDDING_MODEL = "text-embedding-3-small" }

Write-Step "Checking gcloud"
& gcloud --version *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "gcloud is not available. Install Google Cloud SDK, open a new PowerShell, then run gcloud auth login."
}
Run-Gcloud -Arguments @("config", "set", "project", $env:GCP_PROJECT_ID) -Label "Set gcloud project"

Write-Step "Checking VM stack health"
$healthCommand = "cd $($env:PROD_APP_DIR) && sudo docker compose ps && curl -f $($env:USER_URL)/health && curl -f $($env:QUERY_URL)/health && curl -f $($env:DOC_URL)/health && (curl -f $($env:MCP_URL)/health || true)"
Run-Gcloud -Arguments (Gcloud-SshArgs -Command $healthCommand) -Label "VM health check"

Write-Step "Preparing remote eval directory"
Run-Gcloud -Arguments (Gcloud-SshArgs -Command "rm -rf $($env:REMOTE_EVAL_DIR) && mkdir -p $($env:REMOTE_EVAL_DIR)") -Label "Prepare remote eval dir"

Write-Step "Copying eval runner, libs, and dataset to VM"
Run-Gcloud -Arguments (Gcloud-ScpArgs -Paths @("eval\run_eval.py", "eval\requirements.txt", "eval\README.md", "eval\vm_test.md") -Destination "$($env:GCP_VM_NAME):$($env:REMOTE_EVAL_DIR)/") -Label "Copy eval files"
Run-Gcloud -Arguments (Gcloud-ScpArgs -Paths @("eval\lib", "eval\dataset") -Destination "$($env:GCP_VM_NAME):$($env:REMOTE_EVAL_DIR)/" -Recurse) -Label "Copy eval directories"
Write-RemoteEnvFile

if (-not $SkipInstall) {
    Write-Step "Installing eval dependencies on VM"
    $installCommand = "cd $($env:REMOTE_EVAL_DIR) && python3 -m venv venv && ./venv/bin/python -m pip install --upgrade pip && ./venv/bin/python -m pip install -r requirements.txt"
    Run-Gcloud -Arguments (Gcloud-SshArgs -Command $installCommand) -Label "Install eval dependencies"
}

Write-Step "Running production preflight"
$preflight = "cd $($env:REMOTE_EVAL_DIR) && ./venv/bin/python run_eval.py --target production-vm --dataset-root dataset --output-root output --dataset $Dataset --limit 1 --production-readonly --preflight-only"
Run-Gcloud -Arguments (Gcloud-SshArgs -Command $preflight) -Label "Production preflight"

Write-Step "Running production eval"
Invoke-RemoteEval

if (-not $NoCopyBack) {
    Write-Step "Copying output back to local eval/output"
    New-Item -ItemType Directory -Force -Path "eval\output" | Out-Null
    Run-Gcloud -Arguments (Gcloud-ScpArgs -Paths @("$($env:GCP_VM_NAME):$($env:REMOTE_EVAL_DIR)/output") -Destination "eval" -Recurse) -Label "Copy eval output"
    Get-ChildItem "eval\output" -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 5 Name,LastWriteTime | Format-Table
}

Write-Host ""
Write-Host "SUCCESS: production read-only eval finished." -ForegroundColor Green
