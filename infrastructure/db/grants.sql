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

        -- Append-only tables. The triggers from 0005/0006 already reject
        -- UPDATE and DELETE for every role; revoking the privileges means a
        -- compromised application cannot even attempt it. Corrections are
        -- compensating ledger rows. See docs/security/AUDIT_LOGGING.md.
        IF to_regclass('public.stock_movements') IS NOT NULL THEN
            EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON stock_movements FROM zain_app';
        END IF;
        IF to_regclass('public.audit_logs') IS NOT NULL THEN
            EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM zain_app';
        END IF;

        -- Units of measure are platform reference data seeded by migration.
        -- They are global (no tenant_id), so the runtime role gets read-only
        -- access rather than the blanket grant above.
        IF to_regclass('public.units_of_measure') IS NOT NULL THEN
            EXECUTE 'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON units_of_measure FROM zain_app';
        END IF;

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
