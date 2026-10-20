from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi import Request
import time
from urllib.parse import urlsplit
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.core.config import get_settings
from app.core.db import Database
from app.core.logging import configure_logging
from app.api.routes import build_router
from importlib.resources import files as resource_files

def create_app():
    s = get_settings()
    configure_logging()
    db = Database(s.db_path)
    db.migrate()
    app = FastAPI(title="M-Group", version="0.1.0")
    app.state.settings = s
    app.state.db = db
    app.include_router(build_router(db, s))

    @app.middleware("http")
    async def authenticate_admin_session(request: Request, call_next):
        request.state.admin_authenticated = False
        if request.url.path.startswith("/api/v1/"):
            origin = request.headers.get("origin")
            token = request.cookies.get("m_group_session", "")
            if token:
                from app.core.auth import hash_session_token
                now = int(time.time())
                token_hash = hash_session_token(token)
                with db.connect() as c:
                    row = c.execute(
                        """SELECT session_hash FROM webui_sessions
                           WHERE session_hash=? AND revoked_at IS NULL
                             AND expires_at>? AND last_seen>?""",
                        (token_hash, now, now - 1800),
                    ).fetchone()
                    if row:
                        c.execute("UPDATE webui_sessions SET last_seen=? WHERE session_hash=?",
                                  (now, token_hash))
                        c.commit()
                        request.state.admin_authenticated = True
        return await call_next(request)
    webui_dir = Path(__file__).resolve().parent / "webui"
    app.mount("/assets", StaticFiles(directory=webui_dir / "assets"), name="webui-assets")
    app.mount("/pages", StaticFiles(directory=webui_dir / "pages"), name="webui-pages")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return resource_files("app").joinpath("webui/index.html").read_text(encoding="utf-8")

    return app

app = create_app()
