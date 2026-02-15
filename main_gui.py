import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import threading
import os
import pandas as pd

# IMPORTAMOS NUESTROS MÓDULOS PROPIOS 
from xml_parser import XMLParser
from pdf_generator import PDFGenerator
from exel_generator import ExcelGenerator

# ==========================================
# CONFIGURACIÓN
# ==========================================
RUTA_WKHTMLTOPDF = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'

class AppController:
    def __init__(self, root):
        self.root = root
        self.root.title("Convertidor + Validador EFOS (69-B)")
        self.root.geometry("750x600")
        
        # Cargar la base de datos EFOS
        self.efos_dict = self._cargar_lista_negra()
        
        # Inicializamos nuestros servicios
        self.parser = XMLParser()
        self.pdf_gen = PDFGenerator(RUTA_WKHTMLTOPDF)
        self.excel_gen = ExcelGenerator()
        
        self._setup_ui()

    def _cargar_lista_negra(self):
        """Carga el CSV de la carpeta bdChicosMalos a la memoria"""
        # --- CAMBIO CLAVE: Obtener la ruta real donde está este script ---
        directorio_script = os.path.dirname(os.path.abspath(__file__))
        ruta_csv = os.path.join(directorio_script, 'bdChicosMalos', 'Listado_Completo_69-B.csv')
        
        print(f"🔍 Buscando archivo EFOS en:\n -> {ruta_csv}")
        
        efos = {}
        if os.path.exists(ruta_csv):
            try:
                # El SAT pone 2 líneas de texto antes de los encabezados reales
                df = pd.read_csv(ruta_csv, skiprows=2, encoding='latin1')
                for _, row in df.iterrows():
                    rfc = str(row['RFC']).strip()
                    situacion = str(row['Situación del contribuyente']).strip()
                    efos[rfc] = situacion
                print(f"✅ Lista Negra cargada: {len(efos)} registros.")
            except Exception as e:
                print(f"❌ Error al leer el CSV: {e}")
        else:
            print("❌ ERROR: El archivo no existe en esa ruta.")
            
        return efos

    def _setup_ui(self):
        main_frame = tk.Frame(self.root, padx=20, pady=20, bg="#f4f6f9")
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="Validador y Convertidor de Facturas", font=("Segoe UI", 16, "bold"), bg="#f4f6f9").pack(pady=10)

        # Si cargó la lista negra, mostramos un indicador verde
        if self.efos_dict:
            tk.Label(main_frame, text=f"✅ Base de los hijos de perra conectada ({len(self.efos_dict)} registros)", fg="green", bg="#f4f6f9").pack()
        else:
            tk.Label(main_frame, text="❌ Base EFOS No Encontrada", fg="red", bg="#f4f6f9").pack()

        self.btn_select = tk.Button(main_frame, text="📂 Seleccionar XMLs a Procesar", 
                                    bg="#0056b3", fg="white", font=("Segoe UI", 11, "bold"),
                                    command=self.select_files)
        self.btn_select.pack(fill=tk.X, pady=15)

        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.pack(fill=tk.X, pady=5)

        tk.Label(main_frame, text="Bitácora de Resultados:", bg="#f4f6f9", anchor="w").pack(fill=tk.X)
        
        self.log_area = scrolledtext.ScrolledText(main_frame, height=15, font=("Consolas", 9))
        self.log_area.pack(fill=tk.BOTH, expand=True)
        
        # Configurar colores de la bitácora
        self.log_area.tag_config("error", foreground="#d32f2f", font=("Consolas", 9, "bold"))
        self.log_area.tag_config("success", foreground="#2e7d32")

    def log(self, msg, tag=None):
        self.log_area.insert(tk.END, msg + "\n", tag)
        self.log_area.see(tk.END)

    def select_files(self):
        files = filedialog.askopenfilenames(filetypes=[("Archivos XML", "*.xml")])
        if files:
            self.btn_select.config(state=tk.DISABLED)
            threading.Thread(target=self.run_process, args=(files,)).start()

    def run_process(self, files):
        total = len(files)
        success = 0
        all_excel_rows = []
        
        self.log(f"--- Iniciando lote de {total} archivos ---")
        
        for i, xml_path in enumerate(files):
            filename = os.path.basename(xml_path)
            pdf_path = os.path.splitext(xml_path)[0] + ".pdf"
            
            try:
                # 1: Leer XML
                data = self.parser.parse(xml_path)
                
                # --- NUEVA LÓGICA: VALIDACIÓN EFOS ---
                rfc_emisor = data["emisor"]["rfc"]
                es_efos = rfc_emisor in self.efos_dict
                
                if es_efos:
                    situacion = self.efos_dict[rfc_emisor]
                    self.log(f"⚠️ ¡ALERTA! El archivo '{filename}' viene del RFC: {rfc_emisor} (Estado: {situacion})", "error")
                else:
                    self.log(f"✅ OK: {filename}", "success")
                
                # 2: Generar el PDF
                self.pdf_gen.generate(data, pdf_path)
                
                # 3: Obtener filas para el Excel y agregarles la columna de alerta
                flat_rows = self.parser.get_flat_data(data, filename)
                for row in flat_rows:
                    row["Alerta EFOS (Lista 69-B)"] = "SÍ" if es_efos else "NO"
                    row["Situación EFOS"] = situacion if es_efos else "Limpio"
                    
                all_excel_rows.extend(flat_rows)
                success += 1
                
            except Exception as e:
                self.log(f"❌ ERROR en {filename}: {str(e)}", "error")
            
            # Actualizar barra
            progress_val = ((i + 1) / total) * 100
            self.progress['value'] = progress_val
            self.root.update_idletasks()

        # 4: Generar el Excel global
        if all_excel_rows:
            output_dir = os.path.dirname(files[0])
            excel_path = os.path.join(output_dir, "Reporte_Validacion_CFDIs.xlsx")
            try:
                self.excel_gen.generate(all_excel_rows, excel_path)
                self.log(f"\n📊 REPORTE CREADO: {excel_path}", "success")
            except Exception as e:
                self.log(f"❌ Error creando Excel: {str(e)}", "error")

        self.log(f"--- Fin de procesamiento ---")
        self.btn_select.config(state=tk.NORMAL)
        messagebox.showinfo("Proceso Terminado", "Revisa la bitácora y el archivo Excel generado.")

if __name__ == "__main__":
    root = tk.Tk()
    app = AppController(root)
    root.mainloop()