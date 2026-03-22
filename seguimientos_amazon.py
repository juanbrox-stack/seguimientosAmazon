import streamlit as st
import pandas as pd
from datetime import datetime
import io

# Configuración de la página
st.set_page_config(page_title="Amazon Tracking Generator", layout="wide", page_icon="📦")

st.title("📦 Generador de Ficheros de Seguimiento Amazon")
st.markdown("""
Esta aplicación procesa los pedidos pendientes de Amazon y los cruza con los datos del SGA 
para generar el fichero de subida de seguimientos (.txt).
""")

# --- PASO 0: SELECCIÓN DE TIENDA ---
tienda = st.selectbox("¿Qué tienda es?", ["Seleccionar...", "Jabiru", "Turaco", "Marabú"])

if tienda != "Seleccionar...":
    
    # --- PASO 1: SELECCIONAR AMAZON ---
    st.subheader("1. Cargar Pedidos Pendientes (Amazon)")
    file_amazon = st.file_uploader("Sube el archivo .txt de Amazon", type=['txt'])

    if file_amazon:
        # Leemos forzando que todo sea STRING para evitar 6.15E+13
        df_pendientes = pd.read_csv(file_amazon, sep='\t', dtype=str, keep_default_na=False)
        df_pendientes.columns = df_pendientes.columns.str.strip()
        
        # Calcular fecha más antigua para avisar al usuario
        try:
            fechas = pd.to_datetime(df_pendientes['purchase-date'].str[:10])
            fecha_minima = fechas.min().strftime('%d/%m/%Y')
            st.warning(f"⚠️ El pedido más antiguo es del: {fecha_minima}. Descarga el SGA de {tienda} desde esta fecha.")
        except:
            st.info("No se pudo extraer la fecha mínima de los pedidos.")

        # --- PASO 2: SELECCIONAR SGA ---
        st.subheader("2. Cargar Datos del SGA")
        file_sga = st.file_uploader("Sube el archivo del SGA (Excel o CSV)", type=['xlsx', 'csv'])

        if file_sga:
            # Leer SGA forzando strings
            if file_sga.name.endswith('.csv'):
                df_sga = pd.read_csv(file_sga, dtype=str, keep_default_na=False)
            else:
                df_sga = pd.read_excel(file_sga, dtype=str, keep_default_na=False)

            if st.button("🚀 Generar Fichero de Subida"):
                try:
                    # --- PASO 3: MAPEO DEL SGA ---
                    sga_dict = {}
                    for _, row in df_sga.iterrows():
                        # Usamos los índices de columna de la macro (Q=16, S=18, F=5, D=3, R=17)
                        id_pedido = str(row.iloc[16]).strip() if len(row) > 16 else ""
                        id_aux = str(row.iloc[18]).strip() if len(row) > 18 else ""
                        
                        if "UD" in id_pedido.upper() or id_aux.count('-') >= 2:
                            id_pedido = id_aux
                        
                        if "_REGEN_" in id_pedido.upper():
                            id_pedido = id_pedido.split("_REGEN_")[0]
                        
                        if "-" in id_pedido:
                            # Guardamos: [Agencia (F), Tracking (D), TrackingAlt (R)]
                            sga_dict[id_pedido] = [
                                str(row.iloc[5]).strip(), 
                                str(row.iloc[3]).strip(), 
                                str(row.iloc[17]).strip()
                            ]

                    # --- PASO 4: PROCESAR PENDIENTES ---
                    results = []
                    fecha_ahora = datetime.now()

                    for _, row in df_pendientes.iterrows():
                        id_pedido = str(row['order-id']).strip()
                        
                        # Filtro Prime (Col 34 -> índice 33)
                        is_prime = str(row.iloc[33]).upper() if len(row) > 33 else "FALSE"
                        if "-" not in id_pedido or is_prime == "TRUE":
                            continue
                        
                        # LIMPIEZA CRÍTICA: order-item-id (eliminar .0 si existe)
                        order_item_id = str(row['order-item-id']).split('.')[0].strip()
                        
                        reporting_date = str(row['reporting-date'])
                        promise_date_str = str(row['promise-date'])
                        quantity = str(row['quantity-to-ship'])
                        pais = str(row['ship-country']).upper()
                        
                        datos_sga = sga_dict.get(id_pedido)
                        
                        agencia = ""
                        tracking_raw = ""
                        tracking_alt = ""
                        
                        if datos_sga:
                            agencia, tracking_raw, tracking_alt = datos_sga
                        
                        # Lógica de fechas y agencias por defecto
                        tracking_final = ""
                        carrier_name_final = ""
                        
                        # Limpiar tracking de posibles .0
                        if tracking_raw and tracking_raw != "nan":
                            tracking_final = tracking_raw.split('.')[0].strip()
                        
                        if tracking_final == "" or tracking_final == "nan":
                            try:
                                fecha_promesa = datetime.strptime(promise_date_str[:10], '%Y-%m-%d')
                                if fecha_promesa > fecha_ahora:
                                    continue
                            except:
                                pass
                            
                            tracking_final = ""
                            carrier_name_final = promise_date_str
                            agencia = "TIPSA" if pais == "ES" else "UPS"
                        else:
                            if "METHOD" in agencia.upper() and tracking_final.upper().startswith("MECE"):
                                tracking_final = tracking_alt.split('.')[0].strip()

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

                        # Carrier Code y Ship Method
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

                        # Prefijos de Tracking
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
                            "ship-method": ship_method
                        })

                    # --- PASO FINAL: EXPORTACIÓN ---
                    df_final = pd.DataFrame(results)
                    
                    if not df_final.empty:
                        st.success(f"✅ ¡Proceso completado! {len(df_final)} pedidos listos.")
                        
                        # Generar el TXT (tabulado) asegurando formato texto
                        output = io.StringIO()
                        df_final.to_csv(output, sep='\t', index=False, quoting=0) # quoting=0 para evitar comillas
                        
                        st.download_button(
                            label="⬇️ Descargar Fichero para Amazon",
                            data=output.getvalue(),
                            file_name=f"{datetime.now().strftime('%Y%m%d')}_{tienda}.txt",
                            mime="text/plain"
                        )
                        st.dataframe(df_final.astype(str)) # Mostrar como string en la web
                    else:
                        st.warning("No se encontraron pedidos para procesar.")

                except Exception as e:
                    st.error(f"Error en el procesamiento: {str(e)}")