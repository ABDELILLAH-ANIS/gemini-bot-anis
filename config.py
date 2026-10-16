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
# Map local products to Supplier Product IDs (LahaStore)
SUPPLIER_PRODUCT_MAP = {
    "gemini_18m": 14,
    "gemini_12m": 14,
    "chatgpt_plus_4m": 90,
    "codex_api_10m": 36,
    "claude_api_10m": 32,
    "capcut_pro_30d": 21,
    "duolingo_12m": 74,
}

# AccZone API Configuration
ACCZONE_BASE_URL = os.getenv("ACCZONE_BASE_URL", "https://api.acczone.xyz").rstrip("/")
ACCZONE_API_KEY = os.getenv("ACCZONE_API_KEY", "Uw186NiI_zvEGO0SDFDxIPAW4CnhWTek3NY9UPr_34A").strip()
ACCZONE_PRODUCT_MAP = {
    "gemini_18m": "geminilive",
    "gemini_12m": "geminilive",
    "duolingo_12m": "DUOLINGO",
    "adobe_express_12m": "ADOBE_EXPRESS",
    "apple_music_5m": "APPLE_MUSIC_PREPAID_V2",
}

# DigitalCore API Configuration (Primary stock provider)
DIGITALCORE_BASE_URL = os.getenv("DIGITALCORE_BASE_URL", "https://digitalcore.top").rstrip("/")
DIGITALCORE_API_KEY = os.getenv("DIGITALCORE_API_KEY", "6362479e-f69b-4c84-a57d-f425365a16a9").strip()
DIGITALCORE_PRODUCT_MAP = {
    "gemini_18m": "gemini_pro_18_months",
    "gemini_3m": "gemini_pro_3_months",
    "duolingo_12m": "duolingo_super_12_months",
    "adobe_express_4m": "adobe_express_4_months_trial",
    "youtube_premium_3m": "youtube_premium_3_months",
    "nordvpn_3m": "nordvpn_3_months_basic",
    "coursera_12m": "coursera_premium_12_months",
    "lovable_pro_12m": "lovable_pro_lite_12_months_+_300_credits",
    "elevenlabs_creator_3m": "elevenlabs_creator_3_months",
}

# Database File Path (Local fallback cache)
DB_PATH = os.path.join(os.path.dirname(__file__), "gemini_store.db")

# Supabase Cloud Database Configuration (Persistent storage across redeploys)
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://nqjibgbmcpkimqzczmkk.supabase.co").rstrip("/")
SUPABASE_KEY = os.getenv(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5xamliZ2JtY3BraW1xemN6bWtrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQxMjMzNjIsImV4cCI6MjA5OTY5OTM2Mn0.jB4_ohSnRoQMkVD7gtjFBNaZn3hWXJMCK60bLAaVoYs",
).strip()

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

