"""Uygulama ayarları. Tüm değerler ortam değişkenlerinden (.env) okunur."""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value[:1] in ('"', "'") and value[-1:] == value[:1]:
            value = value[1:-1]
        elif " #" in value:  # satır sonu yorumu: AI_PROVIDER=openai   # açıklama
            value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(key.strip(), value)


_load_dotenv()

APP_NAME = os.getenv("APP_NAME", "AI Impact Merkezi")
ORG_NAME = os.getenv("ORG_NAME", "Doğuş Otomotiv · Dijital Dönüşüm")
SECRET_KEY = os.getenv("SECRET_KEY", "degistir-beni-uretimde")
SEED_DEMO = os.getenv("SEED_DEMO", "1") == "1"  # demo verisi "Ayarlar > Demo verisini temizle" ile kalıcı kaldırılır
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "12"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"

# Giriş ekranı. 0 iken herkes doğrudan "Dijital Dönüşüm Ekibi" kullanıcısıyla girer.
# Kullanıcı/rol altyapısı yerinde durur; AUTH_ENABLED=1 yapılınca giriş ekranı geri gelir.
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "0") == "1"

# --- Depolama ---
# DATA_DIR: veritabanı (app.db) ve iş dosyaları.
# STORAGE_DIR: yüklenen dokümanların kendisi. Ayrı bir diske / NAS paylaşımına bağlanabilir.
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "app.db"
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", DATA_DIR / "files"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))
# Eski Office formatlarını (.doc .ppt .xls .rtf .odt) dönüştürmek için LibreOffice yolu (boşsa otomatik aranır)
SOFFICE_PATH = os.getenv("SOFFICE_PATH", "")

# --- Şirket içi AI uç noktası ---
# AI_PROVIDER: "auto" (varsayılan; adresten tahmin), "openai" (OpenAI uyumlu /chat/completions — vLLM, LiteLLM,
#              Ollama, kurumsal gateway), "azure" (Azure OpenAI), "anthropic" (Messages API).
#              AI_BASE_URL boşsa demo (mock) modunda çalışılır.
AI_BASE_URL = os.getenv("AI_BASE_URL", "").strip().rstrip("/")
for _suffix in ("/chat/completions", "/v1/messages"):  # yanlışlıkla tam uç nokta yazıldıysa
    if AI_BASE_URL.endswith(_suffix):
        AI_BASE_URL = AI_BASE_URL[: -len(_suffix)]
AI_PROVIDER_SET = os.getenv("AI_PROVIDER", "auto").strip().lower() or "auto"
# "auto" ya da adres girilmiş ama "mock" bırakılmışsa sağlayıcı adresten tahmin edilir.
if AI_PROVIDER_SET in ("auto", "mock") and AI_BASE_URL:
    AI_PROVIDER = "azure" if ".openai.azure.com" in AI_BASE_URL else "anthropic" if "anthropic" in AI_BASE_URL else "openai"
else:
    AI_PROVIDER = AI_PROVIDER_SET if AI_BASE_URL else "mock"
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "")
AI_AZURE_API_VERSION = os.getenv("AI_AZURE_API_VERSION", "2024-10-21")
# Anahtarın gönderileceği başlık. Boşsa sağlayıcının varsayılanı (Authorization: Bearer / api-key / x-api-key).
# Örn. API Management arkasındaysa: AI_AUTH_HEADER=Ocp-Apim-Subscription-Key
AI_AUTH_HEADER = os.getenv("AI_AUTH_HEADER", "")
try:
    AI_EXTRA_HEADERS = json.loads(os.getenv("AI_EXTRA_HEADERS", "") or "{}")
except json.JSONDecodeError:
    AI_EXTRA_HEADERS = {}
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT", "180"))
AI_VERIFY_TLS = os.getenv("AI_VERIFY_TLS", "1") == "1"
AI_CA_BUNDLE = os.getenv("AI_CA_BUNDLE", "")
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.2"))
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "4000"))
# Tek AI çağrısına gönderilecek en fazla metin (karakter). Modelin bağlam penceresine göre ayarlayın
# (yaklaşık 1 token ≈ 3-4 karakter Türkçe). Büyük dokümanlar bu boyutta parçalara bölünür.
AI_MAX_CONTEXT_CHARS = int(os.getenv("AI_MAX_CONTEXT_CHARS", "60000"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
