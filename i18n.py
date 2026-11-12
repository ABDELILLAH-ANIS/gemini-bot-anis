import asyncio
import hashlib
import logging
import re
import httpx

logger = logging.getLogger(__name__)

SUPPORTED_LANGS = ("ar", "en", "fr")

LANG_LABELS = {
    "ar": "🇩🇿 العربية",
    "en": "🇬🇧 English",
    "fr": "🇫🇷 Français",
}

CURRENCY_MAP = {
    "ar": "دينار",
    "en": "DZD",
    "fr": "DA",
}


def currency_label(lang: str) -> str:
    return CURRENCY_MAP.get(lang, "دينار")


def format_currency_value(raw_curr: str | None, lang: str) -> str:
    """Localize stored currency string ('دينار' -> DZD/DA, '$' stays '$')."""
    if not raw_curr:
        return currency_label(lang)
    c = str(raw_curr).strip()
    if c in ("دينار", "دج", "DZD", "DA"):
        return currency_label(lang)
    return c


# ==================== UI Localization Dictionary (AR / EN / FR) ====================

TRANSLATIONS: dict[str, dict[str, str]] = {
    "ar": {
        # Language Selection
        "choose_language_prompt": (
            "🌐 **اختر لغتك المفضلة / Choose Your Language / Choisissez votre langue:**\n\n"
            "• 🇩🇿 العربية\n"
            "• 🇬🇧 English\n"
            "• 🇫🇷 Français"
        ),
        "lang_saved_toast": "✅ تم اختيار اللغة العربية بنجاح!",
        "btn_change_lang": "🌐 اللغة (Language)",

        # Force-Join Gate
        "force_join_title": "🔒 **للمتابعة واستخدام المتجر، يرجى الانضمام أولاً إلى قنواتنا الرسمية:**",
        "force_join_desc": (
            "👇 اشترك في القناة والمجموعة بالأسفل ثم اضغط على زر **'✅ تحققت، انضممت الآن'** للوصول إلى جميع المنتجات والمحفظة:"
        ),
        "force_join_chat_note": "💡 *ملاحظة:* للدخول إلى الشات، يمكنك الضغط على زر القناة ثم زر **المناقشة (Discuss)** بالأسفل إذا لم يفتح الرابط مباشرة.",
        "force_join_btn_verify": "✅ تحققت، انضممت الآن",
        "force_join_status_joined": "✅ منضم",
        "force_join_status_missing": "❌ غير منضم بعد",
        "force_join_not_yet_alert": "⚠️ لم تنضم بعد إلى: {missing}\nيرجى الانضمام أولاً ثم الضغط على زر التحقق مجدداً.",
        "force_join_verified_toast": "✅ تم التحقق من اشتراكك! أهلاً بك في المتجر 🎉",
        "force_join_join_prefix": "انضمام:",

        # Main Reply Keyboard
        "menu_buy": "🛒 شراء اشتراك",
        "menu_wallet": "👛 محفظتي (Top Up)",
        "menu_orders": "📦 طلباتي السابقة",
        "menu_help": "📘 الدعم والتعليمات",
        "menu_admin": "⚙️ لوحة تحكم الإدارة",
        "menu_cancel": "❌ إلغاء العملية",

        # Start & Welcome
        "welcome": (
            "مرحباً بك يا **{name}** في **متجر الاشتراكات الرقمية** 🤖✨\n\n"
            "نوفر لك اشتراكات رسمية بأفضل الأسعار وبضمان كامل.\n\n"
            "👛 **رصيد محفظتك الحالي:** `{dzd}` {curr} | `${usd}`\n\n"
            "📌 **أبرز الباقات المتوفرة حالياً:**\n{products_list}\n"
            "اختر من القائمة بالأسفل للبدء 👇"
        ),
        "more_products_note": "• 🛍️ _و `{count}` باقات ومنتجات أخرى داخل القائمة..._\n",

        # Help
        "help_text": (
            "📘 **حول الخدمة وطريقة الشراء والتفعيل:**\n\n"
            "1. يمكنك شحن محفظتك بالدينار أو الدولار عبر زر **'👛 محفظتي (Top Up)'** والشراء الفوري بضغطة زر.\n"
            "2. أو يمكنك اختيار المنتج والدفع المباشر وإرسال وصل التحويل.\n"
            "3. لكل منتج زر أزرق **'📖 تعليمات وشروط المنتج'** يوضح طريقة التفعيل والضمان بالتفصيل.\n\n"
            "📞 في حال واجهت أي مشكلة، يمكنك إرسال رسالتك هنا مباشرة وسيقوم فريق الدعم بالرد عليك فوراً."
        ),

        # My Orders
        "no_orders": "📦 ليس لديك أي طلبات سابقة حتى الآن.\nيمكنك الضغط على '🛒 شراء اشتراك' لطلب اشتراكك الأول!",
        "recent_orders_title": "📦 **طلباتك الأخيرة:**\n\n",
        "status_pending": "⏳ قيد المراجعة والتحقق",
        "status_approved": "✅ مكتمل ومُسلّم",
        "status_rejected": "❌ مرفوض",
        "order_item": (
            "🔹 **طلب رقم:** `{code}`\n"
            "• المنتج: {product} (الكمية: `{qty}`)\n"
            "• المبلغ: `{total}` {curr}\n"
            "• الحالة: {status}\n"
            "• التاريخ: `{date}`\n"
        ),
        "delivered_links_label": "🔗 **روابط/بيانات التفعيل المستلمة:**\n`{links}`\n",
        "reject_reason_label": "⚠️ **سبب الرفض:** {reason}\n",

        # Categories & Products
        "choose_brand": "🛒 **اختر علامة تجارية لتصفح المنتجات:**",
        "btn_other_brands": "🛍️ باقات ومنتجات أخرى",
        "btn_back_menu": "🔙 العودة للقائمة",
        "btn_back_categories": "🔙 رجوع للأقسام",
        "btn_back_products": "🔙 رجوع للمنتجات",
        "btn_back_product_list": "🔙 رجوع لقائمة المنتجات",
        "btn_back_quantity": "🔙 رجوع لتحديد الكمية",
        "btn_cancel": "❌ إلغاء",
        "btn_cancel_order": "❌ إلغاء الطلب",
        "btn_prev": "⬅️ السابق",
        "btn_next": "عرض التالي ➡️",
        "no_products_in_cat": "{title}\n\n⚠️ عذراً، لا توجد منتجات متوفرة في هذا القسم حالياً.",
        "cat_page_note": " (صفحة {page} من {total})",
        "cat_products_header": (
            "{title}{page_note}\n"
            "إجمالي الباقات في هذا القسم: `{total_items}` باقة.\n"
            "اختر الباقة المناسبة لك (أو اضغط **عرض التالي ➡️** لتصفح المزيد):"
        ),
        "session_cancelled": "❌ تم إلغاء العملية.",
        "session_cancelled_main": "❌ تم إلغاء العملية والعودة للقائمة الرئيسية.",
        "product_unavailable": "⚠️ عذراً، هذا المنتج غير متوفر حالياً.",
        "product_not_found": "⚠️ عذراً، المنتج غير موجود.",
        "product_detail": (
            "💎 **لقد اخترت:** {name}\n"
            "🇩🇿 **السعر بالدينار:** `{price_dzd}` {curr}\n"
            "💵 **السعر بالدولار:** `${price_usd}`\n\n"
            "📝 **الوصف:**\n{desc}\n\n"
            "🔢 **الرجاء تحديد الكمية المطلوبة (أو اضغط على زر تعليمات المنتج الأزرق):**"
        ),
        "btn_prod_instructions": "🔵 📖 تعليمات وشروط المنتج",
        "btn_prod_instructions_short": "🔵 📖 تعليمات المنتج",
        "btn_continue_buy": "🛒 متابعة شراء هذا المنتج",
        "prod_inst_toast": "📖 تعليمات وشروط المنتج",
        "prod_inst_view": (
            "🔵 📖 **تعليمات وشروط المنتج:**\n"
            "─────────────────────\n"
            "📦 **المنتج:** {name}\n"
            "💰 **السعر:** `{price_dzd}` {curr} | `${price_usd}`\n"
            "─────────────────────\n\n"
            "📋 **التعليمات وطريقة التفعيل:**\n"
            "{inst}\n\n"
            "─────────────────────\n"
            "👇 اضغط على **'🛒 متابعة شراء هذا المنتج'** لاختيار الكمية وإتمام الطلب:"
        ),
        "default_inst_fallback": "اشتراك رسمي أصلي مع ضمان كامل وتسليم فوري.",

        # Payment Selection & Checkout
        "choose_payment": (
            "📦 **المنتج:** {name}\n"
            "🔢 **الكمية:** `{qty}`\n"
            "💵 **الإجمالي:** `{total_dzd}` {curr} أو `${total_usd}`\n"
            "👛 **رصيد محفظتك الحالي:** `{bal_dzd}` {curr} | `${bal_usd}`\n\n"
            "💳 **الرجاء اختيار طريقة الدفع المناسبة لك:**"
        ),
        "choose_payment_change": (
            "📦 **المنتج:** {name}\n"
            "🔢 **الكمية:** `{qty}`\n\n"
            "💳 **الرجاء اختيار طريقة الدفع المناسبة لك:**"
        ),
        "btn_pay_wallet_dzd": "👛 الدفع من محفظة الدينار{dzd_part}",
        "btn_pay_wallet_usd": "👛 الدفع من محفظة الدولار (${total_usd})",
        "btn_pay_baridimob": "🏦 بريدي موب (BaridiMob){dzd_part}",
        "btn_pay_redotpay": "💳 RedotPay (${total_usd})",
        "btn_pay_bybit": "🟡 Bybit (${total_usd})",
        "btn_upload_receipt": "📤 إرسال إشعار التحويل ورقم الحوالة",
        "btn_change_payment": "🔙 تغيير طريقة الدفع",
        "btn_confirm_wallet_pay": "✅ تأكيد الخصم من المحفظة وإتمام الشراء فوراً",
        "btn_topup_now": "➕ شحن المحفظة الآن (Top Up)",
        "btn_choose_other_pay": "🔙 اختيار طريقة دفع أخرى",
        "wallet_dzd_name": "محفظة الدينار 👛",
        "wallet_usd_name": "محفظة الدولار 👛",
        "insufficient_balance": (
            "⚠️ **رصيد محفظتك غير كافٍ لإتمام هذه العملية!**\n"
            "─────────────────\n"
            "📦 **المنتج:** {name} (x{qty})\n"
            "💰 **المبلغ المطلوب:** `{total}` {curr}\n"
            "👛 **رصيدك الحالي في {method}:** `{bal}` {curr}\n"
            "📉 **المبلغ الناقص:** `{needed}` {curr}\n"
            "─────────────────\n\n"
            "💡 يمكنك شحن محفظتك الآن عبر زر **شحن المحفظة (Top Up)** أو اختيار وسيلة دفع مباشرة أخرى:"
        ),
        "confirm_wallet_pay_text": (
            "👛 **تأكيد الدفع الفوري من المحفظة:**\n"
            "─────────────────\n"
            "📦 **المنتج:** {name}\n"
            "🔢 **الكمية:** `{qty}`\n"
            "💳 **طريقة الدفع:** {method}\n"
            "💰 **المبلغ المطلوب خصمه:** `{total}` {curr}\n"
            "👛 **رصيدك الحالي:** `{bal}` {curr}\n"
            "✅ **الرصيد المتبقي بعد الشراء:** `{remaining}` {curr}\n"
            "─────────────────\n\n"
            "👇 اضغط على الزر الأخضر بالأسفل لتأكيد الخصم واستلام اشتراكك فوراً:"
        ),
        "order_summary": (
            "📋 **ملخص طلبك:**\n"
            "─────────────────\n"
            "📦 **المنتج:** {name}\n"
            "🔢 **الكمية:** `{qty}`\n"
            "💳 **طريقة الدفع:** {method}\n"
            "💰 **المبلغ الإجمالي المطلوب:** `{total}` {curr}\n"
            "─────────────────\n"
            "{instructions}\n\n"
            "👇 اضغط على الزر بالأسفل عندما تكون جاهزاً لإرسال إشعار التحويل ورقم الحوالة:"
        ),
        "session_expired": "⚠️ انتهت الجلسة، يرجى إعادة الطلب.",
        "session_expired_restart": "⚠️ حدث خطأ أو انتهت الجلسة. يرجى إعادة الطلب من البداية.",
        "wallet_dzd_insufficient_toast": "⚠️ رصيد محفظة الدينار غير كافٍ!",
        "wallet_usd_insufficient_toast": "⚠️ رصيد محفظة الدولار غير كافٍ!",
        "processing_wallet_order": "⏳ جاري خصم الرصيد وتجهيز اشتراكك...",
        "wallet_pay_ref": "مدفوع من المحفظة ({total} {curr})",
        "wallet_instant_success": (
            "✅ **تم الدفع من محفظتك وتسليم الطلب `{code}` فوراً!**\n\n"
            "📦 **المنتج:** {name}\n"
            "💰 **المبلغ المخصوم:** `{total}` {curr}\n"
            "👛 **رصيد محفظتك المتبقي:** `{bal_dzd}` {dzd_curr} | `${bal_usd}`\n\n"
            "تم إرسال روابط/بيانات التفعيل في الرسالة أعلاه. شكراً لثقتك بنا! 🚀"
        ),
        "wallet_manual_pending": (
            "🎉 **تم خصم المبلغ من محفظتك وتأكيد طلبك `{code}` بنجاح!**\n\n"
            "📦 **المنتج:** {name} (x`{qty}`)\n"
            "💰 **المبلغ المدفوع:** `{total}` {curr}\n"
            "👛 **رصيد محفظتك المتبقي:** `{bal_dzd}` {dzd_curr} | `${bal_usd}`\n\n"
            "⏳ **حالة الطلب:** جاري تجهيز الحساب/الرابط يدوياً من قبل المشرف وسيصلك هنا في أقرب وقت! 🌟"
        ),
        "upload_receipt_prompt": (
            "📸 **الرجاء إرسال صورة وصل / إشعار التحويل الآن.**\n\n"
            "💡 *ملاحظة:* إذا قمت بكتابة رقم التحويل في وصف الصورة (Caption)، سيتم اعتماده مباشرة، "
            "أو يمكنك إرسال الصورة وسيسألك البوت عن رقم الحوالة بعد ذلك."
        ),
        "cancel_reply_hint": "إذا أردت التراجع يمكنك الضغط على '❌ إلغاء العملية':",
        "receipt_received_ask_ref": (
            "✅ تم استلام صورة الإيصال بنجاح.\n\n"
            "✍️ **الآن، يرجى كتابة رقم عملية التحويل (رقم الحوالة أو المرجع):**"
        ),
        "order_submitted": (
            "🎉 **تم إرسال طلبك بنجاح!**\n\n"
            "🔹 **رقم الطلب:** `{code}`\n"
            "📦 **المنتج:** {name}\n"
            "🔢 **الكمية:** `{qty}`\n"
            "💳 **طريقة الدفع:** {method}\n"
            "💰 **المبلغ:** `{total}` {curr}\n"
            "🧾 **رقم التحويل:** `{ref}`\n\n"
            "⏳ جاري التحقق من إشعار التحويل من قبل الإدارة. ستصلك روابط التفعيل هنا في المحادثة فور التأكيد!"
        ),

        # Wallet & Top-Up
        "wallet_dashboard": (
            "👛 **محفظتي الإلكترونية (TOP UP WALLET)**\n"
            "─────────────────────\n"
            "👤 **الحساب:** {name} (`{uid}`)\n\n"
            "🇩🇿 **الرصيد بالدينار الجزائري:** `{bal_dzd}` {curr}\n"
            "💵 **الرصيد بالدولار الأمريكي:** `${bal_usd}`\n"
            "─────────────────────\n"
            "💡 **كيف تعمل المحفظة؟**\n"
            "1. اختر العملة التي تريد شحنها (**دينار** أو **دولار**).\n"
            "2. أدخل المبلغ الذي تريد إضافته لمحفظتك وقم بالتحويل.\n"
            "3. أرسل تأكيد التحويل أو صورة الوصل، وبمجرد تأكيد الإدارة يظهر الرصيد فوراً في محفظتك لتشتري به أي منتج بضغطة زر!\n\n"
            "👇 اختر العملية المطلوبة بالأسفل:"
        ),
        "btn_topup_dzd": "➕ شحن المحفظة بالدينار 🇩🇿 (Top Up DZD)",
        "btn_topup_usd": "➕ شحن المحفظة بالدولار 💵 (Top Up USD)",
        "btn_wallet_history": "📜 سجل عمليات الشحن",
        "btn_go_buy": "🛒 الذهاب لشراء اشتراك",
        "btn_back_wallet": "🔙 رجوع للمحفظة",
        "btn_change_amount": "🔙 تغيير المبلغ",
        "btn_wallet_confirm_transfer": "✅ قمت بالتحويل — إرسال الوصل أو تأكيد العملية",
        "no_topups": (
            "📜 **سجل عمليات شحن المحفظة:**\n\n"
            "لا توجد لديك أي طلبات شحن سابقة حتى الآن.\n"
            "اضغط على **شحن المحفظة** بالأسفل لإضافة رصيدك الأول!"
        ),
        "topups_history_title": "📜 **آخر عمليات شحن المحفظة الخاصة بك:**\n─────────────────────\n",
        "topup_status_approved": "✅ تمت إضافة الرصيد",
        "topup_status_pending": "⏳ قيد المراجعة",
        "topup_status_rejected": "❌ مرفوض",
        "topup_history_item": (
            "🔹 `{code}` — `{amount}` {curr}\n"
            "• الوسيلة: {method} | الحالة: {status}\n"
            "• التاريخ: `{date}`\n"
        ),
        "topup_reject_reason": "• سبب الرفض: {reason}\n",
        "topup_prompt_dzd": (
            "🇩🇿 **شحن المحفظة بالدينار الجزائري (Top Up DZD):**\n"
            "─────────────────────\n"
            "✍️ **أدخل المبلغ بالدينار الذي تريد شحنه في محفظتك (أرقام فقط، أو اختر من الأزرار السريعة بالأسفل):**\n"
            "مثال: `2000` أو `5000`"
        ),
        "topup_prompt_usd": (
            "💵 **شحن المحفظة بالدولار الأمريكي (Top Up USD):**\n"
            "─────────────────────\n"
            "✍️ **أدخل المبلغ بالدولار (`$`) الذي تريد شحنه في محفظتك (أرقام فقط، أو اختر من الأزرار السريعة بالأسفل):**\n"
            "مثال: `10` أو `25`"
        ),
        "topup_invalid_amount": "⚠️ يرجى إدخال مبلغ رقمي صحيح أكبر من الصفر (مثال: `2000` أو `10`).",
        "topup_dzd_step": (
            "👛 **شحن المحفظة بمبلغ `{amount}` {curr}**\n"
            "─────────────────────\n"
            "💳 **طريقة التحويل:** بريدي موب (BaridiMob)\n"
            "💰 **المبلغ المطلوب تحويله:** `{amount}` {curr}\n"
            "─────────────────────\n"
            "{pay_info}\n\n"
            "👇 بعد إتمام التحويل، اضغط على الزر الأخضر بالأسفل لإرسال الوصل أو تأكيد التحويل:"
        ),
        "topup_usd_choose_method": (
            "👛 **شحن المحفظة بمبلغ `${amount}` دولار**\n"
            "─────────────────────\n"
            "💳 **اختر وسيلة الدفع بالدولار التي تود التحويل عبرها:**"
        ),
        "topup_usd_step": (
            "👛 **شحن المحفظة بمبلغ `${amount}` دولار**\n"
            "─────────────────────\n"
            "💳 **وسيلة الدفع:** {method}\n"
            "💰 **المبلغ المطلوب تحويله:** `${amount}`\n"
            "─────────────────────\n"
            "{details}\n\n"
            "👇 بعد إتمام التحويل، اضغط على الزر الأخضر بالأسفل لإرسال الوصل أو تأكيد العملية:"
        ),
        "topup_upload_prompt": (
            "📤 **تأكيد شحن المحفظة بمبلغ `{amount}` {curr}**\n"
            "─────────────────────\n"
            "📸 **أرسل الآن صورة وصل التحويل (Screenshot)**، أو **اكتب رقم عملية التحويل / رسالة تأكيد بأنك قمت بالتحويل** في المحادثة:\n\n"
            "⏳ سيقوم المشرف بمراجعة الحوالة والموافقة عليها ليظهر الرصيد في محفظتك فوراً!"
        ),
        "topup_upload_hint": "أرسل صورة الوصل أو رقم التحويل الآن (أو اضغط '❌ إلغاء العملية' للتراجع):",
        "topup_session_expired": "⚠️ انتهت الجلسة، يرجى فتح المحفظة والمحاولة من جديد.",
        "topup_submitted": (
            "🎉 **تم إرسال طلب شحن المحفظة بنجاح!**\n"
            "─────────────────────\n"
            "🔹 **رقم العملية:** `{code}`\n"
            "💰 **المبلغ المطلوب إضافته:** `{amount}` {curr}\n"
            "💳 **وسيلة الدفع:** {method}\n"
            "🧾 **المرجع / التأكيد:** `{ref}`\n"
            "─────────────────────\n"
            "⏳ **الحالة:** بانتظار تأكيد الإدارة.\n"
            "بمجرد التحقق من وصول المبلغ والموافقة عليه سيصلك إشعار فوري هنا ويُضاف الرصيد إلى محفظتك! 🌟"
        ),

        # Support Inbound
        "support_text_received": (
            "✅ **تم استلام رسالتك وإيصالها لإدارة المتجر بنجاح.**\n"
            "سيقوم المشرف بالرد عليك هنا في أقرب وقت ممكن. شكراً لتواصلك! 🌟"
        ),
        "support_photo_received": (
            "✅ **تم استلام الصورة وإرسالها لإدارة المتجر بنجاح.**\n"
            "سيقوم المشرف بمراجعتها والرد عليك قريباً."
        ),

        # Admin -> Customer Notifications
        "cust_link_header": "🔗 **رابط التفعيل #{idx}:**",
        "cust_code_header": "🔑 **بيانات / كود التفعيل #{idx}:**",
        "cust_custom_inst_header": "📘 **تعليمات وشروط التفعيل:**\n{inst}\n\n",
        "cust_gemini_inst": (
            "🌟 **طريقة التفعيل:**\n"
            "1. قم بفتح رابط التفعيل في المتصفح.\n"
            "2. سجل الدخول بحساب Google الذي تريد تفعيل اشتراك Gemini Pro عليه.\n"
            "3. اضغط على تأكيد/قبول التفعيل ومبروك عليك الاشتراك! 🚀\n\n"
        ),
        "cust_generic_inst": (
            "🌟 **طريقة التفعيل / الاستخدام:**\n"
            "1. استخدم الرابط أو بيانات الحساب/الكود المرفقة أعلاه لتسجيل الدخول والتفعيل.\n"
            "2. الاشتراك أصلي ومضمون طوال المدة المحددة بضمان المتجر.\n"
            "3. إذا احتجت أي مساعدة بالتفعيل يمكنك مراسلتنا هنا مباشرة وسنساعدك فوراً! 🚀\n\n"
        ),
        "cust_delivery_msg": (
            "🎉 **مبروك! تم تأكيد وقبول عملية الدفع لطلبك بنجاح!**\n"
            "─────────────────────\n"
            "🔹 **رقم الطلب:** `{code}`\n"
            "📦 **المنتج:** {name}\n"
            "🔢 **الكمية:** {qty}\n"
            "─────────────────────\n\n"
            "{items}"
            "{instructions}"
            "شكراً لثقتك بنا ونتمنى لك تجربة ممتعة! 🌟"
        ),
        "cust_order_wait": (
            "⏳ **مرحباً بك عزيزي العميل!**\n\n"
            "📌 بخصوص طلبك رقم: `{code}`\n"
            "📦 المنتج: **{name}**\n\n"
            "🛠 **طلبك قيد التجهيز والتفعيل الآن من قبل إدارة المتجر.**\n"
            "نعمل حالياً على تجهيز وشراء اشتراكك لضمان أعلى جودة.\n"
            "يرجى الانتظار بضع دقائق وسيصلك رابط وبيانات التفعيل هنا فور الانتهاء مباشرة! 🚀\n\n"
            "شاكرين لصبرك وحسن تعاملك معنا! 🌟"
        ),
        "cust_order_rejected": (
            "❌ **نعتذر منك، تم رفض طلبك رقم `{code}`.**\n\n"
            "⚠️ **السبب:** {reason}\n\n"
            "إذا كنت ترى أن هناك خطأ أو ترغب في إعادة المحاولة، يرجى مراجعة إشعار التحويل أو التواصل معنا."
        ),
        "cust_admin_msg_order": (
            "📩 **رسالة من إدارة المتجر بخصوص طلبك `{code}`:**\n\n"
            "{msg}\n\n"
            "─────────────────\n"
            "💬 يمكنك الرد مباشرة على هذه الرسالة إذا طُلب منك أي معلومات أو استفسار."
        ),
        "cust_admin_msg_direct": (
            "📩 **رسالة من إدارة المتجر{prefix}:**\n\n"
            "{msg}\n\n"
            "─────────────────\n"
            "💬 يمكنك الرد مباشرة على هذه الرسالة."
        ),
        "cust_admin_order_prefix": " بخصوص طلبك `{code}`",
        "cust_topup_approved": (
            "🎉 **تمت الموافقة على شحن محفظتك بنجاح!**\n"
            "─────────────────────\n"
            "🔹 **رقم العملية:** `{code}`\n"
            "➕ **المبلغ المضاف:** `{amt}` {curr}\n\n"
            "👛 **رصيد محفظتك الحالي الآن:**\n"
            "• 🇩🇿 بالدينار: **`{bal_dzd}` {dzd_curr}**\n"
            "• 💵 بالدولار: **`${bal_usd}`**\n"
            "─────────────────────\n"
            "يمكنك الآن شراء أي اشتراك فوراً باستخدام رصيد محفظتك! 🚀"
        ),
        "cust_topup_rejected": (
            "❌ **نعتذر منك، تم رفض طلب شحن المحفظة `{code}`.**\n\n"
            "⚠️ **السبب:** {reason}\n\n"
            "يرجى التأكد من إشعار التحويل أو التواصل معنا للمساعدة."
        ),
        "cust_manual_wallet_credit": (
            "🎉 **تمت إضافة رصيد إلى محفظتك من قِبل الإدارة!**\n\n"
            "➕ **المبلغ المضاف:** `{amt}` {curr}\n"
            "👛 **رصيد محفظتك الآن:** `{bal_dzd}` {dzd_curr} | `${bal_usd}`"
        ),

        # Payment Details
        "baridimob_name": "بريدي موب (BaridiMob)",
        "baridimob_details": (
            "🏦 **الدفع عبر بريدي موب (BaridiMob):**\n"
            "• رقم الحساب / RIP: `00799999000123456789`\n"
            "• الاسم: المتجر الرقمي\n"
            "• الهاتف / المعرف: `0555000000`"
        ),
        "redotpay_details": (
            "💳 **الدفع عبر RedotPay:**\n"
            "• الـ UID الخاص بالحساب: `1445653765`\n"
            "• نوع التحويل: تحويل داخلي عبر RedotPay ID (مجاني فوري بدون عمولة)"
        ),
        "bybit_details": (
            "🟡 **الدفع عبر منصة Bybit:**\n"
            "• الـ UID الخاص بالحساب: `593583401`\n"
            "• العملة: USDT\n"
            "• نوع التحويل: تحويل داخلي عبر Bybit UID (مجاني فوري بدون رسوم شبكة)"
        ),
    },

    "en": {
        "choose_language_prompt": (
            "🌐 **Choose Your Language / اختر لغتك / Choisissez votre langue:**\n\n"
            "• 🇩🇿 العربية\n"
            "• 🇬🇧 English\n"
            "• 🇫🇷 Français"
        ),
        "lang_saved_toast": "✅ English language selected!",
        "btn_change_lang": "🌐 Language",

        "force_join_title": "🔒 **To use the store and view products, please join our official channels first:**",
        "force_join_desc": (
            "👇 Join both the channel and chat below, then tap **'✅ I Joined — Verify'** to unlock all products and your wallet:"
        ),
        "force_join_chat_note": "💡 *Tip:* To enter the chat group, you can open the channel and tap **Discuss** at the bottom if the direct link isn't listed.",
        "force_join_btn_verify": "✅ I Joined — Verify",
        "force_join_status_joined": "✅ Joined",
        "force_join_status_missing": "❌ Not joined yet",
        "force_join_not_yet_alert": "⚠️ You haven't joined yet: {missing}\nPlease join first, then tap Verify again.",
        "force_join_verified_toast": "✅ Membership verified! Welcome to the store 🎉",
        "force_join_join_prefix": "Join:",

        "menu_buy": "🛒 Buy Subscription",
        "menu_wallet": "👛 My Wallet (Top Up)",
        "menu_orders": "📦 My Orders",
        "menu_help": "📘 Support & Info",
        "menu_admin": "⚙️ لوحة تحكم الإدارة",
        "menu_cancel": "❌ Cancel",

        "welcome": (
            "Welcome **{name}** to the **Digital Subscriptions Store** 🤖✨\n\n"
            "We offer official subscriptions at the best prices with full warranty.\n\n"
            "👛 **Your Current Wallet Balance:** `{dzd}` {curr} | `${usd}`\n\n"
            "📌 **Featured Plans Available Now:**\n{products_list}\n"
            "Choose an option from the menu below to get started 👇"
        ),
        "more_products_note": "• 🛍️ _And `{count}` more plans & products inside the catalog..._\n",

        "help_text": (
            "📘 **About Our Service, Ordering & Activation:**\n\n"
            "1. Top up your wallet in DZD or USD via **'👛 My Wallet (Top Up)'** for instant 1-click checkout.\n"
            "2. Or pick any product, pay directly, and upload your transfer receipt.\n"
            "3. Every product has a blue **'📖 Product Instructions & Terms'** button explaining activation & warranty details.\n\n"
            "📞 Need help? Simply send your message right here and our support team will reply promptly."
        ),

        "no_orders": "📦 You have no previous orders yet.\nTap '🛒 Buy Subscription' to place your first order!",
        "recent_orders_title": "📦 **Your Recent Orders:**\n\n",
        "status_pending": "⏳ Pending Verification",
        "status_approved": "✅ Completed & Delivered",
        "status_rejected": "❌ Rejected",
        "order_item": (
            "🔹 **Order No.:** `{code}`\n"
            "• Product: {product} (Qty: `{qty}`)\n"
            "• Amount: `{total}` {curr}\n"
            "• Status: {status}\n"
            "• Date: `{date}`\n"
        ),
        "delivered_links_label": "🔗 **Delivered Activation Links / Credentials:**\n`{links}`\n",
        "reject_reason_label": "⚠️ **Rejection Reason:** {reason}\n",

        "choose_brand": "🛒 **Select a brand to browse products:**",
        "btn_other_brands": "🛍️ Other Plans & Products",
        "btn_back_menu": "🔙 Back to Menu",
        "btn_back_categories": "🔙 Back to Categories",
        "btn_back_products": "🔙 Back to Products",
        "btn_back_product_list": "🔙 Back to Product List",
        "btn_back_quantity": "🔙 Back to Quantity",
        "btn_cancel": "❌ Cancel",
        "btn_cancel_order": "❌ Cancel Order",
        "btn_prev": "⬅️ Previous",
        "btn_next": "Next ➡️",
        "no_products_in_cat": "{title}\n\n⚠️ Sorry, there are currently no available products in this category.",
        "cat_page_note": " (Page {page} of {total})",
        "cat_products_header": (
            "{title}{page_note}\n"
            "Total plans in this category: `{total_items}`.\n"
            "Choose your plan (or tap **Next ➡️** to browse more):"
        ),
        "session_cancelled": "❌ Operation cancelled.",
        "session_cancelled_main": "❌ Operation cancelled. Returned to main menu.",
        "product_unavailable": "⚠️ Sorry, this product is currently unavailable.",
        "product_not_found": "⚠️ Sorry, product not found.",
        "product_detail": (
            "💎 **Selected Product:** {name}\n"
            "🇩🇿 **Price in DZD:** `{price_dzd}` {curr}\n"
            "💵 **Price in USD:** `${price_usd}`\n\n"
            "📝 **Description:**\n{desc}\n\n"
            "🔢 **Please select the quantity (or tap the blue instructions button):**"
        ),
        "btn_prod_instructions": "🔵 📖 Product Instructions & Terms",
        "btn_prod_instructions_short": "🔵 📖 Product Instructions",
        "btn_continue_buy": "🛒 Continue Buying This Product",
        "prod_inst_toast": "📖 Product Instructions & Terms",
        "prod_inst_view": (
            "🔵 📖 **Product Instructions & Terms:**\n"
            "─────────────────────\n"
            "📦 **Product:** {name}\n"
            "💰 **Price:** `{price_dzd}` {curr} | `${price_usd}`\n"
            "─────────────────────\n\n"
            "📋 **Instructions & Activation Guide:**\n"
            "{inst}\n\n"
            "─────────────────────\n"
            "👇 Tap **'🛒 Continue Buying This Product'** to choose quantity and checkout:"
        ),
        "default_inst_fallback": "Official subscription with full warranty and instant delivery.",

        "choose_payment": (
            "📦 **Product:** {name}\n"
            "🔢 **Quantity:** `{qty}`\n"
            "💵 **Total:** `{total_dzd}` {curr} or `${total_usd}`\n"
            "👛 **Your Wallet Balance:** `{bal_dzd}` {curr} | `${bal_usd}`\n\n"
            "💳 **Please choose your preferred payment method:**"
        ),
        "choose_payment_change": (
            "📦 **Product:** {name}\n"
            "🔢 **Quantity:** `{qty}`\n\n"
            "💳 **Please choose your preferred payment method:**"
        ),
        "btn_pay_wallet_dzd": "👛 Pay from DZD Wallet{dzd_part}",
        "btn_pay_wallet_usd": "👛 Pay from USD Wallet (${total_usd})",
        "btn_pay_baridimob": "🏦 BaridiMob{dzd_part}",
        "btn_pay_redotpay": "💳 RedotPay (${total_usd})",
        "btn_pay_bybit": "🟡 Bybit (${total_usd})",
        "btn_upload_receipt": "📤 Send Transfer Receipt & Reference",
        "btn_change_payment": "🔙 Change Payment Method",
        "btn_confirm_wallet_pay": "✅ Confirm Wallet Deduction & Complete Order",
        "btn_topup_now": "➕ Top Up Wallet Now",
        "btn_choose_other_pay": "🔙 Choose Another Payment Method",
        "wallet_dzd_name": "DZD Wallet 👛",
        "wallet_usd_name": "USD Wallet 👛",
        "insufficient_balance": (
            "⚠️ **Insufficient wallet balance for this purchase!**\n"
            "─────────────────\n"
            "📦 **Product:** {name} (x{qty})\n"
            "💰 **Required Amount:** `{total}` {curr}\n"
            "👛 **Current Balance ({method}):** `{bal}` {curr}\n"
            "📉 **Shortfall:** `{needed}` {curr}\n"
            "─────────────────\n\n"
            "💡 You can top up your wallet now via **Top Up Wallet** or choose another direct payment method:"
        ),
        "confirm_wallet_pay_text": (
            "👛 **Confirm Instant Wallet Payment:**\n"
            "─────────────────\n"
            "📦 **Product:** {name}\n"
            "🔢 **Quantity:** `{qty}`\n"
            "💳 **Payment Method:** {method}\n"
            "💰 **Amount to Deduct:** `{total}` {curr}\n"
            "👛 **Current Balance:** `{bal}` {curr}\n"
            "✅ **Remaining Balance:** `{remaining}` {curr}\n"
            "─────────────────\n\n"
            "👇 Tap the green button below to confirm and receive your subscription immediately:"
        ),
        "order_summary": (
            "📋 **Order Summary:**\n"
            "─────────────────\n"
            "📦 **Product:** {name}\n"
            "🔢 **Quantity:** `{qty}`\n"
            "💳 **Payment Method:** {method}\n"
            "💰 **Total Amount Due:** `{total}` {curr}\n"
            "─────────────────\n"
            "{instructions}\n\n"
            "👇 Tap the button below once you're ready to send the transfer receipt & reference number:"
        ),
        "session_expired": "⚠️ Session expired, please start your order again.",
        "session_expired_restart": "⚠️ An error occurred or your session expired. Please start over.",
        "wallet_dzd_insufficient_toast": "⚠️ Insufficient DZD wallet balance!",
        "wallet_usd_insufficient_toast": "⚠️ Insufficient USD wallet balance!",
        "processing_wallet_order": "⏳ Deducting balance and preparing your subscription...",
        "wallet_pay_ref": "Paid via Wallet ({total} {curr})",
        "wallet_instant_success": (
            "✅ **Paid via Wallet & Order `{code}` Delivered Immediately!**\n\n"
            "📦 **Product:** {name}\n"
            "💰 **Amount Deducted:** `{total}` {curr}\n"
            "👛 **Remaining Wallet Balance:** `{bal_dzd}` {dzd_curr} | `${bal_usd}`\n\n"
            "Your activation links/credentials have been sent above. Thank you for choosing us! 🚀"
        ),
        "wallet_manual_pending": (
            "🎉 **Amount deducted & Order `{code}` confirmed!**\n\n"
            "📦 **Product:** {name} (x`{qty}`)\n"
            "💰 **Amount Paid:** `{total}` {curr}\n"
            "👛 **Remaining Wallet Balance:** `{bal_dzd}` {dzd_curr} | `${bal_usd}`\n\n"
            "⏳ **Status:** Your subscription is being prepared manually by our admin and will arrive here shortly! 🌟"
        ),
        "upload_receipt_prompt": (
            "📸 **Please send a photo/screenshot of your transfer receipt now.**\n\n"
            "💡 *Tip:* If you include the transfer reference number in the photo caption, it will be submitted right away; "
            "otherwise, the bot will ask you for the reference number next."
        ),
        "cancel_reply_hint": "To cancel, tap '❌ Cancel':",
        "receipt_received_ask_ref": (
            "✅ Receipt image received successfully.\n\n"
            "✍️ **Now, please type the transfer reference / transaction ID:**"
        ),
        "order_submitted": (
            "🎉 **Your order has been submitted successfully!**\n\n"
            "🔹 **Order No.:** `{code}`\n"
            "📦 **Product:** {name}\n"
            "🔢 **Quantity:** `{qty}`\n"
            "💳 **Payment Method:** {method}\n"
            "💰 **Amount:** `{total}` {curr}\n"
            "🧾 **Transfer Ref:** `{ref}`\n\n"
            "⏳ Our team is verifying your payment. Your activation details will be delivered right here once approved!"
        ),

        "wallet_dashboard": (
            "👛 **My Electronic Wallet (TOP UP WALLET)**\n"
            "─────────────────────\n"
            "👤 **Account:** {name} (`{uid}`)\n\n"
            "🇩🇿 **DZD Balance:** `{bal_dzd}` {curr}\n"
            "💵 **USD Balance:** `${bal_usd}`\n"
            "─────────────────────\n"
            "💡 **How does the wallet work?**\n"
            "1. Choose the currency you want to top up (**DZD** or **USD**).\n"
            "2. Enter the amount and complete the transfer.\n"
            "3. Send your transfer proof/receipt. Once approved, your balance appears instantly for 1-click purchases!\n\n"
            "👇 Choose an action below:"
        ),
        "btn_topup_dzd": "➕ Top Up in DZD 🇩🇿",
        "btn_topup_usd": "➕ Top Up in USD 💵",
        "btn_wallet_history": "📜 Top-Up History",
        "btn_go_buy": "🛒 Browse Subscriptions",
        "btn_back_wallet": "🔙 Back to Wallet",
        "btn_change_amount": "🔙 Change Amount",
        "btn_wallet_confirm_transfer": "✅ I Transferred — Send Proof / Confirm",
        "no_topups": (
            "📜 **Wallet Top-Up History:**\n\n"
            "You have no previous top-up requests yet.\n"
            "Tap **Top Up** below to add funds to your wallet!"
        ),
        "topups_history_title": "📜 **Your Recent Wallet Top-Ups:**\n─────────────────────\n",
        "topup_status_approved": "✅ Credited",
        "topup_status_pending": "⏳ Pending Review",
        "topup_status_rejected": "❌ Rejected",
        "topup_history_item": (
            "🔹 `{code}` — `{amount}` {curr}\n"
            "• Method: {method} | Status: {status}\n"
            "• Date: `{date}`\n"
        ),
        "topup_reject_reason": "• Reason: {reason}\n",
        "topup_prompt_dzd": (
            "🇩🇿 **Top Up Wallet in DZD:**\n"
            "─────────────────────\n"
            "✍️ **Enter the DZD amount to add (numbers only, or pick a quick preset below):**\n"
            "Example: `2000` or `5000`"
        ),
        "topup_prompt_usd": (
            "💵 **Top Up Wallet in USD:**\n"
            "─────────────────────\n"
            "✍️ **Enter the USD (`$`) amount to add (numbers only, or pick a quick preset below):**\n"
            "Example: `10` or `25`"
        ),
        "topup_invalid_amount": "⚠️ Please enter a valid positive number (e.g., `2000` or `10`).",
        "topup_dzd_step": (
            "👛 **Wallet Top-Up: `{amount}` {curr}**\n"
            "─────────────────────\n"
            "💳 **Method:** BaridiMob\n"
            "💰 **Amount to Transfer:** `{amount}` {curr}\n"
            "─────────────────────\n"
            "{pay_info}\n\n"
            "👇 After transferring, tap the green button below to upload proof or confirm:"
        ),
        "topup_usd_choose_method": (
            "👛 **Wallet Top-Up: `${amount}` USD**\n"
            "─────────────────────\n"
            "💳 **Choose your USD transfer method:**"
        ),
        "topup_usd_step": (
            "👛 **Wallet Top-Up: `${amount}` USD**\n"
            "─────────────────────\n"
            "💳 **Method:** {method}\n"
            "💰 **Amount to Transfer:** `${amount}`\n"
            "─────────────────────\n"
            "{details}\n\n"
            "👇 After transferring, tap the green button below to upload proof or confirm:"
        ),
        "topup_upload_prompt": (
            "📤 **Confirm Wallet Top-Up of `{amount}` {curr}**\n"
            "─────────────────────\n"
            "📸 **Send a screenshot of your transfer receipt**, or **type the transaction reference / confirmation message**:\n\n"
            "⏳ Our admin will verify it and credit your wallet right away!"
        ),
        "topup_upload_hint": "Send your receipt screenshot or transfer reference now (or tap '❌ Cancel'):",
        "topup_session_expired": "⚠️ Session expired, please open your wallet and try again.",
        "topup_submitted": (
            "🎉 **Top-Up Request Submitted!**\n"
            "─────────────────────\n"
            "🔹 **Request ID:** `{code}`\n"
            "💰 **Requested Amount:** `{amount}` {curr}\n"
            "💳 **Payment Method:** {method}\n"
            "🧾 **Reference:** `{ref}`\n"
            "─────────────────────\n"
            "⏳ **Status:** Pending admin confirmation.\n"
            "You will receive an instant notification here as soon as your balance is credited! 🌟"
        ),

        "support_text_received": (
            "✅ **Your message has been forwarded to our support team.**\n"
            "An admin will reply to you right here as soon as possible. Thank you! 🌟"
        ),
        "support_photo_received": (
            "✅ **Your photo has been forwarded to our support team.**\n"
            "An admin will review it and reply shortly."
        ),

        "cust_link_header": "🔗 **Activation Link #{idx}:**",
        "cust_code_header": "🔑 **Activation Credentials / Code #{idx}:**",
        "cust_custom_inst_header": "📘 **Activation Instructions & Terms:**\n{inst}\n\n",
        "cust_gemini_inst": (
            "🌟 **How to Activate:**\n"
            "1. Open the activation link in your browser.\n"
            "2. Sign in with the Google account you want to upgrade to Gemini Pro.\n"
            "3. Confirm/Accept the activation and enjoy! 🚀\n\n"
        ),
        "cust_generic_inst": (
            "🌟 **How to Activate / Use:**\n"
            "1. Use the link or credentials/code above to sign in and activate.\n"
            "2. Official subscription with full store warranty for the entire duration.\n"
            "3. Need any help? Just message us right here! 🚀\n\n"
        ),
        "cust_delivery_msg": (
            "🎉 **Congratulations! Your payment has been confirmed!**\n"
            "─────────────────────\n"
            "🔹 **Order No.:** `{code}`\n"
            "📦 **Product:** {name}\n"
            "🔢 **Quantity:** {qty}\n"
            "─────────────────────\n\n"
            "{items}"
            "{instructions}"
            "Thank you for your trust, enjoy! 🌟"
        ),
        "cust_order_wait": (
            "⏳ **Hello valued customer!**\n\n"
            "📌 Regarding your order: `{code}`\n"
            "📦 Product: **{name}**\n\n"
            "🛠 **Your order is currently being prepared and activated by our team.**\n"
            "Please wait a few minutes — your activation details will arrive right here as soon as it's ready! 🚀\n\n"
            "Thank you for your patience! 🌟"
        ),
        "cust_order_rejected": (
            "❌ **Sorry, your order `{code}` has been rejected.**\n\n"
            "⚠️ **Reason:** {reason}\n\n"
            "If you believe this is a mistake or would like to try again, please check your transfer details or message us."
        ),
        "cust_admin_msg_order": (
            "📩 **Message from Store Support regarding order `{code}`:**\n\n"
            "{msg}\n\n"
            "─────────────────\n"
            "💬 You can reply directly to this message."
        ),
        "cust_admin_msg_direct": (
            "📩 **Message from Store Support{prefix}:**\n\n"
            "{msg}\n\n"
            "─────────────────\n"
            "💬 You can reply directly to this message."
        ),
        "cust_admin_order_prefix": " regarding order `{code}`",
        "cust_topup_approved": (
            "🎉 **Your Wallet Top-Up Has Been Approved!**\n"
            "─────────────────────\n"
            "🔹 **Request ID:** `{code}`\n"
            "➕ **Amount Credited:** `{amt}` {curr}\n\n"
            "👛 **Your Updated Wallet Balance:**\n"
            "• 🇩🇿 DZD: **`{bal_dzd}` {dzd_curr}**\n"
            "• 💵 USD: **`${bal_usd}`**\n"
            "─────────────────────\n"
            "You can now purchase any subscription instantly using your wallet balance! 🚀"
        ),
        "cust_topup_rejected": (
            "❌ **Sorry, your wallet top-up request `{code}` was rejected.**\n\n"
            "⚠️ **Reason:** {reason}\n\n"
            "Please check your transfer receipt or contact support for assistance."
        ),
        "cust_manual_wallet_credit": (
            "🎉 **Funds have been added to your wallet by an admin!**\n\n"
            "➕ **Amount Added:** `{amt}` {curr}\n"
            "👛 **Current Balance:** `{bal_dzd}` {dzd_curr} | `${bal_usd}`"
        ),

        "baridimob_name": "BaridiMob",
        "baridimob_details": (
            "🏦 **Pay via BaridiMob:**\n"
            "• Account / RIP: `00799999000123456789`\n"
            "• Name: Digital Store\n"
            "• Phone / ID: `0555000000`"
        ),
        "redotpay_details": (
            "💳 **Pay via RedotPay:**\n"
            "• Account UID: `1445653765`\n"
            "• Transfer Type: Internal transfer via RedotPay ID (Instant & 0 fees)"
        ),
        "bybit_details": (
            "🟡 **Pay via Bybit:**\n"
            "• Account UID: `593583401`\n"
            "• Currency: USDT\n"
            "• Transfer Type: Internal transfer via Bybit UID (Instant & 0 network fees)"
        ),
    },

    "fr": {
        "choose_language_prompt": (
            "🌐 **Choisissez votre langue / Choose Your Language / اختر لغتك:**\n\n"
            "• 🇩🇿 العربية\n"
            "• 🇬🇧 English\n"
            "• 🇫🇷 Français"
        ),
        "lang_saved_toast": "✅ Langue française sélectionnée !",
        "btn_change_lang": "🌐 Langue",

        "force_join_title": "🔒 **Pour utiliser la boutique et voir les produits, veuillez d'abord rejoindre nos chaînes officielles :**",
        "force_join_desc": (
            "👇 Rejoignez la chaîne et le groupe ci-dessous, puis appuyez sur **'✅ J'ai rejoint — Vérifier'** pour accéder aux produits et au portefeuille :"
        ),
        "force_join_chat_note": "💡 *Astuce :* Pour accéder au chat, ouvrez la chaîne et appuyez sur **Discuter (Discuss)** en bas si le lien direct n'est pas affiché.",
        "force_join_btn_verify": "✅ J'ai rejoint — Vérifier",
        "force_join_status_joined": "✅ Rejoint",
        "force_join_status_missing": "❌ Pas encore rejoint",
        "force_join_not_yet_alert": "⚠️ Vous n'avez pas encore rejoint : {missing}\nVeuillez d'abord rejoindre puis réessayer.",
        "force_join_verified_toast": "✅ Adhésion vérifiée ! Bienvenue dans la boutique 🎉",
        "force_join_join_prefix": "Rejoindre :",

        "menu_buy": "🛒 Acheter un abonnement",
        "menu_wallet": "👛 Mon Portefeuille (Top Up)",
        "menu_orders": "📦 Mes Commandes",
        "menu_help": "📘 Support & Aide",
        "menu_admin": "⚙️ لوحة تحكم الإدارة",
        "menu_cancel": "❌ Annuler",

        "welcome": (
            "Bienvenue **{name}** dans la **Boutique d'Abonnements Numériques** 🤖✨\n\n"
            "Nous proposons des abonnements officiels aux meilleurs prix avec garantie complète.\n\n"
            "👛 **Solde actuel de votre portefeuille :** `{dzd}` {curr} | `${usd}`\n\n"
            "📌 **Offres populaires disponibles :**\n{products_list}\n"
            "Choisissez une option ci-dessous pour commencer 👇"
        ),
        "more_products_note": "• 🛍️ _Et `{count}` autres offres et produits dans le catalogue..._\n",

        "help_text": (
            "📘 **À propos du service, achat et activation :**\n\n"
            "1. Rechargez votre portefeuille en DA ou USD via **'👛 Mon Portefeuille (Top Up)'** pour payer instantanément en un clic.\n"
            "2. Ou choisissez un produit, payez directement et envoyez votre reçu de transfert.\n"
            "3. Chaque produit dispose d'un bouton bleu **'📖 Instructions et conditions'** détaillant l'activation et la garantie.\n\n"
            "📞 Besoin d'aide ? Envoyez simplement votre message ici et notre équipe vous répondra rapidement."
        ),

        "no_orders": "📦 Vous n'avez aucune commande précédente pour le moment.\nAppuyez sur '🛒 Acheter un abonnement' pour passer votre première commande !",
        "recent_orders_title": "📦 **Vos dernières commandes :**\n\n",
        "status_pending": "⏳ En cours de vérification",
        "status_approved": "✅ Terminée et livrée",
        "status_rejected": "❌ Refusée",
        "order_item": (
            "🔹 **Commande N° :** `{code}`\n"
            "• Produit : {product} (Qté : `{qty}`)\n"
            "• Montant : `{total}` {curr}\n"
            "• Statut : {status}\n"
            "• Date : `{date}`\n"
        ),
        "delivered_links_label": "🔗 **Liens / Identifiants d'activation livrés :**\n`{links}`\n",
        "reject_reason_label": "⚠️ **Motif du refus :** {reason}\n",

        "choose_brand": "🛒 **Choisissez une marque pour parcourir les produits :**",
        "btn_other_brands": "🛍️ Autres offres et produits",
        "btn_back_menu": "🔙 Retour au menu",
        "btn_back_categories": "🔙 Retour aux catégories",
        "btn_back_products": "🔙 Retour aux produits",
        "btn_back_product_list": "🔙 Retour à la liste des produits",
        "btn_back_quantity": "🔙 Retour à la quantité",
        "btn_cancel": "❌ Annuler",
        "btn_cancel_order": "❌ Annuler la commande",
        "btn_prev": "⬅️ Précédent",
        "btn_next": "Suivant ➡️",
        "no_products_in_cat": "{title}\n\n⚠️ Désolé, aucun produit disponible dans cette catégorie pour le moment.",
        "cat_page_note": " (Page {page} sur {total})",
        "cat_products_header": (
            "{title}{page_note}\n"
            "Total des offres dans cette catégorie : `{total_items}`.\n"
            "Choisissez votre offre (ou appuyez sur **Suivant ➡️** pour voir plus) :"
        ),
        "session_cancelled": "❌ Opération annulée.",
        "session_cancelled_main": "❌ Opération annulée. Retour au menu principal.",
        "product_unavailable": "⚠️ Désolé, ce produit est actuellement indisponible.",
        "product_not_found": "⚠️ Désolé, produit introuvable.",
        "product_detail": (
            "💎 **Produit sélectionné :** {name}\n"
            "🇩🇿 **Prix en Dinars :** `{price_dzd}` {curr}\n"
            "💵 **Prix en Dollars :** `${price_usd}`\n\n"
            "📝 **Description :**\n{desc}\n\n"
            "🔢 **Veuillez choisir la quantité souhaitée (ou appuyez sur le bouton bleu d'instructions) :**"
        ),
        "btn_prod_instructions": "🔵 📖 Instructions et conditions du produit",
        "btn_prod_instructions_short": "🔵 📖 Instructions du produit",
        "btn_continue_buy": "🛒 Continuer l'achat de ce produit",
        "prod_inst_toast": "📖 Instructions et conditions",
        "prod_inst_view": (
            "🔵 📖 **Instructions et conditions du produit :**\n"
            "─────────────────────\n"
            "📦 **Produit :** {name}\n"
            "💰 **Prix :** `{price_dzd}` {curr} | `${price_usd}`\n"
            "─────────────────────\n\n"
            "📋 **Instructions et guide d'activation :**\n"
            "{inst}\n\n"
            "─────────────────────\n"
            "👇 Appuyez sur **'🛒 Continuer l'achat de ce produit'** pour choisir la quantité :"
        ),
        "default_inst_fallback": "Abonnement officiel avec garantie complète et livraison instantanée.",

        "choose_payment": (
            "📦 **Produit :** {name}\n"
            "🔢 **Quantité :** `{qty}`\n"
            "💵 **Total :** `{total_dzd}` {curr} ou `${total_usd}`\n"
            "👛 **Solde de votre portefeuille :** `{bal_dzd}` {curr} | `${bal_usd}`\n\n"
            "💳 **Veuillez choisir votre moyen de paiement :**"
        ),
        "choose_payment_change": (
            "📦 **Produit :** {name}\n"
            "🔢 **Quantité :** `{qty}`\n\n"
            "💳 **Veuillez choisir votre moyen de paiement :**"
        ),
        "btn_pay_wallet_dzd": "👛 Payer par portefeuille DA{dzd_part}",
        "btn_pay_wallet_usd": "👛 Payer par portefeuille USD (${total_usd})",
        "btn_pay_baridimob": "🏦 BaridiMob{dzd_part}",
        "btn_pay_redotpay": "💳 RedotPay (${total_usd})",
        "btn_pay_bybit": "🟡 Bybit (${total_usd})",
        "btn_upload_receipt": "📤 Envoyer le reçu et la référence",
        "btn_change_payment": "🔙 Changer de mode de paiement",
        "btn_confirm_wallet_pay": "✅ Confirmer le débit et recevoir immédiatement",
        "btn_topup_now": "➕ Recharger le portefeuille (Top Up)",
        "btn_choose_other_pay": "🔙 Choisir un autre mode de paiement",
        "wallet_dzd_name": "Portefeuille DA 👛",
        "wallet_usd_name": "Portefeuille USD 👛",
        "insufficient_balance": (
            "⚠️ **Solde du portefeuille insuffisant pour cet achat !**\n"
            "─────────────────\n"
            "📦 **Produit :** {name} (x{qty})\n"
            "💰 **Montant requis :** `{total}` {curr}\n"
            "👛 **Votre solde ({method}) :** `{bal}` {curr}\n"
            "📉 **Montant manquant :** `{needed}` {curr}\n"
            "─────────────────\n\n"
            "💡 Vous pouvez recharger votre portefeuille maintenant via **Top Up** ou choisir un autre mode de paiement :"
        ),
        "confirm_wallet_pay_text": (
            "👛 **Confirmation du paiement instantané par portefeuille :**\n"
            "─────────────────\n"
            "📦 **Produit :** {name}\n"
            "🔢 **Quantité :** `{qty}`\n"
            "💳 **Moyen de paiement :** {method}\n"
            "💰 **Montant à débiter :** `{total}` {curr}\n"
            "👛 **Solde actuel :** `{bal}` {curr}\n"
            "✅ **Solde restant après achat :** `{remaining}` {curr}\n"
            "─────────────────\n\n"
            "👇 Appuyez sur le bouton vert ci-dessous pour confirmer et recevoir votre abonnement :"
        ),
        "order_summary": (
            "📋 **Récapitulatif de votre commande :**\n"
            "─────────────────\n"
            "📦 **Produit :** {name}\n"
            "🔢 **Quantité :** `{qty}`\n"
            "💳 **Moyen de paiement :** {method}\n"
            "💰 **Montant total à payer :** `{total}` {curr}\n"
            "─────────────────\n"
            "{instructions}\n\n"
            "👇 Appuyez sur le bouton ci-dessous une fois prêt à envoyer le reçu et la référence :"
        ),
        "session_expired": "⚠️ Session expirée, veuillez recommencer votre commande.",
        "session_expired_restart": "⚠️ Une erreur est survenue ou la session a expiré. Veuillez recommencer.",
        "wallet_dzd_insufficient_toast": "⚠️ Solde du portefeuille DA insuffisant !",
        "wallet_usd_insufficient_toast": "⚠️ Solde du portefeuille USD insuffisant !",
        "processing_wallet_order": "⏳ Débit en cours et préparation de votre abonnement...",
        "wallet_pay_ref": "Payé par portefeuille ({total} {curr})",
        "wallet_instant_success": (
            "✅ **Paiement par portefeuille effectué et commande `{code}` livrée immédiatement !**\n\n"
            "📦 **Produit :** {name}\n"
            "💰 **Montant débité :** `{total}` {curr}\n"
            "👛 **Solde restant :** `{bal_dzd}` {dzd_curr} | `${bal_usd}`\n\n"
            "Vos liens/identifiants d'activation ont été envoyés ci-dessus. Merci pour votre confiance ! 🚀"
        ),
        "wallet_manual_pending": (
            "🎉 **Montant débité et commande `{code}` confirmée !**\n\n"
            "📦 **Produit :** {name} (x`{qty}`)\n"
            "💰 **Montant payé :** `{total}` {curr}\n"
            "👛 **Solde restant :** `{bal_dzd}` {dzd_curr} | `${bal_usd}`\n\n"
            "⏳ **Statut :** Votre abonnement est en cours de préparation manuelle par notre administrateur et vous parviendra très vite ! 🌟"
        ),
        "upload_receipt_prompt": (
            "📸 **Veuillez envoyer la photo / capture d'écran de votre reçu de transfert.**\n\n"
            "💡 *Astuce :* Si vous indiquez le numéro de référence en légende de la photo, la commande sera envoyée immédiatement ; "
            "sinon le bot vous demandera le numéro ensuite."
        ),
        "cancel_reply_hint": "Pour annuler, appuyez sur '❌ Annuler' :",
        "receipt_received_ask_ref": (
            "✅ Photo du reçu bien reçue.\n\n"
            "✍️ **Veuillez maintenant saisir le numéro de référence du transfert :**"
        ),
        "order_submitted": (
            "🎉 **Votre commande a été envoyée avec succès !**\n\n"
            "🔹 **Commande N° :** `{code}`\n"
            "📦 **Produit :** {name}\n"
            "🔢 **Quantité :** `{qty}`\n"
            "💳 **Moyen de paiement :** {method}\n"
            "💰 **Montant :** `{total}` {curr}\n"
            "🧾 **Référence :** `{ref}`\n\n"
            "⏳ Notre équipe vérifie votre paiement. Vos accès seront livrés ici dès validation !"
        ),

        "wallet_dashboard": (
            "👛 **Mon Portefeuille Électronique (TOP UP WALLET)**\n"
            "─────────────────────\n"
            "👤 **Compte :** {name} (`{uid}`)\n\n"
            "🇩🇿 **Solde en Dinars (DA) :** `{bal_dzd}` {curr}\n"
            "💵 **Solde en Dollars (USD) :** `${bal_usd}`\n"
            "─────────────────────\n"
            "💡 **Comment fonctionne le portefeuille ?**\n"
            "1. Choisissez la devise à recharger (**DA** ou **USD**).\n"
            "2. Saisissez le montant et effectuez le virement.\n"
            "3. Envoyez le justificatif. Dès validation par l'admin, le solde apparaît pour acheter en un clic !\n\n"
            "👇 Choisissez une opération ci-dessous :"
        ),
        "btn_topup_dzd": "➕ Recharger en Dinars 🇩🇿 (Top Up DZD)",
        "btn_topup_usd": "➕ Recharger en Dollars 💵 (Top Up USD)",
        "btn_wallet_history": "📜 Historique des recharges",
        "btn_go_buy": "🛒 Acheter un abonnement",
        "btn_back_wallet": "🔙 Retour au portefeuille",
        "btn_change_amount": "🔙 Changer le montant",
        "btn_wallet_confirm_transfer": "✅ J'ai transféré — Envoyer la preuve",
        "no_topups": (
            "📜 **Historique des recharges :**\n\n"
            "Vous n'avez aucune demande de recharge pour le moment.\n"
            "Appuyez sur **Recharger** ci-dessous pour ajouter du solde !"
        ),
        "topups_history_title": "📜 **Vos dernières recharges de portefeuille :**\n─────────────────────\n",
        "topup_status_approved": "✅ Crédité",
        "topup_status_pending": "⏳ En attente",
        "topup_status_rejected": "❌ Refusé",
        "topup_history_item": (
            "🔹 `{code}` — `{amount}` {curr}\n"
            "• Méthode : {method} | Statut : {status}\n"
            "• Date : `{date}`\n"
        ),
        "topup_reject_reason": "• Motif : {reason}\n",
        "topup_prompt_dzd": (
            "🇩🇿 **Recharger le portefeuille en Dinars (DA) :**\n"
            "─────────────────────\n"
            "✍️ **Saisissez le montant en DA à recharger (chiffres uniquement, ou choisissez un montant rapide) :**\n"
            "Exemple : `2000` ou `5000`"
        ),
        "topup_prompt_usd": (
            "💵 **Recharger le portefeuille en Dollars (USD) :**\n"
            "─────────────────────\n"
            "✍️ **Saisissez le montant en USD (`$`) à recharger (chiffres uniquement, ou choisissez un montant rapide) :**\n"
            "Exemple : `10` ou `25`"
        ),
        "topup_invalid_amount": "⚠️ Veuillez saisir un montant numérique valide supérieur à zéro (ex : `2000` ou `10`).",
        "topup_dzd_step": (
            "👛 **Recharge de `{amount}` {curr}**\n"
            "─────────────────────\n"
            "💳 **Méthode :** BaridiMob\n"
            "💰 **Montant à transférer :** `{amount}` {curr}\n"
            "─────────────────────\n"
            "{pay_info}\n\n"
            "👇 Après le transfert, appuyez sur le bouton vert ci-dessous pour envoyer la preuve :"
        ),
        "topup_usd_choose_method": (
            "👛 **Recharge de `${amount}` USD**\n"
            "─────────────────────\n"
            "💳 **Choisissez votre méthode de transfert en USD :**"
        ),
        "topup_usd_step": (
            "👛 **Recharge de `${amount}` USD**\n"
            "─────────────────────\n"
            "💳 **Méthode :** {method}\n"
            "💰 **Montant à transférer :** `${amount}`\n"
            "─────────────────────\n"
            "{details}\n\n"
            "👇 Après le transfert, appuyez sur le bouton vert ci-dessous pour envoyer la preuve :"
        ),
        "topup_upload_prompt": (
            "📤 **Confirmation de recharge de `{amount}` {curr}**\n"
            "─────────────────────\n"
            "📸 **Envoyez maintenant la capture d'écran du reçu**, ou **écrivez le numéro de référence du transfert** :\n\n"
            "⏳ L'administrateur vérifiera et créditera votre portefeuille immédiatement !"
        ),
        "topup_upload_hint": "Envoyez la capture d'écran ou la référence maintenant (ou appuyez sur '❌ Annuler') :",
        "topup_session_expired": "⚠️ Session expirée, veuillez ouvrir votre portefeuille et réessayer.",
        "topup_submitted": (
            "🎉 **Demande de recharge envoyée avec succès !**\n"
            "─────────────────────\n"
            "🔹 **Demande N° :** `{code}`\n"
            "💰 **Montant demandé :** `{amount}` {curr}\n"
            "💳 **Moyen de paiement :** {method}\n"
            "🧾 **Référence :** `{ref}`\n"
            "─────────────────────\n"
            "⏳ **Statut :** En attente de confirmation.\n"
            "Vous recevrez une notification ici dès que votre solde sera crédité ! 🌟"
        ),

        "support_text_received": (
            "✅ **Votre message a bien été transmis au support de la boutique.**\n"
            "Un administrateur vous répondra ici très prochainement. Merci ! 🌟"
        ),
        "support_photo_received": (
            "✅ **Votre photo a bien été transmise au support de la boutique.**\n"
            "Un administrateur l'examinera et vous répondra bientôt."
        ),

        "cust_link_header": "🔗 **Lien d'activation #{idx} :**",
        "cust_code_header": "🔑 **Identifiants / Code d'activation #{idx} :**",
        "cust_custom_inst_header": "📘 **Instructions et conditions d'activation :**\n{inst}\n\n",
        "cust_gemini_inst": (
            "🌟 **Comment activer :**\n"
            "1. Ouvrez le lien d'activation dans votre navigateur.\n"
            "2. Connectez-vous avec le compte Google à activer sur Gemini Pro.\n"
            "3. Confirmez/Acceptez l'activation et profitez de votre abonnement ! 🚀\n\n"
        ),
        "cust_generic_inst": (
            "🌟 **Comment activer / utiliser :**\n"
            "1. Utilisez le lien ou les identifiants ci-dessus pour vous connecter et activer.\n"
            "2. Abonnement officiel avec garantie complète de la boutique.\n"
            "3. Besoin d'aide ? Écrivez-nous directement ici ! 🚀\n\n"
        ),
        "cust_delivery_msg": (
            "🎉 **Félicitations ! Votre paiement a été confirmé !**\n"
            "─────────────────────\n"
            "🔹 **Commande N° :** `{code}`\n"
            "📦 **Produit :** {name}\n"
            "🔢 **Quantité :** {qty}\n"
            "─────────────────────\n\n"
            "{items}"
            "{instructions}"
            "Merci pour votre confiance et bonne utilisation ! 🌟"
        ),
        "cust_order_wait": (
            "⏳ **Bonjour cher client !**\n\n"
            "📌 Concernant votre commande : `{code}`\n"
            "📦 Produit : **{name}**\n\n"
            "🛠 **Votre commande est en cours de préparation et d'activation par notre équipe.**\n"
            "Merci de patienter quelques minutes — vos accès arriveront ici dès que tout sera prêt ! 🚀\n\n"
            "Merci pour votre patience ! 🌟"
        ),
        "cust_order_rejected": (
            "❌ **Désolé, votre commande `{code}` a été refusée.**\n\n"
            "⚠️ **Motif :** {reason}\n\n"
            "Si vous pensez qu'il s'agit d'une erreur, vérifiez votre justificatif ou contactez-nous ici."
        ),
        "cust_admin_msg_order": (
            "📩 **Message du support concernant votre commande `{code}` :**\n\n"
            "{msg}\n\n"
            "─────────────────\n"
            "💬 Vous pouvez répondre directement à ce message."
        ),
        "cust_admin_msg_direct": (
            "📩 **Message du support de la boutique{prefix} :**\n\n"
            "{msg}\n\n"
            "─────────────────\n"
            "💬 Vous pouvez répondre directement à ce message."
        ),
        "cust_admin_order_prefix": " concernant la commande `{code}`",
        "cust_topup_approved": (
            "🎉 **Votre recharge de portefeuille a été approuvée !**\n"
            "─────────────────────\n"
            "🔹 **Demande N° :** `{code}`\n"
            "➕ **Montant crédité :** `{amt}` {curr}\n\n"
            "👛 **Votre nouveau solde :**\n"
            "• 🇩🇿 DA : **`{bal_dzd}` {dzd_curr}**\n"
            "• 💵 USD : **`${bal_usd}`**\n"
            "─────────────────────\n"
            "Vous pouvez maintenant acheter n'importe quel abonnement en un clic ! 🚀"
        ),
        "cust_topup_rejected": (
            "❌ **Désolé, votre demande de recharge `{code}` a été refusée.**\n\n"
            "⚠️ **Motif :** {reason}\n\n"
            "Veuillez vérifier votre reçu de transfert ou nous contacter pour obtenir de l'aide."
        ),
        "cust_manual_wallet_credit": (
            "🎉 **Du solde a été ajouté à votre portefeuille par un administrateur !**\n\n"
            "➕ **Montant ajouté :** `{amt}` {curr}\n"
            "👛 **Solde actuel :** `{bal_dzd}` {dzd_curr} | `${bal_usd}`"
        ),

        "baridimob_name": "BaridiMob",
        "baridimob_details": (
            "🏦 **Payer via BaridiMob :**\n"
            "• Compte / RIP : `00799999000123456789`\n"
            "• Nom : Boutique Numérique\n"
            "• Téléphone / ID : `0555000000`"
        ),
        "redotpay_details": (
            "💳 **Payer via RedotPay :**\n"
            "• UID du compte : `1445653765`\n"
            "• Type de transfert : Transfert interne via RedotPay ID (Instantané, 0 frais)"
        ),
        "bybit_details": (
            "🟡 **Payer via Bybit :**\n"
            "• UID du compte : `593583401`\n"
            "• Devise : USDT\n"
            "• Type de transfert : Transfert interne via Bybit UID (Instantané, 0 frais réseau)"
        ),
    },
}


