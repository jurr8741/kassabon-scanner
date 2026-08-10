import streamlit as st
from supabase import create_client, Client
import pytesseract
from PIL import Image, ImageOps, ImageEnhance
import pandas as pd
import datetime
import io
import re
import numpy as np

try:
    from pyzbar.pyzbar import decode as decode_barcodes
except ImportError:
    decode_barcodes = None

# 1. Page Configuration
st.set_page_config(page_title="Kassabonnen Scanner", page_icon="🧾", layout="centered")

st.title("🧾 Kassabonnen Scanner")

# Initialize Session State for Barcode Data
if "found_barcodes" not in st.session_state:
    st.session_state["found_barcodes"] = ""

# 2. Supabase Instellingen uit Secrets
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Kon niet verbinden met Supabase. Controleer de secrets in Streamlit Cloud.")

# ---------------------------------------------------------
# 3. OVERZICHT BOVENAAN DE PAGINA (GESORTEERD OP ZELF/NIET ZELF EN PIN/CONTANT)
# ---------------------------------------------------------
st.subheader("📈 Overzicht Uitgaven")

try:
    res = supabase.table("kassabonnen").select("*").execute()
    if res.data:
        df_stats = pd.DataFrame(res.data)
        
        # Zorg dat numerieke kolommen goed als float worden gelezen
        df_stats["totaalprijs"] = pd.to_numeric(df_stats.get("totaalprijs", 0), errors="coerce").fillna(0.0)
        df_stats["eigen_bedrag"] = pd.to_numeric(df_stats.get("eigen_bedrag", 0), errors="coerce").fillna(0.0)
        
        totaal_uitgaven = df_stats["totaalprijs"].sum()
        
        # Buffers voor de categorieën
        zelf_pin = 0.0
        zelf_contant = 0.0
        
        niet_zelf_pin = 0.0
        niet_zelf_contant = 0.0
        
        for _, row in df_stats.iterrows():
            status = str(row.get("zelf", "")).lower()
            tot = float(row.get("totaalprijs", 0.0))
            eigen = float(row.get("eigen_bedrag", 0.0)) if "eigen_bedrag" in row else 0.0
            betaalwijze = str(row.get("betaalwijze", "")).lower()
            
            is_contant = "contant" in betaalwijze or "cash" in betaalwijze
            
            if status in ["zelf", "ja"]:
                if is_contant:
                    zelf_contant += tot
                else:
                    zelf_pin += tot
            elif status in ["niet zelf", "nee"]:
                if is_contant:
                    niet_zelf_contant += tot
                else:
                    niet_zelf_pin += tot
            elif status == "gedeeltelijk zelf":
                if is_contant:
                    zelf_contant += eigen
                    niet_zelf_contant += max(0.0, tot - eigen)
                else:
                    zelf_pin += eigen
                    niet_zelf_pin += max(0.0, tot - eigen)
            else:
                if is_contant:
                    zelf_contant += tot
                else:
                    zelf_pin += tot

        # --- TONEN IN STREAMLIT ---
        col_totaal, _, _ = st.columns(3)
        col_totaal.metric("Totaal Uitgegeven", f"€ {totaal_uitgaven:.2f}")

        col_left, col_right = st.columns(2)
        
        with col_left:
            st.markdown("### 👤 Zelf")
            c1, c2 = st.columns(2)
            c1.metric("💳 Pin", f"€ {zelf_pin:.2f}")
            c2.metric("💶 Contant", f"€ {zelf_contant:.2f}")
            st.caption(f"**Subtotaal Zelf:** € {zelf_pin + zelf_contant:.2f}")

        with col_right:
            st.markdown("### 👥 Niet zelf")
            c3, c4 = st.columns(2)
            c3.metric("💳 Pin", f"€ {niet_zelf_pin:.2f}")
            c4.metric("💶 Contant", f"€ {niet_zelf_contant:.2f}")
            st.caption(f"**Subtotaal Niet zelf:** € {niet_zelf_pin + niet_zelf_contant:.2f}")

    else:
        st.info("Nog geen uitgaven opgeslagen om een overzicht te tonen.")
except Exception as e:
    st.warning("Kon het uitgavenoverzicht niet laden uit Supabase.")

st.divider()

# ---------------------------------------------------------
# 4. GEAVANCEERDE PARSER FUNCTIE & BARCODE DETECTIE
# ---------------------------------------------------------
def scan_barcodes_from_image(pil_img):
    """Detecteert Barcodes en QR-codes op de afbeelding."""
    detected_codes = []
    if decode_barcodes is None:
        st.error("Het pakket 'pyzbar' is niet beschikbaar.")
        return detected_codes
    
    try:
        cv_img = np.array(pil_img)
        barcodes = decode_barcodes(cv_img)
        for barcode in barcodes:
            code_data = barcode.data.decode('utf-8')
            code_type = barcode.type
            detected_codes.append(f"{code_type}: {code_data}")
    except Exception as e:
        st.warning(f"Fout bij scannen barcode: {e}")
    return detected_codes

