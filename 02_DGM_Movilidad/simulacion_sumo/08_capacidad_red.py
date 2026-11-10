"""
Ajuste de capacidad de la red piloto (version 2), tras ver que los accesos semaforizados de las avenidas se saturaban
con un tercio del trafico contado.

1. Carriles: OpenStreetMap registra con 1 carril por sentido varios tramos de avenida que en Cuenca tienen 2. Se pasan a
   2 carriles los tramos de "Avenida ..." y de la Sebastian de Benalcazar que tienen 1. Excepcion: la Av. Remigio
   Crespo Toral se deja con 1 carril util por sentido, porque el otro suele estar ocupado por autos parqueados.
   (Criterio de conocimiento local; verificar con la DGM.)
   Rieles: OSM dibuja varios tramos del tranvia en un solo sentido; se habilitan en ambos sentidos (via propia).
2. Semaforos: se probo recalcular el verde con el metodo de Webster y se descarto (empeoraba la congestion).

Uso:  py simulacion_sumo/08_capacidad_red.py [escenario]
Salida: simulacion_sumo/red/cuenca_piloto_v2.net.xml, red/cambios_carriles_v2.csv
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import sumo

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
sys.path.append(str(SIM))
from conteos_accesos import norm  # noqa: E402

ESC = sys.argv[1] if len(sys.argv) > 1 else "ambos"
RED = SIM / "red"
NET1, NET2 = RED / "cuenca_piloto.net.xml", RED / "cuenca_piloto_v2.net.xml"
RUTAS = SIM / "calibracion" / ESC / "ronda1_calibrar" / "calibrada.rou.xml"     # demanda calibrada (07)
BIN, TOOLS = Path(sumo.SUMO_HOME) / "bin", Path(sumo.SUMO_HOME) / "tools"
env = dict(os.environ, SUMO_HOME=sumo.SUMO_HOME)

# ----------------------------------------------------------------------------- 1. carriles
net = sumolib.net.readNet(str(NET1))
cambios = []
for e in net.getEdges():
    if e.getFunction() == "internal" or not e.allows("passenger") or e.getLaneNumber() != 1:
        continue
    n = norm(e.getName())
    if (n.startswith("avenida") or "benalcazar" in n) and "remigio crespo" not in n:
        cambios.append({"arista": e.getID(), "calle": e.getName(), "tipo": e.getType(), "largo_m": round(e.getLength())})
cambios = pd.DataFrame(cambios)
cambios.to_csv(RED / "cambios_carriles_v2.csv", index=False, encoding="utf-8-sig")
with open(RED / "carriles_v2.edg.xml", "w", encoding="utf-8") as f:
    f.write("<edges>\n")
    for a in cambios.arista:
        f.write(f'  <edge id="{a}" numLanes="2"/>\n')
    f.write("</edges>\n")
print(f"tramos pasados de 1 a 2 carriles: {len(cambios)} ({cambios.largo_m.sum() / 1000:.1f} km)")
print(cambios.groupby("calle").largo_m.sum().sort_values(ascending=False).head(15).to_string())
r = subprocess.run([str(BIN / "netconvert"), "-s", str(NET1), "-e", str(RED / "carriles_v2.edg.xml"),
                    "-o", str(NET2), "--no-warnings",
                    "--railway.topology.all-bidi"],         # rieles del tranvia utilizables en ambos sentidos
                   env=env, capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(r.stderr)

# ----------------------------------------------------------------------------- 2. semaforos (Webster): descartado
# Se probo recalcular el verde con tlsCycleAdaptation.py (Webster) y empeoraba la congestion (4 518 vehiculos sin
# llegar a las 9:00 contra 0 con los programas por defecto). La red v2 usa los programas por defecto.
