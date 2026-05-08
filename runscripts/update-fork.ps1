param(
    [string]$ForkUrl = "https://github.com/cpxazn/MedusaAnime.git",
    [string]$UpstreamUrl = "https://github.com/pymedusa/Medusa.git",
    [string]$UpstreamBranch = "master",
    [string]$MirrorBranch = "master",
    [string]$FeatureBranch = "feature/livechart-integration",
    [switch]$RunTests,
    [switch]$SkipMirrorPush,
    [switch]$AllowDirty
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Ensure-Remote {
    param(
        [string]$Name,
        [string]$Url
    )

    $remoteNames = @(git remote)
    if ($remoteNames -notcontains $Name) {
        Write-Step "Adding remote '$Name' -> $Url"
        git remote add $Name $Url
        return
    }

    $existing = (git remote get-url $Name).Trim()

    if ($existing -ne $Url) {
        Write-Step "Updating remote '$Name' from '$existing' to '$Url'"
        git remote set-url $Name $Url
    }
}

function Ensure-Clean-Tree {
    $status = git status --porcelain
    if (-not [string]::IsNullOrWhiteSpace($status)) {
        throw "Working tree has uncommitted changes. Commit or stash first, or rerun with -AllowDirty."
    }
}

function Ensure-Branch {
    param(
        [string]$Branch,
        [string]$StartPoint
    )

    git show-ref --verify --quiet "refs/heads/$Branch"
    if ($LASTEXITCODE -ne 0) {
        Write-Step "Creating branch '$Branch' from '$StartPoint'"
        git checkout -b $Branch $StartPoint
    }
}

$autoStashCreated = $false
$completed = $false

try {
    Write-Step "Validating repository"
    git rev-parse --is-inside-work-tree | Out-Null

    if (-not $AllowDirty) {
        Write-Step "Checking working tree is clean"
        Ensure-Clean-Tree
    }
    else {
        $status = git status --porcelain
        if (-not [string]::IsNullOrWhiteSpace($status)) {
            Write-Step "Stashing local changes because -AllowDirty was set"
            git stash push --include-untracked --message "update-fork-autostash"
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to create auto-stash."
            }
            $autoStashCreated = $true
        }
    }

    Write-Step "Ensuring remotes are configured"
    Ensure-Remote -Name "origin" -Url $ForkUrl
    Ensure-Remote -Name "upstream" -Url $UpstreamUrl

    Write-Step "Fetching origin and upstream"
    git fetch --prune origin
    git fetch --prune upstream

    Write-Step "Syncing local '$MirrorBranch' with upstream/$UpstreamBranch"
    Ensure-Branch -Branch $MirrorBranch -StartPoint "upstream/$UpstreamBranch"
    git checkout $MirrorBranch
    git reset --hard "upstream/$UpstreamBranch"

    if (-not $SkipMirrorPush) {
        Write-Step "Pushing mirror branch '$MirrorBranch' to origin"
        git push --force-with-lease origin "${MirrorBranch}:${MirrorBranch}"
    }

    git show-ref --verify --quiet "refs/heads/$FeatureBranch"
    if ($LASTEXITCODE -ne 0) {
        git show-ref --verify --quiet "refs/remotes/origin/$FeatureBranch"
        if ($LASTEXITCODE -eq 0) {
            Write-Step "Creating local feature branch from origin/$FeatureBranch"
            git checkout -b $FeatureBranch "origin/$FeatureBranch"
        }
        else {
            Write-Step "Creating new feature branch '$FeatureBranch' from '$MirrorBranch'"
            git checkout -b $FeatureBranch $MirrorBranch
        }
    }
    else {
        git checkout $FeatureBranch
    }

    Write-Step "Rebasing '$FeatureBranch' onto '$MirrorBranch'"
    git rebase $MirrorBranch

    if ($RunTests) {
        $targetedTests = @(
            "tests/clients/test_anime.py",
            "tests/helpers/test_anime_matcher.py",
            "tests/apiv2/test_anime.py"
        )
        $existingTargets = @($targetedTests | Where-Object { Test-Path $_ })

        if ($existingTargets.Count -gt 0) {
            Write-Step "Running targeted anime test suite"
            python -m pytest @existingTargets -v
            if ($LASTEXITCODE -ne 0) {
                throw "Tests failed."
            }
        }
        elseif (Test-Path "tests") {
            Write-Step "Running fallback smoke tests because anime test files were not found"
            python -m pytest tests -q
            if ($LASTEXITCODE -ne 0) {
                throw "Tests failed."
            }
        }
        else {
            Write-Step "No test paths found in this checkout; skipping -RunTests"
        }
    }

    Write-Step "Pushing rebased feature branch to origin"
    git push --force-with-lease origin "${FeatureBranch}:${FeatureBranch}"

    $completed = $true
    Write-Step "Done"
    Write-Host "Feature branch '$FeatureBranch' is now rebased on upstream/$UpstreamBranch and pushed to your fork." -ForegroundColor Green
}
finally {
    if ($autoStashCreated) {
        if ($completed) {
            Write-Step "Restoring previously stashed local changes"
            git stash pop
        }
        else {
            Write-Step "Script failed; local changes are still stashed"
            Write-Host "Run 'git stash list' and 'git stash pop' after resolving the error." -ForegroundColor Yellow
        }
    }
}