"""AI katmanı: şirket içi model uç noktası, istemler ve demo (mock) karşılıkları.

Görevler
1. extract_document   — dokümanı sınıflandırır, tarihini/özetini çıkarır, projelerle eşleştirir, bilgi (fact) çıkarır
2. project_synthesis  — bir projenin TÜM kaynaklarını (DT raporu, iç notlar, PDD, kazanım…) birleştirip yorumlar
3. portfolio_weekly   — son dönem dokümanlarından portföy yorumu
4. gap_analysis       — departmanlar × portföy boşluk ve odak analizi
5. advisor_answer     — kaynak göstererek soru-cevap (tam metin aramayla bağlam toplar)

Uç nokta tanımlı değilse (AI_PROVIDER=mock) kural tabanlı çıktılar üretilir.
"""
import json
import re
import time
from datetime import date, datetime, timedelta

import httpx

from . import config, db, knowledge
from .domain import (ACTIVE_STAGES, DOC_TYPES, FACT_FIELDS, HEALTH, MEASUREMENT_LABELS,
                     SECURITY_REVIEW_LABELS, STAGE_LABELS)

SYSTEM_PROMPT = """Sen Doğuş Otomotiv Dijital Dönüşüm ekibinin kıdemli AI danışmanısın.
Görevin: Doğuş Teknoloji (DT) ve iş birimleriyle yürütülen AI Impact projelerini takip eden Dijital Dönüşüm
ekibine ve Genel Müdür'e net, kanıta dayalı ve aksiyon odaklı tavsiyeler vermek.
Kurallar:
- Türkçe, kısa ve yönetici diline uygun yaz. Önce sonuç, sonra gerekçe.
- Yalnızca sana verilen verilere dayan; bilmediğini uydurma, eksik veriyi açıkça söyle.
- Proje atıflarında proje kodunu kullan (ör. AI-012). Bilgi bir dokümandan geliyorsa kaynağı [D12] biçiminde göster.
- Farklı kaynaklar çelişiyorsa bunu açıkça belirt (ör. DT raporu ile PDD'deki hedef tarih farklı).
- Ölçümlemesi olmayan canlı projeleri işaretle: ölçülmeyen etki, etki değildir.
"""


class AIError(Exception):
    pass


def is_live() -> bool:
    return config.AI_PROVIDER != "mock" and bool(config.AI_BASE_URL)


def provider_label() -> str:
    if not is_live():
        return "Demo modu (AI uç noktası bağlı değil)"
    return f"{config.AI_PROVIDER} · {config.AI_MODEL or 'varsayılan model'}"


# ---------------------------------------------------------------- düşük seviye çağrı

def _verify():
    if not config.AI_VERIFY_TLS:
        return False
    if config.AI_CA_BUNDLE:
        return config.AI_CA_BUNDLE
    if config.AI_USE_SYSTEM_CERTS:
        try:
            import ssl

            import truststore
            return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except ImportError:
            pass
    return True


def _client(timeout: float | None = None) -> httpx.Client:
    kwargs = {"timeout": timeout or config.AI_TIMEOUT, "verify": _verify()}
    if config.AI_PROXY:
        kwargs["proxy"] = config.AI_PROXY
    return httpx.Client(**kwargs)


def _auth_headers(default_header: str, bearer: bool) -> dict:
    h = {"Content-Type": "application/json", **config.AI_EXTRA_HEADERS}
    if config.AI_API_KEY:
        if config.AI_AUTH_HEADER:
            h[config.AI_AUTH_HEADER] = config.AI_API_KEY
        else:
            h[default_header] = f"Bearer {config.AI_API_KEY}" if bearer else config.AI_API_KEY
    return h


def complete(messages: list[dict], system: str = SYSTEM_PROMPT, json_mode: bool = False, max_tokens: int | None = None,
             retries: int = 3, timeout: float | None = None) -> str:
    if not is_live():
        raise AIError("mock")
    max_tokens = max_tokens or config.AI_MAX_TOKENS
    provider = config.AI_PROVIDER
    last_exc = None
    for attempt in range(retries):  # geçici hatalarda (429/5xx/zaman aşımı) yeniden dene
        try:
            with _client(timeout) as client:
                if provider == "anthropic":
                    body = {"model": config.AI_MODEL, "max_tokens": max_tokens, "system": system, "messages": messages,
                            "temperature": config.AI_TEMPERATURE}
                    headers = _auth_headers("x-api-key", bearer=False)
                    headers["anthropic-version"] = "2023-06-01"
                    base = config.AI_BASE_URL[:-3] if config.AI_BASE_URL.endswith("/v1") else config.AI_BASE_URL
                    r = client.post(f"{base}/v1/messages", headers=headers, json=body)
                    _raise(r)
                    return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
                body = {"messages": [{"role": "system", "content": system}, *messages], "max_tokens": max_tokens,
                        "temperature": config.AI_TEMPERATURE}
                if json_mode:
                    body["response_format"] = {"type": "json_object"}
                url = request_url()
                if provider in ("azure", "azure_v1", "azure_inference"):
                    headers = _auth_headers("api-key", bearer=False)
                else:
                    headers = _auth_headers("Authorization", bearer=True)
                if provider != "azure":  # klasik Azure'da model adresteki deployment'tır
                    body["model"] = config.AI_MODEL
                r = client.post(url, headers=headers, json=body)
                for _ in range(3):  # sunucunun desteklemediği parametreleri ayıklayıp yeniden dene
                    if r.status_code not in (400, 422):
                        break
                    err = r.text.lower()
                    if "max_tokens" in err and "max_completion_tokens" not in body:
                        body["max_completion_tokens"] = body.pop("max_tokens")      # o-serisi / gpt-5
                    elif "temperature" in err and "temperature" in body:
                        body.pop("temperature")
                    elif "response_format" in body:
                        body.pop("response_format")                                # JSON modu desteklenmiyor
                    else:
                        break
                    r = client.post(url, headers=headers, json=body)
                _raise(r)
                return r.json()["choices"][0]["message"]["content"] or ""
        except AIError as exc:
            last_exc = exc
            if not getattr(exc, "retry", False):
                raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = AIError(f"AI uç noktasına ulaşılamadı: {exc}")
        if attempt < retries - 1:
            time.sleep(2 * (attempt + 1))
    raise last_exc


def _raise(r: httpx.Response) -> None:
    if r.status_code >= 400:
        exc = AIError(f"AI uç noktası {r.status_code} döndü: {r.text[:500]}")
        exc.retry = r.status_code in (408, 409, 429) or r.status_code >= 500
        raise exc


def parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise AIError("AI yanıtı JSON içermiyor")
    return json.loads(text[start:end + 1])


