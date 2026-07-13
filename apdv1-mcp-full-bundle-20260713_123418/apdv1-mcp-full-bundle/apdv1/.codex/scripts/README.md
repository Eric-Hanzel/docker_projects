# APDv1 Scripts

Only runtime scripts used by the current deployment workflow are kept here.

- `update_state.py`: atomic task state/history writer.
- `observe_rollout.py`: captures Codex exec rollout logs for the shell batch runner.
- `port_registry.py`: optional shared port coordination.
- `docker_image_cache_policy.py`: safe Docker image cache reporting/cleanup policy.
- `experience_store.py`: query and merge the compact experience store.
- `validate_final_outputs.py`: final portable bundle contract check used by runners.
- `render_state_status.py`: writes `.codex/state/STATUS.md` for human inspection.

## Final Output Validation

```bash
python3 .codex/scripts/validate_final_outputs.py <project_name>
python3 .codex/scripts/validate_final_outputs.py <project_name> \
  --terminal-status COMPLETED_SUCCESS \
  --require-audit \
  --json
python3 .codex/scripts/validate_final_outputs.py <project_name> \
  --delivery-style image \
  --terminal-status COMPLETED_SUCCESS \
  --require-audit \
  --json
```

Batch runners use the strict form before accepting successful portable tasks.

## Archived Utilities

Optional diagnostics and pre-refactor files were moved to `.codex-backups/`.
Restore them from the latest `cleanup-*` backup only if needed for one-off
maintenance.
