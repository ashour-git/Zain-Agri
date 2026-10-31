export type MembershipRole = "owner" | "manager" | "cashier" | "inventory_manager";
export type TenantStatus = "active" | "suspended";
export type MembershipStatus = "active" | "invited" | "suspended";

export type User = {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  email_verified_at: string | null;
  created_at: string;
};

export type Tenant = {
  id: string;
  name: string;
  slug: string;
  status: TenantStatus;
  created_at: string;
};

export type TenantMembership = {
  id: string;
  name: string;
  slug: string;
  status: TenantStatus;
  role: MembershipRole;
  membership_status: MembershipStatus;
};

export type Session = {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
  tenant: Tenant | null;
  role: MembershipRole | null;
  permissions: string[];
  tenants: TenantMembership[];
  requires_tenant_selection: boolean;
};

export type SessionInfo = {
  id: string;
  created_at: string;
  expires_at: string;
  user_agent: string | null;
  is_current: boolean;
};

export type TenantMember = {
  membership_id: string;
  user_id: string;
  email: string;
  full_name: string;
  role: MembershipRole;
  status: MembershipStatus;
  is_active: boolean;
  created_at: string;
};

export const ROLE_LABELS: Record<MembershipRole, string> = {
  owner: "مالك",
  manager: "مدير",
  cashier: "كاشير",
  inventory_manager: "مسؤول مخزون",
};

export const PERMISSION_LABELS: Record<string, string> = {
  "tenant.settings.manage": "إدارة إعدادات المتجر",
  "users.manage": "إدارة المستخدمين",
  "finance.view": "الاطلاع على البيانات المالية",
  "inventory.manage": "إدارة المخزون",
  "purchases.manage": "إدارة المشتريات",
  "sales.operate": "تشغيل المبيعات",
  "sales.refund": "تنفيذ المرتجعات",
  "reports.view": "عرض التقارير",
};
