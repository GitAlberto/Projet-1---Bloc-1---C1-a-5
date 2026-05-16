#!/bin/sh
set -eu

METASTORE_ROOT="/opt/hive/metastore_volume"

# Initialise explicitement le schema Derby du metastore au premier demarrage.
# L'image apache/hive:4.0.0 ne le fait pas toujours de facon fiable avec un
# volume persistant local, ce qui provoque "Version information not found in
# metastore." puis un restart infini.

mkdir -p "$METASTORE_ROOT"
chown -R hive:hive "$METASTORE_ROOT"
chmod 775 "$METASTORE_ROOT"

if su -s /bin/sh hive -c "cd '$METASTORE_ROOT' && /opt/hive/bin/schematool -dbType derby -info >/tmp/hive-schema-info.log 2>&1"; then
  echo "Hive metastore schema already present."
else
  echo "Hive metastore schema missing, running initSchema..."
  su -s /bin/sh hive -c "cd '$METASTORE_ROOT' && /opt/hive/bin/schematool -dbType derby -initSchema"
fi

export IS_RESUME=true
exec su -m -s /bin/sh hive -c "cd '$METASTORE_ROOT' && /entrypoint.sh"
