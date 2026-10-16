import os
import datetime
import logging
from contextlib import asynccontextmanager
import aiosqlite
import httpx

from config import (
    DB_PATH,
    DEFAULT_PAYMENT_INFO,
    PROOF_CHANNEL,
    SUPABASE_URL,
    SUPABASE_KEY,
)

logger = logging.getLogger(__name__)

# ==================== Supabase REST API Helper ====================

def _get_supabase_headers(prefer: str | None = None) -> dict:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


async def _sb_request(method: str, endpoint: str, params: dict | None = None, json_data=None, prefer: str | None = None):
    """Executes an async request to Supabase PostgREST API with timeout and error handling"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None

    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    headers = _get_supabase_headers(prefer)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, params=params, json=json_data, headers=headers)
            if resp.status_code in (200, 201):
                try:
                    return resp.json()
                except Exception:
                    return resp.text
            elif resp.status_code == 204:
                return True
            else:
                logger.warning(f"Supabase {method} {endpoint} returned status {resp.status_code}: {resp.text}")
                return None
    except Exception as e:
        logger.error(f"Supabase connection error ({method} {endpoint}): {e}")
        return None


# ==================== SQLite Context (Local Cache & Fallback) ====================

@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    # 1. Initialize local SQLite
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

        # Migrations for orders
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

        try:
            await db.execute("ALTER TABLE products ADD COLUMN category TEXT DEFAULT 'other'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE products ADD COLUMN price_usd REAL DEFAULT 2.5")
        except Exception:
            pass

        # Seed products locally
        initial_products = [
            # 1. Gemini
            ("gemini_18m", "جيميني برو 18 شهر", 1100.0, 2.5, "gemini", "💎 اشتراك Google Gemini Pro أصلي لمدة 18 شهر بضمان كامل مع ميزات AI المتقدمة و2TB تخزين سحابي.", 14, 1),
            ("gemini_12m", "جيميني برو 12 شهر", 1000.0, 2.5, "gemini", "💎 اشتراك Google Gemini Pro أصلي لمدة 12 شهر بضمان كامل مع ميزات AI المتقدمة و2TB تخزين سحابي.", 14, 1),
            ("gemini_3m", "جيميني برو 3 أشهر", 500.0, 2.0, "gemini", "💎 اشتراك Google Gemini Pro أصلي لمدة 3 أشهر مع ميزات AI وسعة تخزين سحابية 5TB.", None, 1),

            # 2. ChatGPT & Codex
            ("chatgpt_plus_4m", "ChatGPT Plus (4 أشهر)", 6000.0, 25.0, "chatgpt", "🤖 اشتراك شات جي بي تي بلس الأصلي لمدة 4 أشهر كاملة مع ميزات GPT-4o وتوليد الصور المتقدمة.", 90, 1),
            ("codex_api_10m", "Codex API (10M Tokens)", 1000.0, 2.5, "chatgpt", "💻 رصيد 10 مليون توكن API لـ OpenAI Codex للمطورين والمبرمجين مع ضمان كامل.", 36, 1),

            # 3. Other Products & Digital Subscriptions
            ("youtube_premium_3m", "YouTube Premium (3 أشهر)", 800.0, 3.5, "other", "🔴 اشتراك يوتيوب بريميوم رسمي لمدة 3 أشهر بدون إعلانات مع تشغيل بالخلفية وYouTube Music.", None, 1),
            ("nordvpn_3m", "NordVPN Basic (3 أشهر)", 900.0, 4.0, "other", "🛡 اشتراك نورد في بي إن الأصلي لمدة 3 أشهر لحماية خصوصيتك وتصفح آمن على 10 أجهزة مع ضمان كامل.", None, 1),
            ("coursera_12m", "Coursera Premium (12 شهر)", 800.0, 3.5, "other", "🎓 وصول بريميوم كامل لمنصة كورسيرا لمدة سنة مع جميع الكورسات والشهادات المعتمدة.", None, 1),
            ("lovable_pro_12m", "Lovable Pro Lite (12 شهر + 300C)", 2000.0, 8.5, "other", "⚡️ اشتراك لوفابل برو لمدة سنة لتطوير تطبيقات الويب بالذكاء الاصطناعي مع 300 رصيد شهري.", None, 1),
            ("elevenlabs_creator_3m", "ElevenLabs Creator (3 أشهر)", 4500.0, 20.0, "other", "🎙 اشتراك إيلفن لابس كريتور لتوليد الأصوات بالذكاء الاصطناعي بدقة سينمائية (121k كريدت شهرياً).", None, 1),
            ("claude_api_10m", "Claude API (10M Tokens)", 1000.0, 2.5, "other", "⚡️ رصيد 10 مليون توكن API لـ Claude 3.5 Sonnet / Opus للمطورين مع ضمان كامل.", 32, 1),
            ("duolingo_12m", "Duolingo Super (12 شهر)", 600.0, 1.5, "other", "🦉 اشتراك دوولينجو سوبر لمدة سنة كاملة بدون إعلانات مع قلوب غير محدودة لتعلم اللغات.", 74, 1),
            ("adobe_express_12m", "Adobe Express (12 شهر)", 500.0, 1.5, "other", "🎨 اشتراك أدوبي إكسبريس بريميوم لمدة سنة كاملة للتصميم وصناعة المحتوى مع آلاف القوالب.", None, 1),
            ("adobe_express_4m", "Adobe Express (4 أشهر)", 400.0, 1.5, "other", "🎨 اشتراك أدوبي إكسبريس بريميوم لمدة 4 أشهر للتصميم وصناعة المحتوى مع آلاف القوالب.", None, 1),
            ("apple_music_5m", "Apple Music (5 أشهر)", 500.0, 1.5, "other", "🎵 اشتراك أبل ميوزك أصلي لمدة 5 أشهر مع جودة صوت فائقة وبدون إعلانات.", None, 1),
            ("capcut_pro_30d", "CapCut Pro (30 يوم)", 800.0, 2.5, "other", "🎬 اشتراك كاب كت برو لمدة شهر لمونتاج وتعديل الفيديوهات باحترافية وبدون علامة مائية.", 21, 1),
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

        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('payment_info', ?)",
            (DEFAULT_PAYMENT_INFO,),
        )
        await db.commit()

    # 2. Check and sync Supabase Cloud tables
    logger.info("Syncing with Supabase Cloud Database...")
    sb_prods = await _sb_request("GET", "bot_products", params={"select": "id", "limit": 1})
    if sb_prods is not None and len(sb_prods) == 0:
        # Seed cloud products if empty
        seed_payload = [
            {"id": p[0], "name": p[1], "price": p[2], "price_usd": p[3], "category": p[4], "description": p[5], "supplier_product_id": p[6], "is_active": p[7]}
            for p in initial_products
        ]
        await _sb_request("POST", "bot_products", json_data=seed_payload, prefer="resolution=merge-duplicates")


# ==================== إدارة المنتجات والأسعار (Products) ====================

async def get_all_products(only_active: bool = True) -> dict[str, dict]:
    """Fetch all products as a dictionary {product_id: product_data}"""
    params = {"order": "price.desc"}
    if only_active:
        params["is_active"] = "eq.1"

    sb_rows = await _sb_request("GET", "bot_products", params=params)
    if sb_rows is not None:
        result = {}
        for r in sb_rows:
            r["price"] = float(r["price"])
            r["price_usd"] = float(r.get("price_usd") or 2.5)
            result[r["id"]] = r
        return result

    # Local fallback
    async with get_db() as db:
        query = "SELECT * FROM products WHERE is_active = 1 ORDER BY price DESC" if only_active else "SELECT * FROM products ORDER BY price DESC"
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
        return {r["id"]: dict(r) for r in rows}


async def get_products_by_category(category: str, only_active: bool = True) -> dict[str, dict]:
    """Fetch products filtered by category ('gemini', 'chatgpt', 'other')"""
    params = {"category": f"eq.{category}", "order": "price.desc"}
    if only_active:
        params["is_active"] = "eq.1"

    sb_rows = await _sb_request("GET", "bot_products", params=params)
    if sb_rows is not None:
        result = {}
        for r in sb_rows:
            r["price"] = float(r["price"])
            r["price_usd"] = float(r.get("price_usd") or 2.5)
            result[r["id"]] = r
        return result

    # Local fallback
    async with get_db() as db:
        query = "SELECT * FROM products WHERE category = ? AND is_active = 1 ORDER BY price DESC" if only_active else "SELECT * FROM products WHERE category = ? ORDER BY price DESC"
        cursor = await db.execute(query, (category,))
        rows = await cursor.fetchall()
        return {r["id"]: dict(r) for r in rows}


async def get_product_by_id(product_id: str) -> dict | None:
    sb_rows = await _sb_request("GET", "bot_products", params={"id": f"eq.{product_id}", "limit": 1})
    if sb_rows is not None:
        if sb_rows:
            r = sb_rows[0]
            r["price"] = float(r["price"])
            r["price_usd"] = float(r.get("price_usd") or 2.5)
            return r
        return None

    # Local fallback
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_product_price(product_id: str, new_price: float):
    # Supabase Cloud update
    await _sb_request("PATCH", "bot_products", params={"id": f"eq.{product_id}"}, json_data={"price": new_price})

    # Local update
    async with get_db() as db:
        await db.execute("UPDATE products SET price = ? WHERE id = ?", (new_price, product_id))
        await db.commit()


async def add_new_product(
    product_id: str,
    name: str,
    price: float,
    description: str = "",
    supplier_product_id: int | None = None,
    price_usd: float = 2.5,
    category: str = "other",
):
    # Supabase Cloud insert
    payload = {
        "id": product_id,
        "name": name,
        "price": price,
        "price_usd": price_usd,
        "category": category,
        "description": description,
        "supplier_product_id": supplier_product_id,
        "is_active": 1,
    }
    await _sb_request("POST", "bot_products", json_data=payload, prefer="resolution=merge-duplicates")

    # Local insert
    async with get_db() as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO products (id, name, price, price_usd, category, description, supplier_product_id, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (product_id, name, price, price_usd, category, description, supplier_product_id),
        )
        await db.commit()


async def toggle_product_active(product_id: str) -> bool:
    prod = await get_product_by_id(product_id)
    if not prod:
        return False
    new_status = 0 if prod.get("is_active", 1) == 1 else 1

    # Supabase Cloud update
    await _sb_request("PATCH", "bot_products", params={"id": f"eq.{product_id}"}, json_data={"is_active": new_status})

    # Local update
    async with get_db() as db:
        await db.execute("UPDATE products SET is_active = ? WHERE id = ?", (new_status, product_id))
        await db.commit()

    return bool(new_status)


# ==================== روابط المخزن (Stock) ====================

async def add_links_to_stock(product_id: str, links: list[str]) -> int:
    """Saves links directly to Supabase Cloud bot_links_stock and local cache"""
    clean_links = [l.strip() for l in links if l.strip()]
    if not clean_links:
        return 0

    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Supabase Cloud insertion
    sb_payload = [
        {"product_id": product_id, "link_url": l, "is_used": False}
        for l in clean_links
    ]
    sb_res = await _sb_request("POST", "bot_links_stock", json_data=sb_payload, prefer="return=representation")
    if sb_res is not None and isinstance(sb_res, list):
        logger.info(f"Successfully added {len(sb_res)} links to Supabase Cloud for {product_id}")

    # 2. Local SQLite insertion
    async with get_db() as db:
        for clean_link in clean_links:
            await db.execute(
                """
                INSERT INTO links_stock (product_id, link_url, is_used, added_at)
                VALUES (?, ?, 0, ?)
                """,
                (product_id, clean_link, now_iso),
            )
        await db.commit()

    return len(clean_links)


async def get_stock_counts() -> dict:
    """Returns {product_id: count of unused links} from Supabase Cloud"""
    sb_rows = await _sb_request(
        "GET",
        "bot_links_stock",
        params={"select": "product_id", "is_used": "eq.false"}
    )
    if sb_rows is not None and isinstance(sb_rows, list):
        counts = {}
        for r in sb_rows:
            pid = r.get("product_id")
            if pid:
                counts[pid] = counts.get(pid, 0) + 1
        return counts

    # Local fallback
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
    """Fetch available links from Supabase Cloud without marking them yet"""
    sb_rows = await _sb_request(
        "GET",
        "bot_links_stock",
        params={
            "product_id": f"eq.{product_id}",
            "is_used": "eq.false",
            "order": "id.asc",
            "limit": str(count),
        }
    )
    if sb_rows is not None and isinstance(sb_rows, list):
        return [{"id": r["id"], "link_url": r["link_url"]} for r in sb_rows]

    # Local fallback
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
    """Mark links as used in Supabase Cloud and local database"""
    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Supabase Cloud update
    if link_ids:
        id_filter = f"in.({','.join(map(str, link_ids))})"
        update_data = {
            "is_used": True,
            "order_id": order_id,
            "used_by_user_id": user_id,
            "used_at": now_iso,
        }
        await _sb_request("PATCH", "bot_links_stock", params={"id": id_filter}, json_data=update_data)

    # Local update
    async with get_db() as db:
        for lid in link_ids:
            await db.execute(
                """
                UPDATE links_stock 
                SET is_used = 1, order_id = ?, used_by_user_id = ?, used_at = ?
                WHERE id = ?
                """,
                (order_id, user_id, now_iso, lid),
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
    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    order_payload = {
        "user_id": user_id,
        "user_name": user_name,
        "user_username": user_username,
        "product_id": product_id,
        "product_name": product_name,
        "quantity": quantity,
        "total_price": total_price,
        "transfer_number": transfer_number,
        "receipt_file_id": receipt_file_id,
        "payment_method": payment_method,
        "currency": currency,
        "status": "PENDING",
    }

    # 1. Supabase Cloud order creation
    sb_res = await _sb_request("POST", "bot_orders", json_data=order_payload, prefer="return=representation")
    order_id = None
    if sb_res is not None and isinstance(sb_res, list) and sb_res:
        order_id = sb_res[0].get("id")
        order_code = f"ORD-{order_id:04d}"
        await _sb_request("PATCH", "bot_orders", params={"id": f"eq.{order_id}"}, json_data={"order_code": order_code})

    # 2. Local SQLite order creation (for fallback / replication)
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
                now_iso,
                now_iso,
            ),
        )
        local_order_id = cursor.lastrowid
        if not order_id:
            order_id = local_order_id

        order_code = f"ORD-{order_id:04d}"
        await db.execute(
            "UPDATE orders SET order_code = ? WHERE id = ?",
            (order_code, local_order_id),
        )
        await db.commit()

    return order_id, order_code


async def get_order_by_id(order_id: int) -> dict | None:
    sb_rows = await _sb_request("GET", "bot_orders", params={"id": f"eq.{order_id}", "limit": 1})
    if sb_rows is not None and sb_rows:
        return sb_rows[0]

    # Local fallback
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_pending_orders(limit: int = 10) -> list[dict]:
    sb_rows = await _sb_request(
        "GET",
        "bot_orders",
        params={"status": "eq.PENDING", "order": "id.desc", "limit": str(limit)}
    )
    if sb_rows is not None and isinstance(sb_rows, list):
        return sb_rows

    # Local fallback
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM orders WHERE status = 'PENDING' ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_user_orders(user_id: int, limit: int = 5) -> list[dict]:
    sb_rows = await _sb_request(
        "GET",
        "bot_orders",
        params={"user_id": f"eq.{user_id}", "order": "id.desc", "limit": str(limit)}
    )
    if sb_rows is not None and isinstance(sb_rows, list):
        return sb_rows

    # Local fallback
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def mark_order_approved(order_id: int, links: list[str]) -> bool:
    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    links_str = "\n".join(links)

    # Supabase Cloud update
    await _sb_request(
        "PATCH",
        "bot_orders",
        params={"id": f"eq.{order_id}"},
        json_data={"status": "APPROVED", "delivered_links": links_str, "updated_at": now_iso}
    )

    # Local update
    async with get_db() as db:
        await db.execute(
            """
            UPDATE orders 
            SET status = 'APPROVED', delivered_links = ?, updated_at = ?
            WHERE id = ?
            """,
            (links_str, now_iso, order_id),
        )
        await db.commit()
    return True


async def mark_order_rejected(order_id: int, reason: str = "") -> bool:
    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Supabase Cloud update
    await _sb_request(
        "PATCH",
        "bot_orders",
        params={"id": f"eq.{order_id}"},
        json_data={"status": "REJECTED", "reject_reason": reason, "updated_at": now_iso}
    )

    # Local update
    async with get_db() as db:
        await db.execute(
            """
            UPDATE orders 
            SET status = 'REJECTED', reject_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (reason, now_iso, order_id),
        )
        await db.commit()
    return True


