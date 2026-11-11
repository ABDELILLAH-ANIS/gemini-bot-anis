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
AWAITING_TOPUP_AMOUNT = 6
AWAITING_TOPUP_PROOF = 7


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


async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Silent handler for pagination indicator button"""
    if update.callback_query:
        await safe_answer(update.callback_query)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command"""
    context.user_data.pop("order_draft", None)
    context.user_data.pop("topup_draft", None)
    user = update.effective_user
    products = await database.get_all_products(only_active=True)
    wallet = await database.get_user_wallet(
        user.id,
        user_name=user.full_name or "",
        user_username=f"@{user.username}" if user.username else "",
    )

    products_list_text = ""
    for p in list(products.values())[:8]:
        p_usd = p.get("price_usd", 2.5)
        products_list_text += f"• 💎 {escape_md(p['name'])} — `{p['price']}` {CURRENCY} (`${p_usd}`)\n"
    if len(products) > 8:
        products_list_text += f"• 🛍️ _و `{len(products) - 8}` باقات ومنتجات أخرى داخل القائمة..._\n"

    bal_dzd = wallet.get("balance_dzd", 0.0)
    bal_usd = wallet.get("balance_usd", 0.0)
    dzd_str = f"{int(bal_dzd)}" if float(bal_dzd).is_integer() else f"{bal_dzd:.2f}"
    usd_str = f"{bal_usd:.2f}"

    welcome_text = (
        f"مرحباً بك يا **{escape_md(user.first_name)}** في **متجر الاشتراكات الرقمية** 🤖✨\n\n"
        "نوفر لك اشتراكات رسمية بأفضل الأسعار وبضمان كامل.\n\n"
        f"👛 **رصيد محفظتك الحالي:** `{dzd_str}` {CURRENCY} | `${usd_str}`\n\n"
        f"📌 **أبرز الباقات المتوفرة حالياً:**\n{products_list_text}\n"
        "اختر من القائمة بالأسفل للبدء 👇"
    )
    if update.callback_query:
        await safe_answer(update.callback_query)
        await safe_edit_text(
            update.callback_query.message,
            welcome_text,
            reply_markup=keyboards.get_categories_keyboard(),
            parse_mode="Markdown",
        )
    else:
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
    context.user_data.pop("topup_draft", None)
    text = (
        "📘 **حول الخدمة وطريقة الشراء والتفعيل:**\n\n"
        "1. يمكنك شحن محفظتك بالدينار أو الدولار عبر زر **'👛 محفظتي (Top Up)'** والشراء الفوري بضغطة زر.\n"
        "2. أو يمكنك اختيار المنتج والدفع المباشر وإرسال وصل التحويل.\n"
        "3. لكل منتج زر أزرق **'📖 تعليمات وشروط المنتج'** يوضح طريقة التفعيل والضمان بالتفصيل.\n\n"
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
    context.user_data.pop("topup_draft", None)
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
    """Entry point: Show 3-column brand grid to browse products"""
    context.user_data.pop("order_draft", None)
    context.user_data.pop("topup_draft", None)
    text = "🛒 **اختر علامة تجارية لتصفح المنتجات:**"
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


async def _render_category_products_page(query, cat: str, page: int = 0):
    products = await database.get_products_by_category(cat, only_active=True)

    cat_titles = {
        "gemini": "🟢 ✨ **منتجات واشتراكات Google Gemini:**",
        "claude": "🔴 ✴️ **منتجات واشتراكات Claude AI:**",
        "chatgpt": "🤖 **منتجات واشتراكات ChatGPT & OpenAI:**",
        "kiro": "👻 **منتجات واشتراكات kiro:**",
        "elevenlabs": "⏸️ **منتجات واشتراكات ElevenLabs:**",
        "cursor": "🧊 **منتجات واشتراكات Cursor:**",
        "adobe": "🎨 **منتجات واشتراكات Adobe:**",
        "grok": "🪐 **منتجات واشتراكات Grok:**",
        "antigravity": "🚀 **منتجات واشتراكات Antigravity:**",
        "perplexity": "✳️ **منتجات واشتراكات Perplexity:**",
        "lovable": "💝 **منتجات واشتراكات Lovable:**",
        "heygen": "💎 **منتجات واشتراكات HeyGen:**",
        "capcut": "🎬 **منتجات واشتراكات CapCut:**",
        "notion": "📓 **منتجات واشتراكات Notion:**",
        "youtube": "▶️ **منتجات واشتراكات YouTube:**",
        "runway": "🎥 **منتجات واشتراكات Runway:**",
        "higgsfield": "⚡ **منتجات واشتراكات Higgsfield:**",
        "telegram": "⭐ **منتجات واشتراكات Telegram:**",
        "canva": "🎨 **منتجات واشتراكات Canva:**",
        "netflix": "🍿 **منتجات واشتراكات Netflix:**",
        "kling": "🌀 **منتجات واشتراكات Kling:**",
        "spotify": "🎵 **منتجات واشتراكات Spotify:**",
        "suno": "🎶 **منتجات واشتراكات Suno:**",
        "krea": "🖼️ **منتجات واشتراكات Krea:**",
        "other": "🛍️ **الباقات والمنتجات الرقمية الأخرى:**",
    }
    title = cat_titles.get(cat, f"🛍️ **منتجات {escape_md(cat)}:**")

    if not products:
        text = f"{title}\n\n⚠️ عذراً، لا توجد منتجات متوفرة في هذا القسم حالياً."
    else:
        total_items = len(products)
        per_page = 6
        total_pages = max(1, (total_items + per_page - 1) // per_page)
        page = max(0, min(page, total_pages - 1))
        page_note = f" (صفحة {page + 1} من {total_pages})" if total_pages > 1 else ""
        text = (
            f"{title}{page_note}\n"
            f"إجمالي الباقات في هذا القسم: `{total_items}` باقة.\n"
            "اختر الباقة المناسبة لك (أو اضغط **عرض التالي ➡️** لتصفح المزيد):"
        )

    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_products_keyboard(
            products, category=cat, page=page, per_page=6
        ),
        parse_mode="Markdown",
    )


async def category_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle choosing a category: 'gemini', 'claude', 'chatgpt', 'other'"""
    query = update.callback_query
    await safe_answer(query)
    cat = query.data.split(":", 1)[1]
    await _render_category_products_page(query, cat=cat, page=0)
    return SELECTING_PRODUCT


async def category_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pagination 'عرض التالي ➡️' / '⬅️ السابق' inside a category"""
    query = update.callback_query
    await safe_answer(query)
    parts = query.data.split(":")
    cat = parts[1] if len(parts) > 1 else "gemini"
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    await _render_category_products_page(query, cat=cat, page=page)
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

    # Save to draft
    context.user_data["order_draft"] = {
        "product_id": product_id,
        "product_name": product["name"],
        "price": product["price"],
        "price_usd": price_usd,
        "category": cat,
    }

    text = (
        f"💎 **لقد اخترت:** {escape_md(product['name'])}\n"
        f"🇩🇿 **السعر بالدينار:** `{product['price']}` {CURRENCY}\n"
        f"💵 **السعر بالدولار:** `${price_usd}`\n\n"
        f"📝 **الوصف (Description):**\n{escape_md(product.get('description', ''))}\n\n"
        "🔢 **الرجاء تحديد الكمية المطلوبة (أو اضغط على زر تعليمات المنتج الأزرق):**"
    )
    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_quantity_keyboard(
            product_id, category=cat, is_admin=(query.from_user.id in ADMIN_IDS)
        ),
        parse_mode="Markdown",
    )
    return SELECTING_QUANTITY


