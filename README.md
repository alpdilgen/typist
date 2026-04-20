# Anova Typist — Streamlit Prototipi

Taranmış dokümanları (PDF, JPEG, PNG, TIFF, BMP, WebP) Claude Vision ile
transkribe eden ve Word (.docx) dosyası olarak indiren Streamlit uygulaması.

> **Not:** Bu repo, `portal.anova.bg`'ye entegrasyon öncesi test için kullanılır.
> `typist_core.py` modülü değiştirilmeden FastAPI backend'e taşınabilir.

---

## Yerel Kurulum

```bash
# 1. Repoyu klonla
git clone https://github.com/[kullanıcı-adı]/anova-typist.git
cd anova-typist

# 2. Sanal ortam oluştur
python -m venv venv
source venv/bin/activate        # Mac/Linux
venv\Scripts\activate           # Windows

# 3. Bağımlılıkları kur
pip install -r requirements.txt

# 4. API anahtarını ayarla
cp .env.example .env
# .env dosyasını aç, ANTHROPIC_API_KEY değerini gir

# 5. Uygulamayı başlat
streamlit run app.py
```

Uygulama `http://localhost:8501` adresinde açılır.

---

## Streamlit Cloud Deployment

1. Bu repoyu GitHub'a push edin
2. [share.streamlit.io](https://share.streamlit.io) adresine gidin
3. **New app** → Repoyu seçin → `app.py` dosyasını seçin
4. **Advanced settings → Secrets** kısmına ekleyin:

```toml
ANTHROPIC_API_KEY = "sk-ant-buraya-girin"
```

5. **Deploy** butonuna tıklayın — uygulama canlıya alınır.

---

## Proje Yapısı

```
anova-typist/
├── app.py              ← Streamlit arayüzü
├── typist_core.py      ← Çekirdek mantık (portal'a taşınacak)
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Portal'a Taşıma (Migration)

Test başarılı olduğunda `typist_core.py` direkt olarak `portal.anova.bg/backend/services/typist_service.py` olarak kopyalanır.
Backend'de yapılacak tek değişiklik:

```python
# routers/typist.py
from fastapi import APIRouter, UploadFile, File, Request
from fastapi.responses import Response
from services.typist_service import transcribe_document, create_docx
import config

router = APIRouter()

@router.post("/typist/process")
async def typist_process(request: Request, file: UploadFile = File(...)):
    contents = await file.read()
    result = transcribe_document(contents, file.filename, config.ANTHROPIC_API_KEY)
    docx_bytes = create_docx(result)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=transkripsiyon.docx"}
    )
```

---

## Desteklenen Formatlar

| Format | Notlar |
|--------|--------|
| PDF | Çok sayfalı desteklenir, Claude native PDF okuma kullanır |
| JPEG / JPG | Direkt Claude Vision |
| PNG | Direkt Claude Vision |
| WebP | Direkt Claude Vision |
| TIFF / TIF | Pillow ile PNG'ye dönüştürülür |
| BMP | Pillow ile PNG'ye dönüştürülür |

**Maksimum dosya boyutu:** 20 MB

---

## Lisans

Anova Translation dahili kullanım — © 2026
