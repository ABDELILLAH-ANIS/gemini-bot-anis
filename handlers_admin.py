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
    if data in ["adm_back_menu", "adm_dashboard"]:
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

    # Cancel pending links
    if data == "adm_cancel_pending_links":
        context.bot_data.pop(f"admin_pending_links_{user_id}", None)
        await query.message.edit_text("❌ تم إلغاء العملية ولم يتم حفظ الروابط.")
        return

    # Assign pending links to selected product
    if data.startswith("adm_assign_stock:"):
        pid = data.split(":")[1]
        pending_links = context.bot_data.pop(f"admin_pending_links_{user_id}", [])
        if not pending_links:
            await query.message.edit_text("⚠️ لم يتم العثور على روابط معلقة أو انتهت صلاحيتها.")
            return

        added_count = await database.add_links_to_stock(pid, pending_links)
        prod = await database.get_product_by_id(pid)
        prod_name = prod["name"] if prod else pid

        counts = await database.get_stock_counts()
        curr_stock = counts.get(pid, 0)

        await query.message.edit_text(
            f"🎉 **تمت إضافة الروابط بنجاح!**\n\n"
            f"📦 المنتج: **{prod_name}**\n"
            f"➕ عدد الروابط المضافة: `{added_count}` رابط\n"
            f"📊 إجمالي المخزون الحالي للمنتج: `{curr_stock}` رابط متوفر\n"
            f"☁️ تم الحفظ والمزامنة السحابية بشكل دائم 🔒",
            parse_mode="Markdown",
        )
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
        buttons = []
        for p in pending:
            text += (
                f"🔹 **طلب:** `{p['order_code']}`\n"
                f"• العميل: {p['user_name']} ({p['user_username']})\n"
                f"• المنتج: {p['product_name']} (الكمية: {p['quantity']})\n"
                f"• المبلغ: {p['total_price']} {p.get('currency', CURRENCY)}\n"
                f"• رقم التحويل: `{p['transfer_number']}`\n"
                f"• التاريخ: {p['created_at']}\n"
                f"───────────────\n"
            )
            buttons.append([
                InlineKeyboardButton(f"⚙️ إدارة طلب {p['order_code']}", callback_data=f"adm_manage_order:{p['id']}")
            ])
        buttons.append([InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="adm_dashboard")])
        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
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
        await query.answer()
        curr_chan = await database.get_proof_channel()
        if not curr_chan:
            await query.message.reply_text("⚠️ لا توجد قناة مضبوطة حالياً. يرجى ضبط القناة أولاً بالضغط على '✏️ ضبط / تغيير معرف القناة'.")
            return

        try:
            bot_me = await context.bot.get_me()
            test_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🤖 تجربة زر البوت", url=f"https://t.me/{bot_me.username}")]
            ]) if bot_me.username else None

            test_text = (
                "🎉 **New Purchase!**\n\n"
                "▪️ **Service:** Gemini AI\n"
                "👤 **By:** `(117***89)`\n"
                "🛍 **Plan:** Gemini Pro — 18 Months (Links)\n"
                "🔖 **Order No.:** `ORDER097C3CA1BC`\n"
                "   **QTY:** 1"
            )
            chat_id_target = int(curr_chan) if (curr_chan.startswith("-") and curr_chan[1:].isdigit()) else curr_chan
            await context.bot.send_message(
                chat_id=chat_id_target,
                text=test_text,
                reply_markup=test_markup,
                parse_mode="Markdown",
            )
            await query.message.reply_text(
                f"✅ **تم إرسال المنشور التجريبي بنجاح إلى القناة `{curr_chan}`!**\nتفضل بزيارة قناتك وستجد الرسالة منشورة الآن 🎉",
                parse_mode="Markdown",
            )
        except Exception as e:
            err_msg = str(e)
            logger.error(f"Failed to send test proof to {curr_chan}: {e}")
            advice = ""
            if "Chat not found" in err_msg:
                advice = "💡 **السبب المحتمل:** معرف القناة غير صحيح، أو القناة خاصة. إذا كانت القناة خاصة، يجب استخدام الـ ID الرقمي (مثال: `-100...`)."
            elif "bot is not a member" in err_msg or "administrator" in err_msg.lower():
                advice = "💡 **السبب المحتمل:** البوت ليس مضافاً داخل القناة كـ **مشرف (Administrator)**. توجه للقناة وأضف البوت مشرفاً مع صلاحية نشر الرسائل."
            elif "rights to send a message" in err_msg:
                advice = "💡 **السبب المحتمل:** البوت موجود بالقناة ولكنه لا يملك صلاحية نشر الرسائل (Post Messages)."

            await query.message.reply_text(
                f"⚠️ **تعذر إرسال المنشور التجريبي إلى القناة `{curr_chan}`!**\n\n"
                f"❌ **رسالة الخطأ من تليجرام:**\n`{err_msg}`\n\n"
                f"{advice}",
                parse_mode="Markdown",
            )
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


    # Check Supplier Balance & Stock (DigitalCore, LahaStore, and AccZone)
    if data == "adm_supplier":
        # 1. Primary Supplier: DigitalCore
        dc_bal = await supplier_api.check_digitalcore_balance()
        dc_stock = await supplier_api.get_digitalcore_stock()

        # 2. Secondary Supplier: LahaStore
        laha_bal = await supplier_api.check_supplier_balance()
        laha_stock = await supplier_api.get_supplier_gemini_stock()

        # 3. Backup Supplier: AccZone
        acc_bal = await supplier_api.check_acczone_balance()
        acc_stock = await supplier_api.get_acczone_gemini_stock()

        text = "🌐 **بيانات ورصيد مزودي الروابط (APIs):**\n─────────────────────\n\n"

        # DigitalCore Section
        text += "🥇 **1. المورد الرئيسي (DigitalCore API):**\n"
        if dc_bal.get("ok"):
            text += (
                f"• رصيد المحفظة: `{dc_bal.get('balance_text')}`\n"
                f"• إجمالي الطلبات المنفذة: `{dc_bal.get('total_orders')}` طلب\n"
            )
        else:
            text += f"• حالة الحساب: ⚠️ {dc_bal.get('error')}\n"

        if dc_stock.get("ok"):
            prods_dc = dc_stock.get("products", [])
            for p in prods_dc[:7]:
                p_name = p.get("name", "")
                p_stock = p.get("stock", 0)
                p_price = p.get("price", 0.0)
                text += f"  - {p_name}: `{p_stock}` متوفر (${p_price})\n"
        else:
            text += "  - تعذر فحص مخزون DigitalCore.\n"

        text += "\n─────────────────────\n"

        # LahaStore Section
        text += "🥈 **2. المورد الثاني (LahaStore API):**\n"
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
            text += "  - تعذر فحص مخزون LahaStore.\n"

        text += "\n─────────────────────\n"

        # AccZone Section
        text += "🥉 **3. المورد الثالث (AccZone API):**\n"
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
            text += "  - تعذر فحص مخزون AccZone.\n"

        text += (
            "\n─────────────────────\n"
            "🔄 **نظام السحب والتسليم الذكي:**\n"
            "1. يبحث في المخزن السحابي المباشر أولاً.\n"
            "2. إذا فرغ المخزن، يسحب تلقائياً وبأقل تكلفة من **DigitalCore**.\n"
            "3. كبديل ثانٍ، يسحب تلقائياً من **AccZone** أو **LahaStore**.\n"
            "4. إذا تعذرت جميع السيرفرات، يطلب منك إدخال الرابط يدوياً.\n"
        )

        await query.message.edit_text(
            text,
            reply_markup=keyboards.get_admin_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Sync & Scan Supplier Products (APIs)
    if data == "adm_sync_apis":
        await query.answer("🔄 جاري فحص ومزامنة منتجات الموردين...")
        loading_text = (
            "🔄 **جاري فحص الموردين ومزامنة المنتجات...**\n\n"
            "• فحص كتالوج DigitalCore API...\n"
            "• فحص كتالوج LahaStore API...\n"
            "• فحص خدمات AccZone API...\n"
            "يرجى الانتظار بضع ثوانٍ ⏳"
        )
        try:
            await query.message.edit_text(loading_text, parse_mode="Markdown")
        except Exception:
            pass

        new_items = await supplier_api.sync_new_supplier_products(bot=context.bot)

        # Live counts
        dc_stock = await supplier_api.get_digitalcore_stock()
        dc_count = len(dc_stock.get("products", [])) if dc_stock.get("ok") else 0
        laha_stock = await supplier_api.get_lahastore_all_products()
        laha_count = len(laha_stock.get("products", [])) if laha_stock.get("ok") else 0
        acc_stock = await supplier_api.get_acczone_all_services()
        acc_count = len(acc_stock.get("services", [])) if acc_stock.get("ok") else 0

        res_text = (
            "🎉 **اكتمل فحص ومزامنة منتجات الموردين بنجاح!**\n"
            "─────────────────────\n"
            f"🥇 **DigitalCore:** `{dc_count}` منتج نشط\n"
            f"🥈 **LahaStore:** `{laha_count}` منتج نشط\n"
            f"🥉 **AccZone:** `{acc_count}` خدمات نشطة\n"
            "─────────────────────\n"
        )
        if new_items:
            res_text += f"🆕 **تم اكتشاف وإضافة `{len(new_items)}` منتج جديد للمتجر تلقائياً:**\n\n"
            for itm in new_items:
                res_text += (
                    f"• **{itm['name']}** ({itm['supplier']})\n"
                    f"  سعر الجملة: `${itm['wholesale']}` | سعر البيع: `{itm['price_dzd']} دج` (${itm['price_usd']})\n"
                    f"  المخزون: `{itm['stock']}` قطعة | القسم: `{itm['category']}`\n\n"
                )
            res_text += "💡 يمكنك تعديل الأسعار أو إيقاف أي منتج من 'إدارة المنتجات والأسعار'."
        else:
            res_text += "✅ **جميع المنتجات لدى الموردين مسجلة ومحدثة في قاعدة البيانات مسبقاً!**\nلا توجد منتجات جديدة غير مضافة حالياً."

        await query.message.edit_text(
            res_text,
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

    # Manage specific pending order from admin panel
    if data.startswith("adm_manage_order:"):
        order_id = int(data.split(":")[1])
        order = await database.get_order_by_id(order_id)
        if not order:
            await query.answer("⚠️ الطلب غير موجود.", show_alert=True)
            return

        status_text = "⏳ معلق قيد الانتظار" if order["status"] == "PENDING" else order["status"]
        text = (
            f"📦 **إدارة الطلب رقم `{order['order_code']}`:**\n"
            f"─────────────────────\n"
            f"👤 **العميل:** {order['user_name']} (`{order['user_id']}`)\n"
            f"🛍 **المنتج:** {order['product_name']}\n"
            f"🔢 **الكمية:** {order['quantity']}\n"
            f"💰 **المبلغ:** {order['total_price']} {order.get('currency', CURRENCY)}\n"
            f"💳 **طريقة الدفع:** {order.get('payment_method', 'بريدي موب')}\n"
            f"🧾 **رقم التحويل:** `{order.get('transfer_number')}`\n"
            f"📊 **الحالة:** {status_text}\n"
            f"📅 **التاريخ:** {order['created_at']}\n"
            f"─────────────────────\n"
            "اختر الإجراء المطلوب بالأسفل 👇"
        )
        kb = [
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
                InlineKeyboardButton("🔙 رجوع للطلبات المعلقة", callback_data="adm_pending"),
            ],
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    # Notify Customer: Order In Preparation / Please Wait
    if data.startswith("adm_wait:"):
        order_id = int(data.split(":")[1])
        order = await database.get_order_by_id(order_id)
        if not order:
            await query.answer("⚠️ الطلب غير موجود.", show_alert=True)
            return

        cust_user_id = order["user_id"]
        order_code = order["order_code"]
        prod_name = order["product_name"]

        wait_msg = (
            f"⏳ **مرحباً بك عزيزي العميل!**\n\n"
            f"📌 بخصوص طلبك رقم: `{order_code}`\n"
            f"📦 المنتج: **{prod_name}**\n\n"
            f"🛠 **طلبك قيد التجهيز والتفعيل الآن من قبل إدارة المتجر.**\n"
            f"نعمل حالياً على تجهيز وشراء اشتراكك لضمان أعلى جودة.\n"
            f"يرجى الانتظار بضع دقائق وسيصلك رابط وبيانات التفعيل هنا فور الانتهاء مباشرة! 🚀\n\n"
            f"شاكرين لصبرك وحسن تعاملك معنا! 🌟"
        )
        try:
            await context.bot.send_message(
                chat_id=cust_user_id,
                text=wait_msg,
                parse_mode="Markdown",
            )
            await query.answer("✅ تم إرسال إشعار 'طلبك قيد التجهيز' للعميل بنجاح!", show_alert=True)
            await query.message.reply_text(
                f"⏳ **تم إشعار العميل بنجاح بأن طلبه قيد التجهيز!**\n\n"
                f"👤 العميل: **{order['user_name']}** (`{cust_user_id}`)\n"
                f"🔖 الطلب: `{order_code}`\n\n"
                f"العميل الآن يعلم أن طلبه قيد الشراء والتجهيز. عندما تجهز الرابط/الحساب يمكنك الضغط على **'✍️ تسليم يدوي'** أو **'✅ قبول وتسليم تلقائي'**.",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Failed to send wait notification to {cust_user_id}: {e}")
            await query.answer(f"⚠️ تعذر إرسال الإشعار للعميل: {e}", show_alert=True)
        return

    # Custom Message to Customer for specific order
    if data.startswith("adm_msg:"):
        order_id = int(data.split(":")[1])
        order = await database.get_order_by_id(order_id)
        if not order:
            await query.answer("⚠️ الطلب غير موجود.", show_alert=True)
            return

        context.bot_data[f"admin_custom_msg_{user_id}"] = order_id
        await query.answer()
        await query.message.reply_text(
            f"💬 **مراسلة مخصصة للعميل (طلب `{order['order_code']}`):**\n"
            f"─────────────────────\n"
            f"👤 العميل: **{order['user_name']}** (`{order['user_id']}`)\n"
            f"📦 المنتج: **{order['product_name']}**\n\n"
            f"✍️ **أرسل الآن نص الرسالة التي تريد توجيهها للعميل:**\n"
            f"(مثال: 'السلام عليكم، جاري تجهيز اشتراكك نحتاج 15 دقيقة' أو 'يرجى إرسال إيميلك لتفعيل الحساب').\n\n"
            f"• لإلغاء المراسلة أرسل: `/cancel_action`",
            parse_mode="Markdown",
        )
        return

    # Direct Manual Delivery (bypassing APIs)
    if data.startswith("adm_manual_deliver:"):
        order_id = int(data.split(":")[1])
        order = await database.get_order_by_id(order_id)
        if not order:
            await query.answer("⚠️ الطلب غير موجود.", show_alert=True)
            return

        if order["status"] != "PENDING":
            await query.answer(f"⚠️ هذا الطلب تمت معالجته مسبقاً ({order['status']}).", show_alert=True)
            return

        context.bot_data[f"admin_manual_order_{user_id}"] = order_id
        await query.answer()
        await query.message.reply_text(
            f"✍️ **تسليم يدوي مباشر للطلب `{order['order_code']}`:**\n"
            f"─────────────────────\n"
            f"👤 العميل: **{order['user_name']}** (`{order['user_id']}`)\n"
            f"📦 المنتج: **{order['product_name']}**\n"
            f"🔢 الكمية المطلوبة: `{order['quantity']}`\n\n"
            f"📥 **أرسل الآن رابط أو بيانات الاشتراك في رسالة:**\n"
            f"(إذا كانت الكمية أكثر من 1، ضع كل رابط في سطر منفصل).\n\n"
            f"• لإلغاء العملية أرسل: `/cancel_action`",
            parse_mode="Markdown",
        )
        return

    # Direct Reply to a Customer User ID
    if data.startswith("adm_reply_user:"):
        target_uid = int(data.split(":")[1])
        context.bot_data[f"admin_reply_user_{user_id}"] = target_uid
        await query.answer()
        await query.message.reply_text(
            f"💬 **كتابة رد مباشر للعميل (`{target_uid}`):**\n\n"
            f"✍️ أرسل رسالتك الآن في هذه المحادثة وسيتم تسليمها للعميل فوراً.\n"
            f"• لإلغاء المراسلة: `/cancel_action`",
            parse_mode="Markdown",
        )
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


def format_masked_user_id(user_id: int) -> str:
    """Format user ID as (117***89)"""
    uid_str = str(user_id) if user_id else "117000089"
    if len(uid_str) >= 5:
        return f"({uid_str[:3]}***{uid_str[-2:]})"
    elif len(uid_str) > 2:
        return f"({uid_str[0]}***{uid_str[-1]})"
    return "(***)"


async def post_order_proof_to_channel(context: ContextTypes.DEFAULT_TYPE, order: dict):
    """Broadcasts a clean, privacy-masked proof of completed order to public proof channel/group"""
    channel = await database.get_proof_channel()
    if not channel:
        return

    masked_by = format_masked_user_id(order.get("user_id", 0))
    plan_name = order.get("product_name", "Gemini Pro — 18 Months (Links)")
    quantity = order.get("quantity", 1)
    order_code = order.get("order_code", "ORDER")

    bot_username = ""
    try:
        bot_user = await context.bot.get_me()
        bot_username = bot_user.username or ""
    except Exception:
        pass

    proof_text = (
        "🎉 **New Purchase!**\n\n"
        "▪️ **Service:** Gemini AI\n"
        f"👤 **By:** `{masked_by}`\n"
        f"🛍 **Plan:** {plan_name}\n"
        f"🔖 **Order No.:** `{order_code}`\n"
        f"   **QTY:** {quantity}"
    )

    reply_markup = None
    if bot_username:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Buy / طلب اشتراك", url=f"https://t.me/{bot_username}")]
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
    """Sends the activation link(s) / credentials to the customer with instructions and posts channel proof"""
    user_id = order["user_id"]
    product_name = order.get("product_name", "الاشتراك")
    prod_id = order.get("product_id", "")

    items_formatted = ""
    for idx, l in enumerate(links, 1):
        is_url = l.startswith("http://") or l.startswith("https://")
        header = f"🔗 **رابط التفعيل #{idx}:**" if is_url else f"🔑 **بيانات / كود التفعيل #{idx}:**"
        items_formatted += f"{header}\n`{l}`\n\n"

    # Tailor instructions depending on whether it's Gemini or other digital products
    if "gemini" in prod_id.lower() or "gemini" in product_name.lower():
        instructions = (
            "🌟 **طريقة التفعيل:**\n"
            "1. قم بفتح رابط التفعيل في المتصفح.\n"
            "2. سجل الدخول بحساب Google الذي تريد تفعيل اشتراك Gemini Pro عليه.\n"
            "3. اضغط على تأكيد/قبول التفعيل ومبروك عليك الاشتراك! 🚀\n\n"
        )
    else:
        instructions = (
            "🌟 **طريقة التفعيل / الاستخدام:**\n"
            "1. استخدم الرابط أو بيانات الحساب/الكود المرفقة أعلاه لتسجيل الدخول والتفعيل.\n"
            "2. الاشتراك أصلي ومضمون طوال المدة المحددة بضمان المتجر.\n"
            "3. إذا احتجت أي مساعدة بالتفعيل يمكنك مراسلتنا هنا مباشرة وسنساعدك فوراً! 🚀\n\n"
        )

    customer_msg = (
        f"🎉 **مبروك! تم تأكيد وقبول عملية الدفع لطلبك بنجاح!**\n"
        f"─────────────────────\n"
        f"🔹 **رقم الطلب:** `{order['order_code']}`\n"
        f"📦 **المنتج:** {product_name}\n"
        f"🔢 **الكمية:** {order['quantity']}\n"
        f"─────────────────────\n\n"
        f"{items_formatted}"
        f"{instructions}"
        "شكراً لثقتك بنا ونتمنى لك تجربة ممتعة! 🌟"
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
        context.bot_data.pop(f"admin_custom_msg_{user_id}", None)
        context.bot_data.pop(f"admin_reply_user_{user_id}", None)
        await update.message.reply_text("✅ تم إلغاء العملية الحالية.")
        return

    # 0. Awaiting Custom Message for a Customer Order
    custom_msg_order_id = context.bot_data.get(f"admin_custom_msg_{user_id}")
    if custom_msg_order_id:
        order = await database.get_order_by_id(custom_msg_order_id)
        if not order:
            context.bot_data.pop(f"admin_custom_msg_{user_id}", None)
            await update.message.reply_text("⚠️ لم يتم العثور على بيانات الطلب.")
            return

        cust_uid = order["user_id"]
        order_code = order["order_code"]
        cust_msg = (
            f"📩 **رسالة من إدارة المتجر بخصوص طلبك `{order_code}`:**\n\n"
            f"{text}\n\n"
            f"─────────────────\n"
            f"💬 يمكنك الرد مباشرة على هذه الرسالة إذا طُلب منك أي معلومات أو استفسار."
        )
        try:
            await context.bot.send_message(
                chat_id=cust_uid,
                text=cust_msg,
                parse_mode="Markdown",
            )
            context.bot_data.pop(f"admin_custom_msg_{user_id}", None)
            await update.message.reply_text(
                f"✅ **تم إرسال رسالتك بنجاح للعميل {order['user_name']}!**\n\n"
                f"📌 **نص الرسالة المرسلة:**\n_{text}_",
                parse_mode="Markdown",
            )
        except Exception as e:
            await update.message.reply_text(f"⚠️ فشل إرسال الرسالة للعميل: {e}")
        return

    # 0.1 Awaiting Direct Message to a Customer User ID
    reply_target_uid = context.bot_data.get(f"admin_reply_user_{user_id}")
    if reply_target_uid:
        cust_msg = (
            f"📩 **رسالة من إدارة المتجر:**\n\n"
            f"{text}\n\n"
            f"─────────────────\n"
            f"💬 يمكنك الرد مباشرة على هذه الرسالة."
        )
        try:
            await context.bot.send_message(
                chat_id=reply_target_uid,
                text=cust_msg,
                parse_mode="Markdown",
            )
            context.bot_data.pop(f"admin_reply_user_{user_id}", None)
            await update.message.reply_text(
                f"✅ **تم إرسال الرد إلى العميل (`{reply_target_uid}`) بنجاح!**\n\n"
                f"📌 **نص الرسالة:**\n_{text}_",
                parse_mode="Markdown",
            )
        except Exception as e:
            await update.message.reply_text(f"⚠️ فشل إرسال الرسالة للعميل: {e}")
        return

    # 0.2 Smart Telegram Direct Reply: If Admin replied directly to an order/customer message in chat
    if update.message.reply_to_message:
        replied_msg = update.message.reply_to_message
        target_uid = None
        target_order_code = None

        search_text = (replied_msg.caption or "") + "\n" + (replied_msg.text or "")
        import re
        m_id = re.search(r"(?:ID|معرف العميل|معرف العميل \(ID\))[:\s*`]+(\d{5,})", search_text)
        if m_id:
            target_uid = int(m_id.group(1))

        m_order = re.search(r"(ORDER[0-9A-Z]+)", search_text)
        if m_order:
            target_order_code = m_order.group(1)

        if target_uid and target_uid not in ADMIN_IDS:
            prefix = f" بخصوص طلبك `{target_order_code}`" if target_order_code else ""
            cust_msg = (
                f"📩 **رسالة من إدارة المتجر{prefix}:**\n\n"
                f"{text}\n\n"
                f"─────────────────\n"
                f"💬 يمكنك الرد مباشرة على هذه الرسالة."
            )
            try:
                await context.bot.send_message(
                    chat_id=target_uid,
                    text=cust_msg,
                    parse_mode="Markdown",
                )
                await update.message.reply_text(
                    f"✅ **تم تسليم ردك مباشرة إلى العميل (`{target_uid}`)!**",
                    parse_mode="Markdown",
                )
                return
            except Exception as e:
                logger.warning(f"Failed to send direct reply to {target_uid}: {e}")


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
        counts = await database.get_stock_counts()
        curr_stock = counts.get(stock_product_id, 0)
        await update.message.reply_text(
            f"🎉 **تمت الإضافة بنجاح!**\n\n"
            f"📦 المنتج: **{prod_name}**\n"
            f"➕ عدد الروابط المضافة: `{added_count}` رابط\n"
            f"📊 إجمالي المخزون الحالي للمنتج: `{curr_stock}` رابط متوفر\n"
            f"☁️ تم الحفظ والمزامنة السحابية بشكل دائم 🔒",
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

        # Handle t.me links
        if "t.me/" in clean_chan:
            clean_chan = clean_chan.split("t.me/")[-1].strip().split("?")[0].strip()
            if not clean_chan.startswith("+") and not clean_chan.startswith("joinchat/"):
                clean_chan = f"@{clean_chan.lstrip('@')}"

        # Handle raw numbers vs usernames
        if not clean_chan.startswith("@") and not clean_chan.startswith("-"):
            if clean_chan.isdigit():
                clean_chan = f"-{clean_chan}" if clean_chan.startswith("100") else f"-100{clean_chan}"
            elif not clean_chan.startswith("+"):
                clean_chan = f"@{clean_chan}"

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
            "اضغط الآن على **'🧪 إرسال منشور تجريبي للقناة'** من لوحة التحكم للتأكد من وصول الرسائل! 🚀",
            parse_mode="Markdown",
        )
        return

    # 8. Fallback Smart Link Detector: If the admin pastes links directly into chat
    potential_lines = [line.strip() for line in text.split("\n") if line.strip()]
    link_candidates = [
        l for l in potential_lines 
        if any(marker in l.lower() for marker in ("http://", "https://", "serviceactive", "t.me/", ".com", ".online", ".xyz", ".me", "lh3.google"))
    ]

    if link_candidates:
        context.bot_data[f"admin_pending_links_{user_id}"] = link_candidates
        prods = await database.get_all_products(only_active=True)
        buttons = []
        for pid, prod in prods.items():
            buttons.append([InlineKeyboardButton(f"📦 {prod['name']}", callback_data=f"adm_assign_stock:{pid}")])
        buttons.append([InlineKeyboardButton("❌ إلغاء", callback_data="adm_cancel_pending_links")])

        keyboard = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(
            f"📥 **تم اكتشاف `{len(link_candidates)}` رابط في رسالتك!**\n\n"
            "👇 **يرجى اختيار المنتج المراد حفظ هذه الروابط في مخزونه السحابي:**",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

