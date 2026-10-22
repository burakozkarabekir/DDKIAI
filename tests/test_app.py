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


# ---------------------------------------------------------------- v2.1

TRELLO = {
    "name": "AI Impact",
    "lists": [{"id": "L1", "name": "İŞ LİSTESİ"}, {"id": "L2", "name": "INPROGRESS"}, {"id": "L3", "name": "DONE/MAINTENANCE"},
              {"id": "L4", "name": "AI Champion"}, {"id": "L5", "name": "ÖN DEĞERLENDİRME"}],
    "labels": [{"id": "B1", "name": "AI Impact"}, {"id": "B2", "name": "Dependent"}],
    "members": [{"id": "M1", "fullName": "Burak Özkarabekir"}],
    "checklists": [{"id": "K1", "name": "Checklist", "checkItems": [{"name": "DT ön görüşme", "state": "incomplete"}]}],
    "cards": [
        {"id": "68000000a1", "name": "UC88-YP Lojistik-Spare Parts Demand Forecasting", "idList": "L2", "idLabels": ["B1", "B2"],
         "idMembers": ["M1"], "due": "2027-01-08T09:00:00.000Z", "desc": "Yedek parça talep tahmini. Detay.", "idChecklists": ["K1"]},
        {"id": "68000000a2", "name": "UC88- Yedek Parça Lojistik - Stok Optimizasyon", "idList": "L1", "idLabels": [], "idMembers": []},
        {"id": "68000000a3", "name": "UC57-VW Binek - Price Positioning Faz2", "idList": "L3", "idLabels": ["B1"], "idMembers": []},
        {"id": "68000000a4", "name": "UC62 - Micro-Segment & Personalization Engine", "idList": "L5", "idLabels": [], "idMembers": []},
        {"id": "68000000a5", "name": "AI Championlar", "idList": "L4", "idLabels": [], "idMembers": []},
    ],
    "actions": [
        {"type": "updateCard", "date": "2026-10-05T10:39:56.154Z", "data": {"card": {"id": "68000000a1"},
         "listBefore": {"id": "L1", "name": "İŞ LİSTESİ"}, "listAfter": {"id": "L2", "name": "INPROGRESS"}}},
        {"type": "updateCard", "date": "2026-04-06T10:00:00.000Z", "data": {"card": {"id": "68000000a3"},
         "listBefore": {"id": "L2", "name": "INPROGRESS"}, "listAfter": {"id": "L3", "name": "DONE/MAINTENANCE"}}},
        {"type": "commentCard", "date": "2026-09-01T10:00:00.000Z", "data": {"card": {"id": "68000000a1"}, "text": "ERP onayı bekleniyor"},
         "memberCreator": {"fullName": "Burak Özkarabekir"}},
    ],
}


