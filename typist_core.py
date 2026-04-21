"""
typist_core.py — Anova Typist Çekirdek Mantığı
===============================================
Bu modül hem Streamlit prototipinde hem de FastAPI portalında kullanılır.
Bağımlılık: anthropic, python-docx, Pillow
"""

import base64
import io
import re
from datetime import date
from typing import Optional

import anthropic
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Pt, RGBColor, Cm
from PIL import Image

# ---------------------------------------------------------------------------
# Desteklenen formatlar
# ---------------------------------------------------------------------------
SUPPORTED_FORMATS = {
    "pdf":  "application/pdf",
    "jpeg": "image/jpeg",
    "jpg":  "image/jpeg",
    "png":  "image/png",
    "webp": "image/webp",
    "tiff": "image/png",   # Pillow ile PNG'ye dönüştürülür
    "tif":  "image/png",
    "bmp":  "image/png",   # Pillow ile PNG'ye dönüştürülür
}

MAX_FILE_SIZE_MB = 20

# ---------------------------------------------------------------------------
# Typist Prompt (SKILL.md ile birebir uyumlu)
# ---------------------------------------------------------------------------
TYPIST_PROMPT = """You are a professional document digitization and transcription agent.
Convert the uploaded document into accurately formatted, machine-readable text while
preserving original layout, character formatting, and linguistic integrity.

## Step 1 — Pre-Transcription Analysis
Identify: page count, structure (headings/body/margins/columns), formatting
(bold/italic/underline/font sizes), layout (headers/footers/tables/lists),
document type, special characters, language(s), scan quality.

## Step 2 — Transcribe
Extract ALL visible text in reading order (left-to-right, top-to-bottom).

## Transcription Rules
- Extract ALL visible text in reading order
- Preserve spacing that indicates structure (line breaks, paragraph breaks)
- Use Markdown formatting: **bold**, *italic*, [UNDERLINED: text]
- Headings: # H1, ## H2, ### H3
- Tables: pipe format | Col1 | Col2 |
- Lists: - unordered, 1. ordered
- Page breaks: ---PAGE BREAK---
- Unclear word: [?word] | Image/diagram: [IMAGE: description]
- Uncertain handwriting: [HANDWRITTEN - UNCERTAIN: text]
- Illegible: [HANDWRITTEN - ILLEGIBLE]
- Language switch: [LANGUAGE SWITCH: Language]
- Forms: [FILLED: response] or [BLANK FIELD]
- NEVER correct spelling mistakes — preserve as-is
- Distinguish carefully: O vs 0, l vs 1, I vs 1
- Preserve all diacritics: é, ñ, ü, ş, ğ, č, etc.
- TWO-COLUMN TABLE LAYOUTS: Many forms and patent documents use a two-column table
  where field labels appear in the left column and values (or blank fields) in the right.
  ALWAYS detect and transcribe these as pipe-format Markdown tables, even if column
  borders are faint, implied, or obscured by watermarks. Do not skip any field.

## Step 3 — Output Format
Structure your response EXACTLY in these four sections with these exact headers:

### SECTION 1 — DOCUMENT METADATA
Document Type:         [Letter / Report / Form / Table / etc.]
Languages Identified:  [ISO code (Language name) — Confidence: High/Medium/Low]
Total Pages:           [X]
Scan Quality:          [Excellent / Good / Fair / Poor]
Handwritten Content:   [Yes (approx. X%) / No]
Transcription Date:    [YYYY-MM-DD]
Uncertain Elements:    [X flagged items]

### SECTION 2 — TRANSCRIBED CONTENT
[Full transcribed text with all formatting preserved]

### SECTION 3 — FORMATTING NOTES
[Formatting decisions, ambiguities resolved, layout choices]

### SECTION 4 — QUALITY NOTES
[Limitations, unclear sections, recommendations. If no issues: "Document transcribed with high confidence. No manual review required."]
"""

# ---------------------------------------------------------------------------
# Yardımcı: Görsel dönüşüm (TIFF, BMP → PNG)
# ---------------------------------------------------------------------------
def _convert_to_supported(file_bytes: bytes, ext: str) -> tuple[bytes, str]:
    """TIFF/BMP dosyalarını Claude'un desteklediği PNG formatına dönüştürür."""
    if ext in ("tiff", "tif", "bmp"):
        img = Image.open(io.BytesIO(file_bytes))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    return file_bytes, SUPPORTED_FORMATS[ext]


