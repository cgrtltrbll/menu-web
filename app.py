import io
import json
import re
import base64
from datetime import date
from pathlib import Path

import requests
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import Color

MM = 72 / 25.4
def mm(x): return x * MM

# ---------------- Paths ----------------
APP_DIR = Path(__file__).resolve().parent
ICONS_DIR = APP_DIR / "icons"
TRANSLATIONS_FILE = APP_DIR / "translations.json"

# ---------------- Weekdays ----------------
DIAS_ES = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
DIAS_CA = ["Dilluns","Dimarts","Dimecres","Dijous","Divendres","Dissabte","Diumenge"]
DIAS_EN = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

# ---------------- Allergens ----------------
ALLERGENS = [
    ("gluten", "Gluten"),
    ("crustaceos", "Crustáceos"),
    ("huevo", "Huevo"),
    ("pescado", "Pescado"),
    ("cacahuetes", "Cacahuetes"),
    ("soja", "Soja"),
    ("lacteos", "Lácteos"),
    ("frutos_secos", "Frutos secos"),
    ("apio", "Apio"),
    ("mostaza", "Mostaza"),
    ("sesamo", "Sésamo"),
    ("sulfitos", "Sulfitos"),
    ("altramuces", "Altramuces"),
    ("moluscos", "Moluscos"),
]

# Tu repo (según tu captura)
ALLERGEN_ICON_MAP = {
    "altramuces": "altramuces.png",
    "apio": "apio.png",
    "cacahuetes": "cacahuetes.png",
    "crustaceos": "crustaceos.png",
    "frutos_secos": "frutos_secos.png",
    "gluten": "gluten.png",
    "huevo": "huevo.png",
    "lacteos": "lacteos.png",
    "moluscos": "moluscos.png",
    "mostaza": "mostaza.png",
    "pescado": "pescado.png",
    "sesamo": "sesamo.png",
    "soja": "soja.png",
    "sulfitos": "sulfitos.png",
}

# ---------------- Translations store ----------------
def load_translations() -> dict:
    default = {"es_to_ca": {}, "es_to_en": {}}
    if not TRANSLATIONS_FILE.exists():
        return default
    try:
        raw = TRANSLATIONS_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return default
        data = json.loads(raw)
        if not isinstance(data, dict):
            return default
        data.setdefault("es_to_ca", {})
        data.setdefault("es_to_en", {})
        if not isinstance(data["es_to_ca"], dict) or not isinstance(data["es_to_en"], dict):
            return default
        return data
    except Exception:
        return default

def save_translations(t: dict) -> None:
    # En Streamlit Cloud esto puede no persistir; por eso añadimos export/import.
    try:
        TRANSLATIONS_FILE.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

# ---------------- Text helpers ----------------
def normalize_es(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    if s:
        s = s[0].upper() + s[1:]
    return s

def tag_to_suffix(tag: str):
    if tag == "vegan":
        return (" (vegà)", " (vegano)", " (vegan)")
    if tag == "vegetarian":
        return (" (vegetari)", " (vegetariano)", " (vegetarian)")
    return ("", "", "")

# ---------------- Free translator (best-effort) ----------------
def libretranslate(text: str, target: str) -> str | None:
    """
    Best-effort using public LibreTranslate endpoints.
    If blocked/unavailable, returns None.
    """
    text = (text or "").strip()
    if not text:
        return ""
    endpoints = [
        "https://libretranslate.com/translate",
        "https://translate.argosopentech.com/translate",
    ]
    payload = {"q": text, "source": "es", "target": target, "format": "text"}
    headers = {"Content-Type": "application/json"}
    for url in endpoints:
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=6)
            if r.status_code == 200:
                data = r.json()
                out = data.get("translatedText")
                if isinstance(out, str) and out.strip():
                    return out.strip()
        except Exception:
            continue
    return None

def get_translations(es_raw: str, t: dict, ca_override: str, en_override: str, auto_translate: bool):
    es = normalize_es(es_raw)

    # Manual override wins
    if ca_override.strip():
        t["es_to_ca"][es] = ca_override.strip()
    if en_override.strip():
        t["es_to_en"][es] = en_override.strip()

    ca = t["es_to_ca"].get(es)
    en = t["es_to_en"].get(es)

    # Try free auto-translate only if not cached and enabled
    if auto_translate and ca is None:
        ca_try = libretranslate(es, "ca")
        if ca_try:
            t["es_to_ca"][es] = ca_try
            ca = ca_try

    if auto_translate and en is None:
        en_try = libretranslate(es, "en")
        if en_try:
            t["es_to_en"][es] = en_try
            en = en_try

    # Fallback: show ES if still missing
    ca = ca if ca else es
    en = en if en else es
    return ca, es, en

