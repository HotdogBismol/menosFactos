from jinja2 import Environment, FileSystemLoader
import pdfkit
import os
import pathlib  # <--- AGREGAMOS ESTA LIBRERÍA

class PDFGenerator:
    def __init__(self, wkhtmltopdf_path):
        self.wkhtmltopdf_path = wkhtmltopdf_path
        
    def generate(self, data, output_path):
        # 1. Leer CSS
        css_text = ""
        try:
            with open('estiloPlantilla.css', 'r', encoding='utf-8') as f:
                css_text = f.read()
        except:
            pass
        data['css_contenido'] = css_text

        # --- CORRECCIÓN DEL ERROR DE IMAGEN ---
        # Obtenemos la ruta absoluta
        abs_path = os.path.abspath("R.png")
        
        # La convertimos a formato URI (file:///C:/...)
        # Esto satisface al motor de wkhtmltopdf en Windows
        ruta_logo = pathlib.Path(abs_path).as_uri()
        
        data['ruta_logo'] = ruta_logo 
        # --------------------------------------------------

        # 3. Configurar Jinja2
        file_loader = FileSystemLoader('.')
        env = Environment(loader=file_loader)
        template = env.get_template('plantilla.html')

        # 4. Renderizar
        html_content = template.render(data)
        
        # 5. Configurar PDFKit
        options = {
            'page-size': 'Letter', 
            'margin-top': '10mm', 'margin-right': '10mm', 
            'margin-bottom': '10mm', 'margin-left': '10mm',
            'encoding': "UTF-8", 
            'no-outline': None,
            'enable-local-file-access': None 
        }
        
        config = pdfkit.configuration(wkhtmltopdf=self.wkhtmltopdf_path)
        pdfkit.from_string(html_content, output_path, configuration=config, options=options)