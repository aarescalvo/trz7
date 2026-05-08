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

