import html
import datetime
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from config import ADMIN_IDS, PRODUCTS, CURRENCY, SUPPLIER_SHOP_ID
import database
import keyboards
import supplier_api

logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for /admin or reply button"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔️ عذراً، هذا الأمر مخصص للمسؤولين فقط.")
        return

    text = (
        "⚙️ **لوحة تحكم المسؤول (Admin Dashboard)**\n"
        "─────────────────────\n"
        "مرحباً بك في لوحة إدارة بوت اشتراكات جيميني.\n"
        "اختر العملية التي تريد إدارتها من الأزرار بالأسفل:"
    )
    await update.message.reply_text(
        text,
        reply_markup=keyboards.get_admin_menu_keyboard(),
        parse_mode="Markdown",
    )


async def admin_callback_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles admin inline keyboard callbacks"""
    query = update.callback_query
    user_id = query.from_user.id

    if not is_admin(user_id):
        await query.answer("⛔️ غير مصرح لك.", show_alert=True)
        return

    data = query.data
    await query.answer()

    # Close dashboard
    if data == "adm_close":
        await query.message.delete()
        return

    # Back to admin menu
    if data == "adm_back_menu":
        text = (
            "⚙️ **لوحة تحكم المسؤول (Admin Dashboard)**\n"
            "─────────────────────\n"
            "اختر العملية التي تريد إدارتها:"
        )
        await query.message.edit_text(
            text,
            reply_markup=keyboards.get_admin_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # View Statistics
    if data == "adm_stats":
        stats = await database.get_admin_stats()
        text = (
            "📊 **إحصائيات المتجر والمبيعات:**\n"
            "─────────────────────\n"
            f"🛒 **إجمالي الطلبات:** `{stats['total_orders']}`\n"
            f"⏳ **الطلبات المعلقة:** `{stats['pending_orders']}`\n"
            f"✅ **الطلبات المقبولة والمكتملة:** `{stats['approved_orders']}`\n"
            f"❌ **الطلبات المرفوضة:** `{stats['rejected_orders']}`\n"
            f"👥 **إجمالي العملاء:** `{stats['unique_customers']}`\n"
            f"💰 **إجمالي الأرباح والمبيعات:** `{stats['total_revenue']}` {CURRENCY}\n"
        )
        await query.message.edit_text(
            text,
            reply_markup=keyboards.get_admin_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Products Management Sub-menu
    if data == "adm_products_manage":
        text = (
            "🏷️ **إدارة المنتجات والأسعار:**\n─────────────────────\n"
            "من هنا يمكنك تعديل أسعار المنتجات الحالية، إضافة منتجات جديدة، أو إيقاف/تفعيل أي منتج."
        )
        await query.message.edit_text(
            text,
            reply_markup=keyboards.get_admin_products_management_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Select product to edit price
    if data == "adm_edit_price_select":
        prods = await database.get_all_products(only_active=False)
        text = "✏️ **اختر المنتج الذي تريد تعديل سعره:**"
        await query.message.edit_text(
            text,
            reply_markup=keyboards.get_admin_select_product_for_price_edit(prods),
            parse_mode="Markdown",
        )
        return

    # Awaiting new price for a specific product
    if data.startswith("adm_set_price_for:"):
        pid = data.split(":")[1]
        prod = await database.get_product_by_id(pid)
        if not prod:
            await query.message.edit_text("⚠️ المنتج غير موجود.")
            return

        context.bot_data[f"admin_set_price_{user_id}"] = pid
        text = (
            f"✏️ **تعديل سعر:** {prod['name']}\n"
            f"💵 **السعر الحالي:** {prod['price']} {CURRENCY}\n\n"
            "✍️ **أرسل الآن السعر الجديد بالدينار (أرقام فقط):**\n"
            "مثال: `1200`\n\n"
            "لإلغاء العملية أرسل: `/cancel_action`"
        )
        await query.message.edit_text(text, parse_mode="Markdown")
        return

    # Toggle product visibility (active / inactive)
    if data == "adm_toggle_product_select":
        prods = await database.get_all_products(only_active=False)
        text = "👁️ **اضغط على أي منتج لإيقافه أو تفعيله:**"
        await query.message.edit_text(
            text,
            reply_markup=keyboards.get_admin_select_product_for_toggle(prods),
            parse_mode="Markdown",
        )
        return

    # Perform Toggle for product
    if data.startswith("adm_toggle_for:"):
        pid = data.split(":")[1]
        await database.toggle_product_active(pid)
        prods = await database.get_all_products(only_active=False)
        await query.message.edit_reply_markup(
            reply_markup=keyboards.get_admin_select_product_for_toggle(prods)
        )
        await query.answer("تم تغيير حالة المنتج بنجاح!", show_alert=False)
        return

    # Add new product wizard start
    if data == "adm_add_product":
        context.bot_data[f"admin_add_prod_step_{user_id}"] = {"step": 1}
        text = (
            "➕ **إضافة منتج جديد (الخطوة 1 من 3):**\n\n"
            "✍️ أرسل **اسم المنتج** الآن:\n"
            "مثال: `ChatGPT Plus 1 Month` أو `اشتراك كانفا برو سنة`\n\n"
            "لإلغاء العملية أرسل: `/cancel_action`"
        )
        await query.message.edit_text(text, parse_mode="Markdown")
        return

    # View Stock
    if data == "adm_stock":
        counts = await database.get_stock_counts()
        prods = await database.get_all_products(only_active=False)
        text = "📦 **جرد المخزون الحالي للروابط:**\n─────────────────────\n"
        for pid, prod in prods.items():
            cnt = counts.get(pid, 0)
            status_dot = "🟢" if cnt > 5 else ("🟡" if cnt > 0 else "🔴")
            text += f"{status_dot} **{prod['name']}:** `{cnt}` رابط متوفر ({prod['price']} {CURRENCY})\n"
        text += "\n💡 لإضافة روابط جديدة، اضغط على زر '➕ إضافة روابط للمخزن'."
        await query.message.edit_text(
            text,
            reply_markup=keyboards.get_admin_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Select product to add links
    if data == "adm_add_links":
        prods = await database.get_all_products(only_active=True)
        text = "➕ **إضافة روابط للمخزن:**\nيرجى اختيار الباقة التي تريد تزويد روابطها:"
        await query.message.edit_text(
            text,
            reply_markup=keyboards.get_admin_select_product_for_stock(prods),
            parse_mode="Markdown",
        )
        return

    # Selected product for stock
    if data.startswith("adm_stock_for:"):
        pid = data.split(":")[1]
        prod = await database.get_product_by_id(pid)
        if not prod:
            await query.message.edit_text("⚠️ الباقة غير معروفة.")
            return

        context.bot_data[f"admin_add_stock_{user_id}"] = pid
        text = (
            f"📥 **إضافة روابط لمخزن:** {prod['name']}\n\n"
            "✍️ أرسل الروابط الآن في هذه المحادثة.\n"
            "• ضع **رابط واحد في كل سطر**.\n"
            "• يمكنك إرسال أي عدد من الروابط دفعة واحدة.\n\n"
            "لإلغاء العملية في أي وقت، أرسل: `/cancel_action`"
        )
        await query.message.edit_text(text, parse_mode="Markdown")
        return

    # Pending Orders
    if data == "adm_pending":
        pending = await database.get_pending_orders(limit=10)
        if not pending:
            text = "⏳ **الطلبات المعلقة:**\n\n🎉 لا توجد أي طلبات معلقة حالياً، جميع الطلبات تمت معالجتها!"
            await query.message.edit_text(
                text,
                reply_markup=keyboards.get_admin_menu_keyboard(),
                parse_mode="Markdown",
            )
            return

        text = "⏳ **الطلبات المعلقة قيد الانتظار:**\n─────────────────────\n"
        for p in pending:
            text += (
                f"🔹 **طلب:** `{p['order_code']}`\n"
                f"• العميل: {p['user_name']} ({p['user_username']})\n"
                f"• المنتج: {p['product_name']} (الكمية: {p['quantity']})\n"
                f"• المبلغ: {p['total_price']} {CURRENCY}\n"
                f"• رقم التحويل: `{p['transfer_number']}`\n"
                f"• التاريخ: {p['created_at']}\n"
                f"───────────────\n"
            )
        await query.message.edit_text(
            text,
            reply_markup=keyboards.get_admin_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Edit Payment Info
    if data == "adm_edit_payment":
        current_info = await database.get_payment_info()
        context.bot_data[f"admin_edit_pay_{user_id}"] = True
        text = (
            "💳 **تعديل بيانات الدفع:**\n\n"
            "البيانات الحالية:\n"
            f"{current_info}\n\n"
            "✍️ **أرسل الآن النص الجديد لبيانات الدفع وطرق التحويل:**\n"
            "(يمكنك إلغاء العملية بكتابة `/cancel_action`)"
        )
        await query.message.edit_text(text, parse_mode="Markdown")
        return

    # Proof Channel Dashboard
    if data == "adm_proof_channel":
        curr_chan = await database.get_proof_channel()
        has_chan = bool(curr_chan)
        chan_display = f"`{curr_chan}`" if has_chan else "❌ _غير مضبوطة حالياً_"
        text = (
            "📢 **إدارة قناة إثباتات المبيعات (Proofs Channel):**\n"
            "─────────────────────\n"
            f"• **القناة الحالية:** {chan_display}\n\n"
            "💡 **كيف تعمل؟**\n"
            "بمجرد قبول أي طلب للزبائن (سواء تلقائياً عبر API أو يدوياً)، سيقوم البوت بنشر إثبات تسليم فوري في قناتك مع حماية خصوصية العميل، لتعزيز الثقة وجلب زبائن جدد!\n\n"
            "⚠️ **مهم جداً:**\n"
            "يجب إضافة البوت كمشرف (Admin) داخل القناة مع منح صلاحية **نشر الرسائل (Post Messages)** لتتمكن من النشر."
        )
        await query.message.edit_text(
            text,
            reply_markup=keyboards.get_admin_proof_channel_keyboard(has_channel=has_chan),
            parse_mode="Markdown",
        )
        return

    # Set Proof Channel Prompt
    if data == "adm_set_proof_channel":
        context.bot_data[f"admin_set_proof_chan_{user_id}"] = True
        text = (
            "✏️ **ضبط قناة الإثباتات:**\n\n"
            "✍️ أرسل معرف القناة الآن:\n"
            "• إذا كانت القناة عامة (Public)، أرسل المعرف مثل: `@my_proofs_channel`\n"
            "• إذا كانت القناة خاصة (Private)، أرسل المعرف الرقمي مثل: `-1001234567890`\n\n"
            "⚠️ تأكد من إضافة البوت كمشرف (Admin) داخل القناة أولاً!\n"
            "للإلغاء أرسل: `/cancel_action`"
        )
        await query.message.edit_text(text, parse_mode="Markdown")
        return

    # Test Proof Channel
    if data == "adm_test_proof_channel":
        curr_chan = await database.get_proof_channel()
        if not curr_chan:
            await query.answer("⚠️ لا توجد قناة مضبوطة حالياً.", show_alert=True)
            return

        try:
            bot_me = await context.bot.get_me()
            test_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🤖 تجربة زر البوت", url=f"https://t.me/{bot_me.username}")]
            ]) if bot_me.username else None

            chat_id_target = int(curr_chan) if (curr_chan.startswith("-") and curr_chan[1:].isdigit()) else curr_chan
            await context.bot.send_message(
                chat_id=chat_id_target,
                text="🧪 **منشور تجريبي لقناة الإثباتات:**\nتم ربط البوت بالقناة بنجاح! سيتم نشر عمليات البيع الناجحة هنا تلقائياً لتوثيق الطلبات ✅",
                reply_markup=test_markup,
                parse_mode="Markdown",
            )
            await query.answer("✅ تم إرسال رسالة تجريبية بنجاح إلى قناتك!", show_alert=True)
        except Exception as e:
            await query.answer(f"⚠️ فشل الإرسال للقناة: {e}\nتأكد أن البوت مشرف (Admin) في القناة!", show_alert=True)
        return

    # Remove Proof Channel
    if data == "adm_remove_proof_channel":
        await database.update_proof_channel("")
        await query.answer("🗑️ تم إلغاء ربط القناة.", show_alert=False)
        text = (
            "📢 **إدارة قناة إثباتات المبيعات (Proofs Channel):**\n"
            "─────────────────────\n"
            "• **القناة الحالية:** ❌ _تم إلغاء الربط_\n\n"
            "تم إيقاف النشر التلقائي للطلبات في القناة."
        )
        await query.message.edit_text(
            text,
            reply_markup=keyboards.get_admin_proof_channel_keyboard(has_channel=False),
            parse_mode="Markdown",
        )
        return


    # Check Supplier Balance & Stock (Both LahaStore and AccZone)
    if data == "adm_supplier":
        # 1. Primary Supplier: LahaStore
        laha_bal = await supplier_api.check_supplier_balance()
        laha_stock = await supplier_api.get_supplier_gemini_stock()

        # 2. Backup Supplier: AccZone
        acc_bal = await supplier_api.check_acczone_balance()
        acc_stock = await supplier_api.get_acczone_gemini_stock()

        text = "🌐 **بيانات ورصيد مزودي الروابط (APIs):**\n─────────────────────\n\n"
        
        # LahaStore Section
        text += "🥇 **1. المورد الأساسي (LahaStore):**\n"
        if laha_bal.get("ok"):
            text += (
                f"• معرف المتجر: `{laha_bal.get('shop_id')}`\n"
                f"• رصيد المحفظة: `{laha_bal.get('balance_usd_text')}` ({laha_bal.get('balance_vnd_text')})\n"
            )
        else:
            text += f"• حالة الحساب: ⚠️ {laha_bal.get('error')}\n"

        if laha_stock.get("ok"):
            items = laha_stock.get("items", [])
            for itm in items:
                text += f"  - {itm.get('name')}: `{itm.get('stock')}` متوفر (${itm.get('priceUsd')})\n"
        else:
            text += "  - تعذر فحص مخزون جيميني.\n"

        text += "\n─────────────────────\n"

        # AccZone Section
        text += "🥈 **2. المورد الاحتياطي (AccZone):**\n"
        if acc_bal.get("ok"):
            text += (
                f"• المستخدم: `{acc_bal.get('username')}`\n"
                f"• رصيد المحفظة: `{acc_bal.get('balance_text')}`\n"
            )
        else:
            text += f"• حالة الحساب: ⚠️ {acc_bal.get('error')}\n"

        if acc_stock.get("ok"):
            items = acc_stock.get("items", [])
            for itm in items:
                text += f"  - {itm.get('name')}: `{itm.get('stock')}` متوفر (${itm.get('price')})\n"
        else:
            text += "  - تعذر فحص مخزون جيميني.\n"

        text += (
            "\n─────────────────────\n"
            "🔄 **نظام السحب الذكي:**\n"
            "1. يبحث في المخزن المحلي أولاً.\n"
            "2. إذا فرغ المخزن، يسحب تلقائياً من **LahaStore**.\n"
            "3. إذا نفد رصيد أو كمية الأول، يسحب تلقائياً من **AccZone**.\n"
            "4. إذا تعذر كلاهما، يطلب منك إدخال الرابط يدوياً.\n"
        )

        await query.message.edit_text(
            text,
            reply_markup=keyboards.get_admin_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Approve Order Clicked
    if data.startswith("adm_appr:"):
        order_id = int(data.split(":")[1])
        await process_order_approval(update, context, order_id)
        return

    # Reject Order Clicked
    if data.startswith("adm_rej:"):
        order_id = int(data.split(":")[1])
        context.bot_data[f"admin_reject_order_{user_id}"] = order_id
        text = (
            f"❌ **رفض الطلب رقم `{order_id}`:**\n\n"
            "✍️ يرجى إرسال سبب الرفض في رسالة ليتم إخطار العميل به.\n"
            "• أو أرسل `/skip_reason` لإرسال الرفض بدون تفاصيل.\n"
            "• لإلغاء الرفض أرسل `/cancel_action`."
        )
        await query.message.reply_text(text, parse_mode="Markdown")
        return


# ==================== معالجة قبول الطلب (Hybrid: Stock -> LahaStore -> AccZone -> Manual) ====================

async def process_order_approval(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    order_id: int,
):
    query = update.callback_query
    admin_id = query.from_user.id

    order = await database.get_order_by_id(order_id)
    if not order:
        await query.answer("⚠️ الطلب غير موجود.", show_alert=True)
        return

    if order["status"] != "PENDING":
        await query.answer(f"⚠️ هذا الطلب تمت معالجته مسبقاً ({order['status']}).", show_alert=True)
        return

    product_id = order["product_id"]
    quantity = order["quantity"]

    # --- 1. المحاولة الأولى: السحب من المخزن المحلي للبوت ---
    available_links = await database.get_available_links_from_stock(product_id, quantity)
    if len(available_links) >= quantity:
        link_ids = [l["id"] for l in available_links]
        urls = [l["link_url"] for l in available_links]

        await database.consume_stock_links(link_ids, order_id, order["user_id"])
        await database.mark_order_approved(order_id, urls)
        await deliver_links_to_customer(context, order, urls)

        success_caption = (
            f"✅ **تم قبول الطلب `{order['order_code']}` بنجاح!**\n"
            f"⚡️ تم تسليم `{quantity}` رابط تلقائياً من **المخزن المحلي**.\n"
            f"👤 العميل: {order['user_name']} (`{order['user_id']}`)\n"
            f"📦 المنتج: {order['product_name']}\n"
            f"💳 طريقة الدفع: {order.get('payment_method', 'بريدي موب')}\n"
            f"💰 المبلغ المحصل: {order['total_price']} {order.get('currency', CURRENCY)}"
        )
        try:
            await query.message.edit_caption(
                caption=success_caption,
                parse_mode="Markdown",
                reply_markup=None,
            )
        except Exception:
            await query.message.reply_text(success_caption, parse_mode="Markdown")

        await query.answer("✅ تم التسليم من المخزن المحلي بنجاح!", show_alert=False)
        return

    # --- 2. المحاولة الثانية: الشراء التلقائي عبر API (LahaStore أولاً ثم AccZone كبديل) ---
    api_success, api_links, api_msg, provider_used = await supplier_api.purchase_with_fallback(
        local_product_id=product_id,
        quantity=quantity,
        order_code=order["order_code"],
    )

    if api_success and api_links:
        await database.mark_order_approved(order_id, api_links)
        await deliver_links_to_customer(context, order, api_links)

        success_caption = (
            f"✅ **تم قبول الطلب `{order['order_code']}` بنجاح!**\n"
            f"⚡️ تم سحب `{quantity}` رابط وتوليده تلقائياً عبر **API المورد ({provider_used})**.\n"
            f"👤 العميل: {order['user_name']} (`{order['user_id']}`)\n"
            f"📦 المنتج: {order['product_name']}\n"
            f"💳 طريقة الدفع: {order.get('payment_method', 'بريدي موب')}\n"
            f"💰 المبلغ المحصل: {order['total_price']} {order.get('currency', CURRENCY)}"
        )
        try:
            await query.message.edit_caption(
                caption=success_caption,
                parse_mode="Markdown",
                reply_markup=None,
            )
        except Exception:
            await query.message.reply_text(success_caption, parse_mode="Markdown")

        await query.answer(f"✅ تم الشراء والتسليم عبر {provider_used} بنجاح!", show_alert=False)
        return

    # --- 3. المحاولة الثالثة: طلب الرابط يدوياً من الأدمن (في حال عدم توفره بالمخزن وبكلا الموردين) ---
    context.bot_data[f"admin_manual_order_{admin_id}"] = order_id
    alert_text = (
        f"⚠️ **تنبيه: تعذر التسليم التلقائي للطلب `{order['order_code']}`!**\n\n"
        f"• المخزن المحلي: متوفر `{len(available_links)}` فقط (المطلوب: `{quantity}`).\n"
        f"• نتيجة الموردين (APIs): {api_msg}\n\n"
        f"✍️ **يرجى إرسال رابط التفعيل يدوياً الآن في هذه المحادثة:**\n"
        f"(إذا كانت الكمية أكثر من 1، يمكنك وضع كل رابط في سطر منفصل).\n\n"
        "لإلغاء العملية أرسل: `/cancel_action`"
    )
    await query.message.reply_text(alert_text, parse_mode="Markdown")
    await query.answer("⚠️ يرجى إدخال الرابط يدوياً (المخازن والموردين غير متاحين حالياً).", show_alert=True)


def mask_customer_info(name: str, username: str, user_id: int) -> str:
    """Masks sensitive customer personal info for public proofs channel"""
    parts = []
    if name:
        clean_name = name.strip()
        if len(clean_name) <= 2:
            parts.append(clean_name[0] + "*")
        else:
            parts.append(f"{clean_name[0]}{'*' * min(3, len(clean_name)-2)}{clean_name[-1]}")

    if username:
        u = username.lstrip("@").strip()
        if len(u) <= 2:
            parts.append(f"(@{u[0]}*)")
        else:
            parts.append(f"(@{u[0]}{'*' * min(3, len(u)-2)}{u[-1]})")
    elif user_id:
        uid_str = str(user_id)
        if len(uid_str) > 4:
            parts.append(f"({uid_str[:4]}****)")

    return " ".join(parts) if parts else "عميل مميز ⭐"


async def post_order_proof_to_channel(context: ContextTypes.DEFAULT_TYPE, order: dict):
    """Broadcasts a clean, privacy-masked proof of completed order to public proof channel"""
    channel = await database.get_proof_channel()
    if not channel:
        return

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    masked_cust = mask_customer_info(
        order.get("user_name", ""),
        order.get("user_username", ""),
        order.get("user_id", 0),
    )

    currency = order.get("currency", CURRENCY)
    price_val = order.get("total_price", 0)
    payment_method = order.get("payment_method", "بريدي موب")
    product_name = order.get("product_name", "اشتراك Google AI Pro")
    quantity = order.get("quantity", 1)
    order_code = order.get("order_code", "ORD")

    bot_username = ""
    try:
        bot_user = await context.bot.get_me()
        bot_username = bot_user.username or ""
    except Exception:
        pass

    proof_text = (
        "🛍️ **عملية تسليم وتفعيل ناجحة! ✅**\n"
        "─────────────────────\n"
        f"📦 **المنتج:** {product_name}\n"
        f"🔢 **الكمية:** {quantity}\n"
        f"💳 **طريقة الدفع:** {payment_method}\n"
        f"💰 **المبلغ:** `{price_val}` {currency}\n"
        f"👤 **العميل:** {masked_cust}\n"
        f"🆔 **رقم الطلب:** `#{order_code}`\n"
        f"🕒 **التاريخ:** {now_str}\n"
        "─────────────────────\n"
        "⚡️ **الحالة:** تم تسليم رابط التفعيل الرسمي للعميل بنجاح 🚀\n"
        "💎 نسعد دائماً بثقتكم واختياركم لنا!\n\n"
        "👇 **لطلب اشتراكك الخاص فوراً عبر البوت:**"
    )

    reply_markup = None
    if bot_username:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 اطلب اشتراكك الآن من البوت", url=f"https://t.me/{bot_username}")]
        ])

    try:
        chat_id_target = int(channel) if (channel.startswith("-") and channel[1:].isdigit()) else channel
        await context.bot.send_message(
            chat_id=chat_id_target,
            text=proof_text,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
        logger.info(f"Proof posted to channel {channel} for order {order_code}")
    except Exception as e:
        logger.warning(f"Could not post proof to channel {channel}: {e}")


async def deliver_links_to_customer(
    context: ContextTypes.DEFAULT_TYPE,
    order: dict,
    links: list[str],
):
    """Sends the activation link(s) to the customer with full instructions and posts channel proof"""
    user_id = order["user_id"]

    links_formatted = ""
    for idx, l in enumerate(links, 1):
        links_formatted += f"🔗 **رابط التفعيل #{idx}:**\n`{l}`\n\n"

    customer_msg = (
        f"🎉 **مبروك! تم تأكيد وقبول عملية الدفع لطلبك بنجاح!**\n"
        f"─────────────────────\n"
        f"🔹 **رقم الطلب:** `{order['order_code']}`\n"
        f"📦 **المنتج:** {order['product_name']}\n"
        f"🔢 **الكمية:** {order['quantity']}\n"
        f"─────────────────────\n\n"
        f"{links_formatted}"
        "🌟 **طريقة التفعيل:**\n"
        "1. قم بفتح رابط التفعيل في المتصفح.\n"
        "2. سجل الدخول بحساب Google الذي تريد تفعيل اشتراك Gemini Pro عليه.\n"
        "3. اضغط على تأكيد/قبول التفعيل ومبروك عليك الاشتراك! 🚀\n\n"
        "شكراً لثقتك بنا! إذا كان لديك أي استفسار يسعدنا دائماً خدمتك."
    )

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=customer_msg,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Failed to deliver links to user {user_id}: {e}")

    # Post proof to public channel
    try:
        await post_order_proof_to_channel(context, order)
    except Exception as e:
        logger.warning(f"Error posting proof to channel: {e}")



# ==================== معالج النصوص الخاصة بالمسؤول ====================

async def handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages from admins when awaiting manual links, stock additions, or reasons"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    text = update.message.text.strip()

    # Cancel command check
    if text in ["/cancel_action", "الغاء", "إلغاء"]:
        context.bot_data.pop(f"admin_manual_order_{user_id}", None)
        context.bot_data.pop(f"admin_reject_order_{user_id}", None)
        context.bot_data.pop(f"admin_add_stock_{user_id}", None)
        context.bot_data.pop(f"admin_edit_pay_{user_id}", None)
        context.bot_data.pop(f"admin_set_price_{user_id}", None)
        context.bot_data.pop(f"admin_add_prod_step_{user_id}", None)
        context.bot_data.pop(f"admin_set_proof_chan_{user_id}", None)
        await update.message.reply_text("✅ تم إلغاء العملية الحالية.")
        return

    # 1. Awaiting new price for product
    edit_price_pid = context.bot_data.get(f"admin_set_price_{user_id}")
    if edit_price_pid:
        try:
            new_price = float(text.replace(",", "."))
            if new_price <= 0:
                await update.message.reply_text("⚠️ يرجى إدخال سعر موجب.")
                return
            await database.update_product_price(edit_price_pid, new_price)
            prod = await database.get_product_by_id(edit_price_pid)
            context.bot_data.pop(f"admin_set_price_{user_id}", None)
            await update.message.reply_text(
                f"✅ **تم تحديث السعر بنجاح!**\n"
                f"المنتج: **{prod['name'] if prod else edit_price_pid}** أصبح بسعر `{new_price}` {CURRENCY}.",
                parse_mode="Markdown",
            )
            return
        except ValueError:
            await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح للسعر (مثال: 1200).")
            return

    # 2. Add product wizard
    add_prod_state = context.bot_data.get(f"admin_add_prod_step_{user_id}")
    if add_prod_state:
        step = add_prod_state.get("step", 1)
        if step == 1:
            add_prod_state["name"] = text
            add_prod_state["step"] = 2
            context.bot_data[f"admin_add_prod_step_{user_id}"] = add_prod_state
            await update.message.reply_text(
                "➕ **إضافة منتج جديد (الخطوة 2 من 3):**\n\n"
                f"الاسم: **{text}**\n"
                "✍️ الآن أرسل **السعر بالدينار** (أرقام فقط، مثال: `1500`):",
                parse_mode="Markdown",
            )
            return
        elif step == 2:
            try:
                price = float(text.replace(",", "."))
                if price <= 0:
                    await update.message.reply_text("⚠️ يرجى إدخال سعر أكبر من الصفر.")
                    return
                add_prod_state["price"] = price
                add_prod_state["step"] = 3
                context.bot_data[f"admin_add_prod_step_{user_id}"] = add_prod_state
                await update.message.reply_text(
                    "➕ **إضافة منتج جديد (الخطوة 3 من 3):**\n\n"
                    f"السعر: `{price}` {CURRENCY}\n"
                    "✍️ الآن أرسل **وصف مختصر للمنتج** (أو أرسل `/skip_desc` للمتابعة بدون وصف):",
                    parse_mode="Markdown",
                )
                return
            except ValueError:
                await update.message.reply_text("⚠️ يرجى كتابة أرقام فقط للسعر (مثال: 1500).")
                return
        elif step == 3:
            import time
            desc = text if text != "/skip_desc" else "اشتراك رقمي أصلي بضمان كامل."
            name = add_prod_state["name"]
            price = add_prod_state["price"]
            prod_id = f"prod_{int(time.time())}"

            await database.add_new_product(
                product_id=prod_id,
                name=name,
                price=price,
                description=desc,
                supplier_product_id=None,
            )
            context.bot_data.pop(f"admin_add_prod_step_{user_id}", None)
            await update.message.reply_text(
                f"🎉 **تمت إضافة المنتج الجديد بنجاح!**\n\n"
                f"📦 **الاسم:** {name}\n"
                f"💵 **السعر:** `{price}` {CURRENCY}\n"
                f"📝 **الوصف:** {desc}\n\n"
                "أصبح المنتج متاحاً فوراً لجميع الزبائن في قائمة الشراء! 🚀",
                parse_mode="Markdown",
            )
            return

    # 3. Awaiting manual links for an order
    manual_order_id = context.bot_data.get(f"admin_manual_order_{user_id}")
    if manual_order_id:
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            await update.message.reply_text("⚠️ يرجى إرسال رابط صالح.")
            return

        order = await database.get_order_by_id(manual_order_id)
        if not order:
            context.bot_data.pop(f"admin_manual_order_{user_id}", None)
            await update.message.reply_text("⚠️ الطلب غير موجود.")
            return

        await database.mark_order_approved(manual_order_id, lines)
        await deliver_links_to_customer(context, order, lines)

        context.bot_data.pop(f"admin_manual_order_{user_id}", None)
        await update.message.reply_text(
            f"✅ **تم إرسال الروابط للعميل بنجاح واكتمال الطلب `{order['order_code']}`!**",
            parse_mode="Markdown",
        )
        return

    # 4. Awaiting rejection reason
    reject_order_id = context.bot_data.get(f"admin_reject_order_{user_id}")
    if reject_order_id:
        reason = text if text != "/skip_reason" else "لم يتم التحقق من صحة عملية التحويل"
        order = await database.get_order_by_id(reject_order_id)

        if order:
            await database.mark_order_rejected(reject_order_id, reason)
            cust_text = (
                f"❌ **نعتذر منك، تم رفض طلبك رقم `{order['order_code']}`.**\n\n"
                f"⚠️ **السبب:** {reason}\n\n"
                "إذا كنت ترى أن هناك خطأ أو ترغب في إعادة المحاولة، يرجى مراجعة إشعار التحويل أو التواصل معنا."
            )
            try:
                await context.bot.send_message(
                    chat_id=order["user_id"],
                    text=cust_text,
                    parse_mode="Markdown",
                )
            except Exception as e:
                print(f"Could not notify user of rejection: {e}")

        context.bot_data.pop(f"admin_reject_order_{user_id}", None)
        await update.message.reply_text(
            f"✅ تم رفض الطلب وتسجيل السبب وإشعار العميل.",
            parse_mode="Markdown",
        )
        return

    # 5. Adding links to stock
    stock_product_id = context.bot_data.get(f"admin_add_stock_{user_id}")
    if stock_product_id:
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            await update.message.reply_text("⚠️ يرجى إدخال روابط صحيحة.")
            return

        added_count = await database.add_links_to_stock(stock_product_id, lines)
        prod = await database.get_product_by_id(stock_product_id)
        prod_name = prod["name"] if prod else stock_product_id

        context.bot_data.pop(f"admin_add_stock_{user_id}", None)
        await update.message.reply_text(
            f"🎉 **تمت الإضافة بنجاح!**\n"
            f"تمت إضافة `{added_count}` رابط جديد إلى مخزن: **{prod_name}**.",
            parse_mode="Markdown",
        )
        return

    # 6. Editing payment info
    if context.bot_data.get(f"admin_edit_pay_{user_id}"):
        await database.update_payment_info(text)
        context.bot_data.pop(f"admin_edit_pay_{user_id}", None)
        await update.message.reply_text(
            "✅ **تم تحديث بيانات وطرق الدفع بنجاح!**\nستظهر الآن الصيغة الجديدة لجميع العملاء.",
            parse_mode="Markdown",
        )
        return

    # 7. Editing proof channel
    if context.bot_data.get(f"admin_set_proof_chan_{user_id}"):
        clean_chan = text.strip()
        if not (clean_chan.startswith("@") or clean_chan.startswith("-")):
            await update.message.reply_text(
                "⚠️ صيغة المعرف غير صحيحة.\n"
                "• للقنوات العامة: يجب أن يبدأ بـ `@` (مثال: `@my_channel`)\n"
                "• للقنوات الخاصة: يجب أن يبدأ برقم القناة (مثال: `-1001234567890`)\n\n"
                "أعد المحاولة أو أرسل `/cancel_action` للإلغاء."
            )
            return

        await database.update_proof_channel(clean_chan)
        context.bot_data.pop(f"admin_set_proof_chan_{user_id}", None)

        title_info = ""
        try:
            chat_id_target = int(clean_chan) if (clean_chan.startswith("-") and clean_chan[1:].isdigit()) else clean_chan
            chat_obj = await context.bot.get_chat(chat_id_target)
            title = chat_obj.title or clean_chan
            title_info = f"\n📢 اسم القناة: **{title}**"
        except Exception as e:
            title_info = f"\n⚠️ تذكير: تأكد من إضافة البوت كمشرف (Admin) في القناة بصلاحية نشر الرسائل لكي يتمكن من إرسال الإثباتات."

        await update.message.reply_text(
            f"✅ **تم ضبط قناة إثباتات المبيعات بنجاح!**\n"
            f"القناة: `{clean_chan}`{title_info}\n\n"
            "سيتم الآن إرسال إثباتات الطلبات الناجحة تلقائياً في هذه القناة لزيادة ثقة الزبائن! 🚀",
            parse_mode="Markdown",
        )
        return

