import io
import json
import re
from datetime import date
from pathlib import Path

import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import Color

MM = 72 / 25.4
def mm(x):  # mm -> points
    return x * MM


# -------------------- PATHS (robustos en Cloud) --------------------
APP_DIR = Path(__file__).resolve().parent
ICONS_DIR = APP_DIR / "icons"
TRANSLATIONS_FILE = APP_DIR / "translations.json"


# -------------------- DATE TEXT --------------------
DIAS_ES = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
DIAS_CA = ["Dilluns","Dimarts","Dimecres","Dijous","Divendres","Dissabte","Diumenge"]
DIAS_EN = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]


# -------------------- ALLERGENS (14 oficiales) --------------------
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

# Ajusta aquí si tus iconos tienen otros nombres
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


# -------------------- TRANSLATIONS (robusto) --------------------
def load_translations() -> dict:
    default = {"es_to_ca": {}, "es_to_en": {}}

    if not TRANSLATIONS_FILE.exists():
        # crear uno válido para evitar JSONDecodeError
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
        if "es_to_ca" not in data or "es_to_en" not in data:
            return default
        if not isinstance(data["es_to_ca"], dict) or not isinstance(data["es_to_en"], dict):
            return default
        return data
    except Exception:
        return default


def save_translations(t: dict) -> None:
    # Nota: en Streamlit Cloud, escribir archivos puede no persistir tras reinicios.
    try:
        TRANSLATIONS_FILE.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# -------------------- TEXT HELPERS --------------------
def normalize_dish_es(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    if s:
        s = s[0].upper() + s[1:]
    return s


def get_translations(es_name: str, t: dict, ca_override: str, en_override: str):
    """
    Devuelve (CA, ES corregido, EN).
    Si el usuario pone overrides, se guardan.
    """
    es = normalize_dish_es(es_name)

    if ca_override and ca_override.strip():
        t["es_to_ca"][es] = ca_override.strip()
    if en_override and en_override.strip():
        t["es_to_en"][es] = en_override.strip()

    ca = t["es_to_ca"].get(es, es)  # fallback: ES
    en = t["es_to_en"].get(es, es)
    return ca, es, en


def tag_to_labels(tag: str):
    if tag == "vegan":
        return (" (vegà)", " (vegano)", " (vegan)")
    if tag == "vegetarian":
        return (" (vegetari)", " (vegetariano)", " (vegetarian)")
    return ("", "", "")


# -------------------- UI HELPERS (alérgenos + botones rápidos) --------------------
def set_allergen_state(prefix: str, value: bool):
    for key, _label in ALLERGENS:
        st.session_state[f"{prefix}_al_{key}"] = value


def allergen_selector(prefix: str) -> list[str]:
    # Grid 3 columnas, como checklist
    cols = st.columns(3)
    selected = []
    for i, (key, label) in enumerate(ALLERGENS):
        col = cols[i % 3]
        checked = col.checkbox(label, key=f"{prefix}_al_{key}")
        if checked:
            selected.append(key)
    return selected


def quick_buttons(prefix: str):
    c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1.2])

    if c1.button("⚡ Sin alérgenos", key=f"{prefix}_btn_none", use_container_width=True):
        set_allergen_state(prefix, False)

    if c2.button("🌱 Vegano", key=f"{prefix}_btn_vegan", use_container_width=True):
        st.session_state[f"{prefix}_tag"] = "vegan"

    if c3.button("🥗 Vegetariano", key=f"{prefix}_btn_veg", use_container_width=True):
        st.session_state[f"{prefix}_tag"] = "vegetarian"

    if c4.button("✖ Quitar etiqueta", key=f"{prefix}_btn_tag_clear", use_container_width=True):
        st.session_state[f"{prefix}_tag"] = "none"


# -------------------- PDF RENDER (estilo similar a tu imagen) --------------------
def wrap_lines_for_width(c, text, font_name, font_size, max_width):
    """Devuelve lista de líneas ajustadas a max_width."""
    c.setFont(font_name, font_size)
    words = (text or "").split()
    if not words:
        return [""]
    lines = []
    line = words[0]
    for w in words[1:]:
        trial = f"{line} {w}"
        if c.stringWidth(trial, font_name, font_size) <= max_width:
            line = trial
        else:
            lines.append(line)
            line = w
    lines.append(line)
    return lines


