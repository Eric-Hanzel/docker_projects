---
name: official-flow-deploy
description: Execute the official installation flow correctly, verify and audit it, then extract a portable Docker bundle from the validated result
---

# Project Folder Rules (Mandatory)

- create `Deliverable/<project_name>/` and `DP_LOGS/<project_name>/` at task start
- write deployment artifacts only under `Deliverable/<project_name>/`
- write deploy/error/summary logs only under `DP_LOGS/<project_name>/`
- do not write project outputs directly to root-level `Deliverable/` or `DP_LOGS/`

# Stable Project Name Rule (Mandatory)

Choose `project_name` once and keep it stable for the entire task.

Priority:

1. official project/repo/framework name from docs or source URL
2. explicit user-provided name
3. repository directory name only if descriptive

Rules:

- avoid abstract names such as `apdv1`, `project-1`, `test`, `demo`, `tmp`, `repo`
- if the repo directory name is abstract, replace it with the official project name
- normalize for filesystem stability:
  - lowercase
  - replace spaces with `-`
  - keep only `a-z`, `0-9`, `-`, `_`
- never generate random or time-based names
- persist the resolved name in task state as soon as it is known:
  - `project_name=<project_name>`
  - `cleanup_project_names=<primary_compose_project>[,<final_compose_project>]`
- keep compose project names aligned with the resolved output names so the runner can clean only this task's Docker resources
- if creating Docker resources outside compose, label them with `codex.apdv1.cleanup_project=<project_name>`

# Source Placement (Conditional)

- use `Deliverable/<project_name>/source/` when the official flow, local build/patching, verification, or reproducible extraction depends on local source
- if the source comes from git and is needed, clone directly into that path
- if the source already exists locally and is needed, copy or sync only deploy-relevant contents there
- for official image-first deployments that do not depend on local source checkout, `Deliverable/<project_name>/source/` is optional and must not delay audit or success classification
- generate deployment files in `Deliverable/<project_name>/`

# Official-Flow First Principle (Mandatory)

This skill has two different goals, in this order:

1. complete a correct deployment that follows the official installation flow
2. only after that succeeds, extract the final portable Docker deliverable

Rules:

- Phase 1 through the official deployment audit are not "final bundle Dockerization"
- use the least additional abstraction needed to execute the official docs correctly
- Docker may be used early as a runtime carrier or dependency carrier, but not as the primary goal
- do not shape the first deployment around the final portable bundle structure
- do not treat an early deploy container layout as the final deliverable by default

# Business-App Target Rule (Mandatory)

If the upstream repository is a framework, platform, starter ecosystem, or mixed monorepo:

- do not default to deploying the docs or marketing site if an official runnable application also exists
- explicitly inspect whether the repository ships an official app, starter, admin panel, operator console, or example app that better represents real product functionality
- prefer the official runnable application as the deployment target whenever it exists
- treat a docs-only deployment as insufficient unless the upstream is genuinely docs-only or official guidance makes the docs site the primary deployment target

# Batch Input Compatibility (Mandatory)

For JSONL batch records:

- required: `url`
- optional: any additional keys

Rules:

1. preserve all extra keys as `extras`
2. use known extras when relevant, for example `license_key`
3. record consumed extras in `deploy.log` and `summary.md`

# Task State Tracking (Mandatory)

Use `.codex/state/task_state.json` to mark execution boundaries:

1. at actual task start, set `status=RUNNING`
2. end with `COMPLETED_SUCCESS`, `COMPLETED_CONDITIONAL_SUCCESS`, or `COMPLETED_FAILED`
3. treat `TIMED_OUT` and `ABORTED` as runner-owned
4. append final result to `.codex/state/task_history.jsonl`

Use `python3 .codex/scripts/update_state.py` when available.

Batch ownership:

- write only agent-owned statuses: `RUNNING`, `COMPLETED_SUCCESS`, `COMPLETED_CONDITIONAL_SUCCESS`, `COMPLETED_FAILED`
- never write runner-owned statuses: `INITIALIZING`, `STARTING`, `TIMED_OUT`, `ABORTED`, `IDLE`

# Logging Rules (Mandatory)

- create `DP_LOGS/<project_name>/deploy.log` before deployment commands
- log commands, stdout/stderr or summarized output, failures, root causes, fixes, and retries
- create `DP_LOGS/<project_name>/errors.log` if errors occur
- create `DP_LOGS/<project_name>/summary.md` at completion
- on success, `summary.md` must include copy-paste `Quick Restart Verification` commands
- on success, `summary.md` must also record the concrete basic-function verification that proved the initialized deployment was usable, not merely healthy

# Experience Precheck (Mandatory)

Before Phase 1:

1. read `.codex/experience/catalog.json`
2. choose the smallest relevant subcategories under `success_patterns` and/or `failure_avoidance_patterns`
3. query matching index entries with `python3 .codex/scripts/experience_store.py query ...`
4. read only the returned detail records from `.codex/experience/details/...`
5. run listed preventive checks before risky actions and avoid matching `anti_pattern` items

