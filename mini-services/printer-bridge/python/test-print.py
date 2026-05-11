# -*- coding: utf-8 -*-
"""Test DPL variants - buscar cual formato imprime texto visible"""
import ctypes
import struct
import time

PRINTER_NAME = 'Datamax M-4206 Mark II'
PASSTHROUGH = 4105
SI = b'\x0f'  # Shift In - separador DPL Datamax
STX = b'\x02'  # Start of text

class DOCINFOW(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_int),
        ('lpszDocName', ctypes.c_wchar_p),
        ('lpszOutput', ctypes.c_wchar_p),
        ('lpszDatatype', ctypes.c_wchar_p),
        ('fwType', ctypes.c_ulong),
    ]

def send_passthrough(data):
    hdc = ctypes.windll.gdi32.CreateDCW('winspool', PRINTER_NAME, None, None)
    if not hdc:
        print('ERROR: No se pudo crear DC')
        return False
    doc = DOCINFOW()
    doc.cbSize = ctypes.sizeof(DOCINFOW)
    doc.lpszDocName = 'DPL'
    doc.lpszDatatype = 'RAW'
    ctypes.windll.gdi32.StartDocW(hdc, ctypes.byref(doc))
    ctypes.windll.gdi32.StartPage(hdc)
    buf = struct.pack('<I', len(data)) + data
    ret = ctypes.windll.gdi32.ExtEscape(hdc, PASSTHROUGH, len(buf), buf, 0, None)
    ctypes.windll.gdi32.EndPage(hdc)
    ctypes.windll.gdi32.EndDoc(hdc)
    ctypes.windll.gdi32.DeleteDC(hdc)
    return ret > 0

tests = []

# TEST 1: DPL con SI (0x0F) como separador Datamax estandar
tests.append(('SI separador - basico', 
    STX + b'H0080' + SI +
    STX + b'1H0050' + SI +
    STX + b'1V0050' + SI +
    STX + b'1f0' + SI +
    STX + b'1h040' + SI +
    STX + b'1w030' + SI +
    STX + b'c0030HOLA SOLEMAR' + SI +
    STX + b'Q0001' + SI +
    STX + b'E' + SI
))

# TEST 2: DPL con SI y fuente interna 1
tests.append(('SI separador - font 1', 
    STX + b'H0080' + SI +
    STX + b'1H0050' + SI +
    STX + b'1V0050' + SI +
    STX + b'1f1' + SI +
    STX + b'1h040' + SI +
    STX + b'1w030' + SI +
    STX + b'c0030HOLA SOLEMAR' + SI +
    STX + b'Q0001' + SI +
    STX + b'E' + SI
))

# TEST 3: DPL con \r\n y comandos basicos
tests.append(('CRLF - basico',
    b'H0080\r\n'
    b'1H0050\r\n'
    b'1V0050\r\n'
    b'1f0\r\n'
    b'1h040\r\n'
    b'c0030HOLA SOLEMAR\r\n'
    b'Q0001\r\n'
    b'E\r\n'
))

# TEST 4: DPL sistema viejo con control chars reales
tests.append(('Sistema viejo - control chars',
    STX + b'$' + SI + b'\r\n' +
    STX + b'H0080o0030' + SI + b'\r\n' +
    STX + b'f220' + SI + b'\r\n' +
    STX + b'1f100' + SI + b'\r\n' +
    STX + b'1H0050' + SI + b'\r\n' +
    STX + b'1V0100' + SI + b'\r\n' +
    STX + b'c0030HOLA SOLEMAR' + SI + b'\r\n' +
    STX + b'Q0001' + SI + b'\r\n' +
    STX + b'E' + SI + b'\r\n'
))

# TEST 5: DPL con comando 1911A (formato texto del sistema viejo)
tests.append(('1911A formato texto',
    STX + b'$' + SI + b'\r\n' +
    STX + b'H0080o0030' + SI + b'\r\n' +
    STX + b'f220' + SI + b'\r\n' +
    STX + b'1f100' + SI + b'\r\n' +
    b'1911A1200220110HOLA SOLEMAR\r\n' +
    STX + b'Q0001' + SI + b'\r\n' +
    STX + b'E' + SI + b'\r\n'
))

