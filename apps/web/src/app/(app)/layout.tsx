import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth/auth-guard";
import { AppShell } from "@/components/shell/app-shell";
import { ShellSkeleton } from "@/components/shell/shell-skeleton";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard requireTenant loading={<ShellSkeleton />}>
      <AppShell>{children}</AppShell>
    </AuthGuard>
  );
}