async def product_instructions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display detailed product instructions when the customer clicks the blue Instructions button"""
    query = update.callback_query
    await safe_answer(query, "📖 تعليمات وشروط المنتج")

    product_id = query.data.split(":", 1)[1]
    product = await database.get_product_by_id(product_id)
    if not product:
        await safe_edit_text(query.message, "⚠️ المنتج غير موجود.")
        return SELECTING_PRODUCT

    cat = product.get("category", "other")
    price_dzd = product.get("price", 0)
    price_usd = product.get("price_usd", 2.5)
    inst_text = (product.get("instructions") or "").strip()
    if not inst_text:
        inst_text = product.get("description") or "Official subscription with full warranty and instant delivery."

    text = (
        f"🔵 📖 **تعليمات وشروط المنتج:**\n"
        f"─────────────────────\n"
        f"📦 **المنتج:** {escape_md(product['name'])}\n"
        f"💰 **السعر:** `{price_dzd}` {CURRENCY} | `${price_usd}`\n"
        f"─────────────────────\n\n"
        f"📋 **التعليمات وطريقة التفعيل:**\n"
        f"{escape_md(inst_text)}\n\n"
        f"─────────────────────\n"
        f"👇 اضغط على **'🛒 متابعة شراء هذا المنتج'** لاختيار الكمية وإتمام الطلب:"
    )
    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_product_instructions_back_keyboard(
            product_id, category=cat, is_admin=(query.from_user.id in ADMIN_IDS)
        ),
        parse_mode="Markdown",
    )
    return SELECTING_QUANTITY


async def back_to_products_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to product list for the category"""
    query = update.callback_query
    await safe_answer(query)
    parts = query.data.split(":")
    cat = parts[1] if len(parts) > 1 else "gemini"
    await _render_category_products_page(query, cat=cat, page=0)
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
    price_dzd = draft.get("price", 1000)

    wallet = await database.get_user_wallet(query.from_user.id)
    bal_dzd = wallet.get("balance_dzd", 0.0)
    bal_usd = wallet.get("balance_usd", 0.0)

    text = (
        f"📦 **المنتج:** {escape_md(draft['product_name'])}\n"
        f"🔢 **الكمية:** `{quantity}`\n"
        f"💵 **الإجمالي:** `{price_dzd * quantity}` {CURRENCY} أو `${round(price_usd * quantity, 2)}`\n"
        f"👛 **رصيد محفظتك الحالي:** `{bal_dzd}` {CURRENCY} | `${bal_usd:.2f}`\n\n"
        "💳 **الرجاء اختيار طريقة الدفع المناسبة لك:**"
    )
    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_payment_methods_keyboard(
            product_id, quantity, price_usd=price_usd, price_dzd=price_dzd
        ),
        parse_mode="Markdown",
    )
    return SELECTING_PAYMENT


