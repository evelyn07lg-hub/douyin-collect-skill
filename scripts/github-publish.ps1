[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9-]+$')][string]$Owner = '',
    [ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$Repository = 'real-time-spoken-content-detection-update-skill'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$gh = Join-Path $root '.tools\github-cli\gh.exe'
if (-not (Test-Path -LiteralPath $gh)) { throw 'Official GitHub CLI is missing. Install gh or prepare the local .tools/github-cli/gh.exe first.' }
& $gh auth status --hostname github.com *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Authorize GitHub CLI in your browser. Do not send passwords or tokens to chat.'
    & $gh auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -ne 0) { throw 'GitHub authorization did not complete. No repository was published.' }
}
$login = (& $gh api user --jq '.login').Trim()
if ($LASTEXITCODE -ne 0 -or $login -ne $Owner) { throw ('Expected GitHub account ' + $Owner + '; signed in as ' + $login + '. Nothing published.') }
$changes = & git status --porcelain
if ($LASTEXITCODE -ne 0 -or $changes) { throw 'Working tree has uncommitted files. Review and commit before publishing.' }
$repo = $Owner + '/' + $Repository
$expectedRemote = 'https://github.com/' + $repo + '.git'
$existing = & $gh repo view $repo --json nameWithOwner,isPrivate 2>$null
if ($LASTEXITCODE -eq 0) {
    $details = $existing | ConvertFrom-Json
    if (-not $details.isPrivate -or $details.nameWithOwner -ne $repo) { throw 'Target is not the expected private repository. Nothing pushed.' }
    $origins = & git remote
    if ($origins -notcontains 'origin') { throw 'Repository already exists. Review it before connecting or uploading.' }
} else {
    if ((& git remote) -contains 'origin') { throw 'An origin already exists. Review it before creating another repository.' }
    & $gh repo create $repo --private --source $root --remote origin
    if ($LASTEXITCODE -ne 0) { throw 'Private repository creation failed.' }
}
$details = (& $gh repo view $repo --json nameWithOwner,isPrivate) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $details.isPrivate -or $details.nameWithOwner -ne $repo) { throw 'Private repository verification failed. Nothing pushed.' }
$origin = (& git remote get-url origin).Trim()
if ($origin -ne $expectedRemote) { throw ('Unexpected origin: ' + $origin + '. Nothing pushed.') }
& $gh auth setup-git --hostname github.com
if ($LASTEXITCODE -ne 0) { throw 'Git authentication setup failed.' }
& git push --set-upstream origin main
if ($LASTEXITCODE -ne 0) { throw 'Push failed. No force push was attempted.' }
$local = (& git rev-parse HEAD).Trim()
$remoteLine = & git ls-remote origin refs/heads/main
if ($LASTEXITCODE -ne 0 -or -not $remoteLine -or ($remoteLine -split '\s+')[0] -ne $local) { throw 'Remote commit verification failed.' }
$result = @{ ok = $true; repository = $repo; url = ('https://github.com/' + $repo); private = $true; commit = $local; verified_at = [DateTime]::UtcNow.ToString('o') }
$result | ConvertTo-Json | Set-Content -LiteralPath 'data\github-sync-result.json' -Encoding UTF8
$result | ConvertTo-Json
Write-Host 'Private repository synchronized. You can return to Codex now.'