def request_url() -> str:
    p, base = config.AI_PROVIDER, config.AI_BASE_URL
    if p == "anthropic":
        return f"{base[:-3] if base.endswith('/v1') else base}/v1/messages"
    if p == "azure":
        return f"{base}/openai/deployments/{config.AI_MODEL}/chat/completions?api-version={config.AI_AZURE_API_VERSION}"
    if p == "azure_inference":
        return f"{base}/chat/completions?api-version=2024-05-01-preview"
    return f"{base}/chat/completions"


def diagnose() -> dict:
    """AI bağlantısını adım adım dener; her adımda ne olduğunu ve ne yapılması gerektiğini söyler."""
    import os
    import socket
    from urllib.parse import urlparse

    steps = []

    def step(name, ok, detail, fix=None):
        steps.append({"name": name, "ok": ok, "detail": detail, "fix": fix})
        return ok

    # 1) ayar dosyası
    if not config.ENV_FILE and not config.AI_BASE_URL:
        step("Ayar dosyası (.env)", False, f"{config.BASE_DIR} klasöründe .env dosyası bulunamadı.",
             "Proje klasöründe (içinde app klasörü ve requirements.txt olan klasör) .env.example dosyasının kopyasını .env adıyla oluşturun.")
        return {"ok": False, "steps": steps}
    if not config.ENV_FILE:
        step("Ayar dosyası (.env)", True, "Dosya yok; ayarlar ortam değişkenlerinden okundu (ör. Docker env_file).")
    if config.ENV_FILE:
        note = " (adı .env.txt — çalışır, ama .env olarak yeniden adlandırmanız önerilir)" if config.ENV_FILE.name != ".env" else ""
        step("Ayar dosyası (.env)", True, f"Okundu: {config.ENV_FILE}{note}")
    # 2) değerler
    missing = [k for k, v in (("AI_BASE_URL", config.AI_BASE_URL), ("AI_API_KEY", config.AI_API_KEY), ("AI_MODEL", config.AI_MODEL)) if not v]
    if missing:
        in_file = [k for k in missing if k in config.ENV_KEYS]
        step("AI ayarları", False, "Boş: " + ", ".join(missing) + (" (dosyada satır var ama değer boş)" if in_file else ""),
             "Bu satırları .env dosyasında doldurun, kaydedin ve uygulamayı yeniden başlatın (terminalde Ctrl+C, sonra uvicorn app.main:app --reload).")
        if "AI_BASE_URL" in missing:
            return {"ok": False, "steps": steps}
    else:
        step("AI ayarları", True, f"Sağlayıcı: {config.AI_PROVIDER} · model/deployment: {config.AI_MODEL} · anahtar: …{config.AI_API_KEY[-4:]}"
             + (" · " + " · ".join(config.AI_URL_NOTES) if config.AI_URL_NOTES else ""))
    url = request_url()
    step("Çağrılacak adres", True, url)
    host = urlparse(config.AI_BASE_URL).hostname or ""
    port = urlparse(config.AI_BASE_URL).port or (443 if config.AI_BASE_URL.startswith("https") else 80)
    proxy = config.AI_PROXY or os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    if proxy:
        step("Proxy", True, f"İstekler şu proxy üzerinden gider: {proxy}")
    else:
        # 3) DNS ve 4) TCP (proxy yoksa doğrudan bağlantı denenir)
        try:
            ip = socket.gethostbyname(host)
            step("Adres çözümleme (DNS)", True, f"{host} → {ip}")
        except OSError as exc:
            step("Adres çözümleme (DNS)", False, f"{host} bulunamadı: {exc}",
                 "Adres yanlış yazılmış olabilir ya da bu ağdan görünmüyor olabilir (VPN gerekir mi?). Tarayıcıda adresi açmayı deneyin.")
            return {"ok": False, "steps": steps}
        try:
            with socket.create_connection((host, port), timeout=8):
                pass
            step("Ağ bağlantısı", True, f"{host}:{port} portuna ulaşıldı.")
        except OSError as exc:
            step("Ağ bağlantısı", False, f"{host}:{port} portuna bağlanılamadı: {exc}",
                 "Güvenlik duvarı ya da proxy engelliyor olabilir. Şirket ağında proxy gerekiyorsa .env dosyasına AI_PROXY=http://proxy-adresi:port ekleyin; "
                 "VPN gerekiyorsa bağlanın.")
            return {"ok": False, "steps": steps}
    # 5) gerçek istek
    t0 = time.time()
    try:
        out = complete([{"role": "user", "content": 'Sadece şu JSON\'u döndür: {"durum": "hazir"}'}], json_mode=True, max_tokens=50,
                       retries=1, timeout=45)
        step("Model yanıtı", True, f"{time.time() - t0:.1f} sn içinde yanıt geldi: {out[:160]}")
        return {"ok": True, "steps": steps}
    except Exception as exc:
        msg = str(exc)
        low = msg.lower()
        transport = msg.startswith("AI uç noktasına ulaşılamadı")
        if transport and proxy and ("403" in msg or "407" in msg or "proxy" in low or "tunnel" in low):
            fix = (f"İstek proxy üzerinden ({proxy}) gidiyor ve proxy bu adrese çıkışı reddetti. Uç nokta şirket içindeyse proxy'yi atlamak için "
                   f".env dosyasına NO_PROXY={host} ekleyin; dışarıdaysa BT'den bu adres için proxy izni isteyin. "
                   "Proxy kullanıcı adı/parola istiyorsa: AI_PROXY=http://kullanici:parola@proxy-adresi:port")
        elif transport and ("refused" in low or "reddedildi" in low):
            fix = "Sunucu bağlantıyı reddetti: adres doğru ama o portta servis yok. Port numarasını (ör. :443, :8000) ve http/https seçimini kontrol edin."
        elif transport and ("getaddrinfo" in low or "name or service" in low or "nodename" in low):
            fix = "Sunucu adı çözümlenemedi: adresi kontrol edin, VPN gerekiyorsa bağlanın."
        elif "certificate" in low or "ssl" in low:
            fix = ("Şirket ağının SSL sertifikası tanınmadı. Önce 'pip install -r requirements.txt' komutunu tekrar çalıştırın "
                   "(Windows sertifika deposunu kullanan truststore paketi kurulur). Düzelmezse BT'den şirket kök sertifikasını (.pem) alıp "
                   "AI_CA_BUNDLE=C:\\yol\\sirket.pem yazın. Yalnızca denemek için AI_VERIFY_TLS=0.")
        elif not transport and (" 401" in msg or " 403" in msg):
            fix = ("Anahtar reddedildi. AI_API_KEY'i kontrol edin (başında/sonunda boşluk ya da tırnak olmasın). Gateway anahtarı farklı bir başlıkta "
                   "bekliyorsa AI_AUTH_HEADER=api-key ya da AI_AUTH_HEADER=Ocp-Apim-Subscription-Key deneyin.")
        elif not transport and " 404" in msg and config.AI_PROVIDER.startswith("azure"):
            fix = ("Azure 'Resource not found' döndü: anahtar doğru, ama adres ya da deployment adı yanlış. Kontrol edin: "
                   "(1) AI_MODEL, Azure portalındaki model adı değil DEPLOYMENT adıdır (Azure AI Foundry → Deployments listesindeki 'Name'). "
                   "(2) AI_BASE_URL yalnızca kök olsun: https://<kaynak>.openai.azure.com (ya da .cognitiveservices.azure.com). "
                   "En kolayı: portaldaki 'Target URI' / 'Endpoint' adresini olduğu gibi AI_BASE_URL'e yapıştırın; uygulama deployment adını ve "
                   "api-version'ı oradan alır. (3) Deployment yeni oluşturulduysa birkaç dakika bekleyin.")
        elif not transport and " 404" in msg:
            fix = ("Adres ya da model bulunamadı. AI_BASE_URL genelde /v1 ile biter (OpenAI uyumlu). Yukarıdaki 'Çağrılacak adres'i API "
                   "sağlayıcınızın dokümanıyla karşılaştırın; AI_MODEL adını sağlayıcının listesindeki adla birebir yazın.")
        elif " 400" in msg or " 422" in msg:
            fix = "İstek reddedildi; çoğunlukla model adı yanlıştır. AI_MODEL değerini sağlayıcının listesindeki adla birebir yazın. Hata metni: yukarıda."
        elif " 429" in msg:
            fix = "Kota/hız sınırı. Biraz bekleyip tekrar deneyin ya da sağlayıcıdan kota isteyin."
        elif "timed out" in low or "timeout" in low:
            fix = "Zaman aşımı. Proxy gerekiyor olabilir (AI_PROXY) ya da model yavaş yanıt veriyor (AI_TIMEOUT=300)."
        elif "proxy" in low or "407" in msg:
            fix = "Proxy kimlik doğrulaması istiyor: AI_PROXY=http://kullanici:parola@proxy-adresi:port"
        else:
            fix = "Hata metnini BT ekibiyle ya da benimle paylaşın."
        step("Model yanıtı", False, msg[:700], fix)
        return {"ok": False, "steps": steps}


