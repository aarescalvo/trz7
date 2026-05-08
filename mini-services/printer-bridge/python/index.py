# -*- coding: utf-8 -*-
"""
Printer Bridge v3.1 - Solemar Alimentaria
==========================================
Puente TCP -> Impresora USB para Windows 7/10
Compatible con Python 3.8+

Arquitectura:
  Sistema TrazAlan (Next.js) -> TCP/IP :9100 -> Este bridge -> win32print -> USB Datamax Mark II

Metodos de impresion (se prueban en orden hasta que uno funcione):
  A) win32print RAW sin page controls (StartDoc > WritePrinter > EndDoc)
  B) win32print RAW con page controls (StartDoc > StartPage > WritePrinter > EndPage > EndDoc)
  C) Escritura directa al puerto USB via open() con modo binario
  D) Envio TCP directo a la IP de la impresora (si tiene tarjeta de red)

Formatos soportados:
  - ZPL (Zebra Programming Language)
  - DPL (Datamax Programming Language)
  - Cualquier dato RAW enviado por TCP

Uso:
  python index.py              (inicio normal)
  python index.py --debug      (modo debug con logs detallados)

Config: printer-config.json o panel web en http://localhost:9101
"""

import os
import sys
import json
import socket
import struct
import threading
import time
import subprocess
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from functools import partial

# ============================================================
# Configuracion
# ============================================================
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'printer-config.json')
TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp')

DEFAULT_CONFIG = {
    'printerName': '',        # Nombre exacto de la impresora en Windows
    'printerIP': '',          # IP directa de la impresora (TCP port 9100) - opcional
    'tcpPort': 9100,          # Puerto TCP para recibir datos (estandar impresoras)
    'httpPort': 9101,         # Puerto HTTP para panel de control
    'logLevel': 'info',       # info, debug, error
    'autoStart': True,
    'copyCount': 1,           # Cantidad de copias por defecto
    'printMethod': 'auto'     # auto, A, B, C, D - metodo de impresion
}


def load_config():
    """Cargar configuracion desde archivo JSON."""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                cfg = dict(DEFAULT_CONFIG)
                cfg.update(saved)
                return cfg
    except Exception as e:
        print('[ERROR] Error leyendo config: {}'.format(e))
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    """Guardar configuracion a archivo JSON."""
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print('[ERROR] Error guardando config: {}'.format(e))
        return False


config = load_config()

# Crear directorio temp si no existe
if not os.path.exists(TEMP_DIR):
    try:
        os.makedirs(TEMP_DIR)
    except:
        TEMP_DIR = tempfile.gettempdir()

# Limpiar archivos temp viejos (>1 hora)
try:
    ahora = time.time()
    for fname in os.listdir(TEMP_DIR):
        fpath = os.path.join(TEMP_DIR, fname)
        if fname.startswith('print-job-') and fname.endswith('.raw'):
            try:
                if os.path.getmtime(fpath) < ahora - 3600:
                    os.unlink(fpath)
            except:
                pass
except:
    pass


# ============================================================
# Logger
# ============================================================
def log(level, msg, data=None):
    """Imprimir log con timestamp."""
    levels = {'error': 0, 'info': 1, 'debug': 2}
    if levels.get(level, 0) <= levels.get(config.get('logLevel', 'info'), 1):
        ts = datetime.now().strftime('%H:%M:%S')
        prefix = {'error': '[ERROR]', 'info': '[OK]', 'debug': '[DEBUG]', 'warn': '[WARN]'}.get(level, '[INFO]')
        line = '{} {} {}'.format(ts, prefix, msg)
        if data is not None:
            line += ' ' + str(data)
        print(line)
        sys.stdout.flush()


# ============================================================
# Deteccion de impresoras Windows
# ============================================================
def try_import_win32print():
    """Intentar importar win32print. Retorna None si no esta disponible."""
    try:
        import win32print
        return win32print
    except ImportError:
        return None


def list_printers():
    """Listar impresoras instaladas en Windows."""
    printers = []

    # METODO 1: PowerShell (mas confiable, funciona en todas las versiones de Windows)
    try:
        result = subprocess.check_output(
            'powershell -NoProfile -Command "Get-WmiObject Win32_Printer | Select-Object Name,PortName,DriverName | ConvertTo-Json"',
            shell=True, stderr=subprocess.STDOUT, timeout=10
        )
        data = json.loads(result.decode('mbcs', errors='replace'))
        items = data if isinstance(data, list) else [data]
        for p in items:
            name = p.get('Name', '')
            if name:
                printers.append({
                    'name': name,
                    'description': p.get('DriverName', name),
                    'port': p.get('PortName', '')
                })
        if printers:
            return printers
    except Exception as e:
        log('debug', 'PowerShell listado fallo: {}'.format(e))

    # METODO 2: win32print con nivel 4 (formato simple: pPrinterName, pPortName)
    win32print = try_import_win32print()
    if win32print:
        try:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            for item in win32print.EnumPrinters(flags, None, 4):
                info = item if isinstance(item, (list, tuple)) else list(item)
                name = info[0] if len(info) > 0 else ''
                port = info[1] if len(info) > 1 else ''
                if name and not name.startswith('pPrinter'):
                    printers.append({'name': name, 'description': name, 'port': port})
            if printers:
                return printers
        except Exception as e:
            log('debug', 'win32print nivel 4 fallo: {}'.format(e))

        # METODO 3: win32print con nivel 1 (formato: Flags, Desc, Name, Comment)
        try:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            for item in win32print.EnumPrinters(flags, None, 1):
                info = item if isinstance(item, (list, tuple)) else list(item)
                name = info[2] if len(info) > 2 else ''
                desc = info[1] if len(info) > 1 else name
                if name and not name.startswith('p'):
                    printers.append({'name': name, 'description': desc, 'port': ''})
            if printers:
                return printers
        except Exception as e:
            log('error', 'Error listando impresoras: {}'.format(e))

    # METODO 4: Fallback PowerShell simple (sin JSON)
    try:
        result = subprocess.check_output(
            'powershell -NoProfile -Command "Get-WmiObject Win32_Printer | Select-Object -ExpandProperty Name"',
            shell=True, stderr=subprocess.STDOUT, timeout=10
        )
        names = result.decode('mbcs', errors='replace').strip().split('\r\n')
        return [{'name': n.strip(), 'description': n.strip(), 'port': ''} for n in names if n.strip()]
    except Exception as e:
        log('error', 'Error listando impresoras (fallback): {}'.format(e))
        return []

    return printers


