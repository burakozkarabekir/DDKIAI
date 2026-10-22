"""Uçtan uca testler: python -m pytest -q"""
import io
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["SEED_DEMO"] = "1"
os.environ["AI_PROVIDER"] = "mock"
os.environ["AUTH_ENABLED"] = "0"

import docx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import ai, config, db, knowledge, pipeline  # noqa: E402
from app.main import _f, _md, app  # noqa: E402

PAGES = ["/", "/projeler", "/projeler?view=liste", "/projeler/1", "/projeler/3?tab=bilgi", "/projeler/3?tab=etki",
         "/projeler/3?tab=dokuman", "/zaman-cizelgesi", "/zaman-cizelgesi?grup=asama", "/dokumanlar", "/dokumanlar?q=ERP",
         "/dokumanlar/1", "/raporlar", "/inceleme", "/aksiyonlar", "/danisman", "/guvenlik", "/guvenlik/shadow-ai", "/surec",
         "/ayarlar", "/yonetim"]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _docx(lines) -> bytes:
    d = docx.Document()
    d.add_heading(lines[0], level=0)
    for line in lines[1:]:
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_pages_render_without_login(client):
    for url in PAGES:
        assert client.get(url).status_code == 200, url
    assert client.get("/giris", follow_redirects=False).status_code == 303  # giriş kapalı


def test_seed_pipeline_built_knowledge():
    assert db.scalar("SELECT COUNT(*) FROM documents WHERE status = 'islendi'") == 5
    assert db.scalar("SELECT doc_type FROM documents WHERE title LIKE 'DDE İç%'") == "ic_not"  # otomatik sınıflandırma
    assert db.scalar("SELECT COUNT(*) FROM facts WHERE fact_type = 'kpi'") >= 4  # Excel kazanım dokümanından
    labels = [(c["code"], c["label"]) for c in knowledge.conflicts()]
    assert ("AI-003", "Hedef canlı tarihi") in labels  # DT raporu vs iç notlar


def test_upload_word_without_project_links_automatically(client):
    data = _docx(["Komite notu", "AI-007 Fatura & İrsaliye Eşleştirme: Karar: UAT 2 hafta sonra başlayacak.",
                  "Aksiyon: Muhasebe test kullanıcılarını belirlesin."])
    r = client.post("/dokumanlar", files=[("files", ("Komite Notu.docx", data, "application/octet-stream"))],
                    data={"doc_type": "otomatik"}, follow_redirects=False)
    assert r.status_code == 303
    did = int(r.headers["location"].rsplit("/", 1)[1])
    pipeline.drain()
    d = db.row("SELECT * FROM documents WHERE id = ?", (did,))
    assert d["status"] == "islendi" and d["doc_type"] == "toplanti"
    assert db.scalar("SELECT 1 FROM document_links l JOIN projects p ON p.id = l.project_id WHERE l.document_id = ? AND p.code = 'AI-007'", (did,))
    assert db.scalar("SELECT COUNT(*) FROM facts WHERE document_id = ? AND fact_type IN ('karar', 'aksiyon')", (did,)) == 2
    assert client.get(f"/dokumanlar/{did}").status_code == 200
    # aynı dosya tekrar yüklenince kaydedilmez
    r = client.post("/dokumanlar", files=[("files", ("kopya.docx", data, "application/octet-stream"))], follow_redirects=True)
    assert "zaten" in r.text


def test_multi_upload_and_bad_extension(client):
    files = [("files", ("a.txt", b"AI-012 AI Studio: aktif kullanici 1300.", "text/plain")),
             ("files", ("b.exe", b"x", "application/octet-stream"))]
    r = client.post("/dokumanlar", files=files, data={"doc_type": "dt_durum"}, follow_redirects=True)
    assert "1 doküman yüklendi" in r.text and "desteklenmiyor" in r.text


def test_review_apply_updates_project(client):
    pipeline.drain()
    f = next(f for f in knowledge.pending() if f["fact_type"] == "kpi")
    client.post("/inceleme", data={"fact_id": str(f["id"]), "action": "onayla"})
    k = db.row("SELECT * FROM kpis WHERE project_id = ? AND lower(name) = lower(?)", (f["project_id"], f["field"]))
    assert k[f["subfield"]] == f["value_num"]
    assert db.scalar("SELECT status FROM facts WHERE id = ?", (f["id"],)) == "onaylandi"


