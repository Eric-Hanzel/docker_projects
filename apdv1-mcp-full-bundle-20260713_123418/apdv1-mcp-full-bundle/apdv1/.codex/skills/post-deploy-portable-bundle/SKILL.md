---
name: post-deploy-portable-bundle
description: Build and verify a reproducible portable Docker bundle directly from official deployment information.
---

# Purpose

Use for `delivery_mode=portable-deliverable` when a full portable bundle is required. The main agent may execute this skill directly. A worker subagent is optional and should be reserved for large or repeatedly failing builds.

Goal:

- final artifacts in `Deliverable/<project_name>-final/`
- final logs in `DP_LOGS/<project_name>-final/`
- bundle redeploy verified by its own scripts

# Inputs

- target JSON object with required `url`
- optional extras such as `version_requirement`, `license_key`, credentials, or notes
- official docs, README, release metadata, upstream compose/Dockerfile/image references
- relevant experience records only when there is a strong stack/project match

# Workflow

1. Resolve `project_name`.
   - use a semantic product/repo name
   - include upstream version when known
   - avoid collisions with existing `Deliverable/` or `DP_LOGS/`
2. Persist task state:
   - `delivery_mode=portable-deliverable`
   - `portable_final_required=true`
   - `project_name=<project_name>`
   - `cleanup_project_names=<project_name>-final` or the actual compose project name
3. Discover the official setup path:
   - supported version
   - runtime and service dependencies
   - install/init commands
   - DB/cache requirements
   - normal UI/API entrypoints
   - baseline function that can prove usability
4. Build final bundle directly under `Deliverable/<project_name>-final/`.
5. Add scripts:
   - `scripts/deploy.sh`
   - `scripts/verify.sh`
   - `scripts/reset.sh`
6. Add initialized snapshot:
   - `source-initialized.tar.gz` when local source/build context is required
   - `runtime-config-initialized.tar.gz` for official image-first deployments
7. Add DB state:
   - `initdb/00-<db>.sql.gz` for DB-backed state
   - `initdb/README_NO_DB.md` when no DB is required
8. Redeploy from the final bundle only:
   - run `./scripts/reset.sh` when validating from zero
   - run `./scripts/deploy.sh`
   - run `./scripts/verify.sh`
9. Write final logs and evidence.

# Required Files

Portable deliverable:

- `README_QUICKSTART.md`
- `docker-compose.yml`
- `Dockerfile` when a local image/build is needed
- `docker/entrypoint.sh` when custom startup/init is needed
- `scripts/deploy.sh`
- `scripts/verify.sh`
- `scripts/reset.sh`
- `source-initialized.tar.gz` or `runtime-config-initialized.tar.gz`
- `initdb/00-<db>.sql.gz` or `initdb/README_NO_DB.md`

Logs:

- `preflight.json`
- `preflight.md`
- `deploy.log`
- `verification_result.json`
- `summary.md`
- `errors.log` when errors occurred

# README_QUICKSTART Contract

Include these sections:

- `Required Quick Start`
- `Optional Environment`
- `From Zero Re-Deploy`
- `Reset Impact Warning`
- `Project Purpose`
- `Expected Basic Functions`
- `URLs and Expected Behavior`
- `Credentials`
- `Troubleshooting`

Rules:

- mark optional env vars clearly
- mask user-provided secrets, tokens, and license keys
- state that `reset.sh` is destructive
- include `./scripts/reset.sh`, `./scripts/deploy.sh`, `./scripts/verify.sh`
- document every user/operator URL and expected response

# Verification Contract

`scripts/verify.sh` and `verification_result.json` must prove:

- public entrypoint returns expected status
- response body lacks common framework/runtime error signatures
- critical UI assets return success when a UI exists
- one concrete baseline function works after initialization
- `verification_result.json` includes top-level `"passed": true`
- `verification_result.json` includes top-level `"basic_function_verified": true`

Do not accept container health, port listening, or a plain `HTTP 200` as sufficient.

# Port Registry

Use `.codex/scripts/port_registry.py` when available, but bundle scripts must still run outside APDv1:

1. prefer `APP_PUBLIC_PORT` if set
2. otherwise reuse a local saved port file
3. otherwise choose a documented default or local free port
4. skip registry commands gracefully when `.codex` is unavailable

# Conditional Success

Use conditional success only when an external prerequisite blocks full business initialization but the bundle is otherwise coherent and redeployable. Document:

- current working state
- missing external prerequisite
- exact next manual step
- `conditional_reason`
- `blocking_requirement`

# Machine Contracts

Use these files as the compact source of required structure:

- `.codex/contracts/target.schema.json`
- `.codex/contracts/final_outputs.schema.json`
- `.codex/contracts/audit_result.schema.json`

# Completion

After final bundle verification, run the independent portable audit gate. Do not write terminal task success until the audit returns `PASS` or valid `CONDITIONAL`.
