"""
Paso 1c: cauces con el modelo de elevación de alta resolución y candidatos críticos v3.

1. Red de cauces a 5 m: el modelo de elevación de 0.5 m se promedia a 5 m (seis veces más detalle que los 30 m del
   paso 1) y con pysheds se calcula el drenaje con el MISMO umbral del paso 1 (0.45 km² de área drenada), para que
   "quebrada" signifique lo mismo. Las redes de 0.5 m que venían en los datos usan umbrales mucho menores (6 y 1.25 ha)
   y casi duplican los cauces; se usan solo como "drenaje fino" (zanjas y cárcavas, con50k).
2. Distancia de cada tramo a la quebrada más cercana, cruce, y distancia al drenaje fino.
3. Candidatos críticos v3: lastre o dudoso (superficie del paso 1b), pendiente > 8 % (0.5 m, paso 1b), a menos de
   100 m de una quebrada de la red de 5 m o cruzándola.

Probado y descartado: alinear las vías de OSM con la ortofoto desplazándolas hasta 10 m hacia donde la foto muestra
suelo sin vegetación. En una revisión visual, varios tramos se movieron a terrenos arados o techos: el método
confunde suelo desnudo con camino. Se mantiene la geometría de OSM.

Uso:  py 01_Cumbe/cumbe_paso1c_alinear_cauces.py
Entrada: cumbe_paso1b/tramos_v2.gpkg, datos/mdt_cumbe_05m.tif, datos/hidrologia_05m/con50k.tif
Salida: datos/mdt_cumbe_5m.tif, 01_Cumbe/cumbe_paso1c/ (cauces_5m.gpkg, tramos_v3.gpkg, tramos_v3.csv, resumen.txt,
        mapa_v3.png)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

# pysheds 0.5 usa np.in1d, eliminado en numpy 2.4
if not hasattr(np, "in1d"):
    np.in1d = lambda a, b, **kw: np.isin(np.ravel(a), b, **kw)
from pysheds.grid import Grid  # noqa: E402

BASE = Path(__file__).resolve().parent
OUT = BASE / "cumbe_paso1c"
OUT.mkdir(exist_ok=True)
DAT = BASE / "datos"
RES = 5.0                         # m
UMBRAL_KM2 = 0.45                 # el mismo área drenada mínima del paso 1 (500 celdas de 30 m)
log = open(OUT / "resumen.txt", "w", encoding="utf-8")


def p(x=""):
    print(x, flush=True)
    log.write(str(x) + "\n")


t = gpd.read_file(BASE / "cumbe_paso1b" / "tramos_v2.gpkg").to_crs(32717)

# ----------------------------------------------------------------------------- 1. modelo de 5 m y red de cauces
DEM5 = DAT / "mdt_cumbe_5m.tif"
if not DEM5.exists():
    with rasterio.open(DAT / "mdt_cumbe_05m.tif") as s:
        f = int(RES / s.res[0])
        z = s.read(1, out_shape=(s.height // f, s.width // f), resampling=Resampling.average, masked=True)
        perfil = s.profile.copy()
        perfil.update(width=z.shape[1], height=z.shape[0], transform=s.transform * s.transform.scale(f, f),
                      compress="deflate", predictor=3, tiled=True, blockxsize=256, blockysize=256)
        with rasterio.open(DEM5, "w", **perfil) as d:
            d.write(z.filled(s.nodata).astype("float32"), 1)
grid = Grid.from_raster(str(DEM5))
dem = grid.read_raster(str(DEM5))
dem = grid.resolve_flats(grid.fill_depressions(grid.fill_pits(dem)))
fdir = grid.flowdir(dem)
acc = grid.accumulation(fdir)
umbral = UMBRAL_KM2 * 1e6 / RES ** 2
red = grid.extract_river_network(fdir, acc > umbral)
cauces = gpd.GeoDataFrame.from_features(red["features"], crs=32717)
cauces.to_file(OUT / "cauces_5m.gpkg", driver="GPKG")
c1 = gpd.read_file(BASE / "cumbe_paso1" / "cumbe_paso1.gpkg", layer="cauces").to_crs(32717)
area = gpd.GeoSeries([t.unary_union.convex_hull.buffer(500)], crs=32717)
p("1. RED DE CAUCES (umbral 0.45 km², igual que el paso 1)")
p(f"   km de cauce en la zona de las vías: 30 m (paso 1) {c1.clip(area).length.sum() / 1000:.0f} km -> "
  f"5 m {cauces.clip(area).length.sum() / 1000:.0f} km")

# ----------------------------------------------------------------------------- 2. distancias
cerca = gpd.sjoin_nearest(t[["geometry"]], cauces[["geometry"]], distance_col="d", how="left")
t["dist_cauce_5m"] = cerca[~cerca.index.duplicated()]["d"].round(1)
t["cruce_cauce_5m"] = t.index.isin(gpd.sjoin(t[["geometry"]], cauces[["geometry"]], predicate="intersects").index)

xs, ys = [], []
with rasterio.open(DAT / "hidrologia_05m" / "con50k.tif") as s:
    for _, w in s.block_windows(1):
        a = s.read(1, window=w)
        fi, co = np.nonzero(a == 1)
        if len(fi):
            X, Y = rasterio.transform.xy(s.window_transform(w), fi, co)
            xs.append(np.asarray(X)); ys.append(np.asarray(Y))
arbol = cKDTree(np.column_stack([np.concatenate(xs), np.concatenate(ys)]))
t["dist_drenaje_05m"] = [round(arbol.query(np.array([(q.x, q.y) for q in (g.interpolate(x) for x in
                          np.linspace(0, g.length, max(int(g.length / 2), 2) + 1))]))[0].min(), 1)
                         for g in t.geometry]
p("\n2. RELACIÓN CON LOS CAUCES")
p(f"   tramos a menos de 100 m de una quebrada: paso 1 {(t.dist_cauce_m < 100).sum()} -> 5 m "
  f"{(t.dist_cauce_5m < 100).sum()}")
p(f"   tramos que cruzan una quebrada: paso 1 {t.cruce_cauce.sum()} -> 5 m {t.cruce_cauce_5m.sum()}")
p(f"   tramos que tocan el drenaje fino de 0.5 m (zanjas o cárcavas a menos de 2 m): {(t.dist_drenaje_05m < 2).sum()}")

# ----------------------------------------------------------------------------- 3. candidatos v3
lastre = t.superficie_v2.isin(["lastre (OSM)", "lastre (foto)", "dudosa (foto)"])
t["candidato_v3"] = (lastre & (t.pendiente_neta_05m > 8) & ((t.dist_cauce_5m < 100) | t.cruce_cauce_5m)
                     & t.en_parroquia)
v1, v2, v3 = t.candidato_critico & t.en_parroquia, t.candidato_v2, t.candidato_v3
t["en_los_3_pasos"] = v1 & v2 & v3
p("\n3. CANDIDATOS CRÍTICOS")
for nom, v in [("paso 1 (30 m, OSM)", v1), ("paso 1b (pendiente 0.5 m + superficie de la foto)", v2),
               ("paso 1c (+ cauces a 5 m)", v3)]:
    p(f"   {nom}: {v.sum()} tramos, {t[v].largo_m.sum() / 1000:.1f} km")
p(f"   v3 frente al paso 1: se mantienen {(v1 & v3).sum()}, salen {(v1 & ~v3).sum()}, entran {(~v1 & v3).sum()}")
p(f"   en los 3 pasos (los más sólidos): {t.en_los_3_pasos.sum()} tramos, "
  f"{t[t.en_los_3_pasos].largo_m.sum() / 1000:.1f} km")
p(f"   de los v3, cruzan una quebrada: {(v3 & t.cruce_cauce_5m).sum()}; tocan el drenaje fino: "
  f"{(v3 & (t.dist_drenaje_05m < 2)).sum()}")

cols = ["id_tramo", "name", "highway", "surface", "largo_m", "pendiente_pct", "pendiente_neta_05m",
        "pendiente_max20m", "dist_cauce_m", "dist_cauce_5m", "cruce_cauce_5m", "dist_drenaje_05m", "posible_lastre",
        "prob_lastre", "superficie_v2", "en_parroquia", "en_cuenca", "candidato_critico", "candidato_v2",
        "candidato_v3", "en_los_3_pasos"]
t[cols + ["geometry"]].to_file(OUT / "tramos_v3.gpkg", layer="tramos_v3", driver="GPKG")
t[cols].to_csv(OUT / "tramos_v3.csv", index=False, encoding="utf-8-sig")

fig, ax = plt.subplots(figsize=(8, 11))
tp = t[t.en_parroquia]
cauces.clip(area).plot(ax=ax, color="#7FB0E8", lw=0.7, label="quebradas (red de 5 m)")
tp[~tp.superficie_v2.isin(["lastre (OSM)", "lastre (foto)", "dudosa (foto)"])].plot(ax=ax, color="#C8C8C8", lw=0.8,
                                                                                    label="pavimentada")
tp[tp.superficie_v2.isin(["lastre (OSM)", "lastre (foto)", "dudosa (foto)"])].plot(ax=ax, color="#C9A26B", lw=1.0,
                                                                                  label="lastre o dudosa")
tp[tp.candidato_v3 & ~tp.en_los_3_pasos].plot(ax=ax, color="#E8A0A0", lw=3,
                                               label=f"candidato v3 ({(tp.candidato_v3 & ~tp.en_los_3_pasos).sum()})")
tp[tp.en_los_3_pasos].plot(ax=ax, color="#C0392B", lw=3.5, label=f"crítico en los 3 pasos ({tp.en_los_3_pasos.sum()})")
ax.legend(loc="lower left", fontsize=9, frameon=False)
ax.set_axis_off()
ax.set_title("Candidatos críticos v3: pendiente a 0.5 m, superficie de la foto, quebradas a 5 m")
fig.tight_layout()
fig.savefig(OUT / "mapa_v3.png", dpi=170)
p("\nSalidas en " + str(OUT))