async def payment_method_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle chosen payment method (Wallet DZD/USD, BaridiMob, RedotPay, Bybit)"""
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

    # --- Direct Wallet Payment Option ---
    if method_id in ("wallet_dzd", "wallet_usd"):
        wallet = await database.get_user_wallet(query.from_user.id)
        if method_id == "wallet_dzd":
            total_price = float(draft.get("price", 1000)) * quantity
            currency = "دينار"
            user_bal = float(wallet.get("balance_dzd", 0.0))
            method_name = "محفظة الدينار 👛"
        else:
            price_usd = float(draft.get("price_usd", 2.5))
            total_price = round(price_usd * quantity, 2)
            currency = "$"
            user_bal = float(wallet.get("balance_usd", 0.0))
            method_name = "محفظة الدولار 👛"

        draft["quantity"] = quantity
        draft["payment_method"] = method_id
        draft["payment_method_name"] = method_name
        draft["total_price"] = total_price
        draft["currency"] = currency
        context.user_data["order_draft"] = draft

        if user_bal < total_price:
            needed = round(total_price - user_bal, 2)
            insufficient_text = (
                f"⚠️ **رصيد محفظتك غير كافٍ لإتمام هذه العملية!**\n"
                f"─────────────────\n"
                f"📦 **المنتج:** {escape_md(draft['product_name'])} (x{quantity})\n"
                f"💰 **المبلغ المطلوب:** `{total_price}` {escape_md(currency)}\n"
                f"👛 **رصيدك الحالي في {method_name}:** `{user_bal}` {escape_md(currency)}\n"
                f"📉 **المبلغ الناقص:** `{needed}` {escape_md(currency)}\n"
                f"─────────────────\n\n"
                "💡 يمكنك شحن محفظتك الآن عبر زر **شحن المحفظة (Top Up)** أو اختيار وسيلة دفع مباشرة أخرى:"
            )
            kb = InlineKeyboardMarkup([
                [keyboards._btn("➕ شحن المحفظة الآن (Top Up Wallet)", callback_data="wallet_menu", style="success")],
                [keyboards._btn("🔙 اختيار طريقة دفع أخرى", callback_data="change_payment_method", style="primary")],
                [keyboards._btn("❌ إلغاء الطلب", callback_data="cancel_order")],
            ])
            await safe_edit_text(query.message, insufficient_text, reply_markup=kb, parse_mode="Markdown")
            return SELECTING_PAYMENT

        remaining = round(user_bal - total_price, 2)
        confirm_text = (
            f"👛 **تأكيد الدفع الفوري من المحفظة:**\n"
            f"─────────────────\n"
            f"📦 **المنتج:** {escape_md(draft['product_name'])}\n"
            f"🔢 **الكمية:** `{quantity}`\n"
            f"💳 **طريقة الدفع:** {method_name}\n"
            f"💰 **المبلغ المطلوب خصمه:** `{total_price}` {escape_md(currency)}\n"
            f"👛 **رصيدك الحالي:** `{user_bal}` {escape_md(currency)}\n"
            f"✅ **الرصيد المتبقي بعد الشراء:** `{remaining}` {escape_md(currency)}\n"
            f"─────────────────\n\n"
            "👇 اضغط على الزر الأخضر بالأسفل لتأكيد الخصم واستلام اشتراكك فوراً:"
        )
        await safe_edit_text(
            query.message,
            confirm_text,
            reply_markup=keyboards.get_wallet_pay_confirm_keyboard(product_id),
            parse_mode="Markdown",
        )
        return SELECTING_PAYMENT

    # --- Standard External Payment Methods (BaridiMob, RedotPay, Bybit) ---
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

    summary_text = (
        f"📋 **ملخص طلبك:**\n"
        f"─────────────────\n"
        f"📦 **المنتج:** {escape_md(draft['product_name'])}\n"
        f"🔢 **الكمية:** `{quantity}`\n"
        f"💳 **طريقة الدفع:** {escape_md(method['name'])}\n"
        f"💰 **المبلغ الإجمالي المطلوب:** `{total_price}` {escape_md(currency)}\n"
        f"─────────────────\n"
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


async def confirm_wallet_pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deduct balance from customer's wallet and fulfill order immediately"""
    query = update.callback_query
    user = query.from_user
    draft = context.user_data.get("order_draft")
    if not draft:
        await safe_answer(query, "⚠️ انتهت الجلسة، يرجى إعادة الطلب.", show_alert=True)
        return ConversationHandler.END

    method_id = draft.get("payment_method", "wallet_dzd")
    total_price = float(draft.get("total_price", 0))
    currency = draft.get("currency", "دينار")
    product_id = draft["product_id"]
    quantity = int(draft.get("quantity", 1))

    wallet = await database.get_user_wallet(user.id)
    if method_id == "wallet_dzd":
        if float(wallet.get("balance_dzd", 0.0)) < total_price:
            await safe_answer(query, "⚠️ رصيد محفظة الدينار غير كافٍ!", show_alert=True)
            return SELECTING_PAYMENT
        await safe_answer(query, "⏳ جاري خصم الرصيد وتجهيز اشتراكك...")
        updated_wallet = await database.add_wallet_balance(
            user.id,
            amount_dzd=-total_price,
            amount_usd=0.0,
            user_name=user.full_name or "",
            user_username=f"@{user.username}" if user.username else "",
        )
    else:
        if float(wallet.get("balance_usd", 0.0)) < total_price:
            await safe_answer(query, "⚠️ رصيد محفظة الدولار غير كافٍ!", show_alert=True)
            return SELECTING_PAYMENT
        await safe_answer(query, "⏳ جاري خصم الرصيد وتجهيز اشتراكك...")
        updated_wallet = await database.add_wallet_balance(
            user.id,
            amount_dzd=0.0,
            amount_usd=-total_price,
            user_name=user.full_name or "",
            user_username=f"@{user.username}" if user.username else "",
        )

    pay_method_name = draft.get("payment_method_name", "محفظة المتجر 👛")
    transfer_ref = f"مدفوع من المحفظة ({total_price} {currency})"
    draft["transfer_number"] = transfer_ref
    draft["receipt_file_id"] = ""

    order_id, order_code = await database.create_order(
        user_id=user.id,
        user_name=user.full_name or "مستخدم",
        user_username=f"@{user.username}" if user.username else "بدون يوزر",
        product_id=product_id,
        product_name=draft["product_name"],
        quantity=quantity,
        total_price=total_price,
        transfer_number=transfer_ref,
        receipt_file_id="",
        payment_method=pay_method_name,
        currency=currency,
    )

    order_obj = await database.get_order_by_id(order_id) or {
        "id": order_id,
        "order_code": order_code,
        "user_id": user.id,
        "user_name": user.full_name or "مستخدم",
        "user_username": f"@{user.username}" if user.username else "بدون يوزر",
        "product_id": product_id,
        "product_name": draft["product_name"],
        "quantity": quantity,
        "total_price": total_price,
        "currency": currency,
        "payment_method": pay_method_name,
    }

    import handlers_admin as adm

    # 1. Try immediate delivery from local stock
    delivered_links = []
    delivery_source = ""
    available_links = await database.get_available_links_from_stock(product_id, quantity)
    if len(available_links) >= quantity:
        link_ids = [l["id"] for l in available_links]
        delivered_links = [l["link_url"] for l in available_links]
        await database.consume_stock_links(link_ids, order_id, user.id)
        await database.mark_order_approved(order_id, delivered_links)
        delivery_source = "المخزن المحلي"
    else:
        # 2. Try automatic purchase via Supplier APIs
        api_success, api_links, api_msg, provider_used = await supplier_api.purchase_with_fallback(
            local_product_id=product_id,
            quantity=quantity,
            order_code=order_code,
        )
        if api_success and api_links:
            delivered_links = api_links
            await database.mark_order_approved(order_id, delivered_links)
            delivery_source = f"API المورد ({provider_used})"

    context.user_data.pop("order_draft", None)

    if delivered_links:
        await adm.deliver_links_to_customer(context, order_obj, delivered_links)
        await safe_edit_text(
            query.message,
            f"✅ **تم الدفع من محفظتك وتسليم الطلب `{order_code}` فوراً!**\n\n"
            f"📦 **المنتج:** {escape_md(draft['product_name'])}\n"
            f"💰 **المبلغ المخصوم:** `{total_price}` {escape_md(currency)}\n"
            f"👛 **رصيد محفظتك المتبقي:** `{updated_wallet['balance_dzd']}` {CURRENCY} | `${updated_wallet['balance_usd']:.2f}`\n\n"
            "تم إرسال روابط/بيانات التفعيل في الرسالة أعلاه. شكراً لثقتك بنا! 🚀",
            parse_mode="Markdown",
        )
        # Notify Admins of completed wallet order
        admin_note = (
            f"👛 ✅ **عملية شراء فورية ناجحة عبر المحفظة (`{order_code}`)**\n"
            f"─────────────────\n"
            f"👤 **العميل:** {escape_md(user.full_name)} ({escape_md('@' + user.username if user.username else 'بدون يوزر')}) | ID: `{user.id}`\n"
            f"📦 **المنتج:** {escape_md(draft['product_name'])} (x`{quantity}`)\n"
            f"💰 **المبلغ المخصوم:** `{total_price}` {escape_md(currency)} ({escape_md(pay_method_name)})\n"
            f"⚡ **التسليم:** تم التسليم تلقائياً من **{escape_md(delivery_source)}**."
        )
        for admin_id in ADMIN_IDS:
            await adm.safe_send_message(context.bot, admin_id, admin_note, parse_mode="Markdown")
        return ConversationHandler.END

    # 3. If not in stock / requires manual fulfillment, keep order PENDING and notify Admin
    await safe_edit_text(
        query.message,
        f"🎉 **تم خصم المبلغ من محفظتك وتأكيد طلبك `{order_code}` بنجاح!**\n\n"
        f"📦 **المنتج:** {escape_md(draft['product_name'])} (x`{quantity}`)\n"
        f"💰 **المبلغ المدفوع:** `{total_price}` {escape_md(currency)}\n"
        f"👛 **رصيد محفظتك المتبقي:** `{updated_wallet['balance_dzd']}` {CURRENCY} | `${updated_wallet['balance_usd']:.2f}`\n\n"
        "⏳ **حالة الطلب:** جاري تجهيز الحساب/الرابط يدوياً من قبل المشرف وسيصلك هنا في أقرب وقت! 🌟",
        parse_mode="Markdown",
    )
    await notify_admins_new_order(context, order_id, order_code, user, draft)
    return ConversationHandler.END


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
    price_dzd = draft.get("price", 1000)

    text = (
        f"📦 **المنتج:** {escape_md(draft.get('product_name'))}\n"
        f"🔢 **الكمية:** `{quantity}`\n\n"
        "💳 **الرجاء اختيار طريقة الدفع المناسبة لك:**"
    )
    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_payment_methods_keyboard(
            product_id, quantity, price_usd=price_usd, price_dzd=price_dzd
        ),
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
    import handlers_admin as adm
    if adm.has_active_admin_prompt(update.effective_user.id, context):
        await adm.handle_admin_text_input(update, context)
        return ConversationHandler.END

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

    pname_safe = escape_md(draft["product_name"])
    tnum_safe = escape_md(draft.get("transfer_number"))
    pm_safe = escape_md(pay_method)
    curr_safe = escape_md(pay_curr)

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

    await notify_admins_new_order(context, order_id, order_code, user, draft)
    context.user_data.pop("order_draft", None)
    return ConversationHandler.END