# ---------------------------------------------------------------------------
# Ana Transkripsiyon Fonksiyonu
# ---------------------------------------------------------------------------
def transcribe_document(
    file_bytes: bytes,
    filename: str,
    api_key: str,
    model: str = "claude-sonnet-4-6",
) -> dict:
    """
    Dokümanı Claude Vision ile transkribe eder.

    Returns:
        {
            "raw":               str,   # Claude'un tam yanıtı
            "metadata":          str,   # Section 1 içeriği
            "content":           str,   # Section 2 — transkripsiyon
            "formatting_notes":  str,   # Section 3
            "quality_notes":     str,   # Section 4
            "filename":          str,
            "model":             str,
        }
    Raises:
        ValueError: Desteklenmeyen format veya büyük dosya
        anthropic.APIError: API hatası
    """
    # --- Validasyon ---
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Desteklenmeyen format: .{ext}\n"
            f"Desteklenenler: {', '.join(f'.{e}' for e in SUPPORTED_FORMATS)}"
        )

    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise ValueError(f"Dosya çok büyük: {size_mb:.1f} MB (max {MAX_FILE_SIZE_MB} MB)")

    # --- İçerik bloğunu hazırla ---
    client = anthropic.Anthropic(api_key=api_key)

    if ext == "pdf":
        file_b64 = base64.standard_b64encode(file_bytes).decode()
        content_blocks = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": file_b64,
                },
            },
            {"type": "text", "text": TYPIST_PROMPT},
        ]
    else:
        converted_bytes, media_type = _convert_to_supported(file_bytes, ext)
        file_b64 = base64.standard_b64encode(converted_bytes).decode()
        content_blocks = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": file_b64,
                },
            },
            {"type": "text", "text": TYPIST_PROMPT},
        ]

    # --- Claude API çağrısı ---
    message = client.messages.create(
        model=model,
        max_tokens=8192,
        messages=[{"role": "user", "content": content_blocks}],
    )

    raw_text = message.content[0].text

    # --- Yanıtı parse et ---
    sections = _parse_sections(raw_text)
    sections["raw"] = raw_text
    sections["filename"] = filename
    sections["model"] = model

    return sections


# ---------------------------------------------------------------------------
# Response Parser
# ---------------------------------------------------------------------------
def _strip_code_fences(text: str) -> str:
    """
    Claude bazen metadata bölümünü ``` kod bloğuna sarar.
    Bu fonksiyon tüm açılış ve kapanış ``` işaretlerini temizler.
    Metadata bölümünde asla gerçek kod bloğu olmaz.
    """
    # Tüm ``` fence satırlarını kaldır (başında veya sonunda ne olursa)
    text = re.sub(r"```[a-zA-Z]*", "", text)
    return text.strip()


def _clean_html_entities(text: str) -> str:
    """&nbsp; ve diğer yaygın HTML entity'lerini temiz karakterlere çevirir."""
    replacements = {
        "&nbsp;":  " ",
        "&amp;":   "&",
        "&lt;":    "<",
        "&gt;":    ">",
        "&quot;":  '"',
        "&#39;":   "'",
        "&mdash;": "—",
        "&ndash;": "–",
        "&hellip;": "…",
    }
    for entity, char in replacements.items():
        text = text.replace(entity, char)
    return text


def _parse_sections(text: str) -> dict:
    """Claude yanıtından 4 bölümü ayıklar."""
    pattern = re.compile(
        r"###\s*SECTION\s*(\d)\s*[—–-]\s*[^\n]+\n(.*?)(?=###\s*SECTION\s*\d|$)",
        re.DOTALL | re.IGNORECASE,
    )
    found = {m.group(1): m.group(2).strip() for m in pattern.finditer(text)}

    # Metadata bölümündeki kod fence işaretlerini temizle
    metadata_raw = found.get("1", "Metadata ayrıştırılamadı.")
    metadata_clean = _strip_code_fences(metadata_raw)

    # Tüm bölümlerde HTML entity'lerini temizle
    return {
        "metadata":         _clean_html_entities(metadata_clean),
        "content":          _clean_html_entities(found.get("2", "İçerik ayrıştırılamadı.")),
        "formatting_notes": _clean_html_entities(found.get("3", "Biçimlendirme notu bulunamadı.")),
        "quality_notes":    _clean_html_entities(found.get("4", "Kalite notu bulunamadı.")),
    }