def test_connection() -> dict:
    """Geriye uyumluluk: tek satırlık sonuç."""
    d = diagnose()
    last = d["steps"][-1] if d["steps"] else {"detail": "", "fix": None}
    return {"ok": d["ok"], "message": last["detail"] + (f" → {last['fix']}" if last.get("fix") else ""), "steps": d["steps"]}


# ---------------------------------------------------------------- bağlam

def _money(v) -> str:
    return "—" if v is None else f"{v:,.0f} TL".replace(",", ".")


def portfolio_context() -> str:
    projects = db.rows("SELECT p.*, d.name AS dept FROM projects p LEFT JOIN departments d ON d.id = p.department_id ORDER BY code")
    kpis: dict[int, list] = {}
    for k in db.rows("SELECT * FROM kpis"):
        kpis.setdefault(k["project_id"], []).append(k)
    lines = [f"# AI Impact Portföyü ({date.today().isoformat()} itibarıyla, {len(projects)} proje)"]
    for p in projects:
        kp = "; ".join(f"{k['name']}: baseline {k['baseline']}, hedef {k['target']}, gerçekleşen {k['actual']} {k['unit'] or ''}"
                       for k in kpis.get(p["id"], [])) or "KPI tanımlı değil"
        lines.append(
            f"\n## {p['code']} — {p['name']}\n"
            f"Aşama: {STAGE_LABELS.get(p['stage'])} | Sağlık: {HEALTH.get(p['health'], ('?',))[0]} | Öncelik: {p['priority']} | "
            f"Departman: {p['dept'] or '—'} | AI tipi: {p['ai_type'] or '—'}\n"
            f"Sponsor: {p['sponsor'] or '—'} | DO sorumlusu: {p['owner'] or '—'} | DT sorumlusu: {p['dt_lead'] or '—'}\n"
            f"Başlangıç: {p['start_date'] or '—'} | Hedef canlı: {p['target_date'] or '—'} | Canlıya geçiş: {p['golive_date'] or '—'}\n"
            f"Ölçümleme: {MEASUREMENT_LABELS.get(p['measurement_status'])} | Tahmini değer: {_money(p['estimated_value'])}/yıl | "
            f"Gerçekleşen: {_money(p['realized_value'])}/yıl | FTE: {p['fte_saving'] or '—'} | "
            f"Güvenlik: {SECURITY_REVIEW_LABELS.get(p['security_review'])} | Son durum: {p['last_status_at'] or 'yok'}\n"
            f"Özet: {(p['summary'] or '')[:300]}\nKPI'lar: {kp}"
            + (f"\nSon risk notu (skor {p['ai_risk_score']}): {p['ai_risk_note'][:250]}" if p["ai_risk_note"] else "")
        )
    acts = db.rows("SELECT a.*, p.code FROM actions a LEFT JOIN projects p ON p.id = a.project_id WHERE a.status = 'acik'")
    if acts:
        lines.append("\n# Açık aksiyonlar")
        lines += [f"- [{a['code'] or 'Genel'}] {a['title']} — {a['owner'] or '?'} — termin {a['due_date'] or '—'}" for a in acts]
    return "\n".join(lines)


def departments_context() -> str:
    deps = db.rows("SELECT d.*, (SELECT COUNT(*) FROM projects p WHERE p.department_id = d.id AND p.stage != 'iptal') AS n "
                   "FROM departments d WHERE active = 1 ORDER BY sort, name")
    lines = ["# Departmanlar"]
    for d in deps:
        lines.append(f"- {d['name']} ({d['n']} proje){': ' + d['description'] if d['description'] else ''}"
                     f"{' | Ağrı noktaları: ' + d['pain_points'] if d['pain_points'] else ''}")
    return "\n".join(lines)


def security_context() -> str:
    from .security import METRICS
    data = db.rows("SELECT * FROM security_metrics ORDER BY period DESC LIMIT 60")
    return "# AI Güvenlik metrikleri (son dönemler)\n" + "\n".join(
        f"- {m['period']} · {METRICS.get(m['metric'], {}).get('label', m['metric'])}: {m['value']}" for m in reversed(data))


def _trim(text: str, limit: int | None = None) -> str:
    limit = limit or config.AI_MAX_CONTEXT_CHARS
    return text if len(text) <= limit else text[:limit] + "\n[...bağlam kısaltıldı...]"


def _catalog_text() -> str:
    rows = db.rows("SELECT p.code, p.name, p.aliases, p.stage, d.name AS dept FROM projects p LEFT JOIN departments d ON d.id = p.department_id ORDER BY code")
    return "\n".join(f"{r['code']} | {r['name']}" + (f" | diğer adlar: {r['aliases']}" if r["aliases"] else "")
                     + f" | {STAGE_LABELS[r['stage']]} | {r['dept'] or '—'}" for r in rows)