async def notify_admins_new_order(
    context: ContextTypes.DEFAULT_TYPE,
    order_id: int,
    order_code: str,
    user,
    draft: dict,
):
    """Send photo (or text card if wallet-paid) and order details to all registered admins"""
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
    receipt_fid = draft.get("receipt_file_id")

    for admin_id in ADMIN_IDS:
        if not receipt_fid:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_caption,
                    reply_markup=kb,
                    parse_mode="Markdown",
                )
            except Exception:
                clean_caption = admin_caption.replace("**", "").replace("`", "").replace("\\_", "_").replace("\\*", "*")
                await context.bot.send_message(chat_id=admin_id, text=clean_caption, reply_markup=kb)
            continue

        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=receipt_fid,
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
                    photo=receipt_fid,
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


# ==================== محفظة العميل وشحن الرصيد (Customer Wallet & Top-Up Flow) ====================

async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display Customer Dual-Currency Wallet (DZD & USD) and Top-Up options"""
    context.user_data.pop("order_draft", None)
    context.user_data.pop("topup_draft", None)
    user = update.effective_user
    wallet = await database.get_user_wallet(
        user.id,
        user_name=user.full_name or "",
        user_username=f"@{user.username}" if user.username else "",
    )

    bal_dzd = float(wallet.get("balance_dzd", 0.0))
    bal_usd = float(wallet.get("balance_usd", 0.0))
    dzd_str = f"{int(bal_dzd)}" if bal_dzd.is_integer() else f"{bal_dzd:.2f}"
    usd_str = f"{bal_usd:.2f}"

    text = (
        f"👛 **محفظتي الإلكترونية (TOP UP WALLET)**\n"
        f"─────────────────────\n"
        f"👤 **الحساب:** {escape_md(user.full_name)} (`{user.id}`)\n\n"
        f"🇩🇿 **الرصيد بالدينار الجزائري:** `{dzd_str}` {CURRENCY}\n"
        f"💵 **الرصيد بالدولار الأمريكي:** `${usd_str}`\n"
        f"─────────────────────\n"
        "💡 **كيف تعمل المحفظة؟**\n"
        "1. اختر العملة التي تريد شحنها (**دينار** أو **دولار**).\n"
        "2. أدخل المبلغ الذي تريد إضافته لمحفظتك وقم بالتحويل.\n"
        "3. أرسل تأكيد التحويل أو صورة الوصل، وبمجرد تأكيد الإدارة يظهر الرصيد فوراً في محفظتك لتشتري به أي منتج بضغطة زر!\n\n"
        "👇 اختر العملية المطلوبة بالأسفل:"
    )

    if update.callback_query:
        await safe_answer(update.callback_query)
        await safe_edit_text(
            update.callback_query.message,
            text,
            reply_markup=keyboards.get_wallet_main_keyboard(),
            parse_mode="Markdown",
        )
    else:
        await safe_reply_text(
            update.message,
            text,
            reply_markup=keyboards.get_wallet_main_keyboard(),
            parse_mode="Markdown",
        )
    return SELECTING_PRODUCT


async def wallet_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show customer's recent wallet top-up requests"""
    query = update.callback_query
    await safe_answer(query)
    user_id = query.from_user.id
    topups = await database.get_user_topups(user_id, limit=10)

    if not topups:
        text = (
            "📜 **سجل عمليات شحن المحفظة:**\n\n"
            "لا توجد لديك أي طلبات شحن سابقة حتى الآن.\n"
            "اضغط على **شحن المحفظة** بالأسفل لإضافة رصيدك الأول!"
        )
    else:
        text = "📜 **آخر عمليات شحن المحفظة الخاصة بك:**\n─────────────────────\n"
        for t in topups:
            st = t.get("status", "PENDING")
            st_badge = {
                "PENDING": "⏳ قيد المراجعة",
                "APPROVED": "✅ تمت إضافة الرصيد",
                "REJECTED": "❌ مرفوض",
            }.get(st, st)
            tcode = t.get("topup_code") or f"TOP-{t['id']:04d}"
            text += (
                f"🔹 `{tcode}` — `{t.get('amount')}` {escape_md(t.get('currency'))}\n"
                f"• الوسيلة: {escape_md(t.get('payment_method'))} | الحالة: {st_badge}\n"
                f"• التاريخ: `{format_dt(t.get('created_at'))}`\n"
            )
            if st == "REJECTED" and t.get("reject_reason"):
                text += f"• سبب الرفض: {escape_md(t['reject_reason'])}\n"
            text += "───────────────\n"

    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_wallet_main_keyboard(),
        parse_mode="Markdown",
    )
    return SELECTING_PRODUCT


