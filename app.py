import io
import json
import re
import base64
from datetime import date
from pathlib import Path

import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import Color


MM = 72 / 25.4
def mm(x): return x * MM

APP_DIR = Path(__file__).resolve().parent
ICONS_DIR = APP_DIR / "icons"
TRANSLATIONS_FILE = APP_DIR / "translations.json"

DIAS_ES = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
DIAS_CA = ["Dilluns","Dimarts","Dimecres","Dijous","Divendres","Dissabte","Diumenge"]
DIAS_EN = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

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

# IMPORTANTE: estos nombres deben coincidir con tus PNG dentro de /icons
ALLERGEN_ICON_MAP = {
    "gluten": "gluten.png",
    "crustaceos": "crustaceos.png",
    "huevo": "huevo.png",
    "pescado": "pescado.png",
    "cacahuetes": "cacahuetes.png",
    "soja": "soja.png",
    "lacteos": "lacteos.png",
    "frutos_secos": "frutos_secos.png",
    "apio": "apio.png",
    "mostaza": "mostaza.png",
    "sesamo": "sesamo.png",
    "sulfitos": "sulfitos.png",
    "altramuces": "altramuces.png",
    "moluscos": "moluscos.png",
}


# -------------------- translations (robusto) --------------------
def load_translations() -> dict:
    default = {"es_to_ca": {}, "es_to_en": {}}
    if not TRANSLATIONS_FILE.exists():
        try:
            TRANSLATIONS_FILE.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
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
    # Nota: en Streamlit Cloud puede no persistir tras reinicio.
    try:
        TRANSLATIONS_FILE.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def normalize_es(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    if s:
        s = s[0].upper() + s[1:]
    return s


def get_translations(es_raw: str, t: dict, ca_override: str, en_override: str):
    es = normalize_es(es_raw)

    # Si el usuario escribe traducción, guardarla
    if ca_override.strip():
        t["es_to_ca"][es] = ca_override.strip()
    if en_override.strip():
        t["es_to_en"][es] = en_override.strip()

    # Si aún no hay traducción guardada: por defecto usar ES (para que no salga vacío)
    ca = t["es_to_ca"].get(es, es)
    en = t["es_to_en"].get(es, es)
    return ca, es, en


def tag_to_suffix(tag: str):
    if tag == "vegan":
        return (" (vegà)", " (vegano)", " (vegan)")
    if tag == "vegetarian":
        return (" (vegetari)", " (vegetariano)", " (vegetarian)")
    return ("", "", "")


# -------------------- UI helpers --------------------
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


# -------------------- PDF rendering --------------------
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


def draw_pdf(day_line: str, date_str: str, sections: list[dict], footer_lines: list[str] | None):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # Estilo como tu imagen (papel + verde)
    paper = Color(0.98, 0.98, 0.965)
    title_green = Color(0.33, 0.41, 0.20)
    muted = Color(0.42, 0.42, 0.42)

    c.setFillColor(paper)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    left = mm(20); right = mm(20); top = mm(18); bottom = mm(18)
    x0 = left; x1 = W - right
    y = H - top

    # Header derecha
    c.setFillColor(title_green)
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(x1, y, day_line)
    c.drawRightString(x1, y - mm(6), date_str)
    y -= mm(40)

    icon_size = mm(4.8)
    icon_gap = mm(1.0)

    for sec in sections:
        # Título sección
        c.setFillColor(title_green)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x0, y, sec["title"])
        y -= mm(6.2)

        for item in sec["items"]:
            ca = item["ca"]; es = item["es"]; en = item["en"]
            allergens = item["allergens"]

            icon_paths = resolve_icon_paths(allergens)

            # Catalán (negrita) + iconos al final de la última línea
            c.setFillColor(Color(0,0,0))
            ca_lines = wrap_lines(c, ca, "Helvetica-Bold", 10, x1 - x0)
            c.setFont("Helvetica-Bold", 10)
            for li, line in enumerate(ca_lines):
                c.drawString(x0, y, line)
                if li == len(ca_lines) - 1 and icon_paths:
                    line_w = c.stringWidth(line, "Helvetica-Bold", 10)
                    x_icons = x0 + line_w + mm(2.0)
                    y_icons = y - mm(1.2)
                    for p in icon_paths:
                        try:
                            c.drawImage(ImageReader(str(p)), x_icons, y_icons,
                                        width=icon_size, height=icon_size, mask="auto")
                        except Exception:
                            # Si un icono no es PNG/JPG válido, no romper el PDF
                            pass
                        x_icons += icon_size + icon_gap
                y -= mm(4.2)

            # ES y EN en gris itálica
            c.setFillColor(muted)
            for line in wrap_lines(c, es, "Helvetica-Oblique", 8.7, x1 - x0):
                c.setFont("Helvetica-Oblique", 8.7)
                c.drawString(x0, y, line); y -= mm(3.6)
            for line in wrap_lines(c, en, "Helvetica-Oblique", 8.7, x1 - x0):
                c.setFont("Helvetica-Oblique", 8.7)
                c.drawString(x0, y, line); y -= mm(3.6)

            y -= mm(2.5)

            if y < bottom + mm(30):
                c.showPage()
                c.setFillColor(paper)
                c.rect(0, 0, W, H, fill=1, stroke=0)
                y = H - top

        y -= mm(4.5)

    # Footer
    if footer_lines:
        c.setFillColor(Color(0,0,0))
        c.setFont("Helvetica-Oblique", 8.2)
        fy = bottom
        for line in footer_lines[::-1]:
            c.drawCentredString(W/2, fy, line)
            fy += mm(4.2)

    c.save()
    return buf.getvalue()


