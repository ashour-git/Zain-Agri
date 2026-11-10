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
  "products.read": "عرض المنتجات",
  "products.create": "إضافة منتجات",
  "products.update": "تعديل المنتجات",
  "products.archive": "أرشفة المنتجات واستعادتها",
  "categories.manage": "إدارة التصنيفات والعلامات",
  "inventory.read": "عرض المخزون",
  "inventory.adjust": "تسوية المخزون",
  "inventory.view_cost": "الاطلاع على التكلفة",
  "batches.manage": "إدارة دفعات المخزون",
  "audit.read": "عرض سجل التدقيق",
  "purchases.manage": "إدارة المشتريات",
  "sales.operate": "تشغيل المبيعات",
  "sales.refund": "تنفيذ المرتجعات",
  "reports.view": "عرض التقارير",
};

// --- catalog ---------------------------------------------------------------

export type UnitDimension = "count" | "mass" | "volume";
export type ProductStatus = "active" | "archived";
export type StockStatus = "out" | "low" | "ok";
export type MovementType =
  | "opening_balance"
  | "purchase"
  | "sale"
  | "customer_return"
  | "supplier_return"
  | "adjustment_in"
  | "adjustment_out"
  | "damage"
  | "expiry"
  | "transfer_in"
  | "transfer_out";

/** Money and quantities arrive as decimal strings: never parse them into floats. */
export type UnitOfMeasure = {
  id: string;
  code: string;
  name: string;
  name_ar: string;
  dimension: UnitDimension;
};

export type Category = {
  id: string;
  name: string;
  name_ar: string | null;
  parent_id: string | null;
  created_at: string;
};

export type Brand = {
  id: string;
  name: string;
  name_ar: string | null;
  created_at: string;
};

export type UnitConversion = {
  id: string;
  product_id: string;
  from_unit_id: string;
  to_unit_id: string;
  from_unit_code: string;
  to_unit_code: string;
  factor: string;
  created_at: string;
};

export type Product = {
  id: string;
  sku: string;
  barcode: string | null;
  name_ar: string;
  name: string | null;
  description: string | null;
  category_id: string | null;
  category_name: string | null;
  brand_id: string | null;
  brand_name: string | null;
  base_unit_id: string;
  base_unit_code: string;
  base_unit_name_ar: string;
  purchase_unit_id: string | null;
  purchase_unit_code: string | null;
  sale_unit_id: string | null;
  sale_unit_code: string | null;
  cost_price: string | null;
  sale_price: string | null;
  minimum_stock: string;
  tracks_batches: boolean;
  status: ProductStatus;
  stock_quantity: string;
  stock_status: StockStatus;
  created_at: string;
  updated_at: string;
};

export type ProductDetail = Product & { conversions: UnitConversion[] };

export type ProductList = {
  items: Product[];
  total: number;
  page: number;
  page_size: number;
};

// --- inventory -------------------------------------------------------------

export type InventoryItem = {
  product_id: string;
  sku: string;
  name_ar: string;
  name: string | null;
  category_id: string | null;
  category_name: string | null;
  base_unit_id: string;
  base_unit_code: string;
  base_unit_name_ar: string;
  quantity: string;
  minimum_stock: string;
  stock_status: StockStatus;
  tracks_batches: boolean;
  product_status: ProductStatus;
  sale_price: string | null;
  updated_at: string | null;
};

export type InventoryList = {
  items: InventoryItem[];
  total: number;
  page: number;
  page_size: number;
};

export type Movement = {
  id: string;
  product_id: string;
  product_name_ar: string;
  batch_id: string | null;
  batch_number: string | null;
  movement_type: MovementType;
  direction: "in" | "out";
  quantity: string;
  unit_id: string;
  unit_code: string;
  unit_name_ar: string;
  base_quantity: string;
  unit_cost: string | null;
  notes: string | null;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
};

export type MovementList = {
  items: Movement[];
  total: number;
  page: number;
  page_size: number;
};

export type AdjustmentResult = {
  movement: Movement;
  balance_before: string;
  balance_after: string;
};

export type Batch = {
  id: string;
  product_id: string;
  product_name_ar: string;
  batch_number: string;
  expiry_date: string | null;
  quantity: string;
  created_at: string;
};

export type BatchList = {
  items: Batch[];
  total: number;
  page: number;
  page_size: number;
};

export type InventoryDetail = {
  product: InventoryItem;
  batches: Batch[];
  movements: Movement[];
};


export type AuditLog = {
  id: string;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  meta: Record<string, unknown> | null;
  created_at: string;
};

export type AuditList = {
  items: AuditLog[];
  total: number;
  page: number;
  page_size: number;
};
