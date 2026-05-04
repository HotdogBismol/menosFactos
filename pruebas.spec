# -*- mode: python ; coding: utf-8 -*-
import glob
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── wkhtmltopdf: incluir exe + todas sus DLLs ────────────────────────────────
WKHTML_DIR   = r'C:\Program Files\wkhtmltopdf\bin'
wkhtml_binaries = []
if os.path.exists(WKHTML_DIR):
    for f in glob.glob(os.path.join(WKHTML_DIR, '*')):
        if os.path.isfile(f):
            wkhtml_binaries.append((f, '.'))   # van a la raíz del bundle
else:
    print(f"\n⚠  ADVERTENCIA: No se encontró wkhtmltopdf en {WKHTML_DIR}")
    print("   Instálalo antes de hacer el build para incluir PDFs en el exe.\n")

# ── Assets del proyecto ───────────────────────────────────────────────────────
project_datas = [
    ('bdChicosMalos',       'bdChicosMalos'),
    ('plantilla.html',      '.'),
    ('estiloPlantilla.css', '.'),
    ('R.png',               '.'),
]

# ── Assets de customtkinter (temas, íconos, fuentes) ─────────────────────────
ctk_datas = collect_data_files('customtkinter')

# ── Assets de satcfdi (base de datos SQLite de catálogos) ─────────────────────
satcfdi_datas = collect_data_files('satcfdi')

# ── Análisis ──────────────────────────────────────────────────────────────────
a = Analysis(
    ['main_gui.py'],
    pathex=['.'],
    binaries=wkhtml_binaries,
    datas=project_datas + ctk_datas + satcfdi_datas,
    hiddenimports=(
        collect_submodules('customtkinter') +
        collect_submodules('satcfdi') +
        ['xml_parser', 'pdf_generator', 'exel_generator', 'sat_downloader',
         'pandas', 'openpyxl', 'jinja2', 'pdfkit', 'qrcode', 'PIL',
         'xml.etree.ElementTree']
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='pruebas',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # Sin ventana de consola negra
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
