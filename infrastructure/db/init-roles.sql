-- Local development bootstrap. Run as the cluster superuser (zain).
-- Creates the runtime role and the databases. Idempotent.

DO $do$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'zain_app') THEN
        CREATE ROLE zain_app LOGIN PASSWORD 'zain_dev_only';
    END IF;
END
$do$;

-- Never a superuser, never BYPASSRLS: otherwise the tenancy policies are decorative.
ALTER ROLE zain_app NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
