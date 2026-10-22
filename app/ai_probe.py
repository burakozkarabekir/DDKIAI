"""AI bağlantısı derin tanılama.

Uygulamadan bağımsız çalışır: `.env`'de ne okunduğunu gösterir, ağ/SSL katmanını ayrı ayrı test eder, Azure'dan
deployment listesini ister ve farklı adres / api-version kombinasyonlarını tek tek dener. Sonunda çalışan
kombinasyon için hazır `.env` satırları önerir. Anahtar hiçbir çıktıda açık yazılmaz.

Kullanım (proje klasöründe, sanal ortam açıkken):  python -m app.ai_probe
Ayarlar sayfasındaki "Derin tanılama" butonu da aynı testi çalıştırır.
"""
import os
import platform
import re
import socket
import ssl
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import __version__, config

API_VERSIONS = ["2024-10-21", "2025-01-01-preview", "2024-08-01-preview", "2024-06-01", "2024-02-01"]


def _mask(v: str) -> str:
    if not v:
        return "(boş)"
    return f"{v[:3]}…{v[-4:]} ({len(v)} karakter)" if len(v) > 10 else "(çok kısa: %d karakter)" % len(v)


def _short(r: httpx.Response) -> str:
    t = r.text.strip().replace("\n", " ")
    return t[:260] + ("…" if len(t) > 260 else "")


