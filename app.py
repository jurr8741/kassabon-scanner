import io
import re
from datetime import datetime
import pandas as pd
from PIL import Image
import pytesseract
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Kassabon Scanner Sync", page_icon="🧾", layout="centered")

# --- SUPABASE VERBINDING INITIALISEREN ---
@st.cache_resource
def init_supabase():
    # Haalt de credentials op uit Streamlit secrets
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase = init_supabase()
except Exception:
    st.error("🔑 Supabase API keys ontbreken in Streamlit secrets!")
    st.stop()


# --- HELPER FUNCTIES VOOR OCR & PARSING ---
def parse_receipt_text(text):
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    winkel = lines[0] if lines else "Onbekend"

    date_match = re.search(r"\b(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})\b", text)
    datum = date_match.group(1) if date_match else datetime.now().strftime("%Y-%m-%d")

    totaal = 0.0
    totaal_match = re.search(
        r"(?:totaal|totaalbedrag|eur|€)\s*[:=]?\s*(\d+[,\.]\d{2})",
        text,
        re.IGNORECASE,
    )
    if totaal_match:
        try:
            totaal = float(totaal_match.group(1).replace(",", "."))
        except ValueError:
            totaal = 0.0

    statiegeld = 0.0
    statie_match = re.search(
        r"(?:statiegeld|statie)\s*[:=]?\s*(\d+[,\.]\d{2})", text, re.IGNORECASE
    )
    if statie_match:
        try:
            statiegeld = float(statie_match.group(1).replace(",", "."))
        except ValueError:
            statiegeld = 0.0

    betaalwijze = "PIN"
    if re.search(r"\b(contant|cash|kas)\b", text, re.IGNORECASE):
        betaalwijze = "Contant"

    return {
        "winkel": winkel,
        "datum": datum,
        "totaal": totaal,
        "statiegeld": statiegeld,
        "betaalwijze": betaalwijze,
    }


def upload_foto_naar_supabase(image_bytes, filename):
    """Uploadt de foto naar Supabase Storage en geeft de publieke URL terug."""
    bucket_name = "bonnen-fotos"
    supabase.storage.from_(bucket_name).upload(
        file=image_bytes,
        path=filename,
        file_options={"content-type": "image/jpeg"},
    )
    return supabase.storage.from_(bucket_name).get_public_url(filename)


# --- HOOFDAPP ---
st.title("🧾 Kassabon Scanner (Gezamenlijk)")

st.subheader("1. Bon Scannen")
input_method = st.radio("Kies invoermethode:", ["Camera", "Afbeelding Uploaden"], horizontal=True)

image_file = None
if input_method == "Camera":
    image_file = st.camera_input("Maak een foto van de bon")
else:
    image_file = st.file_uploader("Upload een kassabon", type=["png", "jpg", "jpeg"])

if image_file:
    image = Image.open(image_file)

    # Converteer afbeelding naar bytes voor upload
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG")
    image_bytes = buffer.getvalue()

    with st.spinner("Bon analyseren..."):
        raw_text = pytesseract.image_to_string(image, lang="eng+nld")
        extracted_data = parse_receipt_text(raw_text)

    st.success("Bon gescand! Controleer en vul de gegevens aan.")

    st.subheader("2. Gegevens Aanvullen")
    with st.form(key="receipt_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            winkel = st.text_input("Winkel", value=extracted_data["winkel"])
            datum = st.text_input("Datum", value=extracted_data["datum"])
            totaalprijs = st.number_input(
                "Totaalprijs (€)",
                value=float(extracted_data["totaal"]),
                step=0.01,
                format="%.2f",
            )
            statiegeld = st.number_input(
                "Statiegeld (€)",
                value=float(extracted_data["statiegeld"]),
                step=0.01,
                format="%.2f",
            )

        with col2:
            betaalwijze = st.selectbox(
                "Betaalwijze",
                ["PIN", "Contant"],
                index=0 if extracted_data["betaalwijze"] == "PIN" else 1,
            )
            zelf = st.radio("Zelf?", ["Ja", "Nee"], index=0, horizontal=True)
            retour = st.radio("Retour?", ["Nee", "Ja"], index=0, horizontal=True)
            terug_bedrag = st.number_input(
                "Terug bedrag (€)", value=0.0, step=0.01, format="%.2f"
            )

        categorie = st.selectbox(
            "Categorie",
            [
                "Boodschappen",
                "Huishouden",
                "Elektronica",
                "Kleding",
                "Horeca / Cafetaria",
                "Gereedschap / Klussen",
                "Overig",
            ],
        )

        submit_button = st.form_submit_button(label="💾 Opslaan in Cloud")

        if submit_button:
            with st.spinner("Sla bon en foto op..."):
                # Foto uploaden naar cloud storage
                file_name = f"bon_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                foto_url = upload_foto_naar_supabase(image_bytes, file_name)

                # Gegevens opslaan in database
                nieuwe_bon = {
                    "datum": datum,
                    "winkel": winkel,
                    "totaalprijs": totaalprijs,
                    "statiegeld": statiegeld,
                    "betaalwijze": betaalwijze,
                    "zelf": zelf,
                    "retour": retour,
                    "terug_bedrag": terug_bedrag,
                    "categorie": categorie,
                    "afbeelding_url": foto_url,
                }
                supabase.table("kassabonnen").insert(nieuwe_bon).execute()

            st.success("Bon opgeslagen! Zichtbaar op al je apparaten.")
            st.rerun()

# --- OVERZICHT APPARATEN & EXPORT SECTIE ---
st.divider()
st.subheader("3. Alle Gescande Bonnen")

# Data live ophalen uit Supabase
response = supabase.table("kassabonnen").select("*").order("created_at", desc=True).execute()
bonnen_data = response.data

if bonnen_data:
    df = pd.DataFrame(bonnen_data)

    # Tabel opschonen voor weergave
    display_df = df[
        [
            "datum",
            "winkel",
            "totaalprijs",
            "statiegeld",
            "betaalwijze",
            "zelf",
            "retour",
            "terug_bedrag",
            "categorie",
            "afbeelding_url",
        ]
    ].copy()

    st.dataframe(
        display_df,
        use_container_width=True,
        column_config={
            "afbeelding_url": st.column_config.LinkColumn("Foto Link", display_text="Bekijk Bon")
        },
    )

    # Excel export van alle live bonnen
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        display_df.to_excel(writer, index=False, sheet_name="Kassabonnen")
    excel_data = output.getvalue()

    st.download_button(
        label="📊 Exporteer Alle Bonnen naar Excel",
        data=excel_data,
        file_name=f"alle_kassabonnen_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # Mogelijke galerij om bonnen direct te bekijken
    with st.expander("📷 Bekijk gescande foto's"):
        cols = st.columns(3)
        for idx, item in enumerate(bonnen_data):
            with cols[idx % 3]:
                st.image(item["afbeelding_url"], caption=f"{item['winkel']} (€{item['totaalprijs']})")
else:
    st.info("Nog geen bonnen in de cloud opgeslagen.")
