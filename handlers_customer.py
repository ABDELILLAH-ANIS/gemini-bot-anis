import asyncio
import logging
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
)
from config import (
    CURRENCY,
    ADMIN_IDS,
    PAYMENT_METHODS,
    DEFAULT_PAYMENT_INFO,
    FORCE_JOIN_CHANNELS,
)
import database
import keyboards
import supplier_api
import i18n

logger = logging.getLogger(__name__)

# Conversation states
SELECTING_PRODUCT = 1
SELECTING_QUANTITY = 2
SELECTING_PAYMENT = 3
AWAITING_RECEIPT = 4
AWAITING_TRANSFER_NO = 5
AWAITING_TOPUP_AMOUNT = 6
AWAITING_TOPUP_PROOF = 7

# Short cache for dynamic Telegram chat invite link lookups
_CHAT_URL_CACHE: dict[str, tuple[str, float]] = {}


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


# ==================== Language & Force-Join Helpers ====================

async def get_user_lang(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    cached = context.user_data.get("lang")
    if cached in i18n.SUPPORTED_LANGS:
        return cached
    lang = await database.get_user_language(user_id)
    if lang in i18n.SUPPORTED_LANGS:
        context.user_data["lang"] = lang
        return lang
    return None


async def _resolve_channel_url(bot, ch: dict, lang: str) -> tuple[str, bool]:
    """Resolve join URL for a required channel/chat. Returns (url, via_channel_discuss)."""
    ch_id = ch.get("id", "")
    if ch_id == "main_chat":
        db_url = await database.get_force_join_chat_url()
        if db_url:
            return db_url, False

    cfg_url = (ch.get("url") or "").strip()
    if cfg_url:
        return cfg_url, False

    # Try cached Telegram invite_link / username lookup
    cache_key = str(ch.get("chat_id"))
    now = time.time()
    if cache_key in _CHAT_URL_CACHE:
        cached_url, ts = _CHAT_URL_CACHE[cache_key]
        if now - ts < 300:
            return cached_url, (cached_url == "https://t.me/anisgooglebot")

    try:
        chat_obj = await bot.get_chat(ch["chat_id"])
        if getattr(chat_obj, "username", None):
            resolved = f"https://t.me/{chat_obj.username}"
            _CHAT_URL_CACHE[cache_key] = (resolved, now)
            return resolved, False
        if getattr(chat_obj, "invite_link", None):
            resolved = chat_obj.invite_link
            _CHAT_URL_CACHE[cache_key] = (resolved, now)
            return resolved, False
    except Exception as e:
        logger.debug(f"Could not resolve invite link for {ch['chat_id']}: {e}")

    # Fallback to main channel where Telegram shows the linked Discuss/Chat button
    _CHAT_URL_CACHE[cache_key] = ("https://t.me/anisgooglebot", now)
    return "https://t.me/anisgooglebot", True


async def _check_single_channel(bot, user_id: int, ch: dict, lang: str) -> dict:
    target = ch["chat_id"]
    joined = False
    try:
        member = await bot.get_chat_member(chat_id=target, user_id=user_id)
        status = getattr(member, "status", "")
        if status in ("creator", "administrator", "member"):
            joined = True
        elif status == "restricted" and getattr(member, "is_member", False):
            joined = True
    except Exception as e:
        logger.warning(f"Force-join get_chat_member failed for {target} (user {user_id}): {e}")
        # If bot cannot inspect chat at all, avoid permanently soft-locking users if misconfigured
        if "Chat not found" in str(e) or "bot is not a member" in str(e).lower():
            joined = True

    url, via_discuss = await _resolve_channel_url(bot, ch, lang)
    title = ch.get("title", {}).get(lang) or ch.get("title", {}).get("ar") or str(target)
    return {
        "id": ch.get("id"),
        "chat_id": target,
        "title": title,
        "url": url,
        "via_discuss": via_discuss,
        "joined": joined,
    }


async def check_user_membership(bot, user_id: int, lang: str = "ar") -> tuple[bool, list[dict]]:
    """Verify whether the user is a member of all required channels/chats."""
    if not await database.is_force_join_enabled():
        return True, []

    statuses = await asyncio.gather(
        *(_check_single_channel(bot, user_id, ch, lang) for ch in FORCE_JOIN_CHANNELS)
    )
    all_joined = all(s["joined"] for s in statuses)
    return all_joined, list(statuses)


async def send_language_selector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = i18n.t("ar", "choose_language_prompt")
    kb = keyboards.get_language_selection_keyboard()
    if update.callback_query:
        await safe_answer(update.callback_query)
        await safe_edit_text(update.callback_query.message, text, reply_markup=kb, parse_mode="Markdown")
    elif update.message:
        await safe_reply_text(update.message, text, reply_markup=kb, parse_mode="Markdown")


async def send_force_join_gate(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
    statuses: list[dict],
    edit_existing: bool = False,
):
    lines = [i18n.t(lang, "force_join_title"), ""]
    has_discuss_fallback = False
    for s in statuses:
        badge = i18n.t(lang, "force_join_status_joined") if s["joined"] else i18n.t(lang, "force_join_status_missing")
        lines.append(f"• {s['title']} — {badge}")
        if s.get("via_discuss") and not s["joined"]:
            has_discuss_fallback = True

    lines.append("")
    lines.append(i18n.t(lang, "force_join_desc"))
    if has_discuss_fallback:
        lines.append("")
        lines.append(i18n.t(lang, "force_join_chat_note"))

    text = "\n".join(lines)
    kb = keyboards.get_force_join_keyboard(lang, statuses)

    if update.callback_query and (edit_existing or update.callback_query.message):
        await safe_edit_text(update.callback_query.message, text, reply_markup=kb, parse_mode="Markdown")
    elif update.message:
        await safe_reply_text(update.message, text, reply_markup=kb, parse_mode="Markdown")


async def ensure_ready(update: Update, context: ContextTypes.DEFAULT_TYPE, check_join: bool = True) -> str | None:
    """
    Gatekeeper for all customer actions:
    1. Ensures user has picked a language (AR / EN / FR).
    2. Ensures user has joined all required channels/chats.
    Returns user's lang string if ready, otherwise prompts user and returns None.
    """
    user = update.effective_user
    if not user:
        return None

    lang = await get_user_lang(user.id, context)
    if not lang:
        await send_language_selector(update, context)
        return None

    if check_join:
        all_joined, statuses = await check_user_membership(context.bot, user.id, lang=lang)
        if not all_joined:
            if update.callback_query:
                await safe_answer(update.callback_query)
            await send_force_join_gate(update, context, lang, statuses, edit_existing=bool(update.callback_query))
            return None

    return lang


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open language selector (/lang, /language, or 🌐 Language button)"""
    context.user_data.pop("order_draft", None)
    context.user_data.pop("topup_draft", None)
    await send_language_selector(update, context)
    return ConversationHandler.END


async def language_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle language button tap: lang:ar | lang:en | lang:fr"""
    query = update.callback_query
    user = query.from_user
    lang = query.data.split(":", 1)[1].strip().lower()
    if lang not in i18n.SUPPORTED_LANGS:
        lang = "ar"

    await database.set_user_language(user.id, lang)
    context.user_data["lang"] = lang
    await safe_answer(query, i18n.t(lang, "lang_saved_toast"))

    # Check Force-Join immediately after language selection
    all_joined, statuses = await check_user_membership(context.bot, user.id, lang=lang)
    if not all_joined:
        await send_force_join_gate(update, context, lang, statuses, edit_existing=True)
        return ConversationHandler.END

    # Delete the language selector inline message and send fresh localized Welcome + Main Menu keyboard
    try:
        await query.message.delete()
    except Exception:
        pass
    await _send_welcome_message(context, user, query.message, lang, as_reply=True)
    return ConversationHandler.END


async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify membership button callback ('check_join')"""
    query = update.callback_query
    user = query.from_user
    lang = await get_user_lang(user.id, context)
    if not lang:
        await send_language_selector(update, context)
        return ConversationHandler.END

    all_joined, statuses = await check_user_membership(context.bot, user.id, lang=lang)
    if not all_joined:
        missing_titles = ", ".join(s["title"] for s in statuses if not s["joined"])
        await safe_answer(
            query,
            i18n.t(lang, "force_join_not_yet_alert", missing=missing_titles),
            show_alert=True,
        )
        await send_force_join_gate(update, context, lang, statuses, edit_existing=True)
        return ConversationHandler.END

    await safe_answer(query, i18n.t(lang, "force_join_verified_toast"))
    try:
        await query.message.delete()
    except Exception:
        pass
    await _send_welcome_message(context, user, query.message, lang, as_reply=True)
    return ConversationHandler.END


async def get_localized_payment_info(lang: str) -> str:
    """Return BaridiMob payment info localized or smart-translated if customized by admin."""
    raw_info = await database.get_payment_info()
    if not raw_info or raw_info.strip() == DEFAULT_PAYMENT_INFO.strip():
        return i18n.t(lang, "baridimob_details")
    return await i18n.smart_translate(raw_info, lang)


# ==================== Start, Welcome, Help & Orders ====================

async def _send_welcome_message(
    context: ContextTypes.DEFAULT_TYPE,
    user,
    message,
    lang: str,
    as_reply: bool = True,
):
    products = await database.get_all_products(only_active=True)
    wallet = await database.get_user_wallet(
        user.id,
        user_name=user.full_name or "",
        user_username=f"@{user.username}" if user.username else "",
    )

    featured_list = list(products.values())[:8]
    translated_names = await asyncio.gather(
        *(i18n.smart_translate_title(p["name"], lang) for p in featured_list)
    )
    curr_lbl = i18n.currency_label(lang)

    products_list_text = ""
    for p, tname in zip(featured_list, translated_names):
        p_usd = p.get("price_usd", 2.5)
        products_list_text += f"• 💎 {escape_md(tname)} — `{p['price']}` {curr_lbl} (`${p_usd}`)\n"
    if len(products) > 8:
        products_list_text += i18n.t(lang, "more_products_note", count=len(products) - 8)

    bal_dzd = wallet.get("balance_dzd", 0.0)
    bal_usd = wallet.get("balance_usd", 0.0)
    dzd_str = f"{int(bal_dzd)}" if float(bal_dzd).is_integer() else f"{bal_dzd:.2f}"
    usd_str = f"{bal_usd:.2f}"

    welcome_text = i18n.t(
        lang,
        "welcome",
        name=escape_md(user.first_name or "Friend"),
        dzd=dzd_str,
        curr=curr_lbl,
        usd=usd_str,
        products_list=products_list_text,
    )

    if as_reply:
        await safe_reply_text(
            message,
            welcome_text,
            reply_markup=keyboards.get_main_menu(user.id, lang=lang),
            parse_mode="Markdown",
        )
    else:
        await safe_edit_text(
            message,
            welcome_text,
            reply_markup=keyboards.get_categories_keyboard(lang=lang),
            parse_mode="Markdown",
        )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command"""
    context.user_data.pop("order_draft", None)
    context.user_data.pop("topup_draft", None)

    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    user = update.effective_user
    if update.callback_query:
        await safe_answer(update.callback_query)
        await _send_welcome_message(context, user, update.callback_query.message, lang, as_reply=False)
    else:
        await _send_welcome_message(context, user, update.message, lang, as_reply=True)
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for Support & Info button"""
    context.user_data.pop("order_draft", None)
    context.user_data.pop("topup_draft", None)

    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    await safe_reply_text(
        update.message,
        i18n.t(lang, "help_text"),
        reply_markup=keyboards.get_main_menu(update.effective_user.id, lang=lang),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def my_orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View previous orders of the user"""
    context.user_data.pop("order_draft", None)
    context.user_data.pop("topup_draft", None)

    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    user_id = update.effective_user.id
    orders = await database.get_user_orders(user_id, limit=10)

    if not orders:
        await safe_reply_text(
            update.message,
            i18n.t(lang, "no_orders"),
            reply_markup=keyboards.get_main_menu(user_id, lang=lang),
        )
        return ConversationHandler.END

    text = i18n.t(lang, "recent_orders_title")
    for o in orders:
        status_label = {
            "PENDING": i18n.t(lang, "status_pending"),
            "APPROVED": i18n.t(lang, "status_approved"),
            "REJECTED": i18n.t(lang, "status_rejected"),
        }.get(o.get("status"), o.get("status"))

        ocode = o.get("order_code") or f"ORD-{o.get('id', 0):04d}"
        curr = escape_md(i18n.format_currency_value(o.get("currency"), lang))
        pname = await i18n.smart_translate_title(o.get("product_name") or "", lang)

        text += i18n.t(
            lang,
            "order_item",
            code=ocode,
            product=escape_md(pname),
            qty=o.get("quantity", 1),
            total=o.get("total_price"),
            curr=curr,
            status=status_label,
            date=format_dt(o.get("created_at")),
        )

        if o.get("status") == "APPROVED" and o.get("delivered_links"):
            clean_links = str(o["delivered_links"]).replace("`", "")
            text += i18n.t(lang, "delivered_links_label", links=clean_links)
        elif o.get("status") == "REJECTED" and o.get("reject_reason"):
            tr_reason = await i18n.smart_translate(o["reject_reason"], lang)
            text += i18n.t(lang, "reject_reason_label", reason=escape_md(tr_reason))

        text += "───────────────\n"

    await safe_reply_text(
        update.message,
        text,
        reply_markup=keyboards.get_main_menu(user_id, lang=lang),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ==================== تدفق طلب الشراء (Order Flow) ====================

async def buy_subscription_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: Show 3-column brand grid to browse products"""
    context.user_data.pop("order_draft", None)
    context.user_data.pop("topup_draft", None)

    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    text = i18n.t(lang, "choose_brand")
    if update.callback_query:
        await safe_answer(update.callback_query)
        await safe_edit_text(
            update.callback_query.message,
            text,
            reply_markup=keyboards.get_categories_keyboard(lang=lang),
            parse_mode="Markdown",
        )
    else:
        await safe_reply_text(
            update.message,
            text,
            reply_markup=keyboards.get_categories_keyboard(lang=lang),
            parse_mode="Markdown",
        )
    return SELECTING_PRODUCT


async def _render_category_products_page(query, cat: str, page: int = 0, lang: str = "ar"):
    products = await database.get_products_by_category(cat, only_active=True)
    title = i18n.get_category_title(cat, lang=lang)

    if not products:
        text = i18n.t(lang, "no_products_in_cat", title=title)
        localized_products = products
    else:
        total_items = len(products)
        per_page = 6
        total_pages = max(1, (total_items + per_page - 1) // per_page)
        page = max(0, min(page, total_pages - 1))

        # Translate only the visible page items for fast responsiveness
        items = list(products.items())
        start_idx = page * per_page
        page_slice = items[start_idx : start_idx + per_page]
        tr_names = await asyncio.gather(
            *(i18n.smart_translate_title(p.get("name", ""), lang) for _, p in page_slice)
        )
        localized_products = dict(products)
        for (pid, p), tr_name in zip(page_slice, tr_names):
            p_copy = dict(p)
            p_copy["name"] = tr_name
            localized_products[pid] = p_copy

        page_note = i18n.t(lang, "cat_page_note", page=page + 1, total=total_pages) if total_pages > 1 else ""
        text = i18n.t(
            lang,
            "cat_products_header",
            title=title,
            page_note=page_note,
            total_items=total_items,
        )

    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_products_keyboard(
            localized_products, category=cat, page=page, per_page=6, lang=lang
        ),
        parse_mode="Markdown",
    )


async def category_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle choosing a category"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    query = update.callback_query
    await safe_answer(query)
    cat = query.data.split(":", 1)[1]
    await _render_category_products_page(query, cat=cat, page=0, lang=lang)
    return SELECTING_PRODUCT


async def category_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pagination inside a category"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    query = update.callback_query
    await safe_answer(query)
    parts = query.data.split(":")
    cat = parts[1] if len(parts) > 1 else "gemini"
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    await _render_category_products_page(query, cat=cat, page=page, lang=lang)
    return SELECTING_PRODUCT


async def back_to_categories_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to category selection"""
    query = update.callback_query
    await safe_answer(query)
    return await buy_subscription_entry(update, context)


async def product_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle product selection from inline keyboard"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    query = update.callback_query
    await safe_answer(query)

    data = query.data
    if data == "cancel_order":
        await safe_edit_text(query.message, i18n.t(lang, "session_cancelled"))
        return ConversationHandler.END

    product_id = data.split(":", 1)[1]
    product = await database.get_product_by_id(product_id)
    if not product or product.get("is_active") == 0:
        await safe_edit_text(query.message, i18n.t(lang, "product_unavailable"))
        return ConversationHandler.END

    cat = product.get("category", "other")
    price_usd = product.get("price_usd", 2.5)

    # Save raw product info to draft
    context.user_data["order_draft"] = {
        "product_id": product_id,
        "product_name": product["name"],
        "price": product["price"],
        "price_usd": price_usd,
        "category": cat,
    }

    tr_name, tr_desc = await asyncio.gather(
        i18n.smart_translate_title(product["name"], lang),
        i18n.smart_translate(product.get("description", ""), lang),
    )

    text = i18n.t(
        lang,
        "product_detail",
        name=escape_md(tr_name),
        price_dzd=product["price"],
        curr=i18n.currency_label(lang),
        price_usd=price_usd,
        desc=escape_md(tr_desc),
    )
    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_quantity_keyboard(
            product_id, category=cat, is_admin=(query.from_user.id in ADMIN_IDS), lang=lang
        ),
        parse_mode="Markdown",
    )
    return SELECTING_QUANTITY


async def product_instructions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display detailed product instructions when the customer clicks the blue Instructions button"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    query = update.callback_query
    await safe_answer(query, i18n.t(lang, "prod_inst_toast"))

    product_id = query.data.split(":", 1)[1]
    product = await database.get_product_by_id(product_id)
    if not product:
        await safe_edit_text(query.message, i18n.t(lang, "product_not_found"))
        return SELECTING_PRODUCT

    cat = product.get("category", "other")
    price_dzd = product.get("price", 0)
    price_usd = product.get("price_usd", 2.5)
    inst_text = (product.get("instructions") or "").strip()
    if not inst_text:
        inst_text = product.get("description") or i18n.t(lang, "default_inst_fallback")

    tr_name, tr_inst = await asyncio.gather(
        i18n.smart_translate_title(product["name"], lang),
        i18n.smart_translate(inst_text, lang),
    )

    text = i18n.t(
        lang,
        "prod_inst_view",
        name=escape_md(tr_name),
        price_dzd=price_dzd,
        curr=i18n.currency_label(lang),
        price_usd=price_usd,
        inst=escape_md(tr_inst),
    )
    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_product_instructions_back_keyboard(
            product_id, category=cat, is_admin=(query.from_user.id in ADMIN_IDS), lang=lang
        ),
        parse_mode="Markdown",
    )
    return SELECTING_QUANTITY


