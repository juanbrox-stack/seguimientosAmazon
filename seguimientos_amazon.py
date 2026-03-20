import streamlit as st
import pandas as pd
from datetime import datetime
import io

# Configuración de la página
st.set_page_config(page_title="Amazon Tracking Generator", layout="wide")

st.title("📦 Generador de Ficheros de Seguimiento Amazon")
st.markdown("""
Esta aplicación replica la lógica de la Macro V38 para cruzar datos del SGA y Pedidos Pendientes de Amazon.
""")

# --- PASO 0: SELECCIÓN DE TIENDA ---
tienda = st.selectbox("¿Qué tienda es?", ["Seleccionar...", "Jabiru", "Turaco", "Marabú"])

if tienda != "Seleccionar...":
    
    # --- PASO 1: SELECCIONAR AMAZON ---
    st.subheader("1. Cargar Pedidos Pendientes (Amazon)")
    file_amazon = st.file_uploader("Sube el archivo .txt de Amazon", type=['txt'])

    if file_amazon:
        # Leer TXT de Amazon (Delimitado por tabuladores)
        df_pendientes = pd.read_csv(file_amazon, sep='\t', dtype=str)
        
        # Calcular fecha más antigua para informar al usuario (Columna purchase-date)
        try:
            fechas = pd.to_datetime(df_pendientes['purchase-date'].str[:10])
            fecha_minima = fechas.min().strftime('%d/%m/%Y')
            st.warning(f"⚠️ El pedido más antiguo es del: {fecha_minima}. Descarga el SGA de {tienda} desde esta fecha.")
        except:
            st.error("No se pudo procesar la fecha de los pedidos de Amazon.")

        # --- PASO 2: SELECCIONAR SGA ---
        st.subheader("2. Cargar Datos del SGA")
        file_sga = st.file_uploader("Sube el archivo del SGA (Excel o CSV)", type=['xlsx', 'csv'])

        if file_sga:
            # Leer SGA
            if file_sga.name.endswith('.csv'):
                df_sga = pd.read_csv(file_sga, dtype=str)
            else:
                df_sga = pd.read_excel(file_sga, dtype=str)

            if st.button("🚀 Generar Fichero de Subida"):
                try:
                    # --- PASO 3: PROCESAR LOGICA ---
                    # Limpieza y mapeo de columnas SGA (según lógica de la macro)
                    # La macro usa columnas por letra: F(6), D(4), R(18), Q(17), S(19)
                    # Ajustamos a índices 0 (A=0, B=1...)
                    
                    sga_dict = {}
                    for _, row in df_sga.iterrows():
                        # Lógica de IDs de pedido
                        id_pedido = str(row.iloc[16]).strip() if len(row) > 16 else "" # Col Q
                        id_aux = str(row.iloc[18]).strip() if len(row) > 18 else ""    # Col S
                        
                        if "UD" in id_pedido.upper() or id_aux.count('-') >= 2:
                            id_pedido = id_aux
                        
                        if "_REGEN_" in id_pedido.upper():
                            id_pedido = id_pedido.split("_REGEN_")[0]
                        
                        if "-" in id_pedido:
                            # Guardamos Array(Agencia, Seguimiento, SeguimientoAlt)
                            # F=5, D=3, R=17
                            sga_dict[id_pedido] = [row.iloc[5], row.iloc[3], row.iloc[17]]

                    # --- PASO 4: PROCESAR PENDIENTES ---
                    results = []
                    fecha_ahora = datetime.now()

                    for _, row in df_pendientes.iterrows():
                        id_pedido = str(row['order-id']).strip()
                        
                        # Filtros: Debe tener guion y is-prime (Col 34 -> índice 33) no puede ser TRUE
                        is_prime = str(row.iloc[33]).upper() if len(row) > 33 else "FALSE"
                        if "-" not in id_pedido or is_prime == "TRUE":
                            continue
                        
                        order_item_id = row['order-item-id']
                        reporting_date = row['reporting-date']
                        promise_date_str = str(row['promise-date'])
                        quantity = row['quantity-to-ship']
                        pais = str(row['ship-country']).upper()
                        
                        # Buscar en SGA
                        datos_sga = sga_dict.get(id_pedido)
                        
                        agencia = ""
                        seguimiento = ""
                        seguimiento_alt = ""
                        
                        if datos_sga:
                            agencia = str(datos_sga[0]).strip()
                            seguimiento = str(datos_sga[1]).strip()
                            seguimiento_alt = str(datos_sga[2]).strip()

                        # Lógica de fechas y agencias por defecto
                        tracking_final = ""
                        carrier_name_final = ""
                        
                        if seguimiento == "" or seguimiento == "nan":
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
                            tracking_final = seguimiento
                            if "METHOD" in agencia.upper() and tracking_final.upper().startswith("MECE"):
                                tracking_final = seguimiento_alt

                        # Normalización de Agencias (Mapping)
                        ag_upper = agencia.upper()
                        era_ontime = False
                        
                        if "ONTIME" in ag_upper or "ON TIME" in ag_upper:
                            agencia = "Envialia"
                            era_ontime = True
                        elif "ENVIALIA" in ag_upper:
                            agencia = "Envialia"
                        elif "GLS" in ag_upper:
                            agencia = "GLS"
                        elif "METHOD" in ag_upper:
                            agencia = "Method Logistics"
                        elif "WALDEN" in ag_upper or "RELAIS COLIS" in ag_upper:
                            agencia = "Relais Colis"
                        elif "RHENUS" in ag_upper:
                            agencia = "Rhenus Logistics"

                        # Carrier Code y Ship Method
                        carrier_code = agencia
                        ship_method = "Standard"
                        
                        ag_norm = agencia.upper()
                        if ag_norm in ["RHENUS LOGISTICS", "RELAIS COLIS", "METHOD LOGISTICS", "XPO LOGISTICS"]:
                            carrier_code = "OTHER"
                            ship_method = "OTHER"
                        elif ag_norm == "MRW":
                            ship_method = "Urgente 19"
                        elif ag_norm == "SEUR":
                            ship_method = "SEUR 24"
                        elif ag_norm == "GLS":
                            ship_method = "BusinessParcel" if tracking_final.startswith("Z") else "Business Parcel"
                        elif ag_norm == "UPS":
                            ship_method = "Standard"
                        elif ag_norm == "TIPSA":
                            ship_method = "ECONOMY"
                        elif ag_norm == "ENVIALIA":
                            ship_method = "24"

                        # Prefijos de Tracking
                        if tracking_final != "":
                            if "ITALIA" in ag_upper and not tracking_final.startswith("M1"):
                                tracking_final = "M1" + tracking_final
                            if agencia == "Envialia" and not era_ontime:
                                if not tracking_final.startswith("004695"):
                                    tracking_final = "004695" + tracking_final
                            elif agencia == "TIPSA":
                                if not tracking_final.startswith("046005046005"):
                                    tracking_final = "046005046005" + tracking_final

                        # Añadir a resultados
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

                    # Crear DataFrame final
                    df_final = pd.DataFrame(results)

                    # --- PASO FINAL: DESCARGA ---
                    st.success(f"✅ ¡Proceso completado! Se han generado {len(df_final)} líneas.")
                    
                    # Convertir a texto tabulado (formato Amazon)
                    output = io.StringIO()
                    df_final.to_csv(output, sep='\t', index=False)
                    
                    nombre_archivo = f"{datetime.now().strftime('%Y%m%d')}_{tienda}.txt"
                    
                    st.download_button(
                        label="⬇️ Descargar Fichero para Amazon",
                        data=output.getvalue(),
                        file_name=nombre_archivo,
                        mime="text/plain"
                    )
                    
                    st.dataframe(df_final)

                except Exception as e:
                    st.error(f"Error procesando los archivos: {e}")