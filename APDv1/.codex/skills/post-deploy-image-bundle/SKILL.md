---
name: post-deploy-image-bundle
description: After a successful deployment, package runtime environment, initialized source, and startup scripts into runnable images (plus docker save archives) for zero-extra-config fast re-deploy on another machine.
---

# Purpose

Run this skill only after deployment is already successful and verified. It creates an image-centric bundle so another machine can start the same initialized system immediately, without extra setup such as additional license export or first-run initialization.

# Scope and Goal

- input baseline: `Deliverable/<project_name>/` is already deployable and verified
- output goal: another operator can start the packaged system directly and log in with preset accounts
- expected behavior: startup is ready-to-use, not first-run setup

# Execution Mode (Mandatory)

Supported modes:

1. standalone: this skill owns the full workflow
2. spawned: delegated by an upstream workflow

Rules:

- standalone mode follows full task-state, consolidation, and cleanup rules below
- spawned mode handles image packaging and migration verification only, then returns evidence to parent
- in spawned mode, parent owns terminal task state, one-time experience consolidation, and final project-scoped Docker cleanup

# Output Locations (Mandatory)

- final bundle: `Deliverable/<project_name>-image-final/`
- logs: `DP_LOGS/<project_name>-image-final/`

# Naming Rule (Mandatory)

- use a semantic project-specific `project_name`
- do not use abstract names such as `apdv1`, `project-1`, `demo`, `tmp`
- if input is abstract, normalize to the official project name before creating `-image-final` folders
- when this skill owns task state, persist `project_name` and `cleanup_project_names` so final cleanup can target only this bundle's compose project
- if creating Docker resources outside compose, label them with `codex.apdv1.cleanup_project=<project_name>`

# Experience Precheck (Mandatory)

Before packaging or verification:

1. read `.codex/experience/catalog.json`
2. filter to the smallest relevant subcategories under `success_patterns` and/or `failure_avoidance_patterns`
3. query matching index entries with `python3 .codex/scripts/experience_store.py query ...`
4. read only the returned detail records from `.codex/experience/details/...`
5. apply listed quick checks before risky Docker export/import commands and avoid matching `anti_pattern` items

Use experience as guidance, not truth. Validate against current runtime signals and fix inaccurate entries during consolidation.

# Batch Input Compatibility (Mandatory)

For JSONL-driven upstream tasks:

1. treat `url` as primary target
2. treat all other keys as `extras`
3. use relevant extras during packaging
4. record consumed extras in final logs/summary

# Task State Tracking (Mandatory)

When this skill owns task state:

1. keep status `RUNNING` during packaging and verification
2. end with `COMPLETED_SUCCESS` or `COMPLETED_FAILED`
3. treat `TIMED_OUT` and `ABORTED` as runner-owned
4. append final result to `.codex/state/task_history.jsonl`

Use `python3 .codex/scripts/update_state.py` when available.

Batch ownership:

- write only agent-owned statuses: `RUNNING`, `COMPLETED_SUCCESS`, `COMPLETED_FAILED`
- never write runner-owned statuses: `INITIALIZING`, `STARTING`, `TIMED_OUT`, `ABORTED`, `IDLE`

Spawned override:

- if delegated, do not write terminal task state
- return result and evidence to parent instead

# Bundle Strategy (Mandatory)

Package a ready-to-run initialized image set:

1. runtime dependencies live in image layers
2. application source lives in image layers
3. startup/entrypoint scripts live in image layers and bundle scripts
4. initialized system state is preserved for immediate login/use

Also export offline archives so the bundle does not depend on a registry:

- `images/*.tar` from `docker save`, compressed to `.tar.gz` when useful

# No-Extra-Config Rule (Mandatory)

The produced bundle must satisfy all of these:

1. restart does not require extra project setup
2. license-related runtime is already usable from packaged state
3. no first-run installer or init wizard appears
4. preset admin/operator credentials work immediately after deploy

If a license/config was pre-applied from extras or snapshot, say so clearly in quickstart and do not require optional license export for normal restart.

# Required Artifacts

Inside `Deliverable/<project_name>-image-final/` create:

1. `docker-compose.yml`
2. `docker/entrypoint.sh`
3. `scripts/load-images.sh`
4. `scripts/deploy.sh`
5. `scripts/verify.sh`
6. `scripts/reset.sh`
7. `README_QUICKSTART.md`
8. `images/<project_name>-app.tar` or `.tar.gz`
9. `images/<project_name>-db.tar` when DB image is customized
10. `initdb/` only when DB import remains necessary as a fallback

