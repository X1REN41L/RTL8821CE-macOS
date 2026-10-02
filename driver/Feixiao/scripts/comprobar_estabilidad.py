#!/usr/bin/env python3
"""Read-only local Wi-Fi stability sampling. Does not change network settings."""
import datetime, pathlib, re, subprocess, sys
root = pathlib.Path(__file__).resolve().parents[1]
route = subprocess.run(['/sbin/route', '-n', 'get', 'default'], capture_output=True, text=True)
gateway = re.search(r'^\s*gateway:\s*(\S+)', route.stdout, re.M)
interface = re.search(r'^\s*interface:\s*(\S+)', route.stdout, re.M)
if route.returncode or not gateway or not interface:
    sys.exit('No se pudo leer el router: comprobá que Wi-Fi esté conectado.')
gw, iface = gateway.group(1), interface.group(1)
if not re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}', gw):
    sys.exit('Esta prueba requiere una puerta de enlace IPv4.')
folder = root / 'diagnostics' / ('estabilidad-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
folder.mkdir(parents=True)
print(f'Interfaz: {iface}. Router: {gw}. Duración aproximada: 15 minutos.', flush=True)
print('Verificá que esa sea la interfaz Wi-Fi. Mantené la ubicación y usá Internet normalmente.')
print('La prueba mide respuestas del router; no mide barras ni velocidad máxima. Ctrl+C termina antes.\n')
results = []
try:
    for minute in range(1, 16):
        current = subprocess.run(['/sbin/route', '-n', 'get', 'default'], capture_output=True, text=True)
        if not re.search(r'^\s*interface:\s*'+re.escape(iface)+r'\s*$', current.stdout, re.M) or not re.search(r'^\s*gateway:\s*'+re.escape(gw)+r'\s*$', current.stdout, re.M):
            print('La ruta cambió o desapareció. Termino para no mezclar conexiones.'); break
        p = subprocess.run(['/sbin/ping', '-n', '-c', '60', '-i', '1', '-W', '1000', gw], capture_output=True, text=True)
        (folder / f'minuto-{minute:02d}.txt').write_text(p.stdout + p.stderr)
        loss = re.search(r'([\d.]+)% packet loss', p.stdout)
        rtt = re.search(r'= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms', p.stdout)
        row = f'Minuto {minute:02d}: pérdida {loss.group(1) if loss else "sin dato"}%'
        row += f'; latencia promedio {rtt.group(2)} ms, máxima {rtt.group(3)} ms' if rtt else '; sin resumen de latencia'
        results.append(row); print(row, flush=True)
        (folder / 'RESUMEN.txt').write_text('\n'.join(results)+'\n')
except KeyboardInterrupt:
    print('\nPrueba interrumpida; se conservan los minutos completos.')
finally:
    print(f'\nResultados: {folder}')
    print('Buscá pérdida repetida, cortes o latencia que empeora con el tiempo.')
    print('Un router puede limitar ICMP: interpretá estos datos junto con cortes reales de navegación.')
    print('Un resultado sin pérdidas tampoco certifica estabilidad bajo carga ni AirDrop.')