def t(lang: str | None, key: str, **kwargs) -> str:
    """Lookup localized UI string and safely format placeholders."""
    l = lang if lang in SUPPORTED_LANGS else "ar"
    template = TRANSLATIONS.get(l, {}).get(key) or TRANSLATIONS["ar"].get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template


# ==================== Category Titles ====================

_CATEGORY_META: dict[str, tuple[str, str]] = {
    "gemini": ("🟢 ✨", "Google Gemini"),
    "claude": ("🔴 ✴️", "Claude AI"),
    "chatgpt": ("🤖", "ChatGPT & OpenAI"),
    "kiro": ("👻", "kiro"),
    "elevenlabs": ("⏸️", "ElevenLabs"),
    "cursor": ("🧊", "Cursor"),
    "adobe": ("🎨", "Adobe"),
    "grok": ("🪐", "Grok"),
    "antigravity": ("🚀", "Antigravity"),
    "perplexity": ("✳️", "Perplexity"),
    "lovable": ("💝", "Lovable"),
    "heygen": ("💎", "HeyGen"),
    "capcut": ("🎬", "CapCut"),
    "notion": ("📓", "Notion"),
    "youtube": ("▶️", "YouTube"),
    "runway": ("🎥", "Runway"),
    "higgsfield": ("⚡", "Higgsfield"),
    "telegram": ("⭐", "Telegram"),
    "canva": ("🎨", "Canva"),
    "netflix": ("🍿", "Netflix"),
    "kling": ("🌀", "Kling"),
    "spotify": ("🎵", "Spotify"),
    "suno": ("🎶", "Suno"),
    "krea": ("🖼️", "Krea"),
}


