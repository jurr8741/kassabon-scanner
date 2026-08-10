import streamlit as st
from supabase import create_client, Client
import pytesseract
from PIL import Image, ImageOps, ImageEnhance
import pandas as pd
import datetime
import io
import re

# 1. Page Configuration
st.set_page_config(page_title="Kassabonnen Scanner", page_icon="🧾", layout="centered")

st.title("🧾 Kassabonnen Scanner")

# 2. Supabase Instellingen uit Secrets
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Kon niet verbinden met Supabase. Controleer de secrets in Streamlit Cloud.")

# 3. Geavanceerde Parser Functie
def parse_receipt_text(text):
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    text_lower = text.lower()
    
    winkel = ""
    totaal = 0.0
    statiegeld = 0.0
    datum = datetime.date.today()
    betaalmethode = "Pin"
    
    # 1. Winkelherkenning
    if any(k in text_lower for k in ["poiesz", "polesz", "poies", "po1esz"]):
        winkel = "Poiesz"
    elif any(k in text_lower for k in ["albert heijn", " ah ", "ah.nl", "albert"]):
        winkel = "Albert Heijn"
    elif "jumbo" in text_lower:
        winkel = "Jumbo"
    elif "lidl" in text_lower:
        winkel = "Lidl"
    elif "aldi" in text_lower:
        winkel = "Aldi"
    elif "plus" in text_lower:
        winkel = "Plus"
    elif "dirk" in text_lower:
        winkel = "Dirk"

    # 2. Datum (Ondersteunt DD-MM-YYYY, YYYY/MM/DD, DD.MM.YYYY, etc.)
    # Vangt zowel DD-MM-YYYY als YYYY-MM-DD
    datum_matches = re.findall(r'\b(\d{1,4})[-/. ](\d{1,2})[-/. ](\d{1,4})\b', text)
    for p1, p2, p3 in datum_matches:
        try:
            v1, v2, v3 = int(p1), int(p2), int(p3)
            # Scenario YYYY-MM-DD
            if v1 > 1000 and 1 <= v2 <= 12 and 1 <= v3 <= 31:
                datum = datetime.date(v1, v2, v3)
                break
            # Scenario DD-MM-YYYY of DD-MM-YY
            else:
                d, m, y = v1, v2, v3
                if y < 100:
                    y += 2000
                if 1 <= m <= 12 and 1 <= d <= 31 and 2000 <= y <= 2030:
                    datum = datetime.date(y, m, d)
                    break
        except Exception:
            continue

    # 3. Statiegeld (Zoekt specifiek op statiegeld regels)
    for line in lines:
        l_low = line.lower()
        if "stat" in l_low or "emballage" in l_low:
            match = re.search(r'(\d*[,.‚]\d{2})', l_low)
            if match:
                try:
                    raw = match.group(1).replace('‚', '.').replace(',', '.')
                    if raw.startswith('.'):
                        raw = "0" + raw
                    val = float(raw)
                    if 0.05 <= val <= 10.0:
                        statiegeld = val
                        break
                except Exception:
                    pass

    # 4. Totaalbedrag
    # Stap A: Direct zoeken naar trefwoorden t.o.v. bedragen
    for line in reversed(lines):
        l_low = line.lower()
        if "korting" in l_low or "wisselgeld" in l_low or "punten" in l_low:
            continue
        
        match = re.search(r'(?:\btotaal\b|subtotaal|\beur\b|\bpin\b)[^\d]*(\d+[.,‚]\d{2})', l_low)
        if match:
            try:
                val = float(match.group(1).replace('‚', '.').replace(',', '.'))
                if val > 0:
                    totaal = val
                    break
            except Exception:
                pass

    # Stap B: Fallback - pak het hoogste aannemelijke bedrag op de bon
    if totaal == 0.0:
        all_amounts = []
        for line in lines:
            l_low = line.lower()
            if any(x in l_low for x in ["korting", "wisselgeld", "kaart", "transactie", "terminal", "autorisatie", "kassa"]):
                continue
            matches = re.findall(r'(\d+[.,‚]\d{2})', line)
            for m in matches:
                try:
                    v = float(m.replace('‚', '.').replace(',', '.'))
                    if 0.10 <= v <= 500.0:
                        all_amounts.append(v)
                except Exception:
                    pass
        if all_amounts:
            totaal = max(all_amounts)

    # 5. Betaalmethode
    if any(k in text_lower for k in ["debit", "mastercard", "visa", "pin", "chip", "maestro", "contactloos"]):
        betaalmethode = "Pin"
    elif any(k in text_lower for k in ["contant", "cash", "wisselgeld"]):
        betaalmethode = "Contant"

    return winkel, datum, totaal, statiegeld, betaalmethode

