# APDv1 Agents

Only independent audit agents are kept in the default workflow.

- `portable_bundle_auditor.toml`: audits `Deliverable/<project>-final/` and `DP_LOGS/<project>-final/`.
- `primary_deploy_auditor.toml`: audits local-run primary deployment outputs.

Portable bundle construction is handled by the main agent using the portable
bundle skill. Optional worker-agent experiments are archived in `.codex-backups/`.
