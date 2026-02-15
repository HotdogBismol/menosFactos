import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
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
# ¡AJUSTA ESTA RUTA SI ES NECESARIO!
RUTA_WKHTMLTOPDF = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ==========================================
# 2. LÓGICA DE NEGOCIO (CONVERTIDOR ROBUSTO)
# ==========================================
class CFDIConverter:
    def __init__(self, wkhtmltopdf_path):
        self.wkhtmltopdf_path = wkhtmltopdf_path
        self.ns = {
            'cfdi': 'http://www.sat.gob.mx/cfd/4',
            'pago20': 'http://www.sat.gob.mx/Pagos20',
            'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'
        }

    def _fmt(self, value):
        """Formato moneda seguro, maneja None y vacíos"""
        if not value:
            return "$0.00"
        try:
            return "${:,.2f}".format(float(value))
        except (ValueError, TypeError):
            return "$0.00"

    def _get_safe(self, obj, attr, default=""):
        if obj is None: return default
        return obj.get(attr, default)

    def _generate_qr(self, uuid, emisor, receptor, total, sello):
        # Aseguramos que el total sea cadena y tenga formato correcto para el QR
        try:
            total_qr = "{:.6f}".format(float(total))
            # El SAT pide formatear ciertos decimales, pero el float estándar suele funcionar para lectura
        except:
            total_qr = "0.000000"

        qr_str = (f"https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?"
                  f"id={uuid}&re={emisor}&rr={receptor}&tt={total_qr}&fe={sello[-8:]}")
        
        qr = qrcode.QRCode(box_size=3, border=1)
        qr.add_data(qr_str)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode()

    def parse_xml(self, xml_path):
        if not os.path.exists(xml_path):
            raise FileNotFoundError(f"Archivo no encontrado: {xml_path}")

        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Nodos principales
        emisor = root.find('cfdi:Emisor', self.ns)
        receptor = root.find('cfdi:Receptor', self.ns)
        timbre = root.find('.//tfd:TimbreFiscalDigital', self.ns)
        
        # --- 1. DATOS GENERALES ---
        tipo_comprobante = self._get_safe(root, 'TipoDeComprobante', 'I')
        
        # --- 2. EXTRACCIÓN DE CONCEPTOS ---
        conceptos = []
        for c in root.findall('.//cfdi:Concepto', self.ns):
            conceptos.append({
                "clave": c.get('ClaveProdServ'),
                "cantidad": c.get('Cantidad'),
                "unidad": c.get('Unidad', c.get('ClaveUnidad')), # Preferir nombre unidad
                "descripcion": c.get('Descripcion'),
                "valor_unitario": self._fmt(c.get('ValorUnitario')),
                "importe": self._fmt(c.get('Importe')),
                "descuento": self._fmt(c.get('Descuento')) if c.get('Descuento') else ""
            })

        # --- 3. EXTRACCIÓN DE COMPLEMENTO DE PAGOS (SOLO SI ES TIPO P) ---
        pagos_data = None
        monto_total_pagos = 0.0
        
        if tipo_comprobante == 'P':
            pagos_node = root.find('.//pago20:Pagos', self.ns)
            if pagos_node is not None:
                pago_elem = pagos_node.find('pago20:Pago', self.ns)
                totales_elem = pagos_node.find('pago20:Totales', self.ns)
                
                # Obtener monto total pagado
                if totales_elem is not None and totales_elem.get('MontoTotalPagos'):
                     monto_total_pagos = float(totales_elem.get('MontoTotalPagos'))
                elif pago_elem is not None and pago_elem.get('Monto'):
                     monto_total_pagos = float(pago_elem.get('Monto'))

                docs = []
                if pago_elem is not None:
                    for doc in pago_elem.findall('pago20:DoctoRelacionado', self.ns):
                        docs.append({
                            "uuid": doc.get('IdDocumento'),
                            "folio": doc.get('Folio', '-'),
                            "moneda": doc.get('MonedaDR'),
                            "saldo_ant": self._fmt(doc.get('ImpSaldoAnt')),
                            "pagado": self._fmt(doc.get('ImpPagado')),
                            "saldo_ins": self._fmt(doc.get('ImpSaldoInsoluto'))
                        })
                    
                    pagos_data = {
                        "fecha": pago_elem.get('FechaPago'),
                        "forma": pago_elem.get('FormaDePagoP'),
                        "moneda": pago_elem.get('MonedaP'),
                        "monto": self._fmt(monto_total_pagos),
                        "docs": docs
                    }

        # --- 4. TOTALES E IMPUESTOS (LÓGICA UNIFICADA) ---
        # Leemos atributos directos del root (para facturas I, E)
        subtotal_raw = self._get_safe(root, 'SubTotal', '0')
        total_raw = self._get_safe(root, 'Total', '0')
        descuento_raw = self._get_safe(root, 'Descuento', '0')
        
        # Impuestos Globales (fuera de conceptos)
        impuestos_node = root.find('cfdi:Impuestos', self.ns)
        traslados_val = 0.0
        retenciones_val = 0.0
        
        if impuestos_node is not None:
            # Buscar traslados
            if impuestos_node.get('TotalImpuestosTrasladados'):
                traslados_val = float(impuestos_node.get('TotalImpuestosTrasladados'))
            
            # Buscar retenciones (Importante para honorarios/fletes)
            if impuestos_node.get('TotalImpuestosRetenidos'):
                retenciones_val = float(impuestos_node.get('TotalImpuestosRetenidos'))

        # Si es PAGO (P), el Total del CFDI suele ser 0, usamos el del complemento
        if tipo_comprobante == 'P':
            total_display = monto_total_pagos
            qr_total = str(monto_total_pagos)
        else:
            total_display = float(total_raw)
            qr_total = total_raw

        data = {
            "general": {
                "serie": self._get_safe(root, 'Serie'),
                "folio": self._get_safe(root, 'Folio'),
                "fecha": self._get_safe(root, 'Fecha'),
                "tipo": tipo_comprobante,
                "moneda": self._get_safe(root, 'Moneda'),
                "metodo_pago": self._get_safe(root, 'MetodoPago', 'N/A'),
                "forma_pago": self._get_safe(root, 'FormaPago', 'N/A'),
                "lugar": self._get_safe(root, 'LugarExpedicion'),
                "uso_cfdi": self._get_safe(receptor, 'UsoCFDI'),
                "regimen_emisor": self._get_safe(emisor, 'RegimenFiscal'),
                "regimen_receptor": self._get_safe(receptor, 'RegimenFiscalReceptor'),
                "cp_receptor": self._get_safe(receptor, 'DomicilioFiscalReceptor')
            },
            "emisor": {
                "nombre": self._get_safe(emisor, 'Nombre'),
                "rfc": self._get_safe(emisor, 'Rfc')
            },
            "receptor": {
                "nombre": self._get_safe(receptor, 'Nombre'),
                "rfc": self._get_safe(receptor, 'Rfc')
            },
            "conceptos": conceptos,
            "pagos": pagos_data,
            "totales": {
                "subtotal": self._fmt(subtotal_raw),
                "descuento": self._fmt(descuento_raw) if float(descuento_raw) > 0 else None,
                "traslados": self._fmt(traslados_val),
                "retenciones": self._fmt(retenciones_val) if retenciones_val > 0 else None,
                "total": self._fmt(total_display)
            },
            "timbre": {
                "uuid": self._get_safe(timbre, 'UUID'),
                "fecha": self._get_safe(timbre, 'FechaTimbrado'),
                "sello_cfd": self._get_safe(timbre, 'SelloCFD', '0'),
                "sello_sat": self._get_safe(timbre, 'SelloSAT'),
                "cert_sat": self._get_safe(timbre, 'NoCertificadoSAT')
            }
        }
        
        # Generar QR
        data['qr'] = self._generate_qr(
            data['timbre']['uuid'], 
            data['emisor']['rfc'], 
            data['receptor']['rfc'], 
            qr_total, 
            data['timbre']['sello_cfd']
        )
        return data

    def get_html(self):
        return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: sans-serif; font-size: 10px; color: #333; margin: 0; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
        th, td { border: 1px solid #ccc; padding: 5px; text-align: left; vertical-align: top; }
        th { background: #f2f2f2; font-weight: bold; font-size: 9px; }
        .header-box { border: 1px solid #333; padding: 10px; margin-bottom: 15px; }
        .title { font-size: 14px; font-weight: bold; color: #004085; }
        .section-header { background: #004085; color: white; padding: 3px; font-weight: bold; margin-top: 10px; margin-bottom: 5px; font-size: 11px; }
        .text-right { text-align: right; }
        .bold { font-weight: bold; }
        .small { font-size: 8px; word-break: break-all; }
        .total-row { font-size: 12px; background: #e9ecef; }
    </style>
</head>
<body>
    <table style="border: none;">
        <tr style="border: none;">
            <td style="border: none; width: 60%;">
                <div class="title">{{ emisor.nombre }}</div>
                <div>RFC: {{ emisor.rfc }}</div>
                <div>Régimen Fiscal: {{ general.regimen_emisor }}</div>
                <div>Lugar de Expedición: {{ general.lugar }}</div>
            </td>
            <td style="border: none; width: 40%; text-align: right;">
                <div class="title">
                    {% if general.tipo == 'P' %} COMPLEMENTO DE PAGO 
                    {% elif general.tipo == 'I' %} FACTURA (INGRESO) 
                    {% elif general.tipo == 'E' %} NOTA DE CRÉDITO (EGRESO)
                    {% else %} CFDI ({{ general.tipo }}) {% endif %}
                </div>
                <div><strong>Folio:</strong> {{ general.serie }} - {{ general.folio }}</div>
                <div><strong>Fecha:</strong> {{ general.fecha }}</div>
                <div><strong>Uso CFDI:</strong> {{ general.uso_cfdi }}</div>
            </td>
        </tr>
    </table>

    <div class="section-header">DATOS DEL RECEPTOR</div>
    <table>
        <tr>
            <td>
                <strong>Cliente:</strong> {{ receptor.nombre }}<br>
                <strong>RFC:</strong> {{ receptor.rfc }}<br>
                <strong>CP:</strong> {{ general.cp_receptor }} | <strong>Régimen:</strong> {{ general.regimen_receptor }}
            </td>
        </tr>
    </table>

    {% if conceptos %}
    <div class="section-header">CONCEPTOS</div>
    <table>
        <thead>
            <tr>
                <th width="10%">Clave</th>
                <th width="10%">Cant/Unidad</th>
                <th>Descripción</th>
                <th width="15%">Valor Unit.</th>
                <th width="15%">Importe</th>
            </tr>
        </thead>
        <tbody>
            {% for c in conceptos %}
            <tr>
                <td>{{ c.clave }}</td>
                <td>{{ c.cantidad }} <br> {{ c.unidad }}</td>
                <td>{{ c.descripcion }}</td>
                <td class="text-right">{{ c.valor_unitario }}</td>
                <td class="text-right">{{ c.importe }}
                    {% if c.descuento %} <br><small>(Desc: {{ c.descuento }})</small> {% endif %}
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% endif %}

    {% if general.tipo == 'P' and pagos %}
    <div class="section-header">DETALLE DEL PAGO</div>
    <table>
        <tr>
            <td><strong>Fecha Pago:</strong> {{ pagos.fecha }}</td>
            <td><strong>Forma:</strong> {{ pagos.forma }}</td>
            <td><strong>Moneda:</strong> {{ pagos.moneda }}</td>
            <td><strong>Monto:</strong> {{ pagos.monto }}</td>
        </tr>
    </table>
    
    {% if pagos.docs %}
    <div class="section-header">DOCUMENTOS PAGADOS</div>
    <table>
        <thead>
            <tr>
                <th>UUID / Folio</th>
                <th>Moneda</th>
                <th class="text-right">Saldo Ant.</th>
                <th class="text-right">Pagado</th>
                <th class="text-right">Insoluto</th>
            </tr>
        </thead>
        <tbody>
            {% for d in pagos.docs %}
            <tr>
                <td>{{ d.uuid }} <br> (Folio: {{ d.folio }})</td>
                <td>{{ d.moneda }}</td>
                <td class="text-right">{{ d.saldo_ant }}</td>
                <td class="text-right">{{ d.pagado }}</td>
                <td class="text-right">{{ d.saldo_ins }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% endif %}
    {% endif %}

    <table style="width: 45%; float: right; margin-top: 10px;">
        {% if general.tipo != 'P' %}
        <tr>
            <td class="text-right"><strong>Subtotal:</strong></td>
            <td class="text-right">{{ totales.subtotal }}</td>
        </tr>
        {% if totales.descuento %}
        <tr>
            <td class="text-right"><strong>Descuento:</strong></td>
            <td class="text-right">- {{ totales.descuento }}</td>
        </tr>
        {% endif %}
        <tr>
            <td class="text-right"><strong>Impuestos Trasladados:</strong></td>
            <td class="text-right">+ {{ totales.traslados }}</td>
        </tr>
        {% if totales.retenciones %}
        <tr>
            <td class="text-right"><strong>Impuestos Retenidos:</strong></td>
            <td class="text-right">- {{ totales.retenciones }}</td>
        </tr>
        {% endif %}
        {% endif %}
        
        <tr class="total-row">
            <td class="text-right bold">TOTAL:</td>
            <td class="text-right bold">{{ totales.total }}</td>
        </tr>
    </table>
    <div style="clear: both;"></div>

    <br><hr><br>

    <table style="border: none;">
        <tr style="border: none;">
            <td style="border: none; width: 20%;">
                <img src="data:image/png;base64,{{ qr }}" width="120">
            </td>
            <td style="border: none; vertical-align: middle;">
                <div class="small">
                    <strong>UUID:</strong> {{ timbre.uuid }}<br>
                    <strong>Certificado SAT:</strong> {{ timbre.cert_sat }}<br>
                    <strong>Fecha Timbrado:</strong> {{ timbre.fecha }}<br><br>
                    <strong>Sello CFDI:</strong> {{ timbre.sello_cfd }}<br><br>
                    <strong>Sello SAT:</strong> {{ timbre.sello_sat }}
                </div>
            </td>
        </tr>
    </table>
    <center class="small">Este documento es una representación impresa de un CFDI 4.0</center>
</body>
</html>
        """

    def convert(self, xml_path, pdf_path):
        data = self.parse_xml(xml_path)
        html = Template(self.get_html()).render(data)
        options = {
            'page-size': 'Letter', 
            'margin-top': '10mm', 'margin-right': '10mm', 
            'margin-bottom': '10mm', 'margin-left': '10mm',
            'encoding': "UTF-8", 'no-outline': None
        }
        config = pdfkit.configuration(wkhtmltopdf=self.wkhtmltopdf_path)
        pdfkit.from_string(html, pdf_path, configuration=config, options=options)

# ==========================================
# 3. INTERFAZ GRÁFICA
# ==========================================
class XMLApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Convertidor Universal CFDI 4.0 a PDF")
        self.root.geometry("650x500")
        
        self.converter = CFDIConverter(RUTA_WKHTMLTOPDF)
        
        frame = tk.Frame(root, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(frame, text="Convertidor Universal XML SAT", font=("Arial", 16, "bold")).pack(pady=10)
        
        btn = tk.Button(frame, text="Seleccionar Archivos XML", bg="#007bff", fg="white", 
                        font=("Arial", 12), command=self.select_files)
        btn.pack(fill=tk.X, pady=10)
        
        self.progress = ttk.Progressbar(frame, mode='determinate')
        self.progress.pack(fill=tk.X, pady=5)
        
        self.log_area = scrolledtext.ScrolledText(frame, height=15)
        self.log_area.pack(fill=tk.BOTH, expand=True)

    def log(self, msg):
        self.log_area.insert(tk.END, msg + "\n")
        self.log_area.see(tk.END)

    def select_files(self):
        files = filedialog.askopenfilenames(filetypes=[("XML", "*.xml")])
        if files:
            threading.Thread(target=self.run, args=(files,)).start()

    def run(self, files):
        total = len(files)
        for i, f in enumerate(files):
            try:
                out = os.path.splitext(f)[0] + ".pdf"
                self.converter.convert(f, out)
                self.log(f"✅ OK: {os.path.basename(f)}")
            except Exception as e:
                self.log(f"❌ ERROR {os.path.basename(f)}: {e}")
            self.progress['value'] = ((i+1)/total)*100
        messagebox.showinfo("Fin", "Proceso terminado")

if __name__ == "__main__":
    root = tk.Tk()
    app = XMLApp(root)
    root.mainloop()