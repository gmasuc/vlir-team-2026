"""
Exploracion de los datos de transporte publico recibidos de la DGM (octubre 2026).
Genera figuras y tablas resumen en analisis/01_exploracion/.
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import glob
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LogNorm
from matplotlib.lines import Line2D

BASE = Path(__file__).parent
GIS = BASE / "datos" / "GIS_Transporte"
OUT = BASE / "analisis" / "01_exploracion"
OUT.mkdir(parents=True, exist_ok=True)

TINTA, TINTA2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
AZUL, AZUL_CLARO, GRIS_CLARO = "#1c5cab", "#86b6ef", "#cfcdc6"
CATEG = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"]  # orden fijo
plt.rcParams.update({"font.size": 10, "text.color": TINTA, "axes.labelcolor": TINTA2,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": GRID})


def minutos(s):
    t = s.astype(str).str.strip()
    t = t.where(t.str.count(":") >= 2, t + ":00")      # hh:mm -> hh:mm:00 (el tranvia ya viene con segundos)
    return pd.to_timedelta(t, errors="coerce").dt.total_seconds() / 60


def guardar(fig, nombre):
    fig.savefig(OUT / nombre, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("figura:", OUT / nombre)


# ----------------------------------------------------------------------------- datos
lineas = gpd.read_file(BASE / "datos" / "derivados" / "Lineas_corregido.gpkg")  # ver 03_corregir_tranvia.py
rural = gpd.read_file(GIS / "rutas_lines.shp")
paradas = gpd.read_file(GIS / "paradas.shp").explode(index_parts=False)  # MultiPoint de 1 punto
caract = pd.concat([gpd.read_file(f).assign(operadora=Path(f).stem.split("_")[-1])
                    for f in sorted(glob.glob(str(GIS / "02_Paradas Caracterizacion_*.shp")))],
                   ignore_index=True)
caract = gpd.GeoDataFrame(caract, geometry="geometry", crs=4326).dropna(subset=["geometry"])
od = pd.read_excel(BASE / "datos" / "matriz_OD_65zonas.xlsx", index_col=0)

# ----------------------------------------------------------------------------- tabla de lineas urbanas
# Ida/Retorno operativos; se excluyen alargues mal etiquetados como Ida/Retorno (lineas 1 y 3)
op = lineas[lineas["sentido"].isin(["Ida", "Retorno"])
            & ~lineas["name"].str.upper().str.startswith("ALARGUE", na=False)].copy()
for c, n in [("tiempo_rec", "t_min"), ("intervalo_", "h_lv"), ("interval_1", "h_sab"),
             ("interval_2", "h_dom")]:
    op[n] = minutos(op[c]).replace(0, np.nan)          # 00:00 = sin servicio
op["km"] = op.length / 1000
tabla = op.groupby("linename").agg(
    empresa=("empresa", "first"), km_ida_retorno=("km", "sum"), ciclo_min=("t_min", "sum"),
    flota=("flota", "sum"), intervalo_lv_min=("h_lv", "first"), intervalo_sab_min=("h_sab", "first"),
    intervalo_dom_min=("h_dom", "first"))
tabla["buses_hora_lv"] = (60 / tabla["intervalo_lv_min"]).round(1)
tabla["flota_necesaria"] = (tabla["ciclo_min"] / tabla["intervalo_lv_min"]).round(1)
tabla["n_paradas"] = [int((paradas.get("l" + str(l).lower(), pd.Series(dtype=float)) == 1).sum())
                      for l in tabla.index]
tabla = tabla.round(1).sort_values("buses_hora_lv", ascending=False)
tabla.to_csv(OUT / "resumen_lineas_urbanas.csv")
print(tabla.to_string())

# ----------------------------------------------------------------------------- F1 red urbana
bus = op[op["linename"] != "RUTA TRANVIA"].merge(tabla[["buses_hora_lv"]], left_on="linename",
                                                  right_index=True)
tranvia = lineas[lineas["linename"] == "RUTA TRANVIA"]
nlin = (paradas.filter(regex=r"^l") == 1).sum(axis=1)
fig, ax = plt.subplots(figsize=(9, 9))
for _, r in bus.iterrows():   # lineas superpuestas se suman visualmente: mas oscuro = mas buses
    gpd.GeoSeries([r.geometry]).plot(ax=ax, color=AZUL, alpha=0.18,
                                     lw=0.4 + 0.35 * np.nan_to_num(r["buses_hora_lv"]))
tranvia.plot(ax=ax, color="#eb6834", lw=2.2)
ax.scatter(paradas.geometry.x, paradas.geometry.y, s=2 + 4 * nlin, color=TINTA, alpha=0.5, lw=0)
ax.set_axis_off()
ax.set_title("Red urbana de buses: más grueso y oscuro = más buses por hora (lunes a viernes)",
             loc="left", fontsize=11, fontweight="bold")
ax.legend(handles=[Line2D([], [], color=AZUL, lw=3, alpha=0.6, label="líneas de bus (38)"),
                   Line2D([], [], color="#eb6834", lw=2.2, label="tranvía"),
                   Line2D([], [], marker="o", ls="", color=TINTA, alpha=0.5, ms=4,
                          label="paradas (tamaño = n.º de líneas)")],
          loc="lower left", frameon=False, fontsize=8.5)
x0, y0, _, _ = paradas.total_bounds
ax.plot([x0, x0 + 2000], [y0 - 400, y0 - 400], color=TINTA, lw=3)
ax.text(x0 + 1000, y0 - 250, "2 km", ha="center", fontsize=9)
guardar(fig, "f1_red_urbana.png")

# ----------------------------------------------------------------------------- F2 red rural
fig, ax = plt.subplots(figsize=(9, 8))
ops = sorted(rural["empresa"].unique())
for i, e in enumerate(ops):
    rural[rural["empresa"] == e].plot(ax=ax, color=CATEG[i], lw=0.9)
op.plot(ax=ax, color=TINTA, lw=0.5, alpha=0.5)
ax.set_axis_off()
ax.set_title("Rutas rurales (por código de operadora) y red urbana (negro)", loc="left",
             fontsize=11, fontweight="bold")
ax.legend(handles=[Line2D([], [], color=CATEG[i], lw=2, label=f"{e} ({(rural.empresa == e).sum()} rutas)")
                   for i, e in enumerate(ops)]
          + [Line2D([], [], color=TINTA, lw=1, alpha=0.5, label="red urbana")],
          loc="lower left", frameon=False, fontsize=8.5)
guardar(fig, "f2_red_rural.png")

# ----------------------------------------------------------------------------- F3 caracterizacion
si = lambda s: s.astype(str).str.upper().isin(["SI", "BUENO"])
atrib = pd.DataFrame({"Señalización vertical": si(caract["Señal Ver"]), "Caseta": si(caract["Caseta"]),
                      "Asientos": si(caract["Asientos"]), "Paso peatonal": si(caract["Pasos Peat"]),
                      "Basurero": si(caract["Basurero"]), "Bahía de estacionamiento": si(caract["Bahia de e"])})
pct = (atrib.mean() * 100).sort_values()
cat = caract["CATEGORIA"].value_counts().reindex(list("ABCD")).fillna(0)
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.4), gridspec_kw={"width_ratios": [1, 1.6], "wspace": 0.75})
a1.bar(cat.index, cat.values, color=["#184f95", "#2a78d6", "#6da7ec", "#b7d3f6"], width=0.6)
for i, v in enumerate(cat.values):
    a1.text(i, v + 8, f"{int(v)}", ha="center", color=TINTA)
a1.set_title("Paradas rurales por categoría\n(A = mejor equipada)", loc="left", fontweight="bold")
a1.spines[["top", "right", "left"]].set_visible(False); a1.set_yticks([])
a2.barh(pct.index, pct.values, color=AZUL, height=0.6)
for i, v in enumerate(pct.values):
    a2.text(v + 1, i, f"{v:.0f} %", va="center", color=TINTA)
a2.set_xlim(0, 100); a2.set_title(f"¿Qué tienen? ({len(caract)} paradas evaluadas)", loc="left",
                                  fontweight="bold")
a2.spines[["top", "right"]].set_visible(False); a2.tick_params(axis="y", length=0, labelcolor=TINTA)
guardar(fig, "f3_estado_paradas_rurales.png")

# ----------------------------------------------------------------------------- F4 matriz OD
fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.8), gridspec_kw={"width_ratios": [1.15, 1], "wspace": 0.55})
im = a1.imshow(od.values.clip(min=1e-4), cmap="Blues", norm=LogNorm(vmin=1e-3, vmax=1))
corte = list(od.index).index("Baños 1") - 0.5            # zonas numeradas = parroquias rurales
a1.axvline(corte, color=TINTA, lw=0.8); a1.axhline(corte, color=TINTA, lw=0.8)
a1.set_xticks([corte / 2, (corte + len(od)) / 2], [f"urbanas ({int(corte + 0.5)})", f"rurales ({len(od) - int(corte + 0.5)})"])
a1.set_yticks([corte / 2, (corte + len(od)) / 2], ["urbanas", "rurales"])
a1.tick_params(length=0, labelcolor=TINTA)
a1.set_xlabel("zona de destino"); a1.set_ylabel("zona de origen")
cb = fig.colorbar(im, ax=a1, shrink=0.8, pad=0.03); cb.set_label("proporción de los viajes del origen")
a1.set_title("Matriz OD (cada fila suma 1)", loc="left", fontweight="bold")
atr = pd.Series(od.values.sum(0) - np.diag(od.values), od.columns).sort_values().tail(12)
a2.barh(atr.index, atr.values, color=AZUL, height=0.6)
a2.spines[["top", "right"]].set_visible(False); a2.tick_params(axis="y", length=0, labelcolor=TINTA)
a2.set_title("Zonas que más atraen viajes de otras zonas", loc="left", fontweight="bold")
a2.set_xlabel("suma de proporciones recibidas (sin viajes internos)")
guardar(fig, "f4_matriz_od.png")

# ----------------------------------------------------------------------------- resumen
print("\nRESUMEN")
print("lineas urbanas:", len(tabla) - 1, "+ tranvia | flota:", tabla["flota"].sum(),
      "| km red (ida+retorno):", round(tabla["km_ida_retorno"].sum()))
print("paradas urbanas:", len(paradas), "| sin linea:", int((nlin == 0).sum()),
      "| lineas por parada mediana:", nlin.median())
print("rutas rurales:", len(rural), "| km:", round(rural["Long_Km"].sum()))
print("paradas rurales caracterizadas:", len(caract), cat.to_dict())
print("OD intrazonal mediana:", round(float(np.median(np.diag(od.values))), 2))
