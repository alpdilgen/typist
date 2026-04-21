"""
main.py — Anova Typist Web Backend
====================================
FastAPI application serving both the REST API and the static frontend.
Replaces the Streamlit prototype for production deployment on typist.anova.bg.

Endpoints:
  POST /api/transcribe       Upload + transcribe document
  POST /api/export-docx      Generate Word document from (edited) result
  POST /api/export-xliff     Generate XLIFF from result
  POST /api/apply-xliff      Apply translated XLIFF → translated Word
  GET  /api/health           Health check
  GET  /                     Serve SPA frontend

Auth: X-Access-Key header (comma-separated keys in ACCESS_KEYS env var)
"""

import io
import json
import os
from typing import Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from typist_core import (
    SUPPORTED_FORMATS,
    apply_xliff_to_docx,
    create_docx,
    create_xliff,
    get_segments_for_editor,
    reconstruct_content_from_segments,
    transcribe_document,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
_raw_keys: str = os.environ.get("ACCESS_KEYS", "")
ACCESS_KEYS: set[str] = {k.strip() for k in _raw_keys.split(",") if k.strip()}
REQUIRE_AUTH: bool = bool(ACCESS_KEYS)  # auth only if keys configured

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Anova Typist", version="1.0.0", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _check_auth(x_access_key: Optional[str]) -> None:
    """Raise 401 if auth is required and the key is invalid."""
    if not REQUIRE_AUTH:
        return
    if not x_access_key or x_access_key.strip() not in ACCESS_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing access key.")


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "auth_required": REQUIRE_AUTH,
        "api_key_configured": bool(ANTHROPIC_API_KEY),
    }


@app.post("/api/transcribe")
async def api_transcribe(
    file: UploadFile = File(...),
    model: str = Form("claude-sonnet-4-6"),
    include_image_placeholders: bool = Form(True),
    x_access_key: Optional[str] = Header(None),
):
    """
    Upload a document and transcribe it with Claude Vision.

    Returns JSON with transcription result + editor segments.
    """
    _check_auth(x_access_key)

    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured on server.")

    # Validate format
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: .{ext}. Supported: {', '.join(SUPPORTED_FORMATS)}",
        )

    file_bytes = await file.read()

    # Size check (20 MB)
    if len(file_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 20 MB.")

    try:
        result = transcribe_document(
            file_bytes=file_bytes,
            filename=file.filename,
            api_key=ANTHROPIC_API_KEY,
            model=model,
            include_image_placeholders=include_image_placeholders,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")

    # Attach editor segments
    result["segments"] = get_segments_for_editor(result.get("content", ""))

    return JSONResponse(content=result)


@app.post("/api/export-docx")
async def api_export_docx(
    request: Request,
    x_access_key: Optional[str] = Header(None),
):
    """
    Generate a Word document from a (possibly edited) transcription result.

    Body: JSON matching the result dict from /api/transcribe.
    Optionally, 'segments' key with edited segments (reconstructs content).
    """
    _check_auth(x_access_key)

    body = await request.json()

    # If edited segments are provided, rebuild the content from them
    if "segments" in body and body["segments"]:
        body["content"] = reconstruct_content_from_segments(body["segments"])

    try:
        docx_bytes = create_docx(body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DOCX generation failed: {exc}")

    filename = (body.get("filename") or "document").rsplit(".", 1)[0] + "_transcription.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/export-xliff")
async def api_export_xliff(
    request: Request,
    x_access_key: Optional[str] = Header(None),
):
    """
    Generate an XLIFF file from a transcription result.

    Body JSON fields:
      - All result fields from /api/transcribe
      - segments (optional edited list)
      - target_language (str, e.g. "ES")
      - source_language (str, optional)
      - include_bilingual_docx (bool, default True)
    """
    _check_auth(x_access_key)

    body = await request.json()

    if "segments" in body and body["segments"]:
        body["content"] = reconstruct_content_from_segments(body["segments"])

    target_language: str = body.pop("target_language", "")
    source_language: str = body.pop("source_language", "")
    include_bilingual_docx: bool = body.pop("include_bilingual_docx", True)

    # Generate skeleton DOCX to embed in XLIFF
    try:
        docx_bytes = create_docx(body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Skeleton DOCX generation failed: {exc}")

    try:
        xliff_result = create_xliff(
            result=body,
            target_language=target_language,
            source_language=source_language,
            include_bilingual_docx=include_bilingual_docx,
            docx_bytes=docx_bytes,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"XLIFF generation failed: {exc}")

    # create_xliff returns either bytes (xliff only) or dict with multiple files
    if isinstance(xliff_result, bytes):
        fname = (body.get("filename") or "document").rsplit(".", 1)[0] + ".xlf"
        return Response(
            content=xliff_result,
            media_type="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    # If it returned a dict (e.g. {"xliff": bytes, "docx": bytes}), return the xliff
    xliff_bytes = xliff_result.get("xliff") or xliff_result.get("xlf") or b""
    fname = (body.get("filename") or "document").rsplit(".", 1)[0] + ".xlf"
    return Response(
        content=xliff_bytes,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.post("/api/apply-xliff")
async def api_apply_xliff(
    file: UploadFile = File(...),
    x_access_key: Optional[str] = Header(None),
):
    """
    Apply a translated XLIFF file and produce a translated Word document.
    """
    _check_auth(x_access_key)

    xliff_bytes = await file.read()

    try:
        docx_bytes = apply_xliff_to_docx(xliff_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Apply XLIFF failed: {exc}")

    base = (file.filename or "translated").rsplit(".", 1)[0]
    out_name = base + "_translated.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )


# ---------------------------------------------------------------------------
# Static files — mount AFTER API routes
# ---------------------------------------------------------------------------

# Mount static assets (JS, CSS)
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
@app.get("/{full_path:path}", response_class=HTMLResponse)
async def serve_spa(full_path: str = ""):
    """Serve the SPA index.html for all non-API routes."""
    index_path = os.path.join(_static_dir, "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())