def get_category_title(cat: str, lang: str = "ar") -> str:
    if cat == "other":
        return {
            "ar": "🛍️ **الباقات والمنتجات الرقمية الأخرى:**",
            "en": "🛍️ **Other Digital Plans & Subscriptions:**",
            "fr": "🛍️ **Autres offres et abonnements numériques :**",
        }.get(lang, "🛍️ **الباقات والمنتجات الرقمية الأخرى:**")

    if cat in _CATEGORY_META:
        emoji, label = _CATEGORY_META[cat]
        if lang == "en":
            return f"{emoji} **{label} Plans & Subscriptions:**"
        if lang == "fr":
            return f"{emoji} **Abonnements et offres {label} :**"
        return f"{emoji} **منتجات واشتراكات {label}:**"

    if lang == "en":
        return f"🛍️ **{cat} Products:**"
    if lang == "fr":
        return f"🛍️ **Produits {cat} :**"
    return f"🛍️ **منتجات {cat}:**"


def get_payment_method_name(method_id: str, lang: str = "ar") -> str:
    if method_id == "baridimob":
        return t(lang, "baridimob_name")
    if method_id == "redotpay":
        return "RedotPay (2.5$)"
    if method_id == "bybit":
        return "Bybit (2.5$)"
    if method_id == "wallet_dzd":
        return t(lang, "wallet_dzd_name")
    if method_id == "wallet_usd":
        return t(lang, "wallet_usd_name")
    return method_id