def parse_receipt_text(text):
    text_clean = re.sub(r't\s*o\s*t\s*a\s*a\s*l', 'totaal', text, flags=re.IGNORECASE)
    text_clean = re.sub(r's\s*u\s*b\s*t\s*o\s*t\s*a\s*a\s*l', 'subtotaal', text_clean, flags=re.IGNORECASE)
    
    lines = [l.strip() for l in text_clean.split('\n') if l.strip()]
    text_lower = text_clean.lower()
    
    winkel = ""
    totaal = 0.0
    statiegeld = 0.0
    datum = datetime.date.today()
    betaalmethode = "Pin"
    
    # 1. Winkelherkenning
    if any(k in text_lower for k in ["poiesz", "polesz", "poies", "po1esz", "poress"]):
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

    # 2. Datum
    datum_matches = re.findall(r'\b(\d{1,4})[-/. ](\d{1,2})[-/. ](\d{1,4})\b', text_clean)
    for p1, p2, p3 in datum_matches:
        try:
            v1, v2, v3 = int(p1), int(p2), int(p3)
            if v1 > 1000 and 1 <= v2 <= 12 and 1 <= v3 <= 31:
                datum = datetime.date(v1, v2, v3)
                break
            else:
                d, m, y = v1, v2, v3
                if y < 100:
                    y += 2000
                if 1 <= m <= 12 and 1 <= d <= 31 and 2000 <= y <= 2030:
                    datum = datetime.date(y, m, d)
                    break
        except Exception:
            continue

    # 3. Statiegeld
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

    def extract_amounts(s):
        found = []
        matches = re.findall(r'(\d*[,.‚]\d{2})', s)
        for m in matches:
            try:
                raw = m.replace('‚', '.').replace(',', '.')
                if raw.startswith('.'):
                    raw = "0" + raw
                v = float(raw)
                if v > 0:
                    found.append(v)
            except Exception:
                pass
        return found

    # 4. Totaalbedrag
    for idx, line in enumerate(reversed(lines)):
        real_idx = len(lines) - 1 - idx
        l_low = line.lower()
        
        if any(k in l_low for k in ["totaal", "subtotaal", "te betalen", "bedrag"]):
            if any(x in l_low for x in ["btw", "korting", "wisselgeld"]):
                continue
            
            amounts = extract_amounts(l_low)
            if not amounts and real_idx + 1 < len(lines):
                amounts = extract_amounts(lines[real_idx + 1].lower())
                
            if amounts:
                totaal = max(amounts)
                break

    if totaal == 0.0:
        for idx, line in enumerate(reversed(lines)):
            l_low = line.lower()
            if any(k in l_low for k in ["pin", "eur", "€"]):
                if any(x in l_low for x in ["btw", "korting", "wisselgeld", "kaart", "terminal", "kassa"]):
                    continue
                amounts = extract_amounts(l_low)
                if amounts:
                    totaal = max(amounts)
                    break

    if totaal == 0.0:
        all_amounts = []
        for line in lines:
            l_low = line.lower()
            if any(x in l_low for x in ["btw", "korting", "wisselgeld", "kaart", "transactie", "terminal", "autorisatie", "kassa"]):
                continue
            amounts = extract_amounts(l_low)
            all_amounts.extend([a for a in amounts if a <= 500.0])
            
        if all_amounts:
            totaal = max(all_amounts)

    # 5. Betaalmethode
    if any(k in text_lower for k in ["debit", "mastercard", "visa", "pin", "chip", "maestro", "contactloos"]):
        betaalmethode = "Pin"
    elif any(k in text_lower for k in ["contant", "cash", "wisselgeld"]):
        betaalmethode = "Contant"

    return winkel, datum, totaal, statiegeld, betaalmethode

