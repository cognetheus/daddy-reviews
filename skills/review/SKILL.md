---
name: review
description: Deliberate evidence-first Daddy Reviews assessment of tracked working changes or a clean feature branch, with independent risk-proportionate verification.
disable-model-invocation: true
argument-hint: "[working | branch <base-ref>] [focus]"
---

# Daddy Reviews for Claude Code

Run only on explicit request. User arguments: $ARGUMENTS. Never interpolate untrusted input directly into a shell command. Requires Python 3.10+ and Git, but no pip installation. The plugin is at ${CLAUDE_PLUGIN_ROOT}; work in the user's target Git project.

1. Read review-orchestrator, pr-review, repository-intelligence and findings-verification from this plugin's skills directory. Load other specialist skills (backend, frontend, security, ORM, dependency, infra, standards, architecture) only if relevant.
2. Default to working mode (staged + unstaged tracked files). If explicitly asked for 'branch <base-ref>', identify the real base and use branch mode; don't guess an unrelated branch or HEAD~1. Branch mode requires a clean checkout.
3. Run from the target project worktree with Claude Code's Bash tool:

   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/claude_review.py" --root . --scope working
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/claude_review.py" --root . --scope branch --base origin/main

   The branch command is an example; use origin/main only if it is the verified base. No project code, network, model or GitHub writer is executed by the Python bridge.
4. A nonzero exit, abstained, or no_tracked_diff is NOT a clean review. Working scope excludes untracked files: disclose the count and do not claim complete scope. Preserve patch SHA identity and warnings.
5. Independently inspect important changed hunks, consumers, relevant tests and contracts. Try to refute every potential defect and check mitigating guards; candidates are not verified runtime findings. Broaden scope only with evidence. Distinguish introduced bugs, pre-existing debt and unknown risks.
6. Report precise source line references, demonstrated impact, severity vs confidence, reproductions, tests actually run or not run, residual uncertainty and proposed fixes. Zero actionable findings is valid.

Advisory only. Do not modify source, execute untrusted project code, install dependencies, call local Ollama or remote model tools, post GitHub comments, approve, merge or alter release policy without separate explicit user authorization. Claude Code itself processes project context through the user's configured model; only the deterministic bridge makes no model/API calls.
