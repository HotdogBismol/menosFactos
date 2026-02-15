import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk
import threading
import os
import xml.etree.ElementTree as ET
from jinja2 import Template
import pdfkit
import qrcode
import base64
from io import BytesIO

# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
# Ajusta esta ruta si es necesario
RUTA_WKHTMLTOPDF = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'

# ==========================================
# 2. LÓGICA DE CONVERSIÓN (BACKEND)
# ==========================================
class CFDIConverter:
    def __init__(self, wkhtml_path):
        self.wkhtml_path = wkhtml_path
        self.config = pdfkit.configuration(wkhtmltopdf=wkhtml_path)
        self.ns = {
            'cfdi': 'http://www.sat.gob.mx/cfd/4',
            'pago20': 'http://www.sat.gob.mx/Pagos20',
            'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'
        }

    def _format_currency(self, value):
        try:
            return "${:,.2f}".format(float(value))
        except (ValueError, TypeError):
            return "$0.00"

    def _generate_qr(self, data):
        qr_str = (f"https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?"
                  f"id={data['uuid']}&re={data['emisor_rfc']}&rr={data['receptor_rfc']}"
                  f"&tt={data['total_raw']}&fe={data['sello'][-8:]}")
        
        qr = qrcode.QRCode(box_size=3, border=1)
        qr.add_data(qr_str)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode()

    def parse_xml(self, xml_path):
        if not os.path.exists(xml_path):
            raise FileNotFoundError("Archivo no encontrado")

        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Detectar tipo de comprobante para evitar errores si no es PAGO
        tipo = root.get('TipoDeComprobante')
        
        # Extracción básica (Simplificada para el ejemplo, expandible según necesidades)
        emisor = root.find('cfdi:Emisor', self.ns)
        receptor = root.find('cfdi:Receptor', self.ns)
        timbre = root.find('.//tfd:TimbreFiscalDigital', self.ns)
        totales = root.find('.//pago20:Totales', self.ns)
        
        # Si es un PAGO (P), buscamos el nodo Pagos20, si es Ingreso (I), sería diferente.
        # Asumiremos la estructura de tu XML de ejemplo (Pago).
        
        # Manejo de fallos si no encuentra nodos
        uuid = timbre.get('UUID') if timbre is not None else "SIN UUID"
        
        # Extraer total. En Pagos 2.0 es MontoTotalPagos, en Factura normal es Total
        total_raw = "0"
        if totales is not None:
            total_raw = totales.get('MontoTotalPagos')
        elif root.get('Total'):
            total_raw = root.get('Total')

        data = {
            "folio": root.get('Folio', 'S/N'),
            "fecha": root.get('Fecha'),
            "emisor_nombre": emisor.get('Nombre') if emisor is not None else "N/A",
            "emisor_rfc": emisor.get('Rfc') if emisor is not None else "XAXX010101000",
            "receptor_nombre": receptor.get('Nombre') if receptor is not None else "N/A",
            "receptor_rfc": receptor.get('Rfc') if receptor is not None else "XAXX010101000",
            "uuid": uuid,
            "sello": timbre.get('SelloCFD') if timbre is not None else "00000000",
            "total_raw": total_raw,
            "total_fmt": self._format_currency(total_raw)
        }
        
        data['qr_base64'] = self._generate_qr(data)
        return data

    def convert_to_pdf(self, xml_path, output_path):
        data = self.parse_xml(xml_path)
        
        # Plantilla simplificada pero bonita
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body { font-family: sans-serif; padding: 20px; }
                .header { background: #333; color: #fff; padding: 10px; text-align: center; }
                .info { margin-top: 20px; border: 1px solid #ddd; padding: 10px; }
                .row { display: flex; justify-content: space-between; margin-bottom: 5px; }
                .label { font-weight: bold; }
                .total { font-size: 1.5em; text-align: right; margin-top: 20px; color: #0066cc; }
                .qr-box { text-align: center; margin-top: 30px; border-top: 1px dashed #ccc; padding-top: 20px; }
            </style>
        </head>
        <body>
            <div class="header">
                <h2>COMPROBANTE FISCAL DIGITAL</h2>
                <p>Folio: {{ folio }} | Fecha: {{ fecha }}</p>
            </div>
            
            <div class="info">
                <div class="row"><span class="label">Emisor:</span> <span>{{ emisor_nombre }} ({{ emisor_rfc }})</span></div>
                <div class="row"><span class="label">Receptor:</span> <span>{{ receptor_nombre }} ({{ receptor_rfc }})</span></div>
                <div class="row"><span class="label">Folio Fiscal (UUID):</span> <span>{{ uuid }}</span></div>
            </div>

            <div class="total">
                TOTAL: {{ total_fmt }}
            </div>

            <div class="qr-box">
                <img src="data:image/png;base64,{{ qr_base64 }}" width="150">
                <p style="font-size: 10px; color: #777;">Este documento es una representación impresa de un CFDI</p>
            </div>
        </body>
        </html>
        """
        
        content = Template(html).render(data)
        pdfkit.from_string(content, output_path, configuration=self.config)

# ==========================================
# 3. INTERFAZ GRÁFICA (FRONTEND)
# ==========================================
class XMLApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Conversor Masivo XML a PDF")
        self.root.geometry("600x450")
        self.root.configure(bg="#f0f0f0")

        # Instancia del convertidor
        self.converter = CFDIConverter(RUTA_WKHTMLTOPDF)

        # UI Elements
        main_frame = tk.Frame(root, bg="#f0f0f0", padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Título
        lbl_title = tk.Label(main_frame, text="Convertidor XML SAT a PDF", font=("Arial", 16, "bold"), bg="#f0f0f0")
        lbl_title.pack(pady=(0, 20))

        # Botón Seleccionar
        self.btn_select = tk.Button(main_frame, text="📂 Seleccionar Archivos XML", 
                                    command=self.select_files, 
                                    font=("Arial", 12), bg="#007bff", fg="white", height=2, cursor="hand2")
        self.btn_select.pack(fill=tk.X, pady=5)

        # Barra de progreso
        self.progress = ttk.Progressbar(main_frame, orient=tk.HORIZONTAL, length=100, mode='determinate')
        self.progress.pack(fill=tk.X, pady=15)

        # Área de Logs
        lbl_log = tk.Label(main_frame, text="Registro de Actividad:", bg="#f0f0f0", anchor="w")
        lbl_log.pack(fill=tk.X)
        
        self.log_area = scrolledtext.ScrolledText(main_frame, height=10, font=("Consolas", 9))
        self.log_area.pack(fill=tk.BOTH, expand=True)

        # Barra de estado
        self.status_var = tk.StringVar()
        self.status_var.set("Listo para trabajar.")
        lbl_status = tk.Label(main_frame, textvariable=self.status_var, bg="#e0e0e0", anchor="w", relief=tk.SUNKEN)
        lbl_status.pack(side=tk.BOTTOM, fill=tk.X)

    def log(self, message, tag=None):
        self.log_area.insert(tk.END, message + "\n", tag)
        self.log_area.see(tk.END)

    def select_files(self):
        files = filedialog.askopenfilenames(
            title="Seleccionar XMLs",
            filetypes=[("Archivos XML", "*.xml")]
        )
        if files:
            self.start_conversion_thread(files)

    def start_conversion_thread(self, files):
        # Desactivar botón
        self.btn_select.config(state=tk.DISABLED, text="Procesando...")
        self.log_area.delete(1.0, tk.END)
        
        # Iniciar hilo secundario
        thread = threading.Thread(target=self.process_files, args=(files,))
        thread.start()

    def process_files(self, files):
        total = len(files)
        success_count = 0
        
        self.log(f"Iniciando conversión de {total} archivos...")
        
        for i, xml_file in enumerate(files, 1):
            filename = os.path.basename(xml_file)
            folder = os.path.dirname(xml_file)
            pdf_name = os.path.splitext(filename)[0] + ".pdf"
            output_path = os.path.join(folder, pdf_name)

            try:
                self.root.after(0, lambda: self.status_var.set(f"Procesando: {filename}"))
                self.converter.convert_to_pdf(xml_file, output_path)
                
                self.log(f"✅ [OK] {filename} -> Creado", "success")
                success_count += 1
            except Exception as e:
                self.log(f"❌ [ERROR] {filename}: {str(e)}", "error")

            # Actualizar barra de progreso
            progress_val = (i / total) * 100
            self.root.after(0, lambda v=progress_val: self.progress.configure(value=v))

        # Finalizar
        self.root.after(0, lambda: self.finish_process(success_count, total))

    def finish_process(self, success, total):
        self.btn_select.config(state=tk.NORMAL, text="📂 Seleccionar Archivos XML")
        self.status_var.set("Proceso terminado.")
        messagebox.showinfo("Terminado", f"Proceso completo.\nExitosos: {success}\nFallidos: {total - success}")

if __name__ == "__main__":
    root = tk.Tk()
    
    # Configurar colores de tags para el log
    app = XMLApp(root)
    app.log_area.tag_config("success", foreground="green")
    app.log_area.tag_config("error", foreground="red")
    
    root.mainloop()