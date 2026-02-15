import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk
import threading
import os
import logging
import xml.etree.ElementTree as ET
from jinja2 import Template
import pdfkit
import qrcode
import base64
from io import BytesIO

# ==========================================
# 1. CONFIGURACIÓN
# ==========================================
# ¡IMPORTANTE! Verifica que esta ruta sea la correcta en tu PC
RUTA_WKHTMLTOPDF = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'

# Configuración de Logs consola
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ==========================================
# 2. LÓGICA DE NEGOCIO (EL CONVERTIDOR PRO)
# ==========================================
class CFDIConverter:
    def __init__(self, wkhtmltopdf_path):
        self.wkhtmltopdf_path = wkhtmltopdf_path
        # Namespaces oficiales del SAT (CFDI 4.0 y Pagos 2.0)
        self.ns = {
            'cfdi': 'http://www.sat.gob.mx/cfd/4',
            'pago20': 'http://www.sat.gob.mx/Pagos20',
            'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'
        }

    def _format_currency(self, value):
        """Convierte cadenas numéricas a formato moneda: 102759.16 -> $102,759.16"""
        try:
            val_float = float(value)
            return "${:,.2f}".format(val_float)
        except (ValueError, TypeError):
            return "$0.00"

    def _generate_qr(self, data):
        """Genera el código QR en Base64 para incrustar en HTML"""
        # Cadena oficial de verificación del SAT
        # Nota: Usamos el total del XML (que puede ser 0 en Pagos) o el monto del pago
        qr_str = (f"https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?"
                  f"id={data['uuid']}&re={data['emisor_rfc']}&rr={data['receptor_rfc']}"
                  f"&tt={data['total_raw']}&fe={data['sello_cfd'][-8:]}")
        
        qr = qrcode.QRCode(box_size=4, border=1)
        qr.add_data(qr_str)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode()

    def parse_xml(self, xml_path):
        """Extrae y estructura la información del XML"""
        if not os.path.exists(xml_path):
            raise FileNotFoundError(f"No se encontró el archivo: {xml_path}")

        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Función auxiliar segura
        def get_safe(obj, attr, default=""):
            return obj.get(attr) if obj is not None else default

        # Nodos principales
        emisor = root.find('cfdi:Emisor', self.ns)
        receptor = root.find('cfdi:Receptor', self.ns)
        timbre = root.find('.//tfd:TimbreFiscalDigital', self.ns)
        
        # --- LÓGICA DE EXTRACCIÓN MEJORADA (FALLBACK) ---
        pagos_node = root.find('.//pago20:Pagos', self.ns)
        
        # Inicializar variables vacías
        pago = None
        totales = None
        docs_relacionados = []
        
        # Variables para los montos finales (Calculados manualmente si falla el nodo Totales)
        monto_final = 0.0
        iva_final = 0.0
        base_final = 0.0

        if pagos_node is not None:
            pago = pagos_node.find('pago20:Pago', self.ns)
            totales = pagos_node.find('pago20:Totales', self.ns)
            
            # 1. Intentar leer del nodo Totales (Lo ideal)
            if totales is not None:
                monto_final = float(get_safe(totales, 'MontoTotalPagos', 0))
                iva_final = float(get_safe(totales, 'TotalTrasladosImpuestoIVA16', 0))
                base_final = float(get_safe(totales, 'TotalTrasladosBaseIVA16', 0))
            
            # 2. Si Totales falló o dio 0, leer directamente del Pago (Plan B)
            if monto_final == 0 and pago is not None:
                monto_final = float(get_safe(pago, 'Monto', 0))
                # Intentar buscar impuestos dentro del pago si existen
                impuestos_p = pago.find('pago20:ImpuestosP', self.ns)
                if impuestos_p:
                    traslados_p = impuestos_p.find('.//pago20:TrasladoP', self.ns)
                    if traslados_p is not None:
                        iva_final = float(get_safe(traslados_p, 'ImporteP', 0))
                        base_final = float(get_safe(traslados_p, 'BaseP', 0))

            # Lista de documentos relacionados
            if pago is not None:
                for doc in pago.findall('pago20:DoctoRelacionado', self.ns):
                    docs_relacionados.append({
                        "id_documento": doc.get('IdDocumento'),
                        "folio": doc.get('Folio'),
                        "moneda": doc.get('MonedaDR'),
                        "saldo_ant": self._format_currency(doc.get('ImpSaldoAnt')),
                        "pagado": self._format_currency(doc.get('ImpPagado')),
                        "saldo_insoluto": self._format_currency(doc.get('ImpSaldoInsoluto'))
                    })

        data = {
            "folio": root.get('Folio'),
            "serie": root.get('Serie', ''),
            "fecha": root.get('Fecha'),
            "lugar_exp": root.get('LugarExpedicion'),
            "tipo_comprobante": root.get('TipoDeComprobante'),
            "version": root.get('Version'),
            
            # Emisor
            "emisor": {
                "nombre": get_safe(emisor, 'Nombre'),
                "rfc": get_safe(emisor, 'Rfc'),
                "regimen": get_safe(emisor, 'RegimenFiscal')
            },
            
            # Receptor
            "receptor": {
                "nombre": get_safe(receptor, 'Nombre'),
                "rfc": get_safe(receptor, 'Rfc'),
                "domicilio": get_safe(receptor, 'DomicilioFiscalReceptor'),
                "uso_cfdi": get_safe(receptor, 'UsoCFDI'),
                "regimen": get_safe(receptor, 'RegimenFiscalReceptor')
            },
            
            # Datos del Pago
            "pago": {
                "fecha": get_safe(pago, 'FechaPago'),
                "forma": get_safe(pago, 'FormaDePagoP'),
                "moneda": get_safe(pago, 'MonedaP'),
                "monto": self._format_currency(monto_final), # Usamos el calculado
                "tipo_cambio": get_safe(pago, 'TipoCambioP', '1')
            },
            
            # Totales e Impuestos (Usamos los calculados)
            "totales": {
                "total_traslados": self._format_currency(base_final),
                "total_iva": self._format_currency(iva_final),
                "monto_total": self._format_currency(monto_final)
            },

            # Timbre y Certificación
            "timbre": {
                "uuid": get_safe(timbre, 'UUID'),
                "fecha_timbrado": get_safe(timbre, 'FechaTimbrado'),
                "rfc_prov": get_safe(timbre, 'RfcProvCertif'),
                "sello_cfd": get_safe(timbre, 'SelloCFD'),
                "sello_sat": get_safe(timbre, 'SelloSAT'),
                "no_cert_sat": get_safe(timbre, 'NoCertificadoSAT'),
                "no_cert_emisor": root.get('NoCertificado')
            },
            
            "docs_relacionados": docs_relacionados,
            
            # Datos crudos para el QR
            "raw_data": {
                "uuid": get_safe(timbre, 'UUID'),
                "emisor_rfc": get_safe(emisor, 'Rfc'),
                "receptor_rfc": get_safe(receptor, 'Rfc'),
                "total_raw": str(monto_final), # Usamos el monto real del pago, no el Total=0 del CFDI
                "sello_cfd": get_safe(timbre, 'SelloCFD', '00000000')
            }
        }
        
        # Generar QR
        data['qr_img'] = self._generate_qr(data['raw_data'])
        return data

    def get_html_template(self):
        """Retorna la plantilla HTML/CSS profesional"""
        return """
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <style>
                body { font-family: 'Helvetica', 'Arial', sans-serif; font-size: 11px; color: #333; margin: 0; padding: 0; }
                .container { width: 100%; }
                
                table { width: 100%; border-collapse: collapse; margin-bottom: 15px; }
                th, td { border: 1px solid #ccc; padding: 6px; text-align: left; vertical-align: top; }
                th { background-color: #f0f0f0; font-weight: bold; color: #000; font-size: 10px; text-transform: uppercase; }
                .no-border { border: none !important; }
                
                .header-title { font-size: 16px; font-weight: bold; color: #2c3e50; margin-bottom: 5px; }
                .text-right { text-align: right; }
                .text-center { text-align: center; }
                .bold { font-weight: bold; }
                .small { font-size: 9px; }
                .section-title { background-color: #2c3e50; color: white; padding: 4px; font-weight: bold; font-size: 11px; margin-top: 10px; }
                
                .qr-container { width: 18%; float: left; }
                .cadena-container { width: 80%; float: right; font-size: 8px; word-break: break-all; }
                .sello-box { background-color: #f9f9f9; padding: 5px; border: 1px solid #eee; margin-bottom: 5px; }
            </style>
        </head>
        <body>
            <table class="no-border">
                <tr class="no-border">
                    <td class="no-border" width="60%">
                        <div class="header-title">{{ emisor.nombre }}</div>
                        <div><strong>RFC:</strong> {{ emisor.rfc }}</div>
                        <div><strong>Régimen Fiscal:</strong> {{ emisor.regimen }}</div>
                        <div><strong>Lugar de Expedición:</strong> {{ lugar_exp }}</div>
                    </td>
                    <td class="no-border text-right" width="40%">
                        <div class="header-title">COMPLEMENTO DE PAGO</div>
                        <table style="margin-top: 5px;">
                            <tr><th>Folio</th><th>Serie</th><th>Fecha</th></tr>
                            <tr>
                                <td class="text-center">{{ folio }}</td>
                                <td class="text-center">{{ serie }}</td>
                                <td class="text-center">{{ fecha }}</td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>

            <div class="section-title">DATOS DEL CLIENTE (RECEPTOR)</div>
            <table>
                <tr>
                    <td width="50%">
                        <strong>Nombre:</strong> {{ receptor.nombre }}<br>
                        <strong>RFC:</strong> {{ receptor.rfc }}<br>
                        <strong>Domicilio Fiscal:</strong> {{ receptor.domicilio }}
                    </td>
                    <td width="50%">
                        <strong>Uso CFDI:</strong> {{ receptor.uso_cfdi }}<br>
                        <strong>Régimen Fiscal:</strong> {{ receptor.regimen }}
                    </td>
                </tr>
            </table>

            <div class="section-title">INFORMACIÓN DEL PAGO</div>
            <table>
                <thead>
                    <tr>
                        <th>Fecha de Pago</th>
                        <th>Forma de Pago</th>
                        <th>Moneda</th>
                        <th>Tipo Cambio</th>
                        <th>Monto Pagado</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>{{ pago.fecha }}</td>
                        <td>{{ pago.forma }} - Transferencia</td>
                        <td>{{ pago.moneda }}</td>
                        <td>{{ pago.tipo_cambio }}</td>
                        <td class="text-right bold">{{ pago.monto }}</td>
                    </tr>
                </tbody>
            </table>

            <div class="section-title">DOCUMENTOS RELACIONADOS (FACTURAS PAGADAS)</div>
            <table>
                <thead>
                    <tr>
                        <th>UUID Documento</th>
                        <th>Folio</th>
                        <th>Moneda</th>
                        <th class="text-right">Saldo Anterior</th>
                        <th class="text-right">Importe Pagado</th>
                        <th class="text-right">Saldo Insoluto</th>
                    </tr>
                </thead>
                <tbody>
                    {% for doc in docs_relacionados %}
                    <tr>
                        <td class="small">{{ doc.id_documento }}</td>
                        <td class="text-center">{{ doc.folio }}</td>
                        <td class="text-center">{{ doc.moneda }}</td>
                        <td class="text-right">{{ doc.saldo_ant }}</td>
                        <td class="text-right">{{ doc.pagado }}</td>
                        <td class="text-right">{{ doc.saldo_insoluto }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>

            <table style="width: 40%; float: right;">
                <tr>
                    <th class="text-right">Subtotal Base IVA 16%:</th>
                    <td class="text-right">{{ totales.total_traslados }}</td>
                </tr>
                <tr>
                    <th class="text-right">IVA 16%:</th>
                    <td class="text-right">{{ totales.total_iva }}</td>
                </tr>
                <tr>
                    <th class="text-right" style="background-color: #333; color: white;">TOTAL PAGADO:</th>
                    <td class="text-right bold">{{ totales.monto_total }}</td>
                </tr>
            </table>
            <div style="clear: both;"></div>

            <br><hr><br>

            <div>
                <div class="qr-container">
                    <img src="data:image/png;base64,{{ qr_img }}" style="width: 100%;">
                </div>
                <div class="cadena-container">
                    <div class="sello-box">
                        <strong>Folio Fiscal (UUID):</strong> {{ timbre.uuid }} <br>
                        <strong>No. Serie Certificado SAT:</strong> {{ timbre.no_cert_sat }} <br>
                        <strong>Fecha y Hora de Certificación:</strong> {{ timbre.fecha_timbrado }}
                    </div>
                    
                    <strong>Sello Digital del CFDI:</strong>
                    <div class="small">{{ timbre.sello_cfd }}</div>
                    <br>
                    <strong>Sello del SAT:</strong>
                    <div class="small">{{ timbre.sello_sat }}</div>
                    <br>
                    <div class="text-center bold">ESTE DOCUMENTO ES UNA REPRESENTACIÓN IMPRESA DE UN CFDI VERSIÓN 4.0</div>
                </div>
            </div>
        </body>
        </html>
        """

    def convert(self, xml_file, output_pdf):
        """Método principal para ejecutar la conversión"""
        logging.info(f"Procesando archivo: {xml_file}")
        try:
            data = self.parse_xml(xml_file)
        except Exception as e:
            logging.error(f"Error al leer XML: {e}")
            raise e

        template_str = self.get_html_template()
        html_content = Template(template_str).render(data)

        options = {
            'page-size': 'Letter',
            'margin-top': '0.75in',
            'margin-right': '0.75in',
            'margin-bottom': '0.75in',
            'margin-left': '0.75in',
            'encoding': "UTF-8",
            'no-outline': None
        }
        
        config = pdfkit.configuration(wkhtmltopdf=self.wkhtmltopdf_path)
        pdfkit.from_string(html_content, output_pdf, configuration=config, options=options)
        logging.info(f"✅ PDF Generado exitosamente: {output_pdf}")

