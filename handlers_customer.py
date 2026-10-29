import html
import logging
from telegram import Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from config import PRODUCTS, CURRENCY, ADMIN_IDS, PAYMENT_METHODS
import database
import keyboards
import supplier_api

logger = logging.getLogger(__name__)

# Conversation states
SELECTING_PRODUCT = 1
SELECTING_QUANTITY = 2
SELECTING_PAYMENT = 3
AWAITING_RECEIPT = 4
AWAITING_TRANSFER_NO = 5


def escape_md(val) -> str:
    """Safely escape legacy Telegram Markdown v1 special characters in dynamic strings"""
    if val is None:
        return ""
    s = str(val)
    for ch in ("_", "*", "`", "["):
        s = s.replace(ch, f"\\{ch}")
    return s


def format_dt(val) -> str:
    if not val:
        return ""
    return str(val)[:19].replace("T", " ")


async def safe_answer(query, text: str | None = None, show_alert: bool = False):
    if getattr(query, "_answered_safely", False):
        return
    try:
        await query.answer(text=text, show_alert=show_alert)
        setattr(query, "_answered_safely", True)
    except Exception:
        pass


async def safe_edit_text(message, text: str, reply_markup=None, parse_mode: str | None = "Markdown"):
    try:
        return await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        err_str = str(e)
        if "Message is not modified" in err_str:
            return None
        clean_text = text.replace("**", "").replace("`", "").replace("\\_", "_").replace("\\*", "*")
        try:
            return await message.edit_text(clean_text, reply_markup=reply_markup, parse_mode=None)
        except Exception:
            return await message.reply_text(clean_text, reply_markup=reply_markup, parse_mode=None)
    except Exception:
        clean_text = text.replace("**", "").replace("`", "").replace("\\_", "_").replace("\\*", "*")
        return await message.reply_text(clean_text, reply_markup=reply_markup, parse_mode=None)


