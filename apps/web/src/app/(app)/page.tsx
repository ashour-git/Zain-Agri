import { BarChart3, Info, Package, Receipt, ShoppingCart, Users, Wallet } from "lucide-react";

import { StatCard } from "@/components/dashboard/stat-card";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const stats = [
  { label: "مبيعات اليوم", hint: "تُحسب من فواتير البيع", icon: Receipt },
  { label: "قيمة المخزون", hint: "تُحسب من حركة المخزون", icon: Package },
  { label: "أرصدة العملاء", hint: "تُحسب من المدفوعات والآجَل", icon: Users },
  { label: "رصيد الخزينة", hint: "تُحسب من الحركات المالية", icon: Wallet },
];

const modules = [
  {
    title: "نقطة البيع",
    description: "بيع سريع مع بحث فوري عن المنتج وطباعة الفاتورة.",
    icon: ShoppingCart,
  },
  {
    title: "المخزون والدفعات",
    description: "حركة مخزون غير قابلة للتعديل مع تتبع الدفعات وتواريخ الصلاحية.",
    icon: Package,
  },
  {
    title: "المبيعات والمرتجعات",
    description: "فواتير، تحصيل جزئي، آجَل، وإدارة المرتجعات.",
    icon: Receipt,
  },
  {
    title: "العملاء والموردون",
    description: "أرصدة، كشوف حساب، وحدود الائتمان.",
    icon: Users,
  },
  {
    title: "الخزينة والمصروفات",
    description: "حركات نقدية، مصروفات، وربحية قابلة للتتبع.",
    icon: Wallet,
  },
  {
    title: "التقارير والتحليلات",
    description: "مبيعات، أرباح، ومؤشرات أداء المتجر.",
    icon: BarChart3,
  },
];

export default function DashboardPage() {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 px-5 py-8 sm:px-8">
      <section>
        <Card className="relative overflow-hidden border-0 bg-gradient-to-l from-brand-950 via-brand-900 to-brand-800 text-white">
          <div
            className="pointer-events-none absolute -left-16 -top-20 size-64 rounded-full bg-accent-400/10 blur-2xl"
            aria-hidden="true"
          />
          <div className="relative flex flex-col gap-5 p-6 sm:flex-row sm:items-center sm:justify-between sm:p-8">
            <div className="max-w-xl space-y-2">
              <Badge variant="lime" className="bg-accent-400/15 text-accent-300 ring-accent-400/30">
                Sprint 01 — الأساس
              </Badge>
              <h2 className="text-xl font-bold sm:text-2xl">أهلاً بك في ZAIN AGRI</h2>
              <p className="text-sm leading-relaxed text-brand-100/90">
                تم تجهيز هيكل التطبيق وقاعدة البيانات ونظام تعدد المتاجر. الوحدات التشغيلية
                ستُبنى تدريجياً، وستظهر أرقامك الحقيقية هنا بعد ربطها.
              </p>
            </div>
            <div className="rounded-xl bg-white/5 px-4 py-3 text-xs leading-relaxed text-brand-100 ring-1 ring-inset ring-white/10">
              <p className="font-semibold text-white">لا توجد بيانات بعد</p>
              <p className="mt-1 text-brand-200">هذه الواجهة لا تعرض أرقاماً وهمية.</p>
            </div>
          </div>
        </Card>
      </section>

      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <Info className="size-4 text-brand-600" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-ink">مؤشرات المتجر</h2>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {stats.map((stat) => (
            <StatCard key={stat.label} label={stat.label} hint={stat.hint} icon={stat.icon} />
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-ink">الوحدات القادمة</h2>
          <span className="text-[11px] text-ink-muted">جاهزة للتنفيذ بعد Sprint 01</span>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {modules.map((module) => {
            const Icon = module.icon;
            return (
              <Card key={module.title} className="transition-shadow hover:shadow-md">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <span
                      className="grid size-9 place-items-center rounded-lg bg-brand-50 text-brand-700"
                      aria-hidden="true"
                    >
                      <Icon className="size-4" />
                    </span>
                    <Badge variant="brand">قريباً</Badge>
                  </div>
                  <CardTitle className="pt-2">{module.title}</CardTitle>
                  <CardDescription className="leading-relaxed">{module.description}</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="h-1 w-full overflow-hidden rounded-full bg-surface">
                    <div className="h-full w-0 rounded-full bg-accent-400" />
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>
    </div>
  );
}
