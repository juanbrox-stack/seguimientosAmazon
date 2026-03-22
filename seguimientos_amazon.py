import streamlit as st
import pandas as pd
from datetime import datetime
import io
import re

# Configuración de la página
st.set_page_config(page_title="Amazon Tracking Generator", layout="wide", page_icon="📦")

st.title("📦 Generador de Ficheros de Seguimiento Amazon")
st.markdown("""
Esta aplicación procesa los pedidos pendientes de Amazon y genera el fichero de subida.
**Actualización:** Se incluye la columna `promise-date` en el fichero final y ordenación por Tracking.
""")

def es_formato_amazon(texto):
    """Verifica si el texto tiene el patrón de pedido de Amazon (ej. 171-...)"""
    return bool(re.match(r'^\d{3}-', str(texto)))

# --- PASO 0: SELECCIÓN DE TIENDA ---
tienda = st.selectbox("¿Qué tienda es?", ["Seleccionar...", "Jabiru", "Turaco", "Marabú"])

if tienda != "Seleccionar...":
    
    # --- PASO 1: CARGAR ARCHIVO AMAZON ---
    st.subheader("1. Cargar Pedidos Pendientes (Amazon)")
    file_amazon = st.file_uploader("Sube el archivo .txt de Amazon", type=['txt'])

    if file_amazon:
        # Lectura forzando string para evitar notación científica en IDs
        df_pendientes = pd.read_csv(file_amazon, sep='\t', dtype=str, keep_default_na=False)
        df_pendientes.columns = df_pendientes.columns.str.strip()
        
        try:
            # Mostrar aviso de fecha mínima (Columna C de Amazon: purchase-date)
            fechas = pd.to_datetime(df_pendientes['purchase-date'].str[:10])
            fecha_minima = fechas.min().strftime('%d/%m/%Y')
            st.warning(f"⚠️ El pedido más antiguo es del: {fecha_minima}. Descarga el SGA de {tienda} desde esta fecha.")
        except:
            st.info("No se pudo extraer la fecha mínima de compra.")

        # --- PASO 2: CARGAR ARCHIVO SGA ---
        st.subheader("2. Cargar Datos del SGA")
        file_sga = st.file_uploader("Sube el archivo del SGA (Excel o CSV)", type=['xlsx', 'csv'])

        if file_sga:
            if file_sga.name.endswith('.csv'):
                df_sga = pd.read_csv(file_sga, dtype=str, keep_default_na=False)
            else:
                df_sga = pd.read_excel(file_sga, dtype=str, keep_default_na=False)

            if st.button("🚀 Generar Fichero de Subida"):
                try:
                    # --- PASO 3: MAPEO DEL SGA (Q o S) ---
                    sga_dict = {}
                    for _, row in df_sga.iterrows():
                        # Índices: Q=16, S=18, F=5, D=3, R=17
                        val_q = str(row.iloc[16]).strip() if len(row) > 16 else ""
                        val_s = str(row.iloc[18]).strip() if len(row) > 18 else ""
                        
                        # Decidir cuál es el ID de pedido correcto
                        id_final = ""
                        if es_formato_amazon(val_q):
                            id_final = val_q
                        elif es_formato_amazon(val_s):
                            id_final = val_s
                        else:
                            id_final = val_s if ("UD" in val_q.upper() or "-" in val_s) else val_q
                        
                        if "_REGEN_" in id_final.upper():
                            id_final = id_final.split("_REGEN_")[0]
                        
                        if "-" in id_final:
                            sga_dict[id_final] = [
                                str(row.iloc[5]).strip(), # Agencia (F)
                                str(row.iloc[3]).strip(), # Tracking (D)
                                str(row.iloc[17]).strip() # Tracking Alt (R)
                            ]

                    # --- PASO 4: PROCESAR PENDIENTES ---
                    results = []
                    fecha_ahora = datetime.now()

                    for _, row in df_pendientes.iterrows():
                        id_pedido = str(row['order-id']).strip()
                        # Filtro Is-Prime (Índice 33)
                        is_prime = str(row.iloc[33]).upper() if len(row) > 33 else "FALSE"
                        
                        if "-" not in id_pedido or is_prime == "TRUE":
                            continue
                        
                        # Limpieza ID Item (Columna B de Amazon)
                        order_item_id = str(row['order-item-id']).split('.')[0].strip()
                        reporting_date = str(row['reporting-date'])
                        promise_date = str(row['promise-date']) # Columna F original
                        quantity = str(row['quantity-to-ship'])
                        pais = str(row['ship-country']).upper()
                        
                        datos_sga = sga_dict.get(id_pedido)
                        
                        agencia, tracking_raw, tracking_alt = "", "", ""
                        if datos_sga:
                            agencia, tracking_raw, tracking_alt = datos_sga
                        
                        tracking_final = ""
                        carrier_name_final = ""
                        
                        if tracking_raw and tracking_raw != "nan" and tracking_raw != "":
                            tracking_final = tracking_raw.split('.')[0].strip()
                        
                        # Lógica de fechas y agencias por defecto
                        if tracking_final == "":
                            try:
                                # Comprobar si ya ha pasado la fecha de promesa para forzar salida
                                fecha_p_dt = datetime.strptime(promise_date[:10], '%Y-%m-%d')
                                if fecha_p_dt > fecha_ahora: continue
                            except: pass
                            carrier_name_final = promise_date
                            agencia = "TIPSA" if pais == "ES" else "UPS"
                        else:
                            if "METHOD" in agencia.upper() and tracking_final.upper().startswith("MECE"):
                                tracking_final = tracking_alt.split('.')[0].strip()

                        # Normalización de transportistas
                        ag_upper = agencia.upper()
                        era_ontime = False
                        if "ONTIME" in ag_upper or "ON TIME" in ag_upper:
                            agencia = "Envialia"; era_ontime = True
                        elif "ENVIALIA" in ag_upper: agencia = "Envialia"
                        elif "GLS" in ag_upper: agencia = "GLS"
                        elif "METHOD" in ag_upper: agencia = "Method Logistics"
                        elif "WALDEN" in ag_upper or "RELAIS COLIS" in ag_upper: agencia = "Relais Colis"
                        elif "RHENUS" in ag_upper: agencia = "Rhenus Logistics"

                        carrier_code = agencia
                        ship_method = "Standard"
                        ag_norm = agencia.upper()
                        
                        if ag_norm in ["RHENUS LOGISTICS", "RELAIS COLIS", "METHOD LOGISTICS", "XPO LOGISTICS"]:
                            carrier_code = "OTHER"; ship_method = "OTHER"
                        elif ag_norm == "MRW": ship_method = "Urgente 19"
                        elif ag_norm == "SEUR": ship_method = "SEUR 24"
                        elif ag_norm == "GLS":
                            ship_method = "BusinessParcel" if tracking_final.startswith("Z") else "Business Parcel"
                        elif ag_norm == "UPS": ship_method = "Standard"
                        elif ag_norm == "TIPSA": ship_method = "ECONOMY"
                        elif ag_norm == "ENVIALIA": ship_method = "24"

                        # Añadir prefijos a trackings numéricos
                        if tracking_final != "":
                            if "ITALIA" in ag_upper and not tracking_final.startswith("M1"):
                                tracking_final = "M1" + tracking_final
                            if agencia == "Envialia" and not era_ontime:
                                if not tracking_final.startswith("004695"): tracking_final = "004695" + tracking_final
                            elif agencia == "TIPSA":
                                if not tracking_final.startswith("046005046005"): tracking_final = "046005046005" + tracking_final

                        results.append({
                            "order-id": id_pedido,
                            "order-item-id": order_item_id,
                            "quantity": quantity,
                            "ship-date": reporting_date,
                            "carrier-code": carrier_code,
                            "carrier-name": agencia if carrier_code == "OTHER" else carrier_name_final,
                            "tracking-number": tracking_final,
                            "ship-method": ship_method,
                            "promise-date": promise_date # NUEVA COLUMNA AÑADIDA
                        })

                    # --- PASO 5: ORDENACIÓN Y EXPORTACIÓN ---
                    df_final = pd.DataFrame(results)
                    
                    if not df_final.empty:
                        # Ordenar por tracking-number y luego por promise-date
                        df_final = df_final.sort_values(by=['tracking-number', 'promise-date'], ascending=[True, True])
                        
                        st.success(f"✅ Generados {len(df_final)} registros.")
                        
                        output = io.StringIO()
                        df_final.to_csv(output, sep='\t', index=False, quoting=0)
                        
                        st.download_button(
                            label="⬇️ Descargar Fichero para Amazon",
                            data=output.getvalue(),
                            file_name=f"{datetime.now().strftime('%Y%m%d')}_{tienda}.txt",
                            mime="text/plain"
                        )
                        st.dataframe(df_final.astype(str))
                    else:
                        st.warning("No se encontraron registros para procesar.")

                except Exception as e:
                    st.error(f"Error crítico: {str(e)}")