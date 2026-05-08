---
Task ID: FIX-PRINTER-BRIDGE-v3.0.1
Agent: main
Task: Corregir errores en Printer Bridge v3.0 Python

Work Log:
- Corregido error "too many values to unpack (expected 7)" en list_printers()
  - win32print.EnumPrinters(level=2) retorna 5 valores, no 7
  - Cambiado a acceso por indice seguro (info_tuple[2], info_tuple[1])
- Corregido ConnectionAbortedError [WinError 10053] en DashboardHandler
  - Protegido send_json() con try-except para ConnectionAbortedError/BrokenPipeError/ConnectionResetError
  - Protegido do_GET() (dashboard HTML) con try-except para los mismos errores
  - El navegador cerraba la conexion antes de terminar de enviar el HTML

Stage Summary:
- Ambos errores corregidos en mini-services/printer-bridge/python/index.py
- Archivo listo para copiar a la PC de Solemar Alimentaria
- Version del fix: v3.0.1

---
Task ID: FIX-PRINTER-BRIDGE-v3.1
Agent: main
Task: Resolver problema de impresion USB - Datamax no imprime a pesar de que win32print reporta OK

Work Log:
- Diagnostico: `copy USB001 /b` NO funciona para impresoras USB (USB001 es puerto virtual del spooler)
- STX/ETX (\x02 \x03) NO son parte del DPL estandar - estaban confundiendo a la impresora
- Reescrita completa de print_raw() con 4 metodos de impresion que se prueban en secuencia:
  - Metodo A: win32print RAW SIN page controls (StartDoc > WritePrinter > EndDoc) - ideal para etiquetas
  - Metodo B: win32print RAW CON page controls (StartDoc > StartPage > WritePrinter > EndPage > EndDoc)
  - Metodo C: Escritura directa al puerto (open puerto, write bytes)
  - Metodo D: TCP directo a IP de impresora (port 9100) - para impresoras con tarjeta de red
- DPL de prueba corregido: sin STX/ETX, con \r\n como separadores
- Agregado: test_all_methods() que prueba todos los metodos y reporta resultados
- Agregado: scan_printer_network() que busca impresoras en la red local puerto 9100
- Agregado: configuracion de IP directa y metodo de impresion en panel web
- Agregado: "Probar TODOS los metodos" button en panel web
- Auto-guarda el metodo que funciona para impresiones futuras
- Cambiado line endings de \n a \r\n en DPL (formato estandar Datamax)

Stage Summary:
- Printer Bridge v3.1 con multiples metodos de impresion
- El usuario debe: copiar index.py a su PC, abrir panel web, clic "Probar TODOS los metodos"
- Si ningun metodo USB funciona: instalar Generic/Text Only driver o usar Metodo D (TCP directo)
- Archivo: printer-bridge-repo/mini-services/printer-bridge/python/index.py

