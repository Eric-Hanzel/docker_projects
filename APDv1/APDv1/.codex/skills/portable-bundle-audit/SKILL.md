---
name: portable-bundle-audit
description: Audit portable bundle artifacts and workflow logs, return strict PASS/FAIL with remediation items.
---

# Purpose

Audit whether the portable bundle is complete, reproducible, and backed by coherent logs.

# When To Use

- after `post-deploy-portable-bundle` completes
- before declaring overall task success
- after parent remediation for re-audit

# Required Inputs

- `project_name`
- `audit_attempt` (1-based)
- target `url`
- `extras` if any

# Scope (Mandatory)

Audit only final portable bundle outputs:

1. final portable outputs
   - `Deliverable/<project_name>-final/`
2. final bundle logs
   - `DP_LOGS/<project_name>-final/`

# Artifact Checks (Mandatory)

Verify presence and consistency of:

1. `Deliverable/<project_name>-final/Dockerfile`
2. `Deliverable/<project_name>-final/docker-compose.yml`
3. `Deliverable/<project_name>-final/docker/entrypoint.sh`
4. `Deliverable/<project_name>-final/scripts/deploy.sh`
5. `Deliverable/<project_name>-final/scripts/verify.sh`
6. `Deliverable/<project_name>-final/scripts/reset.sh`
7. `Deliverable/<project_name>-final/README_QUICKSTART.md`
8. `Deliverable/<project_name>-final/source-initialized.tar.gz`
9. `Deliverable/<project_name>-final/initdb/00-<db>.sql.gz`

Also require that `README_QUICKSTART.md`:

- separates required startup commands from optional env exports
- marks license vars such as `OCTOBER_LICENSE_KEY` as optional unless strictly required
- states that preset extras/license values are usually not needed again for restart
- includes a dedicated from-zero flow:
  - `./scripts/reset.sh`
  - `./scripts/deploy.sh`
  - `./scripts/verify.sh`
- clearly warns that `reset.sh` is destructive
- explains what the project is for
- explains the basic functions expected from the portable bundle
- lists each published URL or endpoint that a user/operator is expected to touch
- explains the purpose of each URL or endpoint
- explains the expected behavior for each URL or endpoint, for example HTML page, JSON API, redirect, login page, health response, or expected `404`

Also verify the final bundle does not keep an expanded `source/` tree.
Also verify that `scripts/reset.sh`, `scripts/deploy.sh`, and `scripts/verify.sh` do not hard fail solely because `.codex/scripts/port_registry.py` or registry state files are unavailable.

# Log Checks (Mandatory)

Verify:

1. `DP_LOGS/<project_name>-final/deploy.log` includes:
   - extraction commands
   - clean simulation steps
   - verification evidence
   - cleanup of temporary `./source/`
2. `DP_LOGS/<project_name>-final/summary.md` includes:
   - final URLs
   - credentials when applicable
   - fixes made during packaging verification
   - `Quick Restart Verification` when successful
   - the concrete basic-function verification that proved the portable re-deploy remained usable
   - what the project is for
   - the basic functions that were actually verified after portable re-deploy
   - each verified published URL or endpoint with its purpose and expected behavior
3. `DP_LOGS/<project_name>-final/audit_result.json` is consistent with the audit report after each attempt when present

# Functional Audit Gate (Mandatory)

Verify the final portable bundle is not merely container-up:

1. review final verification evidence and require at least one concrete basic-function check that matches the product's baseline behavior after re-deploy
2. if the product normally exposes a UI, API, operator console, or authenticated flow, require evidence that one such real function succeeded from the portable bundle

Treat these as blocking failures:

- bundle services are healthy but no evidence shows baseline product functionality after re-deploy
- final verification proves only reachability or asset delivery while basic initialized functions remain broken
- bundle scripts hard depend on registry helper/state files and cannot run their fallback path without `.codex/scripts/port_registry.py`
- final bundle preserves only a docs site or marketing site when the upstream project also provides an official runnable application that should have been the real target

# Output Contract (Mandatory)

Produce both:

1. human-readable report: `DP_LOGS/<project_name>-final/audit.md`
2. machine-readable result: `DP_LOGS/<project_name>-final/audit_result.json`

`audit_result.json` schema:

```json
{
  "project_name": "string",
  "attempt": 1,
  "verdict": "PASS|FAIL",
  "blocking_findings": [
    {
      "id": "A1",
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
- every blocking finding must include concrete file-path evidence
- missing `scripts/reset.sh` is blocking
- missing or ambiguous env guidance in `README_QUICKSTART.md` is blocking
- missing or ambiguous from-zero redeploy instructions is blocking
- missing reset impact warning is blocking
- missing project-purpose, basic-function, or URL-behavior documentation in `README_QUICKSTART.md` is blocking

# Parent Integration Contract (Mandatory)

When used under `official-flow-deploy`:

- auditor returns findings, evidence, and PASS/FAIL only
- auditor does not write terminal task state
- auditor does not call `experience-feedback`
- auditor does not perform final Docker cleanup

Parent reads `audit_result.json` and decides:

- `PASS` => continue to success path and Phase 7
- `FAIL` with `attempt < 3` => remediate and re-audit
- `FAIL` with `attempt == 3` => declare task failure
