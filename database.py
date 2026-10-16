from contextlib import asynccontextmanager
import aiosqlite
import datetime
from config import DB_PATH, DEFAULT_PAYMENT_INFO, PROOF_CHANNEL


@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT UNIQUE,
                user_id INTEGER,
                user_name TEXT,
                user_username TEXT,
                product_id TEXT,
                product_name TEXT,
                quantity INTEGER,
                total_price REAL,
                transfer_number TEXT,
                receipt_file_id TEXT,
                status TEXT DEFAULT 'PENDING',
                delivered_links TEXT DEFAULT '',
                reject_reason TEXT DEFAULT '',
                payment_method TEXT DEFAULT 'بريدي موب',
                currency TEXT DEFAULT 'دينار',
                created_at TEXT,
                updated_at TEXT
            );
        """)

        # Schema migrations for existing DB
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'بريدي موب'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN currency TEXT DEFAULT 'دينار'")
        except Exception:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS links_stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT,
                link_url TEXT,
                is_used INTEGER DEFAULT 0,
                order_id INTEGER NULL,
                used_by_user_id INTEGER NULL,
                added_at TEXT,
                used_at TEXT NULL
            );
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                price_usd REAL DEFAULT 2.5,
                category TEXT DEFAULT 'other',
                description TEXT DEFAULT '',
                supplier_product_id INTEGER NULL,
                is_active INTEGER DEFAULT 1
            );
        """)

        # Migrations for existing DB
        try:
            await db.execute("ALTER TABLE products ADD COLUMN category TEXT DEFAULT 'other'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE products ADD COLUMN price_usd REAL DEFAULT 2.5")
        except Exception:
            pass

        # Seed products if not exists
        initial_products = [
            # 1. Gemini
            ("gemini_18m", "جيميني برو 18 شهر", 1100.0, 2.5, "gemini", "💎 اشتراك Google Gemini Pro أصلي لمدة 18 شهر بضمان كامل مع ميزات AI المتقدمة و2TB تخزين سحابي.", 14, 1),
            ("gemini_12m", "جيميني برو 12 شهر", 1000.0, 2.5, "gemini", "💎 اشتراك Google Gemini Pro أصلي لمدة 12 شهر بضمان كامل مع ميزات AI المتقدمة و2TB تخزين سحابي.", 14, 1),
            
            # 2. ChatGPT
            ("chatgpt_plus_4m", "ChatGPT Plus (4 أشهر)", 6000.0, 25.0, "chatgpt", "🤖 اشتراك شات جي بي تي بلس الأصلي لمدة 4 أشهر كاملة مع ميزات GPT-4o وتوليد الصور المتقدمة.", 90, 1),
            ("codex_api_10m", "Codex API (10M Tokens)", 1000.0, 2.5, "chatgpt", "💻 رصيد 10 مليون توكن API لـ OpenAI Codex للمطورين والمبرمجين مع ضمان كامل.", 36, 1),
            
            # 3. Other Products
            ("duolingo_12m", "Duolingo Super (12 شهر)", 600.0, 1.5, "other", "🦉 اشتراك دوولينجو سوبر لمدة سنة كاملة بدون إعلانات مع قلوب غير محدودة لتعلم اللغات.", 74, 1),
            ("adobe_express_12m", "Adobe Express (12 شهر)", 500.0, 1.5, "other", "🎨 اشتراك أدوبي إكسبريس بريميوم لمدة سنة كاملة للتصميم وصناعة المحتوى مع آلاف القوالب.", None, 1),
            ("apple_music_5m", "Apple Music (5 أشهر)", 500.0, 1.5, "other", "🎵 اشتراك أبل ميوزك أصلي لمدة 5 أشهر مع جودة صوت فائقة وبدون إعلانات.", None, 1),
            ("capcut_pro_30d", "CapCut Pro (30 يوم)", 800.0, 2.5, "other", "🎬 اشتراك كاب كت برو لمدة شهر لمونتاج وتعديل الفيديوهات باحترافية وبدون علامة مائية.", 21, 1),
            ("claude_api_10m", "Claude API (10M Tokens)", 1000.0, 2.5, "other", "⚡️ رصيد 10 مليون توكن API لـ Claude 3.5 Sonnet / Opus للمطورين مع ضمان كامل.", 32, 1),
        ]

        for p in initial_products:
            await db.execute("""
                INSERT INTO products (id, name, price, price_usd, category, description, supplier_product_id, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    price_usd=excluded.price_usd,
                    category=excluded.category,
                    description=excluded.description,
                    supplier_product_id=excluded.supplier_product_id
            """, p)

        # Set default payment info if not exists
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('payment_info', ?)",
            (DEFAULT_PAYMENT_INFO,),
        )
        await db.commit()


