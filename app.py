"""
app.py — Anova Typist Streamlit Interface
==========================================
Scanned document → Claude Vision transcription → Word (.docx) download
"""

import io
import os
import streamlit as st
from dotenv import load_dotenv
from typist_core import (
    transcribe_document,
    create_docx,
    create_xliff,
    apply_xliff_to_docx,
    get_segments_for_editor,
    reconstruct_content_from_segments,
    SUPPORTED_FORMATS,
    MAX_FILE_SIZE_MB,
)


# ---------------------------------------------------------------------------
# PDF page renderer (requires pypdfium2 — optional, graceful fallback)
# ---------------------------------------------------------------------------
def _render_pdf_page(pdf_bytes: bytes, page_idx: int):
    """
    Renders a single PDF page to PNG bytes.
    Returns None if pypdfium2 is not installed or an error occurs.
    """
    try:
        import pypdfium2 as pdfium
        pdf    = pdfium.PdfDocument(pdf_bytes)
        if page_idx < 0 or page_idx >= len(pdf):
            return None
        page   = pdf[page_idx]
        bitmap = page.render(scale=2.0)
        pil_img = bitmap.to_pil()
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


def _pdf_page_count(pdf_bytes: bytes) -> int | None:
    """Returns the total page count of a PDF, or None if unavailable."""
    try:
        import pypdfium2 as pdfium
        return len(pdfium.PdfDocument(pdf_bytes))
    except Exception:
        return None

load_dotenv()

