---
name: experience-feedback
description: End-of-run pattern extraction and merged experience storage. Extract validated success and failure-avoidance patterns, then merge them into the hierarchical experience store under .codex/experience/.
---

# Purpose

Run only after the workflow ends:

- success: deployment finished and verification passed
- failure: retry budget exhausted

Do not run during intermediate fix loops.

# Inputs

Use current-run outputs such as:

- `DP_LOGS/<project_name>/deploy.log`
- `DP_LOGS/<project_name>/errors.log` if present
- `DP_LOGS/<project_name>/summary.md`
- `DP_LOGS/<project_name>-final/deploy.log` if portable extraction ran
- `DP_LOGS/<project_name>-final/errors.log` if present

# Stores

- catalog: `.codex/experience/catalog.json`
- subcategory indexes: `.codex/experience/index/...`
- detail records: `.codex/experience/details/...`
- helper CLI: `python3 .codex/scripts/experience_store.py`

# Store Layout

1. read `.codex/experience/catalog.json`
2. classify each validated pattern into:
   - `success_patterns`
   - `failure_avoidance_patterns`
3. place it into one stable subcategory, for example:
   - success: `deploy-path`, `runtime-init`, `verification`, `bundle-packaging`, `performance-decisions`, `project-specific`
   - failure avoidance: `source-fetch`, `image-pull`, `runtime-init`, `dependency-gates`, `ports-and-network`, `verification`, `build-artifacts`, `project-specific`
4. merge the detail record into the matching file under `.codex/experience/details/...`
5. refresh the matching lightweight index file under `.codex/experience/index/...`

# Detail Record Shape

```json
{"id":"EXP-...","kind":"success_patterns|failure_avoidance_patterns","subcategory":"...","category":"...","signature":"...","summary":"short canonical summary","stage":["..."],"severity":"low|medium|high","tags":["..."],"project_patterns":["..."],"stack_patterns":["..."],"symptom":"short symptom","root_cause":"short root cause","successful_path":"validated winning path when applicable","fix":["..."],"precheck":["..."],"anti_pattern":["..."],"quick_checks":["..."],"evidence":["..."],"count":1,"created_at":"ISO-8601","updated_at":"ISO-8601","last_seen":"ISO-8601"}
```

# Index Record Shape

```json
{"id":"EXP-...","kind":"...","subcategory":"...","category":"...","signature":"...","stage":["..."],"severity":"low|medium|high","tags":["..."],"project_patterns":["..."],"stack_patterns":["..."],"summary":"short canonical summary","quick_checks":["..."],"detail_file":"details/...jsonl","count":1,"last_seen":"ISO-8601"}
```

# Quality Gate (Mandatory)

Persist only experience that is:

1. accurate
2. validated
3. effective

Do not store guesses, uncertain root causes, or unverified fixes.

Persist both of these when validated:

1. `success_patterns`
   - correct official path
   - correct initialization sequence
   - high-value verification steps
   - winning bundle/redeploy flow
2. `failure_avoidance_patterns`
   - false leads
   - common traps
   - prechecks that prevent wasted retries
   - anti-patterns that reliably cost time

# Merge Rules (Mandatory)

1. Normalize by `kind + category + signature`.
2. Use `python3 .codex/scripts/experience_store.py upsert-record --input <file>` when possible.
3. If an entry exists:
   - increment `count`
   - update `updated_at` and `last_seen`
   - merge unique values in `tags`, `stage`, `project_patterns`, `stack_patterns`, `quick_checks`, `fix`, `precheck`, `anti_pattern`, `evidence`
   - keep `summary`, `symptom`, and `root_cause` concise and canonical
4. If no entry exists, create it in the chosen subcategory detail file and refresh that subcategory index.
5. Keep `id` stable once created.
6. Keep subcategory choice stable unless the previous placement was clearly wrong.

# Usage Semantics

- Experience is guidance, not truth.
- Future runs must verify applicability before using an entry.
- If an entry is outdated or wrong, fix it here.

# State Handling

This is an end-of-run skill. Keep `.codex/state/task_state.json` in a terminal state after writing outputs.

- allowed terminal states: `COMPLETED_SUCCESS`, `COMPLETED_FAILED`, `TIMED_OUT`, `ABORTED`
- do not revert state to `RUNNING`
- treat `TIMED_OUT` and `ABORTED` as runner-owned and do not overwrite them

Batch ownership:

- do not overwrite runner-owned statuses: `INITIALIZING`, `STARTING`, `TIMED_OUT`, `ABORTED`, `IDLE`
- if this skill must write status, use only agent-owned statuses: `RUNNING`, `COMPLETED_SUCCESS`, `COMPLETED_FAILED`

# Extraction Guidance

Prefer actionable patterns such as:

- correct official path choices that shortened a successful deployment
- runtime sequencing that avoided rework
- port conflicts
- runtime version mismatch
- DB readiness or SSL/client-flag issues
- permission or ownership issues
- verification timing or race issues
- non-critical external service failures that should stay non-blocking
- proxy or localhost verification false positives
- source-fetch fallbacks that proved reliable
- bundle verification steps that prevented broken artifacts from shipping

Do not store full stack traces.

# Completion Criteria

- `.codex/experience/catalog.json` used as the routing source of truth
- matching `.codex/experience/index/...` files updated
- matching `.codex/experience/details/...` files updated
- same-run patterns merged by `kind + category + signature`
- only validated, accurate, effective patterns persisted