def test_trello_parse_and_import(client):
    from app import trello
    assert trello.parse_name("UC88-YP Lojistik-Spare Parts Demand Forecasting")["unit"] == "YP Lojistik"
    assert trello.parse_name("UC62 - Micro-Segment & Personalization Engine")["unit"] is None
    assert trello.parse_name("UC32 & UC43- Total Cost of Ownership")["extra"] == ["UC43"]
    assert trello.guess_stage("ÖN DEĞERLENDİRME") == "analiz" and trello.guess_stage("AI Champion") == "atla"
    raw = json.dumps(TRELLO)
    r = client.post("/ayarlar/trello/onizle", files={"file": ("t.json", raw.encode(), "application/json")})
    assert r.status_code == 200 and "UC88" in r.text  # tekrar eden kod uyarısı
    yp = db.scalar("SELECT id FROM departments WHERE name = 'Yedek Parça & Lojistik'")
    form = {"stage_L1": "fikir", "stage_L2": "gelistirme", "stage_L3": "canli", "stage_L4": "atla", "stage_L5": "analiz",
            "unit_YP Lojistik": str(yp), "unit_Yedek Parça Lojistik": str(yp), "unit_VW Binek": "marka", "update_existing": "1"}
    client.post("/ayarlar/trello/aktar", data=form)
    p = db.row("SELECT * FROM projects WHERE code = 'UC88'")
    assert p["stage"] == "gelistirme" and p["department_id"] == yp and p["start_date"] == "2026-10-05"
    assert p["target_date"] == "2027-01-08" and p["health"] == "sari" and "Dependent" in p["tags"] and p["owner"] == "Burak Özkarabekir"
    assert db.scalar("SELECT code FROM projects WHERE trello_id = '68000000a2'") == "UC88-2"
    f2 = db.row("SELECT * FROM projects WHERE code = 'UC57-F2'")
    assert f2["brands"] == "VW Binek" and f2["golive_date"] == "2026-04-06"
    assert not db.scalar("SELECT 1 FROM projects WHERE name = 'AI Championlar'")
    assert db.scalar("SELECT COUNT(*) FROM comments WHERE target_id = ? AND kind = 'trello'", (p["id"],)) == 1
    assert db.scalar("SELECT COUNT(*) FROM actions WHERE project_id = ? AND source = 'Trello checklist'", (p["id"],)) == 1
    # yeniden aktarım tekrar kayıt oluşturmaz
    n = db.scalar("SELECT COUNT(*) FROM projects")
    st = trello.import_board(raw, {k[6:]: v for k, v in form.items() if k.startswith("stage_")}, {}, 1)
    assert st["created"] == 0 and db.scalar("SELECT COUNT(*) FROM projects") == n
    assert db.scalar("SELECT COUNT(*) FROM comments WHERE target_id = ? AND kind = 'trello'", (p["id"],)) == 1


def test_word_table_report_links_by_uc_code(client):
    d = docx.Document()
    d.add_heading("AI IMPACT Proje Statü Raporu", 0)
    t = d.add_table(rows=2, cols=3)
    for j, v in enumerate(("Kod", "Durum", "Sonraki adım")):
        t.cell(0, j).text = v
    for j, v in enumerate(("UC 88", "Veri erişimi bekleniyor, gecikme var", "UAT")):
        t.cell(1, j).text = v
    buf = io.BytesIO()
    d.save(buf)
    r = client.post("/dokumanlar", files=[("files", ("Statü.docx", buf.getvalue(), "application/octet-stream"))],
                    data={"doc_type": "dt_durum"}, follow_redirects=False)
    did = int(r.headers["location"].rsplit("/", 1)[1])
    pipeline.drain()
    pid = db.scalar("SELECT id FROM projects WHERE code = 'UC88'")
    assert db.scalar("SELECT 1 FROM document_links WHERE document_id = ? AND project_id = ?", (did, pid))
    assert db.scalar("SELECT value_text FROM facts WHERE document_id = ? AND project_id = ? AND fact_type = 'durum'", (did, pid)).startswith("Veri erişimi")
    assert "AI bağlı değil" in client.get(f"/dokumanlar/{did}").text  # mock modda kullanıcı uyarılır


