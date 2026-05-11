# -*- coding: utf-8 -*-
"""Test de impresion directa - PASSTHROUGH via ctypes"""
import ctypes
import struct

PRINTER_NAME = 'Datamax M-4206 Mark II'

# DPL de prueba
DPL_DATA = b'n\r\nH0080o0030\r\nf220\r\n1f100\r\nc0000\r\n1911005000100TEST OK\r\nQ0001\r\nE\r\n'

PASSTHROUGH = 4105

# Definir DOCINFOW manualmente
class DOCINFOW(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_int),
        ('lpszDocName', ctypes.c_wchar_p),
        ('lpszOutput', ctypes.c_wchar_p),
        ('lpszDatatype', ctypes.c_wchar_p),
        ('fwType', ctypes.c_ulong),
    ]

print('Creando DC para: ' + PRINTER_NAME)
hdc = ctypes.windll.gdi32.CreateDCW(
    'winspool',          # driver
    PRINTER_NAME,        # device name
    None,                # output file
    None                 # init data
)

if not hdc:
    print('ERROR: No se pudo crear DC. Asegurate que la impresora esta instalada.')
    exit(1)

print('DC creado OK:', hdc)

# Iniciar documento
doc = DOCINFOW()
doc.cbSize = ctypes.sizeof(DOCINFOW)
doc.lpszDocName = 'DPL Test'
doc.lpszDatatype = 'RAW'

print('Iniciando StartDoc...')
ret = ctypes.windll.gdi32.StartDocW(hdc, ctypes.byref(doc))
print('StartDoc:', ret)

print('Iniciando StartPage...')
ret = ctypes.windll.gdi32.StartPage(hdc)
print('StartPage:', ret)

# Preparar buffer PASSTHROUGH: 4 bytes (longitud) + datos
buf_size = 4 + len(DPL_DATA)
buf = ctypes.create_string_buffer(buf_size)
# Escribir longitud como little-endian uint32
struct.pack_into('<I', buf, 0, len(DPL_DATA))
# Copiar datos despues de los 4 bytes
buf.raw = struct.pack('<I', len(DPL_DATA)) + DPL_DATA

print('Enviando ExtEscape PASSTHROUGH ({} bytes)...'.format(len(DPL_DATA)))
ret = ctypes.windll.gdi32.ExtEscapeA(
    hdc,
    PASSTHROUGH,    # escape code
    buf_size,       # input size
    buf,            # input buffer
    0,              # output size
    None            # output buffer
)
print('ExtEscape retorno:', ret)
print('(>0 = datos enviados, 0 = no soportado, <0 = error)')

print('EndPage...')
ctypes.windll.gdi32.EndPage(hdc)

print('EndDoc...')
ctypes.windll.gdi32.EndDoc(hdc)

print('DeleteDC...')
ctypes.windll.gdi32.DeleteDC(hdc)

print('')
print('LISTO. Fijate si la impresora reacciono.')
