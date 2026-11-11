from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from config import CURRENCY, ADMIN_IDS


def _btn(text: str, callback_data: str | None = None, url: str | None = None, style: str | None = None) -> InlineKeyboardButton:
    """Create InlineKeyboardButton with Telegram style ('primary'=blue, 'success'=green, 'danger'=red)"""
    kwargs = {}
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url
    if style is not None:
        try:
            return InlineKeyboardButton(text, style=style, **kwargs)
        except TypeError:
            return InlineKeyboardButton(text, api_kwargs={"style": style}, **kwargs)
    return InlineKeyboardButton(text, **kwargs)


def _kbtn(text: str, style: str | None = None) -> KeyboardButton:
    """Create KeyboardButton with optional Telegram style"""
    if style is not None:
        try:
            return KeyboardButton(text, style=style)
        except TypeError:
            return KeyboardButton(text, api_kwargs={"style": style})
    return KeyboardButton(text)


def get_main_menu(user_id: int):
    """Main persistent reply keyboard"""
    buttons = [
        [
            _kbtn("🛒 شراء اشتراك", style="success"),
            _kbtn("👛 محفظتي (Top Up)"),
        ],
        [
            _kbtn("📦 طلباتي السابقة"),
            _kbtn("📘 الدعم والتعليمات", style="primary"),
        ],
    ]
    if user_id in ADMIN_IDS:
        buttons.append([_kbtn("⚙️ لوحة تحكم الإدارة")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def get_categories_keyboard():
    """3-column Brand Grid keyboard matching the requested design (Gemini=Green, Claude=Red)"""
    keyboard = [
        [
            _btn("👻 kiro", callback_data="cat:kiro"),
            _btn("⏸️ ElevenLabs", callback_data="cat:elevenlabs"),
            _btn("✴️ Claude", callback_data="cat:claude", style="danger"),
        ],
        [
            _btn("🧊 Cursor", callback_data="cat:cursor"),
            _btn("🎨 Adobe", callback_data="cat:adobe"),
            _btn("🪐 Grok", callback_data="cat:grok"),
        ],
        [
            _btn("🤖 ChatGPT", callback_data="cat:chatgpt"),
            _btn("✨ Gemini", callback_data="cat:gemini", style="success"),
            _btn("🚀 Antigravity", callback_data="cat:antigravity"),
        ],
        [
            _btn("✳️ Perplexity", callback_data="cat:perplexity"),
            _btn("💝 Lovable", callback_data="cat:lovable"),
            _btn("💎 HeyGen", callback_data="cat:heygen"),
        ],
        [
            _btn("🎬 CapCut", callback_data="cat:capcut"),
            _btn("📓 Notion", callback_data="cat:notion"),
            _btn("▶️ YouTube", callback_data="cat:youtube"),
        ],
        [
            _btn("🎥 Runway", callback_data="cat:runway"),
            _btn("⚡ Higgsfield", callback_data="cat:higgsfield"),
            _btn("⭐ Telegram", callback_data="cat:telegram"),
        ],
        [
            _btn("🎨 Canva", callback_data="cat:canva"),
            _btn("🍿 Netflix", callback_data="cat:netflix"),
            _btn("🌀 Kling", callback_data="cat:kling"),
        ],
        [
            _btn("🎵 Spotify", callback_data="cat:spotify"),
            _btn("🎶 Suno", callback_data="cat:suno"),
            _btn("🖼️ Krea", callback_data="cat:krea"),
        ],
        [
            _btn("🛍️ باقات ومنتجات أخرى", callback_data="cat:other", style="primary"),
        ],
        [
            _btn("🔙 العودة للقائمة", callback_data="cancel_order"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_products_keyboard(
    products: dict,
    category: str = "gemini",
    stock_status: dict | None = None,
    page: int = 0,
    per_page: int = 6,
):
    """Paginated inline keyboard for selecting a subscription plan with colored Gemini/Claude buttons"""
    items = list(products.items())
    total_items = len(items)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))

    start_idx = page * per_page
    page_items = items[start_idx : start_idx + per_page]

    keyboard = []
    for pid, prod in page_items:
        p_dzd = prod.get("price", 0)
        p_dzd_str = f"{int(p_dzd)}" if float(p_dzd).is_integer() else f"{p_dzd}"
        p_usd = prod.get("price_usd", 2.5)
        text = f"{prod['name']} — {p_dzd_str} {CURRENCY} (${p_usd})"

        combined_lower = f"{pid} {prod.get('name', '')} {prod.get('category', '')}".lower()
        btn_style = None
        if "gemini" in combined_lower:
            btn_style = "success"  # Green for Gemini
        elif "claude" in combined_lower:
            btn_style = "danger"   # Red for Claude

        keyboard.append([_btn(text, callback_data=f"prod:{pid}", style=btn_style)])

    # Pagination controls ("⬅️ السابق" & "عرض التالي ➡️")
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(_btn("⬅️ السابق", callback_data=f"cat_page:{category}:{page - 1}"))
        nav_row.append(_btn(f"📄 {page + 1}/{total_pages}", callback_data="noop"))
        if page + 1 < total_pages:
            nav_row.append(_btn("عرض التالي ➡️", callback_data=f"cat_page:{category}:{page + 1}", style="primary"))
        keyboard.append(nav_row)

    keyboard.append([_btn("🔙 رجوع للأقسام", callback_data="back_to_categories")])
    keyboard.append([_btn("❌ إلغاء", callback_data="cancel_order")])
    return InlineKeyboardMarkup(keyboard)


def get_quantity_keyboard(product_id: str, category: str = "gemini", is_admin: bool = False):
    """Inline keyboard for selecting quantity + Blue Product Instructions button"""
    keyboard = [
        [
            _btn("1", callback_data=f"qty:{product_id}:1"),
            _btn("2", callback_data=f"qty:{product_id}:2"),
            _btn("3", callback_data=f"qty:{product_id}:3"),
        ],
        [
            _btn("4", callback_data=f"qty:{product_id}:4"),
            _btn("5", callback_data=f"qty:{product_id}:5"),
            _btn("10", callback_data=f"qty:{product_id}:10"),
        ],
        [_btn("🔵 📖 تعليمات وشروط المنتج", callback_data=f"prod_inst:{product_id}", style="primary")],
    ]
    if is_admin:
        keyboard.append([
            _btn("✏️ تعديل تعليمة المنتج", callback_data=f"adm_inst_for:{product_id}", style="primary"),
            _btn("💲 تعديل السعر", callback_data=f"adm_set_price_for:{product_id}", style="success"),
        ])
    keyboard.extend([
        [_btn("🔙 رجوع للمنتجات", callback_data=f"cat:{category}")],
        [_btn("❌ إلغاء", callback_data="cancel_order")],
    ])
    return InlineKeyboardMarkup(keyboard)


def get_product_instructions_back_keyboard(product_id: str, category: str = "gemini", is_admin: bool = False):
    """Keyboard shown when viewing product instructions"""
    keyboard = [
        [_btn("🛒 متابعة شراء هذا المنتج", callback_data=f"prod:{product_id}", style="success")],
    ]
    if is_admin:
        keyboard.append([_btn("✏️ تعديل تعليمة هذا المنتج", callback_data=f"adm_inst_for:{product_id}", style="primary")])
    keyboard.append([_btn("🔙 رجوع لقائمة المنتجات", callback_data=f"cat:{category}")])
    return InlineKeyboardMarkup(keyboard)


def get_payment_methods_keyboard(product_id: str, quantity: int, price_usd: float = 2.5, price_dzd: float | None = None):
    """Inline keyboard for choosing payment method: Wallet (DZD/USD), BaridiMob, RedotPay, Bybit"""
    total_usd = round(price_usd * quantity, 2)
    dzd_part = f" ({int(price_dzd * quantity)} {CURRENCY})" if price_dzd else ""
    keyboard = [
        [_btn(f"👛 الدفع من محفظة الدينار{dzd_part}", callback_data=f"paym:{product_id}:{quantity}:wallet_dzd", style="success")],
        [_btn(f"👛 الدفع من محفظة الدولار (${total_usd})", callback_data=f"paym:{product_id}:{quantity}:wallet_usd", style="primary")],
        [_btn(f"🏦 بريدي موب (BaridiMob){dzd_part}", callback_data=f"paym:{product_id}:{quantity}:baridimob")],
        [_btn(f"💳 RedotPay (${total_usd})", callback_data=f"paym:{product_id}:{quantity}:redotpay")],
        [_btn(f"🟡 Bybit (${total_usd})", callback_data=f"paym:{product_id}:{quantity}:bybit")],
        [_btn("🔵 📖 تعليمات المنتج", callback_data=f"prod_inst:{product_id}", style="primary")],
        [_btn("🔙 رجوع لتحديد الكمية", callback_data=f"prod:{product_id}")],
        [_btn("❌ إلغاء الطلب", callback_data="cancel_order")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_payment_confirm_keyboard():
    """Inline keyboard to proceed to upload receipt"""
    keyboard = [
        [_btn("📤 إرسال إشعار التحويل ورقم الحوالة", callback_data="upload_receipt", style="success")],
        [_btn("🔙 تغيير طريقة الدفع", callback_data="change_payment_method")],
        [_btn("❌ إلغاء الطلب", callback_data="cancel_order")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_wallet_pay_confirm_keyboard(product_id: str):
    """Inline keyboard to confirm immediate deduction from wallet"""
    keyboard = [
        [_btn("✅ تأكيد الخصم من المحفظة وإتمام الشراء فوراً", callback_data="confirm_wallet_pay", style="success")],
        [_btn("🔙 تغيير طريقة الدفع", callback_data="change_payment_method")],
        [_btn("❌ إلغاء الطلب", callback_data="cancel_order")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ==================== لوحات المحفظة وشحن الرصيد (Wallet & Top-Up Keyboards) ====================

def get_wallet_main_keyboard():
    """Customer Wallet dashboard buttons"""
    keyboard = [
        [_btn("➕ شحن المحفظة بالدينار 🇩🇿 (Top Up DZD)", callback_data="wallet_topup_curr:dzd", style="success")],
        [_btn("➕ شحن المحفظة بالدولار 💵 (Top Up USD)", callback_data="wallet_topup_curr:usd", style="primary")],
        [_btn("📜 سجل عمليات الشحن", callback_data="wallet_history")],
        [_btn("🛒 الذهاب لشراء اشتراك", callback_data="back_to_categories")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_wallet_amount_presets_keyboard(curr_code: str):
    """Quick amount preset buttons for Top-Up"""
    if curr_code == "usd":
        presets = [
            [_btn("5$", callback_data="wallet_amt:usd:5"), _btn("10$", callback_data="wallet_amt:usd:10")],
            [_btn("20$", callback_data="wallet_amt:usd:20"), _btn("50$", callback_data="wallet_amt:usd:50")],
        ]
    else:
        presets = [
            [_btn("1000 دج", callback_data="wallet_amt:dzd:1000"), _btn("2000 دج", callback_data="wallet_amt:dzd:2000")],
            [_btn("5000 دج", callback_data="wallet_amt:dzd:5000"), _btn("10000 دج", callback_data="wallet_amt:dzd:10000")],
        ]
    presets.append([_btn("🔙 رجوع للمحفظة", callback_data="wallet_menu")])
    presets.append([_btn("❌ إلغاء", callback_data="cancel_order")])
    return InlineKeyboardMarkup(presets)


def get_wallet_usd_methods_keyboard(amount: float):
    """Choose USD payment method for wallet top-up"""
    keyboard = [
        [_btn(f"💳 RedotPay (${amount})", callback_data=f"wallet_paym:usd:{amount}:redotpay", style="primary")],
        [_btn(f"🟡 Bybit (${amount})", callback_data=f"wallet_paym:usd:{amount}:bybit", style="success")],
        [_btn("🔙 تغيير المبلغ", callback_data="wallet_topup_curr:usd")],
        [_btn("❌ إلغاء", callback_data="cancel_order")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_wallet_confirm_transfer_keyboard():
    """Button for customer to confirm they transferred the top-up money"""
    keyboard = [
        [_btn("✅ قمت بالتحويل — إرسال الوصل أو تأكيد العملية", callback_data="wallet_upload_proof", style="success")],
        [_btn("🔙 رجوع للمحفظة", callback_data="wallet_menu")],
        [_btn("❌ إلغاء", callback_data="cancel_order")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_cancel_reply_keyboard():
    """Reply keyboard during input steps"""
    return ReplyKeyboardMarkup([["❌ إلغاء العملية"]], resize_keyboard=True, one_time_keyboard=True)


# ==================== لوحات تحكم المسؤول (Admin Keyboards) ====================

def get_admin_order_keyboard(order_id: int):
    """Buttons on the admin notification for approving, manually delivering, notifying, or rejecting an order"""
    keyboard = [
        [
            _btn("✅ قبول وتسليم تلقائي", callback_data=f"adm_appr:{order_id}", style="success"),
            _btn("✍️ تسليم يدوي", callback_data=f"adm_manual_deliver:{order_id}", style="primary"),
        ],
        [
            _btn("⏳ إشعار: جاري التجهيز", callback_data=f"adm_wait:{order_id}"),
            _btn("💬 مراسلة العميل", callback_data=f"adm_msg:{order_id}"),
        ],
        [
            _btn("❌ رفض الطلب", callback_data=f"adm_rej:{order_id}", style="danger"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_topup_keyboard(topup_id: int, user_id: int):
    """Buttons on admin notification for approving/modifying/rejecting a wallet top-up request"""
    keyboard = [
        [
            _btn("✅ موافقة وإضافة الرصيد للمحفظة", callback_data=f"adm_topup_appr:{topup_id}", style="success"),
        ],
        [
            _btn("✏️ موافقة مع تعديل المبلغ", callback_data=f"adm_topup_edit:{topup_id}", style="primary"),
            _btn("❌ رفض طلب الشحن", callback_data=f"adm_topup_rej:{topup_id}", style="danger"),
        ],
        [
            _btn("🖼️ عرض صورة الوصل", callback_data=f"adm_topup_receipt:{topup_id}"),
            _btn("💬 مراسلة العميل", callback_data=f"adm_reply_user:{user_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_menu_keyboard():
    """Inline keyboard for Admin Dashboard"""
    keyboard = [
        [
            _btn("⏳ الطلبات المعلقة", callback_data="adm_pending", style="primary"),
            _btn("📋 سجل جميع الطلبات", callback_data="adm_all_orders"),
        ],
        [
            _btn("👛 طلبات شحن المحفظة والأرصدة", callback_data="adm_wallets_menu", style="success"),
        ],
        [
            _btn("✏️ تعديل الأسعار ($ / دج)", callback_data="adm_edit_price_select:0", style="success"),
            _btn("🔵 📖 تعديل تعليمة المنتج", callback_data="adm_edit_inst_select:0", style="primary"),
        ],
        [
            _btn("🏷️ إدارة المنتجات", callback_data="adm_products_manage"),
            _btn("📊 الإحصائيات", callback_data="adm_stats"),
        ],
        [
            _btn("📦 جرد المخزن", callback_data="adm_stock"),
            _btn("➕ إضافة روابط للمخزن", callback_data="adm_add_links", style="success"),
        ],
        [
            _btn("🗑️ حذف روابط من المخزن", callback_data="adm_del_links_menu:0", style="danger"),
            _btn("🌐 رصيد ومخزن المورد (API)", callback_data="adm_supplier"),
        ],
        [
            _btn("🔄 مزامنة وفحص الموردين", callback_data="adm_sync_apis"),
            _btn("📢 قناة الإثباتات", callback_data="adm_proof_channel"),
        ],
        [
            _btn("💳 تعديل بيانات الدفع", callback_data="adm_edit_payment"),
            _btn("🔙 إغلاق اللوحة", callback_data="adm_close"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_proof_channel_keyboard(has_channel: bool = False):
    """Keyboard for managing Proofs Channel"""
    keyboard = [
        [_btn("✏️ ضبط / تغيير معرف القناة", callback_data="adm_set_proof_channel")],
    ]
    if has_channel:
        keyboard.append([_btn("🧪 إرسال منشور تجريبي للقناة", callback_data="adm_test_proof_channel", style="primary")])
        keyboard.append([_btn("🗑️ إلغاء ربط القناة", callback_data="adm_remove_proof_channel", style="danger")])
    keyboard.append([_btn("🔙 رجوع للوحة الرئيسية", callback_data="adm_back_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_admin_products_management_keyboard():
    """Sub-menu for managing products, DZD/USD pricing, and product instructions"""
    keyboard = [
        [
            _btn("✏️ تعديل السعر (دينار / دولار)", callback_data="adm_edit_price_select:0", style="success"),
        ],
        [
            _btn("🔵 📖 التحكم بتعليمات المنتج", callback_data="adm_edit_inst_select:0", style="primary"),
        ],
        [
            _btn("➕ إضافة منتج جديد", callback_data="adm_add_product"),
            _btn("👁️ إيقاف / تفعيل منتج", callback_data="adm_toggle_product_select:0"),
        ],
        [
            _btn("🔙 رجوع للوحة الرئيسية", callback_data="adm_back_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def _paginate_admin_products(products: dict, page: int, per_page: int, page_prefix: str, back_callback: str):
    items = list(products.items())
    total_items = len(items)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * per_page
    page_items = items[start_idx : start_idx + per_page]

    nav_row = []
    if total_pages > 1:
        if page > 0:
            nav_row.append(_btn("⬅️ السابق", callback_data=f"{page_prefix}:{page - 1}"))
        nav_row.append(_btn(f"📄 {page + 1}/{total_pages}", callback_data="noop"))
        if page + 1 < total_pages:
            nav_row.append(_btn("عرض التالي ➡️", callback_data=f"{page_prefix}:{page + 1}", style="primary"))

    return page_items, nav_row, [_btn("🔙 رجوع", callback_data=back_callback)]


def get_admin_select_product_for_price_edit(products: dict, page: int = 0, per_page: int = 8):
    """Paginated product selector for editing DZD & USD prices"""
    page_items, nav_row, back_row = _paginate_admin_products(
        products, page, per_page, "adm_edit_price_select", "adm_products_manage"
    )
    keyboard = []
    for pid, prod in page_items:
        p_usd = prod.get("price_usd", 2.5)
        keyboard.append([
            _btn(
                f"✏️ {prod['name']} — {prod['price']} {CURRENCY} | ${p_usd}",
                callback_data=f"adm_set_price_for:{pid}",
            )
        ])
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append(back_row)
    return InlineKeyboardMarkup(keyboard)


def get_admin_select_product_for_inst_edit(products: dict, page: int = 0, per_page: int = 8):
    """Paginated product selector for editing product instructions"""
    page_items, nav_row, back_row = _paginate_admin_products(
        products, page, per_page, "adm_edit_inst_select", "adm_products_manage"
    )
    keyboard = []
    for pid, prod in page_items:
        keyboard.append([
            _btn(
                f"📘 {prod['name']}",
                callback_data=f"adm_inst_for:{pid}",
                style="primary",
            )
        ])
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append(back_row)
    return InlineKeyboardMarkup(keyboard)


def get_admin_select_product_for_toggle(products: dict, page: int = 0, per_page: int = 8):
    """Paginated product selector to enable or disable products"""
    page_items, nav_row, back_row = _paginate_admin_products(
        products, page, per_page, "adm_toggle_product_select", "adm_products_manage"
    )
    keyboard = []
    for pid, prod in page_items:
        is_act = prod.get("is_active", 1) == 1
        status = "🟢 متاح" if is_act else "🔴 متوقف"
        keyboard.append([
            _btn(
                f"{status} - {prod['name']}",
                callback_data=f"adm_toggle_for:{pid}:{page}",
            )
        ])
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append(back_row)
    return InlineKeyboardMarkup(keyboard)


def get_admin_select_product_for_stock(products: dict, page: int = 0, per_page: int = 8):
    """Paginated product selector to add stock links"""
    page_items, nav_row, back_row = _paginate_admin_products(
        products, page, per_page, "adm_add_links_page", "adm_back_menu"
    )
    keyboard = []
    for pid, prod in page_items:
        keyboard.append([_btn(f"➕ {prod['name']}", callback_data=f"adm_stock_for:{pid}")])
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append(back_row)
    return InlineKeyboardMarkup(keyboard)


def get_admin_select_product_for_del_stock(products: dict, stock_counts: dict, page: int = 0, per_page: int = 8):
    """Paginated product selector to view and delete stock links (sorted by stock count descending)"""
    sorted_prods = dict(
        sorted(products.items(), key=lambda kv: (stock_counts.get(kv[0], 0), kv[1].get("price", 0)), reverse=True)
    )
    page_items, nav_row, back_row = _paginate_admin_products(
        sorted_prods, page, per_page, "adm_del_links_menu", "adm_back_menu"
    )
    keyboard = []
    for pid, prod in page_items:
        cnt = stock_counts.get(pid, 0)
        badge = f"({cnt} رابط 🟢)" if cnt > 0 else "(0 رابط ⚪)"
        btn_style = "danger" if cnt > 0 else None
        keyboard.append([
            _btn(f"🗑️ {prod['name']} {badge}", callback_data=f"adm_del_stock_prod:{pid}", style=btn_style)
        ])
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append(back_row)
    return InlineKeyboardMarkup(keyboard)
