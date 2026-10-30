import type { LucideIcon } from "lucide-react";

import { Card } from "@/components/ui/card";

export function StatCard({
  label,
  hint,
  icon: Icon,
}: {
  label: string;
  hint: string;
  icon: LucideIcon;
}) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-ink-muted">{label}</p>
          <p className="mt-3 text-3xl font-bold tracking-tight text-ink" aria-label="لا توجد بيانات">
            —
          </p>
          <p className="mt-1 text-[11px] text-ink-muted/80">{hint}</p>
        </div>
        <span
          className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-700"
          aria-hidden="true"
        >
          <Icon className="size-[18px]" />
        </span>
      </div>
    </Card>
  );
}
