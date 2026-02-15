import xml.etree.ElementTree as ET
import qrcode
import base64
from io import BytesIO
import os

class XMLParser:
    def __init__(self):
        self.ns = {
            'cfdi': 'http://www.sat.gob.mx/cfd/4',
            'pago20': 'http://www.sat.gob.mx/Pagos20',
            'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'
        }

    def _fmt(self, value):
        if not value: return "0.00"
        try:
            return "{:,.2f}".format(float(value))
        except:
            return str(value)

    def _get_safe(self, obj, attr, default=""):
        return obj.get(attr, default) if obj is not None else default

    def _generate_qr_base64(self, uuid, emisor, receptor, total, sello):
        try:
            total_qr = "{:.6f}".format(float(total))
        except:
            total_qr = "0.000000"

        qr_str = (f"https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?"
                  f"id={uuid}&re={emisor}&rr={receptor}&tt={total_qr}&fe={sello[-8:]}")
        
        qr = qrcode.QRCode(box_size=4, border=1) # QR más grande para el diseño
        qr.add_data(qr_str)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode()

    def parse(self, xml_path):
        if not os.path.exists(xml_path):
            raise FileNotFoundError(f"Archivo no encontrado: {xml_path}")

        tree = ET.parse(xml_path)
        root = tree.getroot()

        emisor = root.find('cfdi:Emisor', self.ns)
        receptor = root.find('cfdi:Receptor', self.ns)
        timbre = root.find('.//tfd:TimbreFiscalDigital', self.ns)
        tipo_comprobante = self._get_safe(root, 'TipoDeComprobante', 'I')

        # --- CONCEPTOS (Para Ingreso) ---
        conceptos = []
        for c in root.findall('.//cfdi:Concepto', self.ns):
            # Impuestos por concepto para el detalle
            imp_str = ""
            traslados = c.find('.//cfdi:Traslados', self.ns)
            if traslados:
                for t in traslados.findall('cfdi:Traslado', self.ns):
                    tasa = float(t.get('TasaOCuota', 0))
                    imp_str += f"IVA Tasa {tasa:.4f} "

            conceptos.append({
                "cantidad": c.get('Cantidad'),
                "clave_prod": c.get('ClaveProdServ'),
                "clave_uni": c.get('ClaveUnidad'),
                "unidad": c.get('Unidad', ''),
                "no_iden": c.get('NoIdentificacion', ''),
                "descripcion": c.get('Descripcion'),
                "valor_unitario": self._fmt(c.get('ValorUnitario')),
                "importe": self._fmt(c.get('Importe')),
                "descuento": self._fmt(c.get('Descuento')) if c.get('Descuento') else "0.00",
                "impuestos_str": imp_str
            })

        # --- PAGOS (Para Complemento) ---
        pagos_data = None
        monto_pago = 0.0
        
        if tipo_comprobante == 'P':
            pagos_node = root.find('.//pago20:Pagos', self.ns)
            if pagos_node:
                pago = pagos_node.find('pago20:Pago', self.ns)
                totales_pago = pagos_node.find('pago20:Totales', self.ns)
                
                if totales_pago is not None and totales_pago.get('MontoTotalPagos'):
                    monto_pago = float(totales_pago.get('MontoTotalPagos'))
                elif pago is not None and pago.get('Monto'):
                    monto_pago = float(pago.get('Monto'))

                docs = []
                if pago:
                    for d in pago.findall('pago20:DoctoRelacionado', self.ns):
                        docs.append({
                            "uuid": d.get('IdDocumento'),
                            "folio": d.get('Folio', '-'),
                            "moneda": d.get('MonedaDR'),
                            "tc": d.get('EquivalenciaDR', '1'),
                            "saldo_ant": self._fmt(d.get('ImpSaldoAnt')),
                            "pagado": self._fmt(d.get('ImpPagado')),
                            "saldo_ins": self._fmt(d.get('ImpSaldoInsoluto'))
                        })
                    pagos_data = {
                        "fecha": pago.get('FechaPago'),
                        "forma": pago.get('FormaDePagoP'),
                        "moneda": pago.get('MonedaP'),
                        "tc": pago.get('TipoCambioP', '1'),
                        "monto": self._fmt(monto_pago),
                        "docs": docs
                    }

        # --- TOTALES ---
        subtotal_raw = self._get_safe(root, 'SubTotal', '0')
        total_raw = self._get_safe(root, 'Total', '0')
        impuestos = root.find('cfdi:Impuestos', self.ns)
        
        traslados = 0.0
        if impuestos is not None:
            if impuestos.get('TotalImpuestosTrasladados'):
                traslados = float(impuestos.get('TotalImpuestosTrasladados'))
        
        # QR Data Fix
        qr_total_val = str(monto_pago) if tipo_comprobante == 'P' else total_raw

        data = {
            "general": {
                "serie": self._get_safe(root, 'Serie'),
                "folio": self._get_safe(root, 'Folio'),
                "fecha": self._get_safe(root, 'Fecha'),
                "tipo": tipo_comprobante,
                "version": self._get_safe(root, 'Version'),
                "moneda": self._get_safe(root, 'Moneda'),
                "lugar": self._get_safe(root, 'LugarExpedicion'),
                "metodo": self._get_safe(root, 'MetodoPago', 'N/A'),
                "forma": self._get_safe(root, 'FormaPago', 'N/A'),
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
                "traslados": self._fmt(traslados),
                "total": self._fmt(total_raw) if tipo_comprobante != 'P' else self._fmt(monto_pago)
            },
            "timbre": {
                "uuid": self._get_safe(timbre, 'UUID'),
                "fecha": self._get_safe(timbre, 'FechaTimbrado'),
                "sello_cfd": self._get_safe(timbre, 'SelloCFD', '0'),
                "sello_sat": self._get_safe(timbre, 'SelloSAT'),
                "cert_sat": self._get_safe(timbre, 'NoCertificadoSAT'),
                "cert_emisor": self._get_safe(root, 'NoCertificado'),
                "cadena": f"||1.1|{self._get_safe(timbre, 'UUID')}|{self._get_safe(timbre, 'FechaTimbrado')}|{self._get_safe(timbre, 'SelloCFD')}|{self._get_safe(timbre, 'NoCertificadoSAT')}||"
            }
        }

        data['qr'] = self._generate_qr_base64(
            data['timbre']['uuid'],
            data['emisor']['rfc'],
            data['receptor']['rfc'],
            qr_total_val,
            data['timbre']['sello_cfd']
        )
        
        return data
    
    def get_flat_data(self, data, filename):
        """Convierte los datos jerárquicos en filas planas para Excel"""
        rows = []
        
        # Información que se repetirá en todas las filas de este mismo archivo
        base_info = {
            "Archivo": filename,
            "UUID": data["timbre"]["uuid"],
            "Serie": data["general"]["serie"],
            "Folio": data["general"]["folio"],
            "Fecha Emisión": data["general"]["fecha"],
            "Tipo": data["general"]["tipo"],
            "Emisor RFC": data["emisor"]["rfc"],
            "Emisor Nombre": data["emisor"]["nombre"],
            "Receptor RFC": data["receptor"]["rfc"],
            "Receptor Nombre": data["receptor"]["nombre"],
            "Subtotal Total": data["totales"]["subtotal"],
            "IVA Total": data["totales"]["traslados"],
            "Total CFDI": data["totales"]["total"],
        }

        # Si es una FACTURA NORMAL, iteramos por cada concepto
        if data["general"]["tipo"] != 'P' and data.get("conceptos"):
            for c in data["conceptos"]:
                row = base_info.copy()
                row.update({
                    "Concepto Cantidad": c.get("cantidad"),
                    "Concepto Clave": c.get("clave_prod"),
                    "Concepto Unidad": c.get("unidad"),
                    "Concepto Descripción": c.get("descripcion"),
                    "Concepto V.Unitario": c.get("valor_unitario"),
                    "Concepto Importe": c.get("importe"),
                    "Concepto Descuento": c.get("descuento"),
                    "Pago Fecha": "",
                    "Pago Forma": "",
                    "Pago Monto": "",
                    "DocRel UUID": "",
                    "DocRel Folio": "",
                    "DocRel Pagado": ""
                })
                rows.append(row)
                
        # Si es un PAGO, iteramos por cada documento (factura) pagada
        elif data["general"]["tipo"] == 'P' and data.get("pagos") and data["pagos"].get("docs"):
            for d in data["pagos"]["docs"]:
                row = base_info.copy()
                row.update({
                    "Concepto Cantidad": "1",
                    "Concepto Clave": "84111506",
                    "Concepto Unidad": "ACT",
                    "Concepto Descripción": "Pago de Factura",
                    "Concepto V.Unitario": "0.00",
                    "Concepto Importe": "0.00",
                    "Concepto Descuento": "0.00",
                    "Pago Fecha": data["pagos"]["fecha"],
                    "Pago Forma": data["pagos"]["forma"],
                    "Pago Monto": data["pagos"]["monto"],
                    "DocRel UUID": d.get("uuid"),
                    "DocRel Folio": d.get("folio"),
                    "DocRel Pagado": d.get("pagado")
                })
                rows.append(row)
        else:
            # Por si hay algún archivo vacío o anómalo
            rows.append(base_info.copy())
            
        return rows