def get_printer_port(printer_name):
    """Obtener el puerto de la impresora (ej: USB001, LPT1, etc)."""
    win32print = try_import_win32print()
    if win32print:
        try:
            hPrinter = win32print.OpenPrinter(printer_name)
            try:
                printer_info = {}
                win32print.GetPrinter(hPrinter, 2, printer_info)
                return printer_info.get('pPortName', '')
            finally:
                win32print.ClosePrinter(hPrinter)
        except:
            pass
    return ''


def get_printer_driver(printer_name):
    """Obtener el nombre del driver de la impresora."""
    win32print = try_import_win32print()
    if win32print:
        try:
            hPrinter = win32print.OpenPrinter(printer_name)
            try:
                printer_info = {}
                win32print.GetPrinter(hPrinter, 2, printer_info)
                return printer_info.get('pDriverName', '')
            finally:
                win32print.ClosePrinter(hPrinter)
        except:
            pass
    return ''


# ============================================================
# Metodos de impresion RAW
# ============================================================

def _print_method_a(printer_name, data):
    """
    METODO A: win32print RAW SIN controles de pagina.
    StartDoc > WritePrinter > EndDoc (sin StartPage/EndPage)
    Ideal para impresoras de etiquetas que no usan paginas.
    """
    win32print = try_import_win32print()
    if not win32print:
        return None  # win32print no disponible

    hPrinter = None
    try:
        hPrinter = win32print.OpenPrinter(printer_name)
        # DOC_INFO_1: [pDocName, pOutputFile, pDatatype]
        # 'RAW' = enviar bytes directos al puerto sin procesar
        docInfo = ('PrinterBridge', None, 'RAW')
        win32print.StartDocPrinter(hPrinter, 1, docInfo)
        written = win32print.WritePrinter(hPrinter, data)
        win32print.EndDocPrinter(hPrinter)
        log('info', 'Metodo A OK - {} bytes escritos'.format(written))
        return {'method': 'A', 'success': True, 'bytes_written': written}
    except Exception as e:
        return {'method': 'A', 'success': False, 'error': str(e)}
    finally:
        if hPrinter:
            try:
                win32print.ClosePrinter(hPrinter)
            except:
                pass


def _print_method_b(printer_name, data):
    """
    METODO B: win32print RAW CON controles de pagina.
    StartDoc > StartPage > WritePrinter > EndPage > EndDoc
    Metodo estandar Windows para impresoras convencionales.
    """
    win32print = try_import_win32print()
    if not win32print:
        return None

    hPrinter = None
    try:
        hPrinter = win32print.OpenPrinter(printer_name)
        docInfo = ('PrinterBridge', None, 'RAW')
        win32print.StartDocPrinter(hPrinter, 1, docInfo)
        try:
            win32print.StartPagePrinter(hPrinter)
            try:
                written = win32print.WritePrinter(hPrinter, data)
                log('info', 'Metodo B OK - {} bytes escritos'.format(written))
                return {'method': 'B', 'success': True, 'bytes_written': written}
            finally:
                try:
                    win32print.EndPagePrinter(hPrinter)
                except:
                    pass
        finally:
            try:
                win32print.EndDocPrinter(hPrinter)
            except:
                pass
    except Exception as e:
        return {'method': 'B', 'success': False, 'error': str(e)}
    finally:
        if hPrinter:
            try:
                win32print.ClosePrinter(hPrinter)
            except:
                pass


def _print_method_c(printer_name, data, port_name=''):
    """
    METODO C: Escritura directa al puerto.
    Abre el puerto de la impresora como archivo binario y escribe.
    Equivalente a 'copy archivo puerto /b' pero via Python.
    """
    # Obtener el puerto si no se proporciono
    if not port_name:
        port_name = get_printer_port(printer_name)

    if not port_name:
        return {'method': 'C', 'success': False, 'error': 'No se pudo determinar el puerto'}

    # Intentar diferentes formas de abrir el puerto
    port_paths = [
        port_name,                              # ej: USB001, LPT1
        '\\\\.\\{}'.format(port_name),           # \\.\USB001
        'PRN:',                                  # Puerto de impresora por defecto
    ]

    for port_path in port_paths:
        try:
            # Python 2/3 compatible file open in binary mode
            if sys.version_info[0] >= 3:
                f = open(port_path, 'wb')
            else:
                f = open(port_path, 'wb')
            try:
                f.write(data)
                f.flush()
                log('info', 'Metodo C OK - {} bytes escritos a {}'.format(len(data), port_path))
                return {'method': 'C', 'success': True, 'bytes_written': len(data), 'port': port_path}
            finally:
                f.close()
        except Exception as e:
            log('debug', 'Metodo C fallo con {}: {}'.format(port_path, e))
            continue

    return {'method': 'C', 'success': False, 'error': 'No se pudo abrir el puerto: {}'.format(port_name)}


def _print_method_d(ip, data, port=9100):
    """
    METODO D: Envio TCP directo a la IP de la impresora.
    Muchas impresoras de etiquetas (incluida Datamax M-4206 con tarjeta de red)
    aceptan conexiones TCP en el puerto 9100.
    """
    if not ip:
        return {'method': 'D', 'success': False, 'error': 'No hay IP configurada para la impresora'}

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((ip, port))
        sock.sendall(data)
        sock.close()
        log('info', 'Metodo D OK - {} bytes enviados a {}:{}'.format(len(data), ip, port))
        return {'method': 'D', 'success': True, 'bytes_written': len(data), 'ip': ip}
    except Exception as e:
        return {'method': 'D', 'success': False, 'error': str(e)}