async def wallet_topup_curr_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Customer selects currency to top up: 'dzd' or 'usd'"""
    query = update.callback_query
    await safe_answer(query)

    curr_code = query.data.split(":", 1)[1].lower()
    currency_label = "دينار" if curr_code == "dzd" else "$"
    context.user_data["topup_draft"] = {
        "curr_code": curr_code,
        "currency": currency_label,
    }

    if curr_code == "dzd":
        text = (
            "🇩🇿 **شحن المحفظة بالدينار الجزائري (Top Up DZD):**\n"
            "─────────────────────\n"
            "✍️ **أدخل المبلغ بالدينار الذي تريد شحنه في محفظتك (أرقام فقط، أو اختر من الأزرار السريعة بالأسفل):**\n"
            "مثال: `2000` أو `5000`"
        )
    else:
        text = (
            "💵 **شحن المحفظة بالدولار الأمريكي (Top Up USD):**\n"
            "─────────────────────\n"
            "✍️ **أدخل المبلغ بالدولار (`$`) الذي تريد شحنه في محفظتك (أرقام فقط، أو اختر من الأزرار السريعة بالأسفل):**\n"
            "مثال: `10` أو `25`"
        )

    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_wallet_amount_presets_keyboard(curr_code),
        parse_mode="Markdown",
    )
    return AWAITING_TOPUP_AMOUNT


async def _show_topup_payment_step(message_or_query, context: ContextTypes.DEFAULT_TYPE, is_callback: bool):
    draft = context.user_data.get("topup_draft", {})
    curr_code = draft.get("curr_code", "dzd")
    amount = draft.get("amount", 0)

    if curr_code == "dzd":
        draft["payment_method"] = "بريدي موب (BaridiMob)"
        context.user_data["topup_draft"] = draft
        pay_info = await database.get_payment_info()
        text = (
            f"👛 **شحن المحفظة بمبلغ `{amount}` {CURRENCY}**\n"
            f"─────────────────────\n"
            f"💳 **طريقة التحويل:** بريدي موب (BaridiMob)\n"
            f"💰 **المبلغ المطلوب تحويله:** `{amount}` {CURRENCY}\n"
            f"─────────────────────\n"
            f"{pay_info}\n\n"
            "👇 بعد إتمام التحويل، اضغط على الزر الأخضر بالأسفل لإرسال الوصل أو تأكيد التحويل:"
        )
        kb = keyboards.get_wallet_confirm_transfer_keyboard()
    else:
        text = (
            f"👛 **شحن المحفظة بمبلغ `${amount}` دولار**\n"
            f"─────────────────────\n"
            "💳 **اختر وسيلة الدفع بالدولار التي تود التحويل عبرها:**"
        )
        kb = keyboards.get_wallet_usd_methods_keyboard(amount)

    if is_callback:
        await safe_edit_text(message_or_query.message, text, reply_markup=kb, parse_mode="Markdown")
    else:
        await safe_reply_text(message_or_query, text, reply_markup=kb, parse_mode="Markdown")


async def wallet_amount_preset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Customer tapped a preset amount button for Wallet Top-Up"""
    query = update.callback_query
    await safe_answer(query)
    parts = query.data.split(":")
    curr_code = parts[1].lower()
    amount = float(parts[2])

    context.user_data["topup_draft"] = {
        "curr_code": curr_code,
        "currency": "دينار" if curr_code == "dzd" else "$",
        "amount": amount,
    }
    await _show_topup_payment_step(query, context, is_callback=True)
    return AWAITING_TOPUP_AMOUNT


