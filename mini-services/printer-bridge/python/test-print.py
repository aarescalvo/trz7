# -*- coding: utf-8 -*-
"""Test de impresion PASSTHROUGH - DPL completo del sistema viejo de trazabilidad"""
import ctypes
import struct
import time

PRINTER_NAME = 'Datamax M-4206 Mark II'
PASSTHROUGH = 4105

# DPL del sistema viejo (formato original con <STX>/<SI> como separadores)
# Del archivo EtiHac.trz del sistema de trazabilidad
DPL_VIEJO = (
    "<STX><SI>$<SI>\r\n"
    "<SI>H0080o0030<SI>\r\n"
    "<SI>f220<SI>\r\n"
    "<SI>1f100<SI>\r\n"
    "<SI>H0100o0140<SI>\r\n"
    "<SI>f250<SI>\r\n"
    "<SI>1f100<SI>\r\n"
    "<SI>c0000<SI>\r\n"
    "<SI>1911005000100TEST OK<SI>\r\n"
    "<SI>H0080o0030<SI>\r\n"
    "<SI>1e10006001220065\r\n"
    "<SI>1b31002240065\r\n"
    "<SI>ySE1<SI>\r\n"
    "<SI>1911005000100SOLEMAR ALIMENTARIA<SI>\r\n"
    "<SI>1911005000120** PRUEBA BRIDGE **<SI>\r\n"
    "<SI>Q0001<SI>\r\n"
    "<SI>E<SI>\r\n"
).encode('latin-1')

# DPL alternativo simple
DPL_SIMPLE = b'n\r\nM1084\r\nO0220\r\nSO\r\nd\r\nL\r\nD11\r\nPO\r\npG\r\nSO\r\nA2\r\n1e8406900410065Ccb\r\nySE1\r\n1911A1200220110SOLEMAR ALIMENTARIA\r\n1911A1200550110** PRUEBA **\r\n1911A1200880110Printer Bridge v3.1\r\n1911A1201210110Datamax Mark II\r\nQ0001\r\nE\r\n'

# DPL minimal para probar que la impresora imprime ALGO
DPL_MINIMAL = (
    "H0080o0030\r\n"
    "f220\r\n"
    "1f100\r\n"
    "c0000\r\n"
    "1911005000100HOLA SOLEMAR\r\n"
    "Q0001\r\n"
    "E\r\n"
).encode('latin-1')

class DOCINFOW(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_int),
        ('lpszDocName', ctypes.c_wchar_p),
        ('lpszOutput', ctypes.c_wchar_p),
        ('lpszDatatype', ctypes.c_wchar_p),
        ('fwType', ctypes.c_ulong),
    ]

def send_passthrough(printer_name, data):
    """Enviar datos RAW a la impresora via PASSTHROUGH."""
    hdc = ctypes.windll.gdi32.CreateDCW('winspool', printer_name, None, None)
    if not hdc:
        print('ERROR: No se pudo crear DC para: ' + printer_name)
        return False

    doc = DOCINFOW()
    doc.cbSize = ctypes.sizeof(DOCINFOW)
    doc.lpszDocName = 'DPL'
    doc.lpszDatatype = 'RAW'

    ctypes.windll.gdi32.StartDocW(hdc, ctypes.byref(doc))
    ctypes.windll.gdi32.StartPage(hdc)

    buf = struct.pack('<I', len(data)) + data
    ret = ctypes.windll.gdi32.ExtEscape(
        hdc, PASSTHROUGH, len(buf), buf, 0, None
    )

    ctypes.windll.gdi32.EndPage(hdc)
    ctypes.windll.gdi32.EndDoc(hdc)
    ctypes.windll.gdi32.DeleteDC(hdc)

    return ret > 0

# Ejecutar pruebas
print('=' * 50)
print('TEST PASSTHROUGH - Datamax M-4206 Mark II')
print('=' * 50)

tests = [
    ('VIEJO (sistema trazabilidad)', DPL_VIEJO),
    ('SIMPLE (formato DPL)', DPL_SIMPLE),
    ('MINIMAL (basico)', DPL_MINIMAL),
]

for name, dpl in tests:
    print('')
    print('--- Test: {} ({} bytes) ---'.format(name, len(dpl)))
    print('Contenido:')
    print(repr(dpl[:200]))
    print('...')
    ok = send_passthrough(PRINTER_NAME, dpl)
    print('Resultado:', 'ENVIADO OK' if ok else 'FALLO')
    time.sleep(3)  # Pausa entre impresiones

print('')
print('=' * 50)
print('FIN. Revisa la impresora - deberian haber salido 3 rotulos.')
print('Contame cual de los 3 salio con texto visible.')
