import time
import json
import logging
import asyncio
import httpx
from config import (
    DIGITALCORE_API_KEY,
    DIGITALCORE_BASE_URL,
    DIGITALCORE_PRODUCT_MAP,
    SUPPLIER_API_KEY,
    SUPPLIER_BASE_URL,
    SUPPLIER_PRODUCT_MAP,
    ACCZONE_API_KEY,
    ACCZONE_BASE_URL,
    ACCZONE_PRODUCT_MAP,
)

logger = logging.getLogger(__name__)

# Standard browser headers to bypass Cloudflare protection
DIGITALCORE_HEADERS = {
    "Api-Key": DIGITALCORE_API_KEY,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


# ==================== المورد الأول والرئيسي (DigitalCore) ====================

async def check_digitalcore_balance() -> dict:
    """Check account balance and order count on DigitalCore"""
    if not DIGITALCORE_API_KEY:
        return {"ok": False, "error": "لم يتم ضبط مفتاح DigitalCore API"}

    url = f"{DIGITALCORE_BASE_URL}/api/user/me"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=DIGITALCORE_HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                bal = float(data.get("balance", 0.0))
                orders = data.get("total_orders", "0")
                return {
                    "ok": True,
                    "balance": bal,
                    "balance_text": f"${bal:.2f}",
                    "total_orders": str(orders),
                }
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def get_digitalcore_stock() -> dict:
    """Fetch live catalog and stock levels from DigitalCore"""
    if not DIGITALCORE_API_KEY:
        return {"ok": False, "error": "لم يتم ضبط مفتاح DigitalCore API"}

    url = f"{DIGITALCORE_BASE_URL}/api/user/products"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=DIGITALCORE_HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                return {"ok": True, "products": data}
            return {"ok": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def purchase_from_digitalcore(
    local_product_id: str,
    quantity: int,
    order_code: str,
) -> tuple[bool, list[str], str]:
    """Attempts to buy product via DigitalCore API"""
    if not DIGITALCORE_API_KEY:
        return False, [], "مفتاح API المورد DigitalCore غير مضبوط."

    slug = DIGITALCORE_PRODUCT_MAP.get(local_product_id)
    if not slug:
        return False, [], f"المنتج {local_product_id} غير مربوط بـ DigitalCore."

    url = f"{DIGITALCORE_BASE_URL}/api/user/buy"
    headers = {
        **DIGITALCORE_HEADERS,
        "Content-Type": "application/json",
    }
    payload = {
        "id": slug,
        "count": quantity,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    items = data.get("items", [])
                    if items:
                        order_id_dc = data.get("order_id", "")
                        return True, items, f"تم شراء الرابط بنجاح من DigitalCore (طلب رقم {order_id_dc})."
                    return False, [], "تمت العملية لكن لم يتم استلام أي رابط في الرد."
                else:
                    msg = data.get("msg", "فشلت العملية")
                    if msg == "OUT_OF_STOCK":
                        msg = "المنتج غير متوفر حالياً في مخزن DigitalCore."
                    elif msg == "INSUFFICIENT_BALANCE":
                        msg = "رصيد المحفظة لدى DigitalCore غير كافٍ لإتمام الطلب."
                    return False, [], f"DigitalCore: {msg}"
            else:
                try:
                    err_json = resp.json()
                    msg = err_json.get("msg", resp.text)
                except Exception:
                    msg = resp.text
                return False, [], f"DigitalCore HTTP {resp.status_code}: {msg}"
    except Exception as e:
        return False, [], f"فشل الاتصال بـ DigitalCore: {str(e)}"


# ==================== المورد الثاني (LahaStore) ====================

async def check_supplier_balance() -> dict:
    """Check current wallet balance on LahaStore"""
    if not SUPPLIER_API_KEY:
        return {"ok": False, "error": "لم يتم ضبط مفتاح الـ API (LahaStore)"}

    url = f"{SUPPLIER_BASE_URL}/balance"
    headers = {"X-API-Key": SUPPLIER_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "ok": True,
                    "shop_id": data.get("shopId"),
                    "balance_usd": data.get("balanceUsd", 0.0),
                    "balance_usd_text": data.get("balanceUsdText", "$0.00"),
                    "balance_vnd": data.get("balance", 0),
                    "balance_vnd_text": data.get("balanceText", "0đ"),
                }
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def get_lahastore_all_products() -> dict:
    """Fetch complete product catalog and stock from LahaStore"""
    if not SUPPLIER_API_KEY:
        return {"ok": False, "error": "API Key not configured"}

    url = f"{SUPPLIER_BASE_URL}/products"
    headers = {"X-API-Key": SUPPLIER_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return {"ok": True, "products": data.get("products", [])}
            return {"ok": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def get_supplier_gemini_stock() -> dict:
    """Fetch live stock levels of Gemini products from LahaStore"""
    if not SUPPLIER_API_KEY:
        return {"ok": False, "error": "API Key not configured"}

    url = f"{SUPPLIER_BASE_URL}/products"
    headers = {"X-API-Key": SUPPLIER_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                products = data.get("products", [])
                gemini_items = [
                    p for p in products
                    if "gemini" in (p.get("name") or "").lower() or "gemini" in (p.get("category") or "").lower()
                ]
                return {"ok": True, "items": gemini_items}
            return {"ok": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def purchase_from_supplier(
    local_product_id: str,
    quantity: int,
    order_code: str,
) -> tuple[bool, list[str], str]:
    """Attempts to buy product via LahaStore API"""
    if not SUPPLIER_API_KEY:
        return False, [], "مفتاح API المورد LahaStore غير مضبوط."

    supplier_item_id = SUPPLIER_PRODUCT_MAP.get(local_product_id)
    if not supplier_item_id:
        return False, [], f"المنتج {local_product_id} غير مربوط بـ LahaStore."

    url = f"{SUPPLIER_BASE_URL}/orders"
    headers = {
        "X-API-Key": SUPPLIER_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "productId": supplier_item_id,
        "qty": quantity,
        "currency": "usd",
        "shopOrderId": order_code,
    }

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            data = resp.json()

            if resp.status_code == 200 and data.get("ok"):
                order_info = data.get("order", {})
                accounts = order_info.get("accounts", [])
                if accounts:
                    return True, accounts, "تم شراء الرابط بنجاح من LahaStore."
                return False, [], "تمت العملية لكن لم يتم استلام أي رابط في الرد."
            else:
                err_code = data.get("code", "")
                err_msg = data.get("error", data.get("message", "حدث خطأ أثناء الشراء."))
                if err_code == "INSUFFICIENT_BALANCE":
                    err_msg = "رصيد المحفظة لدى LahaStore غير كافٍ."
                elif err_code == "OUT_OF_STOCK":
                    err_msg = "المنتج غير متوفر حالياً في مخزن LahaStore."
                return False, [], err_msg

    except Exception as e:
        return False, [], f"فشل الاتصال بـ LahaStore: {str(e)}"


# ==================== المورد الثالث الاحتياطي (AccZone) ====================

async def check_acczone_balance() -> dict:
    """Check current wallet balance on AccZone"""
    if not ACCZONE_API_KEY:
        return {"ok": False, "error": "لم يتم ضبط مفتاح الـ API (AccZone)"}

    url = f"{ACCZONE_BASE_URL}/getBalance"
    params = {"apikey": ACCZONE_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "ok": True,
                    "username": data.get("username"),
                    "balance": data.get("balance", 0.0),
                    "balance_text": f"${data.get('balance', 0.0):.2f}",
                }
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def get_acczone_all_services() -> dict:
    """Fetch all services and live stock from AccZone"""
    url = f"{ACCZONE_BASE_URL}/getServices"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                services = resp.json()
                return {"ok": True, "services": services if isinstance(services, list) else []}
            return {"ok": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def get_acczone_gemini_stock() -> dict:
    """Fetch live stock levels of Gemini products from AccZone"""
    url = f"{ACCZONE_BASE_URL}/getServices"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                services = resp.json()
                gemini_items = [
                    s for s in services
                    if "gemini" in (s.get("name") or "").lower() or "gemini" in (s.get("key") or "").lower()
                ]
                return {"ok": True, "items": gemini_items}
            return {"ok": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def purchase_from_acczone(
    local_product_id: str,
    quantity: int,
) -> tuple[bool, list[str], str]:
    """Attempts to buy product via AccZone API"""
    if not ACCZONE_API_KEY:
        return False, [], "مفتاح API المورد AccZone غير مضبوط."

    service_key = ACCZONE_PRODUCT_MAP.get(local_product_id)
    if not service_key:
        return False, [], f"المنتج {local_product_id} غير متوفر لدى AccZone."

    url = f"{ACCZONE_BASE_URL}/buyCpn"
    params = {
        "apikey": ACCZONE_API_KEY,
        "service_key": service_key,
        "quantity": quantity,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    links = [item.get("code_value") for item in data if item.get("code_value")]
                    if links:
                        return True, links, "تم شراء الرابط بنجاح من AccZone."
                    return False, [], "لم يتم العثور على روابط في رد AccZone."
                elif isinstance(data, dict) and data.get("detail"):
                    return False, [], f"خطأ AccZone: {data['detail']}"
                return False, [], "رد غير متوقع من AccZone."
            else:
                try:
                    err_json = resp.json()
                    detail = err_json.get("detail", resp.text)
                except Exception:
                    detail = resp.text
                return False, [], f"AccZone HTTP {resp.status_code}: {detail}"

    except Exception as e:
        return False, [], f"فشل الاتصال بـ AccZone: {str(e)}"


# ==================== المولد التلقائي الذكي مع السحب البديل (Fallback Engine) ====================

async def purchase_with_fallback(
    local_product_id: str,
    quantity: int,
    order_code: str,
) -> tuple[bool, list[str], str, str]:
    """
    Smart Multi-Supplier Routing (DigitalCore -> AccZone -> LahaStore):
    1. Try DigitalCore first (huge stock, best wholesale prices, sub-millisecond execution).
    2. Fallback to AccZone if supported.
    3. Fallback to LahaStore if supported.
    """
    has_dc = local_product_id in DIGITALCORE_PRODUCT_MAP
    has_acczone = local_product_id in ACCZONE_PRODUCT_MAP
    has_laha = local_product_id in SUPPLIER_PRODUCT_MAP

    errors = []

    # 1. First priority: DigitalCore
    if has_dc:
        dc_ok, dc_links, dc_msg = await purchase_from_digitalcore(local_product_id, quantity, order_code)
        if dc_ok and dc_links:
            return True, dc_links, dc_msg, "DigitalCore"
        errors.append(f"DigitalCore: {dc_msg}")

    # 2. Second priority: AccZone
    if has_acczone:
        acc_ok, acc_links, acc_msg = await purchase_from_acczone(local_product_id, quantity)
        if acc_ok and acc_links:
            return True, acc_links, acc_msg, "AccZone"
        errors.append(f"AccZone: {acc_msg}")

    # 3. Third priority: LahaStore
    if has_laha:
        laha_ok, laha_links, laha_msg = await purchase_from_supplier(local_product_id, quantity, order_code)
        if laha_ok and laha_links:
            return True, laha_links, laha_msg, "LahaStore"
        errors.append(f"LahaStore: {laha_msg}")

    # All attempted suppliers failed
    combined_msg = " | ".join(errors) if errors else "المنتج غير مربوط بأي مزود API."
    return False, [], combined_msg, "None"


# ==================== محرك فحص المخزون السريع (Live Stock Cache Engine) ====================

_STOCK_CACHE = {
    "last_fetch": 0.0,
    "digitalcore": {},  # slug -> int
    "acczone": {},      # key -> int
    "lahastore": {},    # int(id) -> int
}


async def refresh_all_supplier_stock_cache(force: bool = False) -> dict:
    """Refreshes stock levels from all active suppliers in parallel with 60s TTL"""
    now = time.time()
    if not force and (now - _STOCK_CACHE["last_fetch"] < 60) and _STOCK_CACHE["last_fetch"] > 0:
        return _STOCK_CACHE

    dc_task = get_digitalcore_stock()
    acc_task = get_acczone_all_services()
    laha_task = get_lahastore_all_products()

    results = await asyncio.gather(dc_task, acc_task, laha_task, return_exceptions=True)
    dc_res, acc_res, laha_res = results

    # 1. Parse DigitalCore Stock
    dc_stock_map = {}
    if isinstance(dc_res, dict) and dc_res.get("ok"):
        for p in dc_res.get("products", []):
            slug = p.get("id")
            stk = p.get("stock", 0)
            if slug:
                try:
                    dc_stock_map[slug] = int(stk)
                except Exception:
                    dc_stock_map[slug] = 0

    # 2. Parse AccZone Stock
    acc_stock_map = {}
    if isinstance(acc_res, dict) and acc_res.get("ok"):
        for s in acc_res.get("services", []):
            k = s.get("key")
            stk = s.get("stock", s.get("amount", 0))
            if k:
                try:
                    acc_stock_map[k] = int(stk)
                except Exception:
                    acc_stock_map[k] = 0

    # 3. Parse LahaStore Stock
    laha_stock_map = {}
    if isinstance(laha_res, dict) and laha_res.get("ok"):
        for p in laha_res.get("products", []):
            pid = p.get("id")
            stk = p.get("stock", 0)
            if pid is not None:
                try:
                    laha_stock_map[int(pid)] = int(stk) if str(stk).isdigit() else 0
                except Exception:
                    laha_stock_map[int(pid)] = 0

    _STOCK_CACHE["digitalcore"] = dc_stock_map
    _STOCK_CACHE["acczone"] = acc_stock_map
    _STOCK_CACHE["lahastore"] = laha_stock_map
    _STOCK_CACHE["last_fetch"] = now
    return _STOCK_CACHE


async def check_total_product_stock(local_product_id: str) -> dict:
    """
    Computes total available stock across local links and connected suppliers.
    Returns:
    {
        "product_id": str,
        "local_stock": int,
        "api_stock": int,
        "total_stock": int,
        "is_in_stock": bool,
    }
    """
    cache = await refresh_all_supplier_stock_cache()

    import database
    stock_counts = await database.get_stock_counts()
    local_stock = stock_counts.get(local_product_id, 0)

    api_stock = 0
    # Check DigitalCore
    dc_slug = DIGITALCORE_PRODUCT_MAP.get(local_product_id)
    if dc_slug:
        api_stock += cache["digitalcore"].get(dc_slug, 0)

    # Check AccZone
    acc_key = ACCZONE_PRODUCT_MAP.get(local_product_id)
    if acc_key:
        api_stock += cache["acczone"].get(acc_key, 0)

    # Check LahaStore
    laha_id = SUPPLIER_PRODUCT_MAP.get(local_product_id)
    if laha_id:
        try:
            api_stock += cache["lahastore"].get(int(laha_id), 0)
        except Exception:
            pass

    total_stock = local_stock + api_stock
    return {
        "product_id": local_product_id,
        "local_stock": local_stock,
        "api_stock": api_stock,
        "total_stock": total_stock,
        "is_in_stock": total_stock > 0,
    }


async def get_products_stock_summary(product_ids: list[str]) -> dict[str, bool]:
    """Returns {product_id: is_in_stock} for a list of products (for menu badges)"""
    cache = await refresh_all_supplier_stock_cache()
    import database
    stock_counts = await database.get_stock_counts()

    status_map = {}
    for pid in product_ids:
        local_stock = stock_counts.get(pid, 0)
        api_stock = 0
        dc_slug = DIGITALCORE_PRODUCT_MAP.get(pid)
        if dc_slug:
            api_stock += cache["digitalcore"].get(dc_slug, 0)
        acc_key = ACCZONE_PRODUCT_MAP.get(pid)
        if acc_key:
            api_stock += cache["acczone"].get(acc_key, 0)
        laha_id = SUPPLIER_PRODUCT_MAP.get(pid)
        if laha_id:
            try:
                api_stock += cache["lahastore"].get(int(laha_id), 0)
            except Exception:
                pass
        status_map[pid] = (local_stock + api_stock) > 0
    return status_map


# ==================== المزامنة التلقائية للمنتجات الجديدة (Auto-Discovery Engine) ====================

def clean_supplier_title(raw_name: str) -> str:
    """Translates common subscription terms and formats product title cleanly in Arabic / English"""
    clean = raw_name.replace("_", " ").replace("-", " ").strip()
    replacements = {
        "18 Months": "(18 شهر)",
        "18 months": "(18 شهر)",
        "12 Months": "(12 شهر)",
        "12 months": "(12 شهر)",
        "12 Month": "(12 شهر)",
        "6 Months": "(6 أشهر)",
        "4 Months": "(4 أشهر)",
        "3 Months": "(3 أشهر)",
        "3 months": "(3 أشهر)",
        "1 Month": "(شهر واحد)",
        "1 month": "(شهر واحد)",
        "30 Days": "(30 يوم)",
        "30 days": "(30 يوم)",
        "30D": "(30 يوم)",
        "Full Warranty": "",
        "Warranty 1 Day": "",
        "Warranty 1 Days": "",
    }
    for k, v in replacements.items():
        clean = clean.replace(k, v)
    import re
    clean = re.sub(r"\s+", " ", clean).strip(" -")
    return clean


def calculate_retail_prices(wholesale: float) -> tuple[float, float]:
    """Calculates suggested retail prices (DZD, USD) based on wholesale cost with profit margin"""
    if wholesale <= 0.4:
        retail_usd = 1.5
        retail_dzd = 400.0
    elif wholesale <= 0.8:
        retail_usd = 2.5
        retail_dzd = 600.0
    elif wholesale <= 1.2:
        retail_usd = 3.0
        retail_dzd = 800.0
    elif wholesale <= 2.0:
        retail_usd = 3.5
        retail_dzd = 900.0
    elif wholesale <= 5.0:
        retail_usd = round(wholesale * 1.8, 1)
        retail_dzd = float(round(wholesale * 430, -1))
    elif wholesale <= 15.0:
        retail_usd = round(wholesale * 1.5, 1)
        retail_dzd = float(round(wholesale * 350, -1))
    else:
        retail_usd = round(wholesale * 1.35, 1)
        retail_dzd = float(round(wholesale * 320, -1))
    return retail_dzd, retail_usd


def detect_product_category(slug: str, name: str) -> str:
    combined = f"{slug} {name}".lower()
    if "gemini" in combined:
        return "gemini"
    elif any(k in combined for k in ["chatgpt", "gpt", "claude", "codex", "openai", "copilot"]):
        return "chatgpt"
    else:
        return "other"


async def load_dynamic_mappings_from_db():
    """Loads custom dynamic mappings from database settings and updates in-memory maps"""
    import database
    try:
        raw_dc = await database.get_setting("dynamic_dc_map", "")
        if raw_dc:
            data = json.loads(raw_dc)
            DIGITALCORE_PRODUCT_MAP.update(data)

        raw_lh = await database.get_setting("dynamic_laha_map", "")
        if raw_lh:
            data = json.loads(raw_lh)
            SUPPLIER_PRODUCT_MAP.update({k: int(v) for k, v in data.items()})

        raw_acc = await database.get_setting("dynamic_acc_map", "")
        if raw_acc:
            data = json.loads(raw_acc)
            ACCZONE_PRODUCT_MAP.update(data)
    except Exception as e:
        logger.warning(f"Could not load dynamic mappings: {e}")


async def save_dynamic_mappings_to_db():
    """Saves dynamic mappings to database settings"""
    import database
    try:
        await database.set_setting("dynamic_dc_map", json.dumps(DIGITALCORE_PRODUCT_MAP))
        await database.set_setting("dynamic_laha_map", json.dumps(SUPPLIER_PRODUCT_MAP))
        await database.set_setting("dynamic_acc_map", json.dumps(ACCZONE_PRODUCT_MAP))
    except Exception as e:
        logger.warning(f"Could not save dynamic mappings: {e}")


async def sync_new_supplier_products(bot=None) -> list[dict]:
    """
    Scans suppliers (DigitalCore, LahaStore, AccZone) for newly added products.
    Automatically imports them into database with markup pricing and sends alerts to admins.
    """
    import database
    await load_dynamic_mappings_from_db()
    existing_products = await database.get_all_products(only_active=False)
    existing_ids = set(existing_products.keys())

    new_products_added = []

    # 1. Scan DigitalCore
    dc_res = await get_digitalcore_stock()
    if dc_res.get("ok"):
        dc_items = dc_res.get("products", [])
        mapped_slugs = set(DIGITALCORE_PRODUCT_MAP.values())

        for itm in dc_items:
            slug = itm.get("id")
            if not slug or slug in mapped_slugs:
                continue

            raw_name = itm.get("name", slug)
            wholesale = float(itm.get("price", 0.0))
            stock = int(itm.get("stock", 0))

            clean_name = clean_supplier_title(raw_name)
            retail_dzd, retail_usd = calculate_retail_prices(wholesale)
            cat = detect_product_category(slug, raw_name)
            desc = itm.get("description", "")
            if not desc or len(desc) > 300:
                desc = f"اشتراك {clean_name} أصلي بضمان كامل مع وصول فوري لكافة الميزات."

            local_pid = slug.strip().lower()
            if local_pid in existing_ids:
                local_pid = f"dc_{local_pid}"

            await database.add_new_product(
                product_id=local_pid,
                name=clean_name,
                price=retail_dzd,
                description=desc,
                supplier_product_id=None,
                price_usd=retail_usd,
                category=cat,
            )

            DIGITALCORE_PRODUCT_MAP[local_pid] = slug
            existing_ids.add(local_pid)
            mapped_slugs.add(slug)

            new_info = {
                "id": local_pid,
                "name": clean_name,
                "supplier": "DigitalCore API",
                "wholesale": wholesale,
                "price_dzd": retail_dzd,
                "price_usd": retail_usd,
                "category": cat,
                "stock": stock,
            }
            new_products_added.append(new_info)

    # 2. Scan LahaStore
    laha_res = await get_lahastore_all_products()
    if laha_res.get("ok"):
        laha_items = laha_res.get("products", [])
        mapped_laha_ids = {int(v) for v in SUPPLIER_PRODUCT_MAP.values() if str(v).isdigit()}

        for itm in laha_items:
            lid = itm.get("id")
            if lid is None or int(lid) in mapped_laha_ids:
                continue

            raw_name = itm.get("name", "")
            if any(skip_word in raw_name.lower() for skip_word in ["extractor", "scan panel", "check link", "tool jio"]):
                continue

            wholesale = float(itm.get("priceUsd", 0.0))
            if wholesale <= 0 or wholesale > 40:
                continue

            stk_raw = itm.get("stock", 0)
            stk = int(stk_raw) if str(stk_raw).isdigit() else 0

            clean_name = clean_supplier_title(raw_name)
            retail_dzd, retail_usd = calculate_retail_prices(wholesale)
            cat = detect_product_category(str(lid), raw_name)
            desc = f"اشتراك {clean_name} رسمي ومضمون طوال فترة الاشتراك."

            import re
            slug_candidate = re.sub(r"[^a-z0-9]+", "_", clean_name.lower()).strip("_")
            local_pid = f"lh_{slug_candidate}_{lid}"
            if len(local_pid) > 35:
                local_pid = f"lh_prod_{lid}"

            if local_pid in existing_ids:
                local_pid = f"{local_pid}_{lid}"

            await database.add_new_product(
                product_id=local_pid,
                name=clean_name,
                price=retail_dzd,
                description=desc,
                supplier_product_id=int(lid),
                price_usd=retail_usd,
                category=cat,
            )

            SUPPLIER_PRODUCT_MAP[local_pid] = int(lid)
            existing_ids.add(local_pid)
            mapped_laha_ids.add(int(lid))

            new_info = {
                "id": local_pid,
                "name": clean_name,
                "supplier": "LahaStore API",
                "wholesale": wholesale,
                "price_dzd": retail_dzd,
                "price_usd": retail_usd,
                "category": cat,
                "stock": stk,
            }
            new_products_added.append(new_info)

    # 3. Save dynamic mappings to database settings if new products were added
    if new_products_added:
        await save_dynamic_mappings_to_db()

        if bot:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            from config import ADMIN_IDS
            for prod in new_products_added:
                alert_text = (
                    f"🆕 **تم اكتشاف وإضافة منتج جديد تلقائياً من المورد!**\n"
                    f"─────────────────────\n"
                    f"🌐 **المورد:** {prod['supplier']}\n"
                    f"📦 **اسم المنتج:** **{prod['name']}**\n"
                    f"🆔 **معرف المنتج:** `{prod['id']}`\n"
                    f"📂 **القسم:** `{prod['category']}`\n"
                    f"💵 **سعر التكلفة لدى المورد:** `${prod['wholesale']}`\n"
                    f"🏷 **سعر البيع بالدينار:** `{prod['price_dzd']} دج`\n"
                    f"💲 **سعر البيع بالدولار:** `${prod['price_usd']}`\n"
                    f"📊 **المخزون المتوفر لدى المورد:** `{prod['stock']}` قطعة\n\n"
                    f"✅ **تمت إضافة المنتج فوراً للمتجر السحابي وأصبح متاحاً للزبائن!**\n"
                    f"💡 يمكنك تعديل سعره، اسمه، أو إيقافه في أي وقت عبر لوحة التحكم (`/admin`)."
                )
                kb = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✏️ تعديل السعر", callback_data=f"adm_edit_price:{prod['id']}"),
                        InlineKeyboardButton("⛔️ إيقاف / تفعيل", callback_data=f"adm_toggle_prod:{prod['id']}"),
                    ]
                ])
                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_message(
                            chat_id=admin_id,
                            text=alert_text,
                            reply_markup=kb,
                            parse_mode="Markdown",
                        )
                    except Exception as e:
                        logger.error(f"Failed to send new product alert to admin {admin_id}: {e}")

    return new_products_added