# ---------------------------------------------------------------- 1) doküman çıkarımı

def _fields_doc() -> str:
    parts = []
    for t, fields in FACT_FIELDS.items():
        parts.append(f'  - "{t}": field ∈ {{{", ".join(fields)}}}')
    return "\n".join(parts)


EXTRACT_PROMPT = """Aşağıda şirketin AI Impact portföyüne ait bir doküman (ya da büyük bir dokümanın bir parçası) var.
Görevin dokümanı okuyup YAPILANDIRILMIŞ bilgi çıkarmak. Yalnızca dokümanda yazanı çıkar; tahmin yürütme.

Doküman türleri: {types}

Bilgi türleri (facts[].type):
  - "durum": projenin o dönemki durumu (1-3 cümle, ilerleme % varsa yaz)
  - "risk": takılma riski ve nedeni — value_num: 0-100 risk skoru
  - "engel": engel / bağımlılık (kimden ne bekleniyor)
  - "sonraki_adim": planlanan sonraki adım
  - "karar": alınmış karar
  - "olcum": ölçüm yöntemi, veri kaynağı, ölçüm notu
  - "not": diğer önemli not / görüş
  - "saglik": önerilen sağlık — value: "yesil" | "sari" | "kirmizi", value_num: risk skoru 0-100
  - "asama": önerilen aşama — value ∈ {{{stages}}}
  - "tarih": tarih bilgisi — field ∈ {{start_date, target_date, golive_date}}, value: YYYY-MM-DD
  - "tanim" / "kazanim": proje alanı değeri — alanlar:
{fields}
    (kazanim'da sayısal alanlar için value_num kullan; TL değerleri tam sayı olarak, ör. 14,5 milyon → 14500000)
  - "kpi": KPI değeri — field: KPI adı (kısa, tutarlı), subfield: "baseline" | "target" | "actual", value_num, unit
  - "aksiyon": yapılması gereken iş — value: aksiyon, unit: sorumlu, as_of: termin (YYYY-MM-DD)

Türlere göre odak:
  - DT Durum Raporu: her proje için durum, risk, engel, sonraki adım, sağlık önerisi; tarih kaymaları
  - İç Notlar / Toplantı: karar, aksiyon, görüş/not, risk; ekibin DT raporuyla çeliştiği noktalar
  - PDD / Business Case: tanım alanları (problem, çözüm, sponsor…), hedef KPI'lar (baseline/target), tarihler, tahmini değer
  - Kazanım dokümanı: gerçekleşen değer (TL/FTE), KPI actual değerleri, ölçüm yöntemi, ölçümleme durumu
  - Takılma sinyalleri: tarih kayması, aynı engelin tekrarı, onay/veri/erişim beklenmesi, ilerleme durması, ekip değişikliği

Kurallar:
  - project_code yalnızca aşağıdaki katalogdan olabilir. Katalogda olmayan bir AI projesinden bahsediliyorsa new_projects'e yaz.
  - Her bilgi için evidence: dokümandan kısa birebir alıntı (en fazla 200 karakter). confidence: 0-1.
  - as_of: bilginin ait olduğu tarih (doküman tarihi ya da metinde geçen tarih), YYYY-MM-DD.

Sadece şu şemada geçerli JSON döndür:
{{"doc_type": "tür anahtarı", "doc_date": "YYYY-MM-DD veya null", "summary": "2-4 cümle özet",
 "projects": [{{"code": "AI-003", "confidence": 0.9}}],
 "new_projects": [{{"name": "...", "description": "..."}}],
 "facts": [{{"project_code": "AI-003", "type": "durum", "field": null, "subfield": null, "value": "...", "value_num": null,
            "unit": null, "as_of": "YYYY-MM-DD", "confidence": 0.8, "evidence": "..."}}]}}

=== PROJE KATALOĞU (kod | ad | diğer adlar | aşama | departman) ===
{catalog}

=== DOKÜMAN BİLGİSİ ===
Dosya adı: {filename}
Kullanıcının seçtiği tür: {declared}
Kaynak: {source}
Yükleme tarihi: {uploaded}
Parça: {part}

=== DOKÜMAN METNİ ===
{text}"""


def extract_document(doc: dict, text: str) -> dict:
    """Dokümanı pencereler hâlinde AI'a gönderir ve sonuçları birleştirir."""
    if not is_live():
        return _mock_extract(doc, text)
    budget = max(8000, config.AI_MAX_CONTEXT_CHARS - 12000)
    windows = [text[i:i + budget] for i in range(0, max(len(text), 1), budget)] or [""]
    merged = {"doc_type": None, "doc_date": None, "summary": None, "projects": [], "new_projects": [], "facts": []}
    types = "; ".join(f'"{k}" = {v[0]} ({v[1]})' for k, v in DOC_TYPES.items())
    for i, window in enumerate(windows[:12], 1):
        prompt = EXTRACT_PROMPT.format(
            types=types, stages=", ".join(STAGE_LABELS), fields=_fields_doc(), catalog=_catalog_text(),
            filename=doc["filename"], declared=DOC_TYPES[doc["doc_type"]][0] if doc["type_source"] == "kullanici" else "otomatik algıla",
            source=doc["source"] or "—", uploaded=doc["uploaded_at"][:10], part=f"{i}/{len(windows)}", text=window)
        res = parse_json(complete([{"role": "user", "content": prompt}], json_mode=True, max_tokens=max(config.AI_MAX_TOKENS, 6000)))
        merged["doc_type"] = merged["doc_type"] or res.get("doc_type")
        merged["doc_date"] = merged["doc_date"] or res.get("doc_date")
        merged["summary"] = merged["summary"] or res.get("summary")
        for key in ("projects", "new_projects", "facts"):
            merged[key] += [x for x in res.get(key) or [] if isinstance(x, dict)]
    if len(windows) > 12:
        merged["summary"] = (merged["summary"] or "") + f" (Not: doküman çok uzun; ilk {12 * budget:,} karakter analiz edildi.)"
    return merged


# --- demo modu: kural tabanlı çıkarım ------------------------------------------------

