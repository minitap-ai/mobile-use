# PowerShell script to get diff and log between current branch and main

# Making sure we get the diff from mobile-use
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir/..

$mergeBase = git merge-base origin/main HEAD

Write-Output "=== Git Diff between current branch and main ==="
git diff "$mergeBase..HEAD"

Write-Output "`n=== Git Log between current branch and main ==="
git log --oneline "$mergeBase..HEAD"
