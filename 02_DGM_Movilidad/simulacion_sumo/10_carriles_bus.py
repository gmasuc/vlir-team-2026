"""
Escenario 2: carriles exclusivos para el bus en los corredores mas cargados (red v3).

Corredores: calles por donde pasan 40 buses por hora o mas (sumando las frecuencias de todas las lineas que las usan,
segun los recorridos de 09_buses.py). En esas calles:
  - con 2 carriles o mas, el carril derecho pasa a ser solo para buses;
  - en la Av. Remigio Crespo Toral (1 carril util en la red v2 porque el otro suele estar con autos parqueados) se
    elimina el parqueo: se agrega un carril y ese carril derecho es solo para buses.
  - Las calles de 1 carril no cambian.

Uso:  py simulacion_sumo/10_carriles_bus.py [umbral_buses_h]
Entrada: red/cuenca_piloto_v2.net.xml, buses/equilibrio_bahia/buses.rou.xml (recorridos y frecuencias)
Salida:  red/cuenca_piloto_v3_carril_bus.net.xml (carril exclusivo, para modo microscopico),
         red/cuenca_piloto_v3b_menos_carril.net.xml (un carril menos para autos, para modo mesoscopico),
         red/carriles_bus_v3.csv; escenario 2b (solo Av. de las Americas y Av. 24 de Mayo): red/carriles_bus_v3_2b.csv y
         red/carriles_bus_v3b_2b.edg.xml (la red v3bs_2b la construye 13_semaforos_scats.py menos_carril 2b)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import sumo

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
sys.path.append(str(SIM))
from conteos_accesos import norm  # noqa: E402

UMBRAL = float(sys.argv[1]) if len(sys.argv) > 1 else 40
RED = SIM / "red"
NET2, NET3 = RED / "cuenca_piloto_v2.net.xml", RED / "cuenca_piloto_v3_carril_bus.net.xml"
BUSES = SIM / "buses" / "equilibrio_bahia" / "buses.rou.xml"
env = dict(os.environ, SUMO_HOME=sumo.SUMO_HOME)

net = sumolib.net.readNet(str(NET2))
rutas = {r.id: r.edges.split() for r in sumolib.xml.parse(str(BUSES), "route")}
bh = defaultdict(float)
for fl in sumolib.xml.parse(str(BUSES), "flow"):
    if fl.type == "bus":
        for e in rutas[fl.route]:
            bh[e] += 3600 / float(fl.period)

filas = []
for eid, b in bh.items():
    if b < UMBRAL:
        continue
    e = net.getEdge(eid)
    remigio = "remigio crespo" in norm(e.getName())
    if e.getLaneNumber() >= 2 or remigio:
        filas.append({"arista": eid, "calle": e.getName(), "buses_h": round(b), "carriles": e.getLaneNumber(),
                      "accion": "agrega carril bus (sin parqueo)" if remigio and e.getLaneNumber() == 1
                      else "carril derecho solo bus", "largo_m": round(e.getLength())})
t = pd.DataFrame(filas)
t.to_csv(RED / "carriles_bus_v3.csv", index=False, encoding="utf-8-sig")
print(f"tramos con carril exclusivo: {len(t)} ({t.largo_m.sum() / 1000:.1f} km); sin cambio por tener 1 carril: "
      f"{sum(1 for e, b in bh.items() if b >= UMBRAL) - len(t)}")
print(t.groupby("calle").agg(km=("largo_m", lambda s: round(s.sum() / 1000, 1)), buses_h=("buses_h", "max"))
      .sort_values("km", ascending=False).head(20).to_string())

with open(RED / "carriles_bus_v3.edg.xml", "w", encoding="utf-8") as f:
    f.write("<edges>\n")
    for r in t.itertuples():
        n = r.carriles + (1 if r.accion.startswith("agrega") else 0)
        f.write(f'  <edge id="{r.arista}" numLanes="{n}">\n    <lane index="0" allow="bus"/>\n  </edge>\n')
    f.write("</edges>\n")
rc = subprocess.run([str(Path(sumo.SUMO_HOME) / "bin" / "netconvert"), "-s", str(NET2), "-e",
                     str(RED / "carriles_bus_v3.edg.xml"), "-o", str(NET3), "--no-warnings"],
                    env=env, capture_output=True, text=True)
if rc.returncode != 0:
    sys.exit(rc.stderr[-2000:])
print("red v3:", NET3.name)

# Red v3b para el modo mesoscopico (una sola cola por calle, donde un carril exclusivo no tiene efecto): los corredores
# pierden un carril para todos. Se usa SOLO para medir el costo del carril exclusivo en los autos.
NET3B = RED / "cuenca_piloto_v3b_menos_carril.net.xml"
with open(RED / "carriles_bus_v3b.edg.xml", "w", encoding="utf-8") as f:
    f.write("<edges>\n")
    for r in t[t.accion == "carril derecho solo bus"].itertuples():
        f.write(f'  <edge id="{r.arista}" numLanes="{r.carriles - 1}"/>\n')
    f.write("</edges>\n")
rc = subprocess.run([str(Path(sumo.SUMO_HOME) / "bin" / "netconvert"), "-s", str(NET2), "-e",
                     str(RED / "carriles_bus_v3b.edg.xml"), "-o", str(NET3B), "--no-warnings"],
                    env=env, capture_output=True, text=True)
if rc.returncode != 0:
    sys.exit(rc.stderr[-2000:])
print("red v3b:", NET3B.name)

# Escenario 2b: carril exclusivo solo en la Av. de las Americas y la Av. 24 de Mayo, donde se concentra casi la mitad de
# la demora de los buses en los corredores (11_escenario_carril_bus.py).
t2b = t[t.calle.fillna("").map(norm).isin(["avenida de las americas", "avenida 24 de mayo"])]
t2b.to_csv(RED / "carriles_bus_v3_2b.csv", index=False, encoding="utf-8-sig")
with open(RED / "carriles_bus_v3b_2b.edg.xml", "w", encoding="utf-8") as f:
    f.write("<edges>\n")
    for r in t2b[t2b.accion == "carril derecho solo bus"].itertuples():
        f.write(f'  <edge id="{r.arista}" numLanes="{r.carriles - 1}"/>\n')
    f.write("</edges>\n")
print(f"escenario 2b: {len(t2b)} tramos ({t2b.largo_m.sum() / 1000:.1f} km)")
