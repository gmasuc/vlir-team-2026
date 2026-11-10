"""
Paso 1b: mejora de los tramos del paso 1 con los datos recibidos el 14-10-2026.

1. Pendiente con el modelo de elevación de 0.5 m (antes: Copernicus 30 m).
   - pendiente_neta_05m: pendiente del ajuste lineal de la elevación a lo largo del tramo (misma definición que el
     paso 1).
   - pendiente_max20m: la mayor pendiente en cualquier tramo de 20 m (donde el agua corre más fuerte).
   Se muestrea la elevación cada 1 m sobre la línea de la vía, suavizada en 5 m.
2. Superficie desde la ortofoto de 0.3 m. Para cada tramo se toman los píxeles a menos de 2 m del eje de la vía
   (color, brillo, verdor, textura). Un bosque aleatorio aprende de los tramos que OSM ya etiqueta (lastre o
   pavimentada) y estima la probabilidad de lastre de los tramos sin dato. Validación cruzada espacial (bloques de
   1 km) para que no aprenda de tramos vecinos.
3. Candidatos críticos v2: mismo criterio que el paso 1 (lastre o dudoso, pendiente > 8 %, a menos de 100 m de un
   cauce o cruzándolo), con la pendiente y la superficie nuevas.

Uso:  py 01_Cumbe/cumbe_paso1b_mdt_ortofoto.py
Salida: 01_Cumbe/cumbe_paso1b/ (tramos_v2.gpkg, tramos_v2.csv, resumen.txt, mapa_v2.png, validacion_superficie.csv)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from rasterio.features import geometry_mask  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402
from sklearn.ensemble import RandomForestClassifier  # noqa: E402
from sklearn.model_selection import GroupKFold, cross_val_predict  # noqa: E402

BASE = Path(__file__).resolve().parent
OUT = BASE / "cumbe_paso1b"
OUT.mkdir(exist_ok=True)
MDT = BASE / "datos" / "mdt_cumbe_05m.tif"
ORTO = BASE / "datos" / "ortofoto_cumbe_03m.tif"
LASTRE = {"unpaved", "compacted", "gravel", "ground", "fine_gravel", "dirt"}
PAVIM = {"asphalt", "concrete", "paved", "paving_stones"}
SEMILLA = 7

t = gpd.read_file(BASE / "cumbe_paso1" / "cumbe_paso1.gpkg", layer="tramos").to_crs(32717)
log = open(OUT / "resumen.txt", "w", encoding="utf-8")


def p(x=""):
    print(x, flush=True)
    log.write(str(x) + "\n")


# ----------------------------------------------------------------------------- 1. pendientes con el MDT 0.5 m
with rasterio.open(MDT) as s:
    nod = s.nodata
    netas, maximas = [], []
    for g in t.geometry:
        n = max(int(g.length), 2)
        pts = [g.interpolate(d) for d in np.linspace(0, g.length, n + 1)]
        z = np.array([v[0] for v in s.sample([(q.x, q.y) for q in pts])], dtype=float)
        z[z == nod] = np.nan
        if np.isnan(z).mean() > 0.2:
            netas.append(np.nan)
            maximas.append(np.nan)
            continue
        z = pd.Series(z).interpolate(limit_direction="both").rolling(5, center=True, min_periods=1).mean().values
        paso = g.length / n
        dist = np.linspace(0, g.length, n + 1)
        netas.append(100 * abs(np.polyfit(dist, z, 1)[0]))      # ajuste lineal, como en el paso 1
        k = max(int(round(20 / paso)), 1)
        maximas.append(100 * np.nanmax(np.abs(z[k:] - z[:-k])) / (k * paso) if len(z) > k else netas[-1])
t["pendiente_neta_05m"] = np.round(netas, 1)
t["pendiente_max20m"] = np.round(maximas, 1)
d = (t.pendiente_neta_05m - t.pendiente_pct).dropna()
p("1. PENDIENTES (MDT 0.5 m vs Copernicus 30 m)")
p(f"   mediana: {t.pendiente_pct.median():.1f} % -> {t.pendiente_neta_05m.median():.1f} %")
p(f"   tramos con más de 30 % (sospechosos con 30 m): {(t.pendiente_pct > 30).sum()} -> {(t.pendiente_neta_05m > 30).sum()}")
p(f"   diferencia típica por tramo (mediana del valor absoluto): {d.abs().median():.1f} puntos")
p(f"   tramos que cruzan el umbral de 8 % en algún sentido: "
  f"{((t.pendiente_pct > 8) != (t.pendiente_neta_05m > 8)).sum()}")

# ----------------------------------------------------------------------------- 2. rasgos de la ortofoto por tramo
filas = []
with rasterio.open(ORTO) as s:
    for g in t.geometry:
        buf = g.buffer(2.0, cap_style="flat")
        w = from_bounds(*buf.bounds, s.transform).round_offsets().round_lengths()
        img = s.read(window=w).astype(float)
        if img.size == 0:
            filas.append({})
            continue
        m = ~geometry_mask([buf], out_shape=img.shape[1:], transform=s.window_transform(w))
        r, gg, b = (img[i][m] for i in range(3))
        if r.size < 20:
            filas.append({})
            continue
        gris = (r + gg + b) / 3
        mx, mn = np.maximum(np.maximum(r, gg), b), np.minimum(np.minimum(r, gg), b)
        sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
        exg = 2 * gg - r - b
        filas.append({"R": r.mean(), "G": gg.mean(), "B": b.mean(), "brillo": gris.mean(), "brillo_sd": gris.std(),
                      "saturacion": sat.mean(), "verdor": exg.mean(), "frac_verde": (exg > 20).mean(),
                      "rojo_azul": (r - b).mean(), "brillo_p90": np.percentile(gris, 90)})
F = pd.DataFrame(filas, index=t.index)
RASGOS = list(F.columns)

# ----------------------------------------------------------------------------- 3. clasificador de superficie
sup = t.surface.fillna("")
y = pd.Series(np.where(sup.isin(LASTRE), 1, np.where(sup.isin(PAVIM), 0, -1)), index=t.index)
ok = F.notna().all(axis=1)
ent = ok & (y >= 0)
mid = t.geometry.interpolate(0.5, normalized=True)
bloque = (mid.x // 1000).astype(int).astype(str) + "_" + (mid.y // 1000).astype(int).astype(str)
rf = RandomForestClassifier(n_estimators=400, min_samples_leaf=3, class_weight="balanced", random_state=SEMILLA,
                            n_jobs=-1)
prob_cv = cross_val_predict(rf, F[ent], y[ent], groups=bloque[ent], cv=GroupKFold(n_splits=5),
                            method="predict_proba")[:, 1]
pred_cv = prob_cv >= 0.5
yt = y[ent].values
acierto = (pred_cv == yt).mean()
rec_l = (pred_cv[yt == 1]).mean()
rec_p = (~pred_cv[yt == 0]).mean()
p("\n2. SUPERFICIE DESDE LA ORTOFOTO (validación cruzada espacial, bloques de 1 km)")
p(f"   tramos de entrenamiento: {ent.sum()} ({(yt == 1).sum()} lastre, {(yt == 0).sum()} pavimentados)")
p(f"   acierto global: {acierto:.0%} | lastre bien reconocido: {rec_l:.0%} | pavimento bien reconocido: {rec_p:.0%}")
pd.DataFrame({"id_tramo": t.loc[ent, "id_tramo"], "real_lastre": yt, "prob_lastre_cv": prob_cv.round(3)}).to_csv(
    OUT / "validacion_superficie.csv", index=False)
rf.fit(F[ent], y[ent])
imp = pd.Series(rf.feature_importances_, index=RASGOS).sort_values(ascending=False)
p("   rasgos más útiles: " + ", ".join(f"{k} ({v:.2f})" for k, v in imp.head(4).items()))

t["prob_lastre"] = np.nan
t.loc[ok, "prob_lastre"] = rf.predict_proba(F[ok])[:, 1].round(3)
sd = t.posible_lastre == "sin_dato"
t["superficie_v2"] = t.posible_lastre.map({"si_osm": "lastre (OSM)", "no": "pavimentada u otra (OSM)"})
t.loc[sd & (t.prob_lastre >= 0.65), "superficie_v2"] = "lastre (foto)"
t.loc[sd & (t.prob_lastre < 0.35), "superficie_v2"] = "pavimentada (foto)"
t.loc[sd & t.superficie_v2.isna(), "superficie_v2"] = "dudosa (foto)"
km = t[t.en_parroquia].groupby("superficie_v2").largo_m.sum().div(1000).round(1)
p("   km en la parroquia por superficie:\n" + "\n".join(f"     {k}: {v} km" for k, v in km.items()))

# ----------------------------------------------------------------------------- 4. candidatos críticos v2
cerca = (t.dist_cauce_m < 100) | t.cruce_cauce
lastre_o_dudosa = t.superficie_v2.isin(["lastre (OSM)", "lastre (foto)", "dudosa (foto)"])
t["candidato_v2"] = lastre_o_dudosa & (t.pendiente_neta_05m > 8) & cerca & t.en_parroquia
viejo, nuevo = t.candidato_critico & t.en_parroquia, t.candidato_v2
p("\n3. CANDIDATOS CRÍTICOS")
p(f"   paso 1: {viejo.sum()} tramos ({t[viejo].largo_m.sum() / 1000:.1f} km) -> v2: {nuevo.sum()} tramos "
  f"({t[nuevo].largo_m.sum() / 1000:.1f} km)")
p(f"   se mantienen: {(viejo & nuevo).sum()} | salen: {(viejo & ~nuevo).sum()} | entran: {(~viejo & nuevo).sum()}")
salen = t[viejo & ~nuevo]
p(f"   por qué salen: pendiente bajo 8 % con el MDT: {(salen.pendiente_neta_05m <= 8).sum()} | "
  f"la foto dice pavimentada: {(salen.superficie_v2 == 'pavimentada (foto)').sum()}")

cols = ["id_tramo", "name", "highway", "surface", "largo_m", "pendiente_pct", "pendiente_neta_05m",
        "pendiente_max20m", "dist_cauce_m", "cruce_cauce", "posible_lastre", "prob_lastre", "superficie_v2",
        "en_parroquia", "en_cuenca", "candidato_critico", "candidato_v2"]
t[cols + ["geometry"]].to_file(OUT / "tramos_v2.gpkg", layer="tramos_v2", driver="GPKG")
t[cols].to_csv(OUT / "tramos_v2.csv", index=False, encoding="utf-8-sig")

fig, ax = plt.subplots(figsize=(8, 11))
estilo = {"pavimentada u otra (OSM)": ("#C8C8C8", 0.8), "pavimentada (foto)": ("#9E9E9E", 0.8),
          "lastre (OSM)": ("#E07B39", 1.2), "lastre (foto)": ("#B8860B", 1.2), "dudosa (foto)": ("#7B68AE", 1.2)}
tp = t[t.en_parroquia]
for k, (c, lw) in estilo.items():
    sub = tp[tp.superficie_v2 == k]
    if len(sub):
        sub.plot(ax=ax, color=c, lw=lw, label=f"{k} ({sub.largo_m.sum() / 1000:.0f} km)")
tp[tp.candidato_v2].plot(ax=ax, color="#C0392B", lw=3, label=f"candidato crítico v2 ({tp.candidato_v2.sum()})")
ax.legend(loc="lower left", fontsize=9, frameon=False)
ax.set_axis_off()
ax.set_title("Superficie estimada y candidatos críticos v2 (MDT 0.5 m + ortofoto 0.3 m)")
fig.tight_layout()
fig.savefig(OUT / "mapa_v2.png", dpi=170)
p("\nSalidas en " + str(OUT))