def draw_menu_pdf(
    header_day_line: str,
    header_date_str: str,
    sections: list[dict],
    footer_lines: list[str] | None = None,
) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # Colores estilo “carta”
    title_green = Color(0.33, 0.41, 0.20)  # verde oliva parecido
    muted_gray = Color(0.40, 0.40, 0.40)
    text_black = Color(0, 0, 0)
    paper = Color(0.98, 0.98, 0.965)

    # Fondo “papel”
    c.setFillColor(paper)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # Márgenes
    left = mm(20)
    right = mm(20)
    top = mm(18)
    bottom = mm(18)

    x0 = left
    x1 = W - right
    y = H - top

    # Cabecera arriba derecha (como tu imagen)
    c.setFillColor(title_green)
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(x1, y, header_day_line)
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(x1, y - mm(6), header_date_str)

    # Bajar a contenido
    y -= mm(40)

    # Tamaños tipográficos (muy similares a la estética que enseñaste)
    sec_size = 10
    ca_size = 10
    sub_size = 8.6

    # Iconos
    icon_size = mm(4.6)
    icon_gap = mm(1.0)

    # Ancho máximo del texto (deja margen para que no se pegue al borde)
    content_max_w = x1 - x0

    for sec in sections:
        # Título sección verde
        c.setFillColor(title_green)
        c.setFont("Helvetica-Bold", sec_size)
        c.drawString(x0, y, sec["title"])
        y -= mm(6.2)

        for item in sec["items"]:
            ca = item["ca"]
            es = item["es"]
            en = item["en"]
            allergens = item["allergens"]

            # Resolve icon paths
            icon_paths = []
            for a in allergens:
                fn = ALLERGEN_ICON_MAP.get(a)
                if fn:
                    p = ICONS_DIR / fn
                    if p.exists():
                        icon_paths.append(p)

            # --- Catalán (negrita) + iconos justo después, en la ÚLTIMA línea ---
            c.setFillColor(text_black)
            ca_lines = wrap_lines_for_width(c, ca, "Helvetica-Bold", ca_size, content_max_w)

            c.setFont("Helvetica-Bold", ca_size)
            for li, line in enumerate(ca_lines):
                c.drawString(x0, y, line)
                # En la última línea, poner iconos a continuación
                if li == len(ca_lines) - 1 and icon_paths:
                    line_w = c.stringWidth(line, "Helvetica-Bold", ca_size)
                    x_icons = x0 + line_w + mm(2.0)
                    y_icons = y - mm(1.1)
                    for p in icon_paths:
                        try:
                            c.drawImage(ImageReader(str(p)), x_icons, y_icons,
                                        width=icon_size, height=icon_size, mask="auto")
                        except Exception:
                            pass
                        x_icons += icon_size + icon_gap
                y -= mm(4.2)

            # --- Castellano (gris, itálica, pequeño) ---
            c.setFillColor(muted_gray)
            es_lines = wrap_lines_for_width(c, es, "Helvetica-Oblique", sub_size, content_max_w)
            c.setFont("Helvetica-Oblique", sub_size)
            for line in es_lines:
                c.drawString(x0, y, line)
                y -= mm(3.6)

            # --- Inglés (gris, itálica, pequeño) ---
            en_lines = wrap_lines_for_width(c, en, "Helvetica-Oblique", sub_size, content_max_w)
            c.setFont("Helvetica-Oblique", sub_size)
            for line in en_lines:
                c.drawString(x0, y, line)
                y -= mm(3.6)

            # Espacio entre platos
            y -= mm(2.3)

            # Salto de página
            if y < bottom + mm(30):
                c.showPage()
                # fondo en página nueva
                c.setFillColor(paper)
                c.rect(0, 0, W, H, fill=1, stroke=0)
                y = H - top

        # Espacio entre secciones
        y -= mm(4.5)

    # Footer (opcional)
    if footer_lines:
        c.setFillColor(text_black)
        c.setFont("Helvetica-Oblique", 8.2)
        fy = bottom
        for line in footer_lines[::-1]:
            c.drawCentredString(W / 2, fy, line)
            fy += mm(4.3)

    c.save()
    return buf.getvalue()


# -------------------- STREAMLIT UI --------------------
st.set_page_config(page_title="Generador de menú", layout="centered")

