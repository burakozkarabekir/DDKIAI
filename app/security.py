"""AI Security metrik tanımları.

Metrikler aylık dönem bazında tutulur. Kaynak sistemler (AI Studio logları, proxy/CASB, DLP,
eğitim platformu) için CSV ile toplu yükleme desteklenir: period,metric,value[,note]
"""
import csv
import io

from . import db

# direction: "up" = artması iyi, "down" = azalması iyi
METRICS = {
    "ai_studio_active_users": {"label": "AI Studio aktif kullanıcı", "unit": "kişi", "group": "Kurumsal AI kullanımı", "direction": "up"},
    "ai_studio_prompts": {"label": "AI Studio istek sayısı", "unit": "istek", "group": "Kurumsal AI kullanımı", "direction": "up"},
    "ai_studio_use_cases": {"label": "AI Studio kayıtlı kullanım senaryosu", "unit": "adet", "group": "Kurumsal AI kullanımı", "direction": "up"},
    "shadow_ai_apps": {"label": "Tespit edilen onaysız AI uygulaması", "unit": "uygulama", "group": "Shadow AI", "direction": "down"},
    "shadow_ai_users": {"label": "Onaysız AI kullanan çalışan", "unit": "kişi", "group": "Shadow AI", "direction": "down"},
    "shadow_ai_blocked": {"label": "Engellenen Shadow AI erişimi", "unit": "istek", "group": "Shadow AI", "direction": "down"},
    "dlp_incidents": {"label": "AI kaynaklı DLP olayı", "unit": "olay", "group": "Veri koruma", "direction": "down"},
    "sensitive_prompts_blocked": {"label": "Hassas veri içeren engellenen prompt", "unit": "prompt", "group": "Veri koruma", "direction": "down"},
    "policy_ack_rate": {"label": "AI kullanım politikası onay oranı", "unit": "%", "group": "Farkındalık & Uyum", "direction": "up"},
    "training_completion": {"label": "AI güvenlik eğitimi tamamlama", "unit": "%", "group": "Farkındalık & Uyum", "direction": "up"},
    "projects_security_reviewed": {"label": "Güvenlik değerlendirmesi tamamlanan proje oranı", "unit": "%", "group": "Farkındalık & Uyum", "direction": "up"},
}


def series(metric: str, months: int = 12) -> list[dict]:
    data = db.rows("SELECT period, value FROM security_metrics WHERE metric = ? ORDER BY period DESC LIMIT ?", (metric, months))
    return list(reversed(data))


def latest_periods(n: int = 12) -> list[str]:
    return [r["period"] for r in db.rows("SELECT DISTINCT period FROM security_metrics ORDER BY period DESC LIMIT ?", (n,))][::-1]


def import_csv(raw: str) -> tuple[int, list[str]]:
    count, errors = 0, []
    reader = csv.DictReader(io.StringIO(raw.lstrip("﻿")))
    for i, r in enumerate(reader, 2):
        metric = (r.get("metric") or "").strip()
        period = (r.get("period") or "").strip()
        try:
            value = float(str(r.get("value", "")).replace(",", "."))
        except ValueError:
            errors.append(f"Satır {i}: değer sayı değil")
            continue
        if metric not in METRICS:
            errors.append(f"Satır {i}: bilinmeyen metrik '{metric}'")
            continue
        if len(period) != 7 or period[4] != "-":
            errors.append(f"Satır {i}: dönem YYYY-AA olmalı")
            continue
        upsert(period, metric, value, (r.get("note") or "").strip() or None)
        count += 1
    return count, errors


def upsert(period: str, metric: str, value: float, note: str | None = None) -> None:
    db.execute(
        "INSERT INTO security_metrics (period, metric, value, note) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(period, metric) DO UPDATE SET value = excluded.value, note = excluded.note",
        (period, metric, value, note))
