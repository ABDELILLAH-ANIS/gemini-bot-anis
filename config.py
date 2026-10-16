import os
from dotenv import load_dotenv

load_dotenv()

# Bot Token from @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Admin Telegram IDs (separated by comma)
# Example: ADMIN_IDS=123456789,987654321
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = [int(i.strip()) for i in ADMIN_IDS_RAW.split(",") if i.strip().isdigit()]

# Supplier LahaStore API Configuration
SUPPLIER_BASE_URL = os.getenv("SUPPLIER_BASE_URL", "https://lahastore.up.railway.app/api/v1").rstrip("/")
SUPPLIER_API_KEY = os.getenv("SUPPLIER_API_KEY", "psk_w8FN2yLrZ5XEovOCDLPf2diXbForvGO9X5k79bARmYt9Hs").strip()
SUPPLIER_SHOP_ID = os.getenv("SUPPLIER_SHOP_ID", "TG5075624178").strip()

# Map local products to Supplier Product IDs
# 14 = Gemini Pro — 18 Months (Links)
SUPPLIER_PRODUCT_MAP = {
    "gemini_18m": 14,
    "gemini_12m": 14,
}

# AccZone (Backup Supplier) API Configuration
ACCZONE_BASE_URL = os.getenv("ACCZONE_BASE_URL", "https://api.acczone.xyz").rstrip("/")
ACCZONE_API_KEY = os.getenv("ACCZONE_API_KEY", "Uw186NiI_zvEGO0SDFDxIPAW4CnhWTek3NY9UPr_34A").strip()
ACCZONE_PRODUCT_MAP = {
    "gemini_18m": "geminilive",
    "gemini_12m": "geminilive",
}

# Database File Path
DB_PATH = os.path.join(os.path.dirname(__file__), "gemini_store.db")

# Currency Name
CURRENCY = "دينار"

# Products Definition
PRODUCTS = {
    "gemini_18m": {
        "id": "gemini_18m",
        "name": "جيميني برو 18 شهر",
        "price": 1100,
        "description": "💎 اشتراك Google Gemini Pro أصلي لمدة 18 شهر مع ميزات الذكاء الاصطناعي المتقدمة.",
    },
    "gemini_12m": {
        "id": "gemini_12m",
        "name": "جيميني برو 12 شهر",
        "price": 1000,
        "description": "💎 اشتراك Google Gemini Pro أصلي لمدة 12 شهر مع ميزات الذكاء الاصطناعي المتقدمة.",
    },
}

# Payment Methods Definition (BaridiMob, RedotPay, Bybit)
PAYMENT_METHODS = {
    "baridimob": {
        "id": "baridimob",
        "name": "بريدي موب (BaridiMob)",
        "currency": "دينار",
        "is_crypto": False,
        "details": """🏦 **الدفع عبر بريدي موب (BaridiMob):**
• رقم الحساب / RIP: `00799999000123456789`
• الاسم: المتجر الرقمي
• الهاتف / المعرف: `0555000000`""",
    },
    "redotpay": {
        "id": "redotpay",
        "name": "RedotPay (2.5$)",
        "price_usd": 2.5,
        "currency": "$",
        "is_crypto": True,
        "details": """💳 **الدفع عبر RedotPay:**
• الـ UID الخاص بالحساب: `1445653765`
• نوع التحويل: تحويل داخلي عبر RedotPay ID (مجاني فوري بدون عمولة)""",
    },
    "bybit": {
        "id": "bybit",
        "name": "Bybit (2.5$)",
        "price_usd": 2.5,
        "currency": "$ (USDT)",
        "is_crypto": True,
        "details": """🟡 **الدفع عبر منصة Bybit:**
• الـ UID الخاص بالحساب: `593583401`
• العملة: USDT
• نوع التحويل: تحويل داخلي عبر Bybit UID (مجاني فوري بدون رسوم شبكة)""",
    },
}

# Default Payment Info (Fallback)
DEFAULT_PAYMENT_INFO = os.getenv(
    "PAYMENT_INFO",
    PAYMENT_METHODS["baridimob"]["details"],
)

# Proofs Channel Username or ID (e.g. @my_proofs_channel or -100xxxxxxxxxx)
PROOF_CHANNEL = os.getenv("PROOF_CHANNEL", "").strip()

