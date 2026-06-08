---
name: official-deployment-audit
description: Independently verify and audit the primary official deployment result, then return strict PASS/FAIL before Phase 6 starts.
---

# Purpose

Audit whether the primary deployment really follows the official flow, is functionally usable, and is documented/logged clearly enough to justify entry into Phase 6.

# When To Use

- after the parent finishes primary deployment and remediation work
- before portable bundle extraction starts
- after parent remediation for re-audit

# Required Inputs

- `project_name`
- `audit_attempt` (1-based)
- target `url`
- deployment entry URL or resolved local URL
- `extras` if any

# Scope (Mandatory)

Audit only the primary deployment result:

1. primary deployment artifacts
   - `Deliverable/<project_name>/`
2. primary deployment logs
   - `DP_LOGS/<project_name>/`
3. live verification evidence for the primary deployment

Do not audit final portable bundle outputs here.

# Verification Checks (Mandatory)

Verify the primary deployment is actually usable:

1. main URL returns expected success or redirect status
2. response body does not contain framework/runtime failure signatures
3. critical static assets referenced by the main UI are reachable when applicable
4. login page or equivalent authenticated entrypoint is reachable when the app exposes one
5. if preset credentials are documented, use them for one authenticated verification when practical
6. require evidence that at least one basic product function works after initialization, for example a minimal user flow, operator flow, API action, CRUD path, route-specific content check, or background job result that matches the product's normal baseline behavior

Treat these as blocking failures:

- `HTTP 4xx` / `5xx` / `000`
- `HTTP 200` with exception/error content such as `Whoops`, `Mix manifest not found`, `DriverException`
- app process up but externally unusable
- app shell reachable but basic initialized functions still unusable
- docs-only or marketing-only deployment accepted in place of an official runnable application
- deployment reachable only through undocumented ad hoc shortcuts

# Audit Checks (Mandatory)

Verify:

1. `Deliverable/<project_name>/README_DEPLOY.md` describes the actual verified deployment path
2. `DP_LOGS/<project_name>/deploy.log` records key deployment, initialization, verification, failure, and remediation steps
3. `DP_LOGS/<project_name>/summary.md` matches the verified runtime state and includes restart verification guidance on success
4. the deployment behavior matches the official install flow rather than an improvised bypass
5. `README_DEPLOY.md` explains what the project is for, what basic functions are expected, and the purpose plus expected behavior of each published URL or endpoint
6. `summary.md` summarizes what the project is for, what basic functions were actually verified, and the purpose plus expected behavior of each verified published URL or endpoint
7. if the upstream repository contains both docs and runnable applications, the audited deployment target matches the official runnable application rather than merely the docs site unless docs-only deployment is explicitly justified

# Output Contract (Mandatory)

Produce both:

1. human-readable report: `DP_LOGS/<project_name>/audit.md`
2. machine-readable result: `DP_LOGS/<project_name>/audit_result.json`

`audit_result.json` schema:

```json
{
  "project_name": "string",
  "attempt": 1,
  "verdict": "PASS|FAIL",
  "blocking_findings": [
    {
      "id": "P1",
      "title": "string",
      "evidence": "path or command evidence",
      "required_fix": "string"
    }
  ],
  "warnings": ["string"],
  "checked_at": "ISO-8601"
}
```

Rules:

- `PASS` only if `blocking_findings` is empty
- `FAIL` if any blocking finding exists
- every blocking finding must include concrete file-path or command evidence

# Parent Integration Contract (Mandatory)

When used under `official-flow-deploy`:

- auditor returns findings, evidence, and PASS/FAIL only
- auditor does not write terminal task state
- auditor does not call `experience-feedback`
- auditor does not perform final Docker cleanup

Parent reads `audit_result.json` and decides:

- `PASS` => continue to Phase 6
- `FAIL` with `attempt < 3` => remediate and re-audit
- `FAIL` with `attempt == 3` => declare task failure