# ---------------------------------------------------------------------------
# BCP-47 Language list (IANA Language Subtag Registry / XLIFF xs:language)
# Format: ("Display Label", "bcp47-code")
# Sorted alphabetically by display label
# ---------------------------------------------------------------------------
_LANG_OPTIONS = [
    ("— Select —", ""),
    ("Afrikaans — af-ZA", "af-ZA"),
    ("Albanian — sq-AL", "sq-AL"),
    ("Amharic — am-ET", "am-ET"),
    ("Arabic — ar-SA", "ar-SA"),
    ("Azerbaijani — az-AZ", "az-AZ"),
    ("Basque — eu-ES", "eu-ES"),
    ("Belarusian — be-BY", "be-BY"),
    ("Bengali — bn-IN", "bn-IN"),
    ("Bosnian — bs-BA", "bs-BA"),
    ("Bulgarian — bg-BG", "bg-BG"),
    ("Catalan — ca-ES", "ca-ES"),
    ("Chinese Simplified — zh-CN", "zh-CN"),
    ("Chinese Traditional (HK) — zh-HK", "zh-HK"),
    ("Chinese Traditional (TW) — zh-TW", "zh-TW"),
    ("Croatian — hr-HR", "hr-HR"),
    ("Czech — cs-CZ", "cs-CZ"),
    ("Danish — da-DK", "da-DK"),
    ("Dutch (Belgium) — nl-BE", "nl-BE"),
    ("Dutch (Netherlands) — nl-NL", "nl-NL"),
    ("English (Australia) — en-AU", "en-AU"),
    ("English (Canada) — en-CA", "en-CA"),
    ("English (Ireland) — en-IE", "en-IE"),
    ("English (UK) — en-GB", "en-GB"),
    ("English (US) — en-US", "en-US"),
    ("Estonian — et-EE", "et-EE"),
    ("Finnish — fi-FI", "fi-FI"),
    ("Filipino — fil-PH", "fil-PH"),
    ("French (Belgium) — fr-BE", "fr-BE"),
    ("French (Canada) — fr-CA", "fr-CA"),
    ("French (France) — fr-FR", "fr-FR"),
    ("French (Switzerland) — fr-CH", "fr-CH"),
    ("Galician — gl-ES", "gl-ES"),
    ("Georgian — ka-GE", "ka-GE"),
    ("German (Austria) — de-AT", "de-AT"),
    ("German (Germany) — de-DE", "de-DE"),
    ("German (Switzerland) — de-CH", "de-CH"),
    ("Greek — el-GR", "el-GR"),
    ("Gujarati — gu-IN", "gu-IN"),
    ("Hebrew — he-IL", "he-IL"),
    ("Hindi — hi-IN", "hi-IN"),
    ("Hungarian — hu-HU", "hu-HU"),
    ("Icelandic — is-IS", "is-IS"),
    ("Indonesian — id-ID", "id-ID"),
    ("Irish — ga-IE", "ga-IE"),
    ("Italian (Italy) — it-IT", "it-IT"),
    ("Italian (Switzerland) — it-CH", "it-CH"),
    ("Japanese — ja-JP", "ja-JP"),
    ("Kannada — kn-IN", "kn-IN"),
    ("Kazakh — kk-KZ", "kk-KZ"),
    ("Khmer — km-KH", "km-KH"),
    ("Korean — ko-KR", "ko-KR"),
    ("Lao — lo-LA", "lo-LA"),
    ("Latvian — lv-LV", "lv-LV"),
    ("Lithuanian — lt-LT", "lt-LT"),
    ("Macedonian — mk-MK", "mk-MK"),
    ("Malay — ms-MY", "ms-MY"),
    ("Malayalam — ml-IN", "ml-IN"),
    ("Marathi — mr-IN", "mr-IN"),
    ("Mongolian — mn-MN", "mn-MN"),
    ("Nepali — ne-NP", "ne-NP"),
    ("Norwegian — nb-NO", "nb-NO"),
    ("Persian — fa-IR", "fa-IR"),
    ("Polish — pl-PL", "pl-PL"),
    ("Portuguese (Brazil) — pt-BR", "pt-BR"),
    ("Portuguese (Portugal) — pt-PT", "pt-PT"),
    ("Punjabi — pa-IN", "pa-IN"),
    ("Romanian — ro-RO", "ro-RO"),
    ("Russian — ru-RU", "ru-RU"),
    ("Serbian — sr-RS", "sr-RS"),
    ("Sinhala — si-LK", "si-LK"),
    ("Slovak — sk-SK", "sk-SK"),
    ("Slovenian — sl-SI", "sl-SI"),
    ("Spanish (Argentina) — es-AR", "es-AR"),
    ("Spanish (Colombia) — es-CO", "es-CO"),
    ("Spanish (Mexico) — es-MX", "es-MX"),
    ("Spanish (Spain) — es-ES", "es-ES"),
    ("Swahili — sw-KE", "sw-KE"),
    ("Swedish (Finland) — sv-FI", "sv-FI"),
    ("Swedish (Sweden) — sv-SE", "sv-SE"),
    ("Tamil — ta-IN", "ta-IN"),
    ("Telugu — te-IN", "te-IN"),
    ("Thai — th-TH", "th-TH"),
    ("Turkish — tr-TR", "tr-TR"),
    ("Ukrainian — uk-UA", "uk-UA"),
    ("Urdu — ur-PK", "ur-PK"),
    ("Vietnamese — vi-VN", "vi-VN"),
    ("Welsh — cy-GB", "cy-GB"),
    ("Zulu — zu-ZA", "zu-ZA"),
]
_LANG_LABELS  = [label for label, _ in _LANG_OPTIONS]
_LANG_CODE_OF = {label: code for label, code in _LANG_OPTIONS}

