"""
Velocidades máximas oficiales de la jerarquía vial en la red del simulador.

Entrada: datos/JERARQUIA VIAL/*.shp (jerarquía vial de Cuenca, entregada por la DGM: preferencia no motorizada
         10 km/h, vías de retorno 20, locales 30, colectoras 40, arteriales 50, estatales 90; campo vel_max_pe) y la red
         red/cuenca_piloto_v2s.net.xml (velocidades de OpenStreetMap).
Proceso: a cada tramo de calle para autos se le asigna la velocidad máxima de la vía de la jerarquía más cercana a su
         punto medio, si está a menos de 12 m y va en la misma dirección (diferencia de rumbo menor a 30°, para no
         tomar la calle que cruza). Los tramos sin vía de la jerarquía cerca conservan su velocidad. Rieles del
         tranvía sin cambio. Los carriles y las conexiones no cambian, así que los programas de semáforo de SCATS
         (red/semaforos_scats.add.xml) siguen valiendo.
Salida:  red/velocidades_oficiales.edg.xml, red/velocidades_oficiales.csv y red/cuenca_piloto_v2s_vel.net.xml
         (se usa con 09_buses.py ... scats vel_oficial).

Uso:  py simulacion_sumo/18_velocidades_oficiales.py
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import math
import os
import subprocess
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
J = pd.concat([gpd.read_file(f).assign(categoria=f.stem.split(" - ")[1])
               for f in sorted((BASE / "datos" / "JERARQUIA VIAL").glob("*.shp"))]).to_crs(32717)
J = J[J.vel_max_pe > 0].reset_index(drop=True)
net = sumolib.net.readNet(str(RED / "cuenca_piloto_v2s.net.xml"))
a_utm = gpd.GeoSeries([Point(0, 0)], crs=4326).to_crs(32717).crs   # solo para dejar claro el sistema de destino


def rumbo(p, q):
    return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 180     # dirección sin sentido (0-180°)


filas = []
for e in net.getEdges():
    if e.getFunction() == "internal" or not e.allows("passenger"):
        continue
    sh = e.getShape()
    k = max(1, len(sh) // 2)
    p, q = sh[k - 1], sh[k]
    mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
    lon, lat = net.convertXY2LonLat(mx, my)
    lon2, lat2 = net.convertXY2LonLat(q[0], q[1])
    filas.append({"arista": e.getID(), "calle": e.getName(), "v_osm_kmh": round(e.getSpeed() * 3.6, 1),
                  "geometry": Point(lon, lat), "p2": Point(lon2, lat2)})
d = gpd.GeoDataFrame(filas, geometry="geometry", crs=4326).to_crs(32717)
d["p2"] = gpd.GeoSeries(d.p2, crs=4326).to_crs(32717)
j = gpd.sjoin_nearest(d, J[["categoria", "vel_max_pe", "nombre_via", "geometry"]], max_distance=12,
                      distance_col="dist")
j = j[~j.index.duplicated()]
ok = []
for i, r in j.iterrows():
    linea = J.geometry[r.index_right]
    s = linea.project(r.geometry)
    a, b = linea.interpolate(max(0, s - 5)), linea.interpolate(min(linea.length, s + 5))
    dif = abs(rumbo((a.x, a.y), (b.x, b.y)) - rumbo((r.geometry.x, r.geometry.y), (r.p2.x, r.p2.y)))
    ok.append(min(dif, 180 - dif) < 30)
j = j[ok]
j["v_oficial_kmh"] = j.vel_max_pe
j[["arista", "calle", "categoria", "nombre_via", "v_osm_kmh", "v_oficial_kmh", "dist"]].to_csv(
    RED / "velocidades_oficiales.csv", index=False, encoding="utf-8-sig")
with open(RED / "velocidades_oficiales.edg.xml", "w", encoding="utf-8") as f:
    f.write("<edges>\n")
    for r in j.itertuples():
        f.write(f'  <edge id="{r.arista}" speed="{r.v_oficial_kmh / 3.6:.2f}"/>\n')
    f.write("</edges>\n")
env = dict(os.environ, SUMO_HOME=sumo.SUMO_HOME)
rc = subprocess.run([str(Path(sumo.SUMO_HOME) / "bin" / "netconvert"), "-s", str(RED / "cuenca_piloto_v2s.net.xml"),
                     "-e", str(RED / "velocidades_oficiales.edg.xml"),
                     "-o", str(RED / "cuenca_piloto_v2s_vel.net.xml"), "--no-warnings"],
                    env=env, capture_output=True, text=True)
if rc.returncode != 0:
    sys.exit(rc.stderr[-2000:])
print(f"tramos para autos: {len(d)}; con velocidad oficial: {len(j)} "
      f"({100 * len(j) / len(d):.0f} %); sin vía de la jerarquía cerca: {len(d) - len(j)}")
print(j.groupby("categoria").agg(tramos=("arista", "size"), v_oficial=("v_oficial_kmh", "first"),
                                 v_osm_media=("v_osm_kmh", "mean")).round(1).to_string())
