---
name: post-deploy-portable-bundle
description: After a successful deployment, extract a portable reproducible Docker bundle (configs, scripts, docs, source archive, DB snapshot), then re-deploy from extracted artifacts to verify migration readiness.
---

# Purpose

Run this skill only after the primary official-flow deployment is already successful, verified, and audited. It packages that validated initialized system into a portable bundle that another machine can reproduce with minimal commands.

# Execution Mode (Mandatory)

Supported modes:

1. standalone: this skill owns the full workflow
2. spawned: delegated by `official-flow-deploy` Phase 6

Rules:

- standalone mode follows full task-state, consolidation, and cleanup rules below
- spawned mode handles extraction and migration verification only, then reports to parent
- in spawned mode, parent owns terminal task state, one-time experience consolidation, and final project-scoped Docker cleanup
- do not use this skill to replace the primary deployment workflow
- assume the source system was already proven correct before extraction starts

# Output Locations (Mandatory)

- artifacts: `Deliverable/<project_name>-final/`
- logs: `DP_LOGS/<project_name>-final/`

# Naming Rule (Mandatory)

- use a semantic project-specific `project_name` such as `october`
- do not use abstract names such as `apdv1`, `project-1`, `demo`, `tmp`
- if input is abstract, normalize to the official project name before creating `-final` folders
- when this skill owns task state, persist `project_name` and `cleanup_project_names` so final cleanup can target only this bundle's compose project
- if creating Docker resources outside compose, label them with `codex.apdv1.cleanup_project=<project_name>`

# Experience Precheck (Mandatory)

Before extraction or migration verification:

1. read `.codex/experience/catalog.json`
2. filter to the smallest relevant subcategories under `success_patterns` and/or `failure_avoidance_patterns`
3. query matching index entries with `python3 .codex/scripts/experience_store.py query ...`
4. read only the returned detail records from `.codex/experience/details/...`
5. apply the listed quick checks and avoid matching `anti_pattern` items

Use experience as guidance, not truth. Validate against current logs and runtime. Fix inaccurate entries during post-run consolidation.

# Batch Input Compatibility (Mandatory)

For JSONL-driven upstream tasks:

1. treat `url` as the primary target
2. treat all other keys as `extras`
3. use relevant extras during packaging or verification
4. record consumed extras in final logs/summary

# Task State Tracking (Mandatory)

When this skill owns task state:

1. keep status `RUNNING` during extraction and verification
2. end with `COMPLETED_SUCCESS` or `COMPLETED_FAILED`
3. treat `TIMED_OUT` and `ABORTED` as runner-owned
4. append final result to `.codex/state/task_history.jsonl`

Use `python3 .codex/scripts/update_state.py` when available.

Batch ownership:

- write only agent-owned statuses: `RUNNING`, `COMPLETED_SUCCESS`, `COMPLETED_FAILED`
- never write runner-owned statuses: `INITIALIZING`, `STARTING`, `TIMED_OUT`, `ABORTED`, `IDLE`

Spawned override:

- when delegated by `official-flow-deploy`, do not write terminal task state
- return result and evidence to parent instead

# Bundle Rules (Mandatory)

- keep the bundle compact for cloud storage
- keep only deploy/config/scripts/docs plus compressed source and DB snapshots
- do not keep an expanded `source/` tree in the final output

Required artifacts inside `Deliverable/<project_name>-final/`:

1. `Dockerfile`
2. `docker-compose.yml`
3. `docker/entrypoint.sh`
4. `scripts/deploy.sh`
5. `scripts/verify.sh`
6. `scripts/reset.sh`
7. `README_QUICKSTART.md`
8. `source-initialized.tar.gz`
9. `initdb/00-<db>.sql.gz`

# Extraction Procedure

Source-of-truth rule:

- extract from the already validated primary deployment result
- preserve behavior already proven during the official-flow deployment
- do not redesign the application architecture during bundle extraction unless required to make the bundle reproducible
- do not carry forward a docs-only deployment as the final bundle when the intended target should have been an official runnable application

1. export DB snapshot from the running DB container
   - prefer `mysqldump` or `pg_dump` according to stack
   - gzip the dump
2. archive initialized source
   - include initialized app state and dependencies needed for fast startup
   - optionally exclude non-essential caches/logs
3. generate portable compose and entrypoint
   - deterministic ports
   - env support for sensitive values such as license keys and admin creds
   - idempotent init behavior
