-- Grants for the runtime (non-superuser) role.
-- Re-run after every migration; safe to run repeatedly.
-- Kept out of Alembic because role names differ per environment
-- (local: zain_app, Neon: the app role you create there).

DO $do$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'zain_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA public TO zain_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO zain_app';
        EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO zain_app';
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
                'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO zain_app';
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
                'GRANT USAGE, SELECT ON SEQUENCES TO zain_app';

        -- Single audited exception to RLS: resolves the workspaces a user may
        -- enter, before any tenant context exists. See
        -- docs/security/TENANT_ISOLATION.md.
        IF to_regprocedure('app_user_tenants(uuid)') IS NOT NULL THEN
            EXECUTE 'REVOKE ALL ON FUNCTION app_user_tenants(uuid) FROM PUBLIC';
            EXECUTE 'GRANT EXECUTE ON FUNCTION app_user_tenants(uuid) TO zain_app';
        END IF;
    ELSE
        RAISE NOTICE 'role zain_app does not exist - skipping grants';
    END IF;
END
$do$;
