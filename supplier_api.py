import httpx
from config import (
    SUPPLIER_API_KEY,
    SUPPLIER_BASE_URL,
    SUPPLIER_PRODUCT_MAP,
    ACCZONE_API_KEY,
    ACCZONE_BASE_URL,
    ACCZONE_PRODUCT_MAP,
)


# ==================== المورد الأول (LahaStore) ====================

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


# ==================== المورد الثاني الاحتياطي (AccZone) ====================

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
    Smart Multi-Supplier Routing:
    - Products available on AccZone with lower cost (Gemini, Duolingo, Adobe, Apple Music) try AccZone first.
    - Products on LahaStore (ChatGPT, Codex, Claude, CapCut) try LahaStore first.
    - Seamless fallback between both suppliers if supported.
    """
    has_acczone = local_product_id in ACCZONE_PRODUCT_MAP
    has_laha = local_product_id in SUPPLIER_PRODUCT_MAP

    # If product is primarily on AccZone
    if has_acczone and not has_laha:
        acc_ok, acc_links, acc_msg = await purchase_from_acczone(local_product_id, quantity)
        return acc_ok, acc_links, acc_msg, ("AccZone" if acc_ok else "None")

    # If product is primarily on LahaStore
    if has_laha and not has_acczone:
        laha_ok, laha_links, laha_msg = await purchase_from_supplier(local_product_id, quantity, order_code)
        return laha_ok, laha_links, laha_msg, ("LahaStore" if laha_ok else "None")

    # If product is available on BOTH (e.g. Gemini, Duolingo), prefer AccZone (cheaper) then LahaStore
    if has_acczone:
        acc_ok, acc_links, acc_msg = await purchase_from_acczone(local_product_id, quantity)
        if acc_ok and acc_links:
            return True, acc_links, acc_msg, "AccZone"
    else:
        acc_msg = "غير متاح"

    if has_laha:
        laha_ok, laha_links, laha_msg = await purchase_from_supplier(local_product_id, quantity, order_code)
        if laha_ok and laha_links:
            return True, laha_links, laha_msg, "LahaStore"
    else:
        laha_msg = "غير متاح"

    # Both failed
    combined_msg = f"AccZone: {acc_msg} | LahaStore: {laha_msg}"
    return False, [], combined_msg, "None"