# ==================== الإحصائيات (Stats) ====================

async def get_admin_stats() -> dict:
    sb_orders = await _sb_request("GET", "bot_orders", params={"select": "id,status,total_price,user_id"})
    if sb_orders is not None and isinstance(sb_orders, list):
        total_orders = len(sb_orders)
        pending_orders = sum(1 for o in sb_orders if o.get("status") == "PENDING")
        approved_orders = sum(1 for o in sb_orders if o.get("status") == "APPROVED")
        rejected_orders = sum(1 for o in sb_orders if o.get("status") == "REJECTED")
        total_revenue = sum(float(o.get("total_price") or 0.0) for o in sb_orders if o.get("status") == "APPROVED")
        unique_customers = len(set(o.get("user_id") for o in sb_orders if o.get("user_id")))

        return {
            "total_orders": total_orders,
            "pending_orders": pending_orders,
            "approved_orders": approved_orders,
            "rejected_orders": rejected_orders,
            "total_revenue": total_revenue,
            "unique_customers": unique_customers,
        }

    # Local fallback
    async with get_db() as db:
        cur = await db.execute("SELECT COUNT(*) as c FROM orders")
        total_orders = (await cur.fetchone())["c"]

        cur = await db.execute("SELECT COUNT(*) as c FROM orders WHERE status = 'PENDING'")
        pending_orders = (await cur.fetchone())["c"]

        cur = await db.execute("SELECT COUNT(*) as c FROM orders WHERE status = 'APPROVED'")
        approved_orders = (await cur.fetchone())["c"]

        cur = await db.execute("SELECT COUNT(*) as c FROM orders WHERE status = 'REJECTED'")
        rejected_orders = (await cur.fetchone())["c"]

        cur = await db.execute("SELECT SUM(total_price) as s FROM orders WHERE status = 'APPROVED'")
        revenue_row = await cur.fetchone()
        total_revenue = revenue_row["s"] if revenue_row and revenue_row["s"] is not None else 0.0

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
    sb_row = await _sb_request("GET", "bot_settings", params={"key": "eq.payment_info", "select": "value", "limit": 1})
    if sb_row is not None and isinstance(sb_row, list) and sb_row:
        val = sb_row[0].get("value")
        if val:
            return val

    # Local fallback
    async with get_db() as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = 'payment_info'")
        row = await cur.fetchone()
        if row and row["value"]:
            return row["value"]
    return DEFAULT_PAYMENT_INFO