# ---------------------------------------------------------------------------
# DOCX Üreticisi
# ---------------------------------------------------------------------------
def create_docx(result: dict) -> bytes:
    """
    Transkripsiyon sonucundan Word belgesi üretir.
    Döndürür: DOCX dosyasının bytes içeriği
    """
    doc = Document()

    # --- Sayfa yapısı ---
    section = doc.sections[0]
    section.page_width  = Cm(21)
    section.page_height = Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.5)
    section.top_margin  = section.bottom_margin = Cm(2.5)

    # --- Stil yardımcıları ---
    ANOVA_NAVY  = RGBColor(0x1B, 0x2A, 0x4A)
    ANOVA_ORANGE = RGBColor(0xF0, 0x6A, 0x00)

    def add_heading(text: str, level: int = 1):
        p = doc.add_heading(text, level=level)
        for run in p.runs:
            run.font.color.rgb = ANOVA_NAVY if level == 1 else ANOVA_ORANGE
        return p

    def add_divider():
        p = doc.add_paragraph()
        pPr = p._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), "1B2A4A")
        pBdr.append(bottom)
        pPr.append(pBdr)

    # --- Başlık ---
    title = doc.add_heading("Anova Typist — Transkripsiyon Raporu", 0)
    for run in title.runs:
        run.font.color.rgb = ANOVA_NAVY

    subtitle = doc.add_paragraph(f"Dosya: {result.get('filename', 'bilinmiyor')}")
    subtitle.runs[0].font.size = Pt(10)
    subtitle.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    subtitle.runs[0].font.italic = True

    add_divider()
    doc.add_paragraph()

    # --- Bölüm 1: Metadata ---
    add_heading("1. Doküman Bilgileri", level=1)
    meta_lines = result.get("metadata", "").splitlines()
    for line in meta_lines:
        if ":" in line:
            key, _, val = line.partition(":")
            p = doc.add_paragraph()
            run_key = p.add_run(key.strip() + ": ")
            run_key.bold = True
            run_key.font.size = Pt(10)
            p.add_run(val.strip()).font.size = Pt(10)
        elif line.strip():
            doc.add_paragraph(line.strip()).runs[0].font.size = Pt(10)

    add_divider()
    doc.add_paragraph()

    # --- Bölüm 2: Transkripsiyon ---
    add_heading("2. Transkripsiyon", level=1)
    _add_markdown_content(doc, result.get("content", ""))

    add_divider()
    doc.add_paragraph()

    # --- Bölüm 3: Biçimlendirme Notları ---
    add_heading("3. Biçimlendirme Notları", level=1)
    doc.add_paragraph(result.get("formatting_notes", "")).runs[0].font.size = Pt(10)

    add_divider()
    doc.add_paragraph()

    # --- Bölüm 4: Kalite Notları ---
    add_heading("4. Kalite Notları", level=1)
    doc.add_paragraph(result.get("quality_notes", "")).runs[0].font.size = Pt(10)

    # --- Footer ---
    doc.add_paragraph()
    footer_p = doc.add_paragraph(
        f"Anova Translation | Üretildi: {date.today().isoformat()} | Model: {result.get('model', 'claude-sonnet-4-6')}"
    )
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in footer_p.runs:
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0xAA, 0xAA, 0xAA)
        run.font.italic = True

    # --- Bytes olarak döndür ---
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Markdown → DOCX yardımcısı (temel)
# ---------------------------------------------------------------------------
def _add_markdown_content(doc: Document, text: str):
    """Markdown formatındaki metni DOCX paragraflarına dönüştürür."""
    lines = text.splitlines()
    i = 0
    table_buffer = []

    while i < len(lines):
        line = lines[i]

        # Sayfa sonu
        if "---PAGE BREAK---" in line or "[PAGE" in line.upper():
            doc.add_page_break()
            i += 1
            continue

        # Tablo başlangıcı
        if line.strip().startswith("|"):
            table_buffer.append(line)
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_buffer.append(lines[i])
                i += 1
            _add_table(doc, table_buffer)
            table_buffer = []
            continue

        # Başlıklar
        if line.startswith("# "):
            p = doc.add_heading(line[2:].strip(), level=2)
        elif line.startswith("## "):
            p = doc.add_heading(line[3:].strip(), level=3)
        elif line.startswith("### "):
            p = doc.add_heading(line[4:].strip(), level=4)

        # Sırasız liste
        elif line.strip().startswith("- "):
            p = doc.add_paragraph(style="List Bullet")
            _apply_inline_formatting(p, line.strip()[2:])

        # Sıralı liste
        elif re.match(r"^\d+\.\s", line.strip()):
            p = doc.add_paragraph(style="List Number")
            _apply_inline_formatting(p, re.sub(r"^\d+\.\s", "", line.strip()))

        # Boş satır
        elif not line.strip():
            doc.add_paragraph()

        # Normal paragraf
        else:
            p = doc.add_paragraph()
            _apply_inline_formatting(p, line)
            p.runs[0].font.size = Pt(10) if p.runs else None

        i += 1


def _apply_inline_formatting(paragraph, text: str):
    """**bold**, *italic* gibi inline Markdown formatını uygular."""
    # Basit bold/italic parser
    parts = re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("*") and part.endswith("*"):
            run = paragraph.add_run(part[1:-1])
            run.italic = True
        else:
            paragraph.add_run(part)


def _add_table(doc: Document, lines: list[str]):
    """Markdown tablo satırlarından DOCX tablosu oluşturur."""
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in lines
        if not re.match(r"^\|[-| :]+\|$", line.strip())  # separator satırını atla
    ]
    if not rows:
        return

    col_count = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=col_count)
    table.style = "Table Grid"

    for r_idx, row in enumerate(rows):
        for c_idx, cell_text in enumerate(row):
            if c_idx < col_count:
                cell = table.cell(r_idx, c_idx)
                cell.text = cell_text
                if r_idx == 0:  # Header row bold
                    for run in cell.paragraphs[0].runs:
                        run.bold = True
