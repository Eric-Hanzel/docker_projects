---
name: official-deployment-audit
description: Read-only audit for local-run official deployments. Returns PASS or FAIL.
---

# Purpose

Use only for `delivery_mode=local-run`. This is an independent gate before local-run success.

Scope:

- `Deliverable/<project_name>/`
- `DP_LOGS/<project_name>/`
- live local deployment endpoint

Do not inspect portable final outputs. Do not fix files. Do not write terminal task state.

# Required Checks

Verify:

- local deployment follows the official install/deploy path closely enough to be trusted
- `README_DEPLOY.md` exists and explains the deployment
- `deploy.log` records install/init/verification commands and relevant fixes
- `summary.md` records verified URL and baseline function
- public endpoint returns expected status
- response body lacks framework/runtime error signatures
- critical UI assets are reachable when a UI exists
- one concrete baseline function works after initialization

Blocking failures:

- required endpoint returns `4xx`, `5xx`, or `000`
- only process/container health is proven
- UI missing when the official product requires a UI
- docs-only output accepted when a runnable app exists
- deployment relies on undocumented ad hoc shortcuts

# Output

Write:

- `DP_LOGS/<project_name>/audit.md`
- `DP_LOGS/<project_name>/audit_result.json`

Schema:

```json
{
  "project_name": "string",
  "delivery_mode": "local-run",
  "attempt": 1,
  "verdict": "PASS|FAIL",
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
  "checked_at": "ISO-8601"
}
```

`PASS` requires no blocking findings and a verified baseline function.