def test_edit_endpoints(client):
    pid = db.scalar("SELECT id FROM projects WHERE code = 'UC88'")
    client.post(f"/projeler/{pid}/aksiyon", data={"title": "Eski", "owner": "", "due_date": ""})
    aid = db.scalar("SELECT id FROM actions WHERE title = 'Eski'")
    client.post(f"/aksiyon/{aid}/duzenle", data={"title": "Yeni başlık", "owner": "BT", "due_date": "2026-12-01"})
    assert db.row("SELECT * FROM actions WHERE id = ?", (aid,))["title"] == "Yeni başlık"
    client.post(f"/aksiyon/{aid}/sil")
    assert not db.row("SELECT 1 FROM actions WHERE id = ?", (aid,))
    client.post(f"/projeler/{pid}/kpi", data={"name": "Stok", "unit": "", "direction": "up"})
    kid = db.scalar("SELECT id FROM kpis WHERE project_id = ? AND name = 'Stok'", (pid,))
    client.post(f"/kpi/{kid}", data={"name": "Stok devir hızı", "unit": "gün", "direction": "down", "baseline": "40"})
    k = db.row("SELECT * FROM kpis WHERE id = ?", (kid,))
    assert (k["name"], k["unit"], k["direction"], k["baseline"]) == ("Stok devir hızı", "gün", "down", 40)
    form = {"name": "Spare Parts", "code": "uc88x", "tags": "AI Impact"}
    client.post(f"/projeler/{pid}", data=form)
    assert db.scalar("SELECT code FROM projects WHERE id = ?", (pid,)) == "UC88X"
    f = next(f for f in knowledge.pending() if f["fact_type"] == "saglik") if knowledge.pending() else None
    if f:
        client.post(f"/bilgi/{f['id']}/deger", data={"value": "sari", "as_of": "2026-10-16"})
        assert db.scalar("SELECT value_text FROM facts WHERE id = ?", (f["id"],)) == "sari"
    client.post("/guvenlik/metrik", data={"period": "2026-09", "dlp_incidents": "5"})
    client.post("/guvenlik/metrik/sil", data={"period": "2026-09"})
    assert not db.scalar("SELECT 1 FROM security_metrics WHERE period = '2026-09'")
    for url in ["/ayarlar", "/guvenlik?donem=2026-10", f"/projeler/{pid}?tab=aksiyon", f"/projeler/{pid}/duzenle", "/inceleme", "/aksiyonlar"]:
        assert client.get(url).status_code == 200, url


def test_clear_demo_keeps_user_data(client):
    from app import seed
    user_doc = db.scalar("SELECT id FROM documents WHERE filename = 'Statü.docx'")
    client.post("/ayarlar/demo-temizle")
    assert not db.scalar("SELECT 1 FROM projects WHERE code = 'AI-001'")
    assert db.scalar("SELECT 1 FROM projects WHERE trello_id = '68000000a1'")  # Trello'dan gelenler korunur
    assert db.scalar("SELECT 1 FROM documents WHERE id = ?", (user_doc,))
    assert not db.scalar("SELECT 1 FROM documents WHERE filename = 'AI-002 PDD.docx'")
    seed.seed_demo()
    assert not db.scalar("SELECT 1 FROM projects WHERE code = 'AI-001'")  # bir daha yüklenmez


def test_provider_autodetect(monkeypatch):
    import importlib
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("AI_BASE_URL", "https://ai.sirket.local/v1/chat/completions")
    importlib.reload(config)
    try:
        assert config.AI_PROVIDER == "openai" and config.AI_BASE_URL == "https://ai.sirket.local/v1"
        monkeypatch.setenv("AI_BASE_URL", "https://x.openai.azure.com")
        importlib.reload(config)
        assert config.AI_PROVIDER == "azure"
    finally:
        monkeypatch.setenv("AI_PROVIDER", "mock")
        monkeypatch.setenv("AI_BASE_URL", "")
        importlib.reload(config)