# ---------------- Allergen icons ----------------
def resolve_icon_paths(allergens: list[str]):
    paths = []
    for a in allergens:
        fn = ALLERGEN_ICON_MAP.get(a)
        if not fn:
            continue
        p = ICONS_DIR / fn
        if p.exists():
            paths.append(p)
    return paths

# ---------------- UI helpers ----------------
def set_allergens(prefix: str, value: bool):
    for k, _ in ALLERGENS:
        st.session_state[f"{prefix}_al_{k}"] = value

def allergen_selector(prefix: str) -> list[str]:
    cols = st.columns(3)
    selected = []
    for i, (k, label) in enumerate(ALLERGENS):
        if cols[i % 3].checkbox(label, key=f"{prefix}_al_{k}"):
            selected.append(k)
    return selected

def quick_buttons(prefix: str):
    c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1.2])
    if c1.button("⚡ Sin alérgenos", key=f"{prefix}_btn_none", use_container_width=True):
        set_allergens(prefix, False)
    if c2.button("🌱 Vegano", key=f"{prefix}_btn_vegan", use_container_width=True):
        st.session_state[f"{prefix}_tag"] = "vegan"
    if c3.button("🥗 Vegetariano", key=f"{prefix}_btn_veg", use_container_width=True):
        st.session_state[f"{prefix}_tag"] = "vegetarian"
    if c4.button("✖ Quitar etiqueta", key=f"{prefix}_btn_tag_clear", use_container_width=True):
        st.session_state[f"{prefix}_tag"] = "none"

# ---------------- PDF rendering ----------------
def wrap_lines(c, text, font, size, max_w):
    c.setFont(font, size)
    words = (text or "").split()
    if not words:
        return [""]
    lines = []
    line = words[0]
    for w in words[1:]:
        trial = f"{line} {w}"
        if c.stringWidth(trial, font, size) <= max_w:
            line = trial
        else:
            lines.append(line)
            line = w
    lines.append(line)
    return lines

def draw_pdf(day_line: str, date_str: str, sections: list[dict], footer_lines: list[str] | None):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # Style similar to your image
    paper = Color(0.98, 0.98, 0.965)
    title_green = Color(0.33, 0.41, 0.20)
    muted = Color(0.42, 0.42, 0.42)
    black = Color(0, 0, 0)

    # background
    c.setFillColor(paper)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # margins
    left, right, top, bottom = mm(20), mm(20), mm(18), mm(18)
    x0, x1 = left, W - right
    y = H - top

    # header (right)
    c.setFillColor(title_green)
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(x1, y, day_line)
    c.drawRightString(x1, y - mm(6), date_str)

    y -= mm(40)

    # typography
    sec_size = 10
    ca_size = 10
    sub_size = 8.6

    # icons
    icon_size = mm(4.8)
    icon_gap = mm(1.0)

    max_w = x1 - x0

    for sec in sections:
        # section title
        c.setFillColor(title_green)
        c.setFont("Helvetica-Bold", sec_size)
        c.drawString(x0, y, sec["title"])
        y -= mm(6.2)

        for item in sec["items"]:
            ca, es, en = item["ca"], item["es"], item["en"]
            allergens = item["allergens"]
            icon_paths = resolve_icon_paths(allergens)

            # CA bold + icons after last wrapped line
            c.setFillColor(black)
            ca_lines = wrap_lines(c, ca, "Helvetica-Bold", ca_size, max_w)
            c.setFont("Helvetica-Bold", ca_size)
            for li, line in enumerate(ca_lines):
                c.drawString(x0, y, line)
                if li == len(ca_lines) - 1 and icon_paths:
                    line_w = c.stringWidth(line, "Helvetica-Bold", ca_size)
                    x_icons = x0 + line_w + mm(2.0)
                    y_icons = y - mm(1.2)
                    for p in icon_paths:
                        try:
                            c.drawImage(ImageReader(str(p)), x_icons, y_icons,
                                        width=icon_size, height=icon_size, mask="auto")
                        except Exception:
                            pass
                        x_icons += icon_size + icon_gap
                y -= mm(4.2)

            # ES/EN muted italic
            c.setFillColor(muted)
            for line in wrap_lines(c, es, "Helvetica-Oblique", sub_size, max_w):
                c.setFont("Helvetica-Oblique", sub_size)
                c.drawString(x0, y, line); y -= mm(3.6)
            for line in wrap_lines(c, en, "Helvetica-Oblique", sub_size, max_w):
                c.setFont("Helvetica-Oblique", sub_size)
                c.drawString(x0, y, line); y -= mm(3.6)

            y -= mm(2.6)

            # page break
            if y < bottom + mm(30):
                c.showPage()
                c.setFillColor(paper)
                c.rect(0, 0, W, H, fill=1, stroke=0)
                y = H - top

        y -= mm(4.5)

    # footer
    if footer_lines:
        c.setFillColor(black)
        c.setFont("Helvetica-Oblique", 8.2)
        fy = bottom
        for line in footer_lines[::-1]:
            c.drawCentredString(W/2, fy, line)
            fy += mm(4.2)

    c.save()
    return buf.getvalue()

