import io
import json
import re
from datetime import date
from pathlib import Path

import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

MM = 72 / 25.4

def mm(x): 
    return x * MM

# -------------------- CONFIG --------------------
ICONS_DIR = Path("icons")
TRANSLATIONS_FILE = Path("translations.json")

DIAS_ES = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
DIAS_CA = ["Dilluns","Dimarts","Dimecres","Dijous","Divendres","Dissabte","Diumenge"]
DIAS_EN = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

# 14 alérgenos oficiales (claves internas)
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

# iconos (archivo por clave alergeno)
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

# -------------------- TEXT HELPERS --------------------
def normalize_dish_es(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    if s:
        s = s[0].upper() + s[1:]
    return s

def load_translations() -> dict:
    if TRANSLATIONS_FILE.exists():
        return json.loads(TRANSLATIONS_FILE.read_text(encoding="utf-8"))
    return {"es_to_ca": {}, "es_to_en": {}}

def save_translations(t: dict) -> None:
    TRANSLATIONS_FILE.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")

def get_translations(es_name: str, t: dict, ca_override: str, en_override: str):
    """Devuelve (CA, ES corregido, EN). Si hay override, lo guarda."""
    es = normalize_dish_es(es_name)

    if ca_override and ca_override.strip():
        t["es_to_ca"][es] = ca_override.strip()
    if en_override and en_override.strip():
        t["es_to_en"][es] = en_override.strip()

    ca = t["es_to_ca"].get(es, es)  # fallback: ES
    en = t["es_to_en"].get(es, es)
    return ca, es, en

# -------------------- UI HELPERS --------------------
def set_allergen_state(prefix: str, value: bool):
    for key, _label in ALLERGENS:
        st.session_state[f"{prefix}_al_{key}"] = value

def allergen_selector(prefix: str) -> list[str]:
    st.markdown("**Alérgenos**")
    cols = st.columns(3)
    selected = []
    for i, (key, label) in enumerate(ALLERGENS):
        col = cols[i % 3]
        checked = col.checkbox(label, key=f"{prefix}_al_{key}")
        if checked:
            selected.append(key)
    return selected

def quick_buttons(prefix: str):
    c1, c2, c3 = st.columns(3)

    if c1.button("⚡ Sin alérgenos", key=f"{prefix}_btn_none"):
        set_allergen_state(prefix, False)

    if c2.button("🌱 Vegano", key=f"{prefix}_btn_vegan"):
        st.session_state[f"{prefix}_tag"] = "vegan"

    if c3.button("🥗 Vegetariano", key=f"{prefix}_btn_veg"):
        st.session_state[f"{prefix}_tag"] = "vegetarian"

    # Botón extra para limpiar etiqueta
    if st.button("Quitar etiqueta vegano/vegetariano", key=f"{prefix}_btn_tag_clear"):
        st.session_state[f"{prefix}_tag"] = "none"

def tag_to_labels(tag: str):
    """Devuelve sufijos para (CA, ES, EN)."""
    if tag == "vegan":
        return (" (vegà)", " (vegano)", " (vegan)")
    if tag == "vegetarian":
        return (" (vegetari)", " (vegetariano)", " (vegetarian)")
    return ("", "", "")

# -------------------- PDF --------------------
def wrap_draw(c, text, x, y, max_w, font, size, leading):
    c.setFont(font, size)
    words = (text or "").split()
    if not words:
        return y
    line = words[0]
    for w in words[1:]:
        trial = f"{line} {w}"
        if c.stringWidth(trial, font, size) <= max_w:
            line = trial
        else:
            c.drawString(x, y, line)
            y -= leading
            line = w
    c.drawString(x, y, line)
    return y - leading

def draw_menu_pdf(menu_title_line: str, day_line: str, date_str: str, sections: list[dict]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # Ajustes visuales (para “clavar” tu imagen, aquí se afina)
    left = mm(18)
    right = mm(18)
    top = mm(16)
    bottom = mm(18)

    x0 = left
    x1 = W - right
    y = H - top

    # Header derecha
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(x1, y, menu_title_line)
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(x1, y - mm(7), day_line)
    c.setFont("Helvetica", 11)
    c.drawRightString(x1, y - mm(13), date_str)

    y -= mm(28)

    icon_size = mm(5)
    icon_gap = mm(1.2)

    for sec in sections:
        # Título sección
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x0, y, sec["title"])
        y -= mm(6)

        for item in sec["items"]:
            ca, es, en = item["ca"], item["es"], item["en"]
            allergens = item["allergens"]

            # Iconos presentes
            icon_paths = []
            for a in allergens:
                fn = ALLERGEN_ICON_MAP.get(a)
                if fn:
                    p = ICONS_DIR / fn
                    if p.exists():
                        icon_paths.append(p)

            icons_w = 0
            if icon_paths:
                icons_w = len(icon_paths) * icon_size + (len(icon_paths) - 1) * icon_gap

            text_max = (x1 - x0) - (icons_w + mm(3))
            y_start = y

            # Orden: CA / ES / EN
            y = wrap_draw(c, ca, x0, y, text_max, "Helvetica-Bold", 10, mm(4.2))
            y = wrap_draw(c, es, x0, y, text_max, "Helvetica", 9.4, mm(3.8))
            y = wrap_draw(c, en, x0, y, text_max, "Helvetica-Oblique", 9.2, mm(3.8))

            # iconos a la derecha, alineados arriba
            if icon_paths:
                x_icons = x1 - icons_w
                y_icons = y_start - mm(1.2)
                for p in icon_paths:
                    c.drawImage(ImageReader(str(p)), x_icons, y_icons, width=icon_size, height=icon_size, mask="auto")
                    x_icons += icon_size + icon_gap

            y -= mm(2.2)

            # salto de página
            if y < bottom + mm(25):
                c.showPage()
                y = H - top

        y -= mm(5)

    c.save()
    return buf.getvalue()

# -------------------- APP --------------------
st.set_page_config(page_title="Generador de Menú", layout="centered")
st.title("Generador de menú (CAT / ES / EN + alérgenos)")

translations = load_translations()

# Fecha y formato
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

st.caption(f"Se mostrará: **{day_line}** — **{date_str}**")
st.divider()

def dish_form(title: str, prefix: str):
    st.subheader(title)
    es_raw = st.text_input("Nombre del plato (castellano)", key=f"{prefix}_es")

    quick_buttons(prefix)
    allergens = allergen_selector(prefix)

    with st.expander("Ajustar traducción (opcional, solo si quieres corregir el CAT/EN una vez)"):
        ca_override = st.text_input("Catalán (override)", key=f"{prefix}_ca")
        en_override = st.text_input("Inglés (override)", key=f"{prefix}_en")

    tag = st.session_state.get(f"{prefix}_tag", "none")
    return es_raw, allergens, ca_override, en_override, tag

sections = []

# PRIMEROS (3)
st.header("Primeros (3)")
first_items = []
for i in range(3):
    es_raw, allergens, ca_override, en_override, tag = dish_form(f"Primer plato {i+1}", f"first_{i}")
    if es_raw.strip():
        ca, es, en = get_translations(es_raw, translations, ca_override, en_override)
        ca_suf, es_suf, en_suf = tag_to_labels(tag)
        first_items.append({
            "ca": ca + ca_suf,
            "es": es + es_suf,
            "en": en + en_suf,
            "allergens": allergens
        })

# SEGUNDOS (4)
st.header("Segundos (4)")
second_items = []
for i in range(4):
    es_raw, allergens, ca_override, en_override, tag = dish_form(f"Segundo plato {i+1}", f"second_{i}")
    if es_raw.strip():
        ca, es, en = get_translations(es_raw, translations, ca_override, en_override)
        ca_suf, es_suf, en_suf = tag_to_labels(tag)
        second_items.append({
            "ca": ca + ca_suf,
            "es": es + es_suf,
            "en": en + en_suf,
            "allergens": allergens
        })

# POSTRES (3)
st.header("Postres (3) — fruta / tarta / lácteo")
dessert_types = ["Fruta", "Tarta", "Lácteo"]
dessert_items = []
for i in range(3):
    es_raw, allergens, ca_override, en_override, tag = dish_form(f"Postre {i+1} ({dessert_types[i]})", f"dessert_{i}")
    if es_raw.strip():
        ca, es, en = get_translations(es_raw, translations, ca_override, en_override)
        ca_suf, es_suf, en_suf = tag_to_labels(tag)
        dessert_items.append({
            "ca": ca + ca_suf,
            "es": es + es_suf,
            "en": en + en_suf,
            "allergens": allergens
        })

sections.append({"title": "Primer Plat / Primer Plato / First Course", "items": first_items})
sections.append({"title": "Segon Plat / Segundo plato / Second Course", "items": second_items})
sections.append({"title": "Postres / Postres / Desserts", "items": dessert_items})

st.divider()

if st.button("Generar PDF"):
    # Guarda el diccionario de traducciones (para reutilizar en el futuro)
    save_translations(translations)

    pdf = draw_menu_pdf(
        menu_title_line="MENÚ",
        day_line=day_line,
        date_str=date_str,
        sections=sections
    )
    filename = f"menu_{menu_date.strftime('%Y-%m-%d')}.pdf"
    st.success("PDF generado.")
    st.download_button("Descargar PDF", data=pdf, file_name=filename, mime="application/pdf")
