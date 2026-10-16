from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from config import CURRENCY, ADMIN_IDS


def get_main_menu(user_id: int):
    """Main persistent reply keyboard"""
    buttons = [
        [KeyboardButton("🛒 شراء اشتراك")],
        [KeyboardButton("📦 طلباتي السابقة"), KeyboardButton("ℹ️ الدعم والتعليمات")],
    ]
    if user_id in ADMIN_IDS:
        buttons.append([KeyboardButton("⚙️ لوحة تحكم الإدارة")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def get_categories_keyboard():
    """Inline keyboard for choosing product category: Gemini, ChatGPT, Other"""
    keyboard = [
        [InlineKeyboardButton("💎 Google Gemini AI", callback_data="cat:gemini")],
        [InlineKeyboardButton("🤖 ChatGPT & OpenAI", callback_data="cat:chatgpt")],
        [InlineKeyboardButton("🛍️ منتجات وخدمات أخرى", callback_data="cat:other")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_order")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_products_keyboard(products: dict, category: str = "gemini"):
    """Inline keyboard for selecting a subscription plan dynamically from DB"""
    keyboard = []
    for pid, prod in products.items():
        text = f"{prod['name']} — {prod['price']} {CURRENCY}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"prod:{pid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للأقسام", callback_data="back_to_categories")])
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel_order")])
    return InlineKeyboardMarkup(keyboard)


def get_quantity_keyboard(product_id: str, category: str = "gemini"):
    """Inline keyboard for selecting quantity"""
    keyboard = [
        [
            InlineKeyboardButton("1", callback_data=f"qty:{product_id}:1"),
            InlineKeyboardButton("2", callback_data=f"qty:{product_id}:2"),
            InlineKeyboardButton("3", callback_data=f"qty:{product_id}:3"),
        ],
        [
            InlineKeyboardButton("4", callback_data=f"qty:{product_id}:4"),
            InlineKeyboardButton("5", callback_data=f"qty:{product_id}:5"),
            InlineKeyboardButton("10", callback_data=f"qty:{product_id}:10"),
        ],
        [InlineKeyboardButton("🔙 رجوع للمنتجات", callback_data=f"cat:{category}")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_order")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_payment_methods_keyboard(product_id: str, quantity: int, price_usd: float = 2.5):
    """Inline keyboard for choosing payment method: BaridiMob, RedotPay, Bybit"""
    total_usd = round(price_usd * quantity, 2)
    keyboard = [
        [InlineKeyboardButton("🏦 بريدي موب (BaridiMob)", callback_data=f"paym:{product_id}:{quantity}:baridimob")],
        [InlineKeyboardButton(f"💳 RedotPay ({total_usd}$)", callback_data=f"paym:{product_id}:{quantity}:redotpay")],
        [InlineKeyboardButton(f"🟡 Bybit ({total_usd}$)", callback_data=f"paym:{product_id}:{quantity}:bybit")],
        [InlineKeyboardButton("🔙 رجوع لتحديد الكمية", callback_data=f"prod:{product_id}")],
        [InlineKeyboardButton("❌ إلغاء الطلب", callback_data="cancel_order")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_payment_confirm_keyboard():
    """Inline keyboard to proceed to upload receipt"""
    keyboard = [
        [InlineKeyboardButton("📤 إرسال إشعار التحويل ورقم الحوالة", callback_data="upload_receipt")],
        [InlineKeyboardButton("🔙 تغيير طريقة الدفع", callback_data="change_payment_method")],
        [InlineKeyboardButton("❌ إلغاء الطلب", callback_data="cancel_order")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_cancel_reply_keyboard():
    """Reply keyboard during input steps"""
    return ReplyKeyboardMarkup([["❌ إلغاء العملية"]], resize_keyboard=True, one_time_keyboard=True)


def get_admin_order_keyboard(order_id: int):
    """Buttons on the admin notification for approving, manually delivering, notifying, or rejecting an order"""
    keyboard = [
        [
            InlineKeyboardButton("✅ قبول وتسليم تلقائي", callback_data=f"adm_appr:{order_id}"),
            InlineKeyboardButton("✍️ تسليم يدوي", callback_data=f"adm_manual_deliver:{order_id}"),
        ],
        [
            InlineKeyboardButton("⏳ إشعار: جاري التجهيز", callback_data=f"adm_wait:{order_id}"),
            InlineKeyboardButton("💬 مراسلة العميل", callback_data=f"adm_msg:{order_id}"),
        ],
        [
            InlineKeyboardButton("❌ رفض الطلب", callback_data=f"adm_rej:{order_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_menu_keyboard():
    """Inline keyboard for Admin Dashboard"""
    keyboard = [
        [
            InlineKeyboardButton("🏷️ إدارة المنتجات والأسعار", callback_data="adm_products_manage"),
            InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats"),
        ],
        [
            InlineKeyboardButton("📦 جرد المخزن", callback_data="adm_stock"),
            InlineKeyboardButton("➕ إضافة روابط للمخزن", callback_data="adm_add_links"),
        ],
        [
            InlineKeyboardButton("⏳ الطلبات المعلقة", callback_data="adm_pending"),
            InlineKeyboardButton("🌐 رصيد ومخزن المورد (API)", callback_data="adm_supplier"),
        ],
        [
            InlineKeyboardButton("💳 تعديل بيانات الدفع", callback_data="adm_edit_payment"),
            InlineKeyboardButton("📢 قناة الإثباتات", callback_data="adm_proof_channel"),
        ],
        [
            InlineKeyboardButton("🔙 إغلاق اللوحة", callback_data="adm_close"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_proof_channel_keyboard(has_channel: bool = False):
    """Keyboard for managing Proofs Channel"""
    keyboard = [
        [InlineKeyboardButton("✏️ ضبط / تغيير معرف القناة", callback_data="adm_set_proof_channel")],
    ]
    if has_channel:
        keyboard.append([InlineKeyboardButton("🧪 إرسال منشور تجريبي للقناة", callback_data="adm_test_proof_channel")])
        keyboard.append([InlineKeyboardButton("🗑️ إلغاء ربط القناة", callback_data="adm_remove_proof_channel")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للوحة الرئيسية", callback_data="adm_back_menu")])
    return InlineKeyboardMarkup(keyboard)



def get_admin_products_management_keyboard():
    """Sub-menu for managing products and pricing"""
    keyboard = [
        [
            InlineKeyboardButton("✏️ تعديل سعر منتج", callback_data="adm_edit_price_select"),
            InlineKeyboardButton("➕ إضافة منتج جديد", callback_data="adm_add_product"),
        ],
        [
            InlineKeyboardButton("👁️ إيقاف / تفعيل منتج", callback_data="adm_toggle_product_select"),
        ],
        [
            InlineKeyboardButton("🔙 رجوع للوحة الرئيسية", callback_data="adm_back_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_select_product_for_price_edit(products: dict):
    """Choose which product to edit price for"""
    keyboard = []
    for pid, prod in products.items():
        keyboard.append([
            InlineKeyboardButton(
                f"✏️ {prod['name']} ({prod['price']} {CURRENCY})",
                callback_data=f"adm_set_price_for:{pid}",
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_products_manage")])
    return InlineKeyboardMarkup(keyboard)


def get_admin_select_product_for_toggle(products: dict):
    """Choose which product to enable or disable"""
    keyboard = []
    for pid, prod in products.items():
        status = "🟢 متاح" if prod.get("is_active", 1) == 1 else "🔴 متوقف"
        keyboard.append([
            InlineKeyboardButton(
                f"{status} - {prod['name']}",
                callback_data=f"adm_toggle_for:{pid}",
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_products_manage")])
    return InlineKeyboardMarkup(keyboard)


def get_admin_select_product_for_stock(products: dict):
    """Choose which product to add stock to"""
    keyboard = []
    for pid, prod in products.items():
        keyboard.append([InlineKeyboardButton(f"➕ {prod['name']}", callback_data=f"adm_stock_for:{pid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للوحة", callback_data="adm_back_menu")])
    return InlineKeyboardMarkup(keyboard)