async def wallet_amount_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Customer typed a custom amount for Wallet Top-Up"""
    import handlers_admin as adm
    if adm.has_active_admin_prompt(update.effective_user.id, context):
        await adm.handle_admin_text_input(update, context)
        return ConversationHandler.END

    raw = (update.message.text or "").strip().replace(",", ".").replace("$", "").replace("دج", "").strip()
    draft = context.user_data.get("topup_draft")
    if not draft:
        return await wallet_command(update, context)

    try:
        amount = float(raw)
        if amount <= 0:
            raise ValueError()
    except ValueError:
        await safe_reply_text(
            update.message,
            "⚠️ يرجى إدخال مبلغ رقمي صحيح أكبر من الصفر (مثال: `2000` أو `10`).",
            parse_mode="Markdown",
        )
        return AWAITING_TOPUP_AMOUNT

    draft["amount"] = round(amount, 2) if draft.get("curr_code") == "usd" else int(amount)
    context.user_data["topup_draft"] = draft
    await _show_topup_payment_step(update.message, context, is_callback=False)
    return AWAITING_TOPUP_AMOUNT


async def wallet_paym_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Customer selected USD payment method (RedotPay or Bybit) for Wallet Top-Up"""
    query = update.callback_query
    await safe_answer(query)
    parts = query.data.split(":")
    curr_code = parts[1]
    amount = float(parts[2])
    method_key = parts[3]

    method_info = PAYMENT_METHODS.get(method_key, PAYMENT_METHODS["redotpay"])
    draft = context.user_data.get("topup_draft", {})
    draft["curr_code"] = curr_code
    draft["currency"] = "$"
    draft["amount"] = amount
    draft["payment_method"] = method_info["name"]
    context.user_data["topup_draft"] = draft

    text = (
        f"👛 **شحن المحفظة بمبلغ `${amount}` دولار**\n"
        f"─────────────────────\n"
        f"💳 **وسيلة الدفع:** {escape_md(method_info['name'])}\n"
        f"💰 **المبلغ المطلوب تحويله:** `${amount}`\n"
        f"─────────────────────\n"
        f"{method_info['details']}\n\n"
        "👇 بعد إتمام التحويل، اضغط على الزر الأخضر بالأسفل لإرسال الوصل أو تأكيد العملية:"
    )
    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_wallet_confirm_transfer_keyboard(),
        parse_mode="Markdown",
    )
    return AWAITING_TOPUP_AMOUNT


