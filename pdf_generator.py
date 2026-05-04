from jinja2 import Environment, FileSystemLoader
import pdfkit
import sys
from pathlib import Path

# Compatibilidad con PyInstaller (--onefile)
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent


class PDFGenerator:
    def __init__(self, wkhtmltopdf_path):
        self.wkhtmltopdf_path = wkhtmltopdf_path

    def generate(self, data, output_path):
        # --- CSS ---
        css_path = BASE_DIR / 'estiloPlantilla.css'
        try:
            css_text = css_path.read_text(encoding='utf-8')
        except FileNotFoundError:
            raise FileNotFoundError(f"No se encontró el archivo de estilos: {css_path}")
        except Exception as e:
            raise RuntimeError(f"Error leyendo estiloPlantilla.css: {e}")

        data['css_contenido'] = css_text

        # --- Logo: ruta URI para wkhtmltopdf en Windows ---
        logo_path = BASE_DIR / 'R.png'
        data['ruta_logo'] = logo_path.as_uri()

        # --- Plantilla Jinja2 con ruta absoluta ---
        env = Environment(loader=FileSystemLoader(str(BASE_DIR)))
        template = env.get_template('plantilla.html')
        html_content = template.render(data)

        # --- Opciones de PDF ---
        options = {
            'page-size':      'Letter',
            'margin-top':     '10mm',
            'margin-right':   '10mm',
            'margin-bottom':  '10mm',
            'margin-left':    '10mm',
            'encoding':       'UTF-8',
            'no-outline':     None,
            'enable-local-file-access': None,
        }

        config = pdfkit.configuration(wkhtmltopdf=self.wkhtmltopdf_path)
        pdfkit.from_string(html_content, output_path,
                           configuration=config, options=options)