# ---------------------------------------------------------------------------
# Page Configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Anova Typist",
    page_icon="🖨️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# CSS — Anova Colour Palette
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* ---------------------------------------------------------------
       Anova Brand Palette
       Charcoal  #3A3A3A  — primary text / headings
       Coral     #E85C4A  — accents, CTAs, highlights
       Amber     #F7931E  — warnings
       Teal      #4ECDC4  — secondary accents, dividers
       White     #FFFFFF  — backgrounds
       Light Grey #F4F4F4 — page backgrounds, stripes
    --------------------------------------------------------------- */

    /* General background */
    .stApp { background-color: #F4F4F4; }

    /* Header area */
    .typist-header {
        background: linear-gradient(135deg, #3A3A3A 0%, #5A5A5A 100%);
        padding: 2rem 2.5rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
        border-bottom: 4px solid #4ECDC4;
    }
    .typist-header h1 {
        color: white !important;
        font-size: 2rem;
        margin: 0;
        font-weight: 700;
    }
    .typist-header p {
        color: #D0D0D0;
        margin: 0.5rem 0 0 0;
        font-size: 1rem;
    }
    .typist-header .accent { color: #E85C4A; }

    /* Upload box */
    .upload-box {
        border: 2px dashed #4ECDC4;
        border-radius: 10px;
        padding: 2rem;
        text-align: center;
        background: white;
        margin-bottom: 1rem;
    }

    /* Result cards */
    .result-card {
        background: white;
        border-radius: 10px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        border-left: 4px solid #E85C4A;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    .result-card h3 {
        color: #3A3A3A;
        margin-top: 0;
    }

    /* Metadata table */
    .meta-row {
        display: flex;
        padding: 0.4rem 0;
        border-bottom: 1px solid #F0F0F0;
    }
    .meta-key {
        font-weight: 600;
        color: #3A3A3A;
        min-width: 200px;
    }
    .meta-val { color: #555; }

    /* Uncertain warning box */
    .uncertain-warning {
        background: #FFF3CD;
        border: 1px solid #F7931E;
        border-left: 5px solid #F7931E;
        border-radius: 8px;
        padding: 1rem 1.25rem;
        margin-bottom: 1rem;
        color: #7A4A00;
        font-weight: 600;
    }
    .uncertain-warning .warn-title {
        font-size: 1.05rem;
        margin-bottom: 0.3rem;
    }
    .uncertain-warning .warn-body {
        font-weight: 400;
        font-size: 0.9rem;
        color: #5A3A00;
    }

    /* Download button */
    .stDownloadButton > button {
        background: #E85C4A !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 0.7rem 2rem !important;
        font-size: 1rem !important;
        font-weight: 600 !important;
        width: 100%;
        transition: background 0.2s;
    }
    .stDownloadButton > button:hover {
        background: #C94A38 !important;
    }

    /* Progress steps */
    .step-indicator {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.6rem 1rem;
        border-radius: 6px;
        margin-bottom: 0.5rem;
        font-size: 0.95rem;
    }
    .step-active { background: #F4F4F4; color: #3A3A3A; border-left: 3px solid #4ECDC4; }
    .step-done   { background: #E6F9F7; color: #1A6A64; border-left: 3px solid #4ECDC4; }

    /* Format badges */
    .format-badge {
        display: inline-block;
        background: #F4F4F4;
        color: #3A3A3A;
        border: 1px solid #4ECDC4;
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 0.8rem;
        font-weight: 600;
        margin: 2px;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# API Key Management
# ---------------------------------------------------------------------------
def get_api_key() -> str | None:
    """Reads API key from .env first, then from sidebar input."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if key:
        return key
    return st.session_state.get("api_key", "")


# ---------------------------------------------------------------------------
# Sidebar — Settings
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## ⚙️ Settings")

    if not os.getenv("ANTHROPIC_API_KEY"):
        st.markdown("### 🔑 API Key")
        api_key_input = st.text_input(
            "Anthropic API Key",
            type="password",
            placeholder="sk-ant-...",
            help="Add ANTHROPIC_API_KEY to your .env file to hide this field.",
        )
        if api_key_input:
            st.session_state["api_key"] = api_key_input
            st.success("API key set ✓")
    else:
        st.success("API key loaded from .env ✓")

    st.markdown("---")
    st.markdown("### 🤖 Model")
    model = st.selectbox(
        "Claude Model",
        ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
        index=0,
        help="Sonnet recommended — best balance of speed and quality.",
    )

    st.markdown("---")
    st.markdown("### 🖼️ Image Handling")
    include_image_placeholders = st.checkbox(
        "Include image descriptions",
        value=False,
        help=(
            "When checked, images and diagrams found in the document will be "
            "described with [IMAGE: …] placeholders in the transcription. "
            "Uncheck to omit all image references."
        ),
    )

    st.markdown("---")
    st.markdown("### 📤 Bilingual Export")
    export_xliff = st.checkbox(
        "Export bilingual XLIFF file",
        value=False,
        help=(
            "In addition to the Word file, generate a standard XLIFF 1.2 bilingual file "
            "(.xlf) for import into any CAT tool — "
            "SDL Trados, memoQ, Phrase, Wordfast, Déjà Vu, OmegaT, and all others. "
            "A separate Transcription Notes Word file will also be provided."
        ),
    )
    if export_xliff:
        st.caption(
            "Select the language codes that **exactly match** your CAT tool project settings."
        )
        src_label = st.selectbox(
            "Source language *",
            options=_LANG_LABELS,
            index=0,
            help="BCP-47 code for the document's source language. Must match the source language in your CAT tool project.",
        )
        tgt_label = st.selectbox(
            "Target language *",
            options=_LANG_LABELS,
            index=0,
            help="BCP-47 code for the translation target language. Must match the target language in your CAT tool project.",
        )
        source_lang_input = _LANG_CODE_OF.get(src_label, "")
        target_lang_input = _LANG_CODE_OF.get(tgt_label, "")

        if not source_lang_input:
            st.warning("⚠️ Select a source language to generate the XLIFF file.")
        if not target_lang_input:
            st.warning("⚠️ Select a target language to generate the XLIFF file.")
    else:
        source_lang_input = ""
        target_lang_input = ""

    st.markdown("---")
    st.markdown("### 📋 Supported Formats")
    for fmt in sorted(set(SUPPORTED_FORMATS.keys())):
        st.markdown(f'<span class="format-badge">.{fmt.upper()}</span>', unsafe_allow_html=True)

    st.markdown(f"\n**Max size:** {MAX_FILE_SIZE_MB} MB")

    st.markdown("---")
    st.markdown(
        "<small>Anova Translation © 2026 | "
        "[portal.anova.bg](https://portal.anova.bg)</small>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Main Header
# ---------------------------------------------------------------------------
st.markdown("""
<div class="typist-header">
    <h1>🖨️ Anova <span class="accent">Typist</span></h1>
    <p>Digitise scanned documents with Claude Vision &mdash; download as a Word file</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# API Key Check
# ---------------------------------------------------------------------------
api_key = get_api_key()
if not api_key:
    st.warning("⚠️ Please enter your Anthropic API key in the sidebar.")
    st.info(
        "No API key? Create a free trial account at "
        "[console.anthropic.com](https://console.anthropic.com)."
    )
    st.stop()

# ---------------------------------------------------------------------------
# File Upload
# ---------------------------------------------------------------------------
st.markdown("### 📁 Upload Document")

uploaded_file = st.file_uploader(
    label="Drag and drop or browse for your PDF or image file",
    type=list(SUPPORTED_FORMATS.keys()),
    help=f"Max {MAX_FILE_SIZE_MB} MB. Supported: {', '.join(f'.{e.upper()}' for e in sorted(set(SUPPORTED_FORMATS.keys())))}",
)

# ---------------------------------------------------------------------------
# File Preview
# ---------------------------------------------------------------------------
if uploaded_file:
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f"**File:** `{uploaded_file.name}`")
        size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)
        st.markdown(f"**Size:** {size_mb:.2f} MB")

    with col2:
        ext = uploaded_file.name.lower().rsplit(".", 1)[-1]
        if ext in ("jpg", "jpeg", "png", "webp"):
            st.image(uploaded_file, caption="Preview", use_column_width=True)
        elif ext == "pdf":
            st.markdown("📄 PDF file uploaded")

# ---------------------------------------------------------------------------
# Action Button
# ---------------------------------------------------------------------------
st.markdown("---")

start_btn = st.button(
    "🔍 Start Transcription",
    type="primary",
    disabled=not uploaded_file,
    use_container_width=True,
)

# ---------------------------------------------------------------------------
# Processing  (runs only when Start button is clicked)
# ---------------------------------------------------------------------------
if start_btn and uploaded_file:
    file_bytes = uploaded_file.getvalue()
    filename   = uploaded_file.name

    progress_container = st.container()
    with progress_container:
        step1 = st.markdown(
            '<div class="step-indicator step-active">⏳ Step 1/3 — Sending file to Claude...</div>',
            unsafe_allow_html=True,
        )

    try:
        with st.spinner("Claude is reading and transcribing the document..."):
            result = transcribe_document(
                file_bytes=file_bytes,
                filename=filename,
                api_key=api_key,
                model=model,
                include_image_placeholders=include_image_placeholders,
            )

        step1.markdown(
            '<div class="step-indicator step-done">✅ Step 1/3 — Transcription complete</div>',
            unsafe_allow_html=True,
        )

        step2_label = (
            "⏳ Step 2/3 — Creating Word document and XLIFF 1.2 file..."
            if export_xliff else
            "⏳ Step 2/3 — Creating Word document..."
        )
        with progress_container:
            step2 = st.markdown(
                f'<div class="step-indicator step-active">{step2_label}</div>',
                unsafe_allow_html=True,
            )

        docx_bytes = create_docx(result)

        # --- Initialise bilingual editor state ---
        _f_ext          = filename.lower().rsplit(".", 1)[-1]
        editor_segments = get_segments_for_editor(result["content"])
        seg_total_pages = max((s["page"] for s in editor_segments), default=1)

        # For PDFs, use the file's own page count as the authoritative total
        # (guards against Claude emitting extra/missing PAGE BREAK markers).
        if _f_ext == "pdf":
            _pdf_count = _pdf_page_count(file_bytes)
            if _pdf_count and _pdf_count != seg_total_pages:
                # Clamp all segment page assignments to the actual page range
                for s in editor_segments:
                    s["page"] = min(s["page"], _pdf_count)
                seg_total_pages = _pdf_count

        st.session_state["t_segments"]          = editor_segments
        st.session_state["t_seg_texts"]         = {s["id"]: s["text"] for s in editor_segments}
        st.session_state["t_total_pages"]       = seg_total_pages
        st.session_state["t_editor_page"]       = 1
        st.session_state["t_file_bytes"]        = file_bytes
        st.session_state["t_file_ext"]          = _f_ext
        st.session_state["t_ready_for_download"] = False   # reveal only after Save & Export

        xliff_bytes    = None
        src_lang       = source_lang_input.strip()
        tgt_lang       = target_lang_input.strip()

        if export_xliff:
            if not src_lang or not tgt_lang:
                st.warning(
                    "⚠️ XLIFF file was not generated — both source and target language codes are required. "
                    "Select them in the sidebar and re-run."
                )
            else:
                # Pass docx_bytes as skeleton → enables round-trip apply-back
                xliff_bytes = create_xliff(result, tgt_lang, src_lang,
                                           docx_bytes=docx_bytes)

        step2.markdown(
            '<div class="step-indicator step-done">✅ Step 2/3 — Output files ready</div>',
            unsafe_allow_html=True,
        )
        with progress_container:
            st.markdown(
                '<div class="step-indicator step-done">✅ Step 3/3 — Ready to download</div>',
                unsafe_allow_html=True,
            )

        # ── Persist results in session_state so download buttons survive re-runs ──
        st.session_state["t_result"]           = result
        st.session_state["t_docx"]             = docx_bytes
        st.session_state["t_xliff"]            = xliff_bytes
        st.session_state["t_filename"]         = filename
        st.session_state["t_src_lang"]         = src_lang
        st.session_state["t_tgt_lang"]         = tgt_lang
        st.session_state["t_export_xliff"]     = export_xliff
        st.session_state["t_img_placeholders"] = include_image_placeholders
        st.session_state["t_model"]            = model

    except ValueError as e:
        st.error(f"❌ Error: {e}")
        st.session_state.pop("t_result", None)   # clear stale results on error
    except Exception as e:
        st.error(f"❌ Unexpected error: {e}")
        with st.expander("Technical details"):
            import traceback
            st.code(traceback.format_exc())
        st.session_state.pop("t_result", None)

# ---------------------------------------------------------------------------
# Results  (rendered from session_state — survives re-runs)
# ---------------------------------------------------------------------------
if "t_result" in st.session_state:
    from typist_core import _extract_uncertain_count

    result         = st.session_state["t_result"]
    docx_bytes     = st.session_state["t_docx"]
    xliff_bytes    = st.session_state["t_xliff"]
    filename       = st.session_state["t_filename"]
    final_src_lang = st.session_state["t_src_lang"]
    tgt_lang       = st.session_state["t_tgt_lang"]
    do_xliff       = st.session_state["t_export_xliff"]
    img_ph         = st.session_state["t_img_placeholders"]
    used_model     = st.session_state["t_model"]

    uncertain_count = _extract_uncertain_count(result.get("metadata", ""))

    st.markdown("---")

    # ── Uncertain elements warning ──────────────────────────────────────────
    if uncertain_count > 0:
        st.markdown(
            f'<div class="uncertain-warning">'
            f'<div class="warn-title">⚠️ Attention: {uncertain_count} uncertain element(s) detected</div>'
            f'<div class="warn-body">'
            f'Some portions could not be read with full confidence. '
            f'Flagged items are highlighted in the editor and the Word file. '
            f'Please review them carefully.'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    stem = filename.rsplit(".", 1)[0]

    # ── Download buttons — visible only AFTER Save & Export ────────────────
    if st.session_state.get("t_ready_for_download"):
        st.markdown("## 📥 Download Files")

        if do_xliff and xliff_bytes:
            col_docx, col_xliff = st.columns(2)
            with col_docx:
                st.download_button(
                    label="⬇️ Transcription Notes (.docx)",
                    data=docx_bytes,
                    file_name=stem + "_transcription_notes.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                    help="Full report with corrected transcription.",
                )
            with col_xliff:
                st.download_button(
                    label="⬇️ Bilingual File (.xlf)",
                    data=xliff_bytes,
                    file_name=stem + ".xlf",
                    mime="application/xliff+xml",
                    use_container_width=True,
                    help=f"XLIFF 1.2 — Source: {final_src_lang} → Target: {tgt_lang}",
                )
            st.caption(f"XLIFF 1.2 | Source: `{final_src_lang}` → Target: `{tgt_lang}`")

        elif do_xliff and not xliff_bytes:
            st.download_button(
                label="⬇️ Transcription Notes (.docx)",
                data=docx_bytes,
                file_name=stem + "_transcription_notes.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            st.warning(
                "⚠️ XLIFF file was not generated — both source and target language codes are required."
            )

        else:
            st.download_button(
                label="⬇️ Download Word File (.docx)",
                data=docx_bytes,
                file_name=stem + "_transcription.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )

        st.markdown("---")

    img_label = "with image descriptions" if img_ph else "without image descriptions"
    st.caption(f"Model: `{used_model}` | File: `{filename}` | {img_label}")

# ---------------------------------------------------------------------------
# Bilingual Editor — review & correct transcription before export
# ---------------------------------------------------------------------------
if "t_segments" in st.session_state:
    import pandas as pd

    st.markdown("---")
    st.markdown("## ✏️ Transcription Editor")
    st.caption(
        "**Left:** original document | **Right:** transcribed text (editable). "
        "Correct any errors, then click **Save & Export** to generate your files."
    )

    all_segs      = st.session_state["t_segments"]
    seg_texts     = st.session_state["t_seg_texts"]
    total_pages   = st.session_state.get("t_total_pages", 1)
    file_bytes_ed = st.session_state.get("t_file_bytes")
    file_ext_ed   = st.session_state.get("t_file_ext", "")

    if "t_editor_page" not in st.session_state:
        st.session_state["t_editor_page"] = 1

    # ── Page navigation bar ─────────────────────────────────────────────────
    if total_pages > 1:
        def _go_prev():
            st.session_state["t_editor_page"] = max(1, st.session_state["t_editor_page"] - 1)
        def _go_next():
            st.session_state["t_editor_page"] = min(
                total_pages, st.session_state["t_editor_page"] + 1
            )

        nav1, nav2, nav3 = st.columns([1, 3, 1])
        with nav1:
            st.button("← Previous Page", on_click=_go_prev,
                      disabled=(st.session_state["t_editor_page"] == 1),
                      use_container_width=True, key="ed_prev")
        with nav2:
            cp = st.session_state["t_editor_page"]
            st.markdown(
                f"<p style='text-align:center;font-weight:700;font-size:1.05rem;"
                f"padding-top:6px;color:#3A3A3A'>Page {cp} / {total_pages}</p>",
                unsafe_allow_html=True,
            )
        with nav3:
            st.button("Next Page →", on_click=_go_next,
                      disabled=(st.session_state["t_editor_page"] == total_pages),
                      use_container_width=True, key="ed_next")

    current_page = st.session_state["t_editor_page"]

    # ── Two-column editor (full width) ──────────────────────────────────────
    left_panel, right_panel = st.columns([1, 1], gap="medium")

    with left_panel:
        st.markdown(
            "<p style='font-weight:700;font-size:0.95rem;"
            "color:#3A3A3A;margin-bottom:6px'>📄 Source Document</p>",
            unsafe_allow_html=True,
        )
        if file_bytes_ed:
            if file_ext_ed in ("jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif"):
                st.image(file_bytes_ed, use_column_width=True)
            elif file_ext_ed == "pdf":
                rendered = _render_pdf_page(file_bytes_ed, current_page - 1)
                if rendered:
                    st.image(rendered, use_column_width=True,
                             caption=f"Page {current_page} / {total_pages}")
                else:
                    st.info(
                        f"📄 PDF page {current_page}  \n"
                        "Install `pypdfium2` to enable page preview:  \n"
                        "`pip install pypdfium2`"
                    )
        else:
            st.info("Source file not available in this session.")

    with right_panel:
        st.markdown(
            "<p style='font-weight:700;font-size:0.95rem;"
            "color:#3A3A3A;margin-bottom:6px'>✏️ Transcription (editable)</p>",
            unsafe_allow_html=True,
        )

        page_segs = [s for s in all_segs if s["page"] == current_page]

        if page_segs:
            _type_abbr = {
                "paragraph": "PAR", "heading": "HDG",
                "list":      "LST", "table":   "TBL",
            }
            df_rows = [
                {
                    "id":            seg["id"],
                    "T":             _type_abbr.get(seg["type"], "PAR"),
                    "Transcription": seg_texts.get(seg["id"], seg["text"]),
                }
                for seg in page_segs
            ]
            df = pd.DataFrame(df_rows)

            edited_df = st.data_editor(
                df,
                column_config={
                    "id": None,
                    "T":  st.column_config.TextColumn(
                        "T", disabled=True, width=40,
                        help="PAR · HDG · LST · TBL",
                    ),
                    "Transcription": st.column_config.TextColumn(
                        "Transcription", width="large",
                        help="Click a cell to edit. Tab / Enter to confirm.",
                    ),
                },
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                height=700,
                key=f"editor_p{current_page}",
            )

            # Persist edits to the master dict on every render.
            # Because data_editor triggers a re-run on each cell change,
            # all edits are saved before the user can navigate away.
            for _, row in edited_df.iterrows():
                seg_id = row["id"]
                if seg_id in seg_texts:
                    st.session_state["t_seg_texts"][seg_id] = row["Transcription"]
        else:
            st.info("No transcribed segments for this page.")

    # ── Save & Export ───────────────────────────────────────────────────────
    st.markdown("")
    save_col, _ = st.columns([2, 3])
    with save_col:
        save_btn = st.button(
            "💾 Save & Export",
            type="primary",
            use_container_width=True,
            key="save_export_btn",
        )

    if save_btn:
        with st.spinner("Rebuilding files from edited segments…"):
            updated_segs = [
                dict(s, text=st.session_state["t_seg_texts"].get(s["id"], s["text"]))
                for s in st.session_state["t_segments"]
            ]
            updated_content = reconstruct_content_from_segments(updated_segs)

            updated_result            = dict(st.session_state["t_result"])
            updated_result["content"] = updated_content

            updated_docx = create_docx(updated_result)
            st.session_state["t_docx"]   = updated_docx
            st.session_state["t_result"] = updated_result

            if (st.session_state.get("t_export_xliff")
                    and st.session_state.get("t_src_lang")
                    and st.session_state.get("t_tgt_lang")):
                updated_xliff = create_xliff(
                    updated_result,
                    st.session_state["t_tgt_lang"],
                    st.session_state["t_src_lang"],
                    docx_bytes=updated_docx,
                )
                st.session_state["t_xliff"] = updated_xliff

        st.session_state["t_ready_for_download"] = True
        st.rerun()   # re-render → download buttons now visible at top

# ---------------------------------------------------------------------------
# Transcription details tabs (always visible for reference after processing)
# ---------------------------------------------------------------------------
if "t_result" in st.session_state and st.session_state.get("t_ready_for_download"):
    result          = st.session_state["t_result"]
    img_ph          = st.session_state.get("t_img_placeholders", False)
    used_model      = st.session_state.get("t_model", "")
    filename        = st.session_state.get("t_filename", "")
    from typist_core import _extract_uncertain_count
    uncertain_count = _extract_uncertain_count(result.get("metadata", ""))

    st.markdown("---")
    st.markdown("### 📊 Transcription Details")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Document Info", "📝 Transcription", "🎨 Formatting", "🔍 Quality"
    ])

    with tab1:
        st.markdown("### Document Metadata")
        st.code(result["metadata"], language=None)

    with tab2:
        st.markdown("### Transcription Content")
        if uncertain_count > 0:
            st.info(
                f"ℹ️ {uncertain_count} uncertain element(s) are flagged inline with "
                "`[UNCERTAIN]`, `[HANDWRITTEN - UNCERTAIN]`, or similar markers."
            )
        st.markdown(
            f'<div class="result-card">{result["content"]}</div>',
            unsafe_allow_html=True,
        )
        with st.expander("Raw text (for copy-paste)"):
            st.text_area(
                "Transcription",
                value=result["content"],
                height=300,
                label_visibility="collapsed",
            )

    with tab3:
        st.markdown("### Formatting Notes")
        st.info(result["formatting_notes"])

    with tab4:
        st.markdown("### Quality Notes")
        quality = result["quality_notes"]
        if "high confidence" in quality.lower() or "no manual review" in quality.lower():
            st.success(quality)
        else:
            st.warning(quality)

# ---------------------------------------------------------------------------
# Apply Translation — upload translated XLIFF → get translated Word
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 🔄 Apply Translation")
st.caption(
    "After translating the XLIFF file in your CAT tool, upload it here "
    "to generate the translated Word document."
)

translated_xliff = st.file_uploader(
    "Upload translated XLIFF (.xlf)",
    type=["xlf", "xliff"],
    key="apply_xliff_upload",
    help="Upload the translated .xlf file exported from your CAT tool.",
)

if translated_xliff:
    apply_btn = st.button("🔄 Generate Translated Word Document", type="primary",
                          use_container_width=True)
    if apply_btn:
        try:
            with st.spinner("Applying translations to Word document…"):
                translated_docx = apply_xliff_to_docx(translated_xliff.getvalue())

            xlf_stem = translated_xliff.name.rsplit(".", 1)[0]
            st.download_button(
                label="⬇️ Download Translated Word File (.docx)",
                data=translated_docx,
                file_name=xlf_stem + "_translated.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
            st.success("✅ Translations applied successfully.")
        except ValueError as e:
            st.error(f"❌ {e}")
        except Exception as e:
            st.error(f"❌ Unexpected error: {e}")
            with st.expander("Technical details"):
                import traceback
                st.code(traceback.format_exc())

# ---------------------------------------------------------------------------
# Help section when no file is uploaded
# ---------------------------------------------------------------------------
if not uploaded_file:
    st.markdown("---")
    with st.expander("ℹ️ How it works"):
        st.markdown("""
        1. **Upload your file** — PDF, JPEG, PNG, TIFF, BMP or WebP
        2. Click **Start Transcription**
        3. Claude Vision reads the document and extracts the text
        4. **Download the Word file** — a 4-section report:
           - Document information (language, page count, quality)
           - Full transcription (formatting preserved)
           - Formatting notes
           - Quality assessment
        """)

    with st.expander("📌 Tips for best results"):
        st.markdown("""
        - **Scan quality:** 300 DPI or higher gives the best results
        - **Multi-page PDF:** Upload as a single file — all pages are processed
        - **Handwriting:** Supported, but unclear portions are flagged `[HANDWRITTEN - UNCERTAIN]`
        - **Mixed languages:** Auto-detected; language switches are labelled
        - **Image descriptions:** Enable the checkbox in the sidebar to include `[IMAGE: …]` placeholders
        """)