def scan_printer_network(port=9100, timeout=0.5):
    """
    Escanear la red local buscando la impresora Datamax en el puerto 9100.
    Retorna la IP si la encuentra, None si no.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        return None

    parts = local_ip.split('.')
    if len(parts) != 4:
        return None

    base = '.'.join(parts[:3])

    log('info', 'Escaneando red {}.0/24 puerto {}...'.format(base, port))

    found_ips = []
    for i in range(1, 255):
        ip = '{}.{}'.format(base, i)
        if ip == local_ip:
            continue
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            if result == 0:
                found_ips.append(ip)
                log('info', '  Encontrado: {}:{}'.format(ip, port))
        except:
            pass

    if found_ips:
        return found_ips
    return None


def print_raw(printer_name, data):
    """
    Imprimir datos RAW (DPL/ZPL) en la impresora.

    Prueba multiples metodos hasta que uno funcione.
    El metodo exitoso se guarda en la configuracion para proximas impresiones.

    Args:
        printer_name: Nombre exacto de la impresora en Windows
        data: bytes o str con los datos a imprimir

    Returns:
        dict con {success: bool, method: str, bytes_written: int, error: str}
    """
    # Convertir a bytes si es string
    if isinstance(data, str):
        data = data.encode('latin-1', errors='replace')

    if len(data) == 0:
        return {'success': False, 'error': 'Datos vacios', 'method': 'none'}

    # Guardar datos en archivo temporal para diagnostico
    try:
        temp_path = os.path.join(TEMP_DIR, 'last-print.raw')
        with open(temp_path, 'wb') as f:
            f.write(data)
        log('debug', 'Datos guardados en {}'.format(temp_path))
    except:
        pass

    win32print = try_import_win32print()
    if not win32print:
        # Si no hay win32print, intentar metodo D (TCP directo) o C (archivo)
        ip = config.get('printerIP', '')
        if ip:
            result = _print_method_d(ip, data)
            return result
        return {
            'success': False,
            'error': 'pywin32 no esta instalado. Ejecuta: pip install pywin32',
            'method': 'none'
        }

    method = config.get('printMethod', 'auto')

    # Si hay un metodo especifico configurado, intentar solo ese
    if method != 'auto':
        log('info', 'Usando metodo configurado: {}'.format(method))
        if method == 'A':
            result = _print_method_a(printer_name, data)
        elif method == 'B':
            result = _print_method_b(printer_name, data)
        elif method == 'C':
            port = get_printer_port(printer_name)
            result = _print_method_c(printer_name, data, port)
        elif method == 'D':
            ip = config.get('printerIP', '')
            result = _print_method_d(ip, data)
        else:
            result = None

        if result and result.get('success'):
            return result

        log('warn', 'Metodo {} fallo, intentando otros...'.format(method))

    # MODO AUTO: probar metodos en orden
    log('info', 'Modo AUTO - probando metodos de impresion...')

    # Metodo A: RAW sin page controls (mejor para impresoras de etiquetas)
    result_a = _print_method_a(printer_name, data)
    if result_a and result_a.get('success'):
        config['printMethod'] = 'A'
        save_config(config)
        return result_a

    # Metodo B: RAW con page controls
    result_b = _print_method_b(printer_name, data)
    if result_b and result_b.get('success'):
        config['printMethod'] = 'B'
        save_config(config)
        return result_b

    # Metodo C: Escritura directa al puerto
    port = get_printer_port(printer_name)
    result_c = _print_method_c(printer_name, data, port)
    if result_c and result_c.get('success'):
        config['printMethod'] = 'C'
        save_config(config)
        return result_c

    # Metodo D: TCP directo a IP de la impresora
    ip = config.get('printerIP', '')
    if ip:
        result_d = _print_method_d(ip, data)
        if result_d and result_d.get('success'):
            config['printMethod'] = 'D'
            save_config(config)
            return result_d

    # Ningun metodo funciono - reportar errores
    errors = []
    for name, result in [('A', result_a), ('B', result_b), ('C', result_c)]:
        if result:
            errors.append('Metodo {}: {}'.format(name, result.get('error', 'fallo')))

    ip = config.get('printerIP', '')
    if ip:
        errors.append('Metodo D: IP {} no configurada o no responde'.format(ip))
    else:
        errors.append('Metodo D: No hay IP de impresora configurada')

    log('error', 'Todos los metodos fallaron:')
    for err in errors:
        log('error', '  {}'.format(err))

    return {
        'success': False,
        'error': 'Ningun metodo de impresion funciono. Ver diagnostico.',
        'method': 'none',
        'details': errors
    }


def test_all_methods(printer_name, data=None):
    """
    Probar TODOS los metodos de impresion y reportar resultados.
    Usado para diagnostico - no guarda configuracion.
    """
    if data is None:
        now = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        data = (
            "<STX><SI>$<SI>\n"
            "<SI>H0080o0030<SI>\n"
            "<SI>f220<SI>\n"
            "<SI>1f100<SI>\n"
            "<SI>H0100o0140<SI>\n"
            "<SI>f250<SI>\n"
            "<SI>1f100<SI>\n"
            "<SI>c0000<SI>\n"
            "<SI>1911005000100TEST OK<SI>\n"
            "<SI>Q0001<SI>\n"
            "<SI>E<SI>\n"
        )

    if isinstance(data, str):
        data = data.encode('latin-1', errors='replace')

    results = {}
    port = get_printer_port(printer_name)

    log('info', 'Probando todos los metodos de impresion...')

    # Metodo A
    try:
        r = _print_method_a(printer_name, data)
        results['A'] = r
        time.sleep(1)  # Pausa entre metodos
    except Exception as e:
        results['A'] = {'method': 'A', 'success': False, 'error': str(e)}

    # Metodo B
    try:
        r = _print_method_b(printer_name, data)
        results['B'] = r
        time.sleep(1)
    except Exception as e:
        results['B'] = {'method': 'B', 'success': False, 'error': str(e)}

    # Metodo C
    try:
        r = _print_method_c(printer_name, data, port)
        results['C'] = r
        time.sleep(1)
    except Exception as e:
        results['C'] = {'method': 'C', 'success': False, 'error': str(e)}

    # Metodo D - solo si hay IP configurada
    ip = config.get('printerIP', '')
    if ip:
        try:
            r = _print_method_d(ip, data)
            results['D'] = r
        except Exception as e:
            results['D'] = {'method': 'D', 'success': False, 'error': str(e)}
    else:
        results['D'] = {'method': 'D', 'success': False, 'error': 'Sin IP configurada (configured: false)'}

    # Info extra
    driver = get_printer_driver(printer_name)
    results['info'] = {
        'printer_name': printer_name,
        'port': port,
        'driver': driver,
        'printer_ip': ip,
        'data_size': len(data),
        'data_hex': data[:50].hex() + '...' if len(data) > 50 else data.hex()
    }

    return results


# ============================================================
# Servidor TCP (puerto 9100) - Recibe ZPL/DPL del sistema
# ============================================================
print_count = 0
last_print_time = ''
last_print_error = ''
last_print_method = ''
lock = threading.Lock()


def handle_tcp_client(conn, addr):
    """Manejar una conexion TCP entrante."""
    global print_count, last_print_time, last_print_error, last_print_method

    remote = '{}:{}'.format(addr[0], addr[1])
    log('info', 'Conexion entrante desde {}'.format(remote))

    chunks = []
    total_bytes = 0

    try:
        conn.settimeout(30)  # 30 segundos

        while True:
            try:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                total_bytes += len(chunk)
                log('debug', 'Recibidos {} bytes (total: {})'.format(len(chunk), total_bytes))
            except socket.timeout:
                log('error', 'Timeout esperando datos')
                break
            except Exception as e:
                log('error', 'Error recibiendo datos: {}'.format(e))
                break
    finally:
        try:
            conn.close()
        except:
            pass

    if total_bytes == 0:
        log('info', 'Conexion cerrada sin datos')
        return

    printer_name = config.get('printerName', '')
    if not printer_name:
        log('error', 'No hay impresora configurada')
        last_print_error = 'No hay impresora configurada'
        return

    data = b''.join(chunks)

    # Determinar tipo de contenido para el log
    sample = data[:100].decode('latin-1', errors='replace') if data else ''
    tipo = 'RAW'
    if sample.startswith('^XA'):
        tipo = 'ZPL'
    elif '<STX>' in sample[:20] or (len(sample) > 0 and sample[0] == '\x02'):
        tipo = 'DPL (Datamax)'
    elif any(cmd in sample[:50] for cmd in ['M1084', 'O0220', 'SO', '1K', '1f100']):
        tipo = 'DPL (Datamax)'

    log('info', 'Recibido {} bytes ({}) desde {}'.format(total_bytes, tipo, remote))

    with lock:
        result = print_raw(printer_name, data)
        print_count += 1
        last_print_time = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        last_print_method = result.get('method', '?')

        if result['success']:
            log('info', 'Impresion #{} exitosa [Metodo {}] ({} bytes escritos)'.format(
                print_count, result.get('method', '?'), result.get('bytes_written', '?')))
            last_print_error = ''
        else:
            log('error', 'Impresion #{} fallida: {}'.format(print_count, result.get('error', '?')))
            last_print_error = result.get('error', 'Error desconocido')


def start_tcp_server():
    """Iniciar servidor TCP para recibir datos de impresion."""
    port = config.get('tcpPort', 9100)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind(('0.0.0.0', port))
    except Exception as e:
        err_str = str(e)
        if 'Address already in use' in err_str or 'EADDRINUSE' in err_str or '10048' in err_str:
            print('')
            print('========================================================')
            print('  ERROR: Puerto {} ya esta en uso.'.format(port))
            print('  Puede haber otra instancia del bridge corriendo.')
            print('  Ejecuta: taskkill /F /IM python.exe')
            print('========================================================')
            print('')
        else:
            print('ERROR al bindear puerto {}: {}'.format(port, e))
        sys.exit(1)

    server.listen(5)
    server.settimeout(1)  # Para poder cerrar limpiamente

    log('info', 'Servidor TCP escuchando en 0.0.0.0:{}'.format(port))

    while running:
        try:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_tcp_client, args=(conn, addr), daemon=True)
            t.start()
        except socket.timeout:
            continue
        except Exception as e:
            if not running:
                break
            log('error', 'Error en servidor TCP: {}'.format(e))


# ============================================================
# Servidor HTTP (puerto 9101) - Panel de control web
# ============================================================
def generate_dashboard():
    """Generar HTML del panel de control."""
    printers = list_printers()
    printer_options = ''
    for p in printers:
        selected = ' selected' if p['name'] == config.get('printerName', '') else ''
        name_esc = p['name'].replace('&', '&amp;').replace('"', '&quot;')
        printer_options += '<option value="{}"{}>{} ({} - {})</option>\n'.format(
            name_esc, selected,
            p['name'].replace('&', '&amp;').replace('<', '&lt;'),
            p.get('port', '?'),
            p.get('description', '?')
        )

    printer_cfg = config.get('printerName', 'Sin configurar')
    printer_cfg = printer_cfg.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    printer_ip = config.get('printerIP', '')
    print_method = config.get('printMethod', 'auto')
    tcp_port = config.get('tcpPort', 9100)
    http_port = config.get('httpPort', 9101)

    html = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Printer Bridge v3.1 - Solemar Alimentaria</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #f5f5f4; color: #292524; padding: 20px; }
    .container { max-width: 760px; margin: 0 auto; }
    h1 { font-size: 22px; margin-bottom: 4px; color: #1c1917; }
    .subtitle { color: #78716c; margin-bottom: 20px; font-size: 13px; }
    .card { background: white; border-radius: 10px; padding: 20px; margin-bottom: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
    .card h2 { font-size: 15px; margin-bottom: 14px; color: #1c1917; }
    .status { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
    .status.online { background: #dcfce7; color: #166534; }
    .status .dot { width: 7px; height: 7px; border-radius: 50%; background: #22c55e; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; background: #fef3c7; color: #92400e; }
    select, input[type=text] { width: 100%; padding: 9px 12px; border: 1px solid #d6d3d1; border-radius: 8px; font-size: 13px; background: white; cursor: pointer; margin-bottom: 10px; }
    select:focus, input[type=text]:focus { outline: none; border-color: #f59e0b; }
    label { font-size: 12px; color: #78716c; display: block; margin-bottom: 4px; font-weight: 600; }
    .btn { padding: 9px 18px; border: none; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; }
    .btn-primary { background: #f59e0b; color: white; }
    .btn-primary:hover { background: #d97706; }
    .btn-danger { background: #ef4444; color: white; }
    .btn-danger:hover { background: #dc2626; }
    .btn-secondary { background: #e7e5e4; color: #292524; }
    .btn-secondary:hover { background: #d6d3d1; }
    .btn-small { padding: 6px 12px; font-size: 12px; }
    .btn-group { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
    .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .info-item { padding: 10px; background: #fafaf9; border-radius: 8px; }
    .info-item .label { font-size: 11px; color: #78716c; margin-bottom: 3px; }
    .info-item .value { font-size: 16px; font-weight: 700; color: #1c1917; word-break: break-all; }
    .info-item .value.small { font-size: 13px; font-weight: 500; }
    .instructions { background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 14px; font-size: 12px; line-height: 1.7; }
    .instructions h3 { color: #92400e; margin-bottom: 6px; font-size: 13px; }
    .instructions code { background: #fef3c7; padding: 1px 5px; border-radius: 3px; font-size: 11px; }
    .instructions ol { padding-left: 18px; }
    .instructions li { margin-bottom: 4px; }
    .msg { padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-top: 10px; display: none; }
    .msg.success { display: block; background: #dcfce7; color: #166534; }
    .msg.error { display: block; background: #fef2f2; color: #991b1b; }
    .toast { position: fixed; bottom: 20px; right: 20px; padding: 10px 18px; border-radius: 8px; color: white; font-weight: 600; font-size: 13px; opacity: 0; transition: opacity 0.3s; z-index: 999; }
    .toast.success { background: #22c55e; }
    .toast.error { background: #ef4444; }
    .format-tabs { display: flex; gap: 4px; margin-bottom: 10px; }
    .format-tab { padding: 6px 12px; border: 1px solid #d6d3d1; border-radius: 6px; font-size: 12px; cursor: pointer; background: white; }
    .format-tab.active { background: #f59e0b; color: white; border-color: #f59e0b; }
    .diag-box { background: #1c1917; color: #a8a29e; padding: 14px; border-radius: 8px; font-family: Consolas, monospace; font-size: 11px; max-height: 400px; overflow-y: auto; display: none; white-space: pre-wrap; word-break: break-all; margin-top: 10px; }
    .method-row { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid #f5f5f4; }
    .method-row:last-child { border-bottom: none; }
    .method-status { width: 10px; height: 10px; border-radius: 50%; }
    .method-status.ok { background: #22c55e; }
    .method-status.fail { background: #ef4444; }
    .method-status.skip { background: #d6d3d1; }
    .method-name { font-weight: 600; font-size: 13px; min-width: 100px; }
    .method-detail { font-size: 11px; color: #78716c; }
    .row { display: flex; gap: 10px; }
    .row > * { flex: 1; }
    .section-sep { border-top: 1px solid #e7e5e4; margin: 16px 0; }
    @media (max-width: 600px) {
      .info-grid { grid-template-columns: 1fr; }
      .btn-group { flex-direction: column; }
      .btn { width: 100%; text-align: center; }
      .row { flex-direction: column; }
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>Printer Bridge v3.1</h1>
    <p class="subtitle">Solemar Alimentaria &mdash; TCP :9100 &rarr; Impresora Datamax Mark II</p>

    <div class="card">
      <h2><span class="status online"><span class="dot"></span> Conectado</span></h2>
      <div class="info-grid">
        <div class="info-item">
          <div class="label">Puerto TCP</div>
          <div class="value">""" + str(tcp_port) + """</div>
        </div>
        <div class="info-item">
          <div class="label">Impresiones</div>
          <div class="value" id="printCount">0</div>
        </div>
        <div class="info-item">
          <div class="label">Ultima impresion</div>
          <div class="value small" id="lastPrint">&mdash;</div>
        </div>
        <div class="info-item">
          <div class="label">Impresora</div>
          <div class="value small" id="currentPrinter">""" + printer_cfg + """</div>
        </div>
        <div class="info-item">
          <div class="label">Metodo de impresion</div>
          <div class="value small" id="currentMethod">""" + str(print_method) + """ <span class="badge" id="methodBadge">""" + (print_method.upper() if print_method != 'auto' else 'AUTO') + """</span></div>
        </div>
        <div class="info-item">
          <div class="label">IP impresora (TCP)</div>
          <div class="value small" id="currentIP">""" + (printer_ip if printer_ip else '<em>no configurada</em>') + """</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Configurar Impresora</h2>
      <select id="printerSelect">
        <option value="">-- Seleccionar impresora --</option>
""" + printer_options + """
      </select>
      <div class="row">
        <div>
          <label>IP directa de la impresora (TCP port 9100)</label>
          <input type="text" id="printerIP" placeholder="ej: 192.168.0.50 (opcional)" value=\"""" + json.dumps(printer_ip) + """\">
        </div>
        <div>
          <label>Metodo de impresion</label>
          <select id="printMethodSelect">
            <option value="auto" """ + ('selected' if print_method == 'auto' else '') + """>AUTO (probar todos)</option>
            <option value="A" """ + ('selected' if print_method == 'A' else '') + """>A - RAW sin pagina</option>
            <option value="B" """ + ('selected' if print_method == 'B' else '') + """>B - RAW con pagina</option>
            <option value="C" """ + ('selected' if print_method == 'C' else '') + """>C - Puerto directo</option>
            <option value="D" """ + ('selected' if print_method == 'D' else '') + """>D - TCP a IP</option>
          </select>
        </div>
      </div>
      <div class="btn-group">
        <button class="btn btn-primary" onclick="savePrinter()">Guardar configuracion</button>
        <button class="btn btn-secondary" onclick="loadPrinters()">Actualizar lista</button>
      </div>
      <div class="msg" id="saveMsg"></div>
    </div>

    <div class="card">
      <h2>Probar Impresion</h2>
      <p style="font-size:12px; color:#78716c; margin-bottom:10px">
        Imprime una etiqueta de prueba usando el metodo configurado.
      </p>
      <div class="format-tabs">
        <button class="format-tab active" onclick="setFormat('dpl', this)">DPL (Datamax)</button>
        <button class="format-tab" onclick="setFormat('zpl', this)">ZPL (Zebra)</button>
      </div>
      <div class="btn-group">
        <button class="btn btn-primary" id="testBtn" onclick="testPrint()">Imprimir prueba</button>
        <button class="btn btn-secondary" onclick="testAllMethods()">Probar TODOS los metodos</button>
      </div>
      <div class="msg" id="testMsg"></div>
      <div id="methodsResult" style="margin-top:10px; display:none;">
        <div style="font-size:12px; font-weight:600; color:#78716c; margin-bottom:6px;">Resultados por metodo:</div>
        <div id="methodsList"></div>
      </div>
    </div>

    <div class="card">
      <h2>Diagnostico Avanzado</h2>
      <div class="btn-group">
        <button class="btn btn-secondary" onclick="runDiagnose()">Ejecutar diagnostico</button>
        <button class="btn btn-secondary" onclick="scanNetwork()">Buscar impresora en la red</button>
      </div>
      <div class="diag-box" id="diagBox"></div>
    </div>

    <div class="card">
      <h2>Solucion de Problemas</h2>
      <div class="instructions">
        <h3>Si la impresora no responde:</h3>
        <ol>
          <li>Hace clic en <strong>"Probar TODOS los metodos"</strong> para ver cual funciona</li>
          <li>Si ninguno funciona via USB, prueba configurar la <strong>IP directa</strong> (Metodo D):
            <ul>
              <li>La Datamax M-4206 Mark II puede tener tarjeta de red interna</li>
              <li>En la impresora: Menu &rarr; Communications &rarr; IP Address</li>
              <li>Ingresa esa IP en el campo "IP directa" de arriba</li>
              <li>O usa "Buscar impresora en la red" para escanear</li>
            </ul>
          </li>
          <li>Alternativa USB: Instalar driver <strong>"Generico / Solo texto"</strong>:
            <ul>
              <li>Panel de control &rarr; Dispositivos e impresoras</li>
              <li>Agregar impresora &rarr; Agregar impresora local</li>
              <li>Usar puerto existente: USB001</li>
              <li>Driver: "Generic / Text Only" (o "Generico / Solo texto")</li>
              <li>Seleccionar ESTA impresora en el dropdown de arriba</li>
            </ul>
          </li>
          <li>Asegurate que la impresora no este <strong>en pausa</strong> ni con <strong>papel atascado</strong></li>
        </ol>
      </div>
    </div>

    <div class="card">
      <h2>Configurar en TrazAlan</h2>
      <div class="instructions">
        <h3>Para que el sistema imprima a esta PC:</h3>
        <p><strong>1.</strong> Verifica la IP de esta PC: <code>ipconfig</code></p>
        <p><strong>2.</strong> En TrazAlan ir a <strong>Configuracion &rarr; Impresoras</strong></p>
        <p><strong>3.</strong> Crear/editar impresora:</p>
        <p>&nbsp;&nbsp; Puerto: <strong>RED</strong></p>
        <p>&nbsp;&nbsp; IP: <strong>la IP de esta PC</strong> (ej: 192.168.0.113)</p>
        <p>&nbsp;&nbsp; Marca: <strong>DATAMAX</strong></p>
        <p>&nbsp;&nbsp; Modelo: <strong>Mark II</strong></p>
        <p>&nbsp;&nbsp; DPI: <strong>203</strong></p>
        <p><strong>4.</strong> Puerto TCP: <strong>""" + str(tcp_port) + """</strong></p>
      </div>
    </div>
  </div>

  <div class="toast" id="toast"></div>

  <script>
    var testFormat = 'dpl';

    function showToast(msg, type) {
      var t = document.getElementById('toast');
      t.textContent = msg;
      t.className = 'toast ' + type;
      t.style.opacity = '1';
      setTimeout(function() { t.style.opacity = '0'; }, 3000);
    }

    function setFormat(fmt, btn) {
      testFormat = fmt;
      var tabs = document.querySelectorAll('.format-tab');
      for (var i = 0; i < tabs.length; i++) tabs[i].className = 'format-tab';
      btn.className = 'format-tab active';
    }

    function loadPrinters() {
      fetch('/api/printers').then(function(r) { return r.json(); }).then(function(data) {
        var sel = document.getElementById('printerSelect');
        sel.innerHTML = '<option value="">-- Seleccionar impresora --</option>';
        data.printers.forEach(function(p) {
          var opt = document.createElement('option');
          opt.value = p.name;
          opt.textContent = p.name + ' (' + (p.port || '?') + ' - ' + (p.description || '?') + ')';
          if (p.name === data.configured) opt.selected = true;
          sel.appendChild(opt);
        });
      }).catch(function() {
        showToast('Error al cargar impresoras', 'error');
      });
    }

    function savePrinter() {
      var name = document.getElementById('printerSelect').value;
      var ip = document.getElementById('printerIP').value.trim();
      var method = document.getElementById('printMethodSelect').value;
      if (!name) { showToast('Selecciona una impresora', 'error'); return; }
      fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({printerName: name, printerIP: ip, printMethod: method})
      }).then(function(r) { return r.json(); }).then(function(data) {
        if (data.success) {
          document.getElementById('currentPrinter').textContent = name;
          document.getElementById('currentIP').textContent = ip || 'no configurada';
          document.getElementById('currentMethod').innerHTML = method + ' <span class="badge">' + method.toUpperCase() + '</span>';
          showToast('Configuracion guardada', 'success');
          document.getElementById('saveMsg').className = 'msg success';
          document.getElementById('saveMsg').textContent = 'Guardado OK';
        } else {
          showToast('Error al guardar', 'error');
        }
      });
    }

    function testPrint() {
      var msgBox = document.getElementById('testMsg');
      var btn = document.getElementById('testBtn');
      msgBox.style.display = 'none';
      var printerName = document.getElementById('currentPrinter').textContent;
      if (!printerName || printerName === 'Sin configurar') {
        showToast('Configura una impresora primero', 'error');
        return;
      }
      btn.disabled = true;
      btn.textContent = 'Imprimiendo...';
      fetch('/api/test', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({format: testFormat})
      }).then(function(r) { return r.json(); }).then(function(data) {
        btn.disabled = false;
        btn.textContent = 'Imprimir prueba';
        if (data.success) {
          showToast('Prueba enviada [Metodo ' + (data.method || '?') + ']', 'success');
          msgBox.className = 'msg success';
          msgBox.textContent = 'Etiqueta enviada via Metodo ' + (data.method || '?') + ' (' + (data.bytes_written || '?') + ' bytes)';
        } else {
          showToast('Error en la prueba', 'error');
          msgBox.className = 'msg error';
          msgBox.textContent = 'Error [Metodo ' + (data.method || '?') + ']: ' + (data.error || 'Desconocido');
        }
      }).catch(function(e) {
        btn.disabled = false;
        btn.textContent = 'Imprimir prueba';
        showToast('Error de conexion', 'error');
      });
    }

    function testAllMethods() {
      var msgBox = document.getElementById('testMsg');
      var btn = document.getElementById('testBtn');
      msgBox.style.display = 'none';
      var printerName = document.getElementById('currentPrinter').textContent;
      if (!printerName || printerName === 'Sin configurar') {
        showToast('Configura una impresora primero', 'error');
        return;
      }
      showToast('Probando todos los metodos...', 'success');
      fetch('/api/test-all', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
      }).then(function(r) { return r.json(); }).then(function(data) {
        var box = document.getElementById('methodsResult');
        var list = document.getElementById('methodsList');
        box.style.display = 'block';
        list.innerHTML = '';

        var methods = ['A', 'B', 'C', 'D'];
        var anyOk = false;
        methods.forEach(function(m) {
          var r = data[m] || {};
          var ok = r.success;
          if (ok) anyOk = true;
          var statusClass = ok ? 'ok' : 'fail';
          var statusTitle = ok ? 'FUNCIONO' : 'FALLO';
          var detail = ok ? (r.bytes_written + ' bytes') : (r.error || 'fallo');

          var row = document.createElement('div');
          row.className = 'method-row';
          row.innerHTML = '<span class="method-status ' + statusClass + '" title="' + statusTitle + '"></span>'
            + '<span class="method-name">Metodo ' + m + '</span>'
            + '<span class="method-detail">' + detail + '</span>';
          list.appendChild(row);
        });

        if (data.info) {
          var infoRow = document.createElement('div');
          infoRow.className = 'method-row';
          infoRow.style.marginTop = '8px';
          infoRow.style.borderTop = '1px solid #e7e5e4';
          infoRow.style.paddingTop = '8px';
          infoRow.innerHTML = '<span class="method-detail" style="font-size:11px; color:#78716c;">'
            + 'Puerto: ' + (data.info.port || '?')
            + ' | Driver: ' + (data.info.driver || '?')
            + ' | IP: ' + (data.info.printer_ip || 'no configurada')
            + '</span>';
          list.appendChild(infoRow);
        }

        if (anyOk) {
          showToast('Al menos un metodo funciono!', 'success');
        } else {
          showToast('Ningun metodo funciono', 'error');
        }
      }).catch(function(e) {
        showToast('Error: ' + e.message, 'error');
      });
    }

    function refreshStats() {
      fetch('/api/config').then(function(r) { return r.json(); }).then(function(data) {
        document.getElementById('printCount').textContent = data.printCount || 0;
        document.getElementById('lastPrint').textContent = data.lastPrintTime || '-';
        document.getElementById('currentPrinter').textContent = data.printerName || 'Sin configurar';
        document.getElementById('currentMethod').innerHTML = (data.printMethod || 'auto') + ' <span class="badge">' + (data.printMethod || 'auto').toUpperCase() + '</span>';
        document.getElementById('currentIP').textContent = data.printerIP || 'no configurada';
      }).catch(function() {});
    }

    function runDiagnose() {
      var box = document.getElementById('diagBox');
      box.style.display = 'block';
      box.textContent = 'Ejecutando diagnostico...';
      fetch('/api/diagnose').then(function(r) { return r.json(); }).then(function(data) {
        box.textContent = JSON.stringify(data, null, 2);
      }).catch(function(e) {
        box.textContent = 'Error: ' + e.message;
      });
    }

    function scanNetwork() {
      var box = document.getElementById('diagBox');
      box.style.display = 'block';
      box.textContent = 'Escaneando red local puerto 9100...\nEsto puede tardar ~2 minutos...\n';
      fetch('/api/scan-network').then(function(r) { return r.json(); }).then(function(data) {
        if (data.found && data.found.length > 0) {
          box.textContent = 'IMPRESORAS ENCONTRADAS EN LA RED:\n\n';
          data.found.forEach(function(ip) {
            box.textContent += '  ' + ip + ':9100\n';
          });
          box.textContent += '\nConfigura la IP en el campo de arriba (Metodo D).\n';
          showToast('Impresora encontrada en la red!', 'success');
        } else {
          box.textContent = JSON.stringify(data, null, 2);
          showToast('No se encontraron impresoras en la red', 'error');
        }
      }).catch(function(e) {
        box.textContent = 'Error: ' + e.message;
      });
    }

    loadPrinters();
    setInterval(refreshStats, 5000);
  </script>
</body>
</html>"""
    return html


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler para el panel de control."""

    def log_message(self, format, *args):
        """Silenciar logs de HTTP."""
        pass

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        try:
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path == '/api/printers':
            printers = list_printers()
            self.send_json({
                'printers': printers,
                'configured': config.get('printerName', '')
            })
        elif self.path == '/api/config':
            self.send_json({
                'printerName': config.get('printerName', ''),
                'printerIP': config.get('printerIP', ''),
                'printMethod': config.get('printMethod', 'auto'),
                'tcpPort': config.get('tcpPort', 9100),
                'httpPort': config.get('httpPort', 9101),
                'logLevel': config.get('logLevel', 'info'),
                'printCount': print_count,
                'lastPrintTime': last_print_time,
                'lastPrintMethod': last_print_method,
                'lastPrintError': last_print_error,
                'status': 'running',
                'python_version': sys.version,
                'platform': sys.platform
            })
        elif self.path == '/api/diagnose':
            win32print = try_import_win32print()
            pname = config.get('printerName', '')
            pport = get_printer_port(pname) if pname else ''
            pdriver = get_printer_driver(pname) if pname else ''
            self.send_json({
                'python_version': sys.version,
                'python_path': sys.executable,
                'platform': sys.platform,
                'pywin32_installed': win32print is not None,
                'config_path': CONFIG_PATH,
                'config_exists': os.path.exists(CONFIG_PATH),
                'temp_dir': TEMP_DIR,
                'temp_dir_exists': os.path.exists(TEMP_DIR),
                'printer_name': pname,
                'printer_port': pport,
                'printer_driver': pdriver,
                'printer_ip': config.get('printerIP', ''),
                'print_method': config.get('printMethod', 'auto'),
                'printers': list_printers(),
                'print_count': print_count,
                'last_print_time': last_print_time,
                'last_print_method': last_print_method,
                'last_print_error': last_print_error,
                'current_dir': os.path.dirname(os.path.abspath(__file__)),
                'tips': [
                    'Si el driver es "Datamax" o "Honeywell": puede estar interceptando datos RAW.',
                    'Solucion: Instalar impresora "Generic/Text Only" en el mismo puerto USB001.',
                    'Alternativa: Si la Datamax tiene tarjeta de red, configure la IP (Metodo D).',
                    'El scan de red busca impresoras en el puerto 9100 de la subred local.'
                ]
            })
        elif self.path == '/api/scan-network':
            self.send_json({'status': 'use POST /api/scan-network'})
        else:
            # Dashboard HTML
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                html = generate_dashboard()
                self.wfile.write(html.encode('utf-8'))
            except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                pass

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b''

        if self.path == '/api/config':
            try:
                new_cfg = json.loads(body.decode('utf-8'))
                global config
                if 'printerName' in new_cfg:
                    config['printerName'] = new_cfg['printerName']
                if 'printerIP' in new_cfg:
                    config['printerIP'] = new_cfg['printerIP']
                if 'printMethod' in new_cfg:
                    config['printMethod'] = new_cfg['printMethod']
                if 'tcpPort' in new_cfg:
                    config['tcpPort'] = int(new_cfg['tcpPort'])
                if 'httpPort' in new_cfg:
                    config['httpPort'] = int(new_cfg['httpPort'])
                if 'logLevel' in new_cfg:
                    config['logLevel'] = new_cfg['logLevel']
                save_config(config)
                self.send_json({'success': True, 'config': config})
            except Exception as e:
                self.send_json({'success': False, 'error': str(e)}, 400)

        elif self.path == '/api/test':
            printer_name = config.get('printerName', '')
            if not printer_name:
                self.send_json({'success': False, 'error': 'No hay impresora configurada'}, 400)
                return

            try:
                req = json.loads(body.decode('utf-8')) if body else {}
                fmt = req.get('format', 'dpl')
            except:
                fmt = 'dpl'

            now = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

            if fmt == 'zpl':
                # Etiqueta de prueba ZPL (compatible Zebra)
                test_data = (
                    "^XA\n"
                    "^FO50,30^A0N,40,40^FD** PRUEBA **^FS\n"
                    "^FO50,80^A0N,30,30^FDPrinter Bridge v3.1^FS\n"
                    "^FO50,120^A0N,20,20^FD{fecha}^FS\n"
                    "^FO50,150^A0N,20,20^FDSolemar Alimentaria^FS\n"
                    "^FO50,180^A0N,25,25^FDDatamax Mark II^FS\n"
                    "^FO50,220^BY3^BCN,60,Y,N,N^FDTEST-BRIDGE^FS\n"
                    "^XZ"
                ).format(fecha=now)
            else:
                # Etiqueta de prueba DPL (Datamax Programming Language)
                # Formato limpio SIN STX/ETX - DPL estandar no los necesita
                # Basado en el formato del sistema viejo de trazabilidad
                test_data = (
                    "n\r\n"
                    "M1084\r\n"
                    "O0220\r\n"
                    "SO\r\n"
                    "d\r\n"
                    "L\r\n"
                    "D11\r\n"
                    "PO\r\n"
                    "pG\r\n"
                    "SO\r\n"
                    "A2\r\n"
                    "1e8406900410065Ccb\r\n"
                    "ySE1\r\n"
                    "1911A1200220110SOLEMAR ALIMENTARIA\r\n"
                    "1911A1200550110** PRUEBA **\r\n"
                    "1911A1200880110Printer Bridge v3.1\r\n"
                    "1911A1201210110Datamax Mark II\r\n"
                    "1911A1201540110" + now + "\r\n"
                    "Q0001\r\n"
                    "E\r\n"
                )

            result = print_raw(printer_name, test_data)
            self.send_json(result)

        elif self.path == '/api/test-all':
            """Probar todos los metodos de impresion y reportar."""
            printer_name = config.get('printerName', '')
            if not printer_name:
                self.send_json({'success': False, 'error': 'No hay impresora configurada'}, 400)
                return

            # DPL de prueba simple
            test_data = (
                "n\r\n"
                "H0080o0030\r\n"
                "f220\r\n"
                "1f100\r\n"
                "H0100o0140\r\n"
                "f250\r\n"
                "1f100\r\n"
                "c0000\r\n"
                "1911005000100TEST OK\r\n"
                "Q0001\r\n"
                "E\r\n"
            )

            results = test_all_methods(printer_name, test_data)
            self.send_json(results)

        elif self.path == '/api/scan-network':
            """Escanear la red buscando impresoras en puerto 9100."""
            log('info', 'Iniciando escaneo de red...')
            found = scan_printer_network(timeout=0.3)
            if found:
                self.send_json({
                    'success': True,
                    'found': found,
                    'message': 'Impresoras encontradas en {}'.format(found)
                })
            else:
                self.send_json({
                    'success': False,
                    'found': [],
                    'message': 'No se encontraron impresoras en puerto 9100'
                })

        else:
            self.send_json({'error': 'Endpoint no encontrado'}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()


def start_http_server():
    """Iniciar servidor HTTP para el panel de control."""
    port = config.get('httpPort', 9101)
    server = HTTPServer(('0.0.0.0', port), DashboardHandler)
    log('info', 'Panel web en http://localhost:{}'.format(port))
    try:
        server.serve_forever()
    except:
        pass


# ============================================================
# Obtener IP local
# ============================================================
def get_local_ip():
    """Obtener la IP local de esta maquina."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'


