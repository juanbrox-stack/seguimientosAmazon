import streamlit as st
import pandas as pd
from datetime import datetime
import io
import re

# Configuración de la página
st.set_page_config(page_title="Amazon Tracking Generator", layout="wide", page_icon="📦")

st.title("📦 Generador de Ficheros de Seguimiento Amazon")
st.markdown("""
Esta aplicación cruza los pedidos pendientes de Amazon con el SGA.
**Cambios aplicados:** `order-item-id` extraído de Columna B, búsqueda de pedido en Q o S, y limpieza estricta de formatos numéricos.
""")

def es_formato_amazon(texto):
    """Verifica si el texto sigue el patrón XXX-XXXXXXX-XXXXXXX"""
    return bool(re.match(r'^\d{3}-', str(texto)))

def limpiar_texto_puro(valor):
    """Fuerza el valor a string, elimina decimales .0 y quita espacios"""
    if pd.isna(valor) or valor == "":
        return ""
    # Convertimos a string y eliminamos el .0 que añade Excel a los números largos
    str_val = str(valor).split('.')[0].strip()
    return str_val

# --- PASO 0: SELECCIÓN DE TIENDA ---
tienda = st.selectbox("¿Qué tienda es?", ["Seleccionar...", "Jabiru", "Turaco", "Marabú"])

if tienda != "Seleccionar...":
    
    # --- PASO 1: CARGAR ARCHIVO AMAZON ---
    st.subheader("1. Cargar Pedidos Pendientes (Amazon)")
    file_amazon = st.file_uploader("Sube el archivo .txt de Amazon", type=['txt'])

    if file_amazon:
        # Leemos el TXT de Amazon (tabulado) forzando que todo sea texto
        df_pendientes = pd.read_csv(file_amazon, sep='\t', dtype=str, keep_default_na=False)
        df_pendientes.columns = df_pendientes.columns.str.strip()
        
        try:
            # Columna purchase-date para aviso al usuario 
            fechas = pd.to_datetime(df_pendientes['purchase-date'].str[:10])
            fecha_minima = fechas.min().strftime('%d/%m/%Y')
            st.warning(f"⚠️ El pedido más antiguo es del: {fecha_minima}. Descarga el SGA de {tienda} desde esta fecha.")
        except:
            st.info("No se pudo determinar la fecha del pedido más antiguo.")

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
                    # --- PASO 3: MAPEO DEL SGA (Lógica de Col Q o S) ---
                    sga_dict = {}
                    for _, row in df_sga.iterrows():
                        # Índices según macro original: Q=16, S=18, F=5, D=3, R=17
                        val_q = limpiar_texto_puro(row.iloc[16])
                        val_s = limpiar_texto_puro(row.iloc[18])
                        
                        id_final = ""
                        if es_formato_amazon(val_q):
                            id_final = val_q
                        elif es_formato_amazon(val_s):
                            id_final = val_s
                        else:
                            # Si no hay formato Amazon, aplicar lógica UD o guiones
                            id_final = val_s if ("UD" in val_q.upper() or "-" in val_s) else val_q
                        
                        if "_REGEN_" in id_final.upper():
                            id_final = id_final.split("_REGEN_")[0]
                        
                        if "-" in id_final:
                            sga_dict[id_final] = [
                                str(row.iloc[5]).strip(), # Agencia
                                str(row.iloc[3]).strip(), # Tracking
                                str(row.iloc[17]).strip() # Tracking Alt
                            ]

                    # --- PASO 4: PROCESAR CRUCE ---
                    results = []
                    fecha_ahora = datetime.now()

                    for _, row in df_pendientes.iterrows():
                        id_pedido = limpiar_texto_puro(row['order-id'])
                        # Filtro Is-Prime (Columna 34 de la macro / Índice 33)
                        is_prime = str(row.iloc[33]).upper() if len(row) > 33 else "FALSE"
                        
                        if "-" not in id_pedido or is_prime == "TRUE":
                            continue
                        
                        # order-item-id extraído de Columna B (Índice 1) 
                        order_item_id = limpiar_texto_puro(row.iloc[1])
                        
                        reporting_date = str(row['reporting-date'])
                        promise_date_val = str(row['promise-date']).strip()
                        quantity = str(row['quantity-to-ship'])
                        pais = str(row['ship-country']).upper()
                        
                        datos_sga = sga_dict.get(id_pedido)
                        agencia, tracking_raw, tracking_alt = "", "", ""
                        if datos_sga:
                            agencia, tracking_raw, tracking_alt = datos_sga
                        
                        tracking_final = ""
                        carrier_name_final = ""
                        
                        if tracking_raw and tracking_raw != "nan" and tracking_raw != "":
                            tracking_final = limpiar_texto_puro(tracking_raw)
                        
                        if tracking_final == "":
                            try:
                                fecha_p_dt = datetime.strptime(promise_date_val[:10], '%Y-%m-%d')
                                if fecha_p_dt > fecha_ahora: continue
                            except: pass
                            agencia = "TIPSA" if pais == "ES" else "UPS"
                            carrier_name_final = promise_date_val
                        else:
                            if "METHOD" in agencia.upper() and tracking_final.upper().startswith("MECE"):
                                tracking_final = limpiar_texto_puro(tracking_alt)

                        # Normalización de Agencias
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
                            "promise-date": promise_date_val
                        })

                    # --- PASO 5: ORDENACIÓN Y EXPORTACIÓN ---
                    df_final = pd.DataFrame(results)
                    
                    if not df_final.empty:
                        # Ordenar por Tracking (Col G) y luego por Promise Date
                        df_final = df_final.sort_values(by=['tracking-number', 'promise-date'], ascending=[True, True])
                        
                        st.success(f"✅ ¡Hecho! {len(df_final)} pedidos listos.")
                        
                        # Vista previa
                        st.dataframe(df_final.astype(str))

                        # Generar archivo TXT tabulado sin comillas (quoting=3)
                        output = io.StringIO()
                        df_final.to_csv(output, sep='\t', index=False, quoting=3, escapechar=' ')
                        
                        st.download_button(
                            label="⬇️ Descargar Fichero para Amazon",
                            data=output.getvalue(),
                            file_name=f"{datetime.now().strftime('%Y%m%d')}_{tienda}.txt",
                            mime="text/plain"
                        )
                    else:
                        st.warning("No se encontraron registros que procesar.")

                except Exception as e:
                    st.error(f"Error en el proceso: {str(e)}")