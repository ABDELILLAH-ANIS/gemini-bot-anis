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


async def post_init(application):
    """Run database initialization and supplier mapping cache on startup"""
    logger.info("Initializing database...")
    await database.init_db()
    logger.info("Database initialized successfully.")

    logger.info("Loading dynamic supplier mappings from database...")
    await supplier_api.load_dynamic_mappings_from_db()
    logger.info("Dynamic supplier mappings loaded successfully.")


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

    # 1. Customer Order Conversation
    order_conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"شراء اشتراك"), cust.buy_subscription_entry),
            CommandHandler("buy", cust.buy_subscription_entry),
        ],
        states={
            cust.SELECTING_PRODUCT: [
                CallbackQueryHandler(cust.category_selected_callback, pattern="^cat:"),
                CallbackQueryHandler(cust.back_to_categories_callback, pattern="^back_to_categories$"),
                CallbackQueryHandler(cust.product_selected_callback, pattern="^prod:"),
                CallbackQueryHandler(cust.cancel_order, pattern="^cancel_order$"),
            ],
            cust.SELECTING_QUANTITY: [
                CallbackQueryHandler(cust.quantity_selected_callback, pattern="^qty:"),
                CallbackQueryHandler(cust.back_to_products_callback, pattern="^back_to_prods:"),
                CallbackQueryHandler(cust.back_to_categories_callback, pattern="^back_to_categories$"),
                CallbackQueryHandler(cust.cancel_order, pattern="^cancel_order$"),
            ],
            cust.SELECTING_PAYMENT: [
                CallbackQueryHandler(cust.payment_method_selected_callback, pattern="^paym:"),
                CallbackQueryHandler(cust.product_selected_callback, pattern="^prod:"),
                CallbackQueryHandler(cust.cancel_order, pattern="^cancel_order$"),
            ],
            cust.AWAITING_RECEIPT: [
                CallbackQueryHandler(cust.proceed_to_upload_callback, pattern="^upload_receipt$"),
                CallbackQueryHandler(cust.change_payment_method_callback, pattern="^change_payment_method$"),
                CallbackQueryHandler(cust.cancel_order, pattern="^cancel_order$"),
                MessageHandler(filters.PHOTO, cust.receipt_photo_received),
                MessageHandler(filters.Regex(r"إلغاء"), cust.cancel_order),
            ],
            cust.AWAITING_TRANSFER_NO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & ~filters.Regex(r"إلغاء"),
                    cust.transfer_number_received,
                ),
                MessageHandler(filters.Regex(r"إلغاء"), cust.cancel_order),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cust.cancel_order),
            CallbackQueryHandler(cust.cancel_order, pattern="^cancel_order$"),
            MessageHandler(filters.Regex(r"إلغاء"), cust.cancel_order),
        ],
        allow_reentry=True,
    )

    # Register Order Conversation first
    app.add_handler(order_conv_handler)

    # 2. General Customer Commands
    app.add_handler(CommandHandler("start", cust.start_command))
    app.add_handler(CommandHandler("help", cust.help_command))
    app.add_handler(CommandHandler("my_orders", cust.my_orders_command))
    app.add_handler(MessageHandler(filters.Regex(r"طلباتي"), cust.my_orders_command))
    app.add_handler(MessageHandler(filters.Regex(r"الدعم|التعليمات"), cust.help_command))

    # 3. Admin Panel and Management
    app.add_handler(CommandHandler("admin", adm.admin_panel_command))
    app.add_handler(MessageHandler(filters.Regex(r"لوحة تحكم الإدارة"), adm.admin_panel_command))
    app.add_handler(CallbackQueryHandler(adm.admin_callback_dispatcher, pattern="^adm_"))
    
    # Admin text handler (for manual links, reject reasons, stock additions, payment edits, custom messaging)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_IDS),
            adm.handle_admin_text_input,
        )
    )
    app.add_handler(CommandHandler("skip_reason", adm.handle_admin_text_input))
    app.add_handler(CommandHandler("cancel_action", adm.handle_admin_text_input))

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
