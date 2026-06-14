param(
    [switch]$Full,
    [string]$Dataset = "dataset_new",
    [int]$Limit = 30,
    [int]$Concurrency = 50,
    [int]$PerfDurationSeconds = 300,
    [int]$PerfSamples = -1,
    [switch]$WarmCache,
    [switch]$Smoke,
    [switch]$NoCleanup,
    [switch]$KeepStack,
    [switch]$SkipBuild,
    [switch]$SkipCompose,
    [switch]$SkipUnitTests,
    [switch]$UseCloudStorage,
    [switch]$UseCloudQdrant,
    [int]$QuestionOffset = -1
)

$ErrorActionPreference = "Stop"
$DatasetWasProvided = $PSBoundParameters.ContainsKey("Dataset")
$LimitWasProvided = $PSBoundParameters.ContainsKey("Limit")

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

function Run-Command {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Label
    )
    Write-Host "+ $FilePath $($Arguments -join ' ')" -ForegroundColor DarkGray
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        Fail "$Label failed with exit code $LASTEXITCODE"
    }
}

function Run-PythonInline {
    param(
        [string]$Python,
        [string]$Script,
        [string]$Label
    )
    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($Script))
    $launcher = "import base64; exec(base64.b64decode('$encoded').decode('utf-8'))"
    Write-Host "+ $Python -c <inline $Label>" -ForegroundColor DarkGray
    & $Python -c $launcher
    if ($LASTEXITCODE -ne 0) {
        Fail "$Label failed with exit code $LASTEXITCODE"
    }
}

function Get-ComposeArgs {
    $args = @("compose", "-f", "docker-compose.e2e.yml")
    if (-not $UseCloudStorage -or -not $UseCloudQdrant) {
        $args += @("-f", "eval\docker-compose.local-eval.yml")
    }
    return $args
}

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return
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

function Assert-RepoRoot {
    if (-not (Test-Path "docker-compose.e2e.yml") -or -not (Test-Path "eval\run_eval.py")) {
        Fail "Run this script from repo root, for example: cd D:\DA08-VSF; .\eval\run_local_eval.ps1"
    }
    $evalRoot = (Resolve-Path "eval").Path
    if ($env:PYTHONPATH) {
        $env:PYTHONPATH = "$evalRoot;$($env:PYTHONPATH)"
    } else {
        $env:PYTHONPATH = $evalRoot
    }
}

function Ensure-Python {
    $venvPython = "eval\venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        & $venvPython --version | Out-Host
        if ($LASTEXITCODE -eq 0) {
            return $venvPython
        }
        Write-Host "Existing eval venv is not runnable; recreating it." -ForegroundColor Yellow
    }

    $candidates = @(
        "C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe",
        "python",
        "py"
    )
    $basePython = $null
    foreach ($candidate in $candidates) {
        try {
            if ($candidate -eq "py") {
                & py -3.11 --version *> $null
                if ($LASTEXITCODE -eq 0) {
                    $basePython = "py -3.11"
                    break
                }
            } else {
                & $candidate --version *> $null
                if ($LASTEXITCODE -eq 0) {
                    $basePython = $candidate
                    break
                }
            }
        } catch {
            continue
        }
    }
    if (-not $basePython) {
        Fail "No runnable Python found. Install Python 3.11+ or fix the WindowsApps Python alias."
    }

    if ($basePython -eq "py -3.11") {
        Run-Command -FilePath "py" -Arguments @("-3.11", "-m", "venv", "eval\venv") -Label "Create eval venv"
    } else {
        Run-Command -FilePath $basePython -Arguments @("-m", "venv", "eval\venv") -Label "Create eval venv"
    }
    Run-Command -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip") -Label "Upgrade pip"
    Run-Command -FilePath $venvPython -Arguments @("-m", "pip", "install", "-r", "eval\requirements.txt") -Label "Install eval requirements"
    return $venvPython
}

function Ensure-TestDeps {
    param([string]$Python)
    & $Python -m pytest --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "pytest is missing in eval venv; installing pytest for parser tests." -ForegroundColor Yellow
        Run-Command -FilePath $Python -Arguments @("-m", "pip", "install", "pytest") -Label "Install pytest"
    }
}

