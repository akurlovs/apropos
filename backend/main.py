"""FastAPI app: /api/summary, /api/invoices, /api/ask; serves the built frontend."""
from __future__ import annotations

import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # pragma: no cover
    pass

from backend import db, llm, tools  # noqa: E402

logging.basicConfig(level=logging.INFO)
ASK_RATE_LIMIT = os.environ.get("ASK_RATE_LIMIT", "10/minute")

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.get_con()  # build the in-memory DB at startup (fails fast on bad data)
    yield


app = FastAPI(title="Apropos procurement policy chatbot", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class SettingsIn(BaseModel):
    report_currency: Literal["EUR", "original"] = "EUR"
    approval_scope: Literal["all", "approved_only"] = "all"


class Msg(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20000)


class AskIn(BaseModel):
    messages: list[Msg] = Field(min_length=1, max_length=50)
    settings: SettingsIn = SettingsIn()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "model": llm.MODEL, "api_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.get("/api/summary")
def summary(report_currency: Literal["EUR", "original"] = "EUR",
            approval_scope: Literal["all", "approved_only"] = "all") -> dict:
    return tools.summary(tools.Settings(report_currency, approval_scope))


@app.get("/api/invoices")
def invoices(currency: Literal["EUR", "original"] = "EUR", format: Literal["json", "csv"] = Query("json")):
    rows = tools.invoice_export(currency)
    if format == "json":
        return {"currency_view": currency, "rows": rows, "lineage": db.source_metadata()}
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=invoices_2025_conversion.csv"})


@app.post("/api/ask")
@limiter.limit(ASK_RATE_LIMIT)
def ask(request: Request, body: AskIn) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "ANTHROPIC_API_KEY is not set on the server (see .env.example).")
    s = tools.Settings(body.settings.report_currency, body.settings.approval_scope)
    return llm.ask([m.model_dump() for m in body.messages], s)


# ---- built frontend (production / Docker); in dev, Vite serves it and proxies /api
DIST = Path(os.environ.get("FRONTEND_DIST", Path(__file__).resolve().parent.parent / "frontend" / "dist"))
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
