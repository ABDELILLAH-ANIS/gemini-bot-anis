import sys
import asyncio
import logging

import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
from telegram import (
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
    MenuButtonCommands,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from config import BOT_TOKEN, ADMIN_IDS
import database
import supplier_api
import handlers_customer as cust
import handlers_admin as adm

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def setup_bot_menu_commands(bot):
    """Configure the corner Telegram Menu button with localized shortcut commands (AR / EN / FR)"""
    commands_by_lang = {
        "ar": [
            BotCommand("start", "🏠 القائمة الرئيسية وبداية البوت"),
            BotCommand("products", "🛒 تصفح المنتجات والعلامات التجارية"),
            BotCommand("wallet", "👛 محفظتي وشحن الرصيد (Top Up)"),
            BotCommand("my_orders", "📦 طلباتي السابقة"),
            BotCommand("lang", "🌐 تغيير اللغة (AR / EN / FR)"),
            BotCommand("help", "📘 الدعم والتعليمات"),
            BotCommand("cancel", "❌ إلغاء العملية الحالية"),
        ],
        "en": [
            BotCommand("start", "🏠 Main Menu & Start"),
            BotCommand("products", "🛒 Browse Products & Brands"),
            BotCommand("wallet", "👛 My Wallet & Top Up"),
            BotCommand("my_orders", "📦 My Orders"),
            BotCommand("lang", "🌐 Change Language (AR / EN / FR)"),
            BotCommand("help", "📘 Support & Info"),
            BotCommand("cancel", "❌ Cancel Current Action"),
        ],
        "fr": [
            BotCommand("start", "🏠 Menu Principal"),
            BotCommand("products", "🛒 Parcourir les produits"),
            BotCommand("wallet", "👛 Mon Portefeuille (Top Up)"),
            BotCommand("my_orders", "📦 Mes Commandes"),
            BotCommand("lang", "🌐 Changer de langue (AR / EN / FR)"),
            BotCommand("help", "📘 Support & Aide"),
            BotCommand("cancel", "❌ Annuler l'opération"),
        ],
    }
    admin_commands = commands_by_lang["ar"] + [
        BotCommand("admin", "⚙️ لوحة تحكم الإدارة"),
    ]
    try:
        await bot.set_my_commands(commands_by_lang["ar"], scope=BotCommandScopeDefault())
        for lc, cmds in commands_by_lang.items():
            try:
                await bot.set_my_commands(cmds, scope=BotCommandScopeDefault(), language_code=lc)
            except Exception:
                pass
        for admin_id in ADMIN_IDS:
            try:
                await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception:
                pass
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Corner Menu button and localized bot commands configured successfully.")
    except Exception as e:
        logger.warning(f"Failed to set bot menu commands: {e}")


async def post_init(application):
    """Run database initialization, supplier mapping cache, and Menu button setup on startup"""
    logger.info("Initializing database...")
    await database.init_db()
    logger.info("Database initialized successfully.")

    logger.info("Loading dynamic supplier mappings from database...")
    await supplier_api.load_dynamic_mappings_from_db()
    logger.info("Dynamic supplier mappings loaded successfully.")

    await setup_bot_menu_commands(application.bot)


async def periodic_supplier_sync_job(context: ContextTypes.DEFAULT_TYPE):
    """Periodically check supplier APIs for newly added products (runs every 30 minutes)"""
    try:
        logger.info("Running scheduled supplier API product synchronization...")
        new_items = await supplier_api.sync_new_supplier_products(bot=context.bot)
        if new_items:
            logger.info(f"Scheduled sync discovered and imported {len(new_items)} new supplier products!")
    except Exception as e:
        logger.error(f"Error during scheduled supplier sync job: {e}", exc_info=True)


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot is alive and running 24/7!")

    def log_message(self, format, *args):
        # Silence access logs to keep terminal output clean
        pass


def start_health_server():
    """Lightweight HTTP server so Render Web Service detects an open port"""
    port = int(os.environ.get("PORT", 8080))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logger.info(f"Health check HTTP server started on port {port}")
        server.serve_forever()
    except Exception as e:
        logger.warning(f"Could not start health check server on port {port}: {e}")


def main():
    if not BOT_TOKEN:
        print("\n" + "=" * 60)
        print("⚠️ خطأ: لم يتم ضبط BOT_TOKEN!")
        print("يرجى فتح ملف .env وإضافة توكن البوت الخاص بك من @BotFather")
        print("مثال: BOT_TOKEN=123456789:ABCdefGhIJKlmnoPQRstuVWXyz")
        print("=" * 60 + "\n")
        return

    # Start HTTP health check server for Render/cloud deployment
    threading.Thread(target=start_health_server, daemon=True).start()

    # Build Application
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Schedule periodic supplier API scan (every 30 minutes, first run 30s after start)
    if app.job_queue:
        app.job_queue.run_repeating(periodic_supplier_sync_job, interval=1800, first=30)
        logger.info("Scheduled periodic supplier product sync every 30 minutes.")
    else:
        logger.warning("JobQueue is not enabled; automatic supplier sync will not run in background.")

    # 0. Admin inline callbacks (highest priority so admin buttons always work)
    app.add_handler(CallbackQueryHandler(adm.admin_callback_dispatcher, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(cust.noop_callback, pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(cust.language_selected_callback, pattern="^lang:"))
    app.add_handler(CallbackQueryHandler(cust.language_command, pattern="^open_lang_menu$"))
    app.add_handler(CallbackQueryHandler(cust.check_join_callback, pattern="^check_join$"))
    app.add_handler(CommandHandler("skip_reason", adm.handle_admin_text_input))
    app.add_handler(CommandHandler("cancel_action", adm.handle_admin_text_input))

    # Common inline callbacks for customer order & wallet flow
    common_order_callbacks = [
        CallbackQueryHandler(cust.category_selected_callback, pattern="^cat:"),
        CallbackQueryHandler(cust.category_page_callback, pattern="^cat_page:"),
        CallbackQueryHandler(cust.back_to_categories_callback, pattern="^back_to_categories$"),
        CallbackQueryHandler(cust.back_to_products_callback, pattern="^back_to_prods:"),
        CallbackQueryHandler(cust.product_selected_callback, pattern="^prod:"),
        CallbackQueryHandler(cust.product_instructions_callback, pattern="^prod_inst:"),
        CallbackQueryHandler(cust.quantity_selected_callback, pattern="^qty:"),
        CallbackQueryHandler(cust.payment_method_selected_callback, pattern="^paym:"),
        CallbackQueryHandler(cust.confirm_wallet_pay_callback, pattern="^confirm_wallet_pay$"),
        CallbackQueryHandler(cust.proceed_to_upload_callback, pattern="^upload_receipt$"),
        CallbackQueryHandler(cust.change_payment_method_callback, pattern="^change_payment_method$"),
        CallbackQueryHandler(cust.wallet_command, pattern="^wallet_menu$"),
        CallbackQueryHandler(cust.wallet_history_callback, pattern="^wallet_history$"),
        CallbackQueryHandler(cust.wallet_topup_curr_callback, pattern="^wallet_topup_curr:"),
        CallbackQueryHandler(cust.wallet_amount_preset_callback, pattern="^wallet_amt:"),
        CallbackQueryHandler(cust.wallet_paym_callback, pattern="^wallet_paym:"),
        CallbackQueryHandler(cust.wallet_upload_proof_callback, pattern="^wallet_upload_proof$"),
        CallbackQueryHandler(cust.cancel_order, pattern="^cancel_order$"),
    ]

    buy_regex = r"^(?:🛒 )?(?:شراء اشتراك|Buy Subscription|Acheter un abonnement)$"
    wallet_regex = r"(?:محفظتي|My Wallet|Mon Portefeuille|Top Up)"
    orders_regex = r"^(?:📦 )?(?:طلباتي السابقة|طلباتي|My Orders|Mes Commandes)$"
    help_regex = r"^(?:📘 )?(?:الدعم والتعليمات|Support & Info|Support & Aide)$"
    lang_regex = r"^(?:🌐 )?(?:اللغة \(Language\)|تغيير اللغة|Language|Langue)$"
    cancel_regex = r"^(?:❌ )?(?:إلغاء(?: العملية)?|Cancel|Annuler)$"
    admin_regex = r"لوحة تحكم الإدارة"

    menu_regex = (
        r"(شراء اشتراك|Buy Subscription|Acheter un abonnement|"
        r"محفظتي|My Wallet|Mon Portefeuille|Top Up|"
        r"طلباتي|My Orders|Mes Commandes|"
        r"الدعم والتعليمات|Support & Info|Support & Aide|"
        r"اللغة \(Language\)|تغيير اللغة|^Language$|^Langue$|"
        r"إلغاء(?: العملية)?|^Cancel$|^Annuler$|"
        r"لوحة تحكم الإدارة)"
    )

    # 1. Customer Order & Wallet Conversation
    order_conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(buy_regex), cust.buy_subscription_entry),
            MessageHandler(filters.Regex(wallet_regex), cust.wallet_command),
            CommandHandler(["products", "buy"], cust.buy_subscription_entry),
            CommandHandler("wallet", cust.wallet_command),
            *common_order_callbacks,
        ],
        states={
            cust.SELECTING_PRODUCT: [*common_order_callbacks],
            cust.SELECTING_QUANTITY: [*common_order_callbacks],
            cust.SELECTING_PAYMENT: [*common_order_callbacks],
            cust.AWAITING_RECEIPT: [
                *common_order_callbacks,
                MessageHandler(filters.PHOTO, cust.receipt_photo_received),
                MessageHandler(filters.Regex(cancel_regex), cust.cancel_order),
            ],
            cust.AWAITING_TRANSFER_NO: [
                *common_order_callbacks,
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & ~filters.Regex(menu_regex),
                    cust.transfer_number_received,
                ),
                MessageHandler(filters.Regex(cancel_regex), cust.cancel_order),
            ],
            cust.AWAITING_TOPUP_AMOUNT: [
                *common_order_callbacks,
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & ~filters.Regex(menu_regex),
                    cust.wallet_amount_text_received,
                ),
                MessageHandler(filters.Regex(cancel_regex), cust.cancel_order),
            ],
            cust.AWAITING_TOPUP_PROOF: [
                *common_order_callbacks,
                MessageHandler(filters.PHOTO, cust.wallet_proof_received),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & ~filters.Regex(menu_regex),
                    cust.wallet_proof_received,
                ),
                MessageHandler(filters.Regex(cancel_regex), cust.cancel_order),
            ],
        },
        fallbacks=[
            CommandHandler("start", cust.start_command),
            CommandHandler(["products", "buy"], cust.buy_subscription_entry),
            CommandHandler("help", cust.help_command),
            CommandHandler("my_orders", cust.my_orders_command),
            CommandHandler("wallet", cust.wallet_command),
            CommandHandler(["lang", "language"], cust.language_command),
            CommandHandler("admin", adm.admin_panel_command),
            CommandHandler("cancel", cust.cancel_order),
            CallbackQueryHandler(cust.cancel_order, pattern="^cancel_order$"),
            CallbackQueryHandler(cust.language_selected_callback, pattern="^lang:"),
            CallbackQueryHandler(cust.language_command, pattern="^open_lang_menu$"),
            CallbackQueryHandler(cust.check_join_callback, pattern="^check_join$"),
            MessageHandler(filters.Regex(cancel_regex), cust.cancel_order),
            MessageHandler(filters.Regex(buy_regex), cust.buy_subscription_entry),
            MessageHandler(filters.Regex(wallet_regex), cust.wallet_command),
            MessageHandler(filters.Regex(orders_regex), cust.my_orders_command),
            MessageHandler(filters.Regex(help_regex), cust.help_command),
            MessageHandler(filters.Regex(lang_regex), cust.language_command),
            MessageHandler(filters.Regex(admin_regex), adm.admin_panel_command),
        ],
        allow_reentry=True,
    )

    # Register Order Conversation
    app.add_handler(order_conv_handler)

    # 2. General Customer Commands
    app.add_handler(CommandHandler("start", cust.start_command))
    app.add_handler(CommandHandler(["products", "buy"], cust.buy_subscription_entry))
    app.add_handler(CommandHandler("help", cust.help_command))
    app.add_handler(CommandHandler("my_orders", cust.my_orders_command))
    app.add_handler(CommandHandler("wallet", cust.wallet_command))
    app.add_handler(CommandHandler(["lang", "language"], cust.language_command))
    app.add_handler(CommandHandler("cancel", cust.cancel_order))
    app.add_handler(MessageHandler(filters.Regex(wallet_regex), cust.wallet_command))
    app.add_handler(MessageHandler(filters.Regex(orders_regex), cust.my_orders_command))
    app.add_handler(MessageHandler(filters.Regex(help_regex), cust.help_command))
    app.add_handler(MessageHandler(filters.Regex(lang_regex), cust.language_command))
    app.add_handler(MessageHandler(filters.Regex(cancel_regex), cust.cancel_order))

    # 3. Admin Panel and Management
    app.add_handler(CommandHandler("admin", adm.admin_panel_command))
    app.add_handler(MessageHandler(filters.Regex(r"لوحة تحكم الإدارة"), adm.admin_panel_command))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_IDS),
            adm.handle_admin_text_input,
        )
    )

    # 4. Customer Support Inbound Handlers (outside active order flow)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.User(ADMIN_IDS),
            cust.handle_customer_inbound_message,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.PHOTO & ~filters.User(ADMIN_IDS),
            cust.handle_customer_inbound_photo,
        )
    )

    print("\n" + "=" * 60)
    print("🚀 بوت متجر اشتراكات Gemini يعمل بنجاح الآن...")
    print("اضغط Ctrl + C لإيقاف البوت.")
    print("=" * 60 + "\n")

    # Start Polling
    app.run_polling()


if __name__ == "__main__":
    main()