function Ensure-PythonModule {
    param(
        [string]$Python,
        [string]$Module,
        [string]$Package
    )
    $moduleOk = $false
    try {
        & $Python -c "import $Module" *> $null
        $moduleOk = ($LASTEXITCODE -eq 0)
    } catch {
        $moduleOk = $false
    }
    if (-not $moduleOk) {
        Write-Host "$Package is missing in eval venv; installing it for local preflight." -ForegroundColor Yellow
        Run-Command -FilePath $Python -Arguments @("-m", "pip", "install", $Package) -Label "Install $Package"
    }
}

function Normalize-EnvForLocal {
    Import-DotEnv ".env"
    Import-DotEnv "eval\.env"

    if ($UseCloudQdrant -and -not $env:VECTOR_DB_BASIC_AUTH -and $env:QDRANT_USERNAME -and $env:QDRANT_PASSWORD) {
        $env:VECTOR_DB_BASIC_AUTH = "$($env:QDRANT_USERNAME):$($env:QDRANT_PASSWORD)"
        Write-Host "Mapped QDRANT_USERNAME/QDRANT_PASSWORD to VECTOR_DB_BASIC_AUTH for this process." -ForegroundColor Yellow
    }

    if ($UseCloudQdrant -and $env:QDRANT_URL -and $env:VECTOR_DB_BASIC_AUTH) {
        try {
            $uri = [Uri]$env:QDRANT_URL
            $hasExplicitPort = $env:QDRANT_URL -match ":\d+/?$"
            if ($uri.Scheme -eq "http" -and -not $hasExplicitPort) {
                $env:QDRANT_URL = "http://$($uri.Host):80"
                Write-Host "Normalized QDRANT_URL to include :80 for local basic-auth Qdrant access." -ForegroundColor Yellow
            }
        } catch {
            Write-Host "QDRANT_URL is not a parseable URI; leaving it unchanged." -ForegroundColor Yellow
        }
    }

    if (-not $UseCloudStorage) {
        if (-not $env:GCS_HMAC_KEY) { $env:GCS_HMAC_KEY = "evalminio" }
        if (-not $env:GCS_HMAC_SECRET) { $env:GCS_HMAC_SECRET = "evalminio123" }
        $env:GCS_BUCKET = "vsf-rag-chatbot-docs-dev"
        Write-Host "Using local MinIO object storage override for this run." -ForegroundColor Yellow
    }

    if (-not $UseCloudQdrant) {
        $env:QDRANT_URL = "http://localhost:6333"
        $env:QDRANT_API_KEY = ""
        $env:VECTOR_DB_BASIC_AUTH = ""
        Write-Host "Using local Qdrant override for this run." -ForegroundColor Yellow
    }

    $required = @("OPENAI_API_KEY")
    if ($UseCloudQdrant) {
        $required += "QDRANT_URL"
    }
    if ($UseCloudStorage) {
        $required += @("GCS_HMAC_KEY", "GCS_HMAC_SECRET")
    }
    $missing = @()
    foreach ($key in $required) {
        if (-not [Environment]::GetEnvironmentVariable($key, "Process")) {
            $missing += $key
        }
    }
    if ($missing.Count -gt 0) {
        Fail "Missing required env values in repo-root .env or eval\.env: $($missing -join ', ')"
    }
}

