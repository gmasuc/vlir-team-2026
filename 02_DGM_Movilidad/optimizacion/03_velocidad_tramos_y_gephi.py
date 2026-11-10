"""
Revisión de la velocidad del bus tramo por tramo y exportación de la red de pasajeros a Gephi.

Pregunta: el grafo de pasajeros (02_grafo_pasajeros.py) le da a cada línea su velocidad observada del Escenario 0 y la
reparte a lo largo del recorrido según SUMO (más lento en el centro). ¿Queda el bus demasiado rápido en el centro y en
el eje del tranvía, frente a lo que da el modelo calibrado de SUMO?

Proceso: para cada tramo de parada a parada se comparan
  - km/h en el grafo (velocidad observada de la línea × reparto de SUMO);
  - km/h en SUMO (mediana de los buses del modelo calibrado, 7:00-8:00);
  - km/h del tranvía en el tramo paralelo más cercano;
y se resumen por zona: Centro Histórico, eje del tranvía (a menos de 150 m de su vía) y resto.
Salida (optimizacion/grafo_pasajeros/):
  - velocidad_tramos.csv y velocidad_tramos.png (comparación);
  - red_pasajeros.gexf: para Gephi. Nodos = paradas, con su posición real (x, y en metros); aristas = tramos entre
    paradas consecutivas, sumando las líneas que pasan: pasajeros/h, buses/h, líneas, km/h en el grafo y en SUMO,
    cociente grafo/SUMO, si está en el centro o en el eje del tranvía, y si es bus o tranvía.

Uso:  py optimizacion/03_velocidad_tramos_y_gephi.py
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import importlib
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
gp = importlib.import_module("02_grafo_pasajeros")
OUT = AQUI / "grafo_pasajeros"

lin, par = gp.cargar_oferta()
vs = gp.velocidades_sumo(par)                         # metros por minuto en SUMO
fac = gp.factores_sumo(par)
ct = pd.read_csv(OUT / "cargas_tramos.csv", dtype={"parada": str})
li = lin.set_index("id_ld")

# ----------------------------------------------------------------------------- 1. tramos
filas = []
for k, g in par.sort_values(["id_ld", "k"]).groupby("id_ld"):
    g = g.reset_index(drop=True)
    carga = ct[ct.id_ld == k].set_index("k").pasajeros_h
    for i in range(len(g) - 1):
        a, b = g.iloc[i], g.iloc[i + 1]
        m = b.pos_m - a.pos_m
        f = fac.get((k, a.parada, b.parada))
        filas.append({"id_ld": k, "linea": li.loc[k, "linea"], "modo": li.loc[k, "modo"], "desde": a.parada,
                      "hasta": b.parada, "nombre_desde": a.nombre, "nombre_hasta": b.nombre, "metros": m,
                      "kmh_grafo": li.loc[k, "kmh"] * (f if f is not None else 1.0),
                      "kmh_sumo": vs.get((k, a.parada, b.parada), np.nan) * 60 / 1000,
                      "buses_h": 60 / li.loc[k, "intervalo_min"], "pasajeros_h": carga.get(a.k, 0),
                      "geometry": LineString([(a.x, a.y), (b.x, b.y)])})
t = gpd.GeoDataFrame(filas, crs=32717)
zon = gpd.read_file(gp.D / "zonas" / "zonas_od_2025.gpkg").to_crs(32717).set_index("zona_od")
centro = zon.loc["Centro Historico", "geometry"]
via = gpd.GeoSeries([g.geometry.iloc[0] for _, g in gpd.GeoDataFrame(
    lin[lin.modo == "tranvia"].assign(geometry=lambda d: gpd.GeoSeries.from_wkt(d.wkt)), crs=32717).groupby("id_ld")],
    crs=32717).union_all()
mid = t.geometry.interpolate(0.5, normalized=True)
t["en_centro"] = mid.within(centro)
t["eje_tranvia"] = mid.distance(via) < 150
t["zona"] = np.where(t.en_centro, "Centro Histórico", np.where(t.eje_tranvia, "Eje del tranvía (fuera del centro)",
                                                                 "Resto de la ciudad"))
t["grafo_sobre_sumo"] = t.kmh_grafo / t.kmh_sumo
t.drop(columns="geometry").to_csv(OUT / "velocidad_tramos.csv", index=False, encoding="utf-8-sig")


def resumen(d):
    """km/h por distancia recorrida (km totales / horas totales), no promedio simple de tramos."""
    ok = d.dropna(subset=["kmh_sumo"])
    return pd.Series({"tramos": len(d), "km": d.metros.sum() / 1000,
                      "kmh_grafo": d.metros.sum() / (d.metros / d.kmh_grafo).sum(),
                      "kmh_sumo": ok.metros.sum() / (ok.metros / ok.kmh_sumo).sum() if len(ok) else np.nan,
                      "kmh_grafo_mismos_tramos": ok.metros.sum() / (ok.metros / ok.kmh_grafo).sum() if len(ok) else np.nan})


res = t.groupby(["modo", "zona"]).apply(resumen).round(1)
res["grafo/sumo"] = (res.kmh_grafo_mismos_tramos / res.kmh_sumo).round(2)
print(res.to_string())
res.to_csv(OUT / "velocidad_tramos_resumen.csv", encoding="utf-8-sig")

# ----------------------------------------------------------------------------- 2. figura
fig, axs = plt.subplots(1, 2, figsize=(14, 6))
bus = t[(t.modo == "bus") & t.kmh_sumo.notna() & (t.metros > 200)]
for z, c in [("Resto de la ciudad", "#95a5a6"), ("Eje del tranvía (fuera del centro)", "#1e8449"),
             ("Centro Histórico", "#c0392b")]:
    d = bus[bus.zona == z]
    axs[0].scatter(d.kmh_sumo, d.kmh_grafo, s=8, alpha=0.5, color=c, label=f"{z} ({len(d)} tramos)")
axs[0].plot([0, 60], [0, 60], "k--", lw=0.8)
axs[0].set_xlim(0, 60); axs[0].set_ylim(0, 60)
axs[0].set_xlabel("km/h del bus en SUMO (modelo calibrado)")
axs[0].set_ylabel("km/h del bus en el grafo (observada × reparto de SUMO)")
axs[0].set_title("Cada punto es un tramo de parada a parada (> 200 m)")
axs[0].legend(fontsize=8)
r = res.reset_index()
CORTO = {"Centro Histórico": "centro", "Eje del tranvía (fuera del centro)": "eje del\ntranvía",
         "Resto de la ciudad": "resto"}
etq = [f"{m}\n{CORTO[z]}" for m, z in zip(r.modo, r.zona)]
x = np.arange(len(r))
axs[1].bar(x - 0.2, r.kmh_sumo, 0.4, label="SUMO", color="#7f8c8d")
axs[1].bar(x + 0.2, r.kmh_grafo_mismos_tramos, 0.4, label="Grafo", color="#2e86c1")
for i, v in enumerate(r["grafo/sumo"]):
    axs[1].text(i, max(r.kmh_sumo[i], r.kmh_grafo_mismos_tramos[i]) + 0.5, f"×{v}", ha="center", fontsize=9)
axs[1].set_xticks(x, etq, fontsize=8)
axs[1].set_ylabel("km/h (km recorridos / horas)")
axs[1].set_title("Velocidad por zona: grafo frente a SUMO")
axs[1].legend()
fig.tight_layout()
fig.savefig(OUT / "velocidad_tramos.png", dpi=150)

# ----------------------------------------------------------------------------- 3. Gephi
G = nx.DiGraph()
pt = par.drop_duplicates("parada").set_index("parada")
n_lin = par.groupby("parada").id_ld.nunique()
x0, y0 = pt.x.mean(), pt.y.mean()
for p, r in pt.iterrows():
    G.add_node(p, label=str(r.nombre), lineas=int(n_lin[p]), tranvia=p.startswith("T"),
               viz={"position": {"x": float(r.x - x0) / 10, "y": float(r.y - y0) / 10, "z": 0.0},
                    "size": 2.0 + float(n_lin[p])})
for (a, b), d in t.groupby(["desde", "hasta"]):
    ok = d.dropna(subset=["kmh_sumo"])
    kg = d.metros.sum() / (d.metros / d.kmh_grafo).sum()
    ks = ok.metros.sum() / (ok.metros / ok.kmh_sumo).sum() if len(ok) else -1.0
    tram = (d.modo == "tranvia").any()
    G.add_edge(a, b, lineas=" ".join(sorted(d.linea.astype(str).unique())), n_lineas=int(d.linea.nunique()),
               pasajeros_h=float(d.pasajeros_h.sum()), buses_h=float(d.buses_h.sum()), metros=float(d.metros.mean()),
               kmh_grafo=round(float(kg), 1), kmh_sumo=round(float(ks), 1),
               grafo_sobre_sumo=round(float(kg / ks), 2) if ks > 0 else -1.0, zona=d.zona.iloc[0],
               modo="tranvía" if tram else "bus", weight=max(float(d.pasajeros_h.sum()), 1.0),
               viz={"color": {"r": 30, "g": 132, "b": 73, "a": 1.0} if tram else {"r": 192, "g": 57, "b": 43, "a": 1.0}})
nx.write_gexf(G, OUT / "red_pasajeros.gexf")
print(f"Gephi: {G.number_of_nodes()} paradas, {G.number_of_edges()} tramos -> {OUT / 'red_pasajeros.gexf'}")