_TYPE_HINTS = [
    ("dt_durum", ("durum raporu", "haftalık rapor", "status report", "haftalik", "durum_raporu", "weekly")),
    ("kazanim", ("kazanım", "kazanim", "fayda", "benefit", "tasarruf")),
    ("pdd", ("pdd", "proje tanım", "project definition")),
    ("business_case", ("business case", "iş değeri", "is degeri")),
    ("pilot", ("pilot sonuç", "pilot raporu", "poc sonuç")),
    ("guvenlik", ("güvenlik değerlendirme", "risk değerlendirme", "security")),
    ("toplanti", ("toplantı", "komite", "tutanak", "minutes")),
    ("ic_not", ("iç not", "iç değerlendirme", "notlar", "değerlendirme notu", "gözlem", "notes")),
    ("teknik", ("teknik tasarım", "mimari", "gereksinim", "architecture")),
    ("sunum", ("sunum", "presentation")),
    ("sozlesme", ("sözleşme", "teklif", "contract", "proposal")),
]
_RISK_WORDS = {
    "gecik": (25, "gecikme bildirildi"), "ertelen": (20, "erteleme var"), "bekleniyor": (15, "dış bağımlılık bekleniyor"),
    "blok": (25, "bloke durum"), "engel": (20, "engel raporlandı"), "onay bekl": (20, "onay bekleniyor"),
    "erişim": (12, "veri/sistem erişimi sorunu"), "sorun": (12, "sorun raporlandı"), "kaydırıldı": (15, "ekip/kaynak kaybı"),
    "kaydı": (15, "tarih kaydı"), "revize": (8, "plan revize ediliyor"), "durdu": (30, "geliştirme durdu"),
    "askı": (25, "iş askıda"), "netleşmedi": (15, "belirsizlik var"), "düşük": (8, "kalite/doğruluk düşük"),
}


def guess_type(filename: str, text: str) -> str:
    """Önce dosya adına, sonra metnin başına bakar (dosya adı genelde daha güvenilir)."""
    for hay in (knowledge.norm(filename), knowledge.norm(text[:1500])):
        for t, words in _TYPE_HINTS:
            if any(knowledge.norm(w) in hay for w in words):
                return t
    return "diger"


def parse_number(s: str) -> float | None:
    s = s.strip().lower()
    m = re.search(r"(-?\d[\d.,]*)\s*(milyon|mn|m\b|bin|k\b)?", s)
    if not m:
        return None
    num, mult = m.group(1), m.group(2)
    if "," in num and "." in num:
        num = num.replace(".", "").replace(",", ".")
    elif "," in num:
        num = num.replace(",", ".")
    elif num.count(".") >= 1 and len(num.split(".")[-1]) == 3:
        num = num.replace(".", "")
    try:
        v = float(num)
    except ValueError:
        return None
    if mult in ("milyon", "mn", "m"):
        v *= 1_000_000
    elif mult in ("bin", "k"):
        v *= 1_000
    return v


_DATE_RE = re.compile(r"(\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{2}-\d{2})")


def _sentences(text: str) -> list[str]:
    return [s.strip(" -•\t") for s in re.split(r"(?<=[.!?])\s+|\n", text) if len(s.strip()) > 12]


def _row_pairs(body: str) -> list[tuple[str, str]]:
    """'Durum: … | Sonraki adım: …' biçimindeki tablo satırlarını (sütun, değer) çiftlerine ayırır."""
    out = []
    for line in body.splitlines():
        if " | " not in line:
            continue
        for cell in line.split(" | "):
            key, sep, val = cell.partition(": ")
            if sep and 0 < len(key) <= 40 and val.strip():
                out.append((key.strip(), val.strip()))
    return out