def get_payment_method_details(method_id: str, lang: str = "ar") -> str:
    if method_id == "redotpay":
        return t(lang, "redotpay_details")
    if method_id == "bybit":
        return t(lang, "bybit_details")
    return t(lang, "baridimob_details")


# ==================== Smart Store Translation Engine ====================

_MEMORY_TRANS_CACHE: dict[str, str] = {}

# Brand & technical terms that MUST stay intact across all languages
_PROTECTED_BRANDS = [
    "Google Gemini Pro", "Google AI Pro", "Gemini Advanced", "Gemini Pro", "Gemini",
    "Google One", "Google", "YouTube Music Premium", "YouTube Premium", "YouTube",
    "ChatGPT Plus", "ChatGPT", "OpenAI Codex", "OpenAI", "GPT-4o", "Codex API", "Codex",
    "Claude API", "Anthropic Claude", "Anthropic", "Claude",
    "ElevenLabs Creator", "ElevenLabs", "ElevenReader",
    "Adobe Express Premium", "Adobe Express", "Creative Cloud", "Adobe Stock", "Adobe",
    "Lovable Pro Lite", "Lovable Pro", "Lovable",
    "Coursera Premium", "Coursera", "Duolingo Super", "Duolingo",
    "CapCut Pro", "CapCut", "Apple Music", "NordVPN", "Cursor", "Antigravity",
    "Perplexity", "HeyGen", "Notion", "Runway", "Higgsfield", "Telegram",
    "Canva Pro", "Canva", "Netflix", "Kling", "Spotify", "Suno", "Krea", "Grok", "kiro",
    "BaridiMob", "RedotPay", "Bybit", "USDT", "RIP", "UID", "API", "Tokens", "Pro Lite",
]
_PROTECTED_BRAND_RE = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(re.escape(b) for b in sorted(_PROTECTED_BRANDS, key=len, reverse=True)) + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# Instant offline phrase rules for titles (fast, deterministic, zero-latency)
_TITLE_RULES: dict[str, list[tuple[re.Pattern, str]]] = {
    "ar": [
        (re.compile(r"\b(\d+)\s*Months?\b", re.I), r"\1 شهر"),
        (re.compile(r"\b(\d+)\s*Years?\b", re.I), r"\1 سنة"),
        (re.compile(r"\b(\d+)\s*Days?\b", re.I), r"\1 يوم"),
        (re.compile(r"\b(\d+)\s*Credits?\b", re.I), r"\1 رصيد"),
        (re.compile(r"\b(\d+[MK]?)\s*Tokens?\b", re.I), r"\1 توكن"),
        (re.compile(r"\bLifetime\b", re.I), "مدى الحياة"),
        (re.compile(r"\bPrivate Account\b", re.I), "حساب خاص"),
        (re.compile(r"\bShared Account\b", re.I), "حساب مشترك"),
        (re.compile(r"\bActivation Link\b", re.I), "رابط تفعيل"),
        (re.compile(r"\bTrial\b", re.I), "تجريبي"),
        (re.compile(r"\bBasic\b", re.I), "الأساسي"),
        (re.compile(r"\bIndividual\b", re.I), "فردي"),
        (re.compile(r"\bFamily\b", re.I), "عائلي"),
        (re.compile(r"\bPersonal\b", re.I), "شخصي"),
        (re.compile(r"\bLinks?\b", re.I), "روابط"),
    ],
    "fr": [
        (re.compile(r"\b(\d+)\s*Months?\b", re.I), r"\1 mois"),
        (re.compile(r"\b(\d+)\s*Years?\b", re.I), r"\1 an(s)"),
        (re.compile(r"\b(\d+)\s*Days?\b", re.I), r"\1 jours"),
        (re.compile(r"\b(\d+)\s*Credits?\b", re.I), r"\1 crédits"),
        (re.compile(r"\bLifetime\b", re.I), "À vie"),
        (re.compile(r"\bPrivate Account\b", re.I), "Compte privé"),
        (re.compile(r"\bShared Account\b", re.I), "Compte partagé"),
        (re.compile(r"\bActivation Link\b", re.I), "Lien d'activation"),
        (re.compile(r"\bTrial\b", re.I), "Essai"),
        (re.compile(r"\bBasic\b", re.I), "Basique"),
        (re.compile(r"\bIndividual\b", re.I), "Individuel"),
        (re.compile(r"\bFamily\b", re.I), "Famille"),
        (re.compile(r"\bPersonal\b", re.I), "Personnel"),
        (re.compile(r"\bLinks?\b", re.I), "Liens"),
    ],
    "en": [],
}


