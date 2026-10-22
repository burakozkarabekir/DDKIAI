"""Uygulama ayarları. Tüm değerler ortam değişkenlerinden (.env) okunur."""
import json
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


ENV_FILE: Path | None = None   # okunan ayar dosyası (tanılama için)
ENV_KEYS: list[str] = []       # dosyada bulunan anahtarlar


def _load_dotenv() -> None:
    global ENV_FILE
    # Windows Not Defteri dosyayı ".env.txt" olarak kaydedebilir; o da kabul edilir.
    env_file = next((f for f in (BASE_DIR / ".env", BASE_DIR / ".env.txt") if f.exists()), None)
    if not env_file:
        return
    ENV_FILE = env_file
    for line in env_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value[:1] in ('"', "'") and value[-1:] == value[:1]:
            value = value[1:-1]
        elif " #" in value:  # satır sonu yorumu: AI_PROVIDER=openai   # açıklama
            value = value.split(" #", 1)[0].strip()
        ENV_KEYS.append(key.strip())
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
AI_MODEL = os.getenv("AI_MODEL", "").strip()
AI_AZURE_API_VERSION = os.getenv("AI_AZURE_API_VERSION", "2024-10-21").strip()
AI_BASE_URL_RAW = os.getenv("AI_BASE_URL", "").strip()
AI_URL_NOTES: list[str] = []   # adresten otomatik düzeltilenler (Ayarlar'da gösterilir)


def _normalize_url(raw: str) -> str:
    """Kullanıcının yapıştırdığı adresi köke indirger; Azure tam yolundan deployment ve api-version'ı çıkarır."""
    global AI_MODEL, AI_AZURE_API_VERSION
    from urllib.parse import parse_qs, urlparse
    url = raw.strip().strip('"').strip("'")
    if not url:
        return ""
    q = parse_qs(urlparse(url).query)
    if q.get("api-version"):
        AI_AZURE_API_VERSION = q["api-version"][0]
        AI_URL_NOTES.append(f"api-version adresten alındı: {AI_AZURE_API_VERSION}")
    url = url.split("?", 1)[0].rstrip("/")
    m = re.search(r"^(.*?)/openai/deployments/([^/]+)", url)
    if m:  # https://x.openai.azure.com/openai/deployments/gpt-4o/chat/completions
        if AI_MODEL and AI_MODEL != m.group(2):
            AI_URL_NOTES.append(f"AI_MODEL ({AI_MODEL}) yerine adresteki deployment adı kullanıldı: {m.group(2)}")
        elif not AI_MODEL:
            AI_URL_NOTES.append(f"Deployment adı adresten alındı: {m.group(2)}")
        AI_MODEL = m.group(2)
        return m.group(1)
    for suffix in ("/chat/completions", "/v1/messages", "/completions"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            AI_URL_NOTES.append(f"Adresin sonundaki {suffix} kaldırıldı (uygulama kendisi ekler).")
    return url


AI_BASE_URL = _normalize_url(AI_BASE_URL_RAW)
AI_PROVIDER_SET = os.getenv("AI_PROVIDER", "auto").strip().lower() or "auto"


def _detect_provider(url: str) -> str:
    host = url.split("/")[2].lower() if "://" in url else url.lower()
    path = url.lower()
    if host.endswith(".azure.com") or ".azure." in host:
        if path.endswith("/openai/v1"):
            return "azure_v1"          # Azure OpenAI v1 API (OpenAI biçimi + api-key)
        if path.endswith("/models"):
            return "azure_inference"   # Azure AI Foundry model çıkarım uç noktası
        return "azure"                 # klasik: /openai/deployments/{deployment}/chat/completions
    if "anthropic" in url:
        return "anthropic"
    return "openai"


# "auto" ya da adres girilmiş ama "mock" bırakılmışsa sağlayıcı adresten tahmin edilir.
if AI_PROVIDER_SET in ("auto", "mock") and AI_BASE_URL:
    AI_PROVIDER = _detect_provider(AI_BASE_URL)
elif AI_PROVIDER_SET == "azure" and AI_BASE_URL:
    AI_PROVIDER = _detect_provider(AI_BASE_URL) if ".azure" in AI_BASE_URL else "azure"
else:
    AI_PROVIDER = AI_PROVIDER_SET if AI_BASE_URL else "mock"
AI_API_KEY = os.getenv("AI_API_KEY", "")
# Anahtarın gönderileceği başlık. Boşsa sağlayıcının varsayılanı (Authorization: Bearer / api-key / x-api-key).
# Örn. API Management arkasındaysa: AI_AUTH_HEADER=Ocp-Apim-Subscription-Key
AI_AUTH_HEADER = os.getenv("AI_AUTH_HEADER", "")
try:
    AI_EXTRA_HEADERS = json.loads(os.getenv("AI_EXTRA_HEADERS", "") or "{}")
except json.JSONDecodeError:
    AI_EXTRA_HEADERS = {}
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT", "180"))
AI_VERIFY_TLS = os.getenv("AI_VERIFY_TLS", "1") == "1"
# Şirket ağları SSL trafiğini kendi sertifikalarıyla inceler; 1 iken işletim sisteminin (Windows/macOS) sertifika
# deposu kullanılır, böylece şirket sertifikası ayrıca tanıtılmadan kabul edilir.
AI_USE_SYSTEM_CERTS = os.getenv("AI_USE_SYSTEM_CERTS", "1") == "1"
# Uç noktaya bir proxy üzerinden çıkılıyorsa: AI_PROXY=http://proxy.sirket.local:8080 (boşsa HTTPS_PROXY ortam değişkeni)
AI_PROXY = os.getenv("AI_PROXY", "").strip()
# Not: .env'deki NO_PROXY / HTTPS_PROXY satırları ortam değişkeni olarak yüklenir ve HTTP istemcisi tarafından kullanılır.
AI_CA_BUNDLE = os.getenv("AI_CA_BUNDLE", "")
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.2"))
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "4000"))
# Tek AI çağrısına gönderilecek en fazla metin (karakter). Modelin bağlam penceresine göre ayarlayın
# (yaklaşık 1 token ≈ 3-4 karakter Türkçe). Büyük dokümanlar bu boyutta parçalara bölünür.
AI_MAX_CONTEXT_CHARS = int(os.getenv("AI_MAX_CONTEXT_CHARS", "60000"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
