import { cn } from "@/lib/utils";

/** "Designed and built by" credit, shown on the sign-in pages and in the app menu. */
export function DeveloperCredit({ className }: { className?: string }) {
  return (
    <p className={cn("text-xs text-ink-muted", className)}>
      تصميم وتطوير{" "}
      <span dir="ltr" lang="en" className="font-medium text-ink">
        Mohamed Ashour
      </span>
    </p>
  );
}