def _has_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def _looks_french(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    if re.search(r"[àâäéèêëîïôöùûüçœ]", low):
        return True
    fr_markers = (" mois", " jours", " pour ", " avec ", " compte", " abonnement", " sans ")
    return any(m in low for m in fr_markers)


def _needs_translation(text: str, target_lang: str) -> bool:
    if not text or not text.strip():
        return False
    has_ar = _has_arabic(text)
    if target_lang == "ar":
        # Needs translation if it has Latin words (outside protected brands/URLs)
        stripped = _PROTECTED_BRAND_RE.sub("", re.sub(r"https?://\S+", "", text))
        return bool(re.search(r"[A-Za-z]{2,}", stripped))
    if target_lang == "en":
        return has_ar or _looks_french(text)
    if target_lang == "fr":
        return has_ar or not _looks_french(text)
    return True


def _protect_tokens(text: str) -> tuple[str, list[str]]:
    """Replace URLs, emails, inline code, and brand names with [[N]] placeholders."""
    tokens: list[str] = []

    def _stash(match: re.Match) -> str:
        idx = len(tokens)
        tokens.append(match.group(0))
        return f"[[{idx}]]"

    out = re.sub(r"`[^`\n]+`", _stash, text)
    out = re.sub(r"https?://\S+", _stash, out)
    out = re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", _stash, out)
    out = _PROTECTED_BRAND_RE.sub(_stash, out)
    return out, tokens


def _restore_tokens(text: str, tokens: list[str]) -> str:
    def _unstash(match: re.Match) -> str:
        idx = int(match.group(1))
        return tokens[idx] if 0 <= idx < len(tokens) else match.group(0)

    return re.sub(r"\[\[\s*(\d+)\s*\]\]", _unstash, text)


async def _google_translate_raw(text: str, target_lang: str) -> str | None:
    if not text or not text.strip():
        return text
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": target_lang,
        "dt": "t",
        "q": text,
    }
    try:
        async with httpx.AsyncClient(timeout=5.5) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data and isinstance(data[0], list):
                    translated = "".join(seg[0] for seg in data[0] if isinstance(seg, list) and seg and seg[0])
                    if translated.strip():
                        return translated
    except Exception as e:
        logger.debug(f"Smart translate fallback ({target_lang}): {e}")
    return None