# TEST 6: DPL solo con ~RESET antes
tests.append(('Con RESET previo',
    b'~RESET\r\n'
    b'H0080\r\n'
    b'1H0050\r\n'
    b'1V0050\r\n'
    b'1f0\r\n'
    b'1h040\r\n'
    b'c0030HOLA SOLEMAR\r\n'
    b'Q0001\r\n'
    b'E\r\n'
))

# TEST 7: DPL con L (label) y D (darkness)
tests.append(('Con L y D (label/darkness)',
    STX + b'$' + SI + b'\r\n' +
    STX + b'H0080o0030' + SI + b'\r\n' +
    b'SO\r\n' +
    b'd\r\n' +
    b'L\r\n' +
    b'D11\r\n' +
    b'PO\r\n' +
    b'pG\r\n' +
    b'SO\r\n' +
    b'A2\r\n' +
    b'1f0\r\n' +
    b'1H0050\r\n' +
    b'1V0100\r\n' +
    b'1h040\r\n' +
    b'1w030\r\n' +
    b'191100500040HOLA SOLEMAR\r\n' +
    STX + b'Q0001' + SI + b'\r\n' +
    STX + b'E' + SI + b'\r\n'
))

# TEST 8: Solo texto con comando 1b (bar width) directo
tests.append(('Comando 1b directo',
    b'H0080\r\n'
    b'1f0\r\n'
    b'1H0050\r\n'
    b'1V0050\r\n'
    b'1b0200\r\n'
    b'1h0060\r\n'
    b'c0030HOLA SOLEMAR\r\n'
    b'Q0001\r\n'
    b'E\r\n'
))

# TEST 9: Formato EtiHac del sistema viejo completo con control chars
tests.append(('EtiHac completo',
    STX + b'$' + SI +
    STX + b'H0080o0030' + SI +
    STX + b'SO' + SI +
    b'd\r\n' +
    b'L\r\n' +
    b'D11\r\n' +
    b'PO\r\n' +
    b'pG\r\n' +
    b'SO\r\n' +
    b'A2\r\n' +
    b'1e8406900410065Ccb\r\n' +
    b'ySE1\r\n' +
    b'1911A1200220110SOLEMAR ALIMENTARIA\r\n' +
    b'1911A1200550110** PRUEBA OK **\r\n' +
    b'1911A1200880110Printer Bridge PASSTHROUGH\r\n' +
    b'1911A1201210110Datamax M-4206 Mark II\r\n' +
    b'Q0001\r\n' +
    b'E\r\n'
))

# TEST 10: DPL con SO (Set Orientation) antes
tests.append(('Con SO orientacion',
    b'SO\r\n'
    b'H0080\r\n'
    b'O0220\r\n'
    b'1f0\r\n'
    b'1H0050\r\n'
    b'1V0050\r\n'
    b'1h040\r\n'
    b'c0030HOLA SOLEMAR\r\n'
    b'Q0001\r\n'
    b'E\r\n'
))

print('=' * 55)
print('TEST DPL VARIANTS - Datamax M-4206 Mark II')
print('=' * 55)
print('Se van a imprimir 10 etiquetas con formatos diferentes.')
print('Contame CUALES tienen texto visible.')
print('')

for i, (name, dpl) in enumerate(tests, 1):
    print('--- Test {}/10: {} ({} bytes) ---'.format(i, name, len(dpl)))
    ok = send_passthrough(dpl)
    print('Enviado: {}'.format('OK' if ok else 'FALLO'))
    time.sleep(2)

print('')
print('=' * 55)
print('FIN - Revisa los 10 rotulos en la impresora.')
print('Contame cual tiene texto visible (numerados del 1 al 10).')
print('=' * 55)