class Probe:
    def __init__(self):
        self.lines: list[str] = []
        self.working: list[dict] = []
        self.deployments: list[str] = []

    def out(self, s: str = "") -> None:
        self.lines.append(s)

    # ------------------------------------------------------------------ 1. ortam ve .env
    def env(self) -> None:
        self.out(f"AI Impact Merkezi tanılama · uygulama sürümü {__version__} · Python {sys.version.split()[0]} · {platform.system()} {platform.release()}")
        self.out(f"Proje klasörü: {config.BASE_DIR}")
        candidates = [config.BASE_DIR / n for n in (".env", ".env.txt", "env", ".env.example")]
        for f in candidates:
            if f.exists():
                self.out(f"  bulundu: {f.name} ({f.stat().st_size} bayt)")
        if not config.ENV_FILE:
            self.out("  ✗ .env okunmadı! Dosya adı tam olarak '.env' olmalı ve bu klasörde durmalı.")
        else:
            self.out(f"  ✓ okunan dosya: {config.ENV_FILE}")
            raw = config.ENV_FILE.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"):
                self.out("  · dosya BOM ile başlıyor (sorun değil, okunuyor)")
            for line in raw.decode("utf-8-sig", errors="replace").splitlines():
                m = re.match(r"\s*(AI_[A-Z_]+)\s*=(.*)$", line)
                if not m:
                    continue
                key, val = m.group(1), m.group(2)
                warn = []
                if val != val.strip():
                    warn.append("başında/sonunda boşluk var")
                if val.strip()[:1] in "\"'<":
                    warn.append("tırnak ya da < > ile başlıyor")
                if " =" in line or "= " in line:
                    warn.append("= çevresinde boşluk")
                shown = _mask(val.strip()) if "KEY" in key else (val.strip() or "(boş)")
                self.out(f"    {key} = {shown}" + (f"   ⚠ {', '.join(warn)}" if warn else ""))
        for k in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL", "AI_PROVIDER"):
            if os.environ.get(k) and config.ENV_FILE and k not in config.ENV_KEYS:
                self.out(f"  ⚠ {k} Windows ortam değişkeni olarak tanımlı; .env'deki değer yerine o kullanılıyor.")
        self.out("")
        self.out("Uygulamanın kullandığı değerler:")
        self.out(f"  sağlayıcı: {config.AI_PROVIDER}   (ayar: {config.AI_PROVIDER_SET})")
        self.out(f"  kök adres: {config.AI_BASE_URL or '(boş)'}")
        self.out(f"  model / deployment: {config.AI_MODEL or '(boş)'}")
        self.out(f"  api-version: {config.AI_AZURE_API_VERSION}")
        self.out(f"  anahtar: {_mask(config.AI_API_KEY)}")
        for n in config.AI_URL_NOTES:
            self.out(f"  · {n}")
        proxy = config.AI_PROXY or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        self.out(f"  proxy: {proxy or 'yok'}   NO_PROXY: {os.environ.get('NO_PROXY') or os.environ.get('no_proxy') or 'yok'}")
        self.out("")

    # ------------------------------------------------------------------ 2. ağ ve SSL
    def network(self, host: str, port: int) -> bool:
        self.out(f"Ağ testi: {host}:{port}")
        proxy = config.AI_PROXY or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy:  # adresi proxy çözer; yerel DNS/port testi yanıltıcı olur
            self.out("  · proxy tanımlı; doğrudan DNS/port/SSL testi atlandı, istekler proxy üzerinden denenecek")
            return True
        try:
            ips = sorted({a[4][0] for a in socket.getaddrinfo(host, port)})
            self.out(f"  ✓ DNS: {', '.join(ips)}")
        except OSError as exc:
            self.out(f"  ✗ DNS çözülemedi: {exc}  → adres yanlış yazılmış ya da bu ağdan görünmüyor (VPN gerekir mi?)")
            return False
        try:
            sock = socket.create_connection((host, port), timeout=8)
            self.out("  ✓ porta bağlanıldı")
        except OSError as exc:
            self.out(f"  ✗ porta bağlanılamadı: {exc}  → güvenlik duvarı/proxy engelliyor olabilir (AI_PROXY ayarlayın)")
            return False
        if port != 443:
            sock.close()
            return True
        for name, ctx in self._contexts():
            try:
                s2 = socket.create_connection((host, port), timeout=8)
                with ctx.wrap_socket(s2, server_hostname=host) as tls:
                    cert = tls.getpeercert() or {}
                    issuer = dict(x[0] for x in cert.get("issuer", [])) if cert else {}
                    self.out(f"  ✓ SSL ({name}): {tls.version()} · sertifikayı veren: {issuer.get('organizationName') or issuer.get('commonName') or '?'}")
            except ssl.SSLError as exc:
                self.out(f"  ✗ SSL ({name}): {exc.reason or exc}")
            except OSError as exc:
                self.out(f"  ✗ SSL ({name}): {exc}")
        sock.close()
        return True

    def _contexts(self):
        out = []
        try:
            import truststore
            out.append(("Windows/sistem sertifika deposu", truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)))
        except ImportError:
            self.out("  ⚠ truststore paketi yok: 'pip install -r requirements.txt' çalıştırın")
        try:
            import certifi
            out.append(("Python sertifika paketi", ssl.create_default_context(cafile=certifi.where())))
        except ImportError:
            out.append(("Python varsayılanı", ssl.create_default_context()))
        return out

    # ------------------------------------------------------------------ 3. istekler
    def _client(self) -> httpx.Client:
        from .ai import _verify
        kw = {"timeout": 30, "verify": _verify()}
        if config.AI_PROXY:
            kw["proxy"] = config.AI_PROXY
        return httpx.Client(**kw)

    def _try(self, c: httpx.Client, label: str, method: str, url: str, headers: dict, body: dict | None = None):
        try:
            t0 = time.time()
            r = c.request(method, url, headers=headers, json=body)
            ok = r.status_code < 300
            self.out(f"  {'✓' if ok else '✗'} {label}: HTTP {r.status_code} ({time.time() - t0:.1f} sn) · {_short(r)}")
            return r
        except httpx.HTTPError as exc:
            self.out(f"  ✗ {label}: {type(exc).__name__}: {exc}")
            return None

    def azure(self, root: str) -> None:
        key = config.AI_API_KEY
        h = {"api-key": key, "Content-Type": "application/json"}
        chat = {"messages": [{"role": "user", "content": "Sadece 'hazir' yaz."}], "max_tokens": 10}
        chat_new = {"messages": chat["messages"], "max_completion_tokens": 10}
        with self._client() as c:
            self.out(f"Azure kaynağı: {root}")
            r = self._try(c, "Deployment listesi", "GET", f"{root}/openai/deployments?api-version=2022-12-01", h)
            if r is not None and r.status_code == 200:
                try:
                    data = r.json().get("data", [])
                    self.deployments = [d.get("id") for d in data if d.get("id")]
                    for d in data:
                        self.out(f"      · deployment: {d.get('id')}  (model: {d.get('model')}, durum: {d.get('status')})")
                except ValueError:
                    pass
            if r is not None and r.status_code == 401:
                self.out("      → 401: anahtar bu kaynağa ait değil ya da yanlış kopyalandı.")
            self._try(c, "Model listesi", "GET", f"{root}/openai/models?api-version=2024-10-21", h)
            names = list(dict.fromkeys([n for n in [config.AI_MODEL] + self.deployments if n]))[:6]
            if not names:
                self.out("  ✗ Deployment adı bilinmiyor (AI_MODEL boş ve liste alınamadı). Portalda Deployments → Name değerini AI_MODEL'e yazın.")
            for name in names:
                for ver in list(dict.fromkeys([config.AI_AZURE_API_VERSION] + API_VERSIONS))[:4]:
                    url = f"{root}/openai/deployments/{name}/chat/completions?api-version={ver}"
                    r = self._try(c, f"Sohbet · deployment={name} · api-version={ver}", "POST", url, h, chat)
                    if r is not None and r.status_code == 400 and "max_tokens" in r.text:
                        r = self._try(c, f"Sohbet (yeni model parametresi) · {name} · {ver}", "POST", url, h, chat_new)
                    if r is not None and r.status_code < 300:
                        self.working.append({"AI_BASE_URL": root, "AI_MODEL": name, "AI_AZURE_API_VERSION": ver})
                        break
                    if r is not None and r.status_code == 404 and "DeploymentNotFound" in r.text:
                        self.out(f"      → '{name}' adında bir deployment yok.")
                        break
                if self.working:
                    break
            if not self.working and names:
                r = self._try(c, f"v1 API · model={names[0]}", "POST", f"{root}/openai/v1/chat/completions", h, {**chat_new, "model": names[0]})
                if r is not None and r.status_code < 300:
                    self.working.append({"AI_BASE_URL": f"{root}/openai/v1", "AI_MODEL": names[0]})
        self.out("")

    def openai_like(self, base: str) -> None:
        key = config.AI_API_KEY
        with self._client() as c:
            self.out(f"OpenAI uyumlu uç nokta: {base}")
            for hname, hval in (("Authorization", f"Bearer {key}"), ("api-key", key)):
                h = {hname: hval, "Content-Type": "application/json"}
                r = self._try(c, f"Model listesi ({hname})", "GET", f"{base}/models", h)
                if r is not None and r.status_code == 200:
                    try:
                        ids = [m.get("id") for m in r.json().get("data", [])][:15]
                        self.out(f"      · modeller: {', '.join(filter(None, ids))}")
                    except ValueError:
                        pass
                body = {"model": config.AI_MODEL, "messages": [{"role": "user", "content": "Sadece 'hazir' yaz."}], "max_tokens": 10}
                r = self._try(c, f"Sohbet ({hname})", "POST", f"{base}/chat/completions", h, body)
                if r is not None and r.status_code < 300:
                    self.working.append({"AI_BASE_URL": base, "AI_MODEL": config.AI_MODEL,
                                         **({"AI_AUTH_HEADER": "api-key"} if hname == "api-key" else {})})
                    break
        self.out("")

    # ------------------------------------------------------------------ çalıştır
    def run(self) -> str:
        self.env()
        if not config.AI_BASE_URL_RAW:
            self.out("✗ AI_BASE_URL boş; test edilecek adres yok.")
            return "\n".join(self.lines)
        u = urlparse(config.AI_BASE_URL_RAW.split("?")[0].strip("\"' "))
        host, port = u.hostname or "", u.port or (443 if u.scheme == "https" else 80)
        if not host:
            self.out(f"✗ AI_BASE_URL bir adres gibi görünmüyor: {config.AI_BASE_URL_RAW!r} (https:// ile başlamalı)")
            return "\n".join(self.lines)
        if "/api/projects/" in u.path:
            self.out("⚠ Bu bir AI Foundry PROJE adresi (…/api/projects/…). Sohbet için kaynak adresi gerekir: "
                     "https://<ad>.openai.azure.com ya da https://<ad>.cognitiveservices.azure.com")
        if not self.network(host, port):
            return self._finish()
        if host.endswith(".azure.com") or ".azure." in host:
            name = host.split(".")[0]
            roots = [f"{u.scheme}://{host}"] + [f"https://{name}.{d}" for d in ("openai.azure.com", "cognitiveservices.azure.com")
                                                 if not host.endswith(d)]
            for root in roots:
                self.azure(root)
                if self.working:
                    break
        else:
            self.openai_like(config.AI_BASE_URL)
        return self._finish()

    def _finish(self) -> str:
        self.out("=" * 70)
        if self.working:
            w = self.working[0]
            self.out("✓ ÇALIŞAN AYAR BULUNDU. .env dosyanızdaki AI satırlarını şöyle yapın:")
            self.out("    AI_PROVIDER=auto")
            for k, v in w.items():
                self.out(f"    {k}={v}")
            self.out("    AI_API_KEY=<mevcut anahtarınız>")
            self.out("  Kaydedip uygulamayı yeniden başlatın.")
        else:
            self.out("✗ Çalışan bir kombinasyon bulunamadı. Bu raporu (anahtar maskelidir) paylaşın.")
        return "\n".join(self.lines)


def run() -> str:
    return Probe().run()


if __name__ == "__main__":
    report = run()
    print(report)
    out = Path(config.BASE_DIR) / "ai_tanilama_raporu.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\nRapor kaydedildi: {out}")
