"""
Prueba de velocidad del simulador: cuánto tarda una corrida y cuánto se puede acelerar sin cambiar los resultados.
Hace falta saberlo antes de correr muchas combinaciones (datos para el modelo sustituto y el optimizador).

Parte de la situación actual con semáforos reales (buses/calibrada_bahia_reruteo_scats: mismos recorridos de buses,
paradas y programas) y corre varias variantes A LA VEZ (así también se mide el efecto de correr en paralelo):
  ref     igual que 09_buses.py (6:00-9:30, cambio de ruta cada 300 s, Dijkstra, 4 hilos)
  astar   algoritmo de rutas A* en vez de Dijkstra (mismo resultado en teoría, búsqueda más corta)
  p600    cambio de ruta cada 600 s en vez de 300 s (la mitad de consultas; cambia algo el comportamiento)
  corto   A* + cambio cada 600 s + simulación de 6:30 a 9:15
  semilla igual que ref con otra semilla aleatoria: mide cuánto cambian los resultados por azar
Mientras corre, el script impide que Windows suspenda la computadora (la primera prueba se invalidó por eso); si se
cierra la tapa del portátil igual puede suspenderse.

Compara con la corrida de referencia (hecha sola): tiempo, velocidad mediana del bus por línea (largo real de la
ruta, como velocidades_bus.py), viaje medio en auto (7:00-8:00) y teletransportes.

Uso:  py simulacion_sumo/14_prueba_velocidad.py [variantes...]
Salida: buses/prueba_velocidad/<variante>/ y buses/prueba_velocidad/resultado.csv
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import sumo

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
BASE_RUN = SIM / "buses" / "calibrada_bahia_reruteo_scats"
OUT = SIM / "buses" / "prueba_velocidad"
NET = SIM / "red" / "cuenca_piloto_v2s.net.xml"
AUTOS = SIM / "calibracion" / "ambos_v2" / "demanda_final.rou.xml"
ADD = [SIM / "red" / "semaforos_scats.add.xml", BASE_RUN / "tranvia_prioridad.add.xml", BASE_RUN / "paradas.add.xml"]
env = dict(os.environ, SUMO_HOME=sumo.SUMO_HOME)

VARIANTES = {
    "ref": dict(periodo=300, algoritmo="dijkstra", b=6 * 3600, e=9.5 * 3600),
    "astar": dict(periodo=300, algoritmo="astar", b=6 * 3600, e=9.5 * 3600),
    "p600": dict(periodo=600, algoritmo="dijkstra", b=6 * 3600, e=9.5 * 3600),
    "corto": dict(periodo=600, algoritmo="astar", b=6.5 * 3600, e=9.25 * 3600),
    "semilla": dict(periodo=300, algoritmo="dijkstra", b=6 * 3600, e=9.5 * 3600, semilla=7),
}
elegidas = [v for v in sys.argv[1:] if v in VARIANTES] or list(VARIANTES)


def comando(v):
    c = VARIANTES[v]
    return [str(Path(sumo.SUMO_HOME) / "bin" / "sumo"), "-n", str(NET), "-r", f"{BASE_RUN / 'buses.rou.xml'},{AUTOS}",
            "-a", ",".join(map(str, ADD)), "--mesosim", "--meso-tls-penalty", "1",
            "--device.rerouting.probability", "1", "--device.rerouting.period", str(c["periodo"]),
            "--device.rerouting.adaptation-steps", str(int(5400 / c["periodo"])),   # media móvil de 90 min, como 18 x 300 s
            "--routing-algorithm", c["algoritmo"], "-b", str(int(c["b"])), "-e", str(int(c["e"])),
            "--time-to-teleport", "300", "--ignore-route-errors", "--no-step-log", "--threads", "4",
            "--tripinfo-output", "viajes.xml", "--tripinfo-output.write-unfinished", "--summary-output", "resumen.xml",
            "--duration-log.statistics", "--seed", str(c.get("semilla", 23423))]   # 23423: semilla por defecto de SUMO


def medir(carpeta):
    """velocidad mediana del bus (largo real de la ruta), viaje medio en auto y teletransportes."""
    net = sumolib.net.readNet(str(NET)) if not hasattr(medir, "net") else medir.net
    medir.net = net
    largo = {r.id: sum(net.getEdge(e).getLength() for e in r.edges.split() if net.hasEdge(e)) / 1000
             for r in sumolib.xml.parse(str(BASE_RUN / "buses.rou.xml"), "route")}
    v = pd.DataFrame([{"id": t.id, "tipo": t.vType, "salida": float(t.depart), "llegada": float(t.arrival),
                       "dur": float(t.duration)} for t in sumolib.xml.parse(str(carpeta / "viajes.xml"), "tripinfo")])
    v = v[(v.salida >= 7 * 3600) & (v.salida < 8 * 3600)]
    b = v[(v.tipo == "bus") & (v.llegada > 0)].copy()
    b["ruta"] = b.id.str.rsplit(".", n=1).str[0]
    b["km"] = b.ruta.map(largo)
    kmh = (b.groupby("ruta").km.mean() / (b.groupby("ruta").dur.mean() / 3600))
    a = v[~v.tipo.isin(["bus", "tranvia"])]
    log = (carpeta / "sumo.log").read_text(errors="ignore")
    tel = re.search(r"Teleports: (\d+)", log)
    return {"bus_kmh_mediana": round(kmh.median(), 2), "auto_min": round(a.dur.mean() / 60, 2),
            "autos_terminan_%": round(100 * (a.llegada > 0).mean(), 1), "teletransportes": int(tel.group(1)) if tel else 0,
            "tiempo_sumo_min": round(float(re.search(r"Duration: ([\d.]+)s", log).group(1)) / 60, 1)}


if os.name == "nt":                       # ES_CONTINUOUS | ES_SYSTEM_REQUIRED: no suspender mientras corre
    import ctypes
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
OUT.mkdir(parents=True, exist_ok=True)
procesos = {}
t0 = time.time()
for v in elegidas:
    d = OUT / v
    d.mkdir(exist_ok=True)
    procesos[v] = (subprocess.Popen(comando(v), cwd=d, env=env, stdout=open(d / "sumo.log", "w"),
                                    stderr=subprocess.STDOUT), d)
print(f"{len(procesos)} corridas a la vez: {', '.join(procesos)}", flush=True)
filas = []
for v, (p, d) in procesos.items():
    rc = p.wait()
    print(f"{v}: terminó (código {rc}) a los {(time.time() - t0) / 60:.1f} min", flush=True)
    if rc == 0:
        filas.append({"variante": v, "en_paralelo": len(procesos), **VARIANTES[v], **medir(d)})
filas.append({"variante": "ref_sola", "en_paralelo": 1, **VARIANTES["ref"], **medir(BASE_RUN)})
filas += [f for f in pd.read_csv(OUT / "resultado.csv").to_dict("records") if f["variante"] not in
          {x["variante"] for x in filas}] if (OUT / "resultado.csv").exists() else []
r = pd.DataFrame(filas)
r.to_csv(OUT / "resultado.csv", index=False, encoding="utf-8-sig")
print(r.to_string(index=False))