# ==================== إدارة المنتجات والأسعار (Products) ====================

async def get_all_products(only_active: bool = True) -> dict[str, dict]:
    """Fetch all products as a dictionary {product_id: product_data}"""
    async with get_db() as db:
        query = "SELECT * FROM products WHERE is_active = 1 ORDER BY price DESC" if only_active else "SELECT * FROM products ORDER BY price DESC"
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
        return {r["id"]: dict(r) for r in rows}


async def get_products_by_category(category: str, only_active: bool = True) -> dict[str, dict]:
    """Fetch products filtered by category ('gemini', 'chatgpt', 'other')"""
    async with get_db() as db:
        query = "SELECT * FROM products WHERE category = ? AND is_active = 1 ORDER BY price DESC" if only_active else "SELECT * FROM products WHERE category = ? ORDER BY price DESC"
        cursor = await db.execute(query, (category,))
        rows = await cursor.fetchall()
        return {r["id"]: dict(r) for r in rows}



async def get_product_by_id(product_id: str) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_product_price(product_id: str, new_price: float):
    async with get_db() as db:
        await db.execute("UPDATE products SET price = ? WHERE id = ?", (new_price, product_id))
        await db.commit()


async def add_new_product(
    product_id: str,
    name: str,
    price: float,
    description: str = "",
    supplier_product_id: int | None = None,
):
    async with get_db() as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO products (id, name, price, description, supplier_product_id, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (product_id, name, price, description, supplier_product_id),
        )
        await db.commit()


async def toggle_product_active(product_id: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute("SELECT is_active FROM products WHERE id = ?", (product_id,))
        row = await cursor.fetchone()
        if row:
            new_status = 0 if row["is_active"] == 1 else 1
            await db.execute("UPDATE products SET is_active = ? WHERE id = ?", (new_status, product_id))
            await db.commit()
            return bool(new_status)
        return False


# ==================== روابط المخزن (Stock) ====================

async def add_links_to_stock(product_id: str, links: list[str]) -> int:
    added = 0
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with get_db() as db:
        for link in links:
            clean_link = link.strip()
            if clean_link:
                await db.execute(
                    """
                    INSERT INTO links_stock (product_id, link_url, is_used, added_at)
                    VALUES (?, ?, 0, ?)
                    """,
                    (product_id, clean_link, now),
                )
                added += 1
        await db.commit()
    return added


async def get_stock_counts() -> dict:
    """Returns {product_id: count of unused links}"""
    counts = {}
    async with get_db() as db:
        cursor = await db.execute("""
            SELECT product_id, COUNT(*) as cnt 
            FROM links_stock 
            WHERE is_used = 0 
            GROUP BY product_id
        """)
        rows = await cursor.fetchall()
        for r in rows:
            counts[r["product_id"]] = r["cnt"]
    return counts


async def get_available_links_from_stock(product_id: str, count: int) -> list[dict]:
    """Fetch available links without marking them yet"""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, link_url 
            FROM links_stock 
            WHERE product_id = ? AND is_used = 0 
            ORDER BY id ASC 
            LIMIT ?
            """,
            (product_id, count),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def consume_stock_links(link_ids: list[int], order_id: int, user_id: int):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with get_db() as db:
        for lid in link_ids:
            await db.execute(
                """
                UPDATE links_stock 
                SET is_used = 1, order_id = ?, used_by_user_id = ?, used_at = ?
                WHERE id = ?
                """,
                (order_id, user_id, now, lid),
            )
        await db.commit()


# ==================== إدارة الطلبات (Orders) ====================

async def create_order(
    user_id: int,
    user_name: str,
    user_username: str,
    product_id: str,
    product_name: str,
    quantity: int,
    total_price: float,
    transfer_number: str,
    receipt_file_id: str,
    payment_method: str = "بريدي موب",
    currency: str = "دينار",
) -> tuple[int, str]:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO orders (
                user_id, user_name, user_username, product_id, product_name,
                quantity, total_price, transfer_number, receipt_file_id,
                payment_method, currency,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """,
            (
                user_id,
                user_name,
                user_username,
                product_id,
                product_name,
                quantity,
                total_price,
                transfer_number,
                receipt_file_id,
                payment_method,
                currency,
                now,
                now,
            ),
        )
        order_id = cursor.lastrowid
        order_code = f"ORD-{order_id:04d}"
        await db.execute(
            "UPDATE orders SET order_code = ? WHERE id = ?",
            (order_code, order_id),
        )
        await db.commit()
        return order_id, order_code


