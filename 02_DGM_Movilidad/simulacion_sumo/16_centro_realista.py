"""
Centro Histórico realista: menos capacidad en las calles del centro.

En el modelo, el centro circulaba a 24 km/h con 160–220 % de los autos contados en la Miguel Vélez: le sobraba
capacidad. En la realidad, en el centro (1) los buses paran en el carril para dejar y recoger pasajeros y (2) hay
parqueo tarifado legal de la EMOV (SERT), unas 1 424 plazas según una fuente no oficial; no hay lista oficial de
calles (pregunta 17 para la DGM). Como aproximación (cota superior del efecto del parqueo):
  - las calles del Centro Histórico con 2 carriles o más pierden 1 carril (el que ocupa el parqueo); las avenidas
    del borde (Huayna Cápac, Héroes de Verdeloma, 12 de Abril...) se mantienen;
  - en esas calles el bus para en el carril, sin bahía (09_buses.py ... centro).
El Centro Histórico es el polígono de la zona «01 Centro Historico» de la matriz origen-destino (2.6 km²).

Uso:  py simulacion_sumo/16_centro_realista.py
      py simulacion_sumo/13_semaforos_scats.py centro        (red v2sc y sus semáforos)
      py simulacion_sumo/09_buses.py ambos calibrada capa bahia reruteo scats centro
Salida: red/carriles_centro.edg.xml, red/aristas_centro.txt, red/carriles_centro.csv
        Versión con capacidad parcial (no se quita el carril): red/tipo_centro.edg.xml (esas calles pasan al tipo
        «centro_cap»), red/cuenca_piloto_v2scap_centro.net.xml y red/meso_centro_cap<NN>.add.xml, donde NN es el % de
        capacidad que queda (85, 70, 55): los tiempos entre vehículos del modo mesoscópico (tau) se dividen por NN/100.
        Uso: 09_buses.py ... scats cap70
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import os
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import sumo
from shapely.geometry import Point

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
BASE = SIM.parent
RED = SIM / "red"
net = sumolib.net.readNet(str(RED / "cuenca_piloto_v2s.net.xml"))
z = gpd.read_file(BASE / "datos" / "zonas" / "zonas_od_2025.gpkg")
centro = z[z.Zona.str.contains("Centro Historico", case=False)].to_crs(4326).geometry.union_all()

filas, todas = [], []
for e in net.getEdges():
    if e.getFunction() == "internal" or not e.allows("passenger"):
        continue
    x, y = e.getShape()[len(e.getShape()) // 2]
    if not centro.contains(Point(net.convertXY2LonLat(x, y))):
        continue
    todas.append(e.getID())
    # las avenidas del borde (Huayna Cápac, Héroes de Verdeloma, 12 de Abril...) no tienen parqueo SERT: se mantienen
    if e.getLaneNumber() >= 2 and not (e.getName() or "").startswith("Avenida"):
        filas.append({"arista": e.getID(), "calle": e.getName(), "carriles": e.getLaneNumber(),
                      "largo_m": round(e.getLength())})
t = pd.DataFrame(filas)
t.to_csv(RED / "carriles_centro.csv", index=False, encoding="utf-8-sig")
(RED / "aristas_centro.txt").write_text("\n".join(todas))
with open(RED / "carriles_centro.edg.xml", "w", encoding="utf-8") as f:
    f.write("<edges>\n")
    for r in t.itertuples():
        f.write(f'  <edge id="{r.arista}" numLanes="{r.carriles - 1}"/>\n')
    f.write("</edges>\n")
print(f"tramos del centro: {len(todas)}; con 2 carriles o más (pierden 1): {len(t)} ({t.largo_m.sum() / 1000:.1f} km)")
print(t.groupby("calle").largo_m.sum().sort_values(ascending=False).head(15).div(1000).round(2).to_string())

# ----------------------------------------------------------------------------- capacidad parcial
import subprocess  # noqa: E402

with open(RED / "tipo_centro.edg.xml", "w", encoding="utf-8") as f:
    f.write("<edges>\n")
    for r in t.itertuples():
        f.write(f'  <edge id="{r.arista}" type="centro_cap"/>\n')
    f.write("</edges>\n")
env = dict(os.environ, SUMO_HOME=sumo.SUMO_HOME)
rc = subprocess.run([str(Path(sumo.SUMO_HOME) / "bin" / "netconvert"), "-s", str(RED / "cuenca_piloto_v2s.net.xml"),
                     "-e", str(RED / "tipo_centro.edg.xml"), "-o", str(RED / "cuenca_piloto_v2scap_centro.net.xml"),
                     "--no-warnings"], env=env, capture_output=True, text=True)
if rc.returncode != 0:
    sys.exit(rc.stderr[-2000:])
TAU = {"tauff": 1.13, "taufj": 1.13, "taujf": 1.73, "taujj": 1.4}      # valores por defecto de SUMO
for nn in (85, 70, 55):
    with open(RED / f"meso_centro_cap{nn}.add.xml", "w", encoding="utf-8") as f:
        attrs = " ".join(f'{k}="{v / (nn / 100):.3f}"' for k, v in TAU.items())
        f.write(f'<additional>\n  <type id="centro_cap"><meso {attrs}/></type>\n</additional>\n')
print("red con capacidad parcial en el centro: cuenca_piloto_v2scap_centro.net.xml; niveles 85, 70 y 55 %")
