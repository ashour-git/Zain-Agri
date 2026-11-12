"""Arabic labels and sheet layout for the backup workbook.

The movement and audit labels must stay identical to the web app's
(``apps/web/src/lib/catalog.ts`` MOVEMENT_LABELS and
``apps/web/src/app/(app)/audit/page.tsx`` ACTION_LABELS), so a shop owner sees
the same words in the file as on screen. tests/test_backup_workbook.py
compares them.
"""

MOVEMENT_LABELS_AR: dict[str, str] = {
    "opening_balance": "رصيد افتتاحي",
    "purchase": "توريد مشتريات",
    "sale": "بيع",
    "customer_return": "مرتجع عميل",
    "supplier_return": "مرتجع مورد",
    "adjustment_in": "تسوية بالزيادة",
    "adjustment_out": "تسوية بالنقص",
    "damage": "تالف",
    "expiry": "منتهي الصلاحية",
    "transfer_in": "تحويل وارد",
    "transfer_out": "تحويل صادر",
}

AUDIT_ACTION_LABELS_AR: dict[str, str] = {
    "product.created": "إضافة منتج",
    "product.updated": "تعديل منتج",
    "product.archived": "أرشفة منتج",
    "product.restored": "استعادة منتج",
    "category.created": "إضافة تصنيف",
    "category.updated": "تعديل تصنيف",
    "brand.created": "إضافة علامة تجارية",
    "conversion.created": "إضافة تحويل وحدات",
    "inventory.movement.created": "حركة مخزون",
    "batch.created": "إضافة دفعة",
    "assistant.asked": "سؤال للمساعد",
    "backup.address_set": "تعيين بريد النسخة اليومية",
    "backup.confirmed": "تأكيد بريد النسخة اليومية",
    "backup.stopped": "إيقاف النسخة اليومية",
    "backup.manual_send": "إرسال نسخة يدوية",
}

ENTITY_LABELS_AR: dict[str, str] = {
    "product": "منتج",
    "category": "تصنيف",
    "brand": "علامة تجارية",
    "conversion": "تحويل وحدات",
    "stock_movement": "حركة مخزون",
    "batch": "دفعة",
    "assistant": "المساعد",
    "backup": "النسخة اليومية",
}

PRODUCT_STATUS_AR = {"active": "نشط", "archived": "مؤرشف"}
YES_AR, NO_AR = "نعم", "لا"

SHEET_PRODUCTS = "المنتجات"
SHEET_BALANCES = "الرصيد"
SHEET_MOVEMENTS = "الحركات"
SHEET_BATCHES = "الدفعات"
SHEET_TAXONOMY = "التصنيفات والعلامات"
SHEET_AUDIT = "سجل النشاط"
SHEET_ABOUT = "عن الملف"

SHEET_NAMES: tuple[str, ...] = (
    SHEET_PRODUCTS,
    SHEET_BALANCES,
    SHEET_MOVEMENTS,
    SHEET_BATCHES,
    SHEET_TAXONOMY,
    SHEET_AUDIT,
    SHEET_ABOUT,
)

HEADERS: dict[str, tuple[str, ...]] = {
    SHEET_PRODUCTS: (
        "الرمز",
        "الباركود",
        "الاسم",
        "الاسم بالإنجليزية",
        "التصنيف",
        "العلامة التجارية",
        "الوحدة الأساسية",
        "سعر التكلفة",
        "سعر البيع",
        "حد التنبيه",
        "تتبع الدفعات",
        "الحالة",
    ),
    SHEET_BALANCES: ("المنتج", "الدفعة", "الكمية", "الوحدة", "تحت الحد الأدنى"),
    SHEET_MOVEMENTS: (
        "التاريخ",
        "المنتج",
        "نوع الحركة",
        "الكمية",
        "الوحدة",
        "الكمية بالوحدة الأساسية",
        "التكلفة",
        "الدفعة",
        "ملاحظة",
        "المستخدم",
    ),
    SHEET_BATCHES: ("المنتج", "رقم الدفعة", "تاريخ الانتهاء"),
    SHEET_TAXONOMY: ("النوع", "الاسم", "التصنيف الرئيسي"),
    SHEET_AUDIT: ("التاريخ", "المستخدم", "الإجراء", "العنصر"),
    SHEET_ABOUT: ("البيان", "القيمة"),
}

TRIMMED_NOTE = (
    "حجم الملف كبير، لذلك تحتوي ورقتا «الحركات» و«سجل النشاط» على آخر 12 شهرًا فقط. "
    "السجل الكامل محفوظ في التطبيق."
)
