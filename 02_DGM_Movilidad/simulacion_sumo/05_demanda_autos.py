"""
Demanda de autos para SUMO (hora pico 7:00-8:00) a partir de la matriz OD y las tablas de viajes,
y comparacion con los conteos vehiculares 2023.

Uso:  py simulacion_sumo/05_demanda_autos.py [laborales|no_laborales|ambos]
Salidas en simulacion_sumo/demanda/<escenario>/: taz.xml, viajes.trips.xml, rutas.rou.xml, comparacion_conteos.csv
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import glob
import os
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import sumo
from shapely.geometry import LineString, Point

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

sys.path.append(str(Path(__file__).resolve().parents[1]))
import red_buses as rb  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
SIM = BASE / "simulacion_sumo"
ESC = sys.argv[1] if len(sys.argv) > 1 else "laborales"
OUT = SIM / "demanda" / ESC
OUT.mkdir(parents=True, exist_ok=True)
BIN = Path(sumo.SUMO_HOME) / "bin"

HORA = 7                      # franja 7:00-8:00
# modo de la encuesta -> (tipo de vehiculo en SUMO, personas por vehiculo: supuesto)
MODOS = {"Vehículo privado": ("auto", 1.3), "Taxi": ("auto", 1.2), "Motocicleta": ("moto", 1.1)}
VTYPES = ('  <vType id="auto" vClass="passenger"/>\n'
          '  <vType id="moto" vClass="motorcycle" length="2.2" maxSpeed="22"/>\n')
TIPOS_ORIGEN = ("highway.primary", "highway.secondary", "highway.tertiary", "highway.trunk",
                "highway.residential", "highway.unclassified", "highway.living_street")
rng = np.random.default_rng(2026)

# ----------------------------------------------------------------------------- 1. viajes en auto por zona
od = pd.read_excel(BASE / "datos" / "matriz_OD_65zonas.xlsx", index_col=0)
vt = pd.read_excel(BASE / "datos_originales" / "viajes_transporte.xlsx", index_col=0) / 100
archivos = {"laborales": ["viajes_laborales.xlsx"], "no_laborales": ["viajes_no_laborales.xlsx"],
            "ambos": ["viajes_laborales.xlsx", "viajes_no_laborales.xlsx"]}[ESC]
gen = {"auto": pd.Series(0.0, index=od.index), "moto": pd.Series(0.0, index=od.index)}
personas = 0.0
for f in archivos:
    d = pd.read_excel(BASE / "datos_originales" / f, index_col=0)
    h = d[d["Franja Horaria"] == HORA].set_index("Modo")["Viajes"]
    for m, (tipo, ocup) in MODOS.items():
        v = h.get(m, 0) * vt.loc[m].reindex(od.index).fillna(0)          # viajes de personas por zona de origen
        gen[tipo] += v / ocup
        personas += v.sum()
veh = {t: od.mul(g, axis=0) for t, g in gen.items()}                     # vehiculos por par origen-destino
print(f"[{ESC}] 7:00-8:00: autos {veh['auto'].values.sum():,.0f} | motos {veh['moto'].values.sum():,.0f} "
      f"(de {personas:,.0f} viajes de personas)")

# ----------------------------------------------------------------------------- 2. zonas -> calles de la red
net = sumolib.net.readNet(str(SIM / "red" / "cuenca_piloto.net.xml"))
zonas = gpd.read_file(BASE / "datos" / "zonas" / "zonas_od_2025.gpkg").to_crs(4326)
filas = []
for e in net.getEdges():
    if e.getFunction() == "internal" or not e.allows("passenger") or e.getLength() < 20 or e.getType() not in TIPOS_ORIGEN:
        continue
    x, y = e.getShape()[len(e.getShape()) // 2]
    lon, lat = net.convertXY2LonLat(x, y)
    filas.append((e.getID(), e.getLength(), e.getType(), Point(lon, lat)))
ed = gpd.GeoDataFrame(filas, columns=["edge", "largo", "tipo", "geometry"], crs=4326)
ed = gpd.sjoin(ed, zonas[["zona_od", "geometry"]], how="left", predicate="within").drop(columns="index_right")
taz = {z: g for z, g in ed.dropna(subset=["zona_od"]).groupby("zona_od")}
# zonas fuera del area piloto (o casi sin calles): entran por las vias principales mas cercanas
ppal = ed[ed.tipo.isin(["highway.primary", "highway.secondary", "highway.trunk"])].to_crs(32717)
zonas_utm = zonas.to_crs(32717).set_index("zona_od")
for z in od.index:
    if z not in taz or len(taz[z]) < 5:
        d = ppal.distance(zonas_utm.loc[z, "geometry"]).nsmallest(6).index
        taz[z] = ed.loc[d]
print(f"zonas con calles propias en la red: {sum(1 for z in od.index if ed.zona_od.eq(z).sum() >= 5)} de 65")
with open(OUT / "taz.xml", "w", encoding="utf-8") as f:
    f.write("<additional>\n")
    for i, z in enumerate(od.index):
        f.write(f'  <taz id="z{i:02d}" name="{z}" edges="{" ".join(taz[z].edge)}"/>\n')
    f.write("</additional>\n")

# ----------------------------------------------------------------------------- 3. viajes individuales
viajes = []
for tipo in veh:
    for oi, o in enumerate(od.index):
        for di, dz in enumerate(od.index):
            x = veh[tipo].iat[oi, di]
            n = int(x) + (rng.random() < x - int(x))                     # redondeo aleatorio sin sesgo
            if n == 0:
                continue
            ro, rd = taz[o], taz[dz]
            po, pd_ = ro.largo / ro.largo.sum(), rd.largo / rd.largo.sum()
            for _ in range(n):
                a, b = rng.choice(ro.edge.values, p=po), rng.choice(rd.edge.values, p=pd_)
                if a != b:
                    viajes.append((HORA * 3600 + rng.uniform(0, 3600), a, b, oi, di, tipo))
viajes.sort()
with open(OUT / "viajes.trips.xml", "w", encoding="utf-8") as f:
    f.write("<routes>\n" + VTYPES)
    for k, (t, a, b, oi, di, tipo) in enumerate(viajes):
        f.write(f'  <trip id="a{k}" type="{tipo}" depart="{t:.1f}" from="{a}" to="{b}" fromTaz="z{oi:02d}" toTaz="z{di:02d}"/>\n')
    f.write("</routes>\n")
print(f"viajes generados: {len(viajes):,}")

# ----------------------------------------------------------------------------- 4. rutas (flujo libre)
r = subprocess.run([str(BIN / "duarouter"), "-n", str(SIM / "red" / "cuenca_piloto.net.xml"), "--route-files", str(OUT / "viajes.trips.xml"),
                    "-o", str(OUT / "rutas.rou.xml"), "--ignore-errors", "--no-warnings", "--routing-threads", "4", "--no-step-log"],
                   capture_output=True, text=True)
rutas = list(sumolib.xml.parse_fast(str(OUT / "rutas.rou.xml"), "route", ["edges"]))
print(f"rutas encontradas: {len(rutas):,} de {len(viajes):,} ({len(rutas) / max(len(viajes), 1):.0%})")
vol = pd.Series(" ".join(r.edges for r in rutas).split()).value_counts()

# ----------------------------------------------------------------------------- 5. comparacion con conteos 2023
c = pd.read_csv(glob.glob(str(BASE / "datos" / "portal" / "gadcuenca_conteovehicular*.csv"))[0], sep=None, engine="python", encoding="latin-1")
c.columns = [x.strip() for x in c.columns]
c["livianos"] = c[[x for x in c.columns if x.upper().startswith("LIVIANOS")]].apply(pd.to_numeric, errors="coerce").sum(axis=1)
c["hora"] = pd.to_numeric(c["HORA INICIO"].astype(str).str.extract(r"(\d{1,2})\s*:")[0], errors="coerce")   # "6:00", " 6:00:00"...
obs = c[c.hora == HORA].groupby(c.DIRECCION.str.strip())["livianos"].sum()
calles = gpd.read_file(BASE / "datos" / "derivados" / "red_calles_osm.gpkg")
filas = []
for nombre, v in obs.items():
    p = rb.ubicar_interseccion(nombre, calles)
    if p is None:
        continue
    lon, lat = gpd.GeoSeries([p], crs=32717).to_crs(4326).iloc[0].coords[0]
    x, y = net.convertLonLat2XY(lon, lat)
    nodos = [n for n in net.getNodes() if np.hypot(n.getCoord()[0] - x, n.getCoord()[1] - y) < 40]
    entrantes = {e.getID() for n in nodos for e in n.getIncoming() if e.getFunction() != "internal"}
    salientes_internos = {e.getID() for n in nodos for e in n.getOutgoing()}
    entrantes -= salientes_internos                                          # cruces de varios nodos: solo lo que entra desde fuera
    filas.append((nombre, v, float(vol.reindex(list(entrantes)).fillna(0).sum()), len(nodos)))
comp = pd.DataFrame(filas, columns=["interseccion", "contados_livianos_h", "simulados_autos_h", "nodos"]).set_index("interseccion")
comp["razon_sim_obs"] = (comp.simulados_autos_h / comp.contados_livianos_h).round(2)
comp.to_csv(OUT / "comparacion_conteos.csv", encoding="utf-8-sig")
print(comp.round(0).to_string())
v = comp[comp.contados_livianos_h > 50]
print(f"\nintersecciones comparadas: {len(v)} | suma contados {v.contados_livianos_h.sum():,.0f} | suma simulados {v.simulados_autos_h.sum():,.0f} "
      f"| razon global {v.simulados_autos_h.sum() / v.contados_livianos_h.sum():.2f} | correlacion {np.corrcoef(v.contados_livianos_h, v.simulados_autos_h)[0, 1]:.2f}")