async def back_to_products_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to product list for the category"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    query = update.callback_query
    await safe_answer(query)
    parts = query.data.split(":")
    cat = parts[1] if len(parts) > 1 else "gemini"
    await _render_category_products_page(query, cat=cat, page=0, lang=lang)
    return SELECTING_PRODUCT


async def quantity_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quantity selection and prompt for payment method"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    query = update.callback_query
    await safe_answer(query)

    parts = query.data.split(":")
    product_id = parts[1]
    quantity = int(parts[2])

    draft = context.user_data.get("order_draft", {})
    if not draft or draft.get("product_id") != product_id:
        product = await database.get_product_by_id(product_id)
        if not product:
            await safe_edit_text(query.message, i18n.t(lang, "product_not_found"))
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
    tr_name = await i18n.smart_translate_title(draft["product_name"], lang)

    text = i18n.t(
        lang,
        "choose_payment",
        name=escape_md(tr_name),
        qty=quantity,
        total_dzd=price_dzd * quantity,
        curr=i18n.currency_label(lang),
        total_usd=round(price_usd * quantity, 2),
        bal_dzd=bal_dzd,
        bal_usd=f"{bal_usd:.2f}",
    )
    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_payment_methods_keyboard(
            product_id, quantity, price_usd=price_usd, price_dzd=price_dzd, lang=lang
        ),
        parse_mode="Markdown",
    )
    return SELECTING_PAYMENT


