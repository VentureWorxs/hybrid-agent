#!/usr/bin/env bash
# Runs one audit sync cycle: local SQLite → Cloudflare D1.
# Designed to be called from crontab every 15 minutes.
#
# Logs to ~/.hybrid-agent/sync.log (rotated at 1 MB by the script itself).

set -euo pipefail

HYBRID_AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${HYBRID_AGENT_DIR}/.venv/bin/python"
ENV_FILE="${HYBRID_AGENT_DIR}/.env"
LOG_FILE="${HOME}/.hybrid-agent/sync.log"
MAX_LOG_BYTES=1048576  # 1 MB

# Load env vars
if [[ -f "${ENV_FILE}" ]]; then
  set -o allexport
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
  set +o allexport
fi

# Rotate log if over 1 MB
if [[ -f "${LOG_FILE}" ]] && (( $(stat -f%z "${LOG_FILE}" 2>/dev/null || echo 0) > MAX_LOG_BYTES )); then
  mv "${LOG_FILE}" "${LOG_FILE}.1"
fi

# Run sync and append timestamped output to log
{
  echo "=== $(date -u +"%Y-%m-%dT%H:%M:%SZ") ==="
  cd "${HYBRID_AGENT_DIR}"
  "${PYTHON}" -m audit.sync_worker --once 2>&1
} >> "${LOG_FILE}"
