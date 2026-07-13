#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DRY_RUN=1

if [ "${1:-}" = "--apply" ]; then
  DRY_RUN=0
elif [ "${1:-}" = "--dry-run" ] || [ "${1:-}" = "" ]; then
  DRY_RUN=1
else
  echo "Usage: $0 [--dry-run|--apply]" >&2
  exit 2
fi

paths=(
  "$ROOT_DIR/Deliverable/minio-final"
  "$ROOT_DIR/DP_LOGS/minio-final"
  "$ROOT_DIR/Deliverable/wordpress-final"
  "$ROOT_DIR/DP_LOGS/wordpress-final"
  "$ROOT_DIR/Deliverable/gitea-final"
  "$ROOT_DIR/DP_LOGS/gitea-final"
  "$ROOT_DIR/Deliverable/gitea-1-26-1-final"
  "$ROOT_DIR/DP_LOGS/gitea-1-26-1-final"
  "$ROOT_DIR/Deliverable/metabase-final"
  "$ROOT_DIR/DP_LOGS/metabase-final"
  "$ROOT_DIR/Deliverable/chatwoot-final"
  "$ROOT_DIR/DP_LOGS/chatwoot-final"
  "$ROOT_DIR/Deliverable/zammad-final"
  "$ROOT_DIR/DP_LOGS/zammad-final"
)

projects=(
  minio-final
  wordpress-final
  gitea-final
  gitea-1-26-1-final
  metabase-final
  chatwoot-final
  zammad-final
)

echo "Portable cost target cleanup mode: $([ "$DRY_RUN" -eq 1 ] && echo dry-run || echo apply)"
echo "Workspace: $ROOT_DIR"

for path in "${paths[@]}"; do
  if [ -e "$path" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "would remove path: $path"
    else
      echo "removing path: $path"
      rm -rf "$path"
    fi
  fi
done

if command -v docker >/dev/null 2>&1; then
  for project in "${projects[@]}"; do
    for label in "com.docker.compose.project=${project}" "codex.apdv1.cleanup_project=${project}"; do
      mapfile -t containers < <(docker ps -aq --filter "label=$label" 2>/dev/null || true)
      mapfile -t networks < <(docker network ls -q --filter "label=$label" 2>/dev/null || true)
      mapfile -t volumes < <(docker volume ls -q --filter "label=$label" 2>/dev/null || true)
      mapfile -t images < <(docker image ls -q --filter "label=$label" 2>/dev/null || true)
      if [ "$DRY_RUN" -eq 1 ]; then
        [ "${#containers[@]}" -eq 0 ] || echo "would remove containers for $label: ${containers[*]}"
        [ "${#networks[@]}" -eq 0 ] || echo "would remove networks for $label: ${networks[*]}"
        [ "${#volumes[@]}" -eq 0 ] || echo "would remove volumes for $label: ${volumes[*]}"
        [ "${#images[@]}" -eq 0 ] || echo "would remove images for $label: ${images[*]}"
      else
        [ "${#containers[@]}" -eq 0 ] || docker rm -f "${containers[@]}" >/dev/null 2>&1 || true
        [ "${#networks[@]}" -eq 0 ] || docker network rm "${networks[@]}" >/dev/null 2>&1 || true
        [ "${#volumes[@]}" -eq 0 ] || docker volume rm -f "${volumes[@]}" >/dev/null 2>&1 || true
        [ "${#images[@]}" -eq 0 ] || docker image rm -f "${images[@]}" >/dev/null 2>&1 || true
      fi
    done
  done
else
  echo "docker command unavailable; skipped Docker label cleanup"
fi