Use experience as guidance, not guaranteed truth. Validate against current docs, logs, and runtime. Fix inaccurate entries during post-run consolidation.

# Phase 1: Fetch Project

- if `url` is a git repo and the official flow needs local source, clone into `Deliverable/<project_name>/source/`
- if `url` is documentation, extract installation steps from it
- if the official flow is image-based, document why source checkout is unnecessary and proceed without blocking on `source/`

# Phase 2: Documentation Analysis

Extract:

- required runtime: Node, Python, PHP, Java, etc.
- install commands such as `npm install`, `pip install`, `composer install`
- required services such as DB and Redis
- initialization steps such as migrations, seed, and frontend build

# Phase 3: Stack Detection

If docs are insufficient, infer from source:

- `package.json` => Node
- `requirements.txt` => Python
- `composer.json` => PHP/Laravel
- `go.mod` => Go

# Phase 4: Official Deployment Planning

Decide how to execute the official install flow with minimal extra machinery.

Allowed patterns:

- host-native execution if the environment already satisfies the docs
- minimal dependency containers, for example DB/Redis only
- minimal runtime containers when host-native execution is impractical

Rules:

- prefer the plan that keeps the deployment behavior closest to the official docs
- avoid writing final-bundle-style deploy/reset/verify wrappers in this phase
- only generate Dockerfile / `docker-compose.yml` now if they are necessary to perform the official deployment itself
- if containers are needed, keep them focused on executing the official flow, not on final deliverable polish

When containerized runtime is necessary, port coordination is mandatory:

- use `.codex/scripts/port_registry.py` with `.codex/state/port_registry.json`
- if `APP_PUBLIC_PORT` is unset, pick one via `choose --preferred 18080`
- claim the selected port before publishing the service
- activate the claim on success
- release the claim on failure/reset with `release` or `release-project`
- persist auto-selected port into a local state file such as `.app_public_port` so verification reads the right port when env is unset

Portable-script fallback rule:

- any generated `./scripts/reset.sh`, `./scripts/deploy.sh`, and `./scripts/verify.sh` must not hard depend on the registry helper or registry state files
- if the registry helper is unavailable, unreadable, or disabled, scripts must fall back to:
  - `APP_PUBLIC_PORT` from the caller when provided
  - otherwise a saved local port file such as `.app_public_port`
  - otherwise a documented deterministic default or local free-port selection
- scripts must skip registry-specific subcommands gracefully in fallback mode and continue with explicit log messages

# Phase 4.5: Official Deployment and Initialization (Mandatory)

Run what the project needs:

- dependency install
- migrations
- seed data
- frontend build if needed

If the project supports users:

- create one admin account
- create one normal user account if supported
- prefer deterministic default credentials unless docs require otherwise
- write created credentials to `Deliverable/<project_name>/README_DEPLOY.md`

# Phase 5: Primary Deployment Auto-Fix Loop

If verification fails:

1. read logs
2. classify the issue, for example dependency missing, wrong command, or missing service
3. fix it by updating Dockerfile, adding services, or changing commands
4. retry

Maximum: 8 attempts.

Verification rule:

- do not accept container health, open ports, or root HTTP 200 alone as success
- require evidence that the initialized deployment's basic functions are usable, for example one minimal user flow, operator flow, CRUD/API action, job run, or route-specific content check that matches the product's normal baseline behavior
- if the app is up but those basic functions fail, keep the deployment in the auto-fix loop

Patience rules:

- if image pulls, package downloads, migrations, or first-run asset builds are still producing output, wait instead of interrupting for speculative retries
- treat slow progress differently from a no-progress stall
- once the primary deployment audit succeeds and portable extraction starts, keep waiting for delegated bundle/audit completion inside the task budget

# Phase 5.5: Primary Deployment Verification And Audit Gate With Subagent (Mandatory)

Before any final bundle extraction:

1. spawn exactly one `primary_deploy_auditor`
2. require it to use `official-deployment-audit`
3. audit:
   - `Deliverable/<project_name>/`
   - `DP_LOGS/<project_name>/`
   - live primary deployment verification evidence
4. wait for the strict result:
   - `PASS`
   - `FAIL` with remediation items
5. if `FAIL`, parent remediates and re-runs audit
6. maximum 3 audit attempts

Audit gate rules:

- do not continue to portable extraction until this gate passes
- if the deployment only works through ad hoc shortcuts that bypass the official flow, fix it before continuing
- treat missing evidence for basic-function usability after initialization as a blocking audit failure
- treat a docs-only or marketing-only deployment as a blocking failure when the upstream project also provides an official runnable application
- keep the task in `RUNNING` during the audit loop
- only parent writes terminal task state
- the audit subagent returns evidence and verdict only
- persist:
  - `primary_audit_gate_required=phase5_5`
  - `primary_audit_attempts=<1..3>`
  - `primary_audit_verdict=PASS|FAIL`
  - `primary_audit_result_file=DP_LOGS/<project_name>/audit_result.json`