def test_azure_url_variants(monkeypatch):
    """Azure portalından yapıştırılan farklı adres biçimleri doğru isteğe dönüşür."""
    import importlib
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers.get("api-key"), body.get("model"), "max_tokens" in body))
            ok_paths = ("/openai/deployments/gpt4o-prod/chat/completions?api-version=2025-01-01-preview",
                        "/openai/deployments/gpt4o-prod/chat/completions?api-version=2024-10-21", "/openai/v1/chat/completions")
            if self.path not in ok_paths:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error":{"code":"404","message": "Resource not found"}}')
                return
            if "max_tokens" in body:  # yeni modeller gibi davran
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error":{"message":"Unsupported parameter: \'max_tokens\'. Use \'max_completion_tokens\' instead."}}')
                return
            out = json.dumps({"choices": [{"message": {"content": '{"durum": "hazir"}'}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    # yerel test sunucusu ".azure" içermediği için sağlayıcıyı açıkça azure veriyoruz; adres biçimi yine çözümlenir
    variants = [
        ("azure", f"{base}/openai/deployments/gpt4o-prod/chat/completions?api-version=2025-01-01-preview", "", "azure"),
        ("azure", base, "gpt4o-prod", "azure"),
        ("azure", f"{base}/openai/v1/", "gpt4o-prod", "azure"),
    ]
    monkeypatch.setenv("AI_API_KEY", "anahtar")
    try:
        for provider, url, model, expect in variants:
            monkeypatch.setenv("AI_PROVIDER", provider)
            monkeypatch.setenv("AI_BASE_URL", url)
            monkeypatch.setenv("AI_MODEL", model)
            importlib.reload(config)
            if url.endswith("/openai/v1/"):
                config.AI_PROVIDER = "azure_v1"  # gerçek *.azure.com adresinde otomatik algılanır
            assert config.AI_MODEL == "gpt4o-prod", url
            r = ai.diagnose()
            assert r["ok"], (url, r["steps"][-1])
        assert all(s[1] == "anahtar" for s in seen)  # api-key başlığı
        assert any(s[0].endswith("2025-01-01-preview") for s in seen)  # api-version adresten alındı
        assert seen[-1][2] == "gpt4o-prod" and not seen[-1][3]  # v1: model gövdede, max_completion_tokens'a düşüldü
        # gerçek Azure adlarında otomatik algılama
        for url, kind in [("https://dogus-ai.openai.azure.com", "azure"), ("https://dogus.cognitiveservices.azure.com/", "azure"),
                          ("https://dogus.openai.azure.com/openai/v1", "azure_v1"), ("https://x.services.ai.azure.com/models", "azure_inference")]:
            monkeypatch.setenv("AI_PROVIDER", "auto")
            monkeypatch.setenv("AI_BASE_URL", url)
            importlib.reload(config)
            assert config.AI_PROVIDER == kind, url
    finally:
        for k in ("AI_PROVIDER", "AI_BASE_URL", "AI_MODEL", "AI_API_KEY"):
            monkeypatch.setenv(k, "mock" if k == "AI_PROVIDER" else "")
        importlib.reload(config)
        srv.shutdown()


def test_deep_probe_finds_right_deployment(client):
    """Derin tanılama: yanlış model adıyla 404 alınırken deployment listesinden doğrusunu bulur."""
    from app import ai_probe

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self):
            if self.path.startswith("/openai/deployments?"):
                return self._send(200, {"data": [{"id": "gpt4o-prod", "model": "gpt-4o", "status": "succeeded"}]})
            self._send(404, {"error": {"code": "404", "message": "Resource not found"}})

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            if self.headers.get("api-key") != "anahtar":
                return self._send(401, {"error": {"code": "401", "message": "Access denied"}})
            if "/deployments/gpt4o-prod/" in self.path:
                return self._send(200, {"choices": [{"message": {"content": "hazir"}}]})
            if "/deployments/" in self.path:
                return self._send(404, {"error": {"code": "DeploymentNotFound", "message": "The API deployment for this resource does not exist."}})
            self._send(404, {"error": {"code": "404", "message": "Resource not found"}})

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old = (config.AI_API_KEY, config.AI_MODEL)
    config.AI_API_KEY, config.AI_MODEL = "anahtar", "gpt-4o"  # kullanıcı model adını yazmış
    try:
        p = ai_probe.Probe()
        p.azure(f"http://127.0.0.1:{srv.server_port}")
        report = "\n".join(p.lines)
        assert "deployment: gpt4o-prod" in report and "'gpt-4o' adında bir deployment yok" in report
        assert p.working and p.working[0]["AI_MODEL"] == "gpt4o-prod"
        assert "anahtar" not in report.replace("anahtar:", "")  # anahtar açık yazılmaz
        assert "ÇALIŞAN AYAR" in p._finish()
        assert client.post("/ayarlar/ai-derin-test").status_code == 200
    finally:
        config.AI_API_KEY, config.AI_MODEL = old
        srv.shutdown()
