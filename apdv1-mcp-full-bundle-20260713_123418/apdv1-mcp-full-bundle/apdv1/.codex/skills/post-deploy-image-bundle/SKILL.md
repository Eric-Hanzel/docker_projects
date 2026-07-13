---
name: post-deploy-image-bundle
description: Build and verify an image-based migration deliverable when explicitly requested.
---

# Purpose

Use only when the target or user request asks for an image-based, image archive,
offline image, or ready-to-load migration deliverable.

This is the second final delivery style:

- non-image portable bundle: `post-deploy-portable-bundle`
- image-based bundle: `post-deploy-image-bundle`

Default batch delivery remains the non-image portable bundle unless the input
explicitly requests image delivery.

# Output Locations

- artifacts: `Deliverable/<project_name>-image-final/`
- logs: `DP_LOGS/<project_name>-image-final/`

# Goal

Another machine can load or build the packaged images and start the initialized
system with the included compose/scripts, without re-running full upstream setup.

# Required Artifacts

Inside `Deliverable/<project_name>-image-final/`:

- `README_QUICKSTART.md`
- `docker-compose.yml`
- `scripts/deploy.sh`
- `scripts/verify.sh`
- `scripts/reset.sh`
- one of:
  - `images/*.tar` or `images/*.tar.gz` for exported Docker images
  - `image-build-context.tar.gz` when local rebuild is the intended image path
- `runtime-config-initialized.tar.gz`
- `initdb/00-<db>.sql.gz` or `initdb/README_NO_DB.md`

Logs:

- `DP_LOGS/<project_name>-image-final/preflight.json`
- `DP_LOGS/<project_name>-image-final/preflight.md`
- `DP_LOGS/<project_name>-image-final/deploy.log`
- `DP_LOGS/<project_name>-image-final/verification_result.json`
- `DP_LOGS/<project_name>-image-final/summary.md`
- `errors.log` when errors occurred

# Workflow

1. Build or identify the initialized runtime images.
2. Label task-built images with `codex.apdv1.cleanup_project=<project_name>`.
3. Export images or package the reproducible image build context.
4. Package runtime config and DB/no-DB state.
5. Generate reset/deploy/verify scripts that work outside APDv1.
6. Validate from the image bundle only:
   - load or rebuild image artifacts
   - start compose
   - verify public URL and baseline function
7. Remove local runtime containers/images only by task labels or compose project.

# README_QUICKSTART Contract

Include:

- required quick start commands
- image load/build instructions
- optional environment variables
- from-zero redeploy sequence: `reset.sh`, `deploy.sh`, `verify.sh`
- destructive reset warning
- project purpose
- expected basic functions
- URLs and expected behavior
- credentials with user-provided secrets masked

# Verification Contract

`verification_result.json` must prove:

- image load/build path works
- compose deployment starts from packaged image artifacts
- expected public endpoint succeeds
- response body has no framework/runtime error signature
- one concrete baseline product function works after redeploy

Do not accept a bundle that only proves image import or container health.

# Audit

Use the same independent final audit principle as portable delivery. If an
image-specific auditor is not present, the parent/auditor must still inspect
only:

- `Deliverable/<project_name>-image-final/`
- `DP_LOGS/<project_name>-image-final/`

Terminal success requires structured audit evidence with `PASS` or valid
`CONDITIONAL`.