# Estilo para que la web no sea “plana”
st.markdown(
    """
    <style>
      .stApp { background: #0f1117; }
      h1, h2, h3, p, label, .stMarkdown, .stCaption { color: #e8e8ea !important; }
      .block-container { max-width: 860px; padding-top: 2rem; }
      div[data-testid="stVerticalBlockBorderWrapper"]{
        background: #161a22; border: 1px solid #242a35; border-radius: 14px;
        padding: 18px 18px 8px 18px;
      }
      .stButton>button{ border-radius: 10px; }
      .stDownloadButton>button{ border-radius: 10px; }
      .stTextInput>div>div>input{ border-radius: 10px; }
      .stDateInput>div>div input{ border-radius: 10px; }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("Generador de menú (CAT / ES / EN + alérgenos)")

translations = load_translations()

# Fecha y formato
col1, col2 = st.columns(2)
with col1:
    menu_date = st.date_input("¿Para qué fecha es el menú?", value=date.today())
with col2:
    date_format = st.text_input("Formato de fecha", value="%d/%m/%y", help="Ejemplo: %d/%m/%y → 04/03/26")

weekday = menu_date.weekday()
header_day_line = f"{DIAS_CA[weekday]} / {DIAS_ES[weekday]} / {DIAS_EN[weekday]}"
try:
    header_date_str = menu_date.strftime(date_format)
except Exception:
    header_date_str = menu_date.strftime("%d/%m/%y")
    st.warning("Formato de fecha inválido. Se usará %d/%m/%y.")

st.caption(f"Cabecera: **{header_day_line}** — **{header_date_str}**")

# Footer opcional como tu ejemplo
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

    with st.expander("Ajustar traducción (opcional: si quieres dejarlo perfecto una vez y que lo recuerde)"):
        ca_override = st.text_input("Catalán", key=f"{prefix}_ca")
        en_override = st.text_input("Inglés", key=f"{prefix}_en")

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
        ca_suf, es_suf, en_suf = tag_to_labels(tag)
        first_items.append({"ca": ca + ca_suf, "es": es + es_suf, "en": en + en_suf, "allergens": allergens})

# 4 segundos
st.header("Segundos (4)")
second_items = []
for i in range(4):
    es_raw, allergens, ca_override, en_override, tag = dish_form(f"Segundo plato {i+1}", f"second_{i}")
    if es_raw.strip():
        ca, es, en = get_translations(es_raw, translations, ca_override, en_override)
        ca_suf, es_suf, en_suf = tag_to_labels(tag)
        second_items.append({"ca": ca + ca_suf, "es": es + es_suf, "en": en + en_suf, "allergens": allergens})

# 3 postres
st.header("Postres (3) — fruta / tarta / lácteo")
dessert_types = ["Fruta", "Tarta", "Lácteo"]
dessert_items = []
for i in range(3):
    es_raw, allergens, ca_override, en_override, tag = dish_form(f"Postre {i+1} ({dessert_types[i]})", f"dessert_{i}")
    if es_raw.strip():
        ca, es, en = get_translations(es_raw, translations, ca_override, en_override)
        ca_suf, es_suf, en_suf = tag_to_labels(tag)
        dessert_items.append({"ca": ca + ca_suf, "es": es + es_suf, "en": en + en_suf, "allergens": allergens})

sections.append({"title": "Primer Plat / Primer Plato / First Course", "items": first_items})
sections.append({"title": "Segon Plat / Segundo plato / Second Course", "items": second_items})
sections.append({"title": "Postres / Postres / Desserts", "items": dessert_items})

st.divider()

# Diagnóstico rápido de iconos (muy útil)
with st.expander("Diagnóstico: iconos encontrados"):
    missing = []
    for k, _ in ALLERGENS:
        fn = ALLERGEN_ICON_MAP.get(k)
        if not fn or not (ICONS_DIR / fn).exists():
            missing.append(f"{k} -> {fn}")
    if missing:
        st.error("Faltan iconos o nombres no coinciden. Revisa la carpeta icons/ y los nombres:")
        st.write(missing)
    else:
        st.success("✅ Todos los iconos existen y coinciden con el mapa.")

if st.button("Generar PDF", use_container_width=True):
    save_translations(translations)

    footer_lines = []
    if footer_1.strip():
        footer_lines.append(footer_1.strip())
    if footer_2.strip():
        footer_lines.append(footer_2.strip())

    pdf_bytes = draw_menu_pdf(
        header_day_line=header_day_line,
        header_date_str=header_date_str,
        sections=sections,
        footer_lines=footer_lines or None,
    )

    filename = f"menu_{menu_date.strftime('%Y-%m-%d')}.pdf"
    st.success("PDF generado.")
    st.download_button("Descargar PDF", data=pdf_bytes, file_name=filename, mime="application/pdf", use_container_width=True)
