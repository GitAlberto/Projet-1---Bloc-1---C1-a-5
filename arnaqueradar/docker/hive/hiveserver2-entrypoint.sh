#!/bin/bash
set -euo pipefail

METASTORE_HOST="${HIVE_METASTORE_HOST:-metastore}"
METASTORE_PORT="${HIVE_METASTORE_PORT:-9083}"
MAX_ATTEMPTS="${HIVE_METASTORE_WAIT_ATTEMPTS:-60}"
SLEEP_SECONDS="${HIVE_METASTORE_WAIT_SECONDS:-2}"

echo "Waiting for Hive Metastore at ${METASTORE_HOST}:${METASTORE_PORT}..."

for ((attempt=1; attempt<=MAX_ATTEMPTS; attempt++)); do
  if echo >"/dev/tcp/${METASTORE_HOST}/${METASTORE_PORT}" 2>/dev/null; then
    echo "Hive Metastore is reachable."
    exec /entrypoint.sh
  fi

  echo "Metastore not ready yet (${attempt}/${MAX_ATTEMPTS}), retry in ${SLEEP_SECONDS}s..."
  sleep "${SLEEP_SECONDS}"
done

echo "Hive Metastore did not become reachable in time."
exit 1
