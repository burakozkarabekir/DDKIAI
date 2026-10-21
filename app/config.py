"""Uygulama ayarları. Tüm değerler ortam değişkenlerinden (.env) okunur."""
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
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

APP_NAME = os.getenv("APP_NAME", "AI Impact Merkezi")
ORG_NAME = os.getenv("ORG_NAME", "Doğuş Otomotiv · Dijital Dönüşüm")
SECRET_KEY = os.getenv("SECRET_KEY", "degistir-beni-uretimde")
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "app.db"
UPLOAD_DIR = DATA_DIR / "uploads"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
SEED_DEMO = os.getenv("SEED_DEMO", "1") == "1"
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "12"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"

# --- Şirket içi AI uç noktası ---
# AI_PROVIDER: "openai" (OpenAI uyumlu /chat/completions — vLLM, LiteLLM, Ollama, OpenAI vb.),
#              "azure" (Azure OpenAI), "anthropic" (Messages API) veya "mock" (demo modu)
AI_PROVIDER = os.getenv("AI_PROVIDER", "mock").lower()
AI_BASE_URL = os.getenv("AI_BASE_URL", "").rstrip("/")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "")
AI_AZURE_API_VERSION = os.getenv("AI_AZURE_API_VERSION", "2024-10-21")
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT", "120"))
AI_VERIFY_TLS = os.getenv("AI_VERIFY_TLS", "1") == "1"
AI_MAX_CONTEXT_CHARS = int(os.getenv("AI_MAX_CONTEXT_CHARS", "60000"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