# ---------------------------------------------------------
# 5. UPLOAD & VERWERKING
# ---------------------------------------------------------
uploaded_file = st.file_uploader(
    "Upload of maak een foto van een kassabon", 
    type=["jpg", "jpeg", "png"]
)

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    image = ImageOps.exif_transpose(image)
    
    st.image(image, caption="Geüploade Kassabon", use_container_width=True)

    text = ""
    
    # OCR bij de standaard upload
    with st.spinner("OCR verwerken en tekst analyseren..."):
        try:
            w, h = image.size
            if w < 1000:
                scale = 1000 / w
                image_resized = image.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            else:
                image_resized = image

            gray_image = image_resized.convert("L")
            enhancer = ImageEnhance.Contrast(gray_image)
            contrast_image = enhancer.enhance(1.8)
            
            text = pytesseract.image_to_string(contrast_image, lang="nld", config=r'--psm 3')
            if not text.strip():
                text = pytesseract.image_to_string(contrast_image, config=r'--psm 6')
        except Exception as ocr_err:
            st.warning(f"OCR kon de afbeelding niet volledig verwerken: {ocr_err}")

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
        categorie = st.selectbox("Categorie", ["Boodschappen", "Huishouden", "Hobby / Electronica", "Overig"])

    # Knop om specifiek Barcode / QR te scannen
    st.markdown("---")
    st.markdown("**🔍 Optioneel: Barcode / QR-code Scannen**")
    
    col_scan1, col_scan2 = st.columns([1, 2])
    with col_scan1:
        if st.button("📷 Scan Barcode op foto"):
            with st.spinner("Scannen op barcodes/QR-codes..."):
                found = scan_barcodes_from_image(image)
                if found:
                    st.session_state["found_barcodes"] = " | ".join(found)
                    st.success("Barcode(s) gevonden!")
                else:
                    st.session_state["found_barcodes"] = ""
                    st.info("Geen barcode of QR-code gevonden.")

    with col_scan2:
        barcode_input = st.text_input(
            "Gescande Barcode / QR Data", 
            value=st.session_state["found_barcodes"]
        )

    st.markdown("---")
    st.markdown("**💳 Betaalmethodes (Max. 5)**")
    
    aantal_methodes = st.number_input("Aantal gebruikte betaalmethodes", min_value=1, max_value=5, value=1, step=1)

    betaal_lijst = []
    betaal_opties = ["Pin", "Contant", "Creditcard", "Cadeaubon", "Anders"]
    
    opgeteld_bedrag = 0.0

    for i in range(int(aantal_methodes)):
        col_bm1, col_bm2 = st.columns(2)
        
        resterend = max(0.0, totaal_bedrag - opgeteld_bedrag)
        
        with col_bm1:
            def_idx = betaal_opties.index(auto_betaalmethode) if (i == 0 and auto_betaalmethode in betaal_opties) else (1 if i == 1 else 0)
            bm_type = st.selectbox(f"Betaalmethode {i+1}", betaal_opties, index=def_idx, key=f"bm_type_{i}")
        
        with col_bm2:
            bm_bedrag = st.number_input(
                f"Bedrag Methode {i+1} (€)", 
                min_value=0.0, 
                max_value=totaal_bedrag,
                value=round(resterend, 2), 
                format="%.2f", 
                key=f"bm_bedrag_{i}"
            )
        
        opgeteld_bedrag += bm_bedrag
        betaal_lijst.append(f"{bm_type}: €{bm_bedrag:.2f}")

    # Resterend saldo feedback
    verschil = totaal_bedrag - opgeteld_bedrag
    if abs(verschil) < 0.01:
        st.caption("✅ Het totaal van de betaalmethodes komt exact overeen met het totaalbedrag.")
    elif verschil > 0:
        st.info(f"💡 Er blijft nog **€ {verschil:.2f}** over om te verdelen.")
    else:
        st.warning(f"⚠️ Het totaal van de betaalmethodes is **€ {abs(verschil):.2f}** hoger dan het totaalbedrag.")

    gecombineerde_betaalwijze = " | ".join(betaal_lijst)

    st.markdown("---")

    # Statiegeld koppeling met Terug Bedrag
    default_terug_bedrag = statiegeld if statiegeld > 0 else 0.0
    default_retour = True if statiegeld > 0 else False

    terug_bedrag = st.number_input("Terug bedrag / Geld terug (€)", value=default_terug_bedrag, min_value=0.0, format="%.2f")
    retour_status = st.checkbox("Retour verwerkt", value=default_retour)

    st.markdown("**Wie betaalt deze uitgave?**")
    zelf_optie = st.radio(
        "Kies uitgavetype",
        ["Zelf", "Niet zelf", "Gedeeltelijk zelf"],
        horizontal=True,
        label_visibility="collapsed"
    )

    eigen_bedrag = totaal_bedrag
    if zelf_optie == "Gedeeltelijk zelf":
        eigen_bedrag = st.number_input(
            "Voer je eigen bedrag in (€)",
            min_value=0.0,
            max_value=totaal_bedrag,
            value=round(totaal_bedrag / 2, 2),
            format="%.2f"
        )
    elif zelf_optie == "Niet zelf":
        eigen_bedrag = 0.0

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
                    "totaalprijs": totaal_bedrag,
                    "statiegeld": statiegeld,
                    "betaalwijze": gecombineerde_betaalwijze,
                    "categorie": categorie,
                    "zelf": zelf_optie,
                    "eigen_bedrag": eigen_bedrag,
                    "retour": "Ja" if retour_status else "Nee",
                    "terug_bedrag": terug_bedrag,
                    "barcode_data": barcode_input,
                    "afbeelding_url": image_url
                }
                
                supabase.table("kassabonnen").insert(data).execute()
                
                # Reset session state for barcodes
                st.session_state["found_barcodes"] = ""
                
                st.success("✅ Kassabon succesvol opgeslagen!")
                st.rerun()
            except Exception as err:
                st.error(f"Fout bij opslaan: {err}")

st.divider()

# ---------------------------------------------------------
# 6. OVERZICHTSTABEL & EXCEL EXPORT
# ---------------------------------------------------------
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
