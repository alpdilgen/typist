"""
app.py — Anova Typist Streamlit Arayüzü
========================================
Taranmış doküman → Claude Vision transkripsiyon → Word (.docx) indirme
"""

import os
import streamlit as st
from dotenv import load_dotenv
from typist_core import (
    transcribe_document,
    create_docx,
    SUPPORTED_FORMATS,
    MAX_FILE_SIZE_MB,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Sayfa Yapılandırması
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Anova Typist",
    page_icon="🖨️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# CSS — Anova Renk Paleti
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* Genel arka plan */
    .stApp { background-color: #F8F9FA; }

    /* Başlık alanı */
    .typist-header {
        background: linear-gradient(135deg, #1B2A4A 0%, #2C3E6B 100%);
        padding: 2rem 2.5rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .typist-header h1 {
        color: white !important;
        font-size: 2rem;
        margin: 0;
        font-weight: 700;
    }
    .typist-header p {
        color: #C8D4F0;
        margin: 0.5rem 0 0 0;
        font-size: 1rem;
    }
    .typist-header .accent { color: #F06A00; }

    /* Upload kutusu */
    .upload-box {
        border: 2px dashed #1B2A4A;
        border-radius: 10px;
        padding: 2rem;
        text-align: center;
        background: white;
        margin-bottom: 1rem;
    }

    /* Sonuç kartları */
    .result-card {
        background: white;
        border-radius: 10px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        border-left: 4px solid #F06A00;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    .result-card h3 {
        color: #1B2A4A;
        margin-top: 0;
    }

    /* Metadata tablosu */
    .meta-row {
        display: flex;
        padding: 0.4rem 0;
        border-bottom: 1px solid #F0F0F0;
    }
    .meta-key {
        font-weight: 600;
        color: #1B2A4A;
        min-width: 200px;
    }
    .meta-val { color: #444; }

    /* İndirme butonu */
    .stDownloadButton > button {
        background: #F06A00 !important;
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
        background: #D45A00 !important;
    }

    /* İlerleme */
    .step-indicator {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.6rem 1rem;
        border-radius: 6px;
        margin-bottom: 0.5rem;
        font-size: 0.95rem;
    }
    .step-active  { background: #EDF2FF; color: #1B2A4A; }
    .step-done    { background: #E6F9F0; color: #1A7A4A; }

    /* Format badge'leri */
    .format-badge {
        display: inline-block;
        background: #EDF2FF;
        color: #1B2A4A;
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 0.8rem;
        font-weight: 600;
        margin: 2px;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# API Key Yönetimi
# ---------------------------------------------------------------------------
def get_api_key() -> str | None:
    """Önce .env dosyasından, sonra sidebar'dan alır."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if key:
        return key
    return st.session_state.get("api_key", "")


# ---------------------------------------------------------------------------
# Sidebar — Ayarlar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## ⚙️ Ayarlar")

    if not os.getenv("ANTHROPIC_API_KEY"):
        st.markdown("### 🔑 API Anahtarı")
        api_key_input = st.text_input(
            "Anthropic API Key",
            type="password",
            placeholder="sk-ant-...",
            help=".env dosyasına ANTHROPIC_API_KEY eklerseniz bu alan kaybolur.",
        )
        if api_key_input:
            st.session_state["api_key"] = api_key_input
            st.success("API anahtarı ayarlandı ✓")
    else:
        st.success("API anahtarı .env'den yüklendi ✓")

    st.markdown("---")
    st.markdown("### 🤖 Model")
    model = st.selectbox(
        "Claude Modeli",
        ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
        index=0,
        help="Sonnet önerilir — hız/kalite dengesi en iyi.",
    )

    st.markdown("---")
    st.markdown("### 📋 Desteklenen Formatlar")
    for fmt in sorted(set(SUPPORTED_FORMATS.keys())):
        st.markdown(f'<span class="format-badge">.{fmt.upper()}</span>', unsafe_allow_html=True)

    st.markdown(f"\n**Max boyut:** {MAX_FILE_SIZE_MB} MB")

    st.markdown("---")
    st.markdown(
        "<small>Anova Translation © 2026 | "
        "[portal.anova.bg](https://portal.anova.bg)</small>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Ana Başlık
# ---------------------------------------------------------------------------
st.markdown("""
<div class="typist-header">
    <h1>🖨️ Anova <span class="accent">Typist</span></h1>
    <p>Taranmış dokümanları Claude Vision ile dijitalleştirin — Word dosyası olarak indirin</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# API Key Kontrolü
# ---------------------------------------------------------------------------
api_key = get_api_key()
if not api_key:
    st.warning("⚠️ Lütfen sol panelden Anthropic API anahtarınızı girin.")
    st.info(
        "API anahtarı yoksa [console.anthropic.com](https://console.anthropic.com) "
        "adresinden ücretsiz deneme hesabı açabilirsiniz."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Dosya Yükleme
# ---------------------------------------------------------------------------
st.markdown("### 📁 Doküman Yükle")

accepted_types = list(set(
    f"image/{v.split('/')[1]}" if v.startswith("image/") else v
    for v in SUPPORTED_FORMATS.values()
) | {"application/pdf"})

uploaded_file = st.file_uploader(
    label="PDF veya görsel dosyanızı sürükleyin / seçin",
    type=list(SUPPORTED_FORMATS.keys()),
    help=f"Max {MAX_FILE_SIZE_MB} MB. Desteklenen: {', '.join(f'.{e.upper()}' for e in sorted(set(SUPPORTED_FORMATS.keys())))}",
)

# ---------------------------------------------------------------------------
# Dosya Önizleme
# ---------------------------------------------------------------------------
if uploaded_file:
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f"**Dosya:** `{uploaded_file.name}`")
        size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)
        st.markdown(f"**Boyut:** {size_mb:.2f} MB")

    with col2:
        ext = uploaded_file.name.lower().rsplit(".", 1)[-1]
        if ext in ("jpg", "jpeg", "png", "webp"):
            st.image(uploaded_file, caption="Önizleme", use_column_width=True)
        elif ext == "pdf":
            st.markdown("📄 PDF dosyası yüklendi")

# ---------------------------------------------------------------------------
# İşlem Butonu
# ---------------------------------------------------------------------------
st.markdown("---")

start_btn = st.button(
    "🔍 Transkripsiyon Başlat",
    type="primary",
    disabled=not uploaded_file,
    use_container_width=True,
)

# ---------------------------------------------------------------------------
# İşlem
# ---------------------------------------------------------------------------
if start_btn and uploaded_file:
    file_bytes = uploaded_file.getvalue()
    filename = uploaded_file.name

    # Adım göstergesi
    progress_container = st.container()

    with progress_container:
        step1 = st.markdown(
            '<div class="step-indicator step-active">⏳ Adım 1/3 — Dosya Claude\'a gönderiliyor...</div>',
            unsafe_allow_html=True,
        )

    try:
        # --- Transkripsiyon ---
        with st.spinner("Claude dokümanı okuyor ve transkribe ediyor..."):
            result = transcribe_document(
                file_bytes=file_bytes,
                filename=filename,
                api_key=api_key,
                model=model,
            )

        step1.markdown(
            '<div class="step-indicator step-done">✅ Adım 1/3 — Transkripsiyon tamamlandı</div>',
            unsafe_allow_html=True,
        )

        # --- DOCX Üretimi ---
        with progress_container:
            step2 = st.markdown(
                '<div class="step-indicator step-active">⏳ Adım 2/3 — Word belgesi oluşturuluyor...</div>',
                unsafe_allow_html=True,
            )

        docx_bytes = create_docx(result)

        step2.markdown(
            '<div class="step-indicator step-done">✅ Adım 2/3 — Word belgesi hazır</div>',
            unsafe_allow_html=True,
        )

        with progress_container:
            st.markdown(
                '<div class="step-indicator step-done">✅ Adım 3/3 — İndirmeye hazır</div>',
                unsafe_allow_html=True,
            )

        # ---------------------------------------------------------------------------
        # Sonuçlar
        # ---------------------------------------------------------------------------
        st.markdown("---")
        st.markdown("## 📊 Sonuçlar")

        # İndirme butonu — en üstte
        docx_filename = filename.rsplit(".", 1)[0] + "_transkripsiyon.docx"
        st.download_button(
            label="⬇️ Word Dosyasını İndir (.docx)",
            data=docx_bytes,
            file_name=docx_filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        st.markdown("---")

        # Sekmeler
        tab1, tab2, tab3, tab4 = st.tabs([
            "📋 Doküman Bilgileri",
            "📝 Transkripsiyon",
            "🎨 Biçimlendirme",
            "🔍 Kalite"
        ])

        with tab1:
            st.markdown("### Doküman Metadata")
            st.code(result["metadata"], language=None)

        with tab2:
            st.markdown("### Transkripsiyon İçeriği")
            st.markdown(
                f'<div class="result-card">{result["content"]}</div>',
                unsafe_allow_html=True,
            )
            # Ham metin de göster
            with st.expander("Ham metin (kopyalamak için)"):
                st.text_area(
                    "Transkripsiyon",
                    value=result["content"],
                    height=300,
                    label_visibility="collapsed",
                )

        with tab3:
            st.markdown("### Biçimlendirme Notları")
            st.info(result["formatting_notes"])

        with tab4:
            st.markdown("### Kalite Notları")
            quality = result["quality_notes"]
            if "high confidence" in quality.lower() or "no manual review" in quality.lower():
                st.success(quality)
            else:
                st.warning(quality)

        # Kullanılan model bilgisi
        st.caption(f"Model: `{model}` | Dosya: `{filename}`")

    except ValueError as e:
        st.error(f"❌ Hata: {e}")
    except Exception as e:
        st.error(f"❌ Beklenmeyen hata: {e}")
        with st.expander("Teknik detaylar"):
            import traceback
            st.code(traceback.format_exc())

# ---------------------------------------------------------------------------
# Henüz dosya yüklenmemişse yardım
# ---------------------------------------------------------------------------
if not uploaded_file:
    st.markdown("---")
    with st.expander("ℹ️ Nasıl çalışır?"):
        st.markdown("""
        1. **Dosyanızı yükleyin** — PDF, JPEG, PNG, TIFF, BMP veya WebP
        2. **Transkripsiyon başlat** butonuna tıklayın
        3. Claude Vision dokümanı okur ve metni çıkartır
        4. **Word dosyasını indirin** — 4 bölümlü rapor:
           - Doküman bilgileri (dil, sayfa sayısı, kalite)
           - Tam transkripsiyon (formatlar korunur)
           - Biçimlendirme notları
           - Kalite değerlendirmesi
        """)

    with st.expander("📌 İpuçları"):
        st.markdown("""
        - **En iyi sonuç için:** 300 DPI veya üzeri tarama kalitesi
        - **Çok sayfalı PDF:** Tek dosya olarak yükleyin, tüm sayfalar işlenir
        - **El yazısı:** Desteklenir ama belirsiz kısımlar `[HANDWRITTEN - UNCERTAIN]` ile işaretlenir
        - **Karışık dil:** Otomatik algılanır, dil geçişleri etiketlenir
        """)
