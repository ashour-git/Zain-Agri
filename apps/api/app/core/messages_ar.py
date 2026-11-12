"""Arabic text for every error message a user can see.

Services raise errors in English: that text also goes to the logs, where
developers read it. ``error_body`` passes each message through ``to_arabic``
so the response a shop owner sees is always Arabic. Error codes are never
translated; clients branch on the code.

Adding a new error message? Add its Arabic here. tests/test_arabic_errors.py
fails until you do. Anything missed still falls back to an Arabic message for
its code, so English never reaches a user.
"""

from __future__ import annotations

import re

MESSAGES_AR: dict[str, str] = {
    # --- sign-in and sessions ---
    "Invalid email or password": "البريد الإلكتروني أو كلمة المرور غير صحيحة.",
    "Invalid or expired session": "انتهت جلستك. سجّل الدخول مرة أخرى.",
    "Invalid or expired access token": "انتهت جلستك. سجّل الدخول مرة أخرى.",
    "Authentication required": "سجّل الدخول للمتابعة.",
    "Too many attempts, please try again later": "محاولات كثيرة. انتظر بضع دقائق ثم حاول مرة أخرى.",
    "Email address is not verified": "لم يتم تأكيد البريد الإلكتروني بعد.",
    "An account with this email already exists": "يوجد حساب مسجّل بهذا البريد الإلكتروني. سجّل الدخول بدلًا من ذلك.",
    "Session not found": "هذه الجلسة غير موجودة أو انتهت بالفعل.",
    # --- shops and roles ---
    "No workspace selected for this session": "اختر متجرًا أولًا.",
    "You do not have access to this workspace": "ليست لديك صلاحية الدخول إلى هذا المتجر.",
    "Your access to this workspace is not active": "عضويتك في هذا المتجر غير مفعّلة. تواصل مع مالك المتجر.",
    "This workspace is suspended": "هذا المتجر موقوف حاليًا.",
    "Your role does not allow this action": "دورك في المتجر لا يسمح بهذا الإجراء.",
    "Could not allocate a workspace address, try another name": "تعذّر إنشاء المتجر بهذا الاسم. جرّب اسمًا آخر.",
    "Your role cannot set cost prices": "دورك في المتجر لا يسمح بتحديد سعر التكلفة.",
    "Your role cannot record costs": "دورك في المتجر لا يسمح بتسجيل التكلفة.",
    # --- products and catalog ---
    "Product not found": "المنتج غير موجود.",
    "Category not found": "التصنيف غير موجود.",
    "Category does not belong to this workspace": "التصنيف المختار غير موجود في هذا المتجر.",
    "Brand does not belong to this workspace": "العلامة التجارية المختارة غير موجودة في هذا المتجر.",
    "Parent category does not belong to this workspace": "التصنيف الرئيسي المختار غير موجود في هذا المتجر.",
    "Unknown unit of measure": "وحدة القياس غير معروفة.",
    "SKU already exists in this workspace": "رمز المنتج مستخدم لمنتج آخر في متجرك.",
    "Barcode already exists in this workspace": "الباركود مستخدم لمنتج آخر في متجرك.",
    "A category with this name already exists at this level": "يوجد تصنيف بهذا الاسم في نفس المستوى.",
    "A brand with this name already exists": "توجد علامة تجارية بهذا الاسم.",
    "This conversion is already configured": "تحويل الوحدات هذا مسجّل بالفعل.",
    "Archived products cannot be modified": "لا يمكن تعديل منتج مؤرشف. أعد تفعيله أولًا.",
    "The base unit cannot change once conversions or movements exist": "لا يمكن تغيير الوحدة الأساسية بعد تسجيل تحويلات أو حركات للمنتج.",
    "Batch tracking is already in use for this product": "تتبع الدفعات مستخدم بالفعل لهذا المنتج ولا يمكن إيقافه.",
    "A category cannot be its own parent": "لا يمكن أن يكون التصنيف تابعًا لنفسه.",
    "Category hierarchy would contain a cycle": "هذا الاختيار يجعل التصنيفات تدور في حلقة. اختر تصنيفًا رئيسيًا آخر.",
    "Category hierarchy is too deep": "عدد مستويات التصنيفات أكبر من المسموح.",
    "Units belong to different dimensions": "لا يمكن التحويل بين وحدتين من نوعين مختلفين، مثل الوزن والحجم.",
    "A conversion must involve the product's base unit; chains are not inferred": "يجب أن يكون أحد طرفي التحويل هو الوحدة الأساسية للمنتج.",
    # --- stock movements and batches ---
    "No conversion exists between this unit and the product's base unit": "لا يوجد تحويل مسجّل بين هذه الوحدة والوحدة الأساسية للمنتج.",
    "Cost can only be recorded on inbound movements": "التكلفة تُسجَّل فقط مع الكميات الداخلة.",
    "Archived products cannot receive stock movements": "لا يمكن تسجيل حركة لمنتج مؤرشف. أعد تفعيله أولًا.",
    "Batch does not belong to this workspace": "الدفعة المختارة غير موجودة في هذا المتجر.",
    "Batch does not belong to this product": "الدفعة المختارة لا تخص هذا المنتج.",
    "A batch is required for this product": "اختر الدفعة، فهذا المنتج يُتابَع بالدفعات.",
    "This product does not track batches": "هذا المنتج لا يُتابَع بالدفعات.",
    "An opening balance can only be recorded once per product": "الرصيد الافتتاحي سُجّل لهذا المنتج من قبل. استخدم التسوية لتعديل الكمية.",
    "Quantity is too small for the product's precision": "الكمية أصغر من أقل كمية يقبلها هذا المنتج.",
    "Insufficient stock for this adjustment": "الرصيد الحالي لا يكفي لهذه التسوية.",
    "Insufficient stock in this batch": "رصيد هذه الدفعة لا يكفي.",
    "Archived products cannot receive new batches": "لا يمكن إضافة دفعة لمنتج مؤرشف.",
    "A batch with this number already exists for the product": "توجد دفعة بهذا الرقم لنفس المنتج.",
    # --- daily backup email ---
    "Invalid or expired confirmation link": "رابط التأكيد غير صالح أو انتهت صلاحيته. احفظ العنوان مرة أخرى لإرسال رابط جديد.",
    "Backup email is not confirmed": "أكّد عنوان البريد أولًا.",
    "Daily manual backup limit reached": "وصلت للحد اليومي: 3 نسخ يدوية. حاول غدًا.",
    "Backup email sending is not configured": "الإرسال غير مُعدّ.",
    "Too many confirmation emails today": "أرسلنا روابط تأكيد كثيرة اليوم. حاول غدًا.",
    # --- framework-level ---
    "Request validation failed": "بعض البيانات المُدخلة غير صالحة. راجعها ثم حاول مرة أخرى.",
    "Internal server error": "حدث خطأ غير متوقع. حاول مرة أخرى بعد قليل.",
    "Not Found": "الصفحة أو العنصر المطلوب غير موجود.",
    "Method Not Allowed": "هذا الإجراء غير مدعوم.",
}