def test_stage_gate_warns(client):
    r = client.post("/projeler/6/asama", data={"to_stage": "onay"}, follow_redirects=True)
    assert "kapı kriterleri eksik" in r.text


def test_departments_crud(client):
    client.post("/ayarlar/departman", data={"name": "Kurumsal İletişim", "description": "PR"})
    dep = db.row("SELECT * FROM departments WHERE name = 'Kurumsal İletişim'")
    assert dep
    client.post(f"/ayarlar/departman/{dep['id']}/sil")
    assert not db.row("SELECT * FROM departments WHERE id = ?", (dep["id"],))


def test_synthesis_and_advisor(client):
    client.post("/projeler/3/sentez")
    pipeline.drain()
    assert db.scalar("SELECT 1 FROM ai_insights WHERE kind = 'project' AND project_id = 3")
    r = client.post("/api/danisman", json={"question": "ERP erişimi neden gecikiyor?"})
    assert r.status_code == 200 and "D" in r.json()["answer_html"]


def test_origin_check(client):
    r = client.post("/yorum", data={"target_type": "project", "target_id": 1, "body": "x"}, headers={"origin": "http://evil.example"})
    assert r.status_code == 403


def test_auth_can_be_reenabled(client):
    config.AUTH_ENABLED = True
    try:
        assert client.get("/", follow_redirects=False).headers["location"].startswith("/giris")
        r = client.post("/giris", data={"email": "admin@demo.local", "password": "Admin123!"}, follow_redirects=False)
        assert r.status_code == 303
        assert client.get("/").status_code == 200
    finally:
        config.AUTH_ENABLED = False
        client.get("/cikis")


def test_live_ai_provider_with_fake_server(client):
    """OpenAI uyumlu uç nokta: kimlik başlığı, JSON modu ve çıkarım sonucunun işlenmesi."""
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers.get("Authorization")))
            if body.get("response_format"):
                content = json.dumps({"doc_type": "kazanim", "doc_date": "2026-09-30", "summary": "AI-009 kazanım özeti",
                                      "projects": [{"code": "AI-009", "confidence": 0.95}], "new_projects": [{"name": "Bayi Chatbot"}],
                                      "facts": [{"project_code": "AI-009", "type": "kazanim", "field": "realized_value", "value": None,
                                                 "value_num": 1100000, "unit": "TL", "as_of": "2026-09-30", "confidence": 0.9,
                                                 "evidence": "Gerçekleşen 1,1 milyon TL"}]})
            else:
                content = "Yanıt [D1]"
            out = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old = (config.AI_PROVIDER, config.AI_BASE_URL, config.AI_API_KEY, config.AI_MODEL)
    config.AI_PROVIDER, config.AI_BASE_URL, config.AI_API_KEY, config.AI_MODEL = "openai", f"http://127.0.0.1:{srv.server_port}/v1", "k", "m"
    try:
        assert ai.test_connection()["ok"]
        r = client.post("/dokumanlar", files=[("files", ("ik.txt", "İK asistanı kazanım raporu".encode(), "text/plain"))], follow_redirects=False)
        did = int(r.headers["location"].rsplit("/", 1)[1])
        pipeline.drain()
        d = db.row("SELECT * FROM documents WHERE id = ?", (did,))
        assert d["doc_type"] == "kazanim" and d["type_source"] == "ai" and d["doc_date"] == "2026-09-30"
        f = db.row("SELECT * FROM facts WHERE document_id = ? AND fact_type = 'kazanim'", (did,))
        assert f["value_num"] == 1_100_000 and f["status"] == "oneri"
        assert db.scalar("SELECT 1 FROM facts WHERE document_id = ? AND field = 'yeni_proje'", (did,))
        assert seen[0] == ("/v1/chat/completions", "Bearer k")
    finally:
        config.AI_PROVIDER, config.AI_BASE_URL, config.AI_API_KEY, config.AI_MODEL = old
        srv.shutdown()


def test_helpers():
    assert _f("1.500.000") == 1_500_000 and _f("12,5") == 12.5 and _f("") is None
    html = str(_md("<script>x</script> [a](javascript:alert(1)) kaynak [D3]"))
    assert "<script>" not in html and "javascript:" not in html and 'href="/dokumanlar/3"' in html
    assert ai.parse_number("14,5 milyon TL") == 14_500_000 and ai.parse_number("15.200.000 TL") == 15_200_000
    assert knowledge.norm("KPI İLK") == "kpi ilk"
