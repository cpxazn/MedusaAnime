param(
    [string]$VenvDir = ".venv",
    [string]$DataDir = "D:\Medusa-dev-data",
    [int]$Port = 8081,
    [switch]$InstallRequirements,
    [switch]$SkipBuild,
    [switch]$ProductionBuild,
    # Path to a Node 18 binary directory (e.g. "C:\node18"). If set, this is
    # prepended to PATH only for the npm install / build steps so the system
    # Node is not affected.
    [string]$Node18Path = "J:\Downloads\node-v18.20.8-win-x64"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $repoRoot $VenvDir
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"

Write-Host "==> Repo root: $repoRoot" -ForegroundColor Cyan
Write-Host "==> Virtualenv: $venvPath" -ForegroundColor Cyan
Write-Host "==> Data dir: $DataDir" -ForegroundColor Cyan

if (-not (Test-Path $venvPath)) {
    Write-Host "==> Creating virtual environment" -ForegroundColor Cyan
    py -3.13 -m venv $venvPath
}

if (-not (Test-Path $activateScript)) {
    throw "Unable to find activation script at $activateScript"
}

if (-not (Test-Path $DataDir)) {
    Write-Host "==> Creating data directory" -ForegroundColor Cyan
    New-Item -ItemType Directory -Path $DataDir | Out-Null
}

Set-Location $repoRoot

Write-Host "==> Activating virtual environment" -ForegroundColor Cyan
. $activateScript

if ($InstallRequirements) {
    Write-Host "==> Installing requirements" -ForegroundColor Cyan
    python -m pip install --upgrade pip
    pip install -r requirements.txt
}

if (-not $SkipBuild) {
    $slimDir = Join-Path $repoRoot "themes-default\slim"

    # Auto-detect a Node 18 binary path when one is not explicitly provided.
    if ($Node18Path -eq "") {
        $node18Candidates = @(
            "J:\Downloads\node-v18.20.8-win-x64",
            "C:\Program Files\nodejs"
        )

        foreach ($candidate in $node18Candidates) {
            $candidateNode = Join-Path $candidate "node.exe"
            if (-not (Test-Path $candidateNode)) {
                continue
            }

            $candidateVersion = (& $candidateNode --version)
            if ($candidateVersion -match '^v18\.') {
                $Node18Path = $candidate
                break
            }
        }
    }

    # Optionally scope PATH to a specific Node binary directory
    $savedPath = $env:PATH
    if ($Node18Path -ne "") {
        if (-not (Test-Path $Node18Path)) {
            throw "Node18Path '$Node18Path' does not exist"
        }
        $env:PATH = "$Node18Path;$env:PATH"
        Write-Host "==> Using Node: $((& (Join-Path $Node18Path 'node.exe') --version))" -ForegroundColor Cyan
    } else {
        $nodeCommand = Get-Command node -ErrorAction SilentlyContinue
        if (-not $nodeCommand) {
            throw "Node.js not found. Install Node 18 or pass -Node18Path."
        }

        $pathNodeVersion = (& node --version)
        if ($pathNodeVersion -notmatch '^v18\.') {
            throw "Detected Node $pathNodeVersion on PATH. This script requires Node 18. Install Node 18 or pass -Node18Path."
        }

        Write-Host "==> Using Node from PATH: $pathNodeVersion" -ForegroundColor Cyan
    }

    try {
        if (-not (Test-Path (Join-Path $slimDir "node_modules"))) {
            Write-Host "==> Installing frontend dependencies (npm)" -ForegroundColor Cyan
            Push-Location $slimDir
            npm install --legacy-peer-deps --ignore-scripts
            if ($LASTEXITCODE -ne 0) { throw "npm install failed (exit code $LASTEXITCODE)" }
            # ajv-keywords v5 requires ajv v8; npm may resolve ajv v6, so force v8
            npm install ajv@^8 --legacy-peer-deps --ignore-scripts
            if ($LASTEXITCODE -ne 0) { throw "ajv install failed (exit code $LASTEXITCODE)" }
            Pop-Location
        }
        $buildMode = if ($ProductionBuild) { "build" } else { "dev" }
        Write-Host "==> Building frontend ($buildMode)" -ForegroundColor Cyan
        Push-Location $slimDir
        npm run $buildMode
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend build failed (exit code $LASTEXITCODE)"
        }
        Pop-Location
        Write-Host "==> Frontend build complete" -ForegroundColor Green
    } finally {
        $env:PATH = $savedPath
    }
} else {
    Write-Host "==> Skipping frontend build (-SkipBuild)" -ForegroundColor Yellow
}

Write-Host "==> Starting Medusa on http://localhost:$Port" -ForegroundColor Green
python start.py --nolaunch --port $Port --datadir $DataDir