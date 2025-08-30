---
description: Generate PR title and description based on git diff from main branch
auto_execution_mode: 3
---

## PR Title and Description Generator

This workflow automatically generates a PR title and description based on the git diff between your current branch and main.

### Step 1: Run the git diff script

Windows: `mobile-use\scripts\git\get_branch_diff.ps1`
MacOS / Linux: `bash "mobile-use/scripts/git/get_branch_diff.sh`

### Step 2: Generate PR title and description

Based on the git diff and commit history output above, generate a concise PR title following conventional commit format (eventually with scope) and a brief description with bullet points.

Title:

```
The PR title will appear here
```

Description:

```
The PR description with bullet points will appear here:

- Key change 1 with purpose
- Key change 2 with technical details
- Additional context if needed
```
