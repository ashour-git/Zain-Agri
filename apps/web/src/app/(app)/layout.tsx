import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth/auth-guard";
import { AppShell } from "@/components/shell/app-shell";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard requireTenant>
      <AppShell>{children}</AppShell>
    </AuthGuard>
  );
}