def pdf_preview(pdf_bytes: bytes):
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    uri = f"data:application/pdf;base64,{b64}"

    st.markdown("### Previsualización")
    st.components.v1.html(
        f"""
        <div style="border:1px solid #2b3240; border-radius:12px; overflow:hidden;">
          <iframe src="{uri}" width="100%" height="820" style="border:0;"></iframe>
        </div>
        """,
        height=860
    )

    st.markdown(
        f"""
        <div style="display:flex; gap:10px; margin:10px 0 0 0;">
          <a href="{uri}" target="_blank" style="text-decoration:none;">
            <button style="padding:10px 14px; border-radius:10px; border:1px solid #2b3240; background:#161a22; color:#e8e8ea; cursor:pointer;">
              🖨️ Imprimir
            </button>
          </a>
        </div>
        """,
        unsafe_allow_html=True
    )

# ---------------- Streamlit UI ----------------
st.set_page_config(page_title="Generador de menú v2", layout="centered")

st.markdown("""
<style>
  .stApp { background: #0f1117; }
  h1,h2,h3,p,label,.stMarkdown,.stCaption { color:#e8e8ea !important; }
  .block-container { max-width: 980px; padding-top: 2rem; }
  .stButton>button, .stDownloadButton>button { border-radius:10px; }
  .stTextInput>div>div>input { border-radius:10px; }
  .stDateInput>div>div input{ border-radius:10px; }
  .panel {
    background:#161a22; border:1px solid #242a35; border-radius:14px; padding:14px;
  }
</style>
""", unsafe_allow_html=True)

st.title("Generador de menú v2 (CAT / ES / EN + alérgenos)")

translations = load_translations()

# Top controls
colA, colB, colC = st.columns([1,1,1])
with colA:
    menu_date = st.date_input("Fecha del menú", value=date.today())
with colB:
    date_format = st.text_input("Formato fecha", value="%d/%m/%y")
with colC:
    auto_translate = st.toggle("Traducción automática (gratis)", value=True, help="Usa LibreTranslate si está disponible. Si falla, usa el texto en ES.")

weekday = menu_date.weekday()
day_line = f"{DIAS_CA[weekday]} / {DIAS_ES[weekday]} / {DIAS_EN[weekday]}"
try:
    date_str = menu_date.strftime(date_format)
except Exception:
    date_str = menu_date.strftime("%d/%m/%y")
    st.warning("Formato inválido. Se usa %d/%m/%y.")

st.caption(f"Cabecera: **{day_line}** — **{date_str}**")

