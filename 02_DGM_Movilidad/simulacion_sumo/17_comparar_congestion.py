"""
Compara la congestión y el ajuste a los conteos entre dos corridas de 09_buses.py (por defecto: la situación actual con
semáforos reales y la versión «centro realista»).

Entrada: buses/<corrida>/aristas_todos.xml (todos los vehículos, 7:00-8:00), viajes.xml y resumen_escenario.csv;
         conteos 2023 por acceso (calibracion/ambos_v2/comparacion_accesos.csv).
Salida (pantalla y buses/comparacion_congestion.csv):
  - ajuste a los 38 accesos contados (r, error típico, volumen %, GEH < 5) y por intersección;
  - congestión: km de calle con tráfico y velocidad bajo el 25 % y el 50 % del límite; velocidad en el centro;
  - autos: viaje medio y demora; bus: velocidad mediana.

Uso:  py simulacion_sumo/17_comparar_congestion.py [corrida_a corrida_b]
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import sumo
from shapely.geometry import Point

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
BASE = SIM.parent
corridas = sys.argv[1:] or ["calibrada_bahia_reruteo_scats", "calibrada_bahia_reruteo_scats_centro"]
acc = pd.read_csv(SIM / "calibracion" / "ambos_v2" / "comparacion_accesos.csv")
centro = gpd.read_file(BASE / "datos" / "zonas" / "zonas_od_2025.gpkg")
centro = centro[centro.Zona.str.contains("Centro Historico", case=False)].to_crs(4326).geometry.union_all()
net = sumolib.net.readNet(str(SIM / "red" / "cuenca_piloto_v2s.net.xml"))   # límites y forma (iguales en ambas)
en_centro = {}
for e in net.getEdges():
    x, y = e.getShape()[len(e.getShape()) // 2]
    en_centro[e.getID()] = centro.contains(Point(net.convertXY2LonLat(x, y)))

filas, por_inter = [], {}
for c in corridas:
    d = SIM / "buses" / c
    ent, rows = {}, []
    for iv in sumolib.xml.parse(str(d / "aristas_todos.xml"), "interval"):
        for e in iv.edge or []:
            v = float(e.entered or 0)
            ent[e.id] = ent.get(e.id, 0) + v
            if net.hasEdge(e.id) and v >= 50 and e.speed:
                E = net.getEdge(e.id)
                rows.append((E.getLength(), float(e.speed) / E.getSpeed(), float(e.speed) * 3.6, v, en_centro[e.id]))
    t = pd.DataFrame(rows, columns=["m", "rel", "kmh", "veh", "centro"])
    s = acc.arista.map(ent).fillna(0)
    geh = np.sqrt(2 * (s - acc.contados) ** 2 / (s + acc.contados).clip(lower=1))
    por_inter[c] = s.groupby(acc.interseccion).sum()
    autos = []
    for ev, el in ET.iterparse(d / "viajes.xml"):
        if el.tag == "tripinfo":
            if el.get("vType") not in ("bus", "tranvia") and 25200 <= float(el.get("depart")) < 28800:
                autos.append((float(el.get("duration")), float(el.get("timeLoss"))))
            el.clear()
    a = np.array(autos)
    r = pd.read_csv(d / "resumen_escenario.csv").iloc[0]
    tc = t[t.centro]
    filas.append({"corrida": c, "r_conteos": round(np.corrcoef(s, acc.contados)[0, 1], 2),
                  "error_tipico_%": round((100 * (s - acc.contados).abs() / acc.contados).median()),
                  "volumen_%": round(100 * s.sum() / acc.contados.sum()), "GEH<5_%": round(100 * (geh < 5).mean()),
                  "km_bajo_25%": round(t[t.rel < 0.25].m.sum() / 1000, 1),
                  "km_bajo_50%": round(t[t.rel < 0.5].m.sum() / 1000, 1),
                  "centro_kmh": round((tc.kmh * tc.veh).sum() / tc.veh.sum(), 1),
                  "centro_km_bajo_50%": round(tc[tc.rel < 0.5].m.sum() / 1000, 1),
                  "auto_min": round(a[:, 0].mean() / 60, 2), "auto_demora_min": round(a[:, 1].mean() / 60, 2),
                  "auto_demora_p90_min": round(np.quantile(a[:, 1], 0.9) / 60, 1),
                  "bus_kmh": r.bus_kmh_mediana, "tranvia_kmh": r.get("tranvia_kmh"),
                  "teletransportes": r.teletransportes, "en_calle_9_30": r.en_calle_9_30})
res = pd.DataFrame(filas)
res.to_csv(SIM / "buses" / "comparacion_congestion.csv", index=False, encoding="utf-8-sig")
print(res.T.to_string())
cont = acc.groupby("interseccion").contados.sum()
tab = pd.DataFrame({"contados": cont, **{c: (100 * por_inter[c] / cont).round() for c in corridas}})
print("\n% simulado / contado por intersección:\n", tab.sort_values(corridas[0]).to_string())