def _mock_extract(doc: dict, text: str) -> dict:
    doc_type = doc["doc_type"] if doc["type_source"] == "kullanici" else guess_type(doc["filename"], text)
    m = _DATE_RE.search(doc["filename"] + " " + text[:200])
    doc_date = knowledge._iso(m.group(1)) if m else None
    as_of = doc["doc_date"] or doc_date or doc["uploaded_at"][:10]
    chunks = db.rows("SELECT * FROM chunks WHERE document_id = ? AND project_id IS NOT NULL ORDER BY seq", (doc["id"],))
    codes = {r["id"]: r["code"] for r in db.rows("SELECT id, code FROM projects")}
    facts, seen = [], set()

    def add(pid, type_, value=None, **kw):
        facts.append({"project_code": codes[pid], "type": type_, "value": value, "as_of": kw.pop("as_of", as_of),
                      "confidence": kw.pop("confidence", 0.6), **kw})

    by_project: dict[int, str] = {}
    for c in chunks:
        by_project[c["project_id"]] = by_project.get(c["project_id"], "") + "\n" + c["text"]
    for pid, body in by_project.items():
        body = re.sub(r"^\s*[A-Z]{2,4}-\d+[^:\n]*:\s*", "", body.strip())
        sents = _sentences(body)
        low = body.lower()
        pairs = _row_pairs(body)
        if pairs:  # tablo satırı: sütun adlarına göre eşle
            for key, val in pairs:
                k = knowledge.norm(key)
                if any(w in k for w in ("durum", "status", "ilerleme", "aciklama", "yorum", "gelisme")):
                    add(pid, "durum", val[:500], evidence=f"{key}: {val}"[:200])
                elif any(w in k for w in ("engel", "bagimlilik", "blocker", "sorun", "issue")):
                    add(pid, "engel", val[:300], evidence=f"{key}: {val}"[:200])
                elif any(w in k for w in ("risk",)):
                    add(pid, "risk", val[:300], evidence=f"{key}: {val}"[:200])
                elif any(w in k for w in ("sonraki", "next", "plan", "aksiyon")):
                    add(pid, "sonraki_adim", val[:300], evidence=f"{key}: {val}"[:200])
                elif any(w in k for w in ("hedef", "bitis", "canli", "termin", "due")) and _DATE_RE.search(val):
                    add(pid, "tarih", knowledge._iso(_DATE_RE.search(val).group(1)),
                        field="golive_date" if "canli" in k and "hedef" not in k else "target_date", evidence=f"{key}: {val}"[:200])
        if doc_type in ("dt_durum", "ic_not", "toplanti", "pilot", "diger", "sunum") and not pairs:
            if sents:
                add(pid, "durum" if doc_type == "dt_durum" else "not", " ".join(sents[:2])[:500], evidence=sents[0][:200])
        if doc_type in ("dt_durum", "ic_not", "toplanti", "pilot", "diger", "sunum"):
            hits = [w for w in _RISK_WORDS if w in low]
            if doc_type == "dt_durum":
                score = min(95, 10 + sum(_RISK_WORDS[w][0] for w in hits))
                health = "kirmizi" if score >= 60 else "sari" if score >= 35 else "yesil"
                add(pid, "saglik", health, value_num=score,
                    evidence="; ".join(_RISK_WORDS[w][1] for w in hits[:3]) or "Belirgin risk sinyali yok")
            if hits and not pairs:
                add(pid, "risk", "; ".join(_RISK_WORDS[w][1] for w in hits[:3]).capitalize(), value_num=min(95, 10 + sum(_RISK_WORDS[w][0] for w in hits)))
            for s in ([] if pairs else sents):
                sl = s.lower()
                if sl.startswith("aksiyon"):
                    add(pid, "aksiyon", s.split(":", 1)[-1].strip()[:300], evidence=s[:200])
                elif sl.startswith("karar") or " karar:" in sl:
                    add(pid, "karar", s.split(":", 1)[-1].strip()[:300], evidence=s[:200])
                elif any(w in sl for w in ("bekl", "engel", "blok", "erişim", "onay")):
                    add(pid, "engel", s[:300], evidence=s[:200])
                elif any(w in sl for w in ("sonraki", "planlan", "gelecek hafta", "önümüzdeki")):
                    add(pid, "sonraki_adim", s[:300], evidence=s[:200])
                if any(w in sl for w in ("hedef tarih", "canlı tarihi", "canlıya geçiş")):
                    d = _DATE_RE.search(s)
                    if d:
                        add(pid, "tarih", knowledge._iso(d.group(1)), field="target_date" if "hedef" in sl else "golive_date", evidence=s[:200])
        if doc_type in ("pdd", "business_case", "kazanim", "pilot"):
            for line in body.splitlines():
                key, _, val = line.partition(":") if ":" in line.split("|")[0] else line.partition("|")
                k, v = knowledge.norm(key), val.strip()
                if not v:
                    continue
                if k in ("problem", "amac", "problem tanimi"):
                    add(pid, "tanim", v[:1500], field="problem", evidence=line[:200])
                elif k in ("cozum", "kapsam", "onerilen cozum"):
                    add(pid, "tanim", v[:1500], field="solution", evidence=line[:200])
                elif k in ("sponsor", "is birimi sponsoru"):
                    add(pid, "tanim", v[:200], field="sponsor", evidence=line[:200])
                elif k in ("baslangic", "baslangic tarihi") and _DATE_RE.search(v):
                    add(pid, "tarih", knowledge._iso(_DATE_RE.search(v).group(1)), field="start_date", evidence=line[:200])
                elif k in ("hedef canli tarihi", "hedef tarih", "canli tarihi") and _DATE_RE.search(v):
                    add(pid, "tarih", knowledge._iso(_DATE_RE.search(v).group(1)), field="target_date", evidence=line[:200])
                elif "gerceklesen" in k and ("tl" in v.lower() or "kazanim" in k or "deger" in k) and not k.startswith("kpi"):
                    add(pid, "kazanim", None, field="realized_value", value_num=parse_number(v), unit="TL", evidence=line[:200])
                elif ("tahmini" in k or "beklenen" in k) and "tl" in v.lower():
                    add(pid, "kazanim", None, field="estimated_value", value_num=parse_number(v), unit="TL", evidence=line[:200])
                elif "fte" in k:
                    add(pid, "kazanim", None, field="fte_saving", value_num=parse_number(v), evidence=line[:200])
                elif k.startswith("kpi"):
                    # "KPI: Garanti ret oranı | baseline 9,5 | hedef 5 | gerçekleşen 6,1 | %"
                    parts = [x.strip() for x in v.split("|")]
                    name = parts[0]
                    for part in parts[1:]:
                        pl = knowledge.norm(part)
                        sub = "baseline" if pl.startswith("baseline") else "target" if pl.startswith("hedef") else "actual" if pl.startswith("gerceklesen") else None
                        num = parse_number(part)
                        if sub and num is not None:
                            add(pid, "kpi", None, field=name, subfield=sub, value_num=num, unit=parts[-1] if len(parts[-1]) <= 6 else None, evidence=line[:200])
                elif "olcum yontemi" in k:
                    add(pid, "olcum", v[:500], evidence=line[:200])
    unique = []
    for f in facts:
        key = json.dumps(f, sort_keys=True, ensure_ascii=False)
        if (f.get("value") is not None or f.get("value_num") is not None) and key not in seen:
            seen.add(key)
            unique.append(f)
    facts = unique
    names = {codes[p] for p in by_project}
    summary = (f"{DOC_TYPES[doc_type][0]} · {len(names)} proje ile eşleşti ({', '.join(sorted(names)) or '—'}), {len(facts)} bilgi çıkarıldı. "
               "Demo modu: kural tabanlı çıkarım; AI uç noktası bağlanınca içerik gerçek modelle yorumlanır.")
    return {"doc_type": doc_type, "doc_date": doc_date, "summary": summary,
            "projects": [{"code": c, "confidence": 0.9} for c in names], "new_projects": [], "facts": facts}


# ---------------------------------------------------------------- 2) proje sentezi

SYNTH_PROMPT = """Aşağıda tek bir AI projesine ait TÜM kaynaklar var: proje kaydı, farklı dokümanlardan çıkarılmış bilgiler
(DT durum raporları, Dijital Dönüşüm iç notları, PDD, kazanım dokümanları vb.), ilgili doküman parçaları ve yorumlar.
Bu kaynakları BİRLEŞTİREREK düşün: kaynakları karşılaştır, zaman içindeki değişimi gör, çelişkileri bul.
Markdown, şu başlıklarla:
## Bütünleşik durum (3-5 cümle; DT ne diyor, iç notlarımız ne diyor, hangisi daha güncel)
## Kaynaklar arası çelişkiler ve boşluklar (tarih, değer, KPI, sorumlu farkları; hangi doküman eksik)
## Takılma riski (0-100 skor + gerekçe; sinyaller)
## Etki ve ölçümleme (PDD hedefi vs kazanım dokümanı gerçekleşeni; ölçüm güvenilirliği)
## Önerilen aksiyonlar (sahip + termin önerisiyle, en fazla 5)
Her önemli iddiada kaynağı [D<doküman no>] olarak göster."""