async def smart_translate(text: str, target_lang: str) -> str:
    """
    Smart, brand-preserving async translator with memory + SQLite persistent cache.
    Translates English/Arabic/French store content cleanly into target_lang.
    """
    if not text or not text.strip():
        return text or ""
    if target_lang not in SUPPORTED_LANGS:
        return text
    if not _needs_translation(text, target_lang):
        return text

    src_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    cache_key = f"{target_lang}:{src_hash}"

    if cache_key in _MEMORY_TRANS_CACHE:
        return _MEMORY_TRANS_CACHE[cache_key]

    import database
    db_cached = await database.get_cached_translation(cache_key)
    if db_cached:
        _MEMORY_TRANS_CACHE[cache_key] = db_cached
        return db_cached

    protected_text, tokens = _protect_tokens(text)
    # If everything was protected (e.g., pure brand name or URL), return original
    if not re.sub(r"\[\[\d+\]\]|\W+|\d+", "", protected_text).strip():
        return text

    # Translate line-by-line to preserve bullet formatting cleanly
    lines = protected_text.split("\n")
    non_empty_indices = [i for i, ln in enumerate(lines) if re.sub(r"\[\[\d+\]\]|\W+|\d+", "", ln).strip()]

    translated_lines = list(lines)
    if non_empty_indices:
        joined = "\n".join(lines[i] for i in non_empty_indices)
        raw_res = await _google_translate_raw(joined, target_lang)
        if raw_res:
            parts = raw_res.split("\n")
            if len(parts) == len(non_empty_indices):
                for idx, tr_line in zip(non_empty_indices, parts):
                    translated_lines[idx] = tr_line
            else:
                # Fallback single-block restore
                restored_full = _restore_tokens(raw_res, tokens)
                _MEMORY_TRANS_CACHE[cache_key] = restored_full
                await database.save_cached_translation(cache_key, target_lang, src_hash, restored_full)
                return restored_full

    final_text = _restore_tokens("\n".join(translated_lines), tokens)
    if final_text != text:
        _MEMORY_TRANS_CACHE[cache_key] = final_text
        await database.save_cached_translation(cache_key, target_lang, src_hash, final_text)
    return final_text