# Arabic names for fields that services report as "<field> cannot be null".
_FIELD_NAMES_AR: dict[str, str] = {
    "name": "الاسم",
    "name_ar": "الاسم بالعربية",
    "sku": "رمز المنتج",
    "base_unit_id": "الوحدة الأساسية",
    "sale_price": "سعر البيع",
    "status": "الحالة",
    "tracks_batches": "تتبع الدفعات",
    "minimum_stock": "حد التنبيه للمخزون",
}

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(?P<field>\w+) cannot be null$"), "required"),
    (re.compile(r"^\w+ is not writable yet$"), "هذا النوع من الحركات غير متاح بعد."),
]

FALLBACK_BY_CODE: dict[str, str] = {
    "bad_request": "تعذّر تنفيذ الطلب. راجع البيانات ثم حاول مرة أخرى.",
    "unauthorized": "سجّل الدخول للمتابعة.",
    "forbidden": "ليست لديك صلاحية لهذا الإجراء.",
    "not_found": "العنصر المطلوب غير موجود.",
    "conflict": "تعارض مع بيانات موجودة. حدّث الصفحة ثم حاول مرة أخرى.",
    "unprocessable": "لا يمكن تنفيذ هذا الطلب بالبيانات الحالية.",
    "validation_error": "بعض البيانات المُدخلة غير صالحة. راجعها ثم حاول مرة أخرى.",
    "rate_limited": "محاولات كثيرة. انتظر بضع دقائق ثم حاول مرة أخرى.",
    "backup_mail_not_configured": "الإرسال غير مُعدّ.",
    "http_error": "تعذّر إكمال الطلب. حاول مرة أخرى.",
    "internal_error": "حدث خطأ غير متوقع. حاول مرة أخرى بعد قليل.",
}
_LAST_RESORT = "تعذّر إكمال الطلب. حاول مرة أخرى."
_ARABIC = re.compile(r"[؀-ۿ]")


def to_arabic(code: str, message: str) -> str:
    """The Arabic text a user should see for this error."""
    if _ARABIC.search(message):
        return message
    if message in MESSAGES_AR:
        return MESSAGES_AR[message]
    for pattern, arabic in _PATTERNS:
        match = pattern.match(message)
        if match is None:
            continue
        if arabic == "required":
            field = _FIELD_NAMES_AR.get(match["field"])
            return f"حقل «{field}» مطلوب." if field else "أحد الحقول المطلوبة فارغ."
        return arabic
    return FALLBACK_BY_CODE.get(code, _LAST_RESORT)