def project_synthesis(project_id: int) -> str:
    p = db.row("SELECT p.*, d.name AS dept FROM projects p LEFT JOIN departments d ON d.id = p.department_id WHERE p.id = ?", (project_id,))
    kpis = db.rows("SELECT name, unit, baseline, target, actual, method, measured_at FROM kpis WHERE project_id = ?", (project_id,))
    if is_live():
        chunks = knowledge.project_chunks(project_id, limit=40)
        docs_text = "\n\n".join(f"[D{c['document_id']}] {c['title']} ({DOC_TYPES[c['doc_type']][0]}, {c['doc_date'] or '—'}) · {c['heading'] or ''}\n{c['text']}"
                                for c in chunks)
        comments = db.rows("SELECT c.body, u.name, c.created_at FROM comments c JOIN users u ON u.id = c.user_id "
                           "WHERE target_type = 'project' AND target_id = ? AND kind NOT IN ('ai') ORDER BY c.id DESC LIMIT 15", (project_id,))
        content = (f"{SYNTH_PROMPT}\n\n=== PROJE KAYDI ===\n{json.dumps(p, ensure_ascii=False, default=str)}\nKPI: {json.dumps(kpis, ensure_ascii=False)}\n\n"
                   f"=== ÇIKARILMIŞ BİLGİLER (yeniden eskiye) ===\n{knowledge.facts_json(project_id)}\n\n"
                   f"=== YORUMLAR ===\n{json.dumps(comments, ensure_ascii=False)}\n\n=== DOKÜMAN PARÇALARI ===\n{docs_text}")
        return complete([{"role": "user", "content": _trim(content)}], max_tokens=3000)
    facts = knowledge.project_facts(project_id)
    conf = knowledge.conflicts(project_id)
    by_type: dict[str, list] = {}
    for f in facts:
        by_type.setdefault(f["doc_type"], []).append(f)
    srcs = ", ".join(f"{DOC_TYPES[t][0]} ({len(v)})" for t, v in by_type.items()) or "kaynak yok"
    last_dt = next((f for f in facts if f["doc_type"] == "dt_durum" and f["fact_type"] == "durum"), None)
    last_note = next((f for f in facts if f["doc_type"] in ("ic_not", "toplanti") and f["fact_type"] in ("not", "karar")), None)
    lines = ["> *Demo modu: kural tabanlı sentez. AI uç noktası bağlanınca kaynaklar modelle birlikte yorumlanır.*",
             "## Bütünleşik durum",
             f"{p['code']} **{STAGE_LABELS[p['stage']]}** aşamasında, sağlık **{HEALTH[p['health']][0]}**. Kaynaklar: {srcs}."]
    if last_dt:
        lines.append(f"- DT son durumu ({last_dt['as_of'] or last_dt['doc_date']}): {last_dt['display']} [D{last_dt['document_id']}]")
    if last_note:
        lines.append(f"- İç notlarımız ({last_note['as_of'] or last_note['doc_date']}): {last_note['display']} [D{last_note['document_id']}]")
    lines.append("\n## Kaynaklar arası çelişkiler ve boşluklar")
    if conf:
        for c in conf:
            lines.append(f"- **{c['label']}**: " + " · ".join(f"{f['display']} [D{f['document_id']}]" for f in c["facts"]))
    else:
        lines.append("- Çelişki tespit edilmedi.")
    have = set(by_type)
    missing = [DOC_TYPES[t][0] for t in ("pdd", "kazanim") if t not in have and p["stage"] in ("gelistirme", "pilot", "canli", "olcekleme")]
    if missing:
        lines.append(f"- Eksik doküman: {', '.join(missing)}")
    lines.append(f"\n## Takılma riski\nSkor: **{p['ai_risk_score'] if p['ai_risk_score'] is not None else '—'}**. "
                 + "; ".join(f["display"] for f in facts if f["fact_type"] == "risk")[:400])
    lines.append(f"\n## Etki ve ölçümleme\nÖlçümleme: **{MEASUREMENT_LABELS[p['measurement_status']]}**, {len(kpis)} KPI. "
                 f"Tahmini {_money(p['estimated_value'])}/yıl, gerçekleşen {_money(p['realized_value'])}/yıl.")
    lines.append("\n## Önerilen aksiyonlar\n- İnceleme kuyruğundaki önerileri onaylayın/reddedin.\n- Çelişen alanlar için kaynağı netleştirin.")
    return "\n".join(lines)


# ---------------------------------------------------------------- 3) portföy yorumu

WEEKLY_PROMPT = """Aşağıda AI Impact portföyü ve son 14 günde yüklenen dokümanlardan çıkarılan bilgiler var
(DT durum raporları ve Dijital Dönüşüm ekibinin iç notları birlikte). Genel Müdür için haftalık yorum yaz (markdown):
## Bu hafta öne çıkanlar (en fazla 5 madde)
## Takılan / takılabilecek projeler (kod, neden, ne yapılmalı)
## DT raporu ile iç notlarımız arasındaki farklar
## Raporda hiç geçmeyen aktif projeler
## Portföy gözlemleri (tekrar eden engeller, ölçümleme, kaynak)
Kaynakları [D<no>] olarak göster."""


def portfolio_weekly() -> str:
    since = (date.today() - timedelta(days=14)).isoformat()
    facts = db.rows("SELECT f.*, p.code, d.doc_type, d.title, d.doc_date FROM facts f JOIN projects p ON p.id = f.project_id "
                    "JOIN documents d ON d.id = f.document_id WHERE COALESCE(d.doc_date, substr(d.uploaded_at, 1, 10)) >= ? "
                    "AND f.status != 'reddedildi' ORDER BY p.code", (since,))
    mentioned = {f["code"] for f in facts}
    active = [r["code"] for r in db.rows("SELECT code, stage FROM projects") if r["stage"] in ACTIVE_STAGES]
    missing = [c for c in active if c not in mentioned]
    if is_live():
        rows = [f"[D{f['document_id']}] {f['code']} · {DOC_TYPES[f['doc_type']][0]} · {f['fact_type']} · "
                f"{knowledge.display_value(f)} · {(f['evidence'] or '')[:160]}" for f in facts]
        content = f"{WEEKLY_PROMPT}\n\n{_trim(portfolio_context(), 30000)}\n\n=== SON 14 GÜNÜN BİLGİLERİ ===\n" + "\n".join(rows)
        content += f"\n\nRaporda/notlarda geçmeyen aktif projeler: {', '.join(missing) or 'yok'}"
        return complete([{"role": "user", "content": _trim(content)}], max_tokens=3000)
    risky = sorted({(f["code"], f["value_num"] or 0, f["document_id"]) for f in facts if f["fact_type"] == "saglik" and f["value_text"] != "yesil"},
                   key=lambda x: -x[1])
    notes = [f for f in facts if f["doc_type"] in ("ic_not", "toplanti")]
    lines = ["> *Demo modu: kural tabanlı özet.*", "## Bu hafta öne çıkanlar",
             f"- Son 14 günde {len({f['document_id'] for f in facts})} dokümandan {len(facts)} bilgi çıkarıldı; {len(mentioned)} proje güncellendi."]
    lines.append("\n## Takılan / takılabilecek projeler")
    lines += [f"- **{c}** — risk {s:.0f} [D{d}]" for c, s, d in risky[:6]] or ["- Risk sinyali yok."]
    lines.append("\n## DT raporu ile iç notlarımız")
    lines += [f"- **{f['code']}**: {knowledge.display_value(f)[:200]} [D{f['document_id']}]" for f in notes[:5]] or ["- Bu dönem iç not yüklenmedi."]
    lines.append("\n## Raporda hiç geçmeyen aktif projeler")
    lines.append(f"- {', '.join(missing)} — DT'den durum istenmeli." if missing else "- Yok.")
    return "\n".join(lines)


# ---------------------------------------------------------------- 4) boşluk analizi

GAP_PROMPT = """Aşağıda şirketin departmanları (ağrı noktalarıyla), mevcut AI proje portföyü ve AI güvenlik metrikleri var.
Bir otomotiv distribütörü/ithalatçısı (çok markalı, bayi ağı, servis, yedek parça, filo/kiralama) için AI olgunluğunu
değerlendir ve markdown ile şu başlıklarla rapor yaz:
## Genel değerlendirme (3-4 cümle)
## Departman kapsama haritası (tablo: departman / durum: kapsanıyor-kısmen-boş / proje sayısı / not)
## Eksik olduğumuz alanlar (en az 5 öneri: problem, AI çözümü, tahmini etki, zorluk, öncelik)
## Odaklanmamız gereken 3 alan (neden şimdi?)
## Portföy sağlığı ve süreç önerileri
Sektör referansı verirken genel bilgi olduğunu belirt; şirkete özel rakam uydurma."""