# Output

Required outputs:

- `Deliverable/<project_name>/source/` when local source is required by the validated official flow or final reproducibility path
- `Deliverable/<project_name>/Dockerfile`
- `Deliverable/<project_name>/docker-compose.yml` when multi-service
- `Deliverable/<project_name>/.env.example` when needed
- `Deliverable/<project_name>/README_DEPLOY.md`
- `DP_LOGS/<project_name>/deploy.log`
- `DP_LOGS/<project_name>/errors.log` if errors occurred
- `DP_LOGS/<project_name>/summary.md`

`README_DEPLOY.md` should include run commands, service URL, and created credentials when applicable.
`README_DEPLOY.md` must also include:

- what the project is for
- the basic functions expected from the validated deployment
- each published URL or endpoint that a user/operator is expected to touch
- the purpose of each URL or endpoint
- the expected behavior for each URL or endpoint, for example HTML page, JSON API, redirect, login page, health response, or expected `404`

`summary.md` must:

- include `Quick Restart Verification` commands on success
- label env exports as required or optional
- keep optional license exports such as `OCTOBER_LICENSE_KEY` separate from required flow
- describe the verified primary deployment path that was actually used
- explicitly state when the deployment was validated from official images without a local source snapshot
- summarize what the project is for
- summarize the basic functions that were actually verified
- list each verified published URL or endpoint with its purpose and expected behavior

Primary deployment outputs should reflect the official-flow deployment result. They do not need to be the final portable bundle shape.

# Phase 6: Post-Deploy Portable Extraction (Mandatory)

After the official deployment succeeds, Phase 5 remediation is complete, and Phase 5.5 audit passes:

1. spawn exactly one `portable_bundle_worker` subagent
2. require it to use `post-deploy-portable-bundle`
3. pass `project_name`, target `url`, and parsed `extras` for traceability
4. wait for the result before continuing
5. if the subagent fails, treat Phase 6 as failed
6. do not end the workflow at first successful official deployment; Phase 6 is mandatory

Ownership:

- parent owns terminal task state, one-time `experience-feedback`, and end-of-task project-scoped Docker cleanup
- child owns only bundle extraction, migration verification retries, and Phase 6 logs/artifacts

# Phase 6 Audit Gate With Subagent (Mandatory)

After Phase 6 extraction succeeds:

1. spawn exactly one `portable_bundle_auditor`
2. require it to use `portable-bundle-audit`
3. audit:
   - final bundle correctness and completeness
   - final logs and verification evidence
4. wait for the strict result:
   - `PASS`
   - `FAIL` with remediation items
5. if `FAIL`, remediate and re-run audit
6. maximum 3 audit attempts

Audit control:

- maintain `audit_attempt` starting at `1`
- persist:
  - `audit_gate_required=phase6`
  - `audit_attempts=<1..3>`
  - `audit_verdict=PASS|FAIL`
  - `audit_result_file=DP_LOGS/<project_name>-final/audit_result.json`
- on `PASS`, `audit_verdict` must be `PASS`
- on final failure after attempt 3, set `audit_verdict=FAIL` and end with `COMPLETED_FAILED`
- on each failed audit, log findings summary, remediation taken, and next attempt

Ownership:

- only parent writes final terminal status
- subagents must not write terminal task state
- parent must not emit `COMPLETED_SUCCESS` until audit passes
- keep task status `RUNNING` during the Phase 6 audit loop
- auditor owns findings/evidence only, not cleanup, experience consolidation, or final completion decisions

# Phase 7: Experience Consolidation (Mandatory)

After the full workflow ends, either by success after audit pass or by final failure:

1. call `experience-feedback` once
2. extract current-run success/failure patterns
3. merge them into:
   - `.codex/experience/catalog.json`
   - `.codex/experience/index/...`
   - `.codex/experience/details/...`

Persist only accurate, validated, useful patterns. Do not run this phase during intermediate retries.

# End-of-Task Docker Cleanup (Mandatory)

After each URL target ends, clear only Docker resources belonging to this task's recorded compose project names for:

- `COMPLETED_SUCCESS`
- `COMPLETED_FAILED`
- `TIMED_OUT`
- `ABORTED`

Cleanup scope:

- containers
- networks
- volumes
- resources with matching `com.docker.compose.project` or `codex.apdv1.cleanup_project` labels

Do not run host-global cleanup commands such as `docker system prune`, `docker network prune`, `docker volume prune`, `docker image prune -a`, `docker builder prune`, or unfiltered `docker stop` / `docker rm`.

If project cleanup identifiers are missing, skip Docker cleanup and record the missing scope. Do not fall back to global cleanup.

Record cleanup commands/results in `deploy.log` and summarize cleanup in `summary.md`.