4. write `README_QUICKSTART.md`
   - keep required commands first
   - keep optional env exports in a separate block
   - mark optional vars explicitly as `(Optional)`
   - treat license vars such as `OCTOBER_LICENSE_KEY` as optional unless startup strictly requires them
   - if a license key came from extras or snapshot, say restart usually does not need it again
   - include a dedicated from-zero sequence:
     - `./scripts/reset.sh`
     - `./scripts/deploy.sh`
     - `./scripts/verify.sh`
   - state clearly that `reset.sh` is destructive
   - explain what the project is for
   - explain the basic functions expected from the portable bundle
   - list each published URL or endpoint that a user/operator is expected to touch
   - explain the purpose of each URL or endpoint
   - explain the expected behavior for each URL or endpoint, for example HTML page, JSON API, redirect, login page, health response, or expected `404`

# Relative Path Rule (Mandatory)

Scripts must use bundle-root relative paths only:

- `./source-initialized.tar.gz`
- `./initdb/00-<db>.sql.gz`
- temporary extraction target `./source/`

Do not require absolute host paths.

# Registry Fallback Rule (Mandatory)

Generated `./scripts/reset.sh`, `./scripts/deploy.sh`, and `./scripts/verify.sh` must not hard depend on `.codex/scripts/port_registry.py` or registry state files.

Rules:

1. prefer registry coordination when the helper and registry files are available
2. if the registry helper is missing, unreadable, or disabled, scripts must still run by falling back to:
   - caller-provided `APP_PUBLIC_PORT`
   - otherwise saved local state such as `.app_public_port`
   - otherwise a documented deterministic default port or local free-port selection
3. fallback mode must skip registry-specific subcommands gracefully and log that registry coordination was unavailable
4. lack of registry support must not block reset, deploy, or verify for a standalone portable bundle

# Re-deploy Verification (Mandatory)

Run a clean simulation from bundle artifacts only:

1. clean previous related runtime resources
   - stop/remove related containers
   - remove related compose volumes and networks
   - remove related app images when needed for a clean rebuild
   - ensure stale runtime state cannot affect validation
2. ensure `./source/` is absent
3. deploy using only bundle scripts and configs
   - extract `./source-initialized.tar.gz` into `./source/`
   - run compose deployment
4. verify
   - containers healthy
   - main URL reachable
   - admin/login path reachable
   - initialized data present, such as admin user existence
   - the same basic product functions proven during primary verification still work after re-deploy; do not accept a bundle that only restores container health while losing baseline usability
5. remove temporary extracted `./source/` after success

If verification fails, fix artifacts and retry up to 8 times.

# Logging (Mandatory)

- `DP_LOGS/<project_name>-final/deploy.log` must record:
  - extraction commands
  - pre-verification cleanup commands/results
  - re-deploy commands
  - verification results
  - post-verification cleanup result for `./source/`
- `DP_LOGS/<project_name>-final/errors.log` if failures occur
- `DP_LOGS/<project_name>-final/summary.md` must include:
  - final commands
  - URLs
  - credentials
  - fixes made during packaging verification
  - `Quick Restart Verification` commands on success
  - required vs optional env guidance
  - optional license exports in a separate optional snippet
  - a from-zero redeploy snippet
  - a reset impact warning
  - the concrete basic-function verification that proved the portable re-deploy remained usable
  - what the project is for
  - the basic functions that were actually verified after portable re-deploy
  - each verified published URL or endpoint with its purpose and expected behavior

# Acceptance Criteria

- another machine with Docker can restore the same initialized system in 2-3 commands
- bundle includes compressed source and DB snapshots
- docs are explicit and copy-paste ready
- logs contain verification evidence
- final portable directory contains no expanded `source/`
- migrated bundle preserves the same baseline usable functions that passed the primary deployment gate

# End-of-Run Docker Cleanup (Mandatory)

After this skill ends for one URL target in standalone mode, clear only Docker resources belonging to this skill's recorded compose project names for:

- `COMPLETED_SUCCESS`
- `COMPLETED_FAILED`
- `TIMED_OUT`
- `ABORTED`

Cleanup scope: containers, networks, volumes, and task-built images with matching `com.docker.compose.project` or `codex.apdv1.cleanup_project` labels.

Do not run host-global cleanup commands such as `docker system prune`, `docker network prune`, `docker volume prune`, `docker image prune -a`, `docker builder prune`, or unfiltered `docker stop` / `docker rm`.

If project cleanup identifiers are missing, skip Docker cleanup and record the missing scope. Do not fall back to global cleanup.

Spawned override:

- if delegated by `official-flow-deploy`, do not perform final Docker cleanup unless parent explicitly requests it

# Post-Run Consolidation (Mandatory)

After this skill finishes, call `experience-feedback` once.

- persist only validated, accurate, effective patterns
- do not call it during intermediate troubleshooting

Spawned override:

- if delegated under `official-flow-deploy`, do not call `experience-feedback` here
- parent performs one-time consolidation after the full pipeline ends
