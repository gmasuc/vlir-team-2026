"""
Figuras y tablas para el informe del Paso 1 (cumbe_paso1/informe/).
Requiere haber ejecutado antes cumbe_paso1_mapa_preliminar.py.
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import osmnx as ox
import rasterio
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D

import cumbe_paso1_mapa_preliminar as p

INF = p.OUT / "informe"
FIG = INF / "figuras"
FIG.mkdir(parents=True, exist_ok=True)

# paleta (tinta y superficies neutras; un color por clase, rojo reservado para "critico")
TINTA, TINTA2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
AZUL, AZUL_CLARO = "#1c5cab", "#86b6ef"
NARANJA, GRIS, GRIS_CLARO, ROJO = "#eb6834", "#7d7b75", "#cfcdc6", "#d03b3b"
plt.rcParams.update({"font.size": 10, "text.color": TINTA, "axes.labelcolor": TINTA2,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": GRID,
                     "figure.facecolor": "white", "axes.facecolor": "white"})

# ----------------------------------------------------------------------------- datos
gpkg = p.OUT / "cumbe_paso1.gpkg"
limite = gpd.read_file(gpkg, layer="limite")
cuenca = gpd.read_file(gpkg, layer="cuenca")
cauces = gpd.read_file(gpkg, layer="cauces")
tramos = gpd.read_file(gpkg, layer="tramos")
par = tramos[tramos["en_parroquia"]].copy()
zona = limite.buffer(1500).union_all()
cauces = cauces.clip(zona)

rios = ox.features_from_polygon(gpd.GeoSeries([zona], crs=p.CRS_UTM).to_crs(4326).iloc[0],
                                tags={"waterway": ["river", "stream"]})
# el rio Cumbe esta etiquetado como "stream" en OSM: filtrar por nombre "Rio ..."
rios = rios[rios.geom_type.isin(["LineString", "MultiLineString"])
            & rios["name"].fillna("").str.startswith("Río")]
rios = rios.to_crs(p.CRS_UTM).clip(zona)
salida = gpd.GeoSeries(gpd.points_from_xy([p.SALIDA_CUENCA[0]], [p.SALIDA_CUENCA[1]]),
                       crs=4326).to_crs(p.CRS_UTM)


def base(ax, titulo=None):
    limite.boundary.plot(ax=ax, color=TINTA, lw=1.1)
    ax.set_axis_off()
    x0, y0, x1, y1 = limite.total_bounds
    # barra de escala 2 km y norte
    bx, by = x0 + 300, y0 + 300
    ax.plot([bx, bx + 2000], [by, by], color=TINTA, lw=3, solid_capstyle="butt")
    ax.text(bx + 1000, by + 250, "2 km", ha="center", fontsize=9)
    ax.annotate("N", xy=(bx + 300, by + 1800), xytext=(bx + 300, by + 700), ha="center",
                fontsize=11, fontweight="bold",
                arrowprops=dict(arrowstyle="-|>", color=TINTA, lw=1.5))
    if titulo:
        ax.set_title(titulo, loc="left", fontsize=12, fontweight="bold")


def guardar(fig, nombre):
    fig.savefig(FIG / nombre, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("figura:", FIG / nombre)


# ----------------------------------------------------------------------------- F1 ubicacion
fig, ax = plt.subplots(figsize=(7, 9))
cauces.plot(ax=ax, color=AZUL_CLARO, lw=0.6)
cuenca.plot(ax=ax, color=AZUL, alpha=0.08)
cuenca.boundary.plot(ax=ax, color=AZUL, lw=1.4, ls="--")
for nombre, g in rios.groupby("name"):
    g.plot(ax=ax, color=AZUL, lw=2.2 if "Cumbe" in nombre else 1.4)
    geo = g.geometry.union_all()
    pt = geo.interpolate(0.5, normalized=True) if geo.geom_type == "LineString" \
        else max(geo.geoms, key=lambda l: l.length).interpolate(0.5, normalized=True)
    ax.text(pt.x + 250, pt.y, nombre, color=AZUL, fontsize=9, fontstyle="italic")
salida.plot(ax=ax, color=TINTA, marker="*", markersize=180, zorder=5)
ax.text(salida.x.iloc[0] + 300, salida.y.iloc[0] + 150, "salida de la cuenca", fontsize=9)
base(ax, "Parroquia Cumbe y cuenca del río Cumbe")
ax.legend(handles=[Line2D([], [], color=TINTA, lw=1.1, label="límite parroquial (OSM)"),
                   Line2D([], [], color=AZUL, lw=1.4, ls="--", label="cuenca del río Cumbe (43 km²)"),
                   Line2D([], [], color=AZUL, lw=2.2, label="ríos con nombre (OSM)"),
                   Line2D([], [], color=AZUL_CLARO, lw=1, label="cauces calculados del DEM")],
          loc="lower right", frameon=False, fontsize=8.5)
guardar(fig, "f1_ubicacion.png")

# ----------------------------------------------------------------------------- F2 relieve
with rasterio.open(p.OUT / "dem_utm.tif") as src:
    z = src.read(1).astype(float)
    z[z == src.nodata] = np.nan
    ext = [src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top]
gy, gx = np.gradient(z, 30)
pend = np.hypot(gx, gy)
asp = np.arctan2(-gx, gy)
hs = np.cos(np.radians(45)) * np.cos(np.arctan(pend)) + \
    np.sin(np.radians(45)) * np.sin(np.arctan(pend)) * np.cos(np.radians(315) - asp)
cmap = LinearSegmentedColormap.from_list("elev", ["#f4efe6", "#c9a77c", "#6b4a2b"])
fig, ax = plt.subplots(figsize=(7, 9))
ax.imshow(hs, extent=ext, cmap="gray", vmin=0, vmax=1)
im = ax.imshow(z, extent=ext, cmap=cmap, alpha=0.6)
cuenca.boundary.plot(ax=ax, color=AZUL, lw=1.4, ls="--")
b = limite.total_bounds
ax.set_xlim(b[0] - 1500, b[2] + 1500); ax.set_ylim(b[1] - 1500, b[3] + 1500)
base(ax, "Relieve (modelo de elevación Copernicus, 30 m)")
cb = fig.colorbar(im, ax=ax, shrink=0.5, pad=0.02)
cb.set_label("elevación (m s.n.m.)"); cb.outline.set_visible(False)
guardar(fig, "f2_relieve.png")

# ----------------------------------------------------------------------------- F3 vias
clases = [("no", GRIS_CLARO, 0.9, "pavimentada / no lastre"),
          ("sin_dato", GRIS, 0.9, "camino rural sin dato de superficie"),
          ("si_osm", NARANJA, 1.1, "lastre según OSM")]
fig, ax = plt.subplots(figsize=(7, 9))
cauces.plot(ax=ax, color=AZUL_CLARO, lw=0.5)
cuenca.boundary.plot(ax=ax, color=AZUL, lw=1.2, ls="--")
for k, c, lw, _ in clases:
    par[par["posible_lastre"] == k].plot(ax=ax, color=c, lw=lw)
par[par["candidato_critico"]].plot(ax=ax, color=ROJO, lw=2.6)
base(ax, "Vías por tipo de superficie y tramos candidatos críticos")
ax.legend(handles=[Line2D([], [], color=c, lw=2, label=l) for _, c, _, l in clases]
          + [Line2D([], [], color=ROJO, lw=3, label="candidato crítico"),
             Line2D([], [], color=AZUL, lw=1.2, ls="--", label="cuenca del río Cumbe")],
          loc="lower right", frameon=False, fontsize=8.5)
guardar(fig, "f3_vias_criticos.png")

# ----------------------------------------------------------------------------- F4 km por categoria
km = par.groupby("posible_lastre")["largo_m"].sum() / 1000
orden = [("si_osm", "Lastre según OSM"), ("sin_dato", "Sin dato de superficie"),
         ("no", "Pavimentada / no lastre")]
fig, ax = plt.subplots(figsize=(7, 2.6))
vals = [km.get(k, 0) for k, _ in orden]
ax.barh([l for _, l in orden][::-1], vals[::-1], color=[GRIS_CLARO, GRIS, NARANJA],
        height=0.6)
for i, v in enumerate(vals[::-1]):
    ax.text(v + 1, i, f"{v:.0f} km", va="center", color=TINTA)
ax.set_xlim(0, max(vals) * 1.18)
ax.spines[["top", "right", "left"]].set_visible(False)
ax.tick_params(axis="y", length=0, labelcolor=TINTA)
ax.set_xlabel("kilómetros de vía dentro de la parroquia")
ax.set_title(f"Red vial de la parroquia: {sum(vals):.0f} km", loc="left", fontweight="bold")
guardar(fig, "f4_km_por_categoria.png")

# ----------------------------------------------------------------------------- F5 pendiente
fig, ax = plt.subplots(figsize=(7, 3.2))
ax.hist(par["pendiente_pct"].clip(upper=40), bins=np.arange(0, 42, 2), color=AZUL,
        edgecolor="white", linewidth=1.5)
ax.axvline(8, color=TINTA, lw=1.2, ls="--")
ax.text(8.6, ax.get_ylim()[1] * 0.9, "umbral 8 %", fontsize=9)
ax.spines[["top", "right"]].set_visible(False)
ax.grid(axis="y", color=GRID, lw=0.6); ax.set_axisbelow(True)
ax.set_xlabel("pendiente del tramo (%)  -  valores sobre 40 % agrupados en 40")
ax.set_ylabel("número de tramos")
ax.set_title("¿Qué tan empinadas son las vías?", loc="left", fontweight="bold")
guardar(fig, "f5_pendientes.png")

# ----------------------------------------------------------------------------- priorizacion
crit = par[par["candidato_critico"]].copy()
crit["_lastre"] = (crit["posible_lastre"] == "si_osm").astype(int)
crit = crit.sort_values(["cruce_cauce", "_lastre", "pendiente_pct"], ascending=False)
crit["prioridad"] = np.arange(1, len(crit) + 1)
mid = crit.geometry.interpolate(0.5, normalized=True).to_crs(4326)
crit["lat"], crit["lon"] = mid.y.round(5), mid.x.round(5)
cols = ["prioridad", "id_tramo", "name", "highway", "posible_lastre", "pendiente_pct",
        "dist_cauce_m", "cruce_cauce", "cobertura", "en_cuenca", "lat", "lon"]
crit[cols].to_csv(INF / "criticos_priorizados.csv", index=False)
print("tabla:", INF / "criticos_priorizados.csv")

# ----------------------------------------------------------------------------- F6 top 15
top = crit.head(15)
fig, ax = plt.subplots(figsize=(7, 9))
cauces.plot(ax=ax, color=AZUL_CLARO, lw=0.5)
par.plot(ax=ax, color=GRIS_CLARO, lw=0.7)
crit.plot(ax=ax, color=ROJO, lw=1.6, alpha=0.45)
top.plot(ax=ax, color=ROJO, lw=3)
pts = top.geometry.interpolate(0.5, normalized=True)
ax.scatter(pts.x, pts.y, s=22, color=ROJO, edgecolor="white", linewidth=1, zorder=4)
# etiquetas sin solaparse: probar 8 direcciones y alejarse hasta encontrar hueco
colocadas = []
for (_, r), c in zip(top.iterrows(), pts):
    for dist in (550, 900, 1250, 1600):
        for ang in np.radians([45, 135, 315, 225, 90, 0, 180, 270]):
            lx, ly = c.x + dist * np.cos(ang), c.y + dist * np.sin(ang)
            if all(np.hypot(lx - qx, ly - qy) > 500 for qx, qy in colocadas):
                break
        else:
            continue
        break
    colocadas.append((lx, ly))
    ax.annotate(str(r["prioridad"]), (c.x, c.y), xytext=(lx, ly), ha="center", va="center",
                fontsize=8.5, fontweight="bold", zorder=6,
                bbox=dict(boxstyle="circle,pad=0.25", fc="white", ec=ROJO, lw=1),
                arrowprops=dict(arrowstyle="-", color=ROJO, lw=0.8))
base(ax, "Los 15 tramos a revisar primero")
ax.legend(handles=[Line2D([], [], color=ROJO, lw=3, label="15 primeros (número = prioridad)"),
                   Line2D([], [], color=ROJO, lw=1.6, alpha=0.45, label="resto de candidatos críticos"),
                   Line2D([], [], color=GRIS_CLARO, lw=1.5, label="otras vías")],
          loc="lower right", frameon=False, fontsize=8.5)
guardar(fig, "f6_top15.png")

# resumen para el texto
print("\nRESUMEN")
print("tramos parroquia:", len(par), "| km:", round(par["largo_m"].sum() / 1000, 1))
print("criticos:", len(crit), "| km:", round(crit["largo_m"].sum() / 1000, 1),
      "| si_osm:", int((crit["posible_lastre"] == "si_osm").sum()),
      "| sin_dato:", int((crit["posible_lastre"] == "sin_dato").sum()),
      "| con cruce:", int(crit["cruce_cauce"].sum()))
print("pendiente mediana parroquia:", par["pendiente_pct"].median(),
      "| % tramos > 8%:", round(100 * (par["pendiente_pct"] > 8).mean(), 1))
print("cobertura:", par["cobertura"].value_counts(normalize=True).round(3).to_dict())
print("lluvia:", par["lluvia_anual_mm"].min(), par["lluvia_anual_mm"].max())
print("elev:", par["elevacion_m"].min(), par["elevacion_m"].max())
print(top[cols].to_string())
