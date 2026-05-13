import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

try:
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        dbname="postgres",
        user="postgres",
        password="Mot de passe",
        connect_timeout=5,
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    # Vérifier si la base existe déjà
    cur.execute("SELECT 1 FROM pg_database WHERE datname='arnaqueradar';")
    if cur.fetchone():
        print("Base arnaqueradar : deja existante.")
    else:
        cur.execute("CREATE DATABASE arnaqueradar OWNER postgres ENCODING 'UTF8';")
        print("Base arnaqueradar : CREEE avec succes.")

    conn.close()

    # Vérifier la connexion à la nouvelle base
    conn2 = psycopg2.connect(
        host="localhost",
        port=5432,
        dbname="arnaqueradar",
        user="postgres",
        password="Mot de passe",
        connect_timeout=5,
    )
    print("Connexion a arnaqueradar : OK")
    conn2.close()

except Exception as e:
    print(type(e).__name__, ":", str(e)[:300])
