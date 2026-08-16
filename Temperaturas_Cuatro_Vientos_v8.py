import requests
import json
import time
from datetime import datetime, timedelta
import logging
import sys
import os
import re
from dotenv import load_dotenv
from pathlib import Path

# 1. FUNCIÓN DE CONFIGURACIÓN DE LOGGING
def setup_robust_logging(log_file='aemet_download.log'):
    """Configura logging con manejo robusto de errores"""
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    if (logger.hasHandlers()):
        logger.handlers.clear()
        
    try:
        file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='w')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"No se pudo crear archivo de log: {e}")
    
    try:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    except Exception as e:
        print(f"No se pudo crear handler de consola: {e}")
    
    return logger

# LLAMADA AL LOGGING
logger = setup_robust_logging()

# 2. CONFIGURACIÓN
#DIRECTORIO_DESTINO = r"C:\M\MARIO\Py\CuatroVientos"
#ARCHIVO_AGREGADO = os.path.join(DIRECTORIO_DESTINO, "datos_estacion_3195.json")

ARCHIVO_AGREGADO = Path(__file__).parent / "datos_estacion_3195.json"


# 3. CLASE AEMETClient
class AEMETClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://opendata.aemet.es/opendata/api"
        self.estacion_id = "3196"  # Cuatro Vientos
        self.requests_count = 0
        self.max_requests = 30 
        self.reset_time = datetime.now() + timedelta(minutes=1)
    
    def safe_log(self, level, message):
        try:
            message_str = str(message)
            clean_message = message_str.encode('utf-8', errors='replace').decode('utf-8')
            
            if level == 'info':
                logging.info(clean_message)
            elif level == 'warning':
                logging.warning(clean_message)
            elif level == 'error':
                logging.error(clean_message)
        except Exception as e:
            print(f"{level.upper()}: {str(message)[:200]} - Error de log: {e}")

    def verificar_conexion_aemet(self):
        """Verifica que la API de AEMET está accesible y la API key es válida"""
        try:
            # Endpoint simple para verificar conexión
            test_url = f"{self.base_url}/valores/climatologicos/inventarioestaciones/todasestaciones"
            headers = {"api_key": self.api_key}
            
            self.safe_log('info', "Verificando conexión con la API de AEMET...")
            
            response = requests.get(test_url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                self.safe_log('info', "✅ Conexión con AEMET establecida correctamente")
                return True
            elif response.status_code == 401:
                self.safe_log('error', "❌ API key no válida o expirada")
                return False
            elif response.status_code == 404:
                self.safe_log('warning', "⚠ Endpoint no encontrado, pero conexión establecida")
                return True
            elif response.status_code == 429:
                self.safe_log('warning', "⚠ Límite de peticiones excedido durante verificación")
                return True  # Consideramos que hay conexión pero con límite
            else:
                self.safe_log('error', f"❌ Error en conexión: Código {response.status_code}")
                return False
                
        except requests.exceptions.Timeout:
            self.safe_log('error', "❌ Timeout: No se pudo conectar con AEMET (tiempo de espera agotado)")
            return False
        except requests.exceptions.ConnectionError:
            self.safe_log('error', "❌ Error de conexión: Verifique su conexión a Internet")
            return False
        except requests.exceptions.SSLError:
            self.safe_log('error', "❌ Error SSL: Problema con el certificado de seguridad")
            return False
        except Exception as e:
            self.safe_log('error', f"❌ Error inesperado al verificar conexión: {str(e)}")
            return False

    def make_request(self, url, max_reintentos=5):
        reintentos = 0
        tiempo_espera = 2
        
        while reintentos <= max_reintentos:
            try:
                if "opendata.aemet.es" in url:
                    current_time = datetime.now()
                    if current_time < self.reset_time and self.requests_count >= self.max_requests:
                        wait_seconds = (self.reset_time - current_time).total_seconds()
                        self.safe_log('warning', f"Límite de peticiones excedido. Esperando {wait_seconds:.0f} segundos...")
                        time.sleep(wait_seconds + 1)
                        self.requests_count = 0
                        self.reset_time = datetime.now() + timedelta(minutes=1)
                    
                    if current_time >= self.reset_time:
                        self.requests_count = 0
                        self.reset_time = current_time + timedelta(minutes=1)
                    
                    headers = {"api_key": self.api_key}
                else:
                    headers = {} 

                self.safe_log('info', f"Realizando petición (reintento {reintentos}/{max_reintentos}): {url[:100]}...")
                response = requests.get(url, headers=headers, timeout=60)
                
                if "opendata.aemet.es" in url:
                    self.requests_count += 1
                
                if response.status_code == 429:
                    raise Exception("Límite de peticiones excedido (429). Espere al siguiente minuto.")
                    
                response.raise_for_status()
                
                try:
                    return response.json()
                except json.JSONDecodeError:
                    return response.text
                    
            except requests.exceptions.RequestException as e:
                reintentos += 1
                if reintentos > max_reintentos:
                    raise Exception(f"Error después de {max_reintentos} reintentos en {url}: {str(e)}")
                 
                tiempo_espera_actual = min(30, tiempo_espera * (2 ** reintentos))
                self.safe_log('warning', f"Error de petición. Reintento {reintentos}/{max_reintentos} en {tiempo_espera_actual:.1f} segundos...")
                time.sleep(tiempo_espera_actual)

        raise Exception(f"Fallo al realizar la petición a {url} después de múltiples reintentos.")
        
    def obtener_datos_estacion(self, fecha_inicio_str, fecha_fin_str, max_reintentos=5):
        # 1. Petición para obtener el enlace de descarga de datos (URL)
        endpoint = f"/valores/climatologicos/diarios/datos/fechaini/{fecha_inicio_str}T00:00:00UTC/fechafin/{fecha_fin_str}T23:59:59UTC/estacion/{self.estacion_id}"
        url_aemet = f"{self.base_url}{endpoint}"
         
        self.safe_log('info', f"Paso 1: Obteniendo URL de descarga para {fecha_inicio_str} a {fecha_fin_str}")
         
        try:
            link_response = self.make_request(url_aemet, max_reintentos)
        except Exception as e:
            self.safe_log('error', f"Error en Paso 1 (Link URL): {e}")
            return None

        # Verificar la respuesta del link
        if isinstance(link_response, dict) and link_response.get('estado') == 200 and 'datos' in link_response:
            data_url = link_response['datos']
        elif isinstance(link_response, dict) and link_response.get('estado') == 404:
            self.safe_log('warning', "El recurso (URL) no está disponible en AEMET para este periodo.")
            return None
        else:
            self.safe_log('error', f"Respuesta inesperada en Paso 1. Estado: {link_response.get('estado', 'N/A')}")
            return None
             
        # 2. Petición para descargar los datos reales desde el enlace
        self.safe_log('info', f"Paso 2: Descargando datos desde la URL proporcionada")
         
        try:
            datos_reales = self.make_request(data_url, max_reintentos)
             
            if isinstance(datos_reales, list):
                return datos_reales
            else:
                self.safe_log('error', f"Los datos descargados no son una lista (JSON). Tipo: {type(datos_reales)}")
                return None
             
        except Exception as e:
            self.safe_log('error', f"Error en Paso 2 (Descarga de Datos): {e}")
            return None


# 4. FUNCIONES DE PROCESAMIENTO
def limpiar_valor(valor):
    if valor is None:
        return None
        
    valor_str = str(valor).strip()
    valor_str = valor_str.replace(',', '.')
    
    if valor_str.lower() == 'tr':
        return 0.001
        
    valor_limpio = re.sub(r'[^\d\.\-\+]', '', valor_str)
    
    if not valor_limpio:
        return None
        
    try:
        return float(valor_limpio)
    except ValueError:
        return None

def limpiar_y_convertir_datos(datos):
    campos_numericos = [
        'tmed', 'tmax', 'tmin', 'prec', 'velmedia', 'racha', 'sol',
        'presMax', 'presMin', 'altura', 'dir', 'inso'
    ]
    
    registros_limpios = []
    total_registros = len(datos)
    fechas_vistas = set() 

    for i, registro in enumerate(datos):
        fecha_registro = registro.get('fecha')
        if fecha_registro and fecha_registro in fechas_vistas:
            continue
        if fecha_registro:
            fechas_vistas.add(fecha_registro)

        for campo in campos_numericos:
            if campo in registro:
                registro[campo] = limpiar_valor(registro[campo])
                
        if fecha_registro:
            registros_limpios.append(registro)
        
    logging.info(f"✅ Pre-procesamiento completado. Registros originales: {total_registros}. Registros limpios: {len(registros_limpios)}")
    return registros_limpios
    
def guardar_datos(datos, nombre_archivo):
    try:
        with open(nombre_archivo, 'w', encoding='utf-8') as f: 
            json.dump(datos, f, ensure_ascii=False, indent=2)
        logging.info(f"Datos guardados en {nombre_archivo}. Total: {len(datos)} registros")
        return True
    except Exception as e:
        logging.error(f"Error guardando datos: {str(e)}")
        return False

def verificar_conexion_internet():
    """Verifica si hay conexión a Internet"""
    try:
        # Intentamos conectar a un servidor confiable
        response = requests.get("https://www.google.com", timeout=5)
        return response.status_code == 200
    except:
        return False

# 5. FUNCIÓN PARA LEER ÚLTIMA FECHA DEL ARCHIVO AGREGADO
def obtener_ultima_fecha_archivo():
    """
    Lee el archivo agregado y obtiene la última fecha disponible
    Retorna: (datetime, bool) - (fecha_ultima, archivo_existe)
    Si el archivo no existe, retorna (None, False)
    Si el archivo está vacío o no tiene fechas válidas, retorna (None, True)
    """
    if not os.path.exists(ARCHIVO_AGREGADO):
        logging.info(f"Archivo agregado no encontrado: {ARCHIVO_AGREGADO}")
        return None, False
    
    try:
        with open(ARCHIVO_AGREGADO, 'r', encoding='utf-8') as f:
            datos = json.load(f)
        
        if not datos or len(datos) == 0:
            logging.warning(f"Archivo agregado vacío: {ARCHIVO_AGREGADO}")
            return None, True
        
        # Extraer todas las fechas y encontrar la máxima
        fechas = []
        for registro in datos:
            fecha_str = registro.get('fecha')
            if fecha_str:
                try:
                    # El formato de fecha en AEMET es YYYY-MM-DD
                    fecha = datetime.strptime(fecha_str, "%Y-%m-%d")
                    fechas.append(fecha)
                except (ValueError, TypeError):
                    continue
        
        if not fechas:
            logging.warning("No se encontraron fechas válidas en el archivo agregado")
            return None, True
        
        ultima_fecha = max(fechas)
        logging.info(f"Última fecha encontrada en archivo agregado: {ultima_fecha.strftime('%Y-%m-%d')}")
        return ultima_fecha, True
        
    except json.JSONDecodeError:
        logging.error(f"Error al decodificar JSON del archivo: {ARCHIVO_AGREGADO}")
        return None, True
    except Exception as e:
        logging.error(f"Error al leer archivo agregado: {str(e)}")
        return None, True

def agregar_datos_nuevos(datos_existentes, datos_nuevos):
    """
    Agrega datos nuevos al archivo existente, evitando duplicados por fecha
    """
    if not datos_existentes:
        return datos_nuevos
    
    # Crear un diccionario con fecha como clave para los datos existentes
    fechas_existentes = {}
    for registro in datos_existentes:
        fecha = registro.get('fecha')
        if fecha:
            fechas_existentes[fecha] = registro
    
    # Agregar solo registros nuevos (por fecha)
    registros_agregados = 0
    for registro in datos_nuevos:
        fecha = registro.get('fecha')
        if fecha and fecha not in fechas_existentes:
            fechas_existentes[fecha] = registro
            registros_agregados += 1
    
    # Convertir de vuelta a lista y ordenar por fecha
    datos_combinados = list(fechas_existentes.values())
    datos_combinados.sort(key=lambda x: x.get('fecha', ''))
    
    logging.info(f"Registros existentes: {len(datos_existentes)}, Nuevos: {len(datos_nuevos)}, Agregados: {registros_agregados}")
    return datos_combinados

# 6. FUNCIÓN PRINCIPAL DE DESCARGA
def descargar_datos_historicos(api_key, fecha_inicio, max_reintentos_por_periodo=5):
    client = AEMETClient(api_key)
    todos_datos = []
    
    # Rango de Fechas - hasta 5 días antes de hoy
    fecha_hoy = datetime.now()
    fecha_fin = fecha_hoy - timedelta(days=5)
    
    # Validar que la fecha de inicio sea anterior a la fecha de fin
    if fecha_inicio > fecha_fin:
        logging.error(f"Error: La fecha de inicio ({fecha_inicio.strftime('%d/%m/%Y')}) es posterior a la fecha de fin ({fecha_fin.strftime('%d/%m/%Y')})")
        return []
    
    logging.info(f"Descargando desde: {fecha_inicio.strftime('%Y-%m-%d')} hasta: {fecha_fin.strftime('%Y-%m-%d')}")
    
    # División por periodos (máximo 180 días por petición debido a limitaciones de AEMET)
    fecha_actual = fecha_inicio
    periodos = []
    
    while fecha_actual < fecha_fin:
        periodo_fin = fecha_actual + timedelta(days=180) 
        if periodo_fin > fecha_fin:
            periodo_fin = fecha_fin
        
        if periodo_fin <= fecha_actual:
            break

        periodos.append((fecha_actual, periodo_fin))
        fecha_actual = periodo_fin + timedelta(days=1)
    
    if not periodos and fecha_inicio <= fecha_fin:
        periodos.append((fecha_inicio, fecha_fin))

    total_periodos = len(periodos)
    logging.info("=====================================================")
    logging.info(f"RANGO DE DESCARGA: {fecha_inicio.strftime('%d/%m/%Y')} hasta {fecha_fin.strftime('%d/%m/%Y')}")
    logging.info(f"Se descargarán {total_periodos} periodos.")
    logging.info("=====================================================")
    
    # Bucle de descarga
    for i, (periodo_inicio, periodo_fin) in enumerate(periodos):
        exito = False
        reintentos_periodo = 0
        
        while not exito and reintentos_periodo <= max_reintentos_por_periodo:
            try:
                inicio_str = periodo_inicio.strftime("%Y-%m-%d")
                fin_str = periodo_fin.strftime("%Y-%m-%d")
                
                if reintentos_periodo == 0:
                    logging.info(f"Descargando periodo {i+1}/{total_periodos}: {inicio_str} a {fin_str}")
                else:
                    logging.info(f"Reintento {reintentos_periodo} para periodo {i+1}/{total_periodos}: {inicio_str} a {fin_str}")
                
                datos_periodo = client.obtener_datos_estacion(inicio_str, fin_str, max_reintentos=3) 
                
                if datos_periodo is not None and len(datos_periodo) > 0:
                    todos_datos.extend(datos_periodo)
                    logging.info(f"✓ {len(datos_periodo)} registros descargados para el periodo {inicio_str} a {fin_str}")
                    exito = True
                elif datos_periodo is not None and len(datos_periodo) == 0:
                    logging.warning(f"⚠ Se obtuvieron 0 registros para el periodo {inicio_str} a {fin_str}")
                    exito = True
                else:
                    raise Exception("Error al obtener datos o el recurso no está disponible.")
                
                time.sleep(0.5)
                
            except Exception as e:
                reintentos_periodo += 1
                if reintentos_periodo > max_reintentos_por_periodo:
                    logging.error(f"✗ Error crítico en periodo {i+1} después de {max_reintentos_por_periodo} reintentos: {str(e)}")
                    logging.error("Continuando con el siguiente periodo...")
                    break
                
                tiempo_espera = min(60, 2 ** reintentos_periodo)
                logging.warning(f"Reintentando periodo {i+1} en {tiempo_espera} segundos...")
                time.sleep(tiempo_espera)
    
    return todos_datos

# 7. FUNCIÓN MAIN
def main():
    

    # Busca el .env en la misma carpeta que el script, sin importar desde dónde se ejecute
    env_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=env_path)


    load_dotenv()  # lee el archivo .env
    API_KEY = os.environ.get("API_KEY")

       
    MAX_REINTENTOS = 10 
    
    if API_KEY == "" or not API_KEY:
        logging.error("⛔ Error: Por favor, configura tu API key de AEMET en la variable API_KEY")
        return
    
    print("\n" + "="*50)
    print("DESCARGA DE DATOS CLIMATOLÓGICOS - AEMET")
    print("Estación: 3194U (Madrid-Retiro)")
    print("="*50)
    
    # 1. Verificar conexión a Internet
    print("\n🔍 Verificando conexión a Internet...")
    if not verificar_conexion_internet():
        print("❌ No hay conexión a Internet. Verifique su conexión e intente nuevamente.")
        logging.error("No hay conexión a Internet")
        return
    
    print("✅ Conexión a Internet establecida")
    
    # 2. Crear cliente y verificar conexión con AEMET
    client = AEMETClient(API_KEY)
    
    print("\n🔍 Verificando conexión con la API de AEMET...")
    if not client.verificar_conexion_aemet():
        print("❌ No se pudo conectar con la API de AEMET.")
        print("   Posibles causas:")
        print("   - API key no válida o expirada")
        print("   - Problemas temporales del servicio AEMET")
        print("   - Restricciones de red/firewall")
        return
    
    print("✅ Conexión con AEMET verificada correctamente")
    
    # 3. Leer última fecha del archivo agregado
    print("\n📂 Verificando archivo agregado...")
    ultima_fecha, archivo_existe = obtener_ultima_fecha_archivo()
    
    if not archivo_existe:
        # Si el archivo no existe, preguntar fecha de inicio
        print("ℹ No se encontró archivo agregado. Es la primera descarga.")
        print("\n" + "-"*50)
        print("PRIMERA DESCARGA - CONFIGURACIÓN INICIAL")
        print("-"*50)
        
        while True:
            fecha_input = input("Introduce la fecha de inicio para la primera descarga (dd/mm/yyyy): ").strip()
            
            try:
                fecha_inicio = datetime.strptime(fecha_input, "%d/%m/%Y")
                
                # Validar que no sea una fecha futura
                hoy = datetime.now()
                if fecha_inicio > hoy:
                    print("Error: La fecha no puede ser futura. Inténtalo de nuevo.")
                    continue
                
                # Validar que sea una fecha razonable
                if fecha_inicio.year < 1900:
                    print("Error: La fecha debe ser posterior a 1900. Inténtalo de nuevo.")
                    continue
                
                break
                
            except ValueError:
                print("Error: Formato incorrecto. Usa dd/mm/yyyy (ej: 01/01/2020). Inténtalo de nuevo.")
    else:
        if ultima_fecha:
            # Archivo existe y tiene datos -> fecha_inicio = última fecha + 1 día
            fecha_inicio = ultima_fecha + timedelta(days=1)
            print(f"📅 Última fecha en archivo: {ultima_fecha.strftime('%d/%m/%Y')}")
            print(f"📅 Nueva fecha de inicio: {fecha_inicio.strftime('%d/%m/%Y')} (última + 1 día)")
        else:
            # Archivo existe pero está vacío o sin fechas válidas
            print("⚠ El archivo agregado existe pero no contiene fechas válidas.")
            print("\n" + "-"*50)
            print("CONFIGURACIÓN DE FECHA DE INICIO")
            print("-"*50)
            
            while True:
                fecha_input = input("Introduce la fecha de inicio para comenzar la descarga (dd/mm/yyyy): ").strip()
                
                try:
                    fecha_inicio = datetime.strptime(fecha_input, "%d/%m/%Y")
                    
                    # Validar que no sea una fecha futura
                    hoy = datetime.now()
                    if fecha_inicio > hoy:
                        print("Error: La fecha no puede ser futura. Inténtalo de nuevo.")
                        continue
                    
                    # Validar que sea una fecha razonable
                    if fecha_inicio.year < 1900:
                        print("Error: La fecha debe ser posterior a 1900. Inténtalo de nuevo.")
                        continue
                    
                    break
                    
                except ValueError:
                    print("Error: Formato incorrecto. Usa dd/mm/yyyy (ej: 01/01/2020). Inténtalo de nuevo.")
    
    hoy = datetime.now()
    fecha_fin = hoy - timedelta(days=5)
    
    logging.info("=====================================================")
    logging.info(f"Fecha de inicio calculada: {fecha_inicio.strftime('%d/%m/%Y')}")
    logging.info(f"Fecha de fin (automática): {fecha_fin.strftime('%d/%m/%Y')}")
    logging.info(f"Días a descargar: {(fecha_fin - fecha_inicio).days + 1} días")
    logging.info(f"Máximo de reintentos por periodo: {MAX_REINTENTOS}")
    logging.info("=====================================================")
    
    start_time = time.time()
    
    datos_nuevos = descargar_datos_historicos(API_KEY, fecha_inicio, MAX_REINTENTOS)
    
    if datos_nuevos:
        logging.info(f"Iniciando limpieza y conversión de {len(datos_nuevos)} registros...")
        datos_nuevos_limpios = limpiar_y_convertir_datos(datos_nuevos)
        
        if not os.path.exists(DIRECTORIO_DESTINO):
            try:
                os.makedirs(DIRECTORIO_DESTINO)
            except OSError as e:
                logging.error(f"Error al crear el directorio de destino {DIRECTORIO_DESTINO}: {e}")
                return
        
        # Leer datos existentes si el archivo ya existe
        datos_existentes = []
        if os.path.exists(ARCHIVO_AGREGADO):
            try:
                with open(ARCHIVO_AGREGADO, 'r', encoding='utf-8') as f:
                    datos_existentes = json.load(f)
                logging.info(f"Archivo existente cargado: {len(datos_existentes)} registros")
            except Exception as e:
                logging.error(f"Error al leer archivo existente: {e}")
                # Continuamos con datos_existentes vacío
        
        # Combinar datos
        datos_combinados = agregar_datos_nuevos(datos_existentes, datos_nuevos_limpios)
        
        # Guardar archivo combinado
        if guardar_datos(datos_combinados, ARCHIVO_AGREGADO):
            end_time = time.time()
            tiempo_total = end_time - start_time
            
            logging.info("=====================================================")
            logging.info(f"✅ Proceso completo. Tiempo total: {tiempo_total:.2f} segundos")
            logging.info(f"Registros nuevos descargados: {len(datos_nuevos_limpios)}")
            logging.info(f"Total registros en archivo agregado: {len(datos_combinados)}")
            logging.info(f"Ruta de guardado: {ARCHIVO_AGREGADO}")
            logging.info("=====================================================")
            
            # Mostrar resumen al usuario
            print("\n" + "="*50)
            print("RESUMEN DE LA DESCARGA")
            print("="*50)
            print(f"Fecha inicio: {fecha_inicio.strftime('%d/%m/%Y')}")
            print(f"Fecha fin: {fecha_fin.strftime('%d/%m/%Y')} (hoy menos 5 días)")
            print(f"Registros nuevos: {len(datos_nuevos_limpios)}")
            print(f"Total registros: {len(datos_combinados)}")
            print(f"Tiempo total: {tiempo_total:.2f} segundos")
            print(f"Archivo actualizado: {ARCHIVO_AGREGADO}")
            print("="*50)
        else:
            logging.error("❌ Error al guardar los datos")
    else:
        # No se descargaron datos nuevos
        if archivo_existe and ultima_fecha:
            print(f"\n✅ No hay datos nuevos disponibles. Última fecha en archivo: {ultima_fecha.strftime('%d/%m/%Y')}")
            logging.info("No se descargaron datos nuevos")
        else:
            logging.error("❌ No se pudieron descargar datos")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠ Descarga interrumpida por el usuario")
        logging.warning("Descarga interrumpida por el usuario")
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        logging.error(f"Error inesperado en ejecución principal: {e}", exc_info=True)