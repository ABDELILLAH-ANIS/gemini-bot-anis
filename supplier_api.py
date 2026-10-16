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