async def get_order_by_id(order_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_pending_orders(limit: int = 10) -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM orders WHERE status = 'PENDING' ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_user_orders(user_id: int, limit: int = 5) -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def mark_order_approved(order_id: int, links: list[str]) -> bool:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    links_str = "\n".join(links)
    async with get_db() as db:
        await db.execute(
            """
            UPDATE orders 
            SET status = 'APPROVED', delivered_links = ?, updated_at = ?
            WHERE id = ?
            """,
            (links_str, now, order_id),
        )
        await db.commit()
    return True


async def mark_order_rejected(order_id: int, reason: str = "") -> bool:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with get_db() as db:
        await db.execute(
            """
            UPDATE orders 
            SET status = 'REJECTED', reject_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (reason, now, order_id),
        )
        await db.commit()
    return True


# ==================== الإحصائيات (Stats) ====================

async def get_admin_stats() -> dict:
    async with get_db() as db:
        # Total orders
        cur = await db.execute("SELECT COUNT(*) as c FROM orders")
        total_orders = (await cur.fetchone())["c"]

        # Pending orders
        cur = await db.execute("SELECT COUNT(*) as c FROM orders WHERE status = 'PENDING'")
        pending_orders = (await cur.fetchone())["c"]

        # Approved orders
        cur = await db.execute("SELECT COUNT(*) as c FROM orders WHERE status = 'APPROVED'")
        approved_orders = (await cur.fetchone())["c"]

        # Rejected orders
        cur = await db.execute("SELECT COUNT(*) as c FROM orders WHERE status = 'REJECTED'")
        rejected_orders = (await cur.fetchone())["c"]

        # Total revenue
        cur = await db.execute("SELECT SUM(total_price) as s FROM orders WHERE status = 'APPROVED'")
        revenue_row = await cur.fetchone()
        total_revenue = revenue_row["s"] if revenue_row and revenue_row["s"] is not None else 0.0

        # Unique customers
        cur = await db.execute("SELECT COUNT(DISTINCT user_id) as c FROM orders")
        unique_customers = (await cur.fetchone())["c"]

        return {
            "total_orders": total_orders,
            "pending_orders": pending_orders,
            "approved_orders": approved_orders,
            "rejected_orders": rejected_orders,
            "total_revenue": total_revenue,
            "unique_customers": unique_customers,
        }


# ==================== الإعدادات (Settings) ====================

async def get_payment_info() -> str:
    async with get_db() as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = 'payment_info'")
        row = await cur.fetchone()
        if row and row["value"]:
            return row["value"]
    return DEFAULT_PAYMENT_INFO


async def update_payment_info(new_info: str):
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('payment_info', ?)",
            (new_info,),
        )
        await db.commit()


async def get_proof_channel() -> str:
    """Fetch configured proofs channel (username like @channel or chat_id)"""
    async with get_db() as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = 'proof_channel'")
        row = await cur.fetchone()
        if row and row["value"]:
            return row["value"].strip()
    return PROOF_CHANNEL.strip() if PROOF_CHANNEL else ""


async def update_proof_channel(new_channel: str):
    """Save or update configured proofs channel"""
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('proof_channel', ?)",
            (new_channel.strip(),),
        )
        await db.commit()

