#!/bin/sh
set -eu

# Reprise automatique : si le Derby metastore existe deja, on evite
# de relancer l'initialisation du schema a chaque restart.
if [ -f /opt/hive/metastore_db/service.properties ]; then
  export IS_RESUME=true
else
  unset IS_RESUME || true
fi

exec /entrypoint.sh
