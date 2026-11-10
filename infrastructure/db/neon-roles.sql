-- One-time setup for a Neon (or any managed PostgreSQL) database.
-- Run in Neon's SQL Editor as the project owner role (e.g. neondb_owner).
--
-- 1. Replace CHANGE-ME with a long random password (store it in your password
--    manager; it goes into the API's DATABASE_URL).
-- 2. Run this file once. Then run apps/api/migrate.py, which creates the
--    tables (as the owner) and grants zain_app exactly what it needs.
--
-- If Neon refuses CREATE ROLE here, create a role named zain_app in the Neon
-- console (Roles → New role) and run only the ALTER ROLE line below.

DO $do$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'zain_app') THEN
        CREATE ROLE zain_app LOGIN PASSWORD 'CHANGE-ME';
    END IF;
END
$do$;

-- Never a superuser, never BYPASSRLS: otherwise the tenancy policies are decorative.
ALTER ROLE zain_app NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
