"use client";

import { Boxes, History, LayoutDashboard, Package, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/lib/auth-provider";
import { cn } from "@/lib/utils";

type NavItem = {
  label: string;
  icon: typeof LayoutDashboard;
  href: string;
  permission?: string;
};

/*
 * Only screens that work today. Modules still being built (sales, purchasing,
 * customers, cash, reports) join this list when they ship, instead of sitting
 * in the menu as disabled promises.
 */
const sections: { label: string; items: NavItem[] }[] = [
  {
    label: "المتجر",
    items: [
      { label: "نظرة عامة", icon: LayoutDashboard, href: "/" },
      { label: "المخزون", icon: Boxes, href: "/inventory", permission: "inventory.read" },
      { label: "المنتجات", icon: Package, href: "/products", permission: "products.read" },
    ],
  },
  {
    label: "الإدارة",
    items: [
      { label: "سجل التعديلات", icon: History, href: "/audit", permission: "audit.read" },
      { label: "الحساب والأمان", icon: Settings, href: "/settings/security" },
    ],
  },
];

function NavLink({
  item,
  active,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  onNavigate?: () => void;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      onClick={onNavigate}
      className={cn(
        "relative flex min-h-10 items-center gap-3 rounded-md px-3 text-sm transition-colors duration-100",
        active
          ? "bg-brand-50 font-semibold text-brand-800"
          : "text-ink-muted hover:bg-surface hover:text-ink",
      )}
    >
      {active ? (
        <span className="absolute inset-y-2 start-0 w-[3px] rounded-full bg-brand-700" aria-hidden="true" />
      ) : null}
      <Icon className={cn("size-[18px] shrink-0", active ? "text-brand-700" : "text-ink-muted")} aria-hidden="true" />
      {item.label}
    </Link>
  );
}

/** Navigation shared by the desktop sidebar and the mobile drawer. */
export function NavLists({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { session } = useAuth();
  const permissions = session?.permissions ?? [];
  const visible = (item: NavItem) => !item.permission || permissions.includes(item.permission);
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-2" aria-label="التنقل الرئيسي">
      {sections.map((section) => {
        const items = section.items.filter(visible);
        if (items.length === 0) return null;
        return (
          <div key={section.label}>
            <p className="px-3 pb-1.5 text-xs font-medium text-ink-muted/80">{section.label}</p>
            <div className="space-y-0.5">
              {items.map((item) => (
                <NavLink key={item.href} item={item} active={isActive(item.href)} onNavigate={onNavigate} />
              ))}
            </div>
          </div>
        );
      })}
    </nav>
  );
}