function Test-CloudPrereqs {
    param([string]$Python)

    if ($UseCloudStorage) {
        Ensure-PythonModule -Python $Python -Module "boto3" -Package "boto3"

        $gcsScript = @'
import os
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

bucket = os.environ.get("GCS_BUCKET") or "vsf-rag-chatbot-docs-dev"
access_key = os.environ.get("GCS_HMAC_KEY")
secret_key = os.environ.get("GCS_HMAC_SECRET")

try:
    kwargs = {
        "signature_version": "s3v4",
        "request_checksum_calculation": "when_required",
        "response_checksum_validation": "when_required",
    }
    config = Config(**kwargs)
except TypeError:
    config = Config(signature_version="s3v4")

client = boto3.client(
    "s3",
    endpoint_url="https://storage.googleapis.com",
    region_name="auto",
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    config=config,
)

try:
    client.head_bucket(Bucket=bucket)
except ClientError as exc:
    response = exc.response or {}
    error = response.get("Error") or {}
    code = error.get("Code") or response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    print(f"GCS HeadBucket failed for bucket '{bucket}' with code {code}. Check GCS_BUCKET/GCS_HMAC_KEY/GCS_HMAC_SECRET in .env.")
    sys.exit(1)
print(f"GCS bucket preflight OK: {bucket}")
'@
        Run-PythonInline -Python $Python -Script $gcsScript -Label "GCS bucket preflight"
    } else {
        Write-Host "Skipping GCS HeadBucket preflight because local MinIO override is enabled."
    }

    if ($UseCloudQdrant) {
        $qdrantUrl = $env:QDRANT_URL
        if (-not $qdrantUrl) {
            Fail "QDRANT_URL is required for cloud Qdrant eval."
        }
        $headers = @{}
        if ($env:QDRANT_API_KEY) {
            $headers["api-key"] = $env:QDRANT_API_KEY
        }
        if ($env:VECTOR_DB_BASIC_AUTH) {
            $bytes = [System.Text.Encoding]::UTF8.GetBytes($env:VECTOR_DB_BASIC_AUTH)
            $headers["Authorization"] = "Basic " + [Convert]::ToBase64String($bytes)
        }
        try {
            $response = Invoke-WebRequest -Uri "$qdrantUrl/collections" -Method Get -Headers $headers -UseBasicParsing -TimeoutSec 15
            if ($response.StatusCode -ge 500) {
                Fail "Qdrant preflight returned HTTP $($response.StatusCode). Check QDRANT_URL/auth."
            }
            Write-Host "Qdrant preflight OK ($($response.StatusCode))"
        } catch {
            Fail "Qdrant preflight failed. Check QDRANT_URL, QDRANT_API_KEY or VECTOR_DB_BASIC_AUTH. Details: $($_.Exception.Message)"
        }
    } else {
        Write-Host "Skipping cloud Qdrant preflight because local Qdrant override is enabled."
    }
}

function Ensure-Docker {
    try {
        & docker version *> $null
    } catch {
        Fail "Docker daemon is not reachable. Open Docker Desktop, wait until the engine is running, then rerun .\eval\run_local_eval.ps1"
    }
    if ($LASTEXITCODE -ne 0) {
        Fail "Docker daemon is not reachable. Open Docker Desktop, wait until the engine is running, then rerun .\eval\run_local_eval.ps1"
    }
    Run-Command -FilePath "docker" -Arguments @("compose", "version") -Label "Docker compose version"
}

function Start-Stack {
    if ($SkipCompose) {
        Write-Host "Skipping docker compose startup because -SkipCompose was provided." -ForegroundColor Yellow
        return
    }
    $compose = Get-ComposeArgs
    Run-Command -FilePath "docker" -Arguments ($compose + @("config", "--services")) -Label "Compose config"
    if ($SkipBuild) {
        Run-Command -FilePath "docker" -Arguments ($compose + @("up", "-d", "--remove-orphans")) -Label "Compose up"
    } else {
        Run-Command -FilePath "docker" -Arguments ($compose + @("up", "-d", "--build", "--remove-orphans")) -Label "Compose up --build"
    }
    Run-Command -FilePath "docker" -Arguments ($compose + @("ps")) -Label "Compose ps"
}

function Test-HttpHealth {
    param(
        [string]$Name,
        [string]$Url,
        [switch]$Optional
    )
    for ($i = 1; $i -le 30; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -lt 500) {
                Write-Host "$Name health OK ($($response.StatusCode))"
                return
            }
        } catch {
            Start-Sleep -Seconds 5
        }
    }
    if ($Optional) {
        Write-Host "$Name health did not respond; continuing because this endpoint is optional." -ForegroundColor Yellow
        return
    }
    Fail "$Name health failed at $Url. Check logs with: docker compose -f docker-compose.e2e.yml logs --tail 120 $Name"
}

