"""AI Danışman katmanı.

Şirket içi AI uç noktasına bağlanır (OpenAI uyumlu, Azure OpenAI veya Anthropic). Uç nokta
tanımlı değilse "mock" modunda kural tabanlı çıktılar üretir; böylece arayüz ve süreç
AI bağlanmadan da denenebilir.
"""
import json
import re
from datetime import date, datetime, timedelta

import httpx

from . import config, db
from .domain import (ACTIVE_STAGES, HEALTH, MEASUREMENT_LABELS, SECURITY_REVIEW_LABELS,
                     STAGE_LABELS, VALUE_CHAIN)

SYSTEM_PROMPT = """Sen Doğuş Otomotiv Dijital Dönüşüm ekibinin kıdemli AI danışmanısın.
Görevin: Doğuş Teknoloji (DT) tarafından geliştirilen AI Impact projelerini takip eden
Genel Müdür ve ekibine net, kanıta dayalı ve aksiyon odaklı tavsiyeler vermek.
Kurallar:
- Türkçe, kısa ve yönetici diline uygun yaz. Önce sonuç, sonra gerekçe.
- Yalnızca sana verilen bağlamdaki verilere dayan; bilmediğin şeyi uydurma, eksik veriyi açıkça söyle.
- Proje atıflarında proje kodunu kullan (ör. AI-012).
- Riskleri "ne oldu → neden önemli → ne yapılmalı → kim" yapısında öner.
- Ölçümlemesi olmayan canlı projeleri her zaman işaretle: ölçülmeyen etki, etki değildir.
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

def complete(messages: list[dict], system: str = SYSTEM_PROMPT, json_mode: bool = False, max_tokens: int = 4000) -> str:
    if not is_live():
        raise AIError("mock")
    provider = config.AI_PROVIDER
    headers = {"Content-Type": "application/json"}
    with httpx.Client(timeout=config.AI_TIMEOUT, verify=config.AI_VERIFY_TLS) as client:
        if provider == "anthropic":
            headers.update({"x-api-key": config.AI_API_KEY, "anthropic-version": "2023-06-01"})
            body = {"model": config.AI_MODEL, "max_tokens": max_tokens, "system": system, "messages": messages}
            r = client.post(f"{config.AI_BASE_URL}/v1/messages", headers=headers, json=body)
            _raise(r)
            data = r.json()
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

        body = {"messages": [{"role": "system", "content": system}, *messages], "max_tokens": max_tokens, "temperature": 0.2}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if provider == "azure":
            headers["api-key"] = config.AI_API_KEY
            url = f"{config.AI_BASE_URL}/openai/deployments/{config.AI_MODEL}/chat/completions?api-version={config.AI_AZURE_API_VERSION}"
        else:
            if config.AI_API_KEY:
                headers["Authorization"] = f"Bearer {config.AI_API_KEY}"
            body["model"] = config.AI_MODEL
            url = f"{config.AI_BASE_URL}/chat/completions"
        r = client.post(url, headers=headers, json=body)
        if r.status_code == 400 and json_mode:  # bazı sunucular response_format desteklemez
            body.pop("response_format", None)
            r = client.post(url, headers=headers, json=body)
        _raise(r)
        return r.json()["choices"][0]["message"]["content"] or ""


def _raise(r: httpx.Response) -> None:
    if r.status_code >= 400:
        raise AIError(f"AI uç noktası {r.status_code} döndü: {r.text[:500]}")


def parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise AIError("AI yanıtı JSON içermiyor")
    return json.loads(text[start:end + 1])


# ---------------------------------------------------------------- bağlam üretimi

def _fmt_money(v) -> str:
    return "—" if v is None else f"{v:,.0f} TL".replace(",", ".")


def portfolio_context(include_internal: bool = True) -> str:
    projects = db.rows("SELECT * FROM projects ORDER BY code")
    kpis = db.rows("SELECT * FROM kpis")
    by_project: dict[int, list] = {}
    for k in kpis:
        by_project.setdefault(k["project_id"], []).append(k)
    open_actions = db.rows("SELECT a.*, p.code FROM actions a LEFT JOIN projects p ON p.id = a.project_id WHERE a.status = 'acik'")
    lines = [f"# AI Impact Portföyü ({date.today().isoformat()} itibarıyla, {len(projects)} proje)"]
    for p in projects:
        kp = "; ".join(
            f"{k['name']}: baseline {k['baseline']}, hedef {k['target']}, gerçekleşen {k['actual']} {k['unit'] or ''}"
            for k in by_project.get(p["id"], [])
        ) or "KPI tanımlı değil"
        lines.append(
            f"\n## {p['code']} — {p['name']}\n"
            f"Aşama: {STAGE_LABELS.get(p['stage'])} | Sağlık: {HEALTH.get(p['health'], ('?',))[0]} | Öncelik: {p['priority']}\n"
            f"Değer zinciri: {p['value_chain']} | Birim: {p['business_unit']} | Markalar: {p['brands']} | AI tipi: {p['ai_type']}\n"
            f"Sponsor: {p['sponsor']} | DO sorumlusu: {p['owner']} | DT sorumlusu: {p['dt_lead']}\n"
            f"Başlangıç: {p['start_date']} | Hedef canlı: {p['target_date']} | Canlıya geçiş: {p['golive_date']}\n"
            f"Ölçümleme: {MEASUREMENT_LABELS.get(p['measurement_status'])} | Tahmini değer: {_fmt_money(p['estimated_value'])}/yıl | "
            f"Gerçekleşen: {_fmt_money(p['realized_value'])}/yıl | FTE: {p['fte_saving'] or '—'}\n"
            f"Güvenlik değerlendirmesi: {SECURITY_REVIEW_LABELS.get(p['security_review'])} | Veri sınıfı: {p['data_class'] or '—'}\n"
            f"Son durum güncellemesi: {p['last_status_at'] or 'yok'}\n"
            f"Özet: {(p['summary'] or '')[:400]}\nKPI'lar: {kp}"
        )
        if include_internal and p["ai_risk_note"]:
            lines.append(f"Son AI risk notu (skor {p['ai_risk_score']}): {p['ai_risk_note'][:300]}")
    if open_actions:
        lines.append("\n# Açık aksiyonlar")
        for a in open_actions:
            lines.append(f"- [{a['code'] or 'Genel'}] {a['title']} — {a['owner'] or '?'} — termin {a['due_date'] or '—'}")
    return "\n".join(lines)


def org_context() -> str:
    units = db.rows("SELECT * FROM org_units ORDER BY parent_id NULLS FIRST, name")
    if not units:
        return "Kurumsal yapı bilgisi henüz girilmedi."
    names = {u["id"]: u["name"] for u in units}
    lines = ["# Kurumsal yapı"]
    for u in units:
        parent = names.get(u["parent_id"], "—")
        lines.append(
            f"- {u['name']} ({u['kind']}, üst: {parent}, değer zinciri: {u['value_chain'] or '—'}, kişi: {u['headcount'] or '—'})"
            f"{': ' + u['description'] if u['description'] else ''}"
            f"{' | Ağrı noktaları: ' + u['pain_points'] if u['pain_points'] else ''}"
        )
    return "\n".join(lines)


def security_context() -> str:
    data = db.rows("SELECT * FROM security_metrics ORDER BY period")
    if not data:
        return "AI güvenlik metriği yok."
    from .security import METRICS
    out = ["# AI Güvenlik metrikleri (aylık)"]
    for m in data:
        label = METRICS.get(m["metric"], {}).get("label", m["metric"])
        out.append(f"- {m['period']} · {label}: {m['value']}")
    return "\n".join(out[-120:])


def _trim(text: str) -> str:
    limit = config.AI_MAX_CONTEXT_CHARS
    return text if len(text) <= limit else text[:limit] + "\n[...bağlam kısaltıldı...]"


# ---------------------------------------------------------------- 1) haftalık rapor analizi

REPORT_PROMPT = """Aşağıda Doğuş Teknoloji'nin gönderdiği haftalık proje durum raporu ve mevcut portföy var.
Raporu oku, her proje için durumu çıkar ve risk değerlendir. Sadece aşağıdaki şemada geçerli JSON döndür:
{
  "summary": "Yönetici özeti, en fazla 6 cümle, markdown madde işaretleri kullanabilirsin",
  "projects": [
    {
      "project_code": "Portföydeki kod (eşleşmiyorsa null)",
      "project_name": "Raporda geçen ad",
      "status": "Bu haftaki durum, 1-3 cümle",
      "suggested_health": "yesil | sari | kirmizi",
      "risk_score": 0-100 arası tamsayı (100 = kesin takılacak),
      "risk_reasons": ["neden 1", "neden 2"],
      "blockers": ["engel / bağımlılık"],
      "next_steps": ["önümüzdeki hafta"],
      "comment": "Danışman yorumu: ne yapılmalı, kim, ne zamana kadar"
    }
  ],
  "missing_projects": ["Portföyde aktif olup raporda hiç geçmeyen proje kodları"],
  "portfolio_observations": ["Genel gözlemler: tekrar eden engeller, kaynak sıkışması, ölçümleme eksikleri vb."]
}
Takılma sinyalleri: tarihin kayması, aynı engelin ikinci kez raporlanması, karar/onay/veri erişimi beklenmesi,
"devam ediyor" denip ilerleme yüzdesinin değişmemesi, test/UAT'nin ertelenmesi, kaynak/ekip değişikliği,
güvenlik onayı veya veri sınıflandırması eksikliği."""


def analyze_weekly_report(report_text: str, previous_text: str | None = None) -> dict:
    portfolio = portfolio_context(include_internal=True)
    if is_live():
        content = (
            f"{REPORT_PROMPT}\n\n=== PORTFÖY ===\n{_trim(portfolio)}\n\n"
            + (f"=== GEÇEN HAFTANIN RAPORU (kıyas için) ===\n{previous_text[:15000]}\n\n" if previous_text else "")
            + f"=== BU HAFTANIN RAPORU ===\n{_trim(report_text)}"
        )
        return parse_json(complete([{"role": "user", "content": content}], json_mode=True))
    return _mock_report_analysis(report_text)


_RISK_WORDS = {  # kök: (ağırlık, okunur açıklama)
    "gecik": (25, "gecikme bildirildi"), "ertelen": (20, "erteleme var"), "bekleniyor": (15, "dış bağımlılık bekleniyor"),
    "beklemede": (15, "iş beklemede"), "blok": (25, "bloke durum"), "engel": (20, "engel raporlandı"),
    "onay bekl": (20, "onay bekleniyor"), "erişim": (12, "veri/sistem erişimi sorunu"), "risk": (10, "raporda risk ifadesi"),
    "sorun": (12, "sorun raporlandı"), "kaynak": (10, "kaynak sıkışması"), "kaydırıldı": (15, "ekip/kaynak kaybı"),
    "eksik": (10, "eksiklik var"), "uat": (5, "UAT/test aşaması"), "kaydı": (15, "tarih kaydı"), "revize": (8, "plan revize ediliyor"),
    "durdu": (30, "geliştirme durdu"), "askı": (25, "iş askıda"), "netleşmedi": (15, "belirsizlik var"), "düşük": (8, "kalite/doğruluk düşük"),
}


def _mock_report_analysis(text: str) -> dict:
    projects = db.rows("SELECT id, code, name, stage FROM projects")
    low = text.lower()
    results, seen = [], set()
    for p in projects:
        pat = re.compile(rf"({re.escape(p['code'])}|{re.escape(p['name'][:18])})", re.I)
        m = pat.search(text)
        if not m:
            continue
        seen.add(p["code"])
        start = text.rfind("\n\n", 0, m.start()) + 1
        end = text.find("\n\n", m.end())
        chunk = text[start: end if end != -1 else len(text)].strip()
        chunk = re.sub(rf"^\s*{re.escape(p['code'])}[^:\n]*:\s*", "", chunk)
        chunk_l = chunk.lower()
        hits = [w for w in _RISK_WORDS if w in chunk_l]
        score = min(95, 10 + sum(_RISK_WORDS[w][0] for w in hits))
        health = "kirmizi" if score >= 60 else "sari" if score >= 35 else "yesil"
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", chunk) if len(s.strip()) > 15]
        blockers = [s for s in sentences if any(w in s.lower() for w in ("bekl", "engel", "blok", "onay", "erişim"))][:3]
        nexts = [s for s in sentences if any(w in s.lower() for w in ("sonraki", "planlan", "hafta", "hedef"))][:3]
        results.append({
            "project_code": p["code"],
            "project_name": p["name"],
            "status": " ".join(sentences[:2])[:400] or chunk[:300],
            "suggested_health": health,
            "risk_score": score,
            "risk_reasons": [_RISK_WORDS[w][1][0].upper() + _RISK_WORDS[w][1][1:] for w in hits[:4]] or ["Belirgin risk sinyali yok"],
            "blockers": blockers,
            "next_steps": nexts,
            "comment": (
                "Demo modu: kural tabanlı değerlendirme. "
                + ("Engel sahibiyle bu hafta karar toplantısı planlanmalı ve yeni termin yazılı alınmalı."
                   if health != "yesil" else "Takvime uygun ilerliyor; ölçümleme planının güncel olduğu teyit edilmeli.")
            ),
        })
    active_missing = [p["code"] for p in projects if p["stage"] in ACTIVE_STAGES and p["code"] not in seen]
    risky = [r for r in results if r["suggested_health"] != "yesil"]
    summary = (
        f"- Raporda **{len(results)}** proje tespit edildi; **{len(risky)}** projede risk sinyali var.\n"
        + (f"- En yüksek risk: **{max(results, key=lambda r: r['risk_score'])['project_code']}**.\n" if results else "")
        + (f"- Raporda hiç geçmeyen {len(active_missing)} aktif proje var — DT'den durum istenmeli.\n" if active_missing else "")
        + "- *Bu analiz demo modunda üretildi; şirket içi AI uç noktası bağlandığında gerçek analiz yapılır.*"
    )
    obs = []
    if "onay" in low:
        obs.append("Birden çok projede onay/karar bekleme sinyali var: karar mekanizması darboğaz olabilir.")
    if "veri" in low and ("erişim" in low or "kalite" in low):
        obs.append("Veri erişimi / veri kalitesi tekrar eden bir engel olarak görünüyor.")
    if "ölç" not in low:
        obs.append("Raporda ölçümlemeye dair hiçbir bilgi yok; DT rapor şablonuna KPI bölümü eklenmeli.")
    return {"summary": summary, "projects": results, "missing_projects": active_missing, "portfolio_observations": obs}


# ---------------------------------------------------------------- 2) boşluk analizi

GAP_PROMPT = """Aşağıda şirketin kurumsal yapısı, mevcut AI proje portföyü ve AI güvenlik metrikleri var.
Bir otomotiv distribütörü/ithalatçısı (çok markalı, bayi ağı, servis, yedek parça, filo/kiralama) için
AI olgunluğunu değerlendir ve markdown formatında şu başlıklarla rapor yaz:
## Genel değerlendirme (3-4 cümle)
## Kapsama haritası (değer zinciri alanı başına: kapsanıyor / kısmen / boş, tablo olarak)
## Eksik olduğumuz alanlar (en az 5 somut öneri: problem, önerilen AI çözümü, tahmini etki, zorluk, öncelik)
## Odaklanmamız gereken 3 alan (neden şimdi?)
## Portföy sağlığı ve süreç önerileri (ölçümleme, güvenlik, DT ile çalışma modeli)
Sektör referansları verirken genel bilgi olduğunu belirt; şirkete özel rakam uydurma."""


def gap_analysis() -> str:
    if is_live():
        content = f"{GAP_PROMPT}\n\n{_trim(org_context())}\n\n{_trim(portfolio_context())}\n\n{security_context()}"
        return complete([{"role": "user", "content": content}], max_tokens=6000)
    return _mock_gap_analysis()


_IDEAS = {
    "Satış & Bayi Yönetimi": "Bayi bazında talep tahmini ve stok-sipariş önerisi (ML)",
    "Satış Sonrası & Servis": "Servis iş emri metinlerinden arıza sınıflandırma ve garanti ön kontrolü (LLM)",
    "Yedek Parça & Lojistik": "Yedek parça talep tahmini ve kritik stok uyarısı (ML)",
    "Müşteri Deneyimi & CRM": "Çağrı merkezi konuşma özetleme ve duygu analizi (LLM)",
    "Pazarlama": "Kampanya içerik üretimi ve marka uyum kontrolü (GenAI)",
    "Finans & Muhasebe": "Fatura / irsaliye eşleştirme ve anomali tespiti (Doküman AI)",
    "İnsan Kaynakları": "İç politika ve yan haklar asistanı, aday ön eleme desteği (LLM)",
    "Tedarik Zinciri & Satın Alma": "Sözleşme ve teklif karşılaştırma asistanı (LLM)",
    "Filo & Kiralama": "Kiralık araç kalan değer tahmini ve hasar fotoğrafı analizi (ML + CV)",
    "Kurumsal Hizmetler & Hukuk": "Sözleşme risk maddesi tarama asistanı (LLM)",
    "BT & Siber Güvenlik": "Shadow AI tespiti ve DLP olay sınıflandırma (AI Security)",
}


def coverage() -> list[dict]:
    projects = db.rows("SELECT code, name, stage, value_chain, health FROM projects WHERE stage != 'iptal'")
    out = []
    for area in VALUE_CHAIN:
        ps = [p for p in projects if p["value_chain"] == area]
        live = [p for p in ps if p["stage"] in ("canli", "olcekleme")]
        level = "boş" if not ps else "kapsanıyor" if live else "kısmen"
        out.append({"area": area, "projects": ps, "live": len(live), "level": level})
    return out


def _mock_gap_analysis() -> str:
    cov = coverage()
    unmeasured = db.rows("SELECT code, name FROM projects WHERE stage IN ('canli','olcekleme') AND measurement_status IN ('yok','planlandi')")
    no_sec = db.rows("SELECT code FROM projects WHERE stage IN ('pilot','canli','olcekleme') AND security_review = 'yok'")
    empty = [c for c in cov if c["level"] == "boş"]
    partial = [c for c in cov if c["level"] == "kısmen"]
    lines = [
        "> *Demo modu: Bu rapor kural tabanlı üretildi. Şirket içi AI uç noktası bağlandığında kurumsal yapı ve "
        "portföy birlikte yorumlanarak gerçek danışman raporu üretilir.*",
        "\n## Genel değerlendirme",
        f"{len(VALUE_CHAIN)} değer zinciri alanının **{len(VALUE_CHAIN) - len(empty)}** tanesinde en az bir AI girişimi var; "
        f"**{len(empty)}** alan tamamen boş. Canlıdaki projelerin **{len(unmeasured)}** tanesinde etki ölçümü yapılmıyor.",
        "\n## Kapsama haritası",
        "| Alan | Durum | Proje sayısı | Canlı |",
        "|---|---|---|---|",
    ]
    for c in cov:
        lines.append(f"| {c['area']} | {c['level']} | {len(c['projects'])} | {c['live']} |")
    lines.append("\n## Eksik olduğumuz alanlar")
    for c in (empty + partial)[:6]:
        lines.append(f"- **{c['area']}** — Öneri: {_IDEAS.get(c['area'], 'Süreç keşif çalıştayı')}. "
                     f"Öncelik: {'Yüksek' if c in empty else 'Orta'}.")
    lines.append("\n## Odaklanmamız gereken 3 alan")
    focus = (empty + partial)[:3]
    for i, c in enumerate(focus, 1):
        lines.append(f"{i}. **{c['area']}** — portföyde {'hiç' if not c['projects'] else 'canlıya çıkmış'} proje yok.")
    lines.append("\n## Portföy sağlığı ve süreç önerileri")
    if unmeasured:
        lines.append("- Ölçümlemesi olmayan canlı projeler: " + ", ".join(f"**{u['code']}**" for u in unmeasured)
                     + ". Bunlar için baseline + aylık ölçüm sorumlusu atanmalı.")
    if no_sec:
        lines.append("- Güvenlik değerlendirmesi yapılmadan pilota/canlıya geçen projeler: " + ", ".join(f"**{s['code']}**" for s in no_sec) + ".")
    lines.append("- DT haftalık rapor şablonuna 'ilerleme %', 'engel sahibi', 'KPI ölçümü' alanları zorunlu eklenmeli.")
    return "\n".join(lines)


# ---------------------------------------------------------------- 3) danışman sohbeti

def advisor_answer(history: list[dict], question: str) -> str:
    if is_live():
        context = (
            "Aşağıdaki şirket verilerini bağlam olarak kullan. Sorular AI genel bilgisi hakkında da olabilir; "
            "o durumda genel bilgini kullan ama şirket bağlamına bağla.\n\n"
            f"{_trim(portfolio_context())}\n\n{org_context()[:15000]}\n\n{security_context()}\n\n"
            f"{_latest_insights_context()}"
        )
        msgs = [{"role": "user", "content": context}, {"role": "assistant", "content": "Bağlamı aldım. Sorunuzu bekliyorum."}]
        msgs += [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
        msgs.append({"role": "user", "content": question})
        return complete(msgs, max_tokens=3000)
    return _mock_answer(question)


def _latest_insights_context() -> str:
    ins = db.rows("SELECT kind, title, body, created_at FROM ai_insights ORDER BY id DESC LIMIT 3")
    return "\n\n".join(f"# Önceki AI içgörüsü: {i['title']} ({i['created_at'][:10]})\n{i['body'][:4000]}" for i in ins)


def _mock_answer(q: str) -> str:
    ql = q.lower()
    projects = db.rows("SELECT * FROM projects")
    if any(w in ql for w in ("risk", "takıl", "gecik", "kırmızı")):
        risky = sorted([p for p in projects if p["health"] != "yesil"], key=lambda p: -(p["ai_risk_score"] or 0))
        if not risky:
            return "Şu an riskli olarak işaretlenmiş proje yok."
        return "**Risk altındaki projeler:**\n\n" + "\n".join(
            f"- **{p['code']} {p['name']}** — {HEALTH[p['health']][0]}, aşama: {STAGE_LABELS[p['stage']]}. "
            f"{p['ai_risk_note'] or ''}" for p in risky[:8]
        ) + "\n\n_Demo modu yanıtı._"
    if any(w in ql for w in ("ölç", "kpi", "etki", "değer")):
        live = [p for p in projects if p["stage"] in ("canli", "olcekleme")]
        um = [p for p in live if p["measurement_status"] in ("yok", "planlandi")]
        total = sum(p["realized_value"] or 0 for p in projects)
        return (f"Canlıda **{len(live)}** proje var; bunların **{len(um)}** tanesinde ölçüm yapılmıyor "
                f"({', '.join(p['code'] for p in um) or '—'}). Doğrulanmış toplam yıllık etki: **{_fmt_money(total)}**.\n\n_Demo modu yanıtı._")
    if any(w in ql for w in ("güvenlik", "shadow", "kvkk", "veri")):
        return ("AI güvenliği için önerilen temel kontroller: (1) onaylı AI araç listesi ve AI Studio üzerinden kurumsal erişim, "
                "(2) Shadow AI tespiti için proxy/CASB loglarının aylık raporlanması, (3) kişisel veri içeren promptlar için DLP, "
                "(4) her AI projesinde veri sınıflandırması ve güvenlik değerlendirmesi kapısı, (5) çalışan farkındalık eğitimi.\n\n_Demo modu yanıtı._")
    return ("Demo modundayım: şirket içi AI uç noktası bağlandığında bu soruya portföy, kurumsal yapı ve raporlar "
            "üzerinden yanıt vereceğim. Şimdilik 'riskli projeler', 'ölçümleme durumu' veya 'AI güvenliği' hakkında sorabilirsiniz.")


# ---------------------------------------------------------------- 4) proje değerlendirmesi

def project_assessment(project_id: int) -> str:
    p = db.row("SELECT * FROM projects WHERE id = ?", (project_id,))
    kpis = db.rows("SELECT * FROM kpis WHERE project_id = ?", (project_id,))
    updates = db.rows(
        "SELECT ru.*, wr.week_start FROM report_updates ru JOIN weekly_reports wr ON wr.id = ru.report_id "
        "WHERE ru.project_id = ? ORDER BY wr.week_start DESC LIMIT 6", (project_id,))
    comments = db.rows("SELECT c.body, u.name, c.created_at FROM comments c JOIN users u ON u.id = c.user_id "
                       "WHERE target_type = 'project' AND target_id = ? ORDER BY c.id DESC LIMIT 15", (project_id,))
    docs = db.rows("SELECT title, category, substr(text_content, 1, 3000) AS excerpt FROM documents WHERE project_id = ?", (project_id,))
    if is_live():
        ctx = json.dumps({"project": p, "kpis": kpis, "weekly_updates": updates, "comments": comments, "documents": docs},
                         ensure_ascii=False, default=str)
        prompt = ("Bu AI projesini değerlendir. Markdown başlıkları: ## Durum özeti, ## Takılma riski (0-100 skor ve gerekçe), "
                  "## Ölçümleme değerlendirmesi, ## Önerilen aksiyonlar (sahip + termin önerisi ile). Veri:\n" + _trim(ctx))
        return complete([{"role": "user", "content": prompt}], max_tokens=2500)
    trend = " → ".join(HEALTH.get(u["suggested_health"], ("?",))[0] for u in reversed(updates)) or "rapor yok"
    return (f"## Durum özeti\n{p['code']} şu an **{STAGE_LABELS[p['stage']]}** aşamasında, sağlık **{HEALTH[p['health']][0]}**.\n\n"
            f"## Takılma riski\nSon haftalık sağlık trendi: {trend}. Skor: **{p['ai_risk_score'] or '—'}**.\n\n"
            f"## Ölçümleme değerlendirmesi\nDurum: **{MEASUREMENT_LABELS[p['measurement_status']]}**, {len(kpis)} KPI tanımlı.\n\n"
            "## Önerilen aksiyonlar\n- Eksik kapı kriterlerini tamamlayın.\n- KPI sahibini ve ölçüm sıklığını netleştirin.\n\n_Demo modu._")


# ---------------------------------------------------------------- yardımcılar

def stale_projects(days: int = 14) -> list[dict]:
    limit = (datetime.now() - timedelta(days=days)).isoformat()
    return db.rows(
        "SELECT * FROM projects WHERE stage IN ('analiz','onay','gelistirme','pilot') "
        "AND (last_status_at IS NULL OR last_status_at < ?) ORDER BY last_status_at", (limit,))