# ==========================================
# 3. INTERFAZ GRÁFICA (FRONTEND)
# ==========================================
class XMLApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Conversor PRO: XML SAT a PDF")
        self.root.geometry("700x500")
        self.root.configure(bg="#2c3e50")
        self.converter = CFDIConverter(RUTA_WKHTMLTOPDF)

        main_frame = tk.Frame(root, bg="#ecf0f1", padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        lbl_title = tk.Label(main_frame, text="Generador de Recibos de Pago (SAT 4.0)", 
                             font=("Segoe UI", 16, "bold"), bg="#ecf0f1", fg="#2c3e50")
        lbl_title.pack(pady=(0, 20))

        self.btn_select = tk.Button(main_frame, text="📂 Seleccionar XMLs de Pagos", 
                                    command=self.select_files, 
                                    font=("Segoe UI", 11), bg="#2980b9", fg="white", 
                                    height=2, width=30, cursor="hand2", borderwidth=0)
        self.btn_select.pack(pady=5)

        self.progress = ttk.Progressbar(main_frame, orient=tk.HORIZONTAL, length=100, mode='determinate')
        self.progress.pack(fill=tk.X, pady=15)

        lbl_log = tk.Label(main_frame, text="Bitácora de Procesamiento:", bg="#ecf0f1", anchor="w", font=("Segoe UI", 9, "bold"))
        lbl_log.pack(fill=tk.X)
        
        self.log_area = scrolledtext.ScrolledText(main_frame, height=12, font=("Consolas", 9), state='normal')
        self.log_area.pack(fill=tk.BOTH, expand=True)

        self.status_var = tk.StringVar()
        self.status_var.set("Esperando archivos...")
        lbl_status = tk.Label(main_frame, textvariable=self.status_var, bg="#bdc3c7", anchor="w", padx=10)
        lbl_status.pack(side=tk.BOTTOM, fill=tk.X)

    def log(self, message, tag=None):
        self.log_area.insert(tk.END, message + "\n", tag)
        self.log_area.see(tk.END)

    def select_files(self):
        files = filedialog.askopenfilenames(title="Seleccionar Complementos de Pago XML", filetypes=[("Archivos XML", "*.xml")])
        if files:
            self.start_conversion_thread(files)

    def start_conversion_thread(self, files):
        self.btn_select.config(state=tk.DISABLED, text="Procesando...", bg="#7f8c8d")
        self.log_area.delete(1.0, tk.END)
        self.progress['value'] = 0
        thread = threading.Thread(target=self.process_files, args=(files,))
        thread.start()

    def process_files(self, files):
        total = len(files)
        success_count = 0
        self.log(f"--- Iniciando lote de {total} archivos ---")
        
        for i, xml_file in enumerate(files, 1):
            filename = os.path.basename(xml_file)
            folder = os.path.dirname(xml_file)
            pdf_name = os.path.splitext(filename)[0] + ".pdf"
            output_path = os.path.join(folder, pdf_name)

            try:
                self.root.after(0, lambda: self.status_var.set(f"Procesando ({i}/{total}): {filename}"))
                self.converter.convert(xml_file, output_path)
                self.log(f"✅ [OK] {filename}", "success")
                success_count += 1
            except Exception as e:
                self.log(f"❌ [ERROR] {filename}: {str(e)}", "error")

            progress_val = (i / total) * 100
            self.root.after(0, lambda v=progress_val: self.progress.configure(value=v))

        self.root.after(0, lambda: self.finish_process(success_count, total))

    def finish_process(self, success, total):
        self.btn_select.config(state=tk.NORMAL, text="📂 Seleccionar XMLs de Pagos", bg="#2980b9")
        self.status_var.set("Proceso terminado.")
        messagebox.showinfo("Reporte Final", f"Proceso completo.\n\nExitosos: {success}\nFallidos: {total - success}")

if __name__ == "__main__":
    root = tk.Tk()
    app = XMLApp(root)
    app.log_area.tag_config("success", foreground="green")
    app.log_area.tag_config("error", foreground="red")
    root.mainloop()