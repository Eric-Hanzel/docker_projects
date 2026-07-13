---
name: portable-bundle-audit
description: Read-only final audit for portable deliverables. Returns PASS, CONDITIONAL, or FAIL.
---

# Purpose

Audit only the final portable deliverable. This is the independent hallucination guard before terminal success.

Scope:

- `Deliverable/<project_name>-final/`
- `DP_LOGS/<project_name>-final/`

Do not fix files. Do not write terminal task state. Do not substitute primary/bootstrap outputs for final evidence.

# Inputs

- `project_name`
- `audit_attempt`
- target `url`
- extras, if any

# Required Checks

Verify final artifacts:

- `README_QUICKSTART.md`
- `docker-compose.yml`
- required `Dockerfile` or clear image-first explanation
- required `docker/entrypoint.sh` when custom startup exists
- `scripts/deploy.sh`
- `scripts/verify.sh`
- `scripts/reset.sh`
- `source-initialized.tar.gz` or `runtime-config-initialized.tar.gz`
- DB dump under `initdb/` or `initdb/README_NO_DB.md`

Verify final logs:

- `preflight.json`
- `preflight.md`
- `deploy.log`
- `verification_result.json`
- `summary.md`

Verify docs:

- required quick start commands are present
- optional env vars are labeled optional
- user-provided secrets/licenses are masked
- from-zero redeploy uses `reset.sh`, `deploy.sh`, `verify.sh`
- destructive reset warning is explicit
- purpose, baseline functions, URLs, and expected behavior are documented

Verify behavior evidence:

- final bundle was deployed from its own artifacts
- public endpoint returns expected status
- response bodies do not contain runtime/framework error signatures
- UI asset check exists when a UI exists
- at least one baseline function is verified after initialization

Verify portability:

- no expanded `source/` tree is required at rest
- scripts do not hard fail solely because `.codex` or the port registry is unavailable
- compose project and built images are task-scoped
- reset/deploy/verify paths are relative to the final bundle

# Blocking Failures

Return `FAIL` for:

- missing required artifact or log
- no final redeploy verification
- verification only proves container health or HTTP status
- UI missing when the official product requires a UI
- docs-only output when a runnable app exists
- unmasked user-provided secret in final docs
- reset/deploy/verify cannot run outside APDv1
- Docker cleanup requires host-global prune/stop/remove commands

Return `CONDITIONAL` only when:

- final artifacts are coherent
- scripts are redeployable
- the only blocker is an external prerequisite such as a required license, private credential, or unavailable third-party service
- `conditional_reason` and `blocking_requirement` are documented

# Output

Write:

- `DP_LOGS/<project_name>-final/audit.md`
- `DP_LOGS/<project_name>-final/audit_result.json`

`audit_result.json` must match `.codex/contracts/audit_result.schema.json`:

```json
{
  "project_name": "string",
  "delivery_mode": "portable-deliverable",
  "attempt": 1,
  "verdict": "PASS|FAIL|CONDITIONAL",
  "verified_url": "string",
  "basic_function_verified": true,
  "blocking_findings": [
    {
      "id": "P1",
      "title": "string",
      "evidence": "path or command evidence",
      "required_fix": "string"
    }
  ],
  "warnings": ["string"],
  "conditional_reason": "string when conditional",
  "blocking_requirement": "string when conditional",
  "checked_at": "ISO-8601"
}
```

Final `PASS` requires an empty `blocking_findings` array and `basic_function_verified=true`.
