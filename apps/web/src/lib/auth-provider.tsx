"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import {
  ApiRequestError,
  apiRequest,
  getAccessToken,
  refreshAccessToken,
  setAccessToken,
} from "@/lib/api";
import type { Session } from "@/lib/types";

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

type MeResponse = {
  user: Session["user"];
  tenant: Session["tenant"];
  role: Session["role"];
  permissions: string[];
  tenants: Session["tenants"];
  requires_tenant_selection: boolean;
};

type AuthContextValue = {
  status: AuthStatus;
  session: Session | null;
  signIn: (email: string, password: string, tenantId?: string) => Promise<Session>;
  signUp: (email: string, password: string, fullName: string) => Promise<Session>;
  signOut: () => Promise<void>;
  signOutEverywhere: () => Promise<void>;
  createWorkspace: (name: string) => Promise<Session>;
  switchWorkspace: (tenantId: string) => Promise<Session>;
  reload: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [session, setSession] = useState<Session | null>(null);

  const applySession = useCallback((next: Session) => {
    setAccessToken(next.access_token);
    setSession(next);
    setStatus("authenticated");
  }, []);

  const clearSession = useCallback(() => {
    setAccessToken(null);
    setSession(null);
    setStatus("unauthenticated");
  }, []);

  const reload = useCallback(async () => {
    try {
      const me = await apiRequest<MeResponse>("/api/v1/auth/me");
      setSession((current) => {
        if (!current) return current;
        return { ...current, ...me };
      });
      setStatus("authenticated");
    } catch {
      clearSession();
    }
  }, [clearSession]);

  // Silent sign-in: the HttpOnly cookie is the only thing that can prove a
  // previous session, so the first move is always a rotation attempt.
  useEffect(() => {
    let cancelled = false;

    void (async () => {
      const refreshed = await refreshAccessToken();
      if (cancelled) return;
      if (!refreshed) {
        clearSession();
        return;
      }
      try {
        const me = await apiRequest<MeResponse>("/api/v1/auth/me");
        if (cancelled) return;
        setSession({
          access_token: getAccessToken() ?? "",
          token_type: "bearer",
          expires_in: 0,
          ...me,
        });
        setStatus("authenticated");
      } catch {
        if (!cancelled) clearSession();
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [clearSession]);

  const signIn = useCallback(
    async (email: string, password: string, tenantId?: string) => {
      const next = await apiRequest<Session>("/api/v1/auth/login", {
        method: "POST",
        anonymous: true,
        body: { email, password, ...(tenantId ? { tenant_id: tenantId } : {}) },
      });
      applySession(next);
      return next;
    },
    [applySession],
  );

  const signUp = useCallback(
    async (email: string, password: string, fullName: string) => {
      const next = await apiRequest<Session>("/api/v1/auth/register", {
        method: "POST",
        anonymous: true,
        body: { email, password, full_name: fullName },
      });
      applySession(next);
      return next;
    },
    [applySession],
  );

  const signOut = useCallback(async () => {
    try {
      await apiRequest<void>("/api/v1/auth/logout", { method: "POST" });
    } catch (error) {
      if (!(error instanceof ApiRequestError)) throw error;
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const signOutEverywhere = useCallback(async () => {
    try {
      await apiRequest<void>("/api/v1/auth/logout-all", { method: "POST" });
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const createWorkspace = useCallback(
    async (name: string) => {
      const created = await apiRequest<{
        tenant: Session["tenant"];
        role: Session["role"];
        access_token: string;
        expires_in: number;
        permissions: string[];
      }>("/api/v1/tenants", { method: "POST", body: { name } });

      const me = await apiRequest<MeResponse>("/api/v1/auth/me").catch(() => null);
      const next: Session = {
        access_token: created.access_token,
        token_type: "bearer",
        expires_in: created.expires_in,
        user: me?.user ?? (session?.user as Session["user"]),
        tenant: created.tenant,
        role: created.role,
        permissions: created.permissions,
        tenants: me?.tenants ?? session?.tenants ?? [],
        requires_tenant_selection: false,
      };
      applySession(next);
      return next;
    },
    [applySession, session],
  );

  const switchWorkspace = useCallback(
    async (tenantId: string) => {
      const next = await apiRequest<Session>("/api/v1/auth/refresh", {
        method: "POST",
        anonymous: true,
        body: { tenant_id: tenantId },
      });
      applySession(next);
      return next;
    },
    [applySession],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      session,
      signIn,
      signUp,
      signOut,
      signOutEverywhere,
      createWorkspace,
      switchWorkspace,
      reload,
    }),
    [
      status,
      session,
      signIn,
      signUp,
      signOut,
      signOutEverywhere,
      createWorkspace,
      switchWorkspace,
      reload,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
