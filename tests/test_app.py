"""Uçtan uca duman testleri: python -m pytest -q"""
import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["SEED_DEMO"] = "1"
os.environ["AI_PROVIDER"] = "mock"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import _f, _md, app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(c, email, password="Demo123!"):
    c.get("/cikis")
    r = c.post("/giris", data={"email": email, "password": password}, follow_redirects=False)
    assert r.status_code == 303


def test_pages_render(client):
    login(client, "gm@demo.local")
    for url in ["/", "/projeler", "/projeler?view=liste", "/projeler/1", "/projeler/3?tab=etki", "/projeler/3?tab=durum",
                "/raporlar", "/raporlar/1", "/aksiyonlar", "/dokumanlar", "/danisman", "/kurumsal-yapi", "/guvenlik",
                "/guvenlik/shadow-ai", "/surec"]:
        assert client.get(url).status_code == 200, url


def test_dt_isolation(client):
    login(client, "dt@demo.local")
    assert "AI-011" not in client.get("/projeler").text
    assert client.get("/projeler/11").status_code == 404
    for url in ["/danisman", "/guvenlik", "/kurumsal-yapi", "/yonetim"]:
        assert client.get(url).status_code == 403, url
    assert client.post("/projeler/3/asama", data={"to_stage": "pilot"}).status_code == 403


def test_weekly_report_flow(client):
    login(client, "dt@demo.local")
    r = client.post("/raporlar", data={"week_start": "2026-10-19", "text": "AI-003: ERP onayı bekleniyor, geliştirme durdu."},
                    follow_redirects=False)
    rid = int(r.headers["location"].rsplit("/", 1)[1])
    login(client, "dde@demo.local")
    assert "Proje bazında" in client.get(f"/raporlar/{rid}").text
    client.post(f"/raporlar/{rid}/uygula", data={"update_id": [str(i) for i in range(1, 100)]})
    assert "Riskli" in client.get("/projeler/3").text


def test_stage_gate_warns(client):
    login(client, "dde@demo.local")
    r = client.post("/projeler/6/asama", data={"to_stage": "onay"}, follow_redirects=True)
    assert "kapı kriterleri eksik" in r.text


def test_origin_check(client):
    login(client, "dde@demo.local")
    r = client.post("/yorum", data={"target_type": "project", "target_id": 1, "body": "x"}, headers={"origin": "http://evil.example"})
    assert r.status_code == 403


def test_helpers():
    assert _f("1.500.000") == 1_500_000 and _f("12,5") == 12.5 and _f("") is None
    html = str(_md("<script>x</script> [a](javascript:alert(1))"))
    assert "<script>" not in html and "javascript:" not in html
