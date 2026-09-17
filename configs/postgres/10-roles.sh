#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
 -v db="$POSTGRES_DB" -v migrator_pw="$(cat /run/secrets/pg_migrator_password)" \
 -v app_pw="$(cat /run/secrets/pg_app_password)" <<'SQL'
CREATE ROLE fm_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'migrator_pw';
CREATE ROLE fm_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_pw';
ALTER DATABASE :"db" OWNER TO fm_migrator;
ALTER SCHEMA public OWNER TO fm_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO fm_app;
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO fm_app;
SQL

