"""Haftalık DT raporlarının AI ile analizi ve sonuçların portföye işlenmesi.

Akış: rapor yüklenir → AI analiz eder (öneri) → DDE ekibi önerileri inceleyip onaylar →
proje sağlıkları, risk skorları ve "son durum" tarihleri güncellenir.
"""
import json

from . import ai, db


def run_analysis(report_id: int, user_id: int | None) -> None:
    report = db.row("SELECT * FROM weekly_reports WHERE id = ?", (report_id,))
    if not report:
        return
    prev = db.row("SELECT text_content FROM weekly_reports WHERE week_start < ? ORDER BY week_start DESC LIMIT 1",
                  (report["week_start"],))
    db.update("weekly_reports", report_id, {"ai_status": "analiz", "ai_error": None})
    try:
        result = ai.analyze_weekly_report(report["text_content"] or "", prev["text_content"] if prev else None)
        store_report_analysis(report_id, result, apply=False, user_id=user_id)
    except Exception as exc:
        db.update("weekly_reports", report_id, {"ai_status": "hata", "ai_error": str(exc)[:1000]})


def store_report_analysis(report_id: int, result: dict, apply: bool, user_id: int | None, at: str | None = None) -> None:
    db.execute("DELETE FROM report_updates WHERE report_id = ?", (report_id,))
    codes = {r["code"].upper(): r["id"] for r in db.rows("SELECT id, code FROM projects")}
    for item in result.get("projects", []):
        code = (item.get("project_code") or "").upper()
        health = item.get("suggested_health") if item.get("suggested_health") in ("yesil", "sari", "kirmizi") else None
        try:
            score = max(0, min(100, int(item.get("risk_score") or 0)))
        except (TypeError, ValueError):
            score = None
        db.insert("report_updates", {
            "report_id": report_id, "project_id": codes.get(code), "project_ref": item.get("project_name") or code,
            "status_text": item.get("status"), "suggested_health": health, "risk_score": score,
            "risk_reasons": json.dumps(item.get("risk_reasons") or [], ensure_ascii=False),
            "blockers": json.dumps(item.get("blockers") or [], ensure_ascii=False),
            "next_steps": json.dumps(item.get("next_steps") or [], ensure_ascii=False),
            "ai_comment": item.get("comment"),
        })
    db.update("weekly_reports", report_id, {
        "ai_status": "tamam", "ai_summary": result.get("summary"), "ai_raw": json.dumps(result, ensure_ascii=False),
    })
    if apply:
        apply_updates(report_id, user_id, at)


def apply_updates(report_id: int, user_id: int | None, at: str | None = None, only: set[int] | None = None) -> int:
    at = at or db.now()
    report = db.row("SELECT * FROM weekly_reports WHERE id = ?", (report_id,))
    n = 0
    for u in db.rows("SELECT * FROM report_updates WHERE report_id = ? AND project_id IS NOT NULL", (report_id,)):
        if only is not None and u["id"] not in only:
            continue
        reasons = json.loads(u["risk_reasons"] or "[]")
        note = (u["ai_comment"] or "") + (" Nedenler: " + "; ".join(reasons) if reasons else "")
        data = {"last_status_at": at, "ai_risk_score": u["risk_score"], "ai_risk_note": note.strip()[:1500], "updated_at": at}
        if u["suggested_health"]:
            data["health"] = u["suggested_health"]
        db.update("projects", u["project_id"], data)
        n += 1
    db.update("weekly_reports", report_id, {"applied": 1})
    raw = json.loads(report["ai_raw"] or "{}")
    body = (report["ai_summary"] or "")
    if raw.get("portfolio_observations"):
        body += "\n\n**Portföy gözlemleri**\n\n" + "\n".join(f"- {o}" for o in raw["portfolio_observations"])
    if raw.get("missing_projects"):
        body += "\n\n**Raporda geçmeyen aktif projeler:** " + ", ".join(raw["missing_projects"])
    db.execute("DELETE FROM ai_insights WHERE source_report_id = ?", (report_id,))
    db.insert("ai_insights", {"kind": "weekly", "title": f"Haftalık analiz — {report['week_start']}", "body": body,
                              "source_report_id": report_id, "created_by": user_id, "created_at": at})
    db.log(user_id, "report_applied", "report", report_id, f"{n} proje güncellendi")
    return n