function Invoke-Eval {
    param([string]$Python)

    $args = @(
        "eval\run_eval.py",
        "--target", "e2e-local",
        "--dataset-root", "eval\dataset",
        "--output-root", "eval\output",
        "--concurrency", "$Concurrency",
        "--perf-duration-seconds", "$PerfDurationSeconds"
    )

    if ($NoCleanup) {
        $args += "--no-cleanup"
    }
    if ($WarmCache) {
        $args += "--warm-cache"
    }
    if ($PerfSamples -ge 0) {
        $args += @("--perf-samples", "$PerfSamples")
    }

    if ($Smoke) {
        $smokeOffset = $QuestionOffset
        if ($smokeOffset -lt 0) {
            if ($Dataset -eq "dataset_new") {
                $smokeOffset = 50
            } else {
                $smokeOffset = 0
            }
        }
        $args += @("--dataset", $Dataset, "--limit", "1", "--perf-samples", "1", "--perf-duration-seconds", "0", "--upload-selected-docs-only")
        if ($smokeOffset -gt 0) {
            $args += @("--question-offset", "$smokeOffset")
        }
    } elseif ($Full) {
        if ($DatasetWasProvided) {
            $args += @("--dataset", $Dataset)
        }
        if ($LimitWasProvided) {
            $args += @("--limit", "$Limit")
        }
    } else {
        $args += @("--dataset", $Dataset, "--limit", "$Limit", "--upload-selected-docs-only")
        if ($QuestionOffset -gt 0) {
            $args += @("--question-offset", "$QuestionOffset")
        }
    }

    Run-Command -FilePath $Python -Arguments $args -Label "Eval run"
}

function Test-OutputArtifacts {
    $outputRoot = "eval\output"
    if (-not (Test-Path $outputRoot)) {
        Fail "Eval output root was not created: $outputRoot"
    }
    $latest = Get-ChildItem $outputRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) {
        Fail "No eval run directory found in $outputRoot"
    }
    $required = @(
        "manifest.json",
        "preflight.json",
        "upload_map.json",
        "ingest_status.json",
        "golden_qa_used.jsonl",
        "qa_results.jsonl",
        "retrieval_results.jsonl",
        "ragas_results.jsonl",
        "ragas_summary.json",
        "safety_reliability.json",
        "performance_cold.json",
        "business_metrics.json",
        "decision.json",
        "report.md"
    )
    $missing = @()
    foreach ($file in $required) {
        if (-not (Test-Path (Join-Path $latest.FullName $file))) {
            $missing += $file
        }
    }
    if ($missing.Count -gt 0) {
        Write-Host "Latest output directory: $($latest.FullName)" -ForegroundColor Yellow
        if (Test-Path (Join-Path $latest.FullName "fatal_error.json")) {
            Write-Host "fatal_error.json:" -ForegroundColor Yellow
            Get-Content (Join-Path $latest.FullName "fatal_error.json") | Out-Host
        }
        Fail "Eval run did not produce required artifacts: $($missing -join ', ')"
    }
    Write-Host ""
    Write-Host "SUCCESS: eval artifacts created in $($latest.FullName)" -ForegroundColor Green
}

Assert-RepoRoot

if (($UseCloudStorage -and -not $UseCloudQdrant) -or ($UseCloudQdrant -and -not $UseCloudStorage)) {
    Fail "Mixed cloud/local infra is not supported by this runner. Use neither switch for local MinIO+Qdrant, or use both -UseCloudStorage -UseCloudQdrant."
}

Write-Step "Preparing eval Python environment"
$python = Ensure-Python

Write-Step "Loading local env"
Normalize-EnvForLocal

Write-Step "Checking cloud prerequisites"
Test-CloudPrereqs -Python $python

if (-not $SkipUnitTests) {
    Write-Step "Running parser/unit checks"
    Ensure-TestDeps -Python $python
    Run-Command -FilePath $python -Arguments @("-m", "compileall", "eval\run_eval.py", "eval\lib") -Label "Compile eval"
    Run-Command -FilePath $python -Arguments @("-m", "pytest", "eval\tests") -Label "Eval tests"
}

Write-Step "Checking Docker"
Ensure-Docker

Write-Step "Starting local e2e stack"
Start-Stack

Write-Step "Checking service health"
Test-HttpHealth -Name "user-service" -Url "http://localhost:8000/health"
Test-HttpHealth -Name "query-service" -Url "http://localhost:8001/health"
Test-HttpHealth -Name "document-service" -Url "http://localhost:8002/health"
Test-HttpHealth -Name "mcp-service" -Url "http://localhost:8003/health" -Optional

Write-Step "Running eval"
Invoke-Eval -Python $python

Write-Step "Verifying eval output"
Test-OutputArtifacts

if (-not $KeepStack) {
    Write-Host ""
    Write-Host "Stack is still running for inspection. Stop it when done:" -ForegroundColor Yellow
    if (-not $UseCloudStorage -or -not $UseCloudQdrant) {
        Write-Host "docker compose -f docker-compose.e2e.yml -f eval\docker-compose.local-eval.yml down -v"
    } else {
        Write-Host "docker compose -f docker-compose.e2e.yml down -v"
    }
}