async def payment_method_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle chosen payment method (Wallet DZD/USD, BaridiMob, RedotPay, Bybit)"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

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
            await safe_edit_text(query.message, i18n.t(lang, "product_not_found"))
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

    tr_name = await i18n.smart_translate_title(draft["product_name"], lang)

    # --- Direct Wallet Payment Option ---
    if method_id in ("wallet_dzd", "wallet_usd"):
        wallet = await database.get_user_wallet(query.from_user.id)
        if method_id == "wallet_dzd":
            total_price = float(draft.get("price", 1000)) * quantity
            currency = "دينار"
            disp_curr = i18n.currency_label(lang)
            user_bal = float(wallet.get("balance_dzd", 0.0))
            method_name = i18n.t(lang, "wallet_dzd_name")
            db_method_name = "محفظة الدينار 👛"
        else:
            price_usd = float(draft.get("price_usd", 2.5))
            total_price = round(price_usd * quantity, 2)
            currency = "$"
            disp_curr = "$"
            user_bal = float(wallet.get("balance_usd", 0.0))
            method_name = i18n.t(lang, "wallet_usd_name")
            db_method_name = "محفظة الدولار 👛"

        draft["quantity"] = quantity
        draft["payment_method"] = method_id
        draft["payment_method_name"] = db_method_name
        draft["total_price"] = total_price
        draft["currency"] = currency
        context.user_data["order_draft"] = draft

        if user_bal < total_price:
            needed = round(total_price - user_bal, 2)
            insufficient_text = i18n.t(
                lang,
                "insufficient_balance",
                name=escape_md(tr_name),
                qty=quantity,
                total=total_price,
                curr=escape_md(disp_curr),
                method=method_name,
                bal=user_bal,
                needed=needed,
            )
            kb = InlineKeyboardMarkup([
                [keyboards._btn(i18n.t(lang, "btn_topup_now"), callback_data="wallet_menu", style="success")],
                [keyboards._btn(i18n.t(lang, "btn_choose_other_pay"), callback_data="change_payment_method", style="primary")],
                [keyboards._btn(i18n.t(lang, "btn_cancel_order"), callback_data="cancel_order")],
            ])
            await safe_edit_text(query.message, insufficient_text, reply_markup=kb, parse_mode="Markdown")
            return SELECTING_PAYMENT

        remaining = round(user_bal - total_price, 2)
        confirm_text = i18n.t(
            lang,
            "confirm_wallet_pay_text",
            name=escape_md(tr_name),
            qty=quantity,
            method=method_name,
            total=total_price,
            curr=escape_md(disp_curr),
            bal=user_bal,
            remaining=remaining,
        )
        await safe_edit_text(
            query.message,
            confirm_text,
            reply_markup=keyboards.get_wallet_pay_confirm_keyboard(product_id, lang=lang),
            parse_mode="Markdown",
        )
        return SELECTING_PAYMENT

    # --- Standard External Payment Methods (BaridiMob, RedotPay, Bybit) ---
    method = PAYMENT_METHODS.get(method_id, PAYMENT_METHODS["baridimob"])
    disp_method_name = i18n.get_payment_method_name(method_id, lang)

    if method_id == "baridimob":
        total_price = draft.get("price", 1000) * quantity
        currency = "دينار"
        disp_curr = i18n.currency_label(lang)
        instructions = await get_localized_payment_info(lang)
    else:
        price_usd = draft.get("price_usd", 2.5)
        total_price = round(price_usd * quantity, 2)
        currency = method.get("currency", "$")
        disp_curr = currency
        instructions = i18n.get_payment_method_details(method_id, lang)

    draft["quantity"] = quantity
    draft["payment_method"] = method_id
    draft["payment_method_name"] = method["name"]
    draft["total_price"] = total_price
    draft["currency"] = currency
    context.user_data["order_draft"] = draft

    summary_text = i18n.t(
        lang,
        "order_summary",
        name=escape_md(tr_name),
        qty=quantity,
        method=escape_md(disp_method_name),
        total=total_price,
        curr=escape_md(disp_curr),
        instructions=instructions,
    )

    await safe_edit_text(
        query.message,
        summary_text,
        reply_markup=keyboards.get_payment_confirm_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return AWAITING_RECEIPT


async def confirm_wallet_pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deduct balance from customer's wallet and fulfill order immediately"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    query = update.callback_query
    user = query.from_user
    draft = context.user_data.get("order_draft")
    if not draft:
        await safe_answer(query, i18n.t(lang, "session_expired"), show_alert=True)
        return ConversationHandler.END

    method_id = draft.get("payment_method", "wallet_dzd")
    total_price = float(draft.get("total_price", 0))
    currency = draft.get("currency", "دينار")
    disp_curr = i18n.format_currency_value(currency, lang)
    dzd_curr = i18n.currency_label(lang)
    product_id = draft["product_id"]
    quantity = int(draft.get("quantity", 1))

    wallet = await database.get_user_wallet(user.id)
    if method_id == "wallet_dzd":
        if float(wallet.get("balance_dzd", 0.0)) < total_price:
            await safe_answer(query, i18n.t(lang, "wallet_dzd_insufficient_toast"), show_alert=True)
            return SELECTING_PAYMENT
        await safe_answer(query, i18n.t(lang, "processing_wallet_order"))
        updated_wallet = await database.add_wallet_balance(
            user.id,
            amount_dzd=-total_price,
            amount_usd=0.0,
            user_name=user.full_name or "",
            user_username=f"@{user.username}" if user.username else "",
        )
    else:
        if float(wallet.get("balance_usd", 0.0)) < total_price:
            await safe_answer(query, i18n.t(lang, "wallet_usd_insufficient_toast"), show_alert=True)
            return SELECTING_PAYMENT
        await safe_answer(query, i18n.t(lang, "processing_wallet_order"))
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

    tr_name = await i18n.smart_translate_title(draft["product_name"], lang)
    context.user_data.pop("order_draft", None)

    if delivered_links:
        await adm.deliver_links_to_customer(context, order_obj, delivered_links)
        await safe_edit_text(
            query.message,
            i18n.t(
                lang,
                "wallet_instant_success",
                code=order_code,
                name=escape_md(tr_name),
                total=total_price,
                curr=escape_md(disp_curr),
                bal_dzd=updated_wallet["balance_dzd"],
                dzd_curr=dzd_curr,
                bal_usd=f"{updated_wallet['balance_usd']:.2f}",
            ),
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
        i18n.t(
            lang,
            "wallet_manual_pending",
            code=order_code,
            name=escape_md(tr_name),
            qty=quantity,
            total=total_price,
            curr=escape_md(disp_curr),
            bal_dzd=updated_wallet["balance_dzd"],
            dzd_curr=dzd_curr,
            bal_usd=f"{updated_wallet['balance_usd']:.2f}",
        ),
        parse_mode="Markdown",
    )
    await notify_admins_new_order(context, order_id, order_code, user, draft)
    return ConversationHandler.END


async def change_payment_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User wants to change chosen payment method"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    query = update.callback_query
    await safe_answer(query)

    draft = context.user_data.get("order_draft", {})
    product_id = draft.get("product_id")
    if not product_id:
        return await buy_subscription_entry(update, context)

    quantity = draft.get("quantity", 1)
    price_usd = draft.get("price_usd", 2.5)
    price_dzd = draft.get("price", 1000)
    tr_name = await i18n.smart_translate_title(draft.get("product_name", ""), lang)

    text = i18n.t(
        lang,
        "choose_payment_change",
        name=escape_md(tr_name),
        qty=quantity,
    )
    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_payment_methods_keyboard(
            product_id, quantity, price_usd=price_usd, price_dzd=price_dzd, lang=lang
        ),
        parse_mode="Markdown",
    )
    return SELECTING_PAYMENT


