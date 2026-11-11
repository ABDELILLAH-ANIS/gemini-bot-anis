import html
import asyncio
import datetime
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
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


def has_active_admin_prompt(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if the admin currently has an active text-input prompt in bot_data"""
    if user_id not in ADMIN_IDS:
        return False
    for key_prefix in (
        "admin_manual_order_",
        "admin_reject_order_",
        "admin_add_stock_",
        "admin_edit_pay_",
        "admin_set_price_",
        "admin_set_price_usd_",
        "admin_set_inst_",
        "admin_add_prod_step_",
        "admin_set_proof_chan_",
        "admin_custom_msg_",
        "admin_reply_user_",
        "admin_edit_topup_",
        "admin_reject_topup_",
        "admin_manual_wallet_step_",
    ):
        if context.bot_data.get(f"{key_prefix}{user_id}") is not None:
            return True
    return False


def escape_md(val) -> str:
    """Safely escape legacy Telegram Markdown v1 special characters in dynamic strings"""
    if val is None:
        return ""
    s = str(val)
    for ch in ("_", "*", "`", "["):
        s = s.replace(ch, f"\\{ch}")
    return s


def format_dt(val) -> str:
    """Cleanly format ISO timestamp for display"""
    if not val:
        return "غير محدد"
    return str(val)[:19].replace("T", " ")


async def safe_answer(query, text: str | None = None, show_alert: bool = False):
    """Answer a CallbackQuery at most once without raising BadRequest if already answered/expired"""
    if getattr(query, "_answered_safely", False):
        return
    try:
        await query.answer(text=text, show_alert=show_alert)
        setattr(query, "_answered_safely", True)
    except Exception as e:
        logger.debug(f"CallbackQuery answer ignored: {e}")


async def safe_edit_text(message, text: str, reply_markup=None, parse_mode: str | None = "Markdown"):
    """Safely edit message text with automatic fallback if Markdown fails, message unchanged, or photo message"""
    if len(text) > 4050:
        text = text[:4040] + "\n..."
    try:
        if getattr(message, "photo", None):
            return await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        err_str = str(e)
        if "Message is not modified" in err_str:
            return None
        if "Can't parse entities" in err_str:
            clean_text = text.replace("**", "").replace("`", "").replace("\\_", "_").replace("\\*", "*")
            try:
                if getattr(message, "photo", None):
                    return await message.reply_text(clean_text, reply_markup=reply_markup, parse_mode=None)
                return await message.edit_text(clean_text, reply_markup=reply_markup, parse_mode=None)
            except Exception as inner_e:
                logger.error(f"Fallback edit_text failed: {inner_e}")
                return None
        try:
            return await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            clean_text = text.replace("**", "").replace("`", "")
            return await message.reply_text(clean_text, reply_markup=reply_markup, parse_mode=None)
    except Exception as e:
        logger.error(f"Unexpected error in safe_edit_text: {e}")
        return None


async def safe_reply_text(message, text: str, reply_markup=None, parse_mode: str | None = "Markdown"):
    """Safely reply_text with fallback to plain text if Markdown parsing fails"""
    try:
        return await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        clean_text = text.replace("**", "").replace("`", "").replace("\\_", "_").replace("\\*", "*")
        return await message.reply_text(clean_text, reply_markup=reply_markup, parse_mode=None)


async def safe_send_message(bot, chat_id, text: str, reply_markup=None, parse_mode: str | None = "Markdown"):
    """Safely send_message with fallback to plain text if Markdown parsing fails"""
    try:
        return await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        clean_text = text.replace("**", "").replace("`", "").replace("\\_", "_").replace("\\*", "*")
        return await bot.send_message(chat_id=chat_id, text=clean_text, reply_markup=reply_markup, parse_mode=None)


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
    await safe_reply_text(
        update.message,
        text,
        reply_markup=keyboards.get_admin_menu_keyboard(),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def admin_callback_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles admin inline keyboard callbacks"""
    query = update.callback_query
    user_id = query.from_user.id

    if not is_admin(user_id):
        await safe_answer(query, "⛔️ غير مصرح لك.", show_alert=True)
        return

    data = query.data

    # Close dashboard
    if data == "adm_close":
        await safe_answer(query)
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    # Back to admin menu
    if data in ["adm_back_menu", "adm_dashboard"]:
        await safe_answer(query)
        text = (
            "⚙️ **لوحة تحكم المسؤول (Admin Dashboard)**\n"
            "─────────────────────\n"
            "اختر العملية التي تريد إدارتها:"
        )
        await safe_edit_text(
            query.message,
            text,
            reply_markup=keyboards.get_admin_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # View Statistics
    if data == "adm_stats":
        await safe_answer(query, "📊 جاري تحديث الإحصائيات...")
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
        await safe_edit_text(
            query.message,
            text,
            reply_markup=keyboards.get_admin_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Products Management Sub-menu
    if data == "adm_products_manage":
        await safe_answer(query)
        text = (
            "🏷️ **إدارة المنتجات والأسعار والتعليمات:**\n─────────────────────\n"
            "• تعديل السعر بالدينار الجزائري (`دج`) وبالدولار (`$`).\n"
            "• التحكم بتعليمات وشروط كل منتج التي تظهر للعميل.\n"
            "• إضافة منتج جديد أو إيقاف/تفعيل أي منتج."
        )
        await safe_edit_text(
            query.message,
            text,
            reply_markup=keyboards.get_admin_products_management_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Select product to edit price (supports pagination adm_edit_price_select or adm_edit_price_select:page)
    if data == "adm_edit_price_select" or data.startswith("adm_edit_price_select:"):
        await safe_answer(query)
        parts = data.split(":")
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        prods = await database.get_all_products(only_active=False)
        text = "✏️ **اختر المنتج لتعديل سعره (بالدينار أو الدولار) أو تعليماته:**"
        await safe_edit_text(
            query.message,
            text,
            reply_markup=keyboards.get_admin_select_product_for_price_edit(prods, page=page),
            parse_mode="Markdown",
        )
        return

    # Select product to edit instructions (paginated)
    if data == "adm_edit_inst_select" or data.startswith("adm_edit_inst_select:"):
        await safe_answer(query)
        parts = data.split(":")
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        prods = await database.get_all_products(only_active=False)
        text = "🔵 📖 **اختر المنتج الذي تريد تعديل تعليماته وشروطه للزبون:**"
        await safe_edit_text(
            query.message,
            text,
            reply_markup=keyboards.get_admin_select_product_for_inst_edit(prods, page=page),
            parse_mode="Markdown",
        )
        return

    # Product selected for price/instructions management
    if data.startswith("adm_set_price_for:") or data.startswith("adm_edit_price:"):
        await safe_answer(query)
        pid = data.split(":", 1)[1]
        prod = await database.get_product_by_id(pid)
        if not prod:
            await safe_edit_text(query.message, "⚠️ المنتج غير موجود.")
            return

        p_usd = prod.get("price_usd", 2.5)
        inst = (prod.get("instructions") or prod.get("description") or "غير محدد")[:250]
        text = (
            f"⚙️ **إدارة سعر وتعليمات المنتج:**\n"
            f"─────────────────────\n"
            f"📦 **المنتج:** {escape_md(prod['name'])}\n"
            f"🇩🇿 **السعر الحالي بالدينار:** `{prod['price']}` {CURRENCY}\n"
            f"💵 **السعر الحالي بالدولار:** `${p_usd}`\n"
            f"📖 **التعليمات الحالية:**\n{escape_md(inst)}\n"
            f"─────────────────────\n"
            "👇 اختر ما تريد تعديله لهذا المنتج:"
        )
        kb = InlineKeyboardMarkup([
            [keyboards._btn(f"🇩🇿 تعديل السعر بالدينار ({prod['price']} {CURRENCY})", callback_data=f"adm_price_dzd:{pid}", style="success")],
            [keyboards._btn(f"💵 تعديل السعر بالدولار (${p_usd})", callback_data=f"adm_price_usd:{pid}", style="primary")],
            [keyboards._btn("🔵 📖 تعديل تعليمات وشروط المنتج", callback_data=f"adm_inst_for:{pid}", style="primary")],
            [keyboards._btn("🔙 رجوع لقائمة المنتجات", callback_data="adm_edit_price_select:0")],
        ])
        await safe_edit_text(query.message, text, reply_markup=kb, parse_mode="Markdown")
        return

    # Prompt for new DZD price
    if data.startswith("adm_price_dzd:"):
        await safe_answer(query)
        pid = data.split(":", 1)[1]
        prod = await database.get_product_by_id(pid)
        if not prod:
            await safe_edit_text(query.message, "⚠️ المنتج غير موجود.")
            return

        context.bot_data[f"admin_set_price_{user_id}"] = pid
        text = (
            f"🇩🇿 **تعديل السعر بالدينار للمنتج:** {escape_md(prod['name'])}\n"
            f"💵 **السعر الحالي:** `{prod['price']}` {CURRENCY}\n\n"
            "✍️ **أرسل الآن السعر الجديد بالدينار (أرقام فقط):**\n"
            "مثال: `1200` أو `6000`\n\n"
            "لإلغاء العملية أرسل: `/cancel_action`"
        )
        await safe_edit_text(query.message, text, parse_mode="Markdown")
        return

    # Prompt for new USD price
    if data.startswith("adm_price_usd:"):
        await safe_answer(query)
        pid = data.split(":", 1)[1]
        prod = await database.get_product_by_id(pid)
        if not prod:
            await safe_edit_text(query.message, "⚠️ المنتج غير موجود.")
            return

        context.bot_data[f"admin_set_price_usd_{user_id}"] = pid
        p_usd = prod.get("price_usd", 2.5)
        text = (
            f"💵 **تعديل السعر بالدولار ($) للمنتج:** {escape_md(prod['name'])}\n"
            f"💲 **السعر الحالي بالدولار:** `${p_usd}`\n\n"
            "✍️ **أرسل الآن السعر الجديد بالدولار (أرقام فقط):**\n"
            "مثال: `2.5` أو `15`\n\n"
            "لإلغاء العملية أرسل: `/cancel_action`"
        )
        await safe_edit_text(query.message, text, parse_mode="Markdown")
        return

    # Prompt for editing Product Instructions
    if data.startswith("adm_inst_for:"):
        await safe_answer(query)
        pid = data.split(":", 1)[1]
        prod = await database.get_product_by_id(pid)
        if not prod:
            await safe_edit_text(query.message, "⚠️ المنتج غير موجود.")
            return

        context.bot_data[f"admin_set_inst_{user_id}"] = pid
        curr_inst = prod.get("instructions") or prod.get("description") or "لا توجد تعليمات مخصصة بعد."
        text = (
            f"🔵 📖 **تعديل تعليمات وشروط المنتج:** {escape_md(prod['name'])}\n"
            f"─────────────────────\n"
            f"📋 **التعليمات الحالية:**\n{escape_md(curr_inst)}\n"
            f"─────────────────────\n\n"
            "✍️ **أرسل الآن النص الجديد لتعليمات وشروط هذا المنتج:**\n"
            "(سيظهر هذا النص للزبون عند الضغط على الزر الأزرق `📖 تعليمات وشروط المنتج` وكذلك عند تسليم الطلب).\n\n"
            "لإلغاء العملية أرسل: `/cancel_action`"
        )
        await safe_edit_text(query.message, text, parse_mode="Markdown")
        return

    # Toggle product visibility (active / inactive) with pagination
    if data == "adm_toggle_product_select" or data.startswith("adm_toggle_product_select:"):
        await safe_answer(query)
        parts = data.split(":")
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        prods = await database.get_all_products(only_active=False)
        text = "👁️ **اضغط على أي منتج لإيقافه أو تفعيله:**"
        await safe_edit_text(
            query.message,
            text,
            reply_markup=keyboards.get_admin_select_product_for_toggle(prods, page=page),
            parse_mode="Markdown",
        )
        return

    # Perform Toggle for product (supports adm_toggle_for:pid:page and adm_toggle_prod:pid)
    if data.startswith("adm_toggle_for:") or data.startswith("adm_toggle_prod:"):
        parts = data.split(":")
        pid = parts[1]
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        is_now_active = await database.toggle_product_active(pid)
        status_label = "🟢 مفعّل" if is_now_active else "🔴 متوقف"
        await safe_answer(query, f"تم تغيير حالة المنتج إلى: {status_label}", show_alert=False)
        if data.startswith("adm_toggle_for:"):
            prods = await database.get_all_products(only_active=False)
            try:
                await query.message.edit_reply_markup(
                    reply_markup=keyboards.get_admin_select_product_for_toggle(prods, page=page)
                )
            except Exception:
                pass
        return

    # Add new product wizard start
    if data == "adm_add_product":
        await safe_answer(query)
        context.bot_data[f"admin_add_prod_step_{user_id}"] = {"step": 1}
        text = (
            "➕ **إضافة منتج جديد (الخطوة 1 من 3):**\n\n"
            "✍️ أرسل **اسم المنتج** الآن:\n"
            "مثال: `ChatGPT Plus 1 Month` أو `اشتراك كانفا برو سنة`\n\n"
            "لإلغاء العملية أرسل: `/cancel_action`"
        )
        await safe_edit_text(query.message, text, parse_mode="Markdown")
        return

    # View Stock
    if data == "adm_stock":
        await safe_answer(query, "📦 جاري جرد المخزن...")
        counts = await database.get_stock_counts()
        prods = await database.get_all_products(only_active=False)
        text = "📦 **جرد المخزون المحلي للروابط:**\n─────────────────────\n"
        for pid, prod in prods.items():
            cnt = counts.get(pid, 0)
            status_dot = "🟢" if cnt > 5 else ("🟡" if cnt > 0 else "🔴")
            p_usd = prod.get("price_usd", 2.5)
            text += f"{status_dot} **{escape_md(prod['name'])}:** `{cnt}` رابط ({prod['price']} {CURRENCY} | ${p_usd})\n"
        text += "\n💡 لإضافة روابط اضغط '➕ إضافة روابط للمخزن'، ولحذف روابط اضغط '🗑️ حذف روابط من المخزن'."
        await safe_edit_text(
            query.message,
            text,
            reply_markup=keyboards.get_admin_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Select product to add links (paginated)
    if data == "adm_add_links" or data.startswith("adm_add_links_page:"):
        await safe_answer(query)
        parts = data.split(":")
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        prods = await database.get_all_products(only_active=True)
        text = "➕ **إضافة روابط للمخزن:**\nيرجى اختيار الباقة التي تريد تزويد روابطها:"
        await safe_edit_text(
            query.message,
            text,
            reply_markup=keyboards.get_admin_select_product_for_stock(prods, page=page),
            parse_mode="Markdown",
        )
        return

    # Delete Stock Links Menu (paginated)
    if data == "adm_del_links_menu" or data.startswith("adm_del_links_menu:"):
        await safe_answer(query)
        parts = data.split(":")
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        prods = await database.get_all_products(only_active=False)
        counts = await database.get_stock_counts()
        text = (
            "🗑️ **حذف روابط من المخزون:**\n"
            "─────────────────────\n"
            "اختر المنتج لعرض الروابط المتوفرة بداخله وحذف رابط معين أو تفريغ مخزونه:"
        )
        await safe_edit_text(
            query.message,
            text,
            reply_markup=keyboards.get_admin_select_product_for_del_stock(prods, counts, page=page),
            parse_mode="Markdown",
        )
        return

    # View unused links for a specific product & delete buttons
    if data.startswith("adm_del_stock_prod:"):
        await safe_answer(query)
        pid = data.split(":", 1)[1]
        prod = await database.get_product_by_id(pid)
        prod_name = prod["name"] if prod else pid
        links = await database.get_unused_links_for_product(pid, limit=25)

        if not links:
            text = (
                f"📦 **مخزون المنتج:** {escape_md(prod_name)}\n\n"
                "⚪ لا توجد أي روابط متوفرة في المخزون المحلي لهذا المنتج حالياً."
            )
            kb = InlineKeyboardMarkup([
                [keyboards._btn("➕ إضافة روابط لهذا المنتج", callback_data=f"adm_stock_for:{pid}", style="success")],
                [keyboards._btn("🔙 رجوع لقائمة المخزون", callback_data="adm_del_links_menu:0")],
            ])
            await safe_edit_text(query.message, text, reply_markup=kb, parse_mode="Markdown")
            return

        text = (
            f"🗑️ **إدارة وحذف روابط المخزون:**\n"
            f"📦 **المنتج:** {escape_md(prod_name)}\n"
            f"🔢 **الروابط المتاحة حالياً:** `{len(links)}` رابط\n"
            f"─────────────────────\n"
        )
        buttons = []
        for idx, l in enumerate(links[:15], 1):
            lid = l["id"]
            url_str = str(l.get("link_url", ""))
            short_url = url_str if len(url_str) <= 38 else url_str[:35] + "..."
            text += f"`#{idx}` — `{escape_md(url_str[:65])}`\n"
            buttons.append([
                keyboards._btn(f"🗑️ حذف #{idx}: {short_url}", callback_data=f"adm_del_one_link:{lid}:{pid}", style="danger")
            ])

        buttons.append([
            keyboards._btn(f"⚠️ حذف جميع الروابط ({len(links)}) لهذا المنتج", callback_data=f"adm_clear_all_links:{pid}", style="danger")
        ])
        buttons.append([keyboards._btn("🔙 رجوع لقائمة المنتجات", callback_data="adm_del_links_menu:0")])
        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return

    # Delete a single stock link
    if data.startswith("adm_del_one_link:"):
        parts = data.split(":", 2)
        link_id = int(parts[1])
        pid = parts[2]
        await database.delete_stock_link(link_id, pid)
        await safe_answer(query, "🗑️ تم حذف الرابط من المخزون السحابي والمحلي!", show_alert=False)
        # Refresh view
        query.data = f"adm_del_stock_prod:{pid}"
        return await admin_callback_dispatcher(update, context)

    # Clear all unused stock links for a product
    if data.startswith("adm_clear_all_links:"):
        pid = data.split(":", 1)[1]
        deleted_cnt = await database.clear_product_stock(pid)
        await safe_answer(query, f"🗑️ تم مسح جميع الروابط ({deleted_cnt}) بنجاح!", show_alert=True)
        query.data = f"adm_del_stock_prod:{pid}"
        return await admin_callback_dispatcher(update, context)

    # ==================== إدارة المحافظ وطلبات شحن الرصيد (Admin Wallets & Top-Ups) ====================

    if data == "adm_wallets_menu":
        await safe_answer(query)
        pending_topups = await database.get_pending_topups(limit=50)
        all_wallets = await database.get_all_wallets(limit=100)
        total_dzd = sum(float(w.get("balance_dzd", 0)) for w in all_wallets)
        total_usd = sum(float(w.get("balance_usd", 0)) for w in all_wallets)

        text = (
            "👛 **إدارة محافظ العملاء وطلبات الشحن (Top Up Wallet):**\n"
            "─────────────────────\n"
            f"⏳ **طلبات الشحن المعلقة بانتظار موافقتك:** `{len(pending_topups)}` طلب\n"
            f"👥 **عدد المحافظ المسجلة:** `{len(all_wallets)}` محفظة\n"
            f"🇩🇿 **إجمالي أرصدة العملاء بالدينار:** `{total_dzd}` {CURRENCY}\n"
            f"💵 **إجمالي أرصدة العملاء بالدولار:** `${total_usd:.2f}`\n"
            "─────────────────────\n"
            "اختر الإجراء المطلوب بالأسفل:"
        )
        kb = InlineKeyboardMarkup([
            [keyboards._btn(f"⏳ طلبات شحن المحفظة المعلقة ({len(pending_topups)})", callback_data="adm_pending_topups", style="primary")],
            [keyboards._btn("👥 عرض أرصدة محافظ العملاء", callback_data="adm_list_wallets")],
            [keyboards._btn("➕ شحن / تعديل رصيد عميل يدوياً", callback_data="adm_manual_wallet_credit", style="success")],
            [keyboards._btn("🔙 رجوع للوحة التحكم", callback_data="adm_dashboard")],
        ])
        await safe_edit_text(query.message, text, reply_markup=kb, parse_mode="Markdown")
        return

    # View Pending Wallet Top-Ups
    if data == "adm_pending_topups":
        await safe_answer(query, "⏳ جاري تحميل طلبات شحن المحفظة...")
        pending = await database.get_pending_topups(limit=20)
        if not pending:
            text = "⏳ **طلبات شحن المحفظة المعلقة:**\n\n🎉 لا توجد أي طلبات شحن معلقة حالياً!"
            kb = InlineKeyboardMarkup([
                [keyboards._btn("👛 رجوع لإدارة المحافظ", callback_data="adm_wallets_menu")],
                [keyboards._btn("🔙 لوحة التحكم", callback_data="adm_dashboard")],
            ])
            await safe_edit_text(query.message, text, reply_markup=kb, parse_mode="Markdown")
            return

        text = f"⏳ **طلبات شحن المحفظة بانتظار التأكيد ({len(pending)}):**\n─────────────────────\n"
        buttons = []
        for t in pending:
            tid = t["id"]
            tcode = t.get("topup_code") or f"TOP-{tid:04d}"
            uname = escape_md(t.get("user_name") or "عميل")
            uuser = escape_md(t.get("user_username") or "")
            amt = t.get("amount", 0)
            curr = escape_md(t.get("currency", CURRENCY))
            pm = escape_md(t.get("payment_method", "بريدي موب"))
            tnum = escape_md(t.get("transfer_number", ""))
            text += (
                f"🔹 **`{tcode}`** | 👤 {uname} ({uuser}) | ID: `{t.get('user_id')}`\n"
                f"• المبلغ: **`{amt}` {curr}** عبر {pm}\n"
                f"• التأكيد/المرجع: `{tnum}`\n"
                f"───────────────\n"
            )
            buttons.append([
                keyboards._btn(f"✅ موافقة {tcode} ({amt} {t.get('currency')})", callback_data=f"adm_topup_appr:{tid}", style="success"),
                keyboards._btn(f"⚙️ تفاصيل {tcode}", callback_data=f"adm_topup_view:{tid}", style="primary"),
            ])
        buttons.append([keyboards._btn("🔙 رجوع لإدارة المحافظ", callback_data="adm_wallets_menu")])
        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return

    # View single Top-Up details
    if data.startswith("adm_topup_view:"):
        await safe_answer(query)
        tid = int(data.split(":", 1)[1])
        topup = await database.get_topup_by_id(tid)
        if not topup:
            await safe_edit_text(query.message, "⚠️ طلب الشحن غير موجود.")
            return
        wallet = await database.get_user_wallet(topup["user_id"])
        text = (
            f"👛 **تفاصيل طلب شحن المحفظة `{topup.get('topup_code')}`:**\n"
            f"─────────────────────\n"
            f"👤 **العميل:** {escape_md(topup.get('user_name'))} ({escape_md(topup.get('user_username'))})\n"
            f"🆔 **ID:** `{topup.get('user_id')}`\n"
            f"💰 **المبلغ المطلوب:** `{topup.get('amount')}` {escape_md(topup.get('currency'))}\n"
            f"💳 **وسيلة الدفع:** {escape_md(topup.get('payment_method'))}\n"
            f"🧾 **التأكيد / المرجع:** `{escape_md(topup.get('transfer_number'))}`\n"
            f"📊 **الحالة:** `{topup.get('status')}`\n"
            f"👛 **رصيد العميل الحالي:** `{wallet.get('balance_dzd', 0)}` {CURRENCY} | `${wallet.get('balance_usd', 0):.2f}`"
        )
        await safe_edit_text(
            query.message,
            text,
            reply_markup=keyboards.get_admin_topup_keyboard(tid, topup["user_id"]),
            parse_mode="Markdown",
        )
        return

    # Approve Wallet Top-Up directly
    if data.startswith("adm_topup_appr:"):
        tid = int(data.split(":", 1)[1])
        ok, topup, new_wallet = await database.approve_wallet_topup(tid)
        if not ok or not topup:
            await safe_answer(query, "⚠️ تمت معالجة هذا الطلب مسبقاً أو أنه غير موجود.", show_alert=True)
            return

        await safe_answer(query, "✅ تمت الموافقة وإضافة الرصيد لمحفظة العميل!", show_alert=True)
        tcode = topup.get("topup_code") or f"TOP-{tid:04d}"
        amt = topup.get("amount", 0)
        curr = topup.get("currency", CURRENCY)
        cust_id = topup["user_id"]

        # Notify Customer
        cust_msg = (
            f"🎉 **تمت الموافقة على شحن محفظتك بنجاح!**\n"
            f"─────────────────────\n"
            f"🔹 **رقم العملية:** `{tcode}`\n"
            f"➕ **المبلغ المضاف:** `{amt}` {escape_md(curr)}\n\n"
            f"👛 **رصيد محفظتك الحالي الآن:**\n"
            f"• 🇩🇿 بالدينار: **`{new_wallet['balance_dzd']}` {CURRENCY}**\n"
            f"• 💵 بالدولار: **`${new_wallet['balance_usd']:.2f}`**\n"
            f"─────────────────────\n"
            "يمكنك الآن شراء أي اشتراك فوراً باستخدام رصيد محفظتك! 🚀"
        )
        await safe_send_message(context.bot, cust_id, cust_msg, parse_mode="Markdown")

        admin_done = (
            f"✅ **تمت الموافقة على طلب الشحن `{tcode}` وإضافة الرصيد!**\n"
            f"👤 العميل: {escape_md(topup.get('user_name'))} (`{cust_id}`)\n"
            f"➕ المبلغ المضاف: `{amt}` {escape_md(curr)}\n"
            f"👛 رصيد العميل الجديد: `{new_wallet['balance_dzd']}` {CURRENCY} | `${new_wallet['balance_usd']:.2f}`"
        )
        if getattr(query.message, "photo", None):
            try:
                await query.message.edit_caption(caption=admin_done, parse_mode="Markdown", reply_markup=None)
            except Exception:
                await safe_reply_text(query.message, admin_done, parse_mode="Markdown")
        else:
            await safe_edit_text(query.message, admin_done, reply_markup=None, parse_mode="Markdown")
        return

    # Approve Wallet Top-Up with edited amount
    if data.startswith("adm_topup_edit:"):
        await safe_answer(query)
        tid = int(data.split(":", 1)[1])
        topup = await database.get_topup_by_id(tid)
        if not topup or topup.get("status") != "PENDING":
            await safe_reply_text(query.message, "⚠️ هذا الطلب تمت معالجته مسبقاً أو غير موجود.")
            return
        context.bot_data[f"admin_edit_topup_{user_id}"] = tid
        await safe_reply_text(
            query.message,
            f"✏️ **تعديل مبلغ الشحن والموافقة على `{topup.get('topup_code')}`:**\n"
            f"المبلغ الذي أدخله العميل: `{topup.get('amount')}` {escape_md(topup.get('currency'))}\n\n"
            "✍️ **أرسل الآن المبلغ الفعلي الذي وصلت قيمته لإضافته لمحفظة العميل (أرقام فقط):**\n"
            "لإلغاء العملية أرسل: `/cancel_action`",
            parse_mode="Markdown",
        )
        return

    # Reject Wallet Top-Up
    if data.startswith("adm_topup_rej:"):
        await safe_answer(query)
        tid = int(data.split(":", 1)[1])
        topup = await database.get_topup_by_id(tid)
        if not topup or topup.get("status") != "PENDING":
            await safe_reply_text(query.message, "⚠️ هذا الطلب تمت معالجته مسبقاً أو غير موجود.")
            return
        context.bot_data[f"admin_reject_topup_{user_id}"] = tid
        await safe_reply_text(
            query.message,
            f"❌ **رفض طلب شحن المحفظة `{topup.get('topup_code')}`:**\n\n"
            "✍️ أرسل سبب الرفض ليتم إرساله للعميل (أو أرسل `/skip_reason` للرفض المباشر):\n"
            "لإلغاء العملية أرسل: `/cancel_action`",
            parse_mode="Markdown",
        )
        return

    # View Top-Up Receipt Photo
    if data.startswith("adm_topup_receipt:"):
        tid = int(data.split(":", 1)[1])
        topup = await database.get_topup_by_id(tid)
        if not topup or not topup.get("receipt_file_id"):
            await safe_answer(query, "⚠️ لا توجد صورة وصل مرفقة بهذا الطلب (العميل أرسل تأكيداً نصياً).", show_alert=True)
            return
        await safe_answer(query, "🖼️ جاري عرض صورة الوصل...")
        await context.bot.send_photo(
            chat_id=user_id,
            photo=topup["receipt_file_id"],
            caption=f"🖼️ وصل شحن المحفظة `{topup.get('topup_code')}` — العميل `{topup.get('user_id')}`",
            reply_markup=keyboards.get_admin_topup_keyboard(tid, topup["user_id"]),
        )
        return

    # List customer wallets
    if data == "adm_list_wallets":
        await safe_answer(query)
        wallets = await database.get_all_wallets(limit=30)
        if not wallets:
            text = "👥 **أرصدة محافظ العملاء:**\n\nلا توجد محافظ مسجلة حتى الآن."
        else:
            text = f"👥 **أرصدة محافظ العملاء (أعلى `{len(wallets)}` محفظة):**\n─────────────────────\n"
            for w in wallets:
                uname = escape_md(w.get("user_name") or "عميل")
                uuser = escape_md(w.get("user_username") or "")
                text += (
                    f"• 👤 **{uname}** ({uuser}) | ID: `{w['user_id']}`\n"
                    f"  🇩🇿 `{w.get('balance_dzd', 0)}` {CURRENCY} | 💵 `${w.get('balance_usd', 0):.2f}`\n"
                )
        kb = InlineKeyboardMarkup([
            [keyboards._btn("➕ شحن / تعديل رصيد عميل يدوياً", callback_data="adm_manual_wallet_credit", style="success")],
            [keyboards._btn("🔙 رجوع لإدارة المحافظ", callback_data="adm_wallets_menu")],
        ])
        await safe_edit_text(query.message, text, reply_markup=kb, parse_mode="Markdown")
        return

    # Manual wallet credit wizard
    if data == "adm_manual_wallet_credit":
        await safe_answer(query)
        context.bot_data[f"admin_manual_wallet_step_{user_id}"] = {"step": 1}
        text = (
            "➕ **شحن / تعديل رصيد محفظة عميل يدوياً (الخطوة 1 من 2):**\n\n"
            "✍️ **أرسل الآن معرف العميل الرقمي (User ID):**\n"
            "مثال: `5075624178`\n\n"
            "لإلغاء العملية أرسل: `/cancel_action`"
        )
        await safe_edit_text(query.message, text, parse_mode="Markdown")
        return

    # Selected product for stock
    if data.startswith("adm_stock_for:"):
        await safe_answer(query)
        pid = data.split(":", 1)[1]
        prod = await database.get_product_by_id(pid)
        if not prod:
            await safe_edit_text(query.message, "⚠️ الباقة غير معروفة.")
            return

        context.bot_data[f"admin_add_stock_{user_id}"] = pid
        text = (
            f"📥 **إضافة روابط لمخزن:** {escape_md(prod['name'])}\n\n"
            "✍️ أرسل الروابط الآن في هذه المحادثة.\n"
            "• ضع **رابط واحد في كل سطر**.\n"
            "• يمكنك إرسال أي عدد من الروابط دفعة واحدة.\n\n"
            "لإلغاء العملية في أي وقت، أرسل: `/cancel_action`"
        )
        await safe_edit_text(query.message, text, parse_mode="Markdown")
        return

    # Cancel pending links
    if data == "adm_cancel_pending_links":
        await safe_answer(query)
        context.bot_data.pop(f"admin_pending_links_{user_id}", None)
        await safe_edit_text(query.message, "❌ تم إلغاء العملية ولم يتم حفظ الروابط.")
        return

    # Assign pending links to selected product
    if data.startswith("adm_assign_stock:"):
        await safe_answer(query, "⏳ جاري حفظ الروابط...")
        pid = data.split(":", 1)[1]
        pending_links = context.bot_data.pop(f"admin_pending_links_{user_id}", [])
        if not pending_links:
            await safe_edit_text(query.message, "⚠️ لم يتم العثور على روابط معلقة أو انتهت صلاحيتها.")
            return

        added_count = await database.add_links_to_stock(pid, pending_links)
        prod = await database.get_product_by_id(pid)
        prod_name = prod["name"] if prod else pid

        counts = await database.get_stock_counts()
        curr_stock = counts.get(pid, 0)

        await safe_edit_text(
            query.message,
            f"🎉 **تمت إضافة الروابط بنجاح!**\n\n"
            f"📦 المنتج: **{escape_md(prod_name)}**\n"
            f"➕ عدد الروابط المضافة: `{added_count}` رابط\n"
            f"📊 إجمالي المخزون الحالي للمنتج: `{curr_stock}` رابط متوفر\n"
            f"☁️ تم الحفظ والمزامنة السحابية بشكل دائم 🔒",
            parse_mode="Markdown",
        )
        return

    # Pending Orders
    if data == "adm_pending":
        await safe_answer(query, "⏳ جاري تحميل الطلبات المعلقة...")
        pending = await database.get_pending_orders(limit=20)
        if not pending:
            text = "⏳ **الطلبات المعلقة:**\n\n🎉 لا توجد أي طلبات معلقة حالياً، جميع الطلبات تمت معالجتها!"
            kb = [
                [InlineKeyboardButton("📋 عرض سجل جميع الطلبات", callback_data="adm_all_orders")],
                [InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="adm_dashboard")],
            ]
            await safe_edit_text(
                query.message,
                text,
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="Markdown",
            )
            return

        text = f"⏳ **الطلبات المعلقة قيد الانتظار ({len(pending)}):**\n─────────────────────\n"
        buttons = []
        for p in pending:
            ocode = p.get("order_code") or f"ORD-{p['id']:04d}"
            uname = escape_md(p.get("user_name") or "عميل")
            uuser = escape_md(p.get("user_username") or "بدون معرف")
            pname = escape_md(p.get("product_name") or p.get("product_id"))
            tnum = escape_md(p.get("transfer_number") or "غير محدد")
            curr = escape_md(p.get("currency") or CURRENCY)
            dt_str = format_dt(p.get("created_at"))
            text += (
                f"🔹 **طلب:** `{ocode}`\n"
                f"• العميل: {uname} ({uuser}) | ID: `{p.get('user_id')}`\n"
                f"• المنتج: {pname} (الكمية: `{p.get('quantity', 1)}`)\n"
                f"• المبلغ: `{p.get('total_price')}` {curr} ({escape_md(p.get('payment_method', 'بريدي موب'))})\n"
                f"• رقم التحويل: `{tnum}`\n"
                f"• التاريخ: `{dt_str}`\n"
                f"───────────────\n"
            )
            short_user = (p.get("user_name") or "عميل")[:16]
            buttons.append([
                InlineKeyboardButton(
                    f"⚙️ إدارة {ocode} — {short_user} ({p.get('total_price')} {p.get('currency', CURRENCY)})",
                    callback_data=f"adm_manage_order:{p['id']}",
                )
            ])
        buttons.append([
            InlineKeyboardButton("🔄 تحديث القائمة", callback_data="adm_pending"),
            InlineKeyboardButton("📋 سجل جميع الطلبات", callback_data="adm_all_orders"),
        ])
        buttons.append([InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="adm_dashboard")])
        await safe_edit_text(
            query.message,
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )
        return

    # All Recent Orders History
    if data == "adm_all_orders":
        await safe_answer(query, "📋 جاري جلب سجل الطلبات...")
        orders = await database.get_recent_orders(limit=15)
        if not orders:
            text = "📋 **سجل الطلبات:**\n\nلا توجد أي طلبات مسجلة في قاعدة البيانات حتى الآن."
            await safe_edit_text(
                query.message,
                text,
                reply_markup=keyboards.get_admin_menu_keyboard(),
                parse_mode="Markdown",
            )
            return

        text = f"📋 **أحدث `{len(orders)}` طلب في المتجر:**\n─────────────────────\n"
        buttons = []
        for o in orders:
            ocode = o.get("order_code") or f"ORD-{o['id']:04d}"
            st = o.get("status", "PENDING")
            st_badge = "⏳ معلق" if st == "PENDING" else ("✅ مقبول" if st == "APPROVED" else "❌ مرفوض")
            uname = escape_md(o.get("user_name") or "عميل")
            uuser = escape_md(o.get("user_username") or "")
            pname = escape_md(o.get("product_name") or o.get("product_id"))
            curr = escape_md(o.get("currency") or CURRENCY)
            dt_str = format_dt(o.get("created_at"))
            text += (
                f"▪️ `{ocode}` | **{st_badge}**\n"
                f"  👤 {uname} ({uuser}) — {pname} (`{o.get('total_price')}` {curr})\n"
                f"  📅 `{dt_str}`\n"
            )
            short_user = (o.get("user_name") or "عميل")[:15]
            buttons.append([
                InlineKeyboardButton(
                    f"{'⏳' if st == 'PENDING' else ('✅' if st == 'APPROVED' else '❌')} {ocode} — {short_user}",
                    callback_data=f"adm_manage_order:{o['id']}",
                )
            ])
        buttons.append([
            InlineKeyboardButton("⏳ الطلبات المعلقة فقط", callback_data="adm_pending"),
            InlineKeyboardButton("🔙 لوحة التحكم", callback_data="adm_dashboard"),
        ])
        await safe_edit_text(
            query.message,
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )
        return

    # View Receipt Photo for a Specific Order
    if data.startswith("adm_receipt:"):
        order_id = int(data.split(":", 1)[1])
        order = await database.get_order_by_id(order_id)
        if not order:
            await safe_answer(query, "⚠️ الطلب غير موجود.", show_alert=True)
            return

        receipt_fid = order.get("receipt_file_id")
        if not receipt_fid:
            await safe_answer(query, "⚠️ لا توجد صورة إيصال مرفقة بهذا الطلب.", show_alert=True)
            return

        await safe_answer(query, "🖼️ جاري عرض صورة الإيصال...")
        ocode = order.get("order_code") or f"ORD-{order_id:04d}"
        caption = (
            f"🖼️ **إيصال الدفع للطلب `{ocode}`**\n"
            f"─────────────────\n"
            f"👤 **العميل:** {escape_md(order.get('user_name'))} ({escape_md(order.get('user_username'))})\n"
            f"🆔 **ID:** `{order.get('user_id')}`\n"
            f"📦 **المنتج:** {escape_md(order.get('product_name'))} (x{order.get('quantity', 1)})\n"
            f"💰 **المبلغ:** `{order.get('total_price')}` {escape_md(order.get('currency', CURRENCY))}\n"
            f"💳 **طريقة الدفع:** {escape_md(order.get('payment_method', 'بريدي موب'))}\n"
            f"🧾 **رقم التحويل:** `{escape_md(order.get('transfer_number'))}`\n"
            f"📊 **الحالة:** `{order.get('status')}`"
        )
        try:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=receipt_fid,
                caption=caption,
                reply_markup=keyboards.get_admin_order_keyboard(order_id),
                parse_mode="Markdown",
            )
        except Exception:
            clean_cap = caption.replace("**", "").replace("`", "").replace("\\_", "_")
            await context.bot.send_photo(
                chat_id=user_id,
                photo=receipt_fid,
                caption=clean_cap,
                reply_markup=keyboards.get_admin_order_keyboard(order_id),
            )
        return

    # Edit Payment Info
    if data == "adm_edit_payment":
        await safe_answer(query)
        current_info = await database.get_payment_info()
        context.bot_data[f"admin_edit_pay_{user_id}"] = True
        text = (
            "💳 **تعديل بيانات الدفع:**\n\n"
            "البيانات الحالية:\n"
            f"{current_info}\n\n"
            "✍️ **أرسل الآن النص الجديد لبيانات الدفع وطرق التحويل:**\n"
            "(يمكنك إلغاء العملية بكتابة `/cancel_action`)"
        )
        await safe_edit_text(query.message, text, parse_mode="Markdown")
        return

    # Proof Channel Dashboard
    if data == "adm_proof_channel":
        await safe_answer(query)
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
        await safe_edit_text(
            query.message,
            text,
            reply_markup=keyboards.get_admin_proof_channel_keyboard(has_channel=has_chan),
            parse_mode="Markdown",
        )
        return

    # Set Proof Channel Prompt
    if data == "adm_set_proof_channel":
        await safe_answer(query)
        context.bot_data[f"admin_set_proof_chan_{user_id}"] = True
        text = (
            "✏️ **ضبط قناة الإثباتات:**\n\n"
            "✍️ أرسل معرف القناة الآن:\n"
            "• إذا كانت القناة عامة (Public)، أرسل المعرف مثل: `@my_proofs_channel`\n"
            "• إذا كانت القناة خاصة (Private)، أرسل المعرف الرقمي مثل: `-1001234567890`\n\n"
            "⚠️ تأكد من إضافة البوت كمشرف (Admin) داخل القناة أولاً!\n"
            "للإلغاء أرسل: `/cancel_action`"
        )
        await safe_edit_text(query.message, text, parse_mode="Markdown")
        return

    # Test Proof Channel
    if data == "adm_test_proof_channel":
        await safe_answer(query, "🧪 جاري إرسال منشور تجريبي...")
        curr_chan = await database.get_proof_channel()
        if not curr_chan:
            await safe_reply_text(query.message, "⚠️ لا توجد قناة مضبوطة حالياً. يرجى ضبط القناة أولاً بالضغط على '✏️ ضبط / تغيير معرف القناة'.")
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
            await safe_reply_text(
                query.message,
                f"✅ **تم إرسال المنشور التجريبي بنجاح إلى القناة `{curr_chan}`!**\nتفضل بزيارة قناتك وستجد الرسالة منشورة الآن 🎉",
                parse_mode="Markdown",
            )
        except Exception as e:
            err_msg = escape_md(str(e))
            logger.error(f"Failed to send test proof to {curr_chan}: {e}")
            advice = ""
            if "Chat not found" in str(e):
                advice = "💡 **السبب المحتمل:** معرف القناة غير صحيح، أو القناة خاصة. إذا كانت القناة خاصة، يجب استخدام الـ ID الرقمي (مثال: `-100...`)."
            elif "bot is not a member" in str(e) or "administrator" in str(e).lower():
                advice = "💡 **السبب المحتمل:** البوت ليس مضافاً داخل القناة كـ **مشرف (Administrator)**. توجه للقناة وأضف البوت مشرفاً مع صلاحية نشر الرسائل."
            elif "rights to send a message" in str(e):
                advice = "💡 **السبب المحتمل:** البوت موجود بالقناة ولكنه لا يملك صلاحية نشر الرسائل (Post Messages)."

            await safe_reply_text(
                query.message,
                f"⚠️ **تعذر إرسال المنشور التجريبي إلى القناة `{curr_chan}`!**\n\n"
                f"❌ **رسالة الخطأ من تليجرام:**\n`{err_msg}`\n\n"
                f"{advice}",
                parse_mode="Markdown",
            )
        return

    # Remove Proof Channel
    if data == "adm_remove_proof_channel":
        await database.update_proof_channel("")
        await safe_answer(query, "🗑️ تم إلغاء ربط القناة.", show_alert=False)
        text = (
            "📢 **إدارة قناة إثباتات المبيعات (Proofs Channel):**\n"
            "─────────────────────\n"
            "• **القناة الحالية:** ❌ _تم إلغاء الربط_\n\n"
            "تم إيقاف النشر التلقائي للطلبات في القناة."
        )
        await safe_edit_text(
            query.message,
            text,
            reply_markup=keyboards.get_admin_proof_channel_keyboard(has_channel=False),
            parse_mode="Markdown",
        )
        return

    # Check Supplier Balance & Stock (DigitalCore, NevaKeyStore, LahaStore, and AccZone in parallel)
    if data == "adm_supplier":
        await safe_answer(query, "🌐 جاري فحص أرصدة ومخزون الموردين...")
        dc_bal, dc_stock, neva_bal, neva_stock, laha_bal, laha_stock, acc_bal, acc_stock = await asyncio.gather(
            supplier_api.check_digitalcore_balance(),
            supplier_api.get_digitalcore_stock(),
            supplier_api.check_neva_balance(),
            supplier_api.get_neva_all_products(),
            supplier_api.check_supplier_balance(),
            supplier_api.get_supplier_gemini_stock(),
            supplier_api.check_acczone_balance(),
            supplier_api.get_acczone_gemini_stock(),
        )

        text = "🌐 **بيانات ورصيد مزودي الروابط (APIs):**\n─────────────────────\n\n"

        # DigitalCore Section
        text += "🥇 **1. المورد الأول (DigitalCore API):**\n"
        if dc_bal.get("ok"):
            text += (
                f"• رصيد المحفظة: `{dc_bal.get('balance_text')}`\n"
                f"• إجمالي الطلبات المنفذة: `{dc_bal.get('total_orders')}` طلب\n"
            )
        else:
            text += f"• حالة الحساب: ⚠️ {escape_md(dc_bal.get('error'))}\n"

        if dc_stock.get("ok"):
            prods_dc = dc_stock.get("products", [])
            text += f"• المنتجات المتاحة: `{len(prods_dc)}` منتج\n"

        text += "\n─────────────────────\n"

        # NevaKeyStore Section
        text += "🌟 **2. المورد الثاني (NevaKeyStore API):**\n"
        if neva_bal.get("ok"):
            text += (
                f"• الحساب: `{escape_md(neva_bal.get('display_name'))}` (`{neva_bal.get('user_id')}`)\n"
                f"• رصيد المحفظة: `{neva_bal.get('balance_text')}`\n"
                f"• الطلبات المنفذة: `{neva_bal.get('api_orders')}` طلب\n"
            )
        else:
            text += f"• حالة الحساب: ⚠️ {escape_md(neva_bal.get('error'))}\n"

        if neva_stock.get("ok"):
            prods_neva = neva_stock.get("products", [])
            text += f"• إجمالي الباقات المربوطة: `{len(prods_neva)}` منتج نشط\n"

        text += "\n─────────────────────\n"

        # LahaStore Section
        text += "🥈 **3. المورد الثالث (LahaStore API):**\n"
        if laha_bal.get("ok"):
            text += (
                f"• معرف المتجر: `{laha_bal.get('shop_id')}`\n"
                f"• رصيد المحفظة: `{laha_bal.get('balance_usd_text')}` ({laha_bal.get('balance_vnd_text')})\n"
            )
        else:
            text += f"• حالة الحساب: ⚠️ {escape_md(laha_bal.get('error'))}\n"

        text += "\n─────────────────────\n"

        # AccZone Section
        text += "🥉 **4. المورد الرابع (AccZone API):**\n"
        if acc_bal.get("ok"):
            text += (
                f"• المستخدم: `{escape_md(acc_bal.get('username'))}`\n"
                f"• رصيد المحفظة: `{acc_bal.get('balance_text')}`\n"
            )
        else:
            text += f"• حالة الحساب: ⚠️ {escape_md(acc_bal.get('error'))}\n"

        text += (
            "\n─────────────────────\n"
            "🔄 **نظام السحب والتسليم الذكي:**\n"
            "1. يبحث في المخزن السحابي المباشر أولاً.\n"
            "2. إذا فرغ المخزن، يسحب تلقائياً من **DigitalCore** أو **NevaKeyStore**.\n"
            "3. كبديل احتياطي، يسحب تلقائياً من **AccZone** أو **LahaStore**.\n"
            "4. إذا تعذرت جميع السيرفرات، يطلب منك إدخال الرابط يدوياً.\n"
        )

        await safe_edit_text(
            query.message,
            text,
            reply_markup=keyboards.get_admin_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Sync & Scan Supplier Products (APIs)
    if data == "adm_sync_apis":
        await safe_answer(query, "🔄 جاري فحص ومزامنة منتجات الموردين...")
        loading_text = (
            "🔄 **جاري فحص الموردين ومزامنة المنتجات...**\n\n"
            "• فحص كتالوج DigitalCore API...\n"
            "• فحص كتالوج NevaKeyStore API...\n"
            "• فحص كتالوج LahaStore API...\n"
            "• فحص خدمات AccZone API...\n"
            "يرجى الانتظار بضع ثوانٍ ⏳"
        )
        await safe_edit_text(query.message, loading_text, parse_mode="Markdown")

        new_items = await supplier_api.sync_new_supplier_products(bot=context.bot)

        # Live counts in parallel
        dc_stock, neva_stock, laha_stock, acc_stock = await asyncio.gather(
            supplier_api.get_digitalcore_stock(),
            supplier_api.get_neva_all_products(),
            supplier_api.get_lahastore_all_products(),
            supplier_api.get_acczone_all_services(),
        )
        dc_count = len(dc_stock.get("products", [])) if dc_stock.get("ok") else 0
        neva_count = len(neva_stock.get("products", [])) if neva_stock.get("ok") else 0
        laha_count = len(laha_stock.get("products", [])) if laha_stock.get("ok") else 0
        acc_count = len(acc_stock.get("services", [])) if acc_stock.get("ok") else 0

        res_text = (
            "🎉 **اكتمل فحص ومزامنة منتجات الموردين بنجاح!**\n"
            "─────────────────────\n"
            f"🥇 **DigitalCore:** `{dc_count}` منتج نشط\n"
            f"🌟 **NevaKeyStore:** `{neva_count}` منتج نشط\n"
            f"🥈 **LahaStore:** `{laha_count}` منتج نشط\n"
            f"🥉 **AccZone:** `{acc_count}` خدمات نشطة\n"
            "─────────────────────\n"
        )
        if new_items:
            res_text += f"🆕 **تم اكتشاف وإضافة `{len(new_items)}` منتج جديد للمتجر تلقائياً:**\n\n"
            for itm in new_items[:15]:
                res_text += (
                    f"• **{escape_md(itm['name'])}** ({escape_md(itm['supplier'])})\n"
                    f"  سعر الجملة: `${itm['wholesale']}` | سعر البيع: `{itm['price_dzd']} دج` (${itm['price_usd']})\n"
                    f"  المخزون: `{itm['stock']}` قطعة | القسم: `{itm['category']}`\n\n"
                )
            if len(new_items) > 15:
                res_text += f"➕ _و `{len(new_items) - 15}` منتج آخر تمت إضافتها لقاعدة البيانات..._\n\n"
            res_text += "💡 يمكنك تعديل الأسعار أو إيقاف أي منتج من 'إدارة المنتجات والأسعار'."
        else:
            res_text += "✅ **جميع المنتجات لدى الموردين مسجلة ومحدثة في قاعدة البيانات مسبقاً!**\nلا توجد منتجات جديدة غير مضافة حالياً."

        await safe_edit_text(
            query.message,
            res_text,
            reply_markup=keyboards.get_admin_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Approve Order Clicked
    if data.startswith("adm_appr:"):
        order_id = int(data.split(":", 1)[1])
        await process_order_approval(update, context, order_id)
        return

    # Reject Order Clicked
    if data.startswith("adm_rej:"):
        await safe_answer(query)
        order_id = int(data.split(":", 1)[1])
        context.bot_data[f"admin_reject_order_{user_id}"] = order_id
        text = (
            f"❌ **رفض الطلب رقم `{order_id}`:**\n\n"
            "✍️ يرجى إرسال سبب الرفض في رسالة ليتم إخطار العميل به.\n"
            "• أو أرسل `/skip_reason` لإرسال الرفض بدون تفاصيل.\n"
            "• لإلغاء الرفض أرسل `/cancel_action`."
        )
        await safe_reply_text(query.message, text, parse_mode="Markdown")
        return

    # Manage specific order from admin panel
    if data.startswith("adm_manage_order:"):
        order_id = int(data.split(":", 1)[1])
        order = await database.get_order_by_id(order_id)
        if not order:
            await safe_answer(query, "⚠️ الطلب غير موجود.", show_alert=True)
            return

        await safe_answer(query)
        st = order.get("status", "PENDING")
        status_text = (
            "⏳ معلق قيد الانتظار" if st == "PENDING"
            else ("✅ مقبول ومكتمل" if st == "APPROVED" else f"❌ مرفوض ({escape_md(order.get('reject_reason', ''))})")
        )
        ocode = order.get("order_code") or f"ORD-{order_id:04d}"
        text = (
            f"📦 **إدارة الطلب رقم `{ocode}`:**\n"
            f"─────────────────────\n"
            f"👤 **العميل:** {escape_md(order.get('user_name'))} ({escape_md(order.get('user_username'))})\n"
            f"🆔 **معرف العميل (ID):** `{order.get('user_id')}`\n"
            f"🛍 **المنتج:** {escape_md(order.get('product_name'))}\n"
            f"🔢 **الكمية:** `{order.get('quantity', 1)}`\n"
            f"💰 **المبلغ:** `{order.get('total_price')}` {escape_md(order.get('currency', CURRENCY))}\n"
            f"💳 **طريقة الدفع:** {escape_md(order.get('payment_method', 'بريدي موب'))}\n"
            f"🧾 **رقم التحويل:** `{escape_md(order.get('transfer_number'))}`\n"
            f"📊 **الحالة:** {status_text}\n"
            f"📅 **التاريخ:** `{format_dt(order.get('created_at'))}`\n"
        )
        if st == "APPROVED" and order.get("delivered_links"):
            text += f"🔗 **الروابط المسلمة:**\n`{escape_md(order.get('delivered_links'))}`\n"
        text += "─────────────────────\nاختر الإجراء المطلوب بالأسفل 👇"

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
                InlineKeyboardButton("🖼️ عرض صورة الإيصال", callback_data=f"adm_receipt:{order_id}"),
                InlineKeyboardButton("❌ رفض الطلب", callback_data=f"adm_rej:{order_id}"),
            ],
            [
                InlineKeyboardButton("⏳ الطلبات المعلقة", callback_data="adm_pending"),
                InlineKeyboardButton("📋 سجل الطلبات", callback_data="adm_all_orders"),
            ],
            [
                InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="adm_dashboard"),
            ],
        ]
        await safe_edit_text(query.message, text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    # Notify Customer: Order In Preparation / Please Wait
    if data.startswith("adm_wait:"):
        order_id = int(data.split(":", 1)[1])
        order = await database.get_order_by_id(order_id)
        if not order:
            await safe_answer(query, "⚠️ الطلب غير موجود.", show_alert=True)
            return

        cust_user_id = order["user_id"]
        order_code = order["order_code"]
        prod_name = escape_md(order["product_name"])

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
            await safe_send_message(
                context.bot,
                chat_id=cust_user_id,
                text=wait_msg,
                parse_mode="Markdown",
            )
            await safe_answer(query, "✅ تم إرسال إشعار 'طلبك قيد التجهيز' للعميل بنجاح!", show_alert=True)
            await safe_reply_text(
                query.message,
                f"⏳ **تم إشعار العميل بنجاح بأن طلبه قيد التجهيز!**\n\n"
                f"👤 العميل: **{escape_md(order['user_name'])}** (`{cust_user_id}`)\n"
                f"🔖 الطلب: `{order_code}`\n\n"
                f"العميل الآن يعلم أن طلبه قيد الشراء والتجهيز. عندما تجهز الرابط/الحساب يمكنك الضغط على **'✍️ تسليم يدوي'** أو **'✅ قبول وتسليم تلقائي'**.",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Failed to send wait notification to {cust_user_id}: {e}")
            await safe_answer(query, f"⚠️ تعذر إرسال الإشعار للعميل: {e}", show_alert=True)
        return

    # Custom Message to Customer for specific order
    if data.startswith("adm_msg:"):
        order_id = int(data.split(":", 1)[1])
        order = await database.get_order_by_id(order_id)
        if not order:
            await safe_answer(query, "⚠️ الطلب غير موجود.", show_alert=True)
            return

        context.bot_data[f"admin_custom_msg_{user_id}"] = order_id
        await safe_answer(query)
        await safe_reply_text(
            query.message,
            f"💬 **مراسلة مخصصة للعميل (طلب `{order['order_code']}`):**\n"
            f"─────────────────────\n"
            f"👤 العميل: **{escape_md(order['user_name'])}** (`{order['user_id']}`)\n"
            f"📦 المنتج: **{escape_md(order['product_name'])}**\n\n"
            f"✍️ **أرسل الآن نص الرسالة التي تريد توجيهها للعميل:**\n"
            f"(مثال: 'السلام عليكم، جاري تجهيز اشتراكك نحتاج 15 دقيقة' أو 'يرجى إرسال إيميلك لتفعيل الحساب').\n\n"
            f"• لإلغاء المراسلة أرسل: `/cancel_action`",
            parse_mode="Markdown",
        )
        return

    # Direct Manual Delivery (bypassing APIs)
    if data.startswith("adm_manual_deliver:"):
        order_id = int(data.split(":", 1)[1])
        order = await database.get_order_by_id(order_id)
        if not order:
            await safe_answer(query, "⚠️ الطلب غير موجود.", show_alert=True)
            return

        if order["status"] != "PENDING":
            await safe_answer(query, f"⚠️ هذا الطلب تمت معالجته مسبقاً ({order['status']}).", show_alert=True)
            return

        context.bot_data[f"admin_manual_order_{user_id}"] = order_id
        await safe_answer(query)
        await safe_reply_text(
            query.message,
            f"✍️ **تسليم يدوي مباشر للطلب `{order['order_code']}`:**\n"
            f"─────────────────────\n"
            f"👤 العميل: **{escape_md(order['user_name'])}** (`{order['user_id']}`)\n"
            f"📦 المنتج: **{escape_md(order['product_name'])}**\n"
            f"🔢 الكمية المطلوبة: `{order['quantity']}`\n\n"
            f"📥 **أرسل الآن رابط أو بيانات الاشتراك في رسالة:**\n"
            f"(إذا كانت الكمية أكثر من 1، ضع كل رابط في سطر منفصل).\n\n"
            f"• لإلغاء العملية أرسل: `/cancel_action`",
            parse_mode="Markdown",
        )
        return

    # Direct Reply to a Customer User ID
    if data.startswith("adm_reply_user:"):
        target_uid = int(data.split(":", 1)[1])
        context.bot_data[f"admin_reply_user_{user_id}"] = target_uid
        await safe_answer(query)
        await safe_reply_text(
            query.message,
            f"💬 **كتابة رد مباشر للعميل (`{target_uid}`):**\n\n"
            f"✍️ أرسل رسالتك الآن في هذه المحادثة وسيتم تسليمها للعميل فوراً.\n"
            f"• لإلغاء المراسلة: `/cancel_action`",
            parse_mode="Markdown",
        )
        return

    await safe_answer(query)


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
        await safe_answer(query, "⚠️ الطلب غير موجود.", show_alert=True)
        return

    if order["status"] != "PENDING":
        await safe_answer(query, f"⚠️ هذا الطلب تمت معالجته مسبقاً ({order['status']}).", show_alert=True)
        return

    await safe_answer(query, "⏳ جاري معالجة الطلب وتسليم الاشتراك...")
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
            f"👤 العميل: {escape_md(order['user_name'])} (`{order['user_id']}`)\n"
            f"📦 المنتج: {escape_md(order['product_name'])}\n"
            f"💳 طريقة الدفع: {escape_md(order.get('payment_method', 'بريدي موب'))}\n"
            f"💰 المبلغ المحصل: {order['total_price']} {escape_md(order.get('currency', CURRENCY))}"
        )
        try:
            if getattr(query.message, "photo", None):
                await query.message.edit_caption(
                    caption=success_caption,
                    parse_mode="Markdown",
                    reply_markup=None,
                )
            else:
                await safe_edit_text(query.message, success_caption, reply_markup=None, parse_mode="Markdown")
        except Exception:
            await safe_reply_text(query.message, success_caption, parse_mode="Markdown")
        return

    # --- 2. المحاولة الثانية: الشراء التلقائي عبر API (DigitalCore -> AccZone -> LahaStore) ---
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
            f"⚡️ تم سحب `{quantity}` رابط وتوليده تلقائياً عبر **API المورد ({escape_md(provider_used)})**.\n"
            f"👤 العميل: {escape_md(order['user_name'])} (`{order['user_id']}`)\n"
            f"📦 المنتج: {escape_md(order['product_name'])}\n"
            f"💳 طريقة الدفع: {escape_md(order.get('payment_method', 'بريدي موب'))}\n"
            f"💰 المبلغ المحصل: {order['total_price']} {escape_md(order.get('currency', CURRENCY))}"
        )
        try:
            if getattr(query.message, "photo", None):
                await query.message.edit_caption(
                    caption=success_caption,
                    parse_mode="Markdown",
                    reply_markup=None,
                )
            else:
                await safe_edit_text(query.message, success_caption, reply_markup=None, parse_mode="Markdown")
        except Exception:
            await safe_reply_text(query.message, success_caption, parse_mode="Markdown")
        return

    # --- 3. المحاولة الثالثة: طلب الرابط يدوياً من الأدمن (في حال عدم توفره بالمخزن وبكلا الموردين) ---
    context.bot_data[f"admin_manual_order_{admin_id}"] = order_id
    alert_text = (
        f"⚠️ **تنبيه: تعذر التسليم التلقائي للطلب `{order['order_code']}`!**\n\n"
        f"• المخزن المحلي: متوفر `{len(available_links)}` فقط (المطلوب: `{quantity}`).\n"
        f"• نتيجة الموردين (APIs): {escape_md(api_msg)}\n\n"
        f"✍️ **يرجى إرسال رابط التفعيل يدوياً الآن في هذه المحادثة:**\n"
        f"(إذا كانت الكمية أكثر من 1، يمكنك وضع كل رابط في سطر منفصل).\n\n"
        "لإلغاء العملية أرسل: `/cancel_action`"
    )
    await safe_reply_text(query.message, alert_text, parse_mode="Markdown")


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
    plan_name = escape_md(order.get("product_name", "Gemini Pro — 18 Months (Links)"))
    quantity = order.get("quantity", 1)
    order_code = escape_md(order.get("order_code", "ORDER"))

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
        await safe_send_message(
            context.bot,
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
        clean_l = l.replace("`", "")
        items_formatted += f"{header}\n`{clean_l}`\n\n"

    # Tailor instructions: use custom product instructions from DB if configured, else default
    prod_record = await database.get_product_by_id(prod_id) if prod_id else None
    custom_inst = (prod_record.get("instructions") or "").strip() if prod_record else ""
    if custom_inst:
        instructions = f"📘 **تعليمات وشروط التفعيل:**\n{escape_md(custom_inst)}\n\n"
    elif "gemini" in prod_id.lower() or "gemini" in product_name.lower():
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
        f"📦 **المنتج:** {escape_md(product_name)}\n"
        f"🔢 **الكمية:** {order['quantity']}\n"
        f"─────────────────────\n\n"
        f"{items_formatted}"
        f"{instructions}"
        "شكراً لثقتك بنا ونتمنى لك تجربة ممتعة! 🌟"
    )

    try:
        await safe_send_message(
            context.bot,
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
        for key_prefix in (
            "admin_manual_order_",
            "admin_reject_order_",
            "admin_add_stock_",
            "admin_edit_pay_",
            "admin_set_price_",
            "admin_set_price_usd_",
            "admin_set_inst_",
            "admin_add_prod_step_",
            "admin_set_proof_chan_",
            "admin_custom_msg_",
            "admin_reply_user_",
            "admin_edit_topup_",
            "admin_reject_topup_",
            "admin_manual_wallet_step_",
        ):
            context.bot_data.pop(f"{key_prefix}{user_id}", None)
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
            f"{escape_md(text)}\n\n"
            f"─────────────────\n"
            f"💬 يمكنك الرد مباشرة على هذه الرسالة إذا طُلب منك أي معلومات أو استفسار."
        )
        try:
            await safe_send_message(
                context.bot,
                chat_id=cust_uid,
                text=cust_msg,
                parse_mode="Markdown",
            )
            context.bot_data.pop(f"admin_custom_msg_{user_id}", None)
            await safe_reply_text(
                update.message,
                f"✅ **تم إرسال رسالتك بنجاح للعميل {escape_md(order['user_name'])}!**\n\n"
                f"📌 **نص الرسالة المرسلة:**\n{escape_md(text)}",
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
            f"{escape_md(text)}\n\n"
            f"─────────────────\n"
            f"💬 يمكنك الرد مباشرة على هذه الرسالة."
        )
        try:
            await safe_send_message(
                context.bot,
                chat_id=reply_target_uid,
                text=cust_msg,
                parse_mode="Markdown",
            )
            context.bot_data.pop(f"admin_reply_user_{user_id}", None)
            await safe_reply_text(
                update.message,
                f"✅ **تم إرسال الرد إلى العميل (`{reply_target_uid}`) بنجاح!**\n\n"
                f"📌 **نص الرسالة:**\n{escape_md(text)}",
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

        m_order = re.search(r"((?:ORD-|ORDER)[0-9A-Z]+)", search_text)
        if m_order:
            target_order_code = m_order.group(1)

        if target_uid and target_uid not in ADMIN_IDS:
            prefix = f" بخصوص طلبك `{target_order_code}`" if target_order_code else ""
            cust_msg = (
                f"📩 **رسالة من إدارة المتجر{prefix}:**\n\n"
                f"{escape_md(text)}\n\n"
                f"─────────────────\n"
                f"💬 يمكنك الرد مباشرة على هذه الرسالة."
            )
            try:
                await safe_send_message(
                    context.bot,
                    chat_id=target_uid,
                    text=cust_msg,
                    parse_mode="Markdown",
                )
                await safe_reply_text(
                    update.message,
                    f"✅ **تم تسليم ردك مباشرة إلى العميل (`{target_uid}`)!**",
                    parse_mode="Markdown",
                )
                return
            except Exception as e:
                logger.warning(f"Failed to send direct reply to {target_uid}: {e}")

    # 1. Awaiting new DZD price for product
    edit_price_pid = context.bot_data.get(f"admin_set_price_{user_id}")
    if edit_price_pid:
        try:
            new_price = float(text.replace(",", ".").replace("دج", "").strip())
            if new_price <= 0:
                await update.message.reply_text("⚠️ يرجى إدخال سعر موجب.")
                return
            await database.update_product_price(edit_price_pid, new_price)
            prod = await database.get_product_by_id(edit_price_pid)
            context.bot_data.pop(f"admin_set_price_{user_id}", None)
            await safe_reply_text(
                update.message,
                f"✅ **تم تحديث السعر بالدينار بنجاح!**\n"
                f"📦 المنتج: **{escape_md(prod['name'] if prod else edit_price_pid)}**\n"
                f"🇩🇿 السعر الجديد: `{new_price}` {CURRENCY}\n"
                f"💵 السعر بالدولار: `${prod.get('price_usd', 2.5) if prod else 2.5}`",
                parse_mode="Markdown",
            )
            return
        except ValueError:
            await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح للسعر بالدينار (مثال: 1200).")
            return

    # 1.1 Awaiting new USD price ($) for product
    edit_price_usd_pid = context.bot_data.get(f"admin_set_price_usd_{user_id}")
    if edit_price_usd_pid:
        try:
            new_price_usd = round(float(text.replace(",", ".").replace("$", "").strip()), 2)
            if new_price_usd <= 0:
                await update.message.reply_text("⚠️ يرجى إدخال سعر موجب بالدولار.")
                return
            await database.update_product_price_usd(edit_price_usd_pid, new_price_usd)
            prod = await database.get_product_by_id(edit_price_usd_pid)
            context.bot_data.pop(f"admin_set_price_usd_{user_id}", None)
            await safe_reply_text(
                update.message,
                f"✅ **تم تحديث السعر بالدولار بنجاح!**\n"
                f"📦 المنتج: **{escape_md(prod['name'] if prod else edit_price_usd_pid)}**\n"
                f"💵 السعر الجديد بالدولار: `${new_price_usd}`\n"
                f"🇩🇿 السعر بالدينار: `{prod.get('price', 1000) if prod else 1000}` {CURRENCY}",
                parse_mode="Markdown",
            )
            return
        except ValueError:
            await update.message.reply_text("⚠️ يرجى إدخال رقم صحيح للسعر بالدولار (مثال: 2.5 أو 15).")
            return

    # 1.2 Awaiting new product instructions
    edit_inst_pid = context.bot_data.get(f"admin_set_inst_{user_id}")
    if edit_inst_pid:
        await database.update_product_instructions(edit_inst_pid, text)
        prod = await database.get_product_by_id(edit_inst_pid)
        context.bot_data.pop(f"admin_set_inst_{user_id}", None)
        await safe_reply_text(
            update.message,
            f"✅ **تم تحديث تعليمات وشروط المنتج بنجاح!**\n"
            f"─────────────────────\n"
            f"📦 **المنتج:** {escape_md(prod['name'] if prod else edit_inst_pid)}\n"
            f"🔵 📖 **التعليمات الجديدة:**\n{escape_md(text)}\n"
            f"─────────────────────\n"
            "ستظهر هذه التعليمات للزبون عند الضغط على زر `📖 تعليمات وشروط المنتج` الأزرق وعند تسليم الطلب!",
            parse_mode="Markdown",
        )
        return

    # 1.3 Awaiting edited amount for Wallet Top-Up approval
    edit_topup_id = context.bot_data.get(f"admin_edit_topup_{user_id}")
    if edit_topup_id:
        try:
            custom_amt = float(text.replace(",", ".").replace("$", "").replace("دج", "").strip())
            if custom_amt <= 0:
                raise ValueError()
        except ValueError:
            await update.message.reply_text("⚠️ يرجى إدخال مبلغ رقمي صحيح أكبر من الصفر.")
            return

        ok, topup, new_wallet = await database.approve_wallet_topup(edit_topup_id, custom_amount=custom_amt)
        context.bot_data.pop(f"admin_edit_topup_{user_id}", None)
        if not ok or not topup:
            await update.message.reply_text("⚠️ الطلب غير موجود أو تمت معالجته مسبقاً.")
            return

        tcode = topup.get("topup_code") or f"TOP-{edit_topup_id:04d}"
        curr = topup.get("currency", CURRENCY)
        cust_id = topup["user_id"]

        cust_msg = (
            f"🎉 **تمت الموافقة على شحن محفظتك بنجاح!**\n"
            f"─────────────────────\n"
            f"🔹 **رقم العملية:** `{tcode}`\n"
            f"➕ **المبلغ المضاف:** `{custom_amt}` {escape_md(curr)}\n\n"
            f"👛 **رصيد محفظتك الحالي الآن:**\n"
            f"• 🇩🇿 بالدينار: **`{new_wallet['balance_dzd']}` {CURRENCY}**\n"
            f"• 💵 بالدولار: **`${new_wallet['balance_usd']:.2f}`**\n"
            f"─────────────────────\n"
            "يمكنك الآن شراء أي اشتراك فوراً باستخدام رصيد محفظتك! 🚀"
        )
        await safe_send_message(context.bot, cust_id, cust_msg, parse_mode="Markdown")
        await safe_reply_text(
            update.message,
            f"✅ **تمت الموافقة على `{tcode}` وإضافة `{custom_amt}` {escape_md(curr)} لمحفظة العميل (`{cust_id}`)!**\n"
            f"👛 رصيد العميل الجديد: `{new_wallet['balance_dzd']}` {CURRENCY} | `${new_wallet['balance_usd']:.2f}`",
            parse_mode="Markdown",
        )
        return

    # 1.4 Awaiting rejection reason for Wallet Top-Up
    reject_topup_id = context.bot_data.get(f"admin_reject_topup_{user_id}")
    if reject_topup_id:
        reason = text if text != "/skip_reason" else "لم يتم التمكن من التحقق من وصول الحوالة"
        topup = await database.get_topup_by_id(reject_topup_id)
        await database.reject_wallet_topup(reject_topup_id, reason)
        context.bot_data.pop(f"admin_reject_topup_{user_id}", None)

        if topup:
            tcode = topup.get("topup_code") or f"TOP-{reject_topup_id:04d}"
            cust_msg = (
                f"❌ **نعتذر منك، تم رفض طلب شحن المحفظة `{tcode}`.**\n\n"
                f"⚠️ **السبب:** {escape_md(reason)}\n\n"
                "يرجى التأكد من إشعار التحويل أو التواصل معنا للمساعدة."
            )
            await safe_send_message(context.bot, topup["user_id"], cust_msg, parse_mode="Markdown")

        await safe_reply_text(update.message, "✅ تم رفض طلب شحن المحفظة وإشعار العميل.", parse_mode="Markdown")
        return

    # 1.5 Manual Wallet Credit Wizard (by User ID)
    manual_wallet_state = context.bot_data.get(f"admin_manual_wallet_step_{user_id}")
    if manual_wallet_state:
        step = manual_wallet_state.get("step", 1)
        if step == 1:
            if not text.isdigit():
                await update.message.reply_text("⚠️ يرجى إرسال معرف العميل الرقمي (User ID) بالأرقام فقط.")
                return
            target_uid = int(text)
            w = await database.get_user_wallet(target_uid)
            manual_wallet_state["target_uid"] = target_uid
            manual_wallet_state["step"] = 2
            context.bot_data[f"admin_manual_wallet_step_{user_id}"] = manual_wallet_state
            await safe_reply_text(
                update.message,
                f"👛 **محفظة العميل (`{target_uid}`):**\n"
                f"• الرصيد الحالي بالدينار: `{w.get('balance_dzd', 0)}` {CURRENCY}\n"
                f"• الرصيد الحالي بالدولار: `${w.get('balance_usd', 0):.2f}`\n\n"
                "✍️ **الآن أرسل المبلغ المراد إضافته مع العملة:**\n"
                "• لإضافة دينار أرسل الرقم فقط (مثال: `2000`)\n"
                "• لإضافة دولار أضف علامة `$` (مثال: `10$`)\n"
                "• لخصم رصيد ضع علامة سالب `-` (مثال: `-500` أو `-5$`)",
                parse_mode="Markdown",
            )
            return
        elif step == 2:
            target_uid = manual_wallet_state["target_uid"]
            is_usd = "$" in text or "usd" in text.lower() or "دولار" in text
            clean_num = text.replace("$", "").replace("usd", "").replace("USD", "").replace("دولار", "").replace("دج", "").replace(",", ".").strip()
            try:
                delta = float(clean_num)
            except ValueError:
                await update.message.reply_text("⚠️ صيغة غير صحيحة. أرسل مثلاً `2000` للدينار أو `10$` للدولار.")
                return

            new_w = await database.add_wallet_balance(
                target_uid,
                amount_dzd=0.0 if is_usd else delta,
                amount_usd=delta if is_usd else 0.0,
            )
            context.bot_data.pop(f"admin_manual_wallet_step_{user_id}", None)
            curr_str = "$" if is_usd else CURRENCY

            if delta > 0:
                await safe_send_message(
                    context.bot,
                    target_uid,
                    f"🎉 **تمت إضافة رصيد إلى محفظتك من قِبل الإدارة!**\n\n"
                    f"➕ **المبلغ المضاف:** `{delta}` {curr_str}\n"
                    f"👛 **رصيد محفظتك الآن:** `{new_w['balance_dzd']}` {CURRENCY} | `${new_w['balance_usd']:.2f}`",
                    parse_mode="Markdown",
                )

            await safe_reply_text(
                update.message,
                f"✅ **تم تعديل محفظة العميل (`{target_uid}`) بنجاح!**\n"
                f"• الرصيد الجديد بالدينار: `{new_w['balance_dzd']}` {CURRENCY}\n"
                f"• الرصيد الجديد بالدولار: `${new_w['balance_usd']:.2f}`",
                parse_mode="Markdown",
            )
            return

    # 2. Add product wizard
    add_prod_state = context.bot_data.get(f"admin_add_prod_step_{user_id}")
    if add_prod_state:
        step = add_prod_state.get("step", 1)
        if step == 1:
            add_prod_state["name"] = text
            add_prod_state["step"] = 2
            context.bot_data[f"admin_add_prod_step_{user_id}"] = add_prod_state
            await safe_reply_text(
                update.message,
                "➕ **إضافة منتج جديد (الخطوة 2 من 3):**\n\n"
                f"الاسم: **{escape_md(text)}**\n"
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
                await safe_reply_text(
                    update.message,
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
            await safe_reply_text(
                update.message,
                f"🎉 **تمت إضافة المنتج الجديد بنجاح!**\n\n"
                f"📦 **الاسم:** {escape_md(name)}\n"
                f"💵 **السعر:** `{price}` {CURRENCY}\n"
                f"📝 **الوصف:** {escape_md(desc)}\n\n"
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
        await safe_reply_text(
            update.message,
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
                f"⚠️ **السبب:** {escape_md(reason)}\n\n"
                "إذا كنت ترى أن هناك خطأ أو ترغب في إعادة المحاولة، يرجى مراجعة إشعار التحويل أو التواصل معنا."
            )
            try:
                await safe_send_message(
                    context.bot,
                    chat_id=order["user_id"],
                    text=cust_text,
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"Could not notify user of rejection: {e}")

        context.bot_data.pop(f"admin_reject_order_{user_id}", None)
        await safe_reply_text(
            update.message,
            "✅ تم رفض الطلب وتسجيل السبب وإشعار العميل.",
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
        await safe_reply_text(
            update.message,
            f"🎉 **تمت الإضافة بنجاح!**\n\n"
            f"📦 المنتج: **{escape_md(prod_name)}**\n"
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
        await safe_reply_text(
            update.message,
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
            title = escape_md(chat_obj.title or clean_chan)
            title_info = f"\n📢 اسم القناة: **{title}**"
        except Exception:
            title_info = "\n⚠️ تذكير: تأكد من إضافة البوت كمشرف (Admin) في القناة بصلاحية نشر الرسائل لكي يتمكن من إرسال الإثباتات."

        await safe_reply_text(
            update.message,
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
        await safe_reply_text(
            update.message,
            f"📥 **تم اكتشاف `{len(link_candidates)}` رابط في رسالتك!**\n\n"
            "👇 **يرجى اختيار المنتج المراد حفظ هذه الروابط في مخزونه السحابي:**",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