Optional rebuild artifacts, only when rebuild is intentionally supported:

1. `Dockerfile`
2. `build-context.tar.gz`

Optional source snapshot, only when explicitly requested or when rebuild,
compliance, or source-level troubleshooting requirements make it necessary:

1. `source-initialized.tar.gz`

If rebuild artifacts are absent, do not claim local rebuild support.
Do not include `source-initialized.tar.gz` by default.

# Packaging Procedure

1. confirm baseline deployment is healthy and initialized
2. produce final runtime image(s)
   - include app runtime, source, and startup scripts
   - include initialized state needed for direct login
3. pin image references by digest in compose when practical
4. export image archives with `docker save` into `images/`
5. generate helper scripts
   - `load-images.sh`: load all archives
   - `deploy.sh`: load if needed, then `docker compose up -d`
   - `verify.sh`: health + URL + login path + preset account check
   - `reset.sh`: destructive cleanup for this bundle runtime state
6. if rebuild is offered, also ship and verify:
   - `Dockerfile`
   - `build-context.tar.gz`
   - a local `docker build` validation path
7. include `source-initialized.tar.gz` only when explicitly required for the target deliverable
8. write `README_QUICKSTART.md` with the shortest command sequence and an explicit reset warning
9. include a `Bundle File Map` section listing every shipped item, its purpose, and whether it is required or optional

# Relative Path Rule (Mandatory)

Scripts must use bundle-root relative paths only:

- `./images/`
- `./scripts/`
- `./docker/`

Do not require absolute host paths.

# Re-deploy Verification (Mandatory)

Run a clean simulation from bundle artifacts only:

1. clean previous related runtime resources
2. run `./scripts/load-images.sh`
3. run `./scripts/deploy.sh`
4. verify
   - containers healthy
   - main URL reachable
   - admin/login path reachable
   - preset admin login works, or equivalent authenticated check
5. confirm no additional manual configuration is required

If verification fails, fix artifacts and retry up to 8 times.

# Logging (Mandatory)

- `DP_LOGS/<project_name>-image-final/deploy.log` must record:
  - image build/commit/export commands
  - image load/redeploy commands
  - verification results
- `DP_LOGS/<project_name>-image-final/errors.log` if failures occur
- `DP_LOGS/<project_name>-image-final/summary.md` must include:
  - final commands
  - URLs
  - credentials in masked/safe form
  - packaged initialized-state notes
  - fixes made during packaging verification
  - `Quick Restart Verification` commands
  - required vs optional env notes
  - a from-zero sequence:
    - `./scripts/reset.sh`
    - `./scripts/deploy.sh`
    - `./scripts/verify.sh`
  - a clear reset impact warning

# README Requirements (Mandatory)

`README_QUICKSTART.md` must include:

1. `Bundle File Map`
2. `Quick Start (No Extra Config)`
3. `From Zero Re-Deploy`
4. `Reset Impact Warning`
5. `Rebuild Path` only if rebuild artifacts are shipped

# Acceptance Criteria

- another machine can start from the bundle and run immediately
- no additional project configuration is required for normal restart
- preset admin/login workflow works after deploy
- logs contain verification evidence
- offline re-deploy works from `docker save` archives

# End-of-Run Docker Cleanup (Mandatory)

After this skill ends for one target in standalone mode, clear only Docker resources belonging to this skill's recorded compose project names for:

- `COMPLETED_SUCCESS`
- `COMPLETED_FAILED`
- `TIMED_OUT`
- `ABORTED`

Cleanup scope: containers, networks, volumes, and task-built images with matching `com.docker.compose.project` or `codex.apdv1.cleanup_project` labels.

Do not run host-global cleanup commands such as `docker system prune`, `docker network prune`, `docker volume prune`, `docker image prune -a`, `docker builder prune`, or unfiltered `docker stop` / `docker rm`.

If project cleanup identifiers are missing, skip Docker cleanup and record the missing scope. Do not fall back to global cleanup.

Spawned override:

- if delegated by a parent workflow, do not perform final Docker cleanup unless parent explicitly requests it

# Post-Run Consolidation (Mandatory)

After this skill finishes, call `experience-feedback` once.

- persist only validated, accurate, effective patterns
- do not call it during intermediate retries

Spawned override:

- if delegated under a parent workflow, do not call `experience-feedback` here
- parent performs one-time consolidation after the full pipeline ends