async def smart_translate_title(title: str, target_lang: str) -> str:
    """
    Fast, smart product title translator:
    - Applies deterministic duration/plan rules first (preserving brands like Gemini Pro, ChatGPT Plus).
    - If non-brand words remain untranslated (e.g. Arabic admin product viewed in EN/FR), uses cached smart_translate.
    """
    if not title or target_lang not in SUPPORTED_LANGS:
        return title or ""

    has_ar = _has_arabic(title)
    # English original viewed in English
    if target_lang == "en" and not has_ar and not _looks_french(title):
        return title

    # If Arabic title viewed in Arabic
    if target_lang == "ar" and has_ar and not re.search(r"\b(months?|years?|days?|trial|basic|private|shared|lifetime)\b", title, re.I):
        return title

    out = title
    for pat, repl in _TITLE_RULES.get(target_lang, []):
        out = pat.sub(repl, out)

    if _needs_translation(out, target_lang):
        out = await smart_translate(out, target_lang)
    return out


async def localize_products_dict(products: dict[str, dict], target_lang: str) -> dict[str, dict]:
    """Return a shallow copy of products dict with translated 'name' fields concurrently."""
    if not products or target_lang not in SUPPORTED_LANGS:
        return products

    items = list(products.items())
    translated_names = await asyncio.gather(
        *(smart_translate_title(p.get("name", ""), target_lang) for _, p in items)
    )
    localized: dict[str, dict] = {}
    for (pid, p), tr_name in zip(items, translated_names):
        p_copy = dict(p)
        p_copy["name"] = tr_name
        localized[pid] = p_copy
    return localized