# 4. Upload & Camera Functionaliteit (JPG, JPEG, PNG)
uploaded_file = st.file_uploader(
    "Upload of maak een foto van een kassabon", 
    type=["jpg", "jpeg", "png"]
)

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    image = ImageOps.exif_transpose(image)
    
    st.image(image, caption="Geüploade Kassabon", use_container_width=True)

    text = ""
    with st.spinner("OCR verwerken en afbeelding optimaliseren..."):
        try:
            # Afbeelding vergroten voor betere OCR van kleine letters op bonnen
            w, h = image.size
            if w < 1000:
                scale = 1000 / w
                image_resized = image.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            else:
                image_resized = image

            gray_image = image_resized.convert("L")
            enhancer = ImageEnhance.Contrast(gray_image)
            contrast_image = enhancer.enhance(1.8)
            
            # Probeer OCR met algemene PSM instelling
            text = pytesseract.image_to_string(contrast_image, lang="nld", config=r'--psm 3')
            if not text.strip():
                text = pytesseract.image_to_string(contrast_image, config=r'--psm 6')
        except Exception as ocr_err:
            st.warning(f"OCR kon de afbeelding niet volledig verwerken: {ocr_err}")

        # Automatische data-extractie
        try:
            auto_winkel, auto_datum, auto_totaal, auto_statiegeld, auto_betaalmethode = parse_receipt_text(text)
        except Exception:
            auto_winkel, auto_datum, auto_totaal, auto_statiegeld, auto_betaalmethode = "", datetime.date.today(), 0.0, 0.0, "Pin"

    st.subheader("Geëxtraheerde Tekst")
    with st.expander("Bekijk ruwe OCR-tekst"):
        st.text(text if text.strip() else "Geen tekst herkend.")

    st.subheader("Details Invoeren & Controleren")
    
    col1, col2 = st.columns(2)
    with col1:
        winkel = st.text_input("Winkelnaam", value=auto_winkel)
        datum = st.date_input("Datum bon", value=auto_datum)
        totaal_bedrag = st.number_input("Totaalbedrag (€)", value=auto_totaal, min_value=0.0, format="%.2f")
    
    with col2:
        statiegeld = st.number_input("Statiegeld (€)", value=auto_statiegeld, min_value=0.0, format="%.2f")
        
        betaal_opties = ["Pin", "Contant", "Creditcard", "Anders"]
        betaal_index = betaal_opties.index(auto_betaalmethode) if auto_betaalmethode in betaal_opties else 0
        betaalmethode = st.selectbox("Betaalmethode", betaal_opties, index=betaal_index)
        
        categorie = st.selectbox("Categorie", ["Boodschappen", "Huishouden", "Hobby / Electronica", "Overig"])

    is_self = st.checkbox("Eigen uitgave (Self)", value=True)
    retour_status = st.checkbox("Retour verwerkt", value=False)

    if st.button("💾 Opslaan in Database", type="primary"):
        with st.spinner("Opslaan in Supabase..."):
            try:
                img_bytes = io.BytesIO()
                image.convert("RGB").save(img_bytes, format="JPEG")
                img_data = img_bytes.getvalue()
                
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"bon_{timestamp}.jpg"
                
                supabase.storage.from_("bonnen-fotos").upload(
                    path=filename,
                    file=img_data,
                    file_options={"content-type": "image/jpeg"}
                )
                
                image_url = supabase.storage.from_("bonnen-fotos").get_public_url(filename)
                
                data = {
                    "datum": str(datum),
                    "winkel": winkel,
                    "totaal_bedrag": totaal_bedrag,
                    "statiegeld": statiegeld,
                    "betaalmethode": betaalmethode,
                    "categorie": categorie,
                    "is_self": is_self,
                    "retour_status": retour_status,
                    "foto_url": image_url
                }
                
                supabase.table("kassabonnen").insert(data).execute()
                st.success("✅ Kassabon succesvol opgeslagen!")
            except Exception as err:
                st.error(f"Fout bij opslaan: {err}")

st.divider()

# 5. Overzicht & Excel Export
st.subheader("📊 Inzage & Excel Export")

if st.button("Laden van opgeslagen bonnen"):
    try:
        res = supabase.table("kassabonnen").select("*").execute()
        if res.data:
            df = pd.DataFrame(res.data)
            st.dataframe(df)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Kassabonnen")
            excel_data = output.getvalue()
            
            st.download_button(
                label="📥 Download als Excel-bestand",
                data=excel_data,
                file_name=f"kassabonnen_export_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("Nog geen kassabonnen gevonden in de database.")
    except Exception as err:
        st.error(f"Fout bij ophalen van gegevens: {err}")
