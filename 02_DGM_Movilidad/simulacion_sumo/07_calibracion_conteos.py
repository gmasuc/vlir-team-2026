"""
Calibracion de la demanda de autos con los conteos vehiculares 2023 (hora 7:00-8:00), por acceso de interseccion.

1. Conteos por acceso (conteos_accesos.py) -> aristas de la red -> archivo de conteos para SUMO.
2. Rutas candidatas extra: rutas de paso que entran y salen por el borde de la red (trafico que viene de fuera de las
   65 zonas: parroquias rurales, otros cantones), solo las que pasan por un acceso contado.
3. Rondas de  calibrar -> reasignar:
   - calibrar: routeSampler parte de la demanda actual y agrega o quita vehiculos en las rutas que pasan por los
     accesos contados hasta acercarse a los conteos. Los viajes que no pasan por ningun conteo se mantienen.
   - reasignar: duaIterate parte de la demanda calibrada y deja que los conductores vuelvan a elegir ruta con el
     nuevo nivel de trafico (si no, los vehiculos agregados quedan en rutas que ya no son las mas rapidas).
   Al final se calibra una vez mas. Cada paso se simula (mesoscopico) y se compara acceso por acceso.

Uso:  py simulacion_sumo/07_calibracion_conteos.py [escenario] [rondas]
Salida: simulacion_sumo/calibracion/<escenario>/  (demanda_final.rou.xml, evolucion_calibracion.csv, comparacion_accesos.csv)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import sumo

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
sys.path.append(str(SIM))
import conteos_accesos as ca  # noqa: E402

ESC = sys.argv[1] if len(sys.argv) > 1 else "ambos"
RONDAS = int(sys.argv[2]) if len(sys.argv) > 2 else 2
RED_V2 = len(sys.argv) > 3 and sys.argv[3] == "v2"     # red con carriles corregidos (08)
ITER_REASIGNAR = 3                      # iteraciones de duaIterate por ronda
OUT = SIM / "calibracion" / (ESC + ("_v2" if RED_V2 else ""))
OUT.mkdir(parents=True, exist_ok=True)
NET = SIM / "red" / ("cuenca_piloto_v2.net.xml" if RED_V2 else "cuenca_piloto.net.xml")
# Los semaforos recalculados con Webster (08) se probaron y empeoraban la congestion (4 518 vehiculos sin llegar a
# las 9:00 contra 0 con los programas por defecto), asi que no se usan.
ADD = []                                # programas semaforicos adicionales
ITERS = sorted((SIM / "asignacion" / ESC).glob("[0-9][0-9][0-9]"))
RUTAS_EQ = ITERS[-1] / f"viajes_validos_{ITERS[-1].name}.rou.xml.gz"
HORA = 7
B, E = HORA * 3600, (HORA + 1) * 3600
BIN = Path(sumo.SUMO_HOME) / "bin"
TOOLS = Path(sumo.SUMO_HOME) / "tools"
env = dict(os.environ, SUMO_HOME=sumo.SUMO_HOME)


def correr(cmd, log, carpeta=OUT):
    carpeta.mkdir(parents=True, exist_ok=True)
    with open(carpeta / log, "w") as f:
        r = subprocess.run([str(x) for x in cmd], cwd=carpeta, env=env, stdout=f, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        sys.exit(f"fallo {Path(str(cmd[1] if cmd[0] == sys.executable else cmd[0])).name} (ver {carpeta / log})")


# ----------------------------------------------------------------------------- 1. conteos por acceso
net = sumolib.net.readNet(str(NET))
conteo = ca.conteos_por_acceso(SIM.parent, HORA)
aristas, notas = ca.ubicar_accesos(net)
print("\n".join(notas))
acc = pd.DataFrame([{"interseccion": i, "acceso": l, "arista": e, "contados": conteo.get((i, l), np.nan)}
                    for (i, l), e in aristas.items()]).dropna(subset=["contados"])
acc = acc.groupby("arista", as_index=False).agg(interseccion=("interseccion", "first"), acceso=("acceso", "first"),
                                                 contados=("contados", "sum"))
print(f"accesos contados ubicados en la red: {len(acc)}  ({int(acc.contados.sum()):,} livianos/h)", flush=True)
with open(OUT / "conteos.xml", "w", encoding="utf-8") as f:
    f.write(f'<data>\n  <interval id="h{HORA}" begin="{B}" end="{E}">\n')
    for r in acc.itertuples():
        f.write(f'    <edge id="{r.arista}" entered="{int(r.contados)}"/>\n')
    f.write("  </interval>\n</data>\n")
contados = set(acc.arista)

# ----------------------------------------------------------------------------- 2. rutas de paso desde el borde de la red
if not (OUT / "paso_contadas.rou.xml").exists():
    correr([sys.executable, TOOLS / "randomTrips.py", "-n", NET, "-o", "paso.trips.xml", "-r", "paso.rou.xml",
            "-b", B, "-e", E, "-p", "0.25", "--fringe-factor", "max", "--vclass", "passenger", "--seed", "7",
            "--prefix", "paso", "--min-distance", "1500", "--validate"], "randomTrips.log")
    with open(OUT / "paso.rou.xml", encoding="utf-8") as fi, \
         open(OUT / "paso_contadas.rou.xml", "w", encoding="utf-8") as fo:
        fo.write("<routes>\n")
        for v in sumolib.xml.parse(fi, "vehicle"):
            if contados & set(v.route[0].edges.split()):
                fo.write(f'  <route id="{v.id}" edges="{v.route[0].edges}"/>\n')
        fo.write("</routes>\n")


# ----------------------------------------------------------------------------- 3. pasos: calibrar, reasignar, simular
def calibrar(rutas, carpeta):
    correr([sys.executable, TOOLS / "routeSampler.py", "-r", f"{rutas},{OUT / 'paso_contadas.rou.xml'}",
            "-d", OUT / "conteos.xml", "-o", "calibrada.rou.xml", "--init-input.remove-overflow", "--keep-attributes",
            "-b", B, "-e", E, "--prefix", f"{carpeta.name}_", "--seed", "7", "--mismatch-output", "diferencias.xml",
            "-v"], "routeSampler.log", carpeta)
    print("  " + next(x for x in open(carpeta / "routeSampler.log") if x.startswith("Wrote")).strip(), flush=True)
    return carpeta / "calibrada.rou.xml"


def reasignar(rutas, carpeta, iteraciones=ITER_REASIGNAR):
    extra = ["-+", ",".join(map(str, ADD))] if ADD else []
    correr([sys.executable, TOOLS / "assign" / "duaIterate.py", "-n", NET, "-r", rutas, "-l", iteraciones, "-m", *extra,
            "-b", B, "-e", E + 3600, "-a", "3600", "--time-to-teleport", "300", "-w", "--clean-alt",
            "--skip-first-routing",                     # el paso 0 simula las rutas calibradas tal como estan
            "duarouter--routing-threads", "4", "sumo--meso-tls-penalty", "1", "sumo--threads", "4"],
           "duaIterate.log", carpeta)
    ult = sorted(carpeta.glob("[0-9][0-9][0-9]"))[-1]          # rutas de la ultima iteracion (no las alternativas)
    return next(p for p in ult.glob("*.rou.xml.gz") if not p.name.endswith(".rou.alt.xml.gz"))


def simular(rutas, nombre):
    with open(OUT / f"{nombre}.add.xml", "w") as f:
        f.write(f'<additional><edgeData id="{nombre}" file="{nombre}_aristas.xml" begin="{B}" end="{E}" '
                f'excludeEmpty="true"/></additional>\n')
    correr([BIN / "sumo", "-n", NET, "-r", rutas, "-a", ",".join(map(str, ADD + [f"{nombre}.add.xml"])), "--mesosim", "--meso-tls-penalty", "1",
            "-b", B, "-e", E + 3600, "--time-to-teleport", "300", "--ignore-route-errors", "--no-step-log",
            "--threads", "4", "--summary-output", f"{nombre}_resumen.xml", "--duration-log.statistics"],
           f"{nombre}.log")
    v = {}
    for iv in sumolib.xml.parse(str(OUT / f"{nombre}_aristas.xml"), "interval"):
        for e in iv.edge or []:
            v[e.id] = float(e.entered or 0)
    sim = acc.arista.map(pd.Series(v, dtype=float)).fillna(0).round(0)
    ult = list(sumolib.xml.parse(str(OUT / f"{nombre}_resumen.xml"), "step"))[-1]
    g = np.sqrt(2 * (sim - acc.contados) ** 2 / (sim + acc.contados).clip(lower=1))
    fila = {"paso": nombre, "vehiculos": int(ult.loaded), "en_calle_9h": int(ult.running),
            "teletransportes": int(ult.teleports), "viaje_medio_min": round(float(ult.meanTravelTime) / 60, 1),
            "simulados_vs_contados_%": round(100 * sim.sum() / acc.contados.sum()),
            "correlacion": round(np.corrcoef(sim, acc.contados)[0, 1], 2), "GEH<5_%": round(100 * (g < 5).mean()),
            "error_medio_%": round((100 * (sim - acc.contados).abs() / acc.contados).median())}
    print("  " + ", ".join(f"{k}={v}" for k, v in fila.items()), flush=True)
    acc[nombre] = sim
    return fila


filas = [simular(RUTAS_EQ, "equilibrio")]
rutas = RUTAS_EQ
if RED_V2:      # la red cambio: primero se deja que las rutas del equilibrio se reacomoden a la nueva capacidad
    print("red v2: reasignar el equilibrio", flush=True)
    rutas = reasignar(rutas, OUT / "previo_reasignar", iteraciones=5)
    filas.append(simular(rutas, "equilibrio_v2"))
for k in range(1, RONDAS + 1):
    print(f"ronda {k}: calibrar", flush=True)
    rutas = calibrar(rutas, OUT / f"ronda{k}_calibrar")
    filas.append(simular(rutas, f"r{k}_calibrada"))
    print(f"ronda {k}: reasignar", flush=True)
    rutas = reasignar(rutas, OUT / f"ronda{k}_reasignar")
    filas.append(simular(rutas, f"r{k}_reasignada"))
print("final: calibrar", flush=True)
rutas = calibrar(rutas, OUT / "final_calibrar")
filas.append(simular(rutas, "final"))
(OUT / "demanda_final.rou.xml").write_bytes(Path(rutas).read_bytes())

evol = pd.DataFrame(filas)
evol.to_csv(OUT / "evolucion_calibracion.csv", index=False)
acc.to_csv(OUT / "comparacion_accesos.csv", index=False, encoding="utf-8-sig")
print(evol.to_string(index=False))
print(acc.drop(columns="arista").to_string(index=False))
