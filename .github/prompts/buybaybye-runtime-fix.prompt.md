---
description: "Implement a focused BuyBayBye runtime fix from logs or a short requirement"
name: "BuyBayBye Runtime Fix"
argument-hint: "Issue, logs, or change request for BuyBayBye runtime"
agent: "agent"
model: "GPT-5 (copilot)"
---

Implement one focused runtime change in BuyBayBye based on the user's issue description, logs, or short requirement.

Use this prompt for tasks such as:
- fixing behavior in `buybaybye/` runtime modules
- reconciling accounting, betting, or shared runtime-state issues
- restoring broken Russian logs or terminal output strings
- removing or narrowing runtime features safely

Required context:
- Follow [project instructions](../copilot-instructions.md)
- Follow [runtime Python instructions](../instructions/runtime-python.instructions.md)

Workflow:
1. Re-read the current contents of the affected files before editing, especially if the user mentions recent undos, formatter changes, or manual edits.
2. Build context from the relevant runtime modules under `buybaybye/`, plus config or dashboard files only when the issue crosses those boundaries.
3. Make the smallest coherent change that fixes the root cause.
4. Preserve Russian user-facing logs, current runtime layering, and existing behavior outside the requested fix.
5. Validate every changed file with diagnostics.
6. Summarize what changed, what was verified, and any remaining runtime risks.

Output requirements:
- Implement the change directly when possible; do not stop at analysis.
- Avoid unrelated refactors.
- If the issue is actually local configuration, say so explicitly and point to the relevant config file.

If the request is ambiguous, ask only the minimum clarifying questions needed to choose the target module or scope.