async def safe_reply_text(message, text: str, reply_markup=None, parse_mode: str | None = "Markdown"):
    try:
        return await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        clean_text = text.replace("**", "").replace("`", "").replace("\\_", "_").replace("\\*", "*")
        return await message.reply_text(clean_text, reply_markup=reply_markup, parse_mode=None)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command"""
    context.user_data.pop("order_draft", None)
    user = update.effective_user
    products = await database.get_all_products(only_active=True)

    products_list_text = ""
    for p in list(products.values())[:12]:
        products_list_text += f"• 💎 {escape_md(p['name'])} — `{p['price']}` {CURRENCY}\n"
    if len(products) > 12:
        products_list_text += f"• 🛍️ _و `{len(products) - 12}` باقات ومنتجات أخرى داخل القائمة..._\n"

    welcome_text = (
        f"مرحباً بك يا **{escape_md(user.first_name)}** في **متجر الاشتراكات الرقمية** 🤖✨\n\n"
        "نوفر لك اشتراكات رسمية بأفضل الأسعار وبضمان كامل.\n\n"
        f"📌 **أبرز الباقات المتوفرة حالياً:**\n{products_list_text}\n"
        "اختر من القائمة بالأسفل للبدء 👇"
    )
    await safe_reply_text(
        update.message,
        welcome_text,
        reply_markup=keyboards.get_main_menu(user.id),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for Support & Info button"""
    context.user_data.pop("order_draft", None)
    text = (
        "ℹ️ **حول الخدمة وطريقة التفعيل:**\n\n"
        "1. بعد إتمام الدفع وتأكيد الحوالة، ستستلم رابط أو بيانات التفعيل المخصصة لحسابك.\n"
        "2. كل ما عليك هو فتح الرابط وتسجيل الدخول بحسابك ليتم تفعيل الاشتراك مباشرة.\n"
        "3. الاشتراكات أصلية ومضمونة طوال فترة الاشتراك.\n\n"
        "📞 في حال واجهت أي مشكلة، يمكنك إرسال رسالتك هنا مباشرة وسيقوم فريق الدعم بالرد عليك فوراً."
    )
    await safe_reply_text(
        update.message,
        text,
        reply_markup=keyboards.get_main_menu(update.effective_user.id),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def my_orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View previous orders of the user"""
    context.user_data.pop("order_draft", None)
    user_id = update.effective_user.id
    orders = await database.get_user_orders(user_id, limit=10)

    if not orders:
        await safe_reply_text(
            update.message,
            "📦 ليس لديك أي طلبات سابقة حتى الآن.\nيمكنك الضغط على '🛒 شراء اشتراك' لطلب اشتراكك الأول!",
            reply_markup=keyboards.get_main_menu(user_id),
        )
        return ConversationHandler.END

    text = "📦 **طلباتك الأخيرة:**\n\n"
    for o in orders:
        status_emoji = {
            "PENDING": "⏳ قيد المراجعة والتحقق",
            "APPROVED": "✅ مكتمل ومُسلّم",
            "REJECTED": "❌ مرفوض",
        }.get(o.get("status"), o.get("status"))

        ocode = o.get("order_code") or f"ORD-{o.get('id', 0):04d}"
        curr = escape_md(o.get("currency") or CURRENCY)
        text += (
            f"🔹 **طلب رقم:** `{ocode}`\n"
            f"• المنتج: {escape_md(o.get('product_name'))} (الكمية: `{o.get('quantity', 1)}`)\n"
            f"• المبلغ: `{o.get('total_price')}` {curr}\n"
            f"• الحالة: {status_emoji}\n"
            f"• التاريخ: `{format_dt(o.get('created_at'))}`\n"
        )

        if o.get("status") == "APPROVED" and o.get("delivered_links"):
            clean_links = str(o["delivered_links"]).replace("`", "")
            text += f"🔗 **روابط/بيانات التفعيل المستلمة:**\n`{clean_links}`\n"
        elif o.get("status") == "REJECTED" and o.get("reject_reason"):
            text += f"⚠️ **سبب الرفض:** {escape_md(o['reject_reason'])}\n"

        text += "───────────────\n"

    await safe_reply_text(
        update.message,
        text,
        reply_markup=keyboards.get_main_menu(user_id),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ==================== تدفق طلب الشراء (Order Flow) ====================

async def buy_subscription_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: Show product categories (Gemini, ChatGPT, Other)"""
    context.user_data.pop("order_draft", None)
    text = (
        "🛍️ **اختر القسم الذي تريده:**\n\n"
        "🔹 اختر قسماً من الأقسام التالية لعرض الاشتراكات والمنتجات المتاحة:"
    )
    if update.callback_query:
        await safe_answer(update.callback_query)
        await safe_edit_text(
            update.callback_query.message,
            text,
            reply_markup=keyboards.get_categories_keyboard(),
            parse_mode="Markdown",
        )
    else:
        await safe_reply_text(
            update.message,
            text,
            reply_markup=keyboards.get_categories_keyboard(),
            parse_mode="Markdown",
        )
    return SELECTING_PRODUCT


async def category_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle choosing a category: 'gemini', 'chatgpt', 'other'"""
    query = update.callback_query
    await safe_answer(query)

    cat = query.data.split(":", 1)[1]
    products = await database.get_products_by_category(cat, only_active=True)
    stock_status = await supplier_api.get_products_stock_summary(list(products.keys())) if products else None

    cat_titles = {
        "gemini": "💎 **اشتراكات Google Gemini AI:**",
        "chatgpt": "🤖 **اشتراكات ChatGPT & OpenAI:**",
        "other": "🛍️ **المنتجات والخدمات الأخرى:**",
    }
    title = cat_titles.get(cat, "🛍️ **قائمة المنتجات:**")

    if not products:
        text = f"{title}\n\n⚠️ عذراً، لا توجد منتجات متوفرة في هذا القسم حالياً."
    else:
        text = f"{title}\nاختر الباقة المناسبة لك:"

    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_products_keyboard(products, category=cat, stock_status=stock_status),
        parse_mode="Markdown",
    )
    return SELECTING_PRODUCT


async def back_to_categories_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to category selection"""
    query = update.callback_query
    await safe_answer(query)
    return await buy_subscription_entry(update, context)


async def product_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle product selection from inline keyboard"""
    query = update.callback_query
    await safe_answer(query)

    data = query.data
    if data == "cancel_order":
        await safe_edit_text(query.message, "❌ تم إلغاء العملية.")
        return ConversationHandler.END

    product_id = data.split(":", 1)[1]
    product = await database.get_product_by_id(product_id)
    if not product or product.get("is_active") == 0:
        await safe_edit_text(query.message, "⚠️ عذراً، هذا المنتج غير متوفر حالياً.")
        return ConversationHandler.END

    cat = product.get("category", "other")
    price_usd = product.get("price_usd", 2.5)

    # Check live stock across local stock and connected suppliers
    stock_info = await supplier_api.check_total_product_stock(product_id)
    is_preorder = not stock_info.get("is_in_stock", True)

    # Save to draft
    context.user_data["order_draft"] = {
        "product_id": product_id,
        "product_name": product["name"],
        "price": product["price"],
        "price_usd": price_usd,
        "category": cat,
        "is_preorder": is_preorder,
    }

    if is_preorder:
        stock_notice = (
            "⚠️ **حالة المخزون:** 🔴 **غير متوفر للتسليم الفوري حالياً (نفد المخزون)**.\n"
            "📌 **نظام الحجز المسبق:** إذا أردت حجز هذا الاشتراك، أكمل الدفع وسنتواصل معك ونقوم بشرائه وتفعيله لك يدوياً في أقرب وقت! 🌟\n\n"
            "🔢 **حدد الكمية المطلوبة للمتابعة في الحجز المسبق:**"
        )
    else:
        stock_notice = (
            "⚡️ **حالة المخزون:** ✅ **متوفر للتسليم الفوري**\n\n"
            "🔢 **الرجاء تحديد الكمية المطلوبة:**"
        )

    text = (
        f"💎 **لقد اخترت:** {escape_md(product['name'])}\n"
        f"💵 **السعر:** `{product['price']}` {CURRENCY}\n"
        f"📝 {escape_md(product.get('description', ''))}\n\n"
        f"{stock_notice}"
    )
    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_quantity_keyboard(product_id, category=cat),
        parse_mode="Markdown",
    )
    return SELECTING_QUANTITY


async def back_to_products_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to product list for the category"""
    query = update.callback_query
    await safe_answer(query)
    parts = query.data.split(":")
    cat = parts[1] if len(parts) > 1 else "gemini"
    products = await database.get_products_by_category(cat, only_active=True)
    stock_status = await supplier_api.get_products_stock_summary(list(products.keys())) if products else None
    await safe_edit_text(
        query.message,
        "🛍️ **اختر باقة الاشتراك المناسبة لك:**",
        reply_markup=keyboards.get_products_keyboard(products, category=cat, stock_status=stock_status),
        parse_mode="Markdown",
    )
    return SELECTING_PRODUCT


async def quantity_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quantity selection and prompt for payment method"""
    query = update.callback_query
    await safe_answer(query)

    parts = query.data.split(":")
    product_id = parts[1]
    quantity = int(parts[2])

    draft = context.user_data.get("order_draft", {})
    if not draft or draft.get("product_id") != product_id:
        product = await database.get_product_by_id(product_id)
        if not product:
            await safe_edit_text(query.message, "⚠️ عذراً، المنتج غير موجود.")
            return ConversationHandler.END
        stock_info = await supplier_api.check_total_product_stock(product_id)
        draft = {
            "product_id": product_id,
            "product_name": product["name"],
            "price": product["price"],
            "price_usd": product.get("price_usd", 2.5),
            "category": product.get("category", "other"),
            "is_preorder": not stock_info.get("is_in_stock", True),
        }

    draft["quantity"] = quantity
    context.user_data["order_draft"] = draft
    price_usd = draft.get("price_usd", 2.5)

    text = (
        f"📦 **المنتج:** {escape_md(draft['product_name'])}\n"
        f"🔢 **الكمية:** `{quantity}`\n\n"
        "💳 **الرجاء اختيار طريقة الدفع المناسبة لك:**"
    )
    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_payment_methods_keyboard(product_id, quantity, price_usd=price_usd),
        parse_mode="Markdown",
    )
    return SELECTING_PAYMENT


async def payment_method_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle chosen payment method (BaridiMob, RedotPay, Bybit)"""
    query = update.callback_query
    await safe_answer(query)

    parts = query.data.split(":")
    product_id = parts[1]
    quantity = int(parts[2])
    method_id = parts[3]

    draft = context.user_data.get("order_draft", {})
    if not draft or draft.get("product_id") != product_id:
        product = await database.get_product_by_id(product_id)
        if not product:
            await safe_edit_text(query.message, "⚠️ عذراً، المنتج غير موجود.")
            return ConversationHandler.END
        stock_info = await supplier_api.check_total_product_stock(product_id)
        draft = {
            "product_id": product_id,
            "product_name": product["name"],
            "price": product["price"],
            "price_usd": product.get("price_usd", 2.5),
            "category": product.get("category", "other"),
            "quantity": quantity,
            "is_preorder": not stock_info.get("is_in_stock", True),
        }

    method = PAYMENT_METHODS.get(method_id, PAYMENT_METHODS["baridimob"])

    if method_id == "baridimob":
        total_price = draft.get("price", 1000) * quantity
        currency = "دينار"
        instructions = await database.get_payment_info()
    else:
        price_usd = draft.get("price_usd", 2.5)
        total_price = round(price_usd * quantity, 2)
        currency = method.get("currency", "$")
        instructions = method["details"]

    draft["quantity"] = quantity
    draft["payment_method"] = method_id
    draft["payment_method_name"] = method["name"]
    draft["total_price"] = total_price
    draft["currency"] = currency
    context.user_data["order_draft"] = draft

    is_preorder = draft.get("is_preorder", False)
    preorder_notice = (
        "⚠️ **تنبيه:** هذا الطلب بنظام **الحجز المسبق** (المنتج غير متوفر للتسليم الفوري).\n"
        "سيقوم المشرف بشرائه وتفعيله لك يدوياً والتواصل معك فور استلام الحوالة.\n"
        "─────────────────\n"
    ) if is_preorder else ""

    summary_text = (
        f"📋 **ملخص طلبك{' (حجز مسبق ⏳)' if is_preorder else ''}:**\n"
        f"─────────────────\n"
        f"📦 **المنتج:** {escape_md(draft['product_name'])}\n"
        f"🔢 **الكمية:** `{quantity}`\n"
        f"💳 **طريقة الدفع:** {escape_md(method['name'])}\n"
        f"💰 **المبلغ الإجمالي المطلوب:** `{total_price}` {escape_md(currency)}\n"
        f"─────────────────\n"
        f"{preorder_notice}"
        f"{instructions}\n\n"
        "👇 اضغط على الزر بالأسفل عندما تكون جاهزاً لإرسال إشعار التحويل ورقم الحوالة:"
    )

    await safe_edit_text(
        query.message,
        summary_text,
        reply_markup=keyboards.get_payment_confirm_keyboard(),
        parse_mode="Markdown",
    )
    return AWAITING_RECEIPT


async def change_payment_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User wants to change chosen payment method"""
    query = update.callback_query
    await safe_answer(query)

    draft = context.user_data.get("order_draft", {})
    product_id = draft.get("product_id")
    if not product_id:
        return await buy_subscription_entry(update, context)

    quantity = draft.get("quantity", 1)
    price_usd = draft.get("price_usd", 2.5)

    text = (
        f"📦 **المنتج:** {escape_md(draft.get('product_name'))}\n"
        f"🔢 **الكمية:** `{quantity}`\n\n"
        "💳 **الرجاء اختيار طريقة الدفع المناسبة لك:**"
    )
    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_payment_methods_keyboard(product_id, quantity, price_usd=price_usd),
        parse_mode="Markdown",
    )
    return SELECTING_PAYMENT


async def proceed_to_upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User confirmed they want to upload receipt"""
    query = update.callback_query
    await safe_answer(query)

    text = (
        "📸 **الرجاء إرسال صورة وصل / إشعار التحويل الآن.**\n\n"
        "💡 *ملاحظة:* إذا قمت بكتابة رقم التحويل في وصف الصورة (Caption)، سيتم اعتماده مباشرة، "
        "أو يمكنك إرسال الصورة وسيسألك البوت عن رقم الحوالة بعد ذلك."
    )
    await safe_edit_text(query.message, text, parse_mode="Markdown")
    await safe_reply_text(
        query.message,
        "إذا أردت التراجع يمكنك الضغط على '❌ إلغاء العملية':",
        reply_markup=keyboards.get_cancel_reply_keyboard(),
    )
    return AWAITING_RECEIPT


async def receipt_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle receipt photo upload"""
    message = update.message
    draft = context.user_data.get("order_draft")
    if not draft:
        await safe_reply_text(
            message,
            "⚠️ حدث خطأ أو انتهت الجلسة. يرجى إعادة الطلب من البداية.",
            reply_markup=keyboards.get_main_menu(update.effective_user.id),
        )
        return ConversationHandler.END

    photo = message.photo[-1]
    draft["receipt_file_id"] = photo.file_id

    caption = (message.caption or "").strip()
    if caption:
        draft["transfer_number"] = caption
        context.user_data["order_draft"] = draft
        return await finalize_order_submission(update, context)

    await safe_reply_text(
        message,
        "✅ تم استلام صورة الإيصال بنجاح.\n\n"
        "✍️ **الآن، يرجى كتابة رقم عملية التحويل (رقم الحوالة أو المرجع):**",
        reply_markup=keyboards.get_cancel_reply_keyboard(),
        parse_mode="Markdown",
    )
    return AWAITING_TRANSFER_NO


async def transfer_number_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle transfer number text input"""
    text = (update.message.text or "").strip()
    draft = context.user_data.get("order_draft")
    if not draft:
        await safe_reply_text(
            update.message,
            "⚠️ حدث خطأ أو انتهت الجلسة. يرجى البدء من جديد.",
            reply_markup=keyboards.get_main_menu(update.effective_user.id),
        )
        return ConversationHandler.END

    draft["transfer_number"] = text
    context.user_data["order_draft"] = draft
    return await finalize_order_submission(update, context)


async def finalize_order_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save order to DB and notify admin"""
    draft = context.user_data.get("order_draft", {})
    user = update.effective_user

    pay_method = draft.get("payment_method_name", "بريدي موب")
    pay_curr = draft.get("currency", "دينار")

    order_id, order_code = await database.create_order(
        user_id=user.id,
        user_name=user.full_name or "مستخدم",
        user_username=f"@{user.username}" if user.username else "بدون يوزر",
        product_id=draft["product_id"],
        product_name=draft["product_name"],
        quantity=draft["quantity"],
        total_price=draft["total_price"],
        transfer_number=draft.get("transfer_number", "غير محدد"),
        receipt_file_id=draft["receipt_file_id"],
        payment_method=pay_method,
        currency=pay_curr,
    )

    # Customer success message
    is_preorder = draft.get("is_preorder", False)
    pname_safe = escape_md(draft["product_name"])
    tnum_safe = escape_md(draft.get("transfer_number"))
    pm_safe = escape_md(pay_method)
    curr_safe = escape_md(pay_curr)

    if is_preorder:
        customer_msg = (
            f"🎉 **تم استلام طلب الحجز المسبق بنجاح!**\n\n"
            f"🔹 **رقم الطلب:** `{order_code}`\n"
            f"📦 **المنتج:** {pname_safe}\n"
            f"🔢 **الكمية:** `{draft['quantity']}`\n"
            f"💳 **طريقة الدفع:** {pm_safe}\n"
            f"💰 **المبلغ:** `{draft['total_price']}` {curr_safe}\n"
            f"🧾 **رقم التحويل:** `{tnum_safe}`\n\n"
            "⏳ **حالة الطلب:** حجز مسبق قيد المراجعة والتجهيز اليدوي.\n"
            "سنقوم بالتحقق من الحوالة وتفعيل اشتراكك والتواصل معك هنا مباشرة لتسليمك الحساب في أقرب وقت. شكراً لصبرك وثقتك بنا! 🌟"
        )
    else:
        customer_msg = (
            f"🎉 **تم إرسال طلبك بنجاح!**\n\n"
            f"🔹 **رقم الطلب:** `{order_code}`\n"
            f"📦 **المنتج:** {pname_safe}\n"
            f"🔢 **الكمية:** `{draft['quantity']}`\n"
            f"💳 **طريقة الدفع:** {pm_safe}\n"
            f"💰 **المبلغ:** `{draft['total_price']}` {curr_safe}\n"
            f"🧾 **رقم التحويل:** `{tnum_safe}`\n\n"
            "⏳ جاري التحقق من إشعار التحويل من قبل الإدارة. ستصلك روابط التفعيل هنا في المحادثة فور التأكيد!"
        )
    await safe_reply_text(
        update.message,
        customer_msg,
        reply_markup=keyboards.get_main_menu(user.id),
        parse_mode="Markdown",
    )

    # Notify Admins
    await notify_admins_new_order(context, order_id, order_code, user, draft)

    # Clear draft
    context.user_data.pop("order_draft", None)

    return ConversationHandler.END


async def notify_admins_new_order(
    context: ContextTypes.DEFAULT_TYPE,
    order_id: int,
    order_code: str,
    user,
    draft: dict,
):
    """Send photo and order details to all registered admins with guaranteed fallback"""
    stock_counts = await database.get_stock_counts()
    available_stock = stock_counts.get(draft["product_id"], 0)
    pay_method = draft.get("payment_method_name", "بريدي موب")
    pay_curr = draft.get("currency", "دينار")
    is_preorder = draft.get("is_preorder", False)

    if is_preorder:
        stock_status_label = "🔴 **حجز مسبق** (المخزون الفوري نفد - يتطلب شراء يدوي من طرفك)"
        order_title = f"🔔 **طلب حجز مسبق جديد ⏳: `{order_code}`**"
    else:
        stock_status_label = f"`{available_stock}` رابط ({'✅ متوفر محلياً' if available_stock >= draft['quantity'] else '🌐 سيتم السحب تلقائياً من API المورد'})"
        order_title = f"🔔 **طلب شراء جديد: `{order_code}`**"

    uname_safe = escape_md(user.full_name or "مستخدم")
    uuser_safe = escape_md(f"@{user.username}" if user.username else "لا يوجد معرف")
    pname_safe = escape_md(draft.get("product_name", ""))
    tnum_safe = escape_md(draft.get("transfer_number", ""))

    admin_caption = (
        f"{order_title}\n"
        f"─────────────────\n"
        f"👤 **العميل:** {uname_safe} ({uuser_safe})\n"
        f"🆔 **معرف العميل (ID):** `{user.id}`\n\n"
        f"📦 **المنتج:** {pname_safe}\n"
        f"🔢 **الكمية:** `{draft['quantity']}`\n"
        f"💳 **طريقة الدفع:** {escape_md(pay_method)}\n"
        f"💰 **المبلغ المطلوب:** `{draft['total_price']}` {escape_md(pay_curr)}\n"
        f"🧾 **رقم التحويل:** `{tnum_safe}`\n"
        f"─────────────────\n"
        f"📦 **حالة المخزون:** {stock_status_label}\n"
    )

    kb = keyboards.get_admin_order_keyboard(order_id)
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=draft["receipt_file_id"],
                caption=admin_caption,
                reply_markup=kb,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning(f"Markdown send_photo failed for admin {admin_id}, retrying plain caption: {e}")
            clean_caption = admin_caption.replace("**", "").replace("`", "").replace("\\_", "_").replace("\\*", "*")
            try:
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=draft["receipt_file_id"],
                    caption=clean_caption,
                    reply_markup=kb,
                )
            except Exception as e2:
                logger.error(f"Fallback send_photo failed for admin {admin_id}, sending text alert: {e2}")
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=clean_caption,
                        reply_markup=kb,
                    )
                except Exception as e3:
                    logger.error(f"Could not notify admin {admin_id} at all: {e3}")


async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel order conversation"""
    context.user_data.pop("order_draft", None)
    if update.callback_query:
        await safe_answer(update.callback_query)
        await safe_edit_text(update.callback_query.message, "❌ تم إلغاء الطلب.")
    else:
        await safe_reply_text(
            update.message,
            "❌ تم إلغاء العملية والعودة للقائمة الرئيسية.",
            reply_markup=keyboards.get_main_menu(update.effective_user.id),
        )
    return ConversationHandler.END


# ==================== خدمة ودعم العملاء الواردة (Inbound Customer Support) ====================

async def handle_customer_inbound_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages from customers outside of active order conversations"""
    user = update.effective_user
    if not user or user.id in ADMIN_IDS:
        return

    text = update.message.text.strip()
    user_id = user.id

    recent_orders = await database.get_user_orders(user_id, limit=1)
    last_order = recent_orders[0] if recent_orders else None

    order_info = ""
    reply_buttons = []
    if last_order:
        st_emoji = "⏳" if last_order.get("status") == "PENDING" else "✅"
        order_info = (
            f"\n🏷 **آخر طلب للعميل:** `{last_order['order_code']}` ({escape_md(last_order['product_name'])}) "
            f"| الحالة: {st_emoji} `{last_order['status']}`"
        )
        if last_order.get("status") == "PENDING":
            reply_buttons.append([
                InlineKeyboardButton("✍️ تسليم الطلب", callback_data=f"adm_manual_deliver:{last_order['id']}"),
                InlineKeyboardButton("⏳ إشعار بالانتظار", callback_data=f"adm_wait:{last_order['id']}"),
            ])

    reply_buttons.append([
        InlineKeyboardButton("💬 الرد على العميل", callback_data=f"adm_reply_user:{user_id}")
    ])

    admin_keyboard = InlineKeyboardMarkup(reply_buttons)
    uname_safe = escape_md(user.full_name or "عميل")
    uuser_safe = escape_md(f"@{user.username}" if user.username else "لا يوجد معرف")
    admin_notification = (
        f"📩 **رسالة جديدة من عميل:**\n"
        f"─────────────────────\n"
        f"👤 **العميل:** {uname_safe} ({uuser_safe})\n"
        f"🆔 **معرف العميل (ID):** `{user_id}`"
        f"{order_info}\n\n"
        f"💬 **نص الرسالة:**\n"
        f"{escape_md(text)}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_notification,
                reply_markup=admin_keyboard,
                parse_mode="Markdown",
            )
        except Exception:
            clean_notif = admin_notification.replace("**", "").replace("`", "").replace("\\_", "_")
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=clean_notif,
                    reply_markup=admin_keyboard,
                )
            except Exception as e:
                logger.error(f"Error forwarding customer message to admin {admin_id}: {e}")

    await safe_reply_text(
        update.message,
        "✅ **تم استلام رسالتك وإيصالها لإدارة المتجر بنجاح.**\n"
        "سيقوم المشرف بالرد عليك هنا في أقرب وقت ممكن. شكراً لتواصلك! 🌟",
        parse_mode="Markdown",
    )


async def handle_customer_inbound_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles photos sent by customers outside of active order conversations"""
    user = update.effective_user
    if not user or user.id in ADMIN_IDS:
        return

    photo_file_id = update.message.photo[-1].file_id
    caption = update.message.caption or ""
    user_id = user.id

    recent_orders = await database.get_user_orders(user_id, limit=1)
    last_order = recent_orders[0] if recent_orders else None

    order_info = ""
    reply_buttons = []
    if last_order and last_order.get("status") == "PENDING":
        order_info = f"\n🏷 **طلب معلق:** `{last_order['order_code']}` ({escape_md(last_order['product_name'])})"
        reply_buttons.append([
            InlineKeyboardButton("✍️ تسليم الطلب", callback_data=f"adm_manual_deliver:{last_order['id']}"),
        ])

    reply_buttons.append([
        InlineKeyboardButton("💬 الرد على العميل", callback_data=f"adm_reply_user:{user_id}")
    ])

    admin_keyboard = InlineKeyboardMarkup(reply_buttons)
    uname_safe = escape_md(user.full_name or "عميل")
    uuser_safe = escape_md(f"@{user.username}" if user.username else "لا يوجد معرف")
    admin_caption = (
        f"📷 **صورة واردة من عميل:**\n"
        f"👤 {uname_safe} ({uuser_safe})\n"
        f"🆔 **معرف العميل (ID):** `{user_id}`"
        f"{order_info}\n"
        f"💬 **التعليق:** {escape_md(caption) if caption else '(بدون تعليق)'}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=photo_file_id,
                caption=admin_caption,
                reply_markup=admin_keyboard,
                parse_mode="Markdown",
            )
        except Exception:
            clean_cap = admin_caption.replace("**", "").replace("`", "").replace("\\_", "_")
            try:
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=photo_file_id,
                    caption=clean_cap,
                    reply_markup=admin_keyboard,
                )
            except Exception as e:
                logger.error(f"Error forwarding customer photo to admin {admin_id}: {e}")

    await safe_reply_text(
        update.message,
        "✅ **تم استلام الصورة وإرسالها للإدارة بنجاح.**\n"
        "شكراً لك، سنرد عليك في أقرب وقت! 🌟",
        parse_mode="Markdown",
    )

