"""AI Impact Merkezi — FastAPI uygulaması (giriş noktası)."""
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import config, db, org, pipeline, seed
from .auth import LoginRequired, current_user
from .routes import documents, misc, projects
from .web import APP_DIR, md, parse_float, redirect, templates

# Testlerin ve eski içe aktarımların kullandığı kısa adlar
_md, _f = md, parse_float


@asynccontextmanager
async def lifespan(_app):
    db.init_db()
    seed.ensure_users()
    seed.purge_legacy_demo()
    org.ensure_org()
    pipeline.start_worker()
    yield


app = FastAPI(title=config.APP_NAME, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, max_age=config.SESSION_HOURS * 3600,
                   same_site="lax", https_only=config.COOKIE_SECURE, session_cookie="aiimpact")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
app.include_router(projects.router)
app.include_router(documents.router)
app.include_router(misc.router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Basit CSRF koruması: form gönderimlerinde Origin başka bir siteyi gösteriyorsa reddet.
    if request.method == "POST":
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return PlainTextResponse("Geçersiz istek kaynağı", status_code=403)
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'"
    return response


@app.exception_handler(LoginRequired)
async def _login_redirect(request: Request, _exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "Oturum gerekli"}, status_code=401)
    return redirect(f"/giris?next={request.url.path}")


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    from .web import nav_counts
    return templates.TemplateResponse(request, "error.html", {"user": current_user(request), "path": request.url.path,
                                                              "nav": nav_counts(), "code": exc.status_code, "message": exc.detail},
                                      status_code=exc.status_code)
