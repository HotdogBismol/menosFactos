import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import os
import sys
import json
from datetime import date, timedelta, datetime
from pathlib import Path
import pandas as pd

from xml_parser import XMLParser
from pdf_generator import PDFGenerator
from exel_generator import ExcelGenerator

try:
    from sat_downloader import DescargadorSAT, SAT_DISPONIBLE
except ImportError:
    SAT_DISPONIBLE = False
    DescargadorSAT = None

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Cuando corre como .exe empaquetado, los assets están en sys._MEIPASS
# El config.json y la carpeta descargas van junto al .exe
def _asset_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent

def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent

ASSET_DIR   = _asset_dir()   # plantilla, CSS, logo, CSV  (bundled read-only)
APP_DIR     = _app_dir()     # config.json, descargas/     (junto al .exe)
BASE_DIR    = ASSET_DIR      # compatibilidad con pdf_generator
CONFIG_PATH = APP_DIR / "config.json"


def load_config():
    d = {"wkhtmltopdf_path": r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                d.update(json.load(f))
        except Exception:
            pass
    return d


def get_wkhtmltopdf_path() -> str:
    """Cuando corre como .exe, usa el binario embebido. En desarrollo, usa el config."""
    if getattr(sys, "frozen", False):
        bundled = ASSET_DIR / "wkhtmltopdf.exe"
        if bundled.exists():
            return str(bundled)
    return load_config().get("wkhtmltopdf_path",
                             r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe")


def save_config(c):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2, ensure_ascii=False)


# =============================================================================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("xmlApedefe")
        self.geometry("1080x720")
        self.minsize(860, 580)
        self.state("zoomed")   # maximizado al abrir

        self.config_data  = load_config()
        self._cancel      = threading.Event()
        self._processing  = False
        self._descargador = None

        self.efos_dict = self._load_efos()
        self.parser    = XMLParser()
        self.pdf_gen   = PDFGenerator(get_wkhtmltopdf_path())
        self.excel_gen = ExcelGenerator()

        self._build_menu()
        self._build_layout()
        self.after(400, self._check_wkhtmltopdf)

    # ── Datos ─────────────────────────────────────────────────────────────────
    def _load_efos(self):
        ruta = ASSET_DIR / "bdChicosMalos" / "Listado_Completo_69-B.csv"
        efos = {}
        if ruta.exists():
            try:
                df = pd.read_csv(ruta, skiprows=2, encoding="latin1")
                for _, row in df.iterrows():
                    efos[str(row["RFC"]).strip()] = str(row["Situación del contribuyente"]).strip()
            except Exception as e:
                print(f"EFOS error: {e}")
        return efos

    def _check_wkhtmltopdf(self):
        p = self.config_data.get("wkhtmltopdf_path", "")
        if not os.path.exists(p):
            if messagebox.askyesno("wkhtmltopdf no encontrado",
                                   "¿Deseas localizarlo manualmente?\n(Sin él no se generan PDFs)"):
                self._config_wkhtmltopdf()

    # ── Menú ──────────────────────────────────────────────────────────────────
    def _build_menu(self):
        mb = tk.Menu(self)
        self.configure(menu=mb)

        m = tk.Menu(mb, tearoff=0)
        mb.add_cascade(label="Archivo", menu=m)
        m.add_command(label="Seleccionar XMLs…", command=self.select_files)
        m.add_separator()
        m.add_command(label="Salir", command=self.quit)

        m2 = tk.Menu(mb, tearoff=0)
        mb.add_cascade(label="Herramientas", menu=m2)
        # Solo mostrar la opción de wkhtmltopdf cuando NO corre como .exe (no está embebido)
        if not getattr(sys, "frozen", False):
            m2.add_command(label="Configurar wkhtmltopdf…", command=self._config_wkhtmltopdf)
        m2.add_command(label="Actualizar lista EFOS…", command=lambda: messagebox.showinfo(
            "EFOS", f"Reemplaza:\n{BASE_DIR / 'bdChicosMalos' / 'Listado_Completo_69-B.csv'}"))

        m3 = tk.Menu(mb, tearoff=0)
        mb.add_cascade(label="Ayuda", menu=m3)
        m3.add_command(label="Acerca de…", command=lambda: messagebox.showinfo(
            "Acerca de", "xmlApedefe v1.1\nConvertidor, validador y descargador de CFDIs."))

    def _config_wkhtmltopdf(self):
        p = filedialog.askopenfilename(
            title="Seleccionar wkhtmltopdf.exe",
            filetypes=[("Ejecutable", "*.exe"), ("Todos", "*.*")])
        if p:
            self.config_data["wkhtmltopdf_path"] = p
            save_config(self.config_data)
            self.pdf_gen = PDFGenerator(p)
            messagebox.showinfo("Guardado", f"Ruta guardada:\n{p}")

    # ── Layout ────────────────────────────────────────────────────────────────
    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()

        content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        self._content = content

        self._page_conv = ctk.CTkFrame(content, corner_radius=0, fg_color="transparent")
        self._page_sat  = ctk.CTkFrame(content, corner_radius=0, fg_color="transparent")

        self._build_conv_page()
        self._build_sat_page()

        # Status bar
        sb = ctk.CTkFrame(self, height=26, corner_radius=0, fg_color=("gray85", "gray13"))
        sb.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._status = tk.StringVar(value="Listo.")
        ctk.CTkLabel(sb, textvariable=self._status, font=("Segoe UI", 10),
                     text_color=("gray40", "gray55"), anchor="w").pack(side="left", padx=14, pady=3)

        self._show("conv")

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=215, corner_radius=0, fg_color=("gray88", "gray12"))
        sb.grid(row=0, column=0, rowspan=2, sticky="nsew")
        sb.grid_propagate(False)

        # Logo
        lf = ctk.CTkFrame(sb, fg_color="transparent")
        lf.pack(padx=18, pady=(22, 8))
        ctk.CTkLabel(lf, text="xml", font=("Segoe UI", 22, "bold"),
                     text_color=("#1D4ED8", "#60A5FA")).pack(side="left")
        ctk.CTkLabel(lf, text="Apedefe", font=("Segoe UI", 22),
                     text_color=("gray35", "gray75")).pack(side="left")

        ctk.CTkFrame(sb, height=1, fg_color=("gray75", "gray22")).pack(fill="x", padx=14, pady=4)

        ctk.CTkLabel(sb, text="NAVEGACIÓN", font=("Segoe UI", 9, "bold"),
                     text_color=("gray55", "gray50"), anchor="w").pack(fill="x", padx=18, pady=(10, 4))

        self._btn_conv = ctk.CTkButton(
            sb, text="📄  Convertidor", anchor="w",
            fg_color="transparent", hover_color=("gray78", "gray22"),
            text_color=("gray15", "gray85"), font=("Segoe UI", 13),
            corner_radius=8, height=42, command=lambda: self._show("conv"))
        self._btn_conv.pack(fill="x", padx=10, pady=2)

        self._btn_sat = ctk.CTkButton(
            sb, text="⬇  Descargador SAT", anchor="w",
            fg_color="transparent", hover_color=("gray78", "gray22"),
            text_color=("gray15", "gray85"), font=("Segoe UI", 13),
            corner_radius=8, height=42, command=lambda: self._show("sat"))
        self._btn_sat.pack(fill="x", padx=10, pady=2)

        # EFOS badge
        ef = ctk.CTkFrame(sb, corner_radius=10, fg_color=("gray80", "gray18"))
        ef.pack(side="bottom", fill="x", padx=12, pady=14)
        if self.efos_dict:
            ctk.CTkLabel(ef, text="✓  Lista EFOS", font=("Segoe UI", 11, "bold"),
                         text_color="#22C55E").pack(pady=(12, 2))
            ctk.CTkLabel(ef, text=f"{len(self.efos_dict):,} registros",
                         font=("Segoe UI", 9), text_color=("gray50", "gray55")).pack(pady=(0, 12))
        else:
            ctk.CTkLabel(ef, text="✗  Lista EFOS", font=("Segoe UI", 11, "bold"),
                         text_color="#EF4444").pack(pady=(12, 2))
            ctk.CTkLabel(ef, text="No encontrada",
                         font=("Segoe UI", 9), text_color=("gray50", "gray55")).pack(pady=(0, 12))

    def _show(self, page):
        self._page_conv.grid_forget()
        self._page_sat.grid_forget()
        sel  = ("#DBEAFE", "#1E3A5F")
        norm = "transparent"
        st   = ("#1D4ED8", "#60A5FA")
        nt   = ("gray15", "gray85")
        if page == "conv":
            self._page_conv.grid(row=0, column=0, sticky="nsew")
            self._btn_conv.configure(fg_color=sel, text_color=st)
            self._btn_sat.configure(fg_color=norm, text_color=nt)
        else:
            self._page_sat.grid(row=0, column=0, sticky="nsew")
            self._btn_sat.configure(fg_color=sel, text_color=st)
            self._btn_conv.configure(fg_color=norm, text_color=nt)

    # =========================================================================
    # PÁGINA CONVERTIDOR
    # =========================================================================
    def _build_conv_page(self):
        p = self._page_conv
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(1, weight=1)

        # Controls card (row 0)
        cc = ctk.CTkFrame(p, corner_radius=14)
        cc.grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 0))

        title_row = ctk.CTkFrame(cc, fg_color="transparent")
        title_row.pack(fill="x", padx=18, pady=(16, 10))
        ctk.CTkLabel(title_row, text="Convertidor & Validador",
                     font=("Segoe UI", 18, "bold")).pack(side="left")

        btn_row = ctk.CTkFrame(cc, fg_color="transparent")
        btn_row.pack(fill="x", padx=18, pady=(0, 10))

        self.btn_select = ctk.CTkButton(
            btn_row, text="📂  Seleccionar XMLs",
            font=("Segoe UI", 12, "bold"), height=38, corner_radius=8,
            command=self.select_files)
        self.btn_select.pack(side="left")

        self.btn_cancel = ctk.CTkButton(
            btn_row, text="✖  Cancelar",
            font=("Segoe UI", 12, "bold"), height=38, corner_radius=8,
            fg_color="#EF4444", hover_color="#DC2626", state="disabled",
            command=self._cancelar)
        self.btn_cancel.pack(side="left", padx=(10, 0))

        self._prog_lbl = ctk.CTkLabel(btn_row, text="",
                                      font=("Segoe UI", 11),
                                      text_color=("gray50", "gray55"))
        self._prog_lbl.pack(side="right")

        self.progress = ctk.CTkProgressBar(cc, height=6, corner_radius=3)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=18, pady=(0, 16))

        # Log card (row 1)
        lc = ctk.CTkFrame(p, corner_radius=14)
        lc.grid(row=1, column=0, sticky="nsew", padx=22, pady=(10, 18))
        lc.grid_columnconfigure(0, weight=1)
        lc.grid_rowconfigure(1, weight=1)

        lh = ctk.CTkFrame(lc, fg_color="transparent", height=46)
        lh.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 0))
        lh.grid_propagate(False)
        ctk.CTkLabel(lh, text="Bitácora",
                     font=("Segoe UI", 13, "bold")).pack(side="left", pady=10)
        ctk.CTkButton(lh, text="Limpiar", width=72, height=28, corner_radius=6,
                      fg_color=("gray80", "gray25"), hover_color=("gray70", "gray30"),
                      text_color=("gray30", "gray70"), font=("Segoe UI", 10),
                      command=lambda: self.log_area.delete(1.0, tk.END)
                      ).pack(side="right", pady=9)

        lw = ctk.CTkFrame(lc, fg_color="transparent")
        lw.grid(row=1, column=0, sticky="nsew", padx=4, pady=(4, 4))
        lw.grid_columnconfigure(0, weight=1)
        lw.grid_rowconfigure(0, weight=1)

        log_bg = "#1E1E1E"
        log_fg = "#D4D4D4"
        self.log_area = tk.Text(lw, font=("Consolas", 9), bg=log_bg, fg=log_fg,
                                relief=tk.FLAT, padx=14, pady=10,
                                insertbackground=log_fg, selectbackground="#3B82F6",
                                bd=0, wrap=tk.WORD)
        self.log_area.grid(row=0, column=0, sticky="nsew")
        vsb = ctk.CTkScrollbar(lw, command=self.log_area.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.log_area.configure(yscrollcommand=vsb.set)

        for tag, fg, bold in [
            ("success", "#22C55E", False),
            ("error",   "#EF4444", True),
            ("warning", "#F59E0B", True),
            ("info",    "#60A5FA", False),
            ("muted",   "#64748B", False),
            ("header",  "#F1F5F9", True),
        ]:
            self.log_area.tag_config(tag, foreground=fg,
                                     font=("Consolas", 9, "bold") if bold else ("Consolas", 9))

    # ── Thread-safe helpers ───────────────────────────────────────────────────
    def log(self, msg, tag=None):
        self.after(0, lambda: (self.log_area.insert(tk.END, msg + "\n", tag),
                               self.log_area.see(tk.END)))

    def _set_prog(self, v, label=""):
        self.after(0, lambda: (self.progress.set(v / 100),
                               self._prog_lbl.configure(text=label)))

    def _set_status(self, t):
        self.after(0, lambda: self._status.set(t))

    def _cancelar(self):
        self._cancel.set()
        self._set_status("Cancelando…")
        self.log("⏹  Cancelado por el usuario.", "warning")

    # ── Lógica convertidor ────────────────────────────────────────────────────
    def select_files(self):
        if self._processing:
            return
        files = filedialog.askopenfilenames(
            title="Seleccionar XMLs CFDI",
            filetypes=[("XML", "*.xml"), ("Todos", "*.*")])
        if not files:
            return
        self._cancel.clear()
        self._processing = True
        self.after(0, lambda: (
            self.btn_select.configure(state="disabled"),
            self.btn_cancel.configure(state="normal"),
            self.progress.set(0),
            self._prog_lbl.configure(text="")))
        threading.Thread(target=self._run, args=(files,), daemon=True).start()

    def _run(self, files):
        total = len(files)
        ok = err = alerts = 0
        rows = []

        self.log(f"{'─' * 58}", "muted")
        self.log(f"  Lote: {total} archivo(s)", "header")
        self.log(f"{'─' * 58}\n", "muted")

        for i, path in enumerate(files):
            if self._cancel.is_set():
                break
            name     = os.path.basename(path)
            pdf_path = os.path.splitext(path)[0] + ".pdf"
            self._set_status(f"Procesando {i + 1}/{total}: {name}")

            try:
                data      = self.parser.parse(path)
                rfc       = data["emisor"]["rfc"]
                es_efos   = rfc in self.efos_dict
                situacion = self.efos_dict.get(rfc, "Limpio")

                if es_efos:
                    alerts += 1
                    self.log(f"  ⚠  {name}", "warning")
                    self.log(f"     RFC {rfc} en Lista 69-B → {situacion}", "error")
                else:
                    self.log(f"  ✓  {name}", "success")

                try:
                    self.pdf_gen.generate(data, pdf_path)
                except Exception as e:
                    self.log(f"     PDF: {e}", "error")

                for row in self.parser.get_flat_data(data, name):
                    row["Alerta EFOS (Lista 69-B)"] = "SÍ" if es_efos else "NO"
                    row["Situación EFOS"]            = situacion
                    rows.append(row)
                ok += 1

            except Exception as e:
                err += 1
                self.log(f"  ✗  {name}: {e}", "error")

            self._set_prog(((i + 1) / total) * 100, f"{i + 1}/{total}")

        if rows:
            out = os.path.dirname(files[0])
            xls = os.path.join(out, f"Reporte_CFDI_{date.today():%Y%m%d}.xlsx")
            try:
                self.excel_gen.generate(rows, xls)
                self.log(f"\n  📊  {os.path.basename(xls)}", "info")
                self.log(f"      {xls}", "muted")
            except PermissionError as e:
                self.log(f"\n  ✗  {e}", "error")
            except Exception as e:
                self.log(f"\n  ✗  Excel: {e}", "error")

        self.log(f"\n{'─' * 58}", "muted")
        res = f"  Resumen: {ok} OK"
        if err:    res += f"  |  {err} error(es)"
        if alerts: res += f"  |  {alerts} alerta(s) EFOS"
        self.log(res, "header")
        self.log(f"{'─' * 58}\n", "muted")
        self._set_status(f"Completado — {ok}/{total} OK, {alerts} alertas")

        def _done():
            self.btn_select.configure(state="normal")
            self.btn_cancel.configure(state="disabled")
            self._processing = False
            if not self._cancel.is_set():
                messagebox.showinfo("Listo",
                    f"{'⚠️' if alerts else '✅'} {ok}/{total} procesados\n"
                    f"Errores: {err}   Alertas EFOS: {alerts}")

        self.after(0, _done)

    # =========================================================================
    # PÁGINA SAT
    # =========================================================================
    def _build_sat_page(self):
        p = self._page_sat
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(p, text="Descargador SAT",
                     font=("Segoe UI", 18, "bold")).grid(
            row=0, column=0, sticky="w", padx=22, pady=(20, 0))

        if not SAT_DISPONIBLE:
            nc = ctk.CTkFrame(p, corner_radius=14)
            nc.grid(row=1, column=0, sticky="ew", padx=22, pady=10)
            ctk.CTkLabel(nc, text="⚠  Módulo satcfdi no instalado",
                         font=("Segoe UI", 14, "bold"), text_color="#F59E0B").pack(pady=(20, 4))
            ctk.CTkLabel(nc, text="pip install satcfdi",
                         font=("Consolas", 12),
                         text_color=("gray50", "gray60")).pack(pady=(0, 20))
            return

        # Fila superior: FIEL | Parámetros
        top = ctk.CTkFrame(p, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", padx=22, pady=(8, 0))
        top.grid_columnconfigure((0, 1), weight=1)

        self._build_fiel_card(top)
        self._build_params_card(top)
        self._build_sat_log(p)

    def _build_fiel_card(self, parent):
        card = ctk.CTkFrame(parent, corner_radius=14)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        ctk.CTkLabel(card, text="🔑  FIEL / e.firma",
                     font=("Segoe UI", 13, "bold"), anchor="w").pack(
            fill="x", padx=18, pady=(16, 10))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=(0, 16))

        ctk.CTkLabel(body, text="RFC", anchor="w", font=("Segoe UI", 11)).pack(fill="x", pady=(0, 2))
        self.sat_rfc = ctk.CTkEntry(body, placeholder_text="XAXX010101000",
                                    height=36, corner_radius=8)
        self.sat_rfc.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(body, text="Contraseña", anchor="w", font=("Segoe UI", 11)).pack(fill="x", pady=(0, 2))
        self.sat_pwd = ctk.CTkEntry(body, placeholder_text="••••••••",
                                    show="●", height=36, corner_radius=8)
        self.sat_pwd.pack(fill="x", pady=(0, 10))

        self.sat_cer = self._file_entry(body, "Archivo .cer", "*.cer")
        self.sat_key = self._file_entry(body, "Archivo .key", "*.key")

        br = ctk.CTkFrame(body, fg_color="transparent")
        br.pack(fill="x", pady=(8, 0))
        self.btn_conectar = ctk.CTkButton(
            br, text="🔌  Conectar al SAT",
            height=36, corner_radius=8, command=self._sat_conectar)
        self.btn_conectar.pack(side="left")
        self.lbl_conexion = ctk.CTkLabel(br, text="Sin conectar",
                                         font=("Segoe UI", 11),
                                         text_color=("gray50", "gray55"))
        self.lbl_conexion.pack(side="left", padx=12)

    def _file_entry(self, parent, label, ext):
        ctk.CTkLabel(parent, text=label, anchor="w",
                     font=("Segoe UI", 11)).pack(fill="x", pady=(0, 2))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 10))
        e = ctk.CTkEntry(row, height=36, corner_radius=8)
        e.pack(side="left", fill="x", expand=True)
        def _browse():
            p = filedialog.askopenfilename(filetypes=[(ext, ext), ("Todos", "*.*")])
            if p:
                e.delete(0, tk.END)
                e.insert(0, p)
        ctk.CTkButton(row, text="…", width=36, height=36, corner_radius=8,
                      command=_browse, fg_color=("gray80", "gray25"),
                      hover_color=("gray70", "gray30"),
                      text_color=("gray20", "gray85")).pack(side="left", padx=(6, 0))
        return e

    def _build_params_card(self, parent):
        card = ctk.CTkFrame(parent, corner_radius=14)
        card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        ctk.CTkLabel(card, text="📅  Parámetros de descarga",
                     font=("Segoe UI", 13, "bold"), anchor="w").pack(
            fill="x", padx=18, pady=(16, 10))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=(0, 16))

        hoy    = date.today()
        hace30 = hoy - timedelta(days=30)

        def date_entry(lbl, default):
            ctk.CTkLabel(body, text=lbl, anchor="w",
                         font=("Segoe UI", 11)).pack(fill="x", pady=(0, 2))
            e = ctk.CTkEntry(body, placeholder_text="dd/mm/aaaa",
                             height=36, corner_radius=8)
            e.insert(0, default.strftime("%d/%m/%Y"))
            e.pack(fill="x", pady=(0, 10))
            return e

        self.sat_fi = date_entry("Fecha inicio:", hace30)
        self.sat_ff = date_entry("Fecha fin:",    hoy)

        ctk.CTkLabel(body, text="Tipo de CFDIs:", anchor="w",
                     font=("Segoe UI", 11)).pack(fill="x", pady=(0, 6))
        self.sat_tipo = tk.StringVar(value="ambos")
        for val, txt in [("emitidos", "Emitidos"), ("recibidos", "Recibidos"), ("ambos", "Ambos")]:
            ctk.CTkRadioButton(body, text=txt, variable=self.sat_tipo,
                               value=val, font=("Segoe UI", 11)).pack(anchor="w", pady=2)

        ctk.CTkLabel(body, text="Carpeta destino:", anchor="w",
                     font=("Segoe UI", 11)).pack(fill="x", pady=(12, 2))
        dr = ctk.CTkFrame(body, fg_color="transparent")
        dr.pack(fill="x", pady=(0, 12))
        self.sat_dest = ctk.CTkEntry(dr, height=36, corner_radius=8)
        self.sat_dest.insert(0, str(APP_DIR / "descargas"))
        self.sat_dest.pack(side="left", fill="x", expand=True)

        def _bd():
            d = filedialog.askdirectory()
            if d:
                self.sat_dest.delete(0, tk.END)
                self.sat_dest.insert(0, d)

        ctk.CTkButton(dr, text="…", width=36, height=36, corner_radius=8,
                      command=_bd, fg_color=("gray80", "gray25"),
                      hover_color=("gray70", "gray30"),
                      text_color=("gray20", "gray85")).pack(side="left", padx=(6, 0))

        self.btn_descargar = ctk.CTkButton(
            body, text="⬇  Iniciar Descarga",
            font=("Segoe UI", 12, "bold"), height=38, corner_radius=8,
            fg_color="#15803D", hover_color="#166534",
            command=self._sat_descargar)
        self.btn_descargar.pack(fill="x")

    def _build_sat_log(self, parent):
        lc = ctk.CTkFrame(parent, corner_radius=14)
        lc.grid(row=2, column=0, sticky="nsew", padx=22, pady=(10, 18))
        lc.grid_columnconfigure(0, weight=1)
        lc.grid_rowconfigure(1, weight=1)

        lh = ctk.CTkFrame(lc, fg_color="transparent", height=46)
        lh.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 0))
        lh.grid_propagate(False)
        ctk.CTkLabel(lh, text="Bitácora de descarga",
                     font=("Segoe UI", 13, "bold")).pack(side="left", pady=10)
        ctk.CTkButton(lh, text="Limpiar", width=72, height=28, corner_radius=6,
                      fg_color=("gray80", "gray25"), hover_color=("gray70", "gray30"),
                      text_color=("gray30", "gray70"), font=("Segoe UI", 10),
                      command=lambda: self.sat_log.delete(1.0, tk.END)
                      ).pack(side="right", pady=9)

        lw = ctk.CTkFrame(lc, fg_color="transparent")
        lw.grid(row=1, column=0, sticky="nsew", padx=4, pady=(4, 4))
        lw.grid_columnconfigure(0, weight=1)
        lw.grid_rowconfigure(0, weight=1)

        self.sat_log = tk.Text(lw, font=("Consolas", 9), bg="#1E1E1E", fg="#D4D4D4",
                               relief=tk.FLAT, padx=14, pady=10,
                               insertbackground="#D4D4D4", bd=0, wrap=tk.WORD)
        self.sat_log.grid(row=0, column=0, sticky="nsew")
        vsb = ctk.CTkScrollbar(lw, command=self.sat_log.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.sat_log.configure(yscrollcommand=vsb.set)

        for tag, fg, bold in [
            ("success", "#22C55E", False),
            ("error",   "#EF4444", True),
            ("warning", "#F59E0B", False),
            ("info",    "#60A5FA", False),
            ("muted",   "#64748B", False),
        ]:
            self.sat_log.tag_config(tag, foreground=fg,
                                    font=("Consolas", 9, "bold") if bold else ("Consolas", 9))

    def sat_log_msg(self, msg, tag=None):
        self.after(0, lambda: (self.sat_log.insert(tk.END, msg + "\n", tag),
                               self.sat_log.see(tk.END)))

    # ── Lógica SAT ────────────────────────────────────────────────────────────
    def _sat_conectar(self):
        rfc = self.sat_rfc.get().strip().upper()
        cer = self.sat_cer.get().strip()
        key = self.sat_key.get().strip()
        pwd = self.sat_pwd.get()
        if not all([rfc, cer, key, pwd]):
            messagebox.showwarning("Datos incompletos", "Completa todos los campos de la FIEL.")
            return
        self.lbl_conexion.configure(text="Conectando…", text_color="#F59E0B")
        self.btn_conectar.configure(state="disabled")

        def _w():
            d  = DescargadorSAT(rfc, cer, key, pwd, log_fn=self.sat_log_msg)
            ok = d.conectar()
            if ok:
                self._descargador = d
                self.after(0, lambda: (
                    self.lbl_conexion.configure(text=f"✓  {rfc}", text_color="#22C55E"),
                    self.btn_conectar.configure(state="normal")))
            else:
                self._descargador = None
                self.after(0, lambda: (
                    self.lbl_conexion.configure(text="✗  Error", text_color="#EF4444"),
                    self.btn_conectar.configure(state="normal")))

        threading.Thread(target=_w, daemon=True).start()

    def _sat_descargar(self):
        if not self._descargador:
            messagebox.showwarning("Sin conexión", "Primero conéctate al SAT.")
            return
        try:
            fi = datetime.strptime(self.sat_fi.get(), "%d/%m/%Y").date()
            ff = datetime.strptime(self.sat_ff.get(), "%d/%m/%Y").date()
        except ValueError:
            messagebox.showerror("Fecha inválida", "Usa el formato DD/MM/AAAA.")
            return
        destino = self.sat_dest.get().strip()
        if not destino:
            messagebox.showwarning("Sin destino", "Selecciona una carpeta.")
            return

        tipo  = self.sat_tipo.get()
        tipos = ["emitidos", "recibidos"] if tipo == "ambos" else [tipo]
        self.btn_descargar.configure(state="disabled")
        self.sat_log_msg(f"\n{'─' * 52}", "muted")
        self.sat_log_msg("Iniciando descarga…", "info")

        def _w():
            for t in tipos:
                self.sat_log_msg(f"\n📥  {t.capitalize()}…", "info")
                r = self._descargador.descargar_xmls(fi, ff, t, destino)
                if r:
                    self.sat_log_msg(f"✓  {r.get('descargados', 0)} archivo(s)", "success")
                else:
                    self.sat_log_msg(f"✗  Error en {t}", "error")
            self.sat_log_msg(f"\n{'─' * 52}", "muted")
            self.after(0, lambda: self.btn_descargar.configure(state="normal"))

        threading.Thread(target=_w, daemon=True).start()


# =============================================================================
if __name__ == "__main__":
    app = App()
    app.mainloop()
