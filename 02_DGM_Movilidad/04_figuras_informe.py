"""
Figuras del informe del eje 3 (oferta de transporte publico) -> analisis/informe/figuras/
Usa los resultados ya calculados: ejecutar antes 01_exploracion_datos.py y el notebook 02_buses_por_hora.ipynb.
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import shutil
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D

import red_buses as rb

BASE = Path(__file__).parent
DER = BASE / "datos" / "derivados"
EDA = BASE / "analisis" / "01_exploracion"
FIG = BASE / "analisis" / "informe" / "figuras"
FIG.mkdir(parents=True, exist_ok=True)

TINTA, TINTA2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
AZUL, NARANJA, ROJO, GRIS = "#1c5cab", "#eb6834", "#d03b3b", "#b4b2a9"
NIVELES = [0, 10, 20, 40, 60, 200]
ETIQ = ["< 10", "10–20", "20–40", "40–60", "≥ 60"]
COLORES = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
CMAP, NORM = ListedColormap(COLORES), BoundaryNorm(NIVELES, len(COLORES))
plt.rcParams.update({"font.size": 10, "text.color": TINTA, "axes.labelcolor": TINTA2,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": GRID})


def guardar(fig, nombre):
    fig.savefig(FIG / nombre, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("figura:", nombre)


def sin_ejes(ax, titulo):
    ax.set_axis_off()
    ax.set_title(titulo, loc="left", fontweight="bold")


def escala(ax, x0, y0):
    ax.plot([x0, x0 + 2000], [y0, y0], color=TINTA, lw=3)
    ax.text(x0 + 1000, y0 + 150, "2 km", ha="center", fontsize=9)


# ----------------------------------------------------------------------------- datos
op = rb.lineas_operativas(gpd.read_file(DER / "Lineas_corregido.gpkg"))
tram = op[op["modo"] == "tranvia"]
t = gpd.read_file(DER / "buses_por_hora.gpkg")
calles = gpd.read_file(DER / "red_calles_osm.gpkg")
lin = pd.read_csv(EDA / "resumen_lineas_urbanas.csv", dtype={"linename": str}).set_index("linename")
corr = pd.read_csv(BASE / "analisis" / "corredores_buses_por_hora.csv", index_col=0)
val = pd.read_csv(BASE / "analisis" / "validacion_conteos_2023.csv", index_col=0)

# ----------------------------------------------------------------------------- figuras del EDA que se reutilizan
for f in ["f2_red_rural.png", "f3_estado_paradas_rurales.png", "f4_matriz_od.png"]:
    shutil.copy(EDA / f, FIG / f)

# ----------------------------------------------------------------------------- 1. frecuencia y flota por linea
b = lin.drop("RUTA TRANVIA", errors="ignore").copy()
b["holgura"] = b["flota"] - b["flota_necesaria"]
b = b.sort_values("buses_hora_lv")
fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 6.5), gridspec_kw={"width_ratios": [1, 1.1], "wspace": 0.3})
a1.barh(b.index, b["buses_hora_lv"], color=[ROJO if h < 0 else AZUL for h in b["holgura"]], height=0.7)
a1.set_xlabel("buses por hora (lunes a viernes)")
a1.tick_params(axis="y", labelsize=7.5, length=0)
a1.spines[["top", "right", "left"]].set_visible(False)
a1.set_title("Frecuencia de cada línea", loc="left", fontweight="bold")
a2.scatter(b["flota_necesaria"], b["flota"], color=[ROJO if h < 0 else AZUL for h in b["holgura"]], s=28, zorder=3)
m = 30
a2.plot([0, m], [0, m], color=GRIS, ls="--", lw=1)
a2.text(m * 0.62, m * 0.55, "flota = necesaria", color=MUTED, fontsize=8.5, rotation=40)
pos = {"9": (6, -4), "23": (-24, -4), "11": (-8, 9), "21": (-26, 3), "11B": (6, 3), "30": (6, -2)}
for nombre, r in b[b["holgura"] < -0.9].iterrows():
    a2.annotate(f"L{nombre}", (r["flota_necesaria"], r["flota"]), xytext=pos.get(nombre, (5, -3)),
                textcoords="offset points", fontsize=8, color=ROJO)
a2.set_xlim(0, m); a2.set_ylim(0, m)
a2.set_xlabel("buses necesarios (vuelta completa ÷ intervalo)"); a2.set_ylabel("buses asignados")
a2.spines[["top", "right"]].set_visible(False)
a2.set_title("¿Alcanzan los buses para cumplir el horario?", loc="left", fontweight="bold")
a2.legend(handles=[Line2D([], [], marker="o", ls="", color=AZUL, label="sí alcanzan"),
                   Line2D([], [], marker="o", ls="", color=ROJO, label="no alcanzan")], frameon=False, loc="upper left")
guardar(fig, "g1_frecuencia_flota.png")

# ----------------------------------------------------------------------------- 2. mapa de buses por hora + zoom
c = t.sort_values("bh_lv_max_sentido")
fig, (a1, a2) = plt.subplots(1, 2, figsize=(15, 7.5), gridspec_kw={"wspace": 0.03})
for ax in (a1, a2):
    calles.plot(ax=ax, color="#eeede8", lw=0.3)
a1.set_xlim(*t.total_bounds[[0, 2]]); a1.set_ylim(*t.total_bounds[[1, 3]])
c.plot(ax=a1, column="bh_lv_max_sentido", cmap=CMAP, norm=NORM, linewidth=0.5 + c["bh_lv_max_sentido"] / 20)
tram.plot(ax=a1, color=NARANJA, lw=1.4, ls="--")
escala(a1, t.total_bounds[0] + 300, t.total_bounds[1] + 400)
sin_ejes(a1, "Toda la red")
cx, cy = t.loc[t["bh_lv_max_sentido"].idxmax()].geometry.centroid.coords[0]
cx += 300
c.plot(ax=a2, column="bh_lv_max_sentido", cmap=CMAP, norm=NORM, linewidth=1 + c["bh_lv_max_sentido"] / 12)
tram.plot(ax=a2, color=NARANJA, lw=2, ls="--")
a2.set_xlim(cx - 2600, cx + 2600); a2.set_ylim(cy - 1900, cy + 1900)
escala(a2, cx - 2400, cy - 1750)
sin_ejes(a2, "Zoom al área central (5 × 4 km)")
a1.legend(handles=[Line2D([], [], color=col, lw=3, label=f"{e} buses/h") for col, e in zip(COLORES, ETIQ)]
          + [Line2D([], [], color=NARANJA, lw=1.5, ls="--", label="tranvía")],
          loc="upper right", frameon=True, fontsize=8.5, title="Lun-Vie, sentido más cargado", title_fontsize=8.5)
guardar(fig, "g2_mapa_buses_por_hora.png")

# ----------------------------------------------------------------------------- 3. km por nivel y por dia
dias = {}
for dia, nom in [("lv", "Lunes a viernes"), ("sab", "Sábado"), ("dom", "Domingo")]:
    x = t[t[f"bh_{dia}"] > 0]
    dias[nom] = x.groupby(pd.cut(x[f"bh_{dia}_max_sentido"], NIVELES, labels=ETIQ, right=False),
                          observed=False)["largo_m"].sum() / 1000
dias = pd.DataFrame(dias).T
fig, ax = plt.subplots(figsize=(9, 3.2))
izq = np.zeros(len(dias))
for e, col in zip(ETIQ, COLORES):
    ax.barh(dias.index[::-1], dias[e][::-1], left=izq[::-1], color=col, height=0.6, label=f"{e}",
            edgecolor="white", linewidth=1.5)
    for i, (v, l) in enumerate(zip(dias[e][::-1], izq[::-1])):
        if v > 25:
            ax.text(l + v / 2, i, f"{v:.0f}", ha="center", va="center", fontsize=8.5,
                    color="white" if col in COLORES[2:] else TINTA)
    izq = izq + dias[e].values
ax.set_xlabel("km de calle con al menos una línea de bus")
ax.spines[["top", "right", "left"]].set_visible(False); ax.tick_params(axis="y", length=0, labelcolor=TINTA)
ax.legend(title="buses/h", ncol=5, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), fontsize=8.5)
guardar(fig, "g3_niveles_por_dia.png")

# ----------------------------------------------------------------------------- 4. corredores principales
top = corr[corr.index != "(sin nombre en OSM)"].head(12).iloc[::-1]
fig, ax = plt.subplots(figsize=(9, 4.6))
ax.barh(top.index, top["buses_h_max"], color=[COLORES[4] if v >= 60 else COLORES[3] for v in top["buses_h_max"]], height=0.65)
for i, (v, n) in enumerate(zip(top["buses_h_max"], top["lineas_max"])):
    ax.text(v + 1, i, f"{v:.0f}  ·  {n:.0f} líneas", va="center", fontsize=8.5, color=TINTA)
ax.axvline(60, color=GRIS, ls="--", lw=1); ax.text(60.5, len(top) - 0.4, "60 buses/h", fontsize=8, color=MUTED)
ax.set_xlim(0, 105); ax.set_xlabel("máximo de buses por hora en un sentido (lunes a viernes)")
ax.spines[["top", "right", "left"]].set_visible(False); ax.tick_params(axis="y", length=0, labelcolor=TINTA)
guardar(fig, "g4_corredores.png")

# ----------------------------------------------------------------------------- 5. superposicion de lineas
fig, ax = plt.subplots(figsize=(8, 7))
calles.plot(ax=ax, color="#eeede8", lw=0.3)
t.plot(ax=ax, color=GRIS, lw=0.6)
s8 = t[t["n_lineas"] >= 8]
s8.plot(ax=ax, color=ROJO, lw=2.4)
ax.set_xlim(cx - 4000, cx + 4000); ax.set_ylim(cy - 3200, cy + 3000)
escala(ax, cx - 3800, cy - 3050)
ax.legend(handles=[Line2D([], [], color=ROJO, lw=2.4, label=f"8 o más líneas ({s8['largo_m'].sum() / 1000:.0f} km)"),
                   Line2D([], [], color=GRIS, lw=1, label="menos de 8 líneas")], loc="upper right", frameon=True, fontsize=8.5)
sin_ejes(ax, "")
guardar(fig, "g5_superposicion.png")

# ----------------------------------------------------------------------------- 6. buses en paralelo al tranvia
par = rb.tramos_paralelos(t, tram, dist=30, angulo=30)
fig, ax = plt.subplots(figsize=(9, 6.5))
calles.plot(ax=ax, color="#eeede8", lw=0.3)
tram.plot(ax=ax, color=NARANJA, lw=7, alpha=0.35)
par.plot(ax=ax, column="bh_lv_max_sentido", cmap=CMAP, norm=NORM, linewidth=2.2)
x0, y0, x1, y1 = tram.total_bounds
ax.set_xlim(x0 - 500, x1 + 500); ax.set_ylim(y0 - 500, y1 + 500)
escala(ax, x0 - 300, y0 - 350)
ax.legend(handles=[Line2D([], [], color=NARANJA, lw=6, alpha=0.4, label="tranvía")]
          + [Line2D([], [], color=col, lw=2.5, label=f"buses en paralelo: {e} buses/h") for col, e in zip(COLORES[1:], ETIQ[1:])],
          loc="upper left", frameon=True, fontsize=8.5)
sin_ejes(ax, "")
guardar(fig, "g6_tranvia_paralelo.png")
km_par = par.groupby(par["calle"].fillna("(sin nombre)"))["largo_m"].sum().div(1000).round(1).sort_values(ascending=False)
print("paralelo al tranvia:", round(par["largo_m"].sum() / 1000, 1), "km |", km_par.head(3).to_dict())

# ----------------------------------------------------------------------------- 7. validacion
v = val.dropna(subset=["programados_h"]).copy()
v.index = v.index.str.strip().str.upper()
terminal = v.index.str.upper().str.contains("BENALCAZAR Y DEL CHORRO|CALLE VIEJA")
corto = {"SEBASTIAN DE BENALCAZAR Y DEL CHORRO": "Benalcázar y Del Chorro", "CALLE VIEJA Y ELIA LIUT": "Calle Vieja y E. Liut",
         "SEBASTIAN DE BENALCAZAR Y AV ESPAÑA": "Benalcázar y Av. España", "MIGUEL VELEZ Y SIMON BOLIVAR": "M. Vélez y S. Bolívar",
         "AV MIGUEL VELEZ Y SANGURIMA": "M. Vélez y Sangurima", "AV 24 DE MAYO Y CUZCO": "24 de Mayo y Cuzco",
         "MIGUEL VELEZ Y MARISCAL LAMAR": "M. Vélez y Lamar", "MIGUEL VELEZ Y MARISCAL SUCRE": "M. Vélez y Sucre",
         "MIGUEL VELEZ Y PIO BRAVO": "M. Vélez y Pío Bravo"}
fig, ax = plt.subplots(figsize=(7, 6))
ax.plot([0, 120], [0, 120], color=GRIS, ls="--", lw=1)
ax.text(95, 99, "contado = programado", color=MUTED, fontsize=8.5, rotation=40)
ax.scatter(v.loc[~terminal, "programados_h"], v.loc[~terminal, "contados_h"], color=AZUL, s=40, zorder=3, label="intersecciones de la ciudad")
ax.scatter(v.loc[terminal, "programados_h"], v.loc[terminal, "contados_h"], color=NARANJA, s=40, zorder=3,
           label="junto al Terminal Terrestre\n(incluye buses interprovinciales)")
desp = {"M. Vélez y Lamar": (-70, -14), "M. Vélez y Sucre": (6, -4), "M. Vélez y S. Bolívar": (-110, 4),
        "Benalcázar y Av. España": (6, -12), "M. Vélez y Sangurima": (6, 3)}
for n, r in v.iterrows():
    if n in corto:
        ax.annotate(corto[n], (r["programados_h"], r["contados_h"]), xytext=desp.get(corto[n], (6, 3)),
                    textcoords="offset points", fontsize=8, color=TINTA2)
r_todo = np.corrcoef(v["programados_h"], v["contados_h"])[0, 1]
r_sin = np.corrcoef(v.loc[~terminal, "programados_h"], v.loc[~terminal, "contados_h"])[0, 1]
ax.set_xlim(-3, 120); ax.set_ylim(-3, 120)
ax.set_xlabel("buses/h programados (horarios DGM, lunes a viernes)"); ax.set_ylabel("buses/h contados (2023, pico de la mañana)")
ax.spines[["top", "right"]].set_visible(False)
ax.legend(frameon=False, loc="upper left", fontsize=8.5)
ax.text(118, 2, f"correlación: {r_todo:.2f} (todas) · {r_sin:.2f} (sin el terminal)", ha="right", fontsize=8.5, color=TINTA2)
guardar(fig, "g7_validacion.png")
print(f"validacion: {len(v)} ubicadas | r todas {r_todo:.2f} | r sin terminal {r_sin:.2f} | "
      f"suma programado {v.loc[~terminal, 'programados_h'].sum():.0f} vs contado {v.loc[~terminal, 'contados_h'].sum():.0f}")
