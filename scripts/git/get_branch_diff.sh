#!/bin/bash

# Make sure we get the diff from mobile-use
cd "$(dirname "$0")/.."

echo "=== Git Diff between current branch and main ==="
git diff "$(git merge-base origin/main HEAD)..HEAD"

echo -e "\n=== Git Log between current branch and main ==="
git log --oneline "$(git merge-base origin/main HEAD)..HEAD"
