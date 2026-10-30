import {
  BarChart3,
  Boxes,
  LayoutDashboard,
  Package,
  Receipt,
  Settings,
  ShoppingCart,
  Sprout,
  Truck,
  Users,
  Wallet,
} from "lucide-react";

import { BrandMark, BrandWordmark } from "@/components/brand";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type NavItem = {
  label: string;
  icon: typeof LayoutDashboard;
  active?: boolean;
  soon?: boolean;
};

const primaryNav: NavItem[] = [
  { label: "لوحة التحكم", icon: LayoutDashboard, active: true },
  { label: "نقطة البيع", icon: ShoppingCart, soon: true },
  { label: "المخزون", icon: Boxes, soon: true },
  { label: "المنتجات", icon: Package, soon: true },
  { label: "المبيعات", icon: Receipt, soon: true },
  { label: "المشتريات", icon: Truck, soon: true },
  { label: "العملاء", icon: Users, soon: true },
  { label: "الخزينة", icon: Wallet, soon: true },
  { label: "التقارير", icon: BarChart3, soon: true },
];

const secondaryNav: NavItem[] = [{ label: "الإعدادات", icon: Settings, soon: true }];

function NavLink({ item }: { item: NavItem }) {
  const Icon = item.icon;

  return (
    <a
      href={item.active ? "/" : "#"}
      aria-current={item.active ? "page" : undefined}
      aria-disabled={item.soon ? true : undefined}
      className={cn(
        "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors",
        item.active
          ? "bg-white/10 font-semibold text-white"
          : "text-brand-100/80 hover:bg-white/5 hover:text-white",
        item.soon && "cursor-default",
      )}
    >
      <span
        className={cn(
          "absolute inset-y-2 -right-3 w-1 rounded-full",
          item.active ? "bg-accent-400" : "bg-transparent",
        )}
        aria-hidden="true"
      />
      <Icon
        className={cn("size-[18px] shrink-0", item.active ? "text-accent-400" : "text-brand-300")}
        aria-hidden="true"
      />
      <span className="flex-1">{item.label}</span>
      {item.soon ? (
        <span className="rounded-md bg-white/5 px-1.5 py-0.5 text-[10px] text-brand-200">
          قريباً
        </span>
      ) : null}
    </a>
  );
}

export function Sidebar() {
  return (
    <aside className="sticky top-0 hidden h-dvh w-72 shrink-0 flex-col bg-brand-950 lg:flex">
      <div className="flex items-center gap-3 px-5 py-6">
        <BrandMark />
        <BrandWordmark />
      </div>

      <div className="mx-5 mb-4 flex items-center gap-2 rounded-xl bg-white/5 px-3 py-2.5 ring-1 ring-inset ring-white/10">
        <Sprout className="size-4 text-accent-400" aria-hidden="true" />
        <span className="text-xs text-brand-100">فرع رئيسي</span>
        <Badge variant="lime" className="ms-auto bg-accent-400/15 text-accent-300 ring-accent-400/30">
          تجريبي
        </Badge>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-5 pb-4" aria-label="التنقل الرئيسي">
        {primaryNav.map((item) => (
          <NavLink key={item.label} item={item} />
        ))}
      </nav>

      <div className="space-y-1 border-t border-white/10 px-5 py-4">
        {secondaryNav.map((item) => (
          <NavLink key={item.label} item={item} />
        ))}
        <p className="pt-3 text-[11px] leading-relaxed text-brand-300/70">
          الإصدار 0.1.0 — أساس Sprint 01
        </p>
      </div>
    </aside>
  );
}