def pdf_preview_block(pdf_bytes: bytes):
    """Muestra preview embebida + botón imprimir (sin instalar nada)."""
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    pdf_data_uri = f"data:application/pdf;base64,{b64}"

    # Preview (iframe)
    st.markdown("### Previsualización")
    st.components.v1.html(
        f"""
        <div style="border:1px solid #2b3240; border-radius:12px; overflow:hidden;">
          <iframe src="{pdf_data_uri}" width="100%" height="820" style="border:0;"></iframe>
        </div>
        """,
        height=860,
    )

    # Imprimir (abre en nueva pestaña y dispara print)
    st.markdown(
        f"""
        <div style="display:flex; gap:10px; margin-top:10px;">
          <a href="{pdf_data_uri}" target="_blank" style="text-decoration:none;">
            <button style="padding:10px 14px; border-radius:10px; border:1px solid #2b3240; background:#161a22; color:#e8e8ea; cursor:pointer;">
              🖨️ Imprimir
            </button>
          </a>
        </div>
        """,
        unsafe_allow_html=True
    )


# -------------------- STREAMLIT UI --------------------
st.set_page_config(page_title="Generador de menú", layout="centered")

st.markdown(
    """
    <style>
      .stApp { background: #0f1117; }
      h1, h2, h3, p, label, .stMarkdown, .stCaption { color: #e8e8ea !important; }
      .block-container { max-width: 900px; padding-top: 2rem; }
      .stButton>button, .stDownloadButton>button { border-radius: 10px; }
      .stTextInput>div>div>input { border-radius: 10px; }
      .stDateInput>div>div input{ border-radius: 10px; }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("Generador de menú (CAT / ES / EN + alérgenos)")

translations = load_translations()

# -------- Diagnóstico de iconos (para que no adivines) --------
with st.expander("🔍 Diagnóstico de iconos (muy importante si no se ven)"):
    st.write(f"Ruta icons/: `{ICONS_DIR}`")
    found = sorted([p.name for p in ICONS_DIR.glob("*.png")]) if ICONS_DIR.exists() else []
    st.write(f"PNG encontrados: **{len(found)}**")
    if found:
        st.code("\n".join(found))
    else:
        st.error("No hay PNG en /icons o la carpeta no existe en el repo.")

    missing = []
    for k, _ in ALLERGENS:
        fn = ALLERGEN_ICON_MAP.get(k)
        if not fn:
            missing.append(f"{k}: (sin asignar)")
        else:
            if not (ICONS_DIR / fn).exists():
                missing.append(f"{k} -> {fn} (NO existe)")
    if missing:
        st.error("Faltan iconos o nombres no coinciden:")
        st.write(missing)
    else:
        st.success("✅ Todos los iconos necesarios existen y coinciden con el mapa.")

    # Preview de un icono
    sample_key = st.selectbox("Ver un icono de ejemplo", options=[k for k,_ in ALLERGENS], index=0)
    sample_fn = ALLERGEN_ICON_MAP.get(sample_key)
    sample_path = ICONS_DIR / sample_fn if sample_fn else None
    if sample_path and sample_path.exists():
        st.image(str(sample_path), caption=f"{sample_key} -> {sample_fn}", width=80)
    else:
        st.warning("No se puede mostrar el icono: no existe o no está bien mapeado.")

st.divider()

# Fecha + formato
col1, col2 = st.columns(2)
with col1:
    menu_date = st.date_input("¿Para qué fecha es el menú?", value=date.today())
with col2:
    date_format = st.text_input("Formato de fecha", value="%d/%m/%y")

weekday = menu_date.weekday()
day_line = f"{DIAS_CA[weekday]} / {DIAS_ES[weekday]} / {DIAS_EN[weekday]}"
try:
    date_str = menu_date.strftime(date_format)
except Exception:
    date_str = menu_date.strftime("%d/%m/%y")
    st.warning("Formato de fecha inválido. Se usará %d/%m/%y.")

st.caption(f"Cabecera: **{day_line}** — **{date_str}**")

# Footer opcional
with st.expander("Opcional: texto inferior (precios, etc.)"):
    footer_1 = st.text_input("Línea 1", value="Menú 15,95€ IVA amb cafè inclòs")
    footer_2 = st.text_input("Línea 2", value="Mig menú 12,95€ IVA amb cafè inclòs")

st.divider()

def dish_form(title: str, prefix: str):
    st.subheader(title)
    es_raw = st.text_input("Nombre del plato (castellano)", key=f"{prefix}_es")

    quick_buttons(prefix)
    st.markdown("**Alérgenos (marca los que correspondan):**")
    allergens = allergen_selector(prefix)

    # Aquí está la clave: si no hay traducción, verás ES por defecto,
    # pero puedes corregir una vez y queda guardado en translations.json.
    with st.expander("Traducción (recomendado: corrígela 1 vez y se recuerda)"):
        es_norm = normalize_es(es_raw)
        ca_suggest = translations["es_to_ca"].get(es_norm, es_norm)
        en_suggest = translations["es_to_en"].get(es_norm, es_norm)
        ca_override = st.text_input("Catalán", value=ca_suggest if es_raw.strip() else "", key=f"{prefix}_ca")
        en_override = st.text_input("Inglés", value=en_suggest if es_raw.strip() else "", key=f"{prefix}_en")

    tag = st.session_state.get(f"{prefix}_tag", "none")
    return es_raw, allergens, ca_override, en_override, tag

sections = []

# 3 primeros
st.header("Primeros (3)")
first_items = []
for i in range(3):
    es_raw, allergens, ca_override, en_override, tag = dish_form(f"Primer plato {i+1}", f"first_{i}")
    if es_raw.strip():
        ca, es, en = get_translations(es_raw, translations, ca_override, en_override)
        ca_s, es_s, en_s = tag_to_suffix(tag)
        first_items.append({"ca": ca + ca_s, "es": es + es_s, "en": en + en_s, "allergens": allergens})

# 4 segundos
st.header("Segundos (4)")
second_items = []
for i in range(4):
    es_raw, allergens, ca_override, en_override, tag = dish_form(f"Segundo plato {i+1}", f"second_{i}")
    if es_raw.strip():
        ca, es, en = get_translations(es_raw, translations, ca_override, en_override)
        ca_s, es_s, en_s = tag_to_suffix(tag)
        second_items.append({"ca": ca + ca_s, "es": es + es_s, "en": en + en_s, "allergens": allergens})

# 3 postres
st.header("Postres (3) — fruta / tarta / lácteo")
dessert_types = ["Fruta", "Tarta", "Lácteo"]
dessert_items = []
for i in range(3):
    es_raw, allergens, ca_override, en_override, tag = dish_form(f"Postre {i+1} ({dessert_types[i]})", f"dessert_{i}")
    if es_raw.strip():
        ca, es, en = get_translations(es_raw, translations, ca_override, en_override)
        ca_s, es_s, en_s = tag_to_suffix(tag)
        dessert_items.append({"ca": ca + ca_s, "es": es + es_s, "en": en + en_s, "allergens": allergens})

sections.append({"title": "Primer Plat / Primer Plato / First Course", "items": first_items})
sections.append({"title": "Segon Plat / Segundo plato / Second Course", "items": second_items})
sections.append({"title": "Postres / Postres / Desserts", "items": dessert_items})

st.divider()

# Generar y previsualizar
if "last_pdf" not in st.session_state:
    st.session_state["last_pdf"] = None

if st.button("Generar y previsualizar", use_container_width=True):
    save_translations(translations)

    footer_lines = []
    if footer_1.strip(): footer_lines.append(footer_1.strip())
    if footer_2.strip(): footer_lines.append(footer_2.strip())

    pdf_bytes = draw_pdf(day_line, date_str, sections, footer_lines or None)
    st.session_state["last_pdf"] = pdf_bytes

pdf_bytes = st.session_state.get("last_pdf")
if pdf_bytes:
    # Preview + Print
    pdf_preview_block(pdf_bytes)

    # Guardar
    st.download_button(
        "💾 Guardar PDF",
        data=pdf_bytes,
        file_name=f"menu_{menu_date.strftime('%Y-%m-%d')}.pdf",
        mime="application/pdf",
        use_container_width=True
    )
else:
    st.info("Pulsa **Generar y previsualizar** para ver el menú antes de guardarlo o imprimirlo.")