async def wallet_upload_proof_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Customer clicked 'I transferred' and is ready to send receipt photo or transfer confirmation"""
    query = update.callback_query
    await safe_answer(query)
    draft = context.user_data.get("topup_draft")
    if not draft or not draft.get("amount"):
        return await wallet_command(update, context)

    text = (
        f"📤 **تأكيد شحن المحفظة بمبلغ `{draft['amount']}` {escape_md(draft['currency'])}**\n"
        f"─────────────────────\n"
        "📸 **أرسل الآن صورة وصل التحويل (Screenshot)**، أو **اكتب رقم عملية التحويل / رسالة تأكيد بأنك قمت بالتحويل** في المحادثة:\n\n"
        "⏳ سيقوم المشرف بمراجعة الحوالة والموافقة عليها ليظهر الرصيد في محفظتك فوراً!"
    )
    await safe_edit_text(query.message, text, parse_mode="Markdown")
    await safe_reply_text(
        query.message,
        "أرسل صورة الوصل أو رقم التحويل الآن (أو اضغط '❌ إلغاء العملية' للتراجع):",
        reply_markup=keyboards.get_cancel_reply_keyboard(),
    )
    return AWAITING_TOPUP_PROOF


async def wallet_proof_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo OR text proof sent by customer for Wallet Top-Up"""
    import handlers_admin as adm
    if update.message and update.message.text and adm.has_active_admin_prompt(update.effective_user.id, context):
        await adm.handle_admin_text_input(update, context)
        return ConversationHandler.END

    message = update.message
    user = update.effective_user
    draft = context.user_data.get("topup_draft")
    if not draft or not draft.get("amount"):
        await safe_reply_text(
            message,
            "⚠️ انتهت الجلسة، يرجى فتح المحفظة والمحاولة من جديد.",
            reply_markup=keyboards.get_main_menu(user.id),
        )
        return ConversationHandler.END

    receipt_file_id = ""
    transfer_number = ""

    if message.photo:
        receipt_file_id = message.photo[-1].file_id
        transfer_number = (message.caption or "").strip() or "مرفق بصورة الوصل"
    else:
        transfer_number = (message.text or "").strip()

    amount = draft["amount"]
    currency = draft.get("currency", "دينار")
    pay_method = draft.get("payment_method", "بريدي موب")

    topup_id, topup_code = await database.create_wallet_topup(
        user_id=user.id,
        user_name=user.full_name or "عميل",
        user_username=f"@{user.username}" if user.username else "بدون يوزر",
        amount=amount,
        currency=currency,
        payment_method=pay_method,
        transfer_number=transfer_number,
        receipt_file_id=receipt_file_id,
    )

    context.user_data.pop("topup_draft", None)

    cust_msg = (
        f"🎉 **تم إرسال طلب شحن المحفظة بنجاح!**\n"
        f"─────────────────────\n"
        f"🔹 **رقم العملية:** `{topup_code}`\n"
        f"💰 **المبلغ المطلوب إضافته:** `{amount}` {escape_md(currency)}\n"
        f"💳 **وسيلة الدفع:** {escape_md(pay_method)}\n"
        f"🧾 **المرجع / التأكيد:** `{escape_md(transfer_number)}`\n"
        f"─────────────────────\n"
        "⏳ **الحالة:** بانتظار تأكيد الإدارة.\n"
        "بمجرد التحقق من وصول المبلغ والموافقة عليه سيصلك إشعار فوري هنا ويُضاف الرصيد إلى محفظتك! 🌟"
    )
    await safe_reply_text(
        message,
        cust_msg,
        reply_markup=keyboards.get_main_menu(user.id),
        parse_mode="Markdown",
    )

    # Notify Admins immediately
    await notify_admins_new_topup(
        context=context,
        topup_id=topup_id,
        topup_code=topup_code,
        user=user,
        amount=amount,
        currency=currency,
        payment_method=pay_method,
        transfer_number=transfer_number,
        receipt_file_id=receipt_file_id,
    )
    return ConversationHandler.END