def coverage() -> list[dict]:
    projects = db.rows("SELECT id, code, name, stage, department_id, health FROM projects WHERE stage != 'iptal'")
    out = []
    for d in db.rows("SELECT * FROM departments WHERE active = 1 ORDER BY sort, name"):
        ps = [p for p in projects if p["department_id"] == d["id"]]
        live = [p for p in ps if p["stage"] in ("canli", "olcekleme")]
        out.append({"id": d["id"], "area": d["name"], "projects": ps, "live": len(live),
                    "level": "boş" if not ps else "kapsanıyor" if live else "kısmen"})
    return out


def gap_analysis() -> str:
    if is_live():
        content = f"{GAP_PROMPT}\n\n{departments_context()}\n\n{_trim(portfolio_context(), 40000)}\n\n{security_context()}"
        return complete([{"role": "user", "content": content}], max_tokens=6000)
    cov = coverage()
    empty = [c for c in cov if c["level"] == "boş"]
    partial = [c for c in cov if c["level"] == "kısmen"]
    unmeasured = db.rows("SELECT code FROM projects WHERE stage IN ('canli','olcekleme') AND measurement_status IN ('yok','planlandi')")
    lines = ["> *Demo modu: kural tabanlı rapor. AI uç noktası bağlanınca departmanlar ve portföy modelle yorumlanır.*",
             "\n## Genel değerlendirme",
             f"{len(cov)} departmanın **{len(cov) - len(empty)}** tanesinde AI girişimi var; **{len(empty)}** departman boş. "
             f"Canlıdaki projelerin **{len(unmeasured)}** tanesinde etki ölçülmüyor.",
             "\n## Departman kapsama haritası", "| Departman | Durum | Proje | Canlı |", "|---|---|---|---|"]
    lines += [f"| {c['area']} | {c['level']} | {len(c['projects'])} | {c['live']} |" for c in cov]
    lines.append("\n## Odaklanmamız gereken 3 alan")
    lines += [f"{i}. **{c['area']}** — {'hiç proje yok' if not c['projects'] else 'canlıya çıkmış proje yok'}." for i, c in enumerate((empty + partial)[:3], 1)]
    if unmeasured:
        lines.append("\n## Portföy sağlığı\n- Ölçümlemesi olmayan canlı projeler: " + ", ".join(f"**{u['code']}**" for u in unmeasured))
    return "\n".join(lines)


# ---------------------------------------------------------------- 5) danışman

def advisor_answer(history: list[dict], question: str) -> tuple[str, list[dict]]:
    """Dönüş: (yanıt, kullanılan kaynak parçaları)"""
    codes = {r["code"].upper(): r["id"] for r in db.rows("SELECT id, code FROM projects")}
    asked = [codes[c.upper()] for c in re.findall(r"\b[A-Za-z]{2,4}-\d{1,4}\b", question) if c.upper() in codes]
    hits = knowledge.search(question, limit=10, project_ids=asked or None)
    if asked and len(hits) < 6:
        hits += [h for h in knowledge.project_chunks(asked[0], limit=8) if h["id"] not in {x["id"] for x in hits}]
    if is_live():
        sources = "\n\n".join(f"[D{h['document_id']}] {h['title']} ({DOC_TYPES[h['doc_type']][0]}, {h['doc_date'] or '—'})\n{h['text'][:1800]}"
                              for h in hits)
        facts = "\n".join(knowledge.facts_json(pid, 60) for pid in asked[:3])
        context = ("Aşağıdaki şirket verilerini bağlam olarak kullan. Soru genel AI bilgisiyle ilgiliyse genel bilgini kullan "
                   "ama şirket bağlamına bağla. Doküman kaynaklarını [D<no>] olarak göster.\n\n"
                   f"{_trim(portfolio_context(), 30000)}\n\n{departments_context()}\n\n{security_context()}\n\n"
                   f"=== İLGİLİ DOKÜMAN PARÇALARI ===\n{sources or 'bulunamadı'}\n\n=== SORUDAKİ PROJELERİN BİLGİLERİ ===\n{facts or '—'}")
        msgs = [{"role": "user", "content": _trim(context)}, {"role": "assistant", "content": "Bağlamı aldım. Sorunuzu bekliyorum."}]
        msgs += [{"role": m["role"], "content": m["content"]} for m in history[-8:]]
        msgs.append({"role": "user", "content": question})
        return complete(msgs, max_tokens=3000), hits
    return _mock_answer(question, hits), hits


def _mock_answer(q: str, hits: list[dict]) -> str:
    ql = q.lower()
    projects = db.rows("SELECT * FROM projects")
    src = ""
    if hits:
        src = "\n\n**İlgili doküman parçaları:**\n" + "\n".join(
            f"- [D{h['document_id']}] {h['title']}: {(h.get('snip') or h['text'][:160]).replace('[[', '**').replace(']]', '**')}" for h in hits[:5])
    if any(w in ql for w in ("risk", "takıl", "gecik", "kırmızı")):
        risky = sorted([p for p in projects if p["health"] != "yesil"], key=lambda p: -(p["ai_risk_score"] or 0))
        return ("**Risk altındaki projeler:**\n\n" + "\n".join(
            f"- **{p['code']} {p['name']}** — {HEALTH[p['health']][0]}, {STAGE_LABELS[p['stage']]}. {p['ai_risk_note'] or ''}" for p in risky[:8])
            + src + "\n\n_Demo modu yanıtı._")
    if any(w in ql for w in ("ölç", "kpi", "etki", "değer", "kazanım")):
        live = [p for p in projects if p["stage"] in ("canli", "olcekleme")]
        um = [p for p in live if p["measurement_status"] in ("yok", "planlandi")]
        return (f"Canlıda **{len(live)}** proje var; **{len(um)}** tanesinde ölçüm yok ({', '.join(p['code'] for p in um) or '—'}). "
                f"Gerçekleşen toplam yıllık etki: **{_money(sum(p['realized_value'] or 0 for p in projects))}**." + src + "\n\n_Demo modu yanıtı._")
    return ("Demo modundayım: AI uç noktası bağlandığında portföy ve dokümanlar üzerinden yanıt vereceğim." + src)


def stale_projects(days: int = 14) -> list[dict]:
    limit = (datetime.now() - timedelta(days=days)).isoformat()
    return db.rows("SELECT * FROM projects WHERE stage IN ('analiz','onay','gelistirme','pilot') "
                   "AND (last_status_at IS NULL OR last_status_at < ?) ORDER BY last_status_at", (limit,))
