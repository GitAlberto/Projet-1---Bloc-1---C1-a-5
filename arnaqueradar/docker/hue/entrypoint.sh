#!/bin/sh
set -eu

CONF_FILE="/usr/share/hue/desktop/conf/z-hue.ini"
HUE_DB_ENGINE="${HUE_DB_ENGINE:-postgresql_psycopg2}"
HUE_DB_HOST="${HUE_DB_HOST:-host.docker.internal}"
HUE_DB_PORT="${HUE_DB_PORT:-${PG_PORT:-5432}}"
HUE_DB_NAME="${HUE_DB_NAME:-${PG_DB:-arnaqueradar}}"
HUE_DB_USER="${HUE_DB_USER:-${PG_USER:-postgres}}"
HUE_DB_PASSWORD="${HUE_DB_PASSWORD:-${PG_PASSWORD:-}}"

cat > "$CONF_FILE" <<EOF
[desktop]
  secret_key=arnaqueradar-hue-local-dev
  http_host=0.0.0.0
  http_port=8888
  time_zone=Europe/Paris
  [[database]]
    engine=$HUE_DB_ENGINE
    host=$HUE_DB_HOST
    port=$HUE_DB_PORT
    user=$HUE_DB_USER
    password=$HUE_DB_PASSWORD
    name=$HUE_DB_NAME
    conn_max_age=0
    options={}

[notebook]
  [[interpreters]]
    [[[hive]]]
      name=Hive
      interface=hiveserver2
      options='{"impersonation_enabled": false, "use_sasl": false, "auth_username": "hue"}'

[beeswax]
  hive_server_host=hive
  hive_server_port=10000
  hive_metastore_host=metastore
  hive_metastore_port=9083
  use_sasl=false
  thrift_version=11

[metastore]
  force_hs2_metadata=true
EOF

exec su -s /bin/sh hue -c 'cd /usr/share/hue && ./startup.sh'