# ============================================================
# Inicio
# ============================================================
running = True


def main():
    """Funcion principal."""
    # Verificar Python 3.8+
    if sys.version_info < (3, 8):
        print('')
        print('ERROR: Se requiere Python 3.8 o superior.')
        print('Version actual: {}'.format(sys.version))
        print('')
        print('Para Windows 7, descarga Python 3.8.10 desde:')
        print('https://www.python.org/ftp/python/3.8.10/python-3.8.10.exe')
        print('')
        sys.exit(1)

    # Verificar pywin32
    win32print = try_import_win32print()
    if not win32print:
        print('')
        print('ADVERTENCIA: pywin32 no esta instalado.')
        print('Sin pywin32 no se puede imprimir via USB.')
        print('')
        print('Para instalar:')
        print('  pip install pywin32')
        print('')
        print('O ejecuta install.bat')
        print('')

    local_ip = get_local_ip()
    tcp_port = config.get('tcpPort', 9100)
    http_port = config.get('httpPort', 9101)
    printer_name = config.get('printerName', '(sin configurar)')
    method = config.get('printMethod', 'auto')

    print('')
    print('========================================================')
    print('  PRINTER BRIDGE v3.1 (Python) - Solemar Alimentaria')
    print('========================================================')
    print('  Python:    {}'.format(sys.version.split()[0]))
    print('  pywin32:   {}'.format('OK' if win32print else 'NO INSTALADO'))
    print('  TCP:       {}:{}'.format(local_ip, tcp_port))
    print('  Panel Web: http://{}:{}'.format(local_ip, http_port))
    print('  Impresora: {}'.format(printer_name))
    print('  Metodo:    {}'.format(method))
    print('========================================================')
    print('')
    print('Abri http://localhost:{} en tu navegador para configurar'.format(http_port))
    print('')

    # Iniciar HTTP server en un thread separado
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    # Iniciar TCP server en el hilo principal
    start_tcp_server()


if __name__ == '__main__':
    main()