async def notify_admins_new_topup(
    context: ContextTypes.DEFAULT_TYPE,
    topup_id: int,
    topup_code: str,
    user,
    amount: float,
    currency: str,
    payment_method: str,
    transfer_number: str,
    receipt_file_id: str,
):
    """Send immediate notification to Admins to verify and approve a Wallet Top-Up"""
    wallet = await database.get_user_wallet(user.id)
    uname_safe = escape_md(user.full_name or "عميل")
    uuser_safe = escape_md(f"@{user.username}" if user.username else "بدون يوزر")

    admin_text = (
        f"👛 **طلب شحن محفظة جديد (TOP UP): `{topup_code}`**\n"
        f"─────────────────────\n"
        f"👤 **العميل:** {uname_safe} ({uuser_safe})\n"
        f"🆔 **معرف العميل (ID):** `{user.id}`\n\n"
        f"💰 **المبلغ المطلوب شحنه:** `{amount}` {escape_md(currency)}\n"
        f"💳 **طريقة التحويل:** {escape_md(payment_method)}\n"
        f"🧾 **المرجع / التأكيد:** `{escape_md(transfer_number)}`\n"
        f"─────────────────────\n"
        f"📊 **رصيد العميل الحالي قبل الشحن:**\n"
        f"• بالدينار: `{wallet.get('balance_dzd', 0)}` {CURRENCY}\n"
        f"• بالدولار: `${wallet.get('balance_usd', 0):.2f}`\n\n"
        "👇 بعد التأكد من وصول المال، اضغط **موافقة وإضافة الرصيد للمحفظة**:"
    )
    kb = keyboards.get_admin_topup_keyboard(topup_id, user.id)

    for admin_id in ADMIN_IDS:
        if receipt_file_id:
            try:
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=receipt_file_id,
                    caption=admin_text,
                    reply_markup=kb,
                    parse_mode="Markdown",
                )
                continue
            except Exception:
                clean_cap = admin_text.replace("**", "").replace("`", "").replace("\\_", "_")
                try:
                    await context.bot.send_photo(
                        chat_id=admin_id,
                        photo=receipt_file_id,
                        caption=clean_cap,
                        reply_markup=kb,
                    )
                    continue
                except Exception:
                    pass

        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                reply_markup=kb,
                parse_mode="Markdown",
            )
        except Exception:
            clean_txt = admin_text.replace("**", "").replace("`", "").replace("\\_", "_")
            await context.bot.send_message(chat_id=admin_id, text=clean_txt, reply_markup=kb)


async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel order or wallet topup conversation"""
    context.user_data.pop("order_draft", None)
    context.user_data.pop("topup_draft", None)
    if update.callback_query:
        await safe_answer(update.callback_query)
        await safe_edit_text(update.callback_query.message, "❌ تم إلغاء العملية.")
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
        "✅ **تم استلام الصورة وإرسالها لإدارة المتجر بنجاح.**\n"
        "سيقوم المشرف بمراجعتها والرد عليك قريباً.",
        parse_mode="Markdown",
    )