async def proceed_to_upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User confirmed they want to upload receipt"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    query = update.callback_query
    await safe_answer(query)

    await safe_edit_text(query.message, i18n.t(lang, "upload_receipt_prompt"), parse_mode="Markdown")
    await safe_reply_text(
        query.message,
        i18n.t(lang, "cancel_reply_hint"),
        reply_markup=keyboards.get_cancel_reply_keyboard(lang=lang),
    )
    return AWAITING_RECEIPT


async def receipt_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle receipt photo upload"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    message = update.message
    draft = context.user_data.get("order_draft")
    if not draft:
        await safe_reply_text(
            message,
            i18n.t(lang, "session_expired_restart"),
            reply_markup=keyboards.get_main_menu(update.effective_user.id, lang=lang),
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
        i18n.t(lang, "receipt_received_ask_ref"),
        reply_markup=keyboards.get_cancel_reply_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return AWAITING_TRANSFER_NO


async def transfer_number_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle transfer number text input"""
    import handlers_admin as adm
    if adm.has_active_admin_prompt(update.effective_user.id, context):
        await adm.handle_admin_text_input(update, context)
        return ConversationHandler.END

    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    text = (update.message.text or "").strip()
    draft = context.user_data.get("order_draft")
    if not draft:
        await safe_reply_text(
            update.message,
            i18n.t(lang, "session_expired_restart"),
            reply_markup=keyboards.get_main_menu(update.effective_user.id, lang=lang),
        )
        return ConversationHandler.END

    draft["transfer_number"] = text
    context.user_data["order_draft"] = draft
    return await finalize_order_submission(update, context)


async def finalize_order_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save order to DB and notify admin"""
    lang = await get_user_lang(update.effective_user.id, context) or "ar"
    draft = context.user_data.get("order_draft", {})
    user = update.effective_user

    pay_method = draft.get("payment_method_name", "بريدي موب")
    pay_method_id = draft.get("payment_method", "baridimob")
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

    tr_name = await i18n.smart_translate_title(draft["product_name"], lang)
    disp_pm = i18n.get_payment_method_name(pay_method_id, lang)
    disp_curr = i18n.format_currency_value(pay_curr, lang)

    customer_msg = i18n.t(
        lang,
        "order_submitted",
        code=order_code,
        name=escape_md(tr_name),
        qty=draft["quantity"],
        method=escape_md(disp_pm),
        total=draft["total_price"],
        curr=escape_md(disp_curr),
        ref=escape_md(draft.get("transfer_number")),
    )
    await safe_reply_text(
        update.message,
        customer_msg,
        reply_markup=keyboards.get_main_menu(user.id, lang=lang),
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

    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

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

    text = i18n.t(
        lang,
        "wallet_dashboard",
        name=escape_md(user.full_name),
        uid=user.id,
        bal_dzd=dzd_str,
        curr=i18n.currency_label(lang),
        bal_usd=usd_str,
    )

    if update.callback_query:
        await safe_answer(update.callback_query)
        await safe_edit_text(
            update.callback_query.message,
            text,
            reply_markup=keyboards.get_wallet_main_keyboard(lang=lang),
            parse_mode="Markdown",
        )
    else:
        await safe_reply_text(
            update.message,
            text,
            reply_markup=keyboards.get_wallet_main_keyboard(lang=lang),
            parse_mode="Markdown",
        )
    return SELECTING_PRODUCT


async def wallet_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show customer's recent wallet top-up requests"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    query = update.callback_query
    await safe_answer(query)
    user_id = query.from_user.id
    topups = await database.get_user_topups(user_id, limit=10)

    if not topups:
        text = i18n.t(lang, "no_topups")
    else:
        text = i18n.t(lang, "topups_history_title")
        for t_row in topups:
            st = t_row.get("status", "PENDING")
            st_badge = {
                "PENDING": i18n.t(lang, "topup_status_pending"),
                "APPROVED": i18n.t(lang, "topup_status_approved"),
                "REJECTED": i18n.t(lang, "topup_status_rejected"),
            }.get(st, st)
            tcode = t_row.get("topup_code") or f"TOP-{t_row['id']:04d}"
            curr_disp = i18n.format_currency_value(t_row.get("currency"), lang)
            text += i18n.t(
                lang,
                "topup_history_item",
                code=tcode,
                amount=t_row.get("amount"),
                curr=escape_md(curr_disp),
                method=escape_md(t_row.get("payment_method")),
                status=st_badge,
                date=format_dt(t_row.get("created_at")),
            )
            if st == "REJECTED" and t_row.get("reject_reason"):
                tr_reason = await i18n.smart_translate(t_row["reject_reason"], lang)
                text += i18n.t(lang, "topup_reject_reason", reason=escape_md(tr_reason))
            text += "───────────────\n"

    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_wallet_main_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return SELECTING_PRODUCT


async def wallet_topup_curr_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Customer selects currency to top up: 'dzd' or 'usd'"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    query = update.callback_query
    await safe_answer(query)

    curr_code = query.data.split(":", 1)[1].lower()
    currency_label = "دينار" if curr_code == "dzd" else "$"
    context.user_data["topup_draft"] = {
        "curr_code": curr_code,
        "currency": currency_label,
    }

    text = i18n.t(lang, "topup_prompt_dzd" if curr_code == "dzd" else "topup_prompt_usd")

    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_wallet_amount_presets_keyboard(curr_code, lang=lang),
        parse_mode="Markdown",
    )
    return AWAITING_TOPUP_AMOUNT


async def _show_topup_payment_step(message_or_query, context: ContextTypes.DEFAULT_TYPE, is_callback: bool, lang: str = "ar"):
    draft = context.user_data.get("topup_draft", {})
    curr_code = draft.get("curr_code", "dzd")
    amount = draft.get("amount", 0)

    if curr_code == "dzd":
        draft["payment_method"] = "بريدي موب (BaridiMob)"
        context.user_data["topup_draft"] = draft
        pay_info = await get_localized_payment_info(lang)
        text = i18n.t(
            lang,
            "topup_dzd_step",
            amount=amount,
            curr=i18n.currency_label(lang),
            pay_info=pay_info,
        )
        kb = keyboards.get_wallet_confirm_transfer_keyboard(lang=lang)
    else:
        text = i18n.t(lang, "topup_usd_choose_method", amount=amount)
        kb = keyboards.get_wallet_usd_methods_keyboard(amount, lang=lang)

    if is_callback:
        await safe_edit_text(message_or_query.message, text, reply_markup=kb, parse_mode="Markdown")
    else:
        await safe_reply_text(message_or_query, text, reply_markup=kb, parse_mode="Markdown")


async def wallet_amount_preset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Customer tapped a preset amount button for Wallet Top-Up"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

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
    await _show_topup_payment_step(query, context, is_callback=True, lang=lang)
    return AWAITING_TOPUP_AMOUNT


async def wallet_amount_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Customer typed a custom amount for Wallet Top-Up"""
    import handlers_admin as adm
    if adm.has_active_admin_prompt(update.effective_user.id, context):
        await adm.handle_admin_text_input(update, context)
        return ConversationHandler.END

    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    raw = (
        (update.message.text or "")
        .strip()
        .replace(",", ".")
        .replace("$", "")
        .replace("دج", "")
        .replace("DA", "")
        .replace("DZD", "")
        .strip()
    )
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
            i18n.t(lang, "topup_invalid_amount"),
            parse_mode="Markdown",
        )
        return AWAITING_TOPUP_AMOUNT

    draft["amount"] = round(amount, 2) if draft.get("curr_code") == "usd" else int(amount)
    context.user_data["topup_draft"] = draft
    await _show_topup_payment_step(update.message, context, is_callback=False, lang=lang)
    return AWAITING_TOPUP_AMOUNT


async def wallet_paym_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Customer selected USD payment method (RedotPay or Bybit) for Wallet Top-Up"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

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

    text = i18n.t(
        lang,
        "topup_usd_step",
        amount=amount,
        method=escape_md(method_info["name"]),
        details=i18n.get_payment_method_details(method_key, lang),
    )
    await safe_edit_text(
        query.message,
        text,
        reply_markup=keyboards.get_wallet_confirm_transfer_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return AWAITING_TOPUP_AMOUNT


async def wallet_upload_proof_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Customer clicked 'I transferred' and is ready to send receipt photo or transfer confirmation"""
    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    query = update.callback_query
    await safe_answer(query)
    draft = context.user_data.get("topup_draft")
    if not draft or not draft.get("amount"):
        return await wallet_command(update, context)

    disp_curr = i18n.format_currency_value(draft.get("currency"), lang)
    text = i18n.t(
        lang,
        "topup_upload_prompt",
        amount=draft["amount"],
        curr=escape_md(disp_curr),
    )
    await safe_edit_text(query.message, text, parse_mode="Markdown")
    await safe_reply_text(
        query.message,
        i18n.t(lang, "topup_upload_hint"),
        reply_markup=keyboards.get_cancel_reply_keyboard(lang=lang),
    )
    return AWAITING_TOPUP_PROOF


async def wallet_proof_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo OR text proof sent by customer for Wallet Top-Up"""
    import handlers_admin as adm
    if update.message and update.message.text and adm.has_active_admin_prompt(update.effective_user.id, context):
        await adm.handle_admin_text_input(update, context)
        return ConversationHandler.END

    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
        return ConversationHandler.END

    message = update.message
    user = update.effective_user
    draft = context.user_data.get("topup_draft")
    if not draft or not draft.get("amount"):
        await safe_reply_text(
            message,
            i18n.t(lang, "topup_session_expired"),
            reply_markup=keyboards.get_main_menu(user.id, lang=lang),
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
    disp_curr = i18n.format_currency_value(currency, lang)

    cust_msg = i18n.t(
        lang,
        "topup_submitted",
        code=topup_code,
        amount=amount,
        curr=escape_md(disp_curr),
        method=escape_md(pay_method),
        ref=escape_md(transfer_number),
    )
    await safe_reply_text(
        message,
        cust_msg,
        reply_markup=keyboards.get_main_menu(user.id, lang=lang),
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
    user = update.effective_user
    lang = (await get_user_lang(user.id, context)) if user else "ar"
    lang = lang or "ar"

    if update.callback_query:
        await safe_answer(update.callback_query)
        await safe_edit_text(update.callback_query.message, i18n.t(lang, "session_cancelled"))
    else:
        await safe_reply_text(
            update.message,
            i18n.t(lang, "session_cancelled_main"),
            reply_markup=keyboards.get_main_menu(user.id, lang=lang),
        )
    return ConversationHandler.END


# ==================== خدمة ودعم العملاء الواردة (Inbound Customer Support) ====================

async def handle_customer_inbound_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages from customers outside of active order conversations"""
    user = update.effective_user
    if not user or user.id in ADMIN_IDS:
        return

    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
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
        f"📩 **رسالة جديدة من عميل ({lang.upper()}):**\n"
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
        i18n.t(lang, "support_text_received"),
        parse_mode="Markdown",
    )


async def handle_customer_inbound_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles photos sent by customers outside of active order conversations"""
    user = update.effective_user
    if not user or user.id in ADMIN_IDS:
        return

    lang = await ensure_ready(update, context, check_join=True)
    if not lang:
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
        f"📷 **صورة واردة من عميل ({lang.upper()}):**\n"
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
        i18n.t(lang, "support_photo_received"),
        parse_mode="Markdown",
    )
