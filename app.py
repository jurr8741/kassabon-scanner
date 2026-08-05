import streamlit as st
from supabase import create_client, Client
import pytesseract
from PIL import Image, ImageOps
import pandas as pd
import datetime
import io

# 1. Page Configuration
st.set_page_config(page_title="Kassabonnen Scanner", page_icon="🧾", layout="centered")

st.title("🧾 Kassabonnen Scanner")

# 2. Supabase Instellingen uit Secrets
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Kon niet verbinden met Supabase. Controleer of SUPABASE_URL en SUPABASE_KEY goed zijn ingesteld in Streamlit Secrets.")

# 3. Upload & Camera Functionaliteit (JPG, JPEG, PNG)
uploaded_file = st.file_uploader(
    "Upload of maak een foto van een kassabon", 
    type=["jpg", "jpeg", "png"]
)

if uploaded_file is not None:
    # Open afbeelding
    image = Image.open(uploaded_file)
    
    # Automatisch corrigeren van de oriëntatie op basis van EXIF-data (telefoonfoto's)
    image = ImageOps.exif_transpose(image)
    
    st.image(image, caption="Geüploade Kassabon", use_container_width=True)

    with st.spinner("OCR verwerken..."):
        # Omzetten naar grijswaarden voor betere contrast-herkenning
        gray_image = image.convert("L")
        
        try:
            # Probeer eerst met het Nederlandse taalpakket
            text = pytesseract.image_to_string(gray_image, lang="nld")
        except Exception:
            # Fallback als nld pakket niet beschikbaar is
            text = pytesseract.image_to_string(gray_image)
    
    st.subheader("Geëxtraheerde Tekst")
    with st.expander("Bekijk ruwe OCR-tekst"):
        st.text(text if text.strip() else "Geen tekst herkend. Zorg voor voldoende licht en een scherpe foto.")

    st.subheader("Details Invoeren & Controleren")
    
    col1, col2 = st.columns(2)
    with col1:
        winkel = st.text_input("Winkelnaam", value="")
        datum = st.date_input("Datum bon", value=datetime.date.today())
        totaal_bedrag = st.number_input("Totaalbedrag (€)", min_value=0.0, format="%.2f")
    
    with col2:
        statiegeld = st.number_input("Statiegeld (€)", min_value=0.0, format="%.2f")
        betaalmethode = st.selectbox("Betaalmethode", ["Pin", "Contant", "Creditcard", "Anders"])
        categorie = st.selectbox("Categorie", ["Boodschappen", "Huishouden", "Hobby / Electronica", "Overig"])

    is_self = st.checkbox("Eigen uitgave (Self)", value=True)
    retour_status = st.checkbox("Retour verwerkt", value=False)

    if st.button("💾 Opslaan in Database", type="primary"):
        with st.spinner("Opslaan in Supabase..."):
            try:
                # Afbeelding klaarmaken voor upload (omzetten naar bytes)
                img_bytes = io.BytesIO()
                image.convert("RGB").save(img_bytes, format="JPEG")
                img_data = img_bytes.getvalue()
                
                # Unieke bestandsnaam genereren
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"bon_{timestamp}.jpg"
                
                # 1. Foto uploaden naar Supabase Storage bucket
                supabase.storage.from_("bonnen-fotos").upload(
                    path=filename,
                    file=img_data,
                    file_options={"content-type": "image/jpeg"}
                )
                
                # Publieke URL ophalen van het geüploade bestand
                image_url = supabase.storage.from_("bonnen-fotos").get_public_url(filename)
                
                # 2. Metadata opslaan in de Postgres database tabel 'kassabonnen'
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

# 4. Inzage & Excel Export
st.subheader("📊 Inzage & Excel Export")

if st.button("Laden van opgeslagen bonnen"):
    try:
        res = supabase.table("kassabonnen").select("*").execute()
        if res.data:
            df = pd.DataFrame(res.data)
            st.dataframe(df)
            
            # Excel export genereren
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
