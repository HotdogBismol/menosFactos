import pandas as pd
from openpyxl.styles import PatternFill, Font
import os

class ExcelGenerator:
    def __init__(self):
        pass
        
    def generate(self, data_list, output_path):
        """Recibe una lista de diccionarios, crea un Excel y formatea alertas"""
        if not data_list:
            return False
            
        # Convertir datos a DataFrame
        df = pd.DataFrame(data_list)
        
        # Iniciar el motor de Excel
        writer = pd.ExcelWriter(output_path, engine='openpyxl')
        df.to_excel(writer, index=False, sheet_name='Reporte CFDI')
        
        # --- SECCIÓN DE FORMATO CONDICIONAL (COLOR ROJO) ---
        worksheet = writer.sheets['Reporte CFDI']
        
        # Definir el estilo visual para los "chicos malos"
        red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
        red_font = Font(color="9C0006")
        
        # Buscar en qué columna quedó nuestra alerta
        if "Alerta EFOS (Lista 69-B)" in df.columns:
            # openpyxl usa índices base 1, pandas usa 0, por eso sumamos 1
            efos_col_idx = df.columns.get_loc("Alerta EFOS (Lista 69-B)") + 1
            
            # Recorrer las filas del Excel (saltando la fila 1 de encabezados)
            for row_idx, row in enumerate(worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, min_col=1, max_col=worksheet.max_column), start=2):
                # Revisar el valor en la columna de la alerta
                alerta = worksheet.cell(row=row_idx, column=efos_col_idx).value
                
                # Si dice "SÍ", pintamos TODAS las celdas de esa fila de rojo
                if alerta == "SÍ":
                    for cell in row:
                        cell.fill = red_fill
                        cell.font = red_font

        # --- AUTOAJUSTE DE COLUMNAS (Para que se vea bonito) ---
        for col in worksheet.columns:
            max_length = 0
            column = col[0].column_letter # Letra de la columna (A, B, C...)
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(cell.value)
                except:
                    pass
            worksheet.column_dimensions[column].width = (max_length + 2)

        # Guardar archivo
        writer.close()
        return True