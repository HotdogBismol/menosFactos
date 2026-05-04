from datetime import date
import os
import time
import zipfile

try:
    from satcfdi.models import Signer
    from satcfdi.pacs.sat import SAT, TipoDescargaMasivaTerceros, EstadoSolicitud, EstadoComprobante
    SAT_DISPONIBLE = True
except ImportError:
    SAT_DISPONIBLE = False


class DescargadorSAT:
    def __init__(self, rfc, archivo_cer, archivo_key, password_key, log_fn=None):
        self.rfc          = rfc
        self.archivo_cer  = archivo_cer
        self.archivo_key  = archivo_key
        self.password_key = password_key
        self.sat_service  = None
        # log_fn(msg, tag=None) — compatible con sat_log_msg de la GUI
        self._log = log_fn if log_fn else lambda msg, tag=None: print(msg)

    # ------------------------------------------------------------------
    def conectar(self):
        if not SAT_DISPONIBLE:
            self._log("✗ satcfdi no está instalado. Ejecuta: pip install satcfdi", "error")
            return False

        # Paso 1 — Leer .cer
        self._log("Paso 1/4  Leyendo archivo .cer…", "muted")
        try:
            with open(self.archivo_cer, 'rb') as f:
                cer_data = f.read()
            self._log(f"   ✓  {len(cer_data):,} bytes leídos de: {self.archivo_cer}", "muted")
        except FileNotFoundError:
            self._log(f"✗ Archivo .cer no encontrado:\n   {self.archivo_cer}", "error")
            return False
        except Exception as e:
            self._log(f"✗ Error leyendo .cer: {e}", "error")
            return False

        # Paso 2 — Leer .key
        self._log("Paso 2/4  Leyendo archivo .key…", "muted")
        try:
            with open(self.archivo_key, 'rb') as f:
                key_data = f.read()
            self._log(f"   ✓  {len(key_data):,} bytes leídos de: {self.archivo_key}", "muted")
        except FileNotFoundError:
            self._log(f"✗ Archivo .key no encontrado:\n   {self.archivo_key}", "error")
            return False
        except Exception as e:
            self._log(f"✗ Error leyendo .key: {e}", "error")
            return False

        # Paso 3 — Construir Signer (valida certificado, clave y contraseña)
        self._log("Paso 3/4  Cargando FIEL con Signer.load()…", "muted")
        try:
            pwd = self.password_key
            if isinstance(pwd, str):
                pwd = pwd.encode('utf-8')
            signer = Signer.load(
                certificate=cer_data,
                key=key_data,
                password=pwd
            )
            self._log(f"   ✓  RFC del certificado: {signer.rfc}", "muted")
        except Exception as e:
            self._log(f"✗ Error al validar FIEL (contraseña incorrecta o archivos inválidos):", "error")
            self._log(f"   {type(e).__name__}: {e}", "error")
            return False

        # Paso 4 — Conectar al SAT
        self._log("Paso 4/4  Conectando con el servicio SAT…", "muted")
        try:
            self.sat_service = SAT(signer=signer)
            self._log(f"✓ FIEL cargada correctamente para RFC: {signer.rfc}", "success")
            return True
        except Exception as e:
            self._log(f"✗ Error al inicializar el servicio SAT:", "error")
            self._log(f"   {type(e).__name__}: {e}", "error")
            return False

    # ------------------------------------------------------------------
    def descargar_xmls(self, fecha_inicio, fecha_fin, tipo="emitidos",
                       carpeta_destino="descargas"):
        if not self.sat_service:
            self._log("✗ No conectado. Llama a conectar() primero.", "error")
            return None

        if fecha_inicio > fecha_fin:
            self._log("✗ La fecha de inicio debe ser anterior a la fecha fin.", "error")
            return None

        if tipo not in ("emitidos", "recibidos"):
            self._log(f"✗ Tipo inválido: '{tipo}'. Usa 'emitidos' o 'recibidos'.", "error")
            return None

        carpeta_cliente = os.path.join(carpeta_destino, self.rfc, tipo)
        os.makedirs(carpeta_cliente, exist_ok=True)

        self._log(f"📥 Solicitando CFDIs {tipo}  "
                  f"({fecha_inicio.strftime('%d/%m/%Y')} – {fecha_fin.strftime('%d/%m/%Y')})", "info")

        try:
            if tipo == "emitidos":
                response = self.sat_service.recover_comprobante_emitted_request(
                    fecha_inicial=fecha_inicio,
                    fecha_final=fecha_fin,
                    tipo_solicitud=TipoDescargaMasivaTerceros.CFDI,
                    estado_comprobante=EstadoComprobante.VIGENTE,
                )
            else:
                response = self.sat_service.recover_comprobante_received_request(
                    fecha_inicial=fecha_inicio,
                    fecha_final=fecha_fin,
                    rfc_receptor=self.sat_service.signer.rfc,
                    tipo_solicitud=TipoDescargaMasivaTerceros.CFDI,
                    estado_comprobante=EstadoComprobante.VIGENTE,
                )

            # Mostrar respuesta completa para diagnóstico
            self._log(f"   Respuesta SAT: {dict(response)}", "muted")

            if 'IdSolicitud' not in response:
                cod = response.get('CodEstatus', response.get('codEstatus', '?'))
                msg = response.get('Mensaje',    response.get('mensaje',    str(response)))
                self._log(f"✗ SAT rechazó la solicitud — Código: {cod} | {msg}", "error")
                return None

            id_solicitud = response['IdSolicitud']
            self._log(f"   ID solicitud: {id_solicitud}", "muted")
            self._log("   Esperando respuesta del SAT...", "muted")

            max_intentos = 30
            for intento in range(max_intentos):
                time.sleep(10)
                status_response = self.sat_service.recover_comprobante_status(id_solicitud)
                estado = status_response.get('EstadoSolicitud')

                if estado == EstadoSolicitud.TERMINADA:
                    paquetes = status_response.get('IdsPaquetes', [])
                    if not paquetes:
                        self._log("⚠  No se encontraron CFDIs en este período.", "warning")
                        return {'descargados': 0, 'paquetes': 0}

                    self._log(f"   Descargando {len(paquetes)} paquete(s)...", "info")
                    total_archivos = 0

                    for idx, id_paquete in enumerate(paquetes, 1):
                        self._log(f"   Paquete {idx}/{len(paquetes)}...", "muted")
                        _, paquete_zip = self.sat_service.recover_comprobante_download(id_paquete)

                        zip_path = os.path.join(carpeta_cliente, f"paquete_{idx}.zip")
                        with open(zip_path, 'wb') as f:
                            f.write(paquete_zip)

                        with zipfile.ZipFile(zip_path, 'r') as zf:
                            archivos = zf.namelist()
                            zf.extractall(carpeta_cliente)
                            total_archivos += len(archivos)

                        os.remove(zip_path)

                    self._log(f"✓ {total_archivos} archivos XML descargados en:\n   {carpeta_cliente}", "success")
                    return {'descargados': total_archivos, 'paquetes': len(paquetes)}

                elif estado in (EstadoSolicitud.ACEPTADA, EstadoSolicitud.EN_PROCESO):
                    self._log(f"   Estado: {estado.name}  (intento {intento + 1}/{max_intentos})", "muted")
                else:
                    mensaje = status_response.get('Mensaje', 'Sin mensaje')
                    self._log(f"✗ Solicitud rechazada: {estado.name} — {mensaje}", "error")
                    return None

            self._log("✗ Tiempo de espera agotado (5 min).", "error")
            return None

        except Exception as e:
            self._log(f"✗ Error en la descarga: {e}", "error")
            return None