async def update_payment_info(new_info: str):
    # Supabase Cloud update
    await _sb_request(
        "POST",
        "bot_settings",
        json_data={"key": "payment_info", "value": new_info},
        prefer="resolution=merge-duplicates"
    )

    # Local update
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('payment_info', ?)",
            (new_info,),
        )
        await db.commit()


async def get_proof_channel() -> str:
    """Fetch configured proofs channel (username like @channel or chat_id)"""
    sb_row = await _sb_request("GET", "bot_settings", params={"key": "eq.proof_channel", "select": "value", "limit": 1})
    if sb_row is not None and isinstance(sb_row, list) and sb_row:
        val = sb_row[0].get("value")
        if val:
            return val.strip()

    # Local fallback
    async with get_db() as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = 'proof_channel'")
        row = await cur.fetchone()
        if row and row["value"]:
            return row["value"].strip()
    return PROOF_CHANNEL.strip() if PROOF_CHANNEL else ""


async def update_proof_channel(new_channel: str):
    """Save or update configured proofs channel in Cloud & Local"""
    clean_chan = new_channel.strip()

    # Supabase Cloud update
    await _sb_request(
        "POST",
        "bot_settings",
        json_data={"key": "proof_channel", "value": clean_chan},
        prefer="resolution=merge-duplicates"
    )

    # Local update
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('proof_channel', ?)",
            (clean_chan,),
        )
        await db.commit()


# ==================== إعدادات عامة (Generic Key-Value Settings) ====================

async def get_setting(key: str, default: str = "") -> str:
    """Fetch setting value from Supabase with local SQLite fallback"""
    sb_row = await _sb_request("GET", "bot_settings", params={"key": f"eq.{key}", "select": "value", "limit": 1})
    if sb_row is not None and isinstance(sb_row, list) and sb_row:
        val = sb_row[0].get("value")
        if val is not None:
            return str(val)

    async with get_db() as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        if row and row["value"] is not None:
            return str(row["value"])
    return default


async def set_setting(key: str, value: str):
    """Save setting value to Supabase Cloud and local SQLite"""
    val_str = str(value)
    await _sb_request(
        "POST",
        "bot_settings",
        json_data={"key": key, "value": val_str},
        prefer="resolution=merge-duplicates"
    )
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, val_str),
        )
        await db.commit()