# Export / Import translations (para no perderlo en Cloud)
with st.expander("📦 Traducciones: exportar / importar (recomendado en Streamlit Cloud)"):
    st.download_button(
        "Descargar translations.json",
        data=json.dumps(translations, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="translations.json",
        mime="application/json"
    )
    up = st.file_uploader("Subir translations.json", type=["json"])
    if up is not None:
        try:
            new_data = json.loads(up.read().decode("utf-8"))
            if isinstance(new_data, dict):
                new_data.setdefault("es_to_ca", {})
                new_data.setdefault("es_to_en", {})
                translations = new_data
                save_translations(translations)
                st.success("Traducciones importadas.")
        except Exception:
            st.error("El JSON subido no es válido.")

# Footer text like your sample
with st.expander("Opcional: texto inferior (precios, etc.)"):
    footer_1 = st.text_input("Línea 1", value="Menú 15,95€ IVA amb cafè inclòs")
    footer_2 = st.text_input("Línea 2", value="Mig menú 12,95€ IVA amb cafè inclòs")

# Icons diagnostic
with st.expander("🔍 Diagnóstico de iconos (si no salen, mira aquí)"):
    st.write(f"Buscando iconos en: `{ICONS_DIR}`")
    pngs = sorted([p.name for p in ICONS_DIR.glob("*.png")]) if ICONS_DIR.exists() else []
    st.write(f"PNG encontrados: **{len(pngs)}**")
    if pngs:
        st.code("\n".join(pngs))
    else:
        st.error("No se encontró la carpeta icons/ o no hay PNG.")

    missing = []
    for k, _ in ALLERGENS:
        fn = ALLERGEN_ICON_MAP.get(k)
        if not fn:
            missing.append(f"{k}: sin mapeo")
        else:
            if not (ICONS_DIR / fn).exists():
                missing.append(f"{k} -> {fn} (NO existe)")
    if missing:
        st.error("Faltan iconos / nombres no coinciden:")
        st.write(missing)
    else:
        st.success("✅ Todos los iconos requeridos están OK.")

    # show one sample
    sample = st.selectbox("Ver icono", options=[k for k,_ in ALLERGENS], index=0)
    fn = ALLERGEN_ICON_MAP.get(sample)
    if fn and (ICONS_DIR / fn).exists():
        st.image(str(ICONS_DIR / fn), caption=f"{sample} -> {fn}", width=90)

st.divider()

def dish_form(title: str, prefix: str):
    st.markdown(f"<div class='panel'><h3 style='margin-top:0'>{title}</h3></div>", unsafe_allow_html=True)
    es_raw = st.text_input("Nombre del plato (castellano)", key=f"{prefix}_es")

    quick_buttons(prefix)

    st.markdown("**Alérgenos:**")
    allergens = allergen_selector(prefix)

    tag = st.session_state.get(f"{prefix}_tag", "none")

    with st.expander("Traducciones (puedes ajustarlas 1 vez y se guardan)"):
        es_norm = normalize_es(es_raw)
        ca_default = translations["es_to_ca"].get(es_norm, "")
        en_default = translations["es_to_en"].get(es_norm, "")
        ca_override = st.text_input("Catalán", value=ca_default, key=f"{prefix}_ca")
        en_override = st.text_input("Inglés", value=en_default, key=f"{prefix}_en")

    return es_raw, allergens, tag, ca_override, en_override

sections = []

# 3 primeros
st.header("Primeros (3)")
first_items = []
for i in range(3):
    es_raw, allergens, tag, ca_override, en_override = dish_form(f"Primer plato {i+1}", f"first_{i}")
    if es_raw.strip():
        ca, es, en = get_translations(es_raw, translations, ca_override, en_override, auto_translate)
        ca_s, es_s, en_s = tag_to_suffix(tag)
        first_items.append({"ca": ca + ca_s, "es": es + es_s, "en": en + en_s, "allergens": allergens})

# 4 segundos
st.header("Segundos (4)")
second_items = []
for i in range(4):
    es_raw, allergens, tag, ca_override, en_override = dish_form(f"Segundo plato {i+1}", f"second_{i}")
    if es_raw.strip():
        ca, es, en = get_translations(es_raw, translations, ca_override, en_override, auto_translate)
        ca_s, es_s, en_s = tag_to_suffix(tag)
        second_items.append({"ca": ca + ca_s, "es": es + es_s, "en": en + en_s, "allergens": allergens})

# 3 postres
st.header("Postres (3) — fruta / tarta / lácteo")
dessert_types = ["Fruta", "Tarta", "Lácteo"]
dessert_items = []
for i in range(3):
    es_raw, allergens, tag, ca_override, en_override = dish_form(f"Postre {i+1} ({dessert_types[i]})", f"dessert_{i}")
    if es_raw.strip():
        ca, es, en = get_translations(es_raw, translations, ca_override, en_override, auto_translate)
        ca_s, es_s, en_s = tag_to_suffix(tag)
        dessert_items.append({"ca": ca + ca_s, "es": es + es_s, "en": en + en_s, "allergens": allergens})

sections.append({"title": "Primer Plat / Primer Plato / First Course", "items": first_items})
sections.append({"title": "Segon Plat / Segundo plato / Second Course", "items": second_items})
sections.append({"title": "Postres / Postres / Desserts", "items": dessert_items})

st.divider()

if "pdf" not in st.session_state:
    st.session_state["pdf"] = None

colX, colY = st.columns([1,1])
with colX:
    if st.button("Generar y previsualizar", use_container_width=True):
        save_translations(translations)
        footer_lines = []
        if footer_1.strip(): footer_lines.append(footer_1.strip())
        if footer_2.strip(): footer_lines.append(footer_2.strip())
        st.session_state["pdf"] = draw_pdf(day_line, date_str, sections, footer_lines or None)
with colY:
    st.download_button(
        "💾 Guardar PDF",
        data=st.session_state["pdf"] if st.session_state["pdf"] else b"",
        file_name=f"menu_{menu_date.strftime('%Y-%m-%d')}.pdf",
        mime="application/pdf",
        use_container_width=True,
        disabled=st.session_state["pdf"] is None
    )

if st.session_state["pdf"]:
    pdf_preview(st.session_state["pdf"])
else:
    st.info("Pulsa **Generar y previsualizar** para ver el menú antes de imprimir o guardar.")
