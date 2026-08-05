import streamlit as st
from supabase import create_client, Client
import pytesseract
from PIL import Image
import pandas as pd
import datetime
import io

# 1. Supabase Instellingen
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Kassabonnen Scanner", page_icon="🧾", layout="centered")

st.title("🧾 Kassabonnen Scanner")

# 2. Upload sectie (Accepteert nu JPG, JPEG en PNG)
uploaded_file = st.file_uploader(
    "Upload of maak een foto van een kassabon", 
    type=["jpg", "jpeg", "png"]
)

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.image(image, caption="Geüploade Kassabon", use_container_width=True)

    with st.spinner("OCR verwerken..."):
        # Tekst extraheren met pytesseract
        text = pytesseract.image_to_string(image, lang="nld")
    
    st.subheader("Geëxtraheerde Tekst")
    with st.expander("Bekijk ruwe OCR-tekst"):
        st.text(text)

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
        with st.spinner("Opslaan..."):
            # 1. Afbeelding uploaden naar Supabase Storage
            img_bytes = io.BytesIO()
            # Zet de afbeelding om naar PNG voor consistentie in de bucket
            image.convert("RGB").save(img_bytes, format="JPEG")
            img_bytes = img_bytes.getvalue()
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"bon_{timestamp}.jpg"
            
            storage_res = supabase.storage.from_("bonnen-fotos").upload(
                path=filename,
                file=img_bytes,
                file_options={"content-type": "image/jpeg"}
            )
            
            # Publieke URL ophalen
            image_url = supabase.storage.from_("bonnen-fotos").get_public_url(filename)
            
            # 2. Data opslaan in Postgres database
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

st.divider()

# 3. Overzicht & Excel Export
st.subheader("📊 Inzage & Excel Export")

if st.button("Laden van opgeslagen bonnen"):
    res = supabase.table("kassabonnen").select("*").execute()
    if res.data:
        df = pd.DataFrame(res.data)
        st.dataframe(df)
        
        # Excel export
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
        st.info("Nog geen kassabonnen gevonden.")
