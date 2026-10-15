import html
from telegram import Update, ReplyKeyboardRemove
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

# Conversation states
SELECTING_PRODUCT = 1
SELECTING_QUANTITY = 2
SELECTING_PAYMENT = 3
AWAITING_RECEIPT = 4
AWAITING_TRANSFER_NO = 5


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command"""
    user = update.effective_user
    products = await database.get_all_products(only_active=True)

    products_list_text = ""
    for p in products.values():
        products_list_text += f"• 💎 {p['name']} — {p['price']} {CURRENCY}\n"

    welcome_text = (
        f"مرحباً بك يا {html.escape(user.first_name)} في **متجر الاشتراكات الرقمية** 🤖✨\n\n"
        "نوفر لك اشتراكات رسمية بأفضل الأسعار وبضمان كامل.\n\n"
        f"📌 **الباقات المتوفرة حالياً:**\n{products_list_text}\n"
        "اختر من القائمة بالأسفل للبدء 👇"
    )
    await update.message.reply_text(
        welcome_text,
        reply_markup=keyboards.get_main_menu(user.id),
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for Support & Info button"""
    text = (
        "ℹ️ **حول الخدمة وطريقة التفعيل:**\n\n"
        "1. بعد إتمام الدفع وتأكيد الحوالة، ستستلم رابط تفعيل مخصص لحسابك.\n"
        "2. كل ما عليك هو فتح الرابط وتسجيل الدخول بحساب Google الخاص بك ليتم تفعيل الاشتراك مباشرة.\n"
        "3. الاشتراكات أصلية ومضمونة طوال فترة الاشتراك.\n\n"
        "📞 في حال واجهت أي مشكلة، يمكنك التواصل مع الدعم الفني مباشرة."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def my_orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View previous orders of the user"""
    user_id = update.effective_user.id
    orders = await database.get_user_orders(user_id, limit=5)

    if not orders:
        await update.message.reply_text(
            "📦 ليس لديك أي طلبات سابقة حتى الآن.\nيمكنك الضغط على '🛒 شراء اشتراك' لطلب اشتراكك الأول!",
            reply_markup=keyboards.get_main_menu(user_id),
        )
        return

    text = "📦 **طلباتك الأخيرة:**\n\n"
    for o in orders:
        status_emoji = {
            "PENDING": "⏳ قيد المراجعة والتحقق",
            "APPROVED": "✅ مكتمل ومُسلّم",
            "REJECTED": "❌ مرفوض",
        }.get(o["status"], o["status"])

        text += (
            f"🔹 **طلب رقم:** `{o['order_code']}`\n"
            f"• المنتج: {o['product_name']} (الكمية: {o['quantity']})\n"
            f"• المبلغ: {o['total_price']} {CURRENCY}\n"
            f"• الحالة: {status_emoji}\n"
            f"• التاريخ: {o['created_at']}\n"
        )

        if o["status"] == "APPROVED" and o["delivered_links"]:
            text += f"🔗 **روابط التفعيل المستلمة:**\n`{o['delivered_links']}`\n"
        elif o["status"] == "REJECTED" and o["reject_reason"]:
            text += f"⚠️ سبب الرفض: {o['reject_reason']}\n"

        text += "───────────────\n"

    await update.message.reply_text(text, parse_mode="Markdown")


# ==================== تدفق طلب الشراء (Order Flow) ====================

async def buy_subscription_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for buying subscription"""
    context.user_data.pop("order_draft", None)
    products = await database.get_all_products(only_active=True)
    if not products:
        await update.message.reply_text("⚠️ عذراً، لا توجد منتجات متاحة للشراء حالياً.")
        return ConversationHandler.END

    text = "🛍️ **اختر باقة الاشتراك المناسبة لك:**"
    await update.message.reply_text(
        text,
        reply_markup=keyboards.get_products_keyboard(products),
        parse_mode="Markdown",
    )
    return SELECTING_PRODUCT


async def product_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle product selection from inline keyboard"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "cancel_order":
        await query.message.edit_text("❌ تم إلغاء العملية.")
        return ConversationHandler.END

    product_id = data.split(":")[1]
    product = await database.get_product_by_id(product_id)
    if not product or product.get("is_active") == 0:
        await query.message.edit_text("⚠️ عذراً، هذا المنتج غير متوفر حالياً.")
        return ConversationHandler.END

    # Save to draft
    context.user_data["order_draft"] = {
        "product_id": product_id,
        "product_name": product["name"],
        "price": product["price"],
    }

    text = (
        f"💎 **لقد اخترت:** {product['name']}\n"
        f"💵 **السعر للحبة:** {product['price']} {CURRENCY}\n"
        f"📝 {product['description']}\n\n"
        "🔢 **الرجاء تحديد الكمية المطلوبة:**"
    )
    await query.message.edit_text(
        text,
        reply_markup=keyboards.get_quantity_keyboard(product_id),
        parse_mode="Markdown",
    )
    return SELECTING_QUANTITY


async def back_to_products_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to product list"""
    query = update.callback_query
    await query.answer()
    products = await database.get_all_products(only_active=True)
    await query.message.edit_text(
        "🛍️ **اختر باقة الاشتراك المناسبة لك:**",
        reply_markup=keyboards.get_products_keyboard(products),
        parse_mode="Markdown",
    )
    return SELECTING_PRODUCT


async def quantity_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quantity selection and prompt for payment method"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    product_id = parts[1]
    quantity = int(parts[2])

    draft = context.user_data.get("order_draft", {})
    if not draft or draft.get("product_id") != product_id:
        product = await database.get_product_by_id(product_id)
        if not product:
            await query.message.edit_text("⚠️ عذراً، المنتج غير موجود.")
            return ConversationHandler.END
        draft = {
            "product_id": product_id,
            "product_name": product["name"],
            "price": product["price"],
        }

    draft["quantity"] = quantity
    context.user_data["order_draft"] = draft

    text = (
        f"📦 **المنتج:** {draft['product_name']}\n"
        f"🔢 **الكمية:** {quantity}\n\n"
        "💳 **الرجاء اختيار طريقة الدفع المناسبة لك:**"
    )
    await query.message.edit_text(
        text,
        reply_markup=keyboards.get_payment_methods_keyboard(product_id, quantity),
        parse_mode="Markdown",
    )
    return SELECTING_PAYMENT


async def payment_method_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle chosen payment method (BaridiMob, RedotPay, Bybit)"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    product_id = parts[1]
    quantity = int(parts[2])
    method_id = parts[3]

    draft = context.user_data.get("order_draft", {})
    method = PAYMENT_METHODS.get(method_id, PAYMENT_METHODS["baridimob"])

    if method_id == "baridimob":
        total_price = draft.get("price", 1000) * quantity
        currency = "دينار"
        instructions = await database.get_payment_info()
    else:
        # RedotPay or Bybit: 2.5$ each
        price_usd = method.get("price_usd", 2.5)
        total_price = round(price_usd * quantity, 2)
        currency = method.get("currency", "$")
        instructions = method["details"]

    draft["payment_method"] = method_id
    draft["payment_method_name"] = method["name"]
    draft["total_price"] = total_price
    draft["currency"] = currency
    context.user_data["order_draft"] = draft

    summary_text = (
        f"📋 **ملخص طلبك:**\n"
        f"─────────────────\n"
        f"📦 **المنتج:** {draft['product_name']}\n"
        f"🔢 **الكمية:** {quantity}\n"
        f"💳 **طريقة الدفع:** {method['name']}\n"
        f"💰 **المبلغ الإجمالي المطلوب:** `{total_price}` {currency}\n"
        f"─────────────────\n\n"
        f"{instructions}\n\n"
        "👇 اضغط على الزر بالأسفل عندما تكون جاهزاً لإرسال إشعار التحويل ورقم الحوالة:"
    )

    await query.message.edit_text(
        summary_text,
        reply_markup=keyboards.get_payment_confirm_keyboard(),
        parse_mode="Markdown",
    )
    return AWAITING_RECEIPT


async def change_payment_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User wants to change chosen payment method"""
    query = update.callback_query
    await query.answer()

    draft = context.user_data.get("order_draft", {})
    product_id = draft.get("product_id")
    quantity = draft.get("quantity", 1)

    text = (
        f"📦 **المنتج:** {draft.get('product_name')}\n"
        f"🔢 **الكمية:** {quantity}\n\n"
        "💳 **الرجاء اختيار طريقة الدفع المناسبة لك:**"
    )
    await query.message.edit_text(
        text,
        reply_markup=keyboards.get_payment_methods_keyboard(product_id, quantity),
        parse_mode="Markdown",
    )
    return SELECTING_PAYMENT


async def proceed_to_upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User confirmed they want to upload receipt"""
    query = update.callback_query
    await query.answer()

    text = (
        "📸 **الرجاء إرسال صورة وصل / إشعار التحويل الآن.**\n\n"
        "💡 *ملاحظة:* إذا قمت بكتابة رقم التحويل في وصف الصورة (Caption)، سيتم اعتماده مباشرة، "
        "أو يمكنك إرسال الصورة وسيسألك البوت عن رقم الحوالة بعد ذلك."
    )
    await query.message.edit_text(text, parse_mode="Markdown")
    await query.message.reply_text(
        "إذا أردت التراجع يمكنك الضغط على '❌ إلغاء العملية':",
        reply_markup=keyboards.get_cancel_reply_keyboard(),
    )
    return AWAITING_RECEIPT


async def receipt_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle receipt photo upload"""
    message = update.message
    draft = context.user_data.get("order_draft")
    if not draft:
        await message.reply_text(
            "⚠️ حدث خطأ أو انتهت الجلسة. يرجى إعادة الطلب من البداية.",
            reply_markup=keyboards.get_main_menu(update.effective_user.id),
        )
        return ConversationHandler.END

    # Get the best resolution photo
    photo = message.photo[-1]
    draft["receipt_file_id"] = photo.file_id

    # Check if caption contains transfer number
    caption = (message.caption or "").strip()
    if caption:
        draft["transfer_number"] = caption
        context.user_data["order_draft"] = draft
        return await finalize_order_submission(update, context)

    # If no caption, prompt user for transfer number
    await message.reply_text(
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
        await update.message.reply_text(
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
    customer_msg = (
        f"🎉 **تم إرسال طلبك بنجاح!**\n\n"
        f"🔹 **رقم الطلب:** `{order_code}`\n"
        f"📦 **المنتج:** {draft['product_name']}\n"
        f"🔢 **الكمية:** {draft['quantity']}\n"
        f"💳 **طريقة الدفع:** {pay_method}\n"
        f"💰 **المبلغ:** {draft['total_price']} {pay_curr}\n"
        f"🧾 **رقم التحويل:** `{draft.get('transfer_number')}`\n\n"
        "⏳ جاري التحقق من إشعار التحويل من قبل الإدارة. ستصلك روابط التفعيل هنا في المحادثة فور التأكيد!"
    )
    await update.message.reply_text(
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
    """Send photo and order details to all registered admins"""
    # Check available stock
    stock_counts = await database.get_stock_counts()
    available_stock = stock_counts.get(draft["product_id"], 0)
    pay_method = draft.get("payment_method_name", "بريدي موب")
    pay_curr = draft.get("currency", "دينار")

    admin_caption = (
        f"🔔 **طلب شراء جديد: `{order_code}`**\n"
        f"─────────────────\n"
        f"👤 **العميل:** {html.escape(user.full_name)} "
        f"({f'@{user.username}' if user.username else 'لا يوجد معرف'})\n"
        f"🆔 **معرف العميل (ID):** `{user.id}`\n\n"
        f"📦 **المنتج:** {draft['product_name']}\n"
        f"🔢 **الكمية:** {draft['quantity']}\n"
        f"💳 **طريقة الدفع:** {pay_method}\n"
        f"💰 **المبلغ المطلوب:** `{draft['total_price']}` {pay_curr}\n"
        f"🧾 **رقم التحويل:** `{draft.get('transfer_number')}`\n"
        f"─────────────────\n"
        f"📦 **المخزن المحلي:** {available_stock} رابط "
        f"({'✅ متوفر محلياً' if available_stock >= draft['quantity'] else '🌐 سيتم السحب تلقائياً من API المورد أو الطلب يدوياً'})\n"
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=draft["receipt_file_id"],
                caption=admin_caption,
                reply_markup=keyboards.get_admin_order_keyboard(order_id),
                parse_mode="Markdown",
            )
        except Exception as e:
            print(f"Error notifying admin {admin_id}: {e}")


async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel order conversation"""
    context.user_data.pop("order_draft", None)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text("❌ تم إلغاء الطلب.")
    else:
        await update.message.reply_text(
            "❌ تم إلغاء العملية والعودة للقائمة الرئيسية.",
            reply_markup=keyboards.get_main_menu(update.effective_user.id),
        )
    return ConversationHandler.END
