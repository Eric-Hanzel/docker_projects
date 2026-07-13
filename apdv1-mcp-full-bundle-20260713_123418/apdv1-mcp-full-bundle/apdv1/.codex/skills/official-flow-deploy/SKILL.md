---
name: official-flow-deploy
description: Run the official local deployment flow and pass the independent local-run audit gate.
---

# Purpose

Use only for `delivery_mode=local-run`.

Goal:

- get the project running correctly on this machine
- follow the official setup path closely enough to be trusted
- verify real baseline usability
- pass `official-deployment-audit`

# Workflow

1. Resolve a semantic `project_name` and avoid output collisions.
2. Persist:
   - `delivery_mode=local-run`
   - `portable_final_required=false`
   - `project_name=<project_name>`
   - `cleanup_project_names=<compose_project_names>`
3. Discover official docs, setup commands, runtime dependencies, service dependencies, initialization steps, and expected UI/API entrypoints.
4. If the repository contains both docs and runnable apps, deploy the runnable app unless upstream explicitly says docs are the primary product.
5. Execute the official install/init sequence.
6. Remediate failures within the deployment retry budget.
7. Verify:
   - public endpoint status is expected
   - response body has no framework/runtime error signatures
   - critical UI assets are reachable when a UI exists
   - one concrete baseline function works
8. Write local-run outputs.
9. Spawn `primary_deploy_auditor`.
10. Terminal success requires audit `PASS`.

# Outputs

Artifacts:

- `Deliverable/<project_name>/README_DEPLOY.md`
- `Deliverable/<project_name>/docker-compose.yml` when needed
- `Deliverable/<project_name>/Dockerfile` when needed
- `Deliverable/<project_name>/source/` when local source is required

Logs:

- `DP_LOGS/<project_name>/deploy.log`
- `DP_LOGS/<project_name>/summary.md`
- `DP_LOGS/<project_name>/audit_result.json` after audit
- `DP_LOGS/<project_name>/errors.log` when errors occurred

`summary.md` must record the verified URL, expected behavior, and concrete baseline function.

# Completion

Do not build a portable final bundle in this mode. After audit `PASS`, write terminal success, run optional terminal experience feedback, and perform only project-scoped cleanup.
