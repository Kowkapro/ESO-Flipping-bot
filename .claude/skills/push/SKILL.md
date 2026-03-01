---
name: push
description: Commit all changes and push to GitHub
disable-model-invocation: true
allowed-tools: Bash
argument-hint: [optional commit message]
---

# Commit & Push to GitHub

Commit all current changes and push to the remote repository.

## Steps

1. Run `git status` to see all changes (never use `-uall` flag)
2. Run `git diff` to review staged and unstaged changes
3. Run `git log --oneline -3` to see recent commit message style
4. Stage all relevant changed files (avoid staging `.env`, secrets, large data files)
5. Create a commit with a short, meaningful message in **English**
   - If `$ARGUMENTS` is provided, use it as the commit message
   - Otherwise, generate a message based on the changes
   - End with: `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`
6. Push to the current branch: `git push origin $(git branch --show-current)`
7. Confirm success and show the commit hash

## Rules
- Commit messages must be in English (per project CLAUDE.md)
- Never commit `.env`, `*.log`, `SavedVariables/`, `__pycache__/`
- Never commit large data files (PriceTable*.lua)
- Use `git add` with specific files, not `git add -A`
