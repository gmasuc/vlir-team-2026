"""
Paso 1 - Mapa preliminar de vias y cuenca de Cumbe (Azuay, Ecuador)
Proyecto: Science-Based Decision Support Tools for Sustainable Cities and the Environment (VLIR-UOS)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca

Que hace (solo con datos publicos, sin esperar a los GAD):
  1. Limite de la parroquia (archivo oficial, OSM o bbox de respaldo)
  2. DEM Copernicus GLO-30 (lectura remota, solo la ventana necesaria) -> UTM 17S
     OJO: GLO-30 es un DSM (incluye arboles y techos), no un DTM
  3. Hidrologia desde el DEM (pysheds): red de cauces (lineas) y cuenca hasta la salida
  4. Vias de OpenStreetMap (parroquia + cuenca, recortadas) -> tramos de 100 m
  5. Atributos por tramo: pendiente neta, elevacion, distancia al cauce, cruce con cauce,
     cobertura (ESA WorldCover), lluvia media anual (CHIRPS), superficie OSM, "posible_lastre"
  6. Salidas: GeoPackage (para QGIS), CSV y mapa PNG para llevar a la reunion con el GAD

Instalacion:
  pip install osmnx geopandas rasterio shapely pysheds matplotlib
"""
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import osmnx as ox
import pandas as pd
import rasterio
from rasterio.features import geometry_mask, shapes
from rasterio.merge import merge
from rasterio.transform import xy
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterio.windows import Window
from shapely.geometry import box, shape
from shapely.ops import substring, unary_union

# pysheds 0.5 usa np.in1d, eliminado en numpy 2.4
if not hasattr(np, "in1d"):
    np.in1d = lambda a, b, **kw: np.isin(np.ravel(a), b, **kw)

# ----------------------------------------------------------------------------- configuracion
OUT = Path("cumbe_paso1")
OUT.mkdir(exist_ok=True)
LUGAR = "Cumbe, Cuenca, Azuay, Ecuador"
LIMITE_OFICIAL = None         # ruta a un .shp/.gpkg con el limite oficial (GAD/INEC); None = OSM
BBOX_RESPALDO = (-79.10, -3.20, -78.92, -3.00)  # lon_min, lat_min, lon_max, lat_max -> VERIFICAR
SALIDA_CUENCA = (-79.02811, -3.06664)  # (lon, lat) sobre el rio Cumbe, 300 m aguas arriba de
                              # su fin en OSM (verificado en imagen satelital). None = celda de mayor
                              # acumulacion en la parroquia (cae en el rio Tarqui, no usar)
BUFFER_M = 5000               # margen alrededor de la parroquia para que la cuenca quepa en el DEM
CRS_UTM = "EPSG:32717"        # WGS84 / UTM 17S
LARGO_TRAMO = 100             # m
PASO_MUESTREO = 10            # m, para la pendiente
UMBRAL_CAUCE = 500            # celdas acumuladas (~0.45 km2 con 30 m); ajustar con el mapa
ANIOS_CHIRPS = range(2015, 2025)
SUP_NO_PAV = {"gravel", "unpaved", "compacted", "fine_gravel", "dirt", "ground",
              "earth", "pebblestone", "mud", "sand"}
TRACKTYPE_NO_PAV = {"grade2", "grade3", "grade4", "grade5"}  # grade1 = solido/pavimentado
VIAS_RURALES = {"track", "unclassified", "service", "residential"}
EXCLUIR = {"footway", "path", "steps", "pedestrian", "cycleway", "bridleway", "corridor"}
WORLDCOVER = {10: "arboles", 20: "arbustos", 30: "pastizal", 40: "cultivo", 50: "urbano",
              60: "suelo_desnudo", 70: "nieve", 80: "agua", 90: "humedal", 95: "manglar",
              100: "musgo_liquen"}


# ----------------------------------------------------------------------------- 1. limite
def obtener_limite():
    if LIMITE_OFICIAL:
        print("Limite parroquial oficial:", LIMITE_OFICIAL)
        g = gpd.read_file(LIMITE_OFICIAL).to_crs("EPSG:4326")
        return gpd.GeoDataFrame(geometry=[unary_union(g.geometry)], crs="EPSG:4326")
    try:
        g = ox.geocode_to_gdf(LUGAR)
        if g.geom_type.iloc[0] in ("Polygon", "MultiPolygon"):
            area = g.to_crs(CRS_UTM).area.iloc[0] / 1e6
            print(f"Limite obtenido de OSM ({area:.1f} km2) -> verificar que sea la parroquia "
                  "y no solo el poblado")
            return g[["geometry"]].to_crs("EPSG:4326")
    except Exception as e:
        print("Geocodificacion fallo, uso bbox de respaldo:", e)
    return gpd.GeoDataFrame(geometry=[box(*BBOX_RESPALDO)], crs="EPSG:4326")


# ----------------------------------------------------------------------------- 2. DEM
def nombres_tiles_copernicus(bounds):
    lon0, lat0, lon1, lat1 = bounds
    nombres = []
    for lat in range(int(np.floor(lat0)), int(np.floor(lat1)) + 1):
        for lon in range(int(np.floor(lon0)), int(np.floor(lon1)) + 1):
            ns = f"N{lat:02d}" if lat >= 0 else f"S{abs(lat):02d}"
            ew = f"E{lon:03d}" if lon >= 0 else f"W{abs(lon):03d}"
            nombres.append(f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM")
    return nombres


def descargar_dem(bounds_4326, destino):
    base = "/vsicurl/https://copernicus-dem-30m.s3.amazonaws.com"
    fuentes = []
    for n in nombres_tiles_copernicus(bounds_4326):
        try:
            fuentes.append(rasterio.open(f"{base}/{n}/{n}.tif"))
            print("Tile DEM:", n)
        except Exception:
            print("Tile no disponible:", n)
    if not fuentes:
        raise RuntimeError("No se pudo leer el DEM. Descargalo manualmente (OpenTopography) "
                           "y guardalo como cumbe_paso1/dem_utm.tif")
    # nodata explicito: sin el, merge rellena con 0 las celdas sin dato (borde del mosaico)
    mosaico, transf = merge(fuentes, bounds=bounds_4326, nodata=-9999)
    crs_src = fuentes[0].crs
    for f in fuentes:
        f.close()
    # reproyectar a UTM con un perfil limpio (no heredar bloques/compresion del COG)
    t, w, h = calculate_default_transform(crs_src, CRS_UTM, mosaico.shape[2], mosaico.shape[1],
                                          *bounds_4326, resolution=30)
    perfil_utm = {"driver": "GTiff", "count": 1, "dtype": "float32", "crs": CRS_UTM,
                  "transform": t, "width": w, "height": h, "nodata": -9999,
                  "compress": "deflate"}
    with rasterio.open(destino, "w", **perfil_utm) as dst:
        reproject(mosaico[0], rasterio.band(dst, 1), src_transform=transf,
                  src_crs=crs_src, src_nodata=-9999, dst_transform=t, dst_crs=CRS_UTM,
                  resampling=Resampling.bilinear, dst_nodata=-9999)
    print("DEM guardado:", destino)


def dem_cubre(ruta_dem, bounds_utm):
    with rasterio.open(ruta_dem) as src:
        b = src.bounds
    x0, y0, x1, y1 = bounds_utm
    return b.left <= x0 and b.bottom <= y0 and b.right >= x1 and b.top >= y1


# ----------------------------------------------------------------------------- 3. hidrologia
def extraer_hidrologia(ruta_dem, limite_utm):
    """Devuelve (cauces como lineas, poligono de la cuenca) en UTM."""
    from pysheds.grid import Grid
    grid = Grid.from_raster(str(ruta_dem))
    dem = grid.read_raster(str(ruta_dem))
    dem = grid.resolve_flats(grid.fill_depressions(grid.fill_pits(dem)))
    fdir = grid.flowdir(dem)
    acc = grid.accumulation(fdir)
    A = np.asarray(acc)

    red = grid.extract_river_network(fdir, acc > UMBRAL_CAUCE)
    cauces = gpd.GeoDataFrame.from_features(red["features"], crs=CRS_UTM)
    print(f"Tramos de cauce: {len(cauces)}")

    # salida de la cuenca
    if SALIDA_CUENCA is None:
        dentro = geometry_mask([limite_utm], out_shape=A.shape, transform=grid.affine,
                               invert=True)
        fila, col = np.unravel_index(np.argmax(np.where(dentro, A, -1)), A.shape)
        print("Salida automatica = celda de mayor acumulacion en la parroquia")
    else:
        p = gpd.GeoSeries(gpd.points_from_xy([SALIDA_CUENCA[0]], [SALIDA_CUENCA[1]]),
                          crs="EPSG:4326").to_crs(CRS_UTM).iloc[0]
        c, f = ~grid.affine * (p.x, p.y)
        cand = np.argwhere(A > UMBRAL_CAUCE)          # ajustar al cauce mas cercano
        fila, col = cand[np.argmin((cand[:, 0] - f) ** 2 + (cand[:, 1] - c) ** 2)]
    x_sal, y_sal = xy(grid.affine, fila, col)          # centro de la celda, para reportar
    catch = grid.catchment(x=int(col), y=int(fila), fdir=fdir, xytype="index")
    C = np.asarray(catch).astype(bool)
    if C[0].any() or C[-1].any() or C[:, 0].any() or C[:, -1].any():
        print("AVISO: la cuenca toca el borde del DEM -> aumentar BUFFER_M")
    cuenca = unary_union([shape(s) for s, v in shapes(C.astype(np.uint8), mask=C,
                                                      transform=grid.affine)])
    print(f"Salida: ({x_sal:.0f}, {y_sal:.0f}) UTM, cuenca de {cuenca.area / 1e6:.1f} km2 "
          "-> verificar en QGIS")
    return cauces, cuenca


# ----------------------------------------------------------------------------- 4. vias
def obtener_vias(area_4326, area_utm):
    feats = ox.features_from_polygon(area_4326, tags={"highway": True})
    vias = feats[feats.geom_type.isin(["LineString", "MultiLineString"])].copy()
    vias = vias[~vias["highway"].isin(EXCLUIR)]
    cols = [c for c in ["highway", "surface", "name", "tracktype"] if c in vias.columns]
    vias = vias[cols + ["geometry"]].reset_index(drop=True).to_crs(CRS_UTM)
    # features_from_polygon devuelve las vias completas que tocan el area: recortar
    vias = gpd.clip(vias, area_utm).explode(index_parts=False)
    return vias[vias.geom_type == "LineString"]


def segmentar(vias):
    filas = []
    for _, r in vias.iterrows():
        linea = r.geometry
        n = max(1, int(np.ceil(linea.length / LARGO_TRAMO)))
        for i in range(n):
            seg = substring(linea, i * LARGO_TRAMO, min((i + 1) * LARGO_TRAMO, linea.length))
            if seg.length > 5:
                filas.append({**r.drop("geometry").to_dict(), "geometry": seg})
    tramos = gpd.GeoDataFrame(filas, crs=CRS_UTM)
    tramos.insert(0, "id_tramo", np.arange(1, len(tramos) + 1))
    tramos["largo_m"] = tramos.length.round(1)
    return tramos


# ----------------------------------------------------------------------------- 5. atributos
def bilineal(z, f, c):
    """Interpolacion bilineal de z en indices fraccionarios (fila, col) de centros de celda."""
    h, w = z.shape
    f0 = np.clip(np.floor(f).astype(int), 0, h - 2)
    c0 = np.clip(np.floor(c).astype(int), 0, w - 2)
    df, dc = f - f0, c - c0
    return (z[f0, c0] * (1 - df) * (1 - dc) + z[f0, c0 + 1] * (1 - df) * dc
            + z[f0 + 1, c0] * df * (1 - dc) + z[f0 + 1, c0 + 1] * df * dc)


def pendiente_y_elevacion(tramos, ruta_dem):
    with rasterio.open(ruta_dem) as src:
        z = src.read(1).astype(float)
        z[z == src.nodata] = np.nan
        inv = ~src.transform
    pend, elev = [], []
    for g in tramos.geometry:
        d = np.arange(0, g.length, PASO_MUESTREO)
        d = np.append(d, g.length)
        pts = [g.interpolate(x) for x in d]
        c, f = inv * (np.array([p.x for p in pts]), np.array([p.y for p in pts]))
        zz = bilineal(z, f - 0.5, c - 0.5)
        ok = ~np.isnan(zz)
        if ok.sum() < 2:
            pend.append(np.nan); elev.append(np.nan); continue
        # pendiente neta (ajuste lineal z~d): menos sensible al ruido del DSM que sumar |dz|
        pend.append(100 * abs(np.polyfit(d[ok], zz[ok], 1)[0]))
        elev.append(zz[ok].mean())
    tramos["pendiente_pct"] = np.round(pend, 2)
    tramos["elevacion_m"] = np.round(elev, 1)
    return tramos


def relacion_cauce(tramos, cauces):
    cerca = gpd.sjoin_nearest(tramos[["geometry"]], cauces[["geometry"]],
                              distance_col="dist_cauce_m", how="left")
    cerca = cerca[~cerca.index.duplicated()]
    tramos["dist_cauce_m"] = cerca["dist_cauce_m"].round(1)
    # cruces via-cauce: puntos probables de entrega de sedimento (cauce del DEM, +/- 30 m)
    cruza = gpd.sjoin(tramos[["geometry"]], cauces[["geometry"]], predicate="intersects").index
    tramos["cruce_cauce"] = tramos.index.isin(cruza)
    return tramos


def muestrear_remoto(url, puntos_4326):
    try:
        with rasterio.open(url) as src:
            return np.array([v[0] for v in src.sample([(p.x, p.y) for p in puntos_4326])])
    except Exception as e:
        print("No se pudo leer", url, "->", e)
        return np.full(len(puntos_4326), np.nan)


def cobertura_worldcover(mid):
    """Clase mayoritaria en 3x3 pixeles (30 m) alrededor de cada punto; tiles de 3x3 grados
    nombrados por la esquina inferior izquierda."""
    res = np.full(len(mid), np.nan)
    lat3 = (np.floor(mid.y.values / 3) * 3).astype(int)
    lon3 = (np.floor(mid.x.values / 3) * 3).astype(int)
    for la, lo in set(zip(lat3, lon3)):
        idx = np.where((lat3 == la) & (lon3 == lo))[0]
        celda = f"{'N' if la >= 0 else 'S'}{abs(la):02d}{'E' if lo >= 0 else 'W'}{abs(lo):03d}"
        url = ("/vsicurl/https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
               f"ESA_WorldCover_10m_2021_v200_{celda}_Map.tif")
        try:
            with rasterio.open(url) as src:
                c, f = ~src.transform * (mid.x.values[idx], mid.y.values[idx])
                f, c = np.floor(f).astype(int), np.floor(c).astype(int)
                f0, c0 = f.min() - 1, c.min() - 1
                a = src.read(1, window=Window(c0, f0, c.max() - c0 + 2, f.max() - f0 + 2),
                             boundless=True, fill_value=0)
        except Exception as e:
            print("No se pudo leer", url, "->", e)
            continue
        for k, fi, ci in zip(idx, f - f0, c - c0):
            v = a[fi - 1:fi + 2, ci - 1:ci + 2].ravel()
            v = v[v > 0]
            if len(v):
                res[k] = np.bincount(v).argmax()
    return res


def cobertura_y_lluvia(tramos):
    mid = tramos.geometry.interpolate(0.5, normalized=True).to_crs("EPSG:4326")
    tramos["cobertura"] = pd.Series(cobertura_worldcover(mid)).map(WORLDCOVER).values

    # CHIRPS tiene celdas de 0.05 grados (~5.5 km): sirve de contexto, casi no diferencia tramos
    anual = []
    for a in ANIOS_CHIRPS:
        url = ("/vsicurl/https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_annual/tifs/"
               f"chirps-v2.0.{a}.tif")
        v = muestrear_remoto(url, list(mid)).astype(float)
        v[v < 0] = np.nan
        anual.append(v)
    tramos["lluvia_anual_mm"] = np.round(np.nanmean(np.vstack(anual), axis=0), 0)
    return tramos


def columna(tramos, nombre):
    if nombre in tramos:
        return tramos[nombre]
    return pd.Series(None, index=tramos.index, dtype=object)


def clasificar(tramos, limite_utm, cuenca):
    sup, tt = columna(tramos, "surface"), columna(tramos, "tracktype")
    sin_dato = sup.isna() & tt.isna() & tramos["highway"].isin(VIAS_RURALES)
    # surface manda sobre tracktype cuando ambos existen
    tramos["posible_lastre"] = np.select(
        [sup.isin(SUP_NO_PAV), sup.notna(), tt.isin(TRACKTYPE_NO_PAV), tt.notna(), sin_dato],
        ["si_osm", "no", "si_osm", "no", "sin_dato"], "no")
    mid = tramos.geometry.interpolate(0.5, normalized=True)
    tramos["en_parroquia"] = mid.within(limite_utm)
    tramos["en_cuenca"] = mid.within(cuenca)
    # Heuristica SOLO para priorizar la conversacion con el GAD (no es un modelo de sedimento)
    tramos["candidato_critico"] = ((tramos["posible_lastre"] != "no")
                                   & (tramos["pendiente_pct"] > 8)
                                   & ((tramos["dist_cauce_m"] < 100) | tramos["cruce_cauce"]))
    return tramos


# ----------------------------------------------------------------------------- 6. salidas
def guardar(limite, cuenca, cauces, tramos):
    gpkg = OUT / "cumbe_paso1.gpkg"
    lim_utm = limite.to_crs(CRS_UTM)
    cuenca_gdf = gpd.GeoDataFrame({"area_km2": [round(cuenca.area / 1e6, 2)]},
                                  geometry=[cuenca], crs=CRS_UTM)
    lim_utm.to_file(gpkg, layer="limite", driver="GPKG")
    cuenca_gdf.to_file(gpkg, layer="cuenca", driver="GPKG")
    cauces.to_file(gpkg, layer="cauces", driver="GPKG")
    tramos.to_file(gpkg, layer="tramos", driver="GPKG")
    tramos.drop(columns="geometry").to_csv(OUT / "tramos_cumbe.csv", index=False)

    fig, ax = plt.subplots(figsize=(10, 10))
    cuenca_gdf.boundary.plot(ax=ax, color="tab:blue", lw=1.2, ls="--", label="cuenca (DEM)")
    lim_utm.boundary.plot(ax=ax, color="black", lw=1, label="parroquia")
    zona = unary_union([cuenca, lim_utm.geometry.iloc[0]]).buffer(500)
    cauces.clip(zona).plot(ax=ax, color="tab:blue", lw=0.6, alpha=0.6)
    colores = {"si_osm": "tab:orange", "sin_dato": "tab:gray", "no": "lightgray"}
    for k, c in colores.items():
        sub = tramos[tramos["posible_lastre"] == k]
        if len(sub):
            sub.plot(ax=ax, color=c, lw=1, label=f"vias: {k}")
    crit = tramos[tramos["candidato_critico"]]
    if len(crit):
        crit.plot(ax=ax, color="red", lw=2.5, label="candidato critico")
    ax.legend(loc="lower left"); ax.set_axis_off()
    ax.set_title("Cumbe - vias y cauces (datos publicos, preliminar)")
    fig.savefig(OUT / "mapa_cumbe_preliminar.png", dpi=200, bbox_inches="tight")

    r = tramos.groupby("posible_lastre")["largo_m"].sum().div(1000).round(2)
    print("\nkm de via por categoria:\n", r.to_string())
    print(f"Tramos con cruce de cauce: {int(tramos['cruce_cauce'].sum())}")
    print(f"Tramos candidatos criticos: {int(tramos['candidato_critico'].sum())}")
    print("Salidas en:", OUT.resolve())


def main():
    limite = obtener_limite()
    limite_utm = limite.to_crs(CRS_UTM).geometry.iloc[0]
    area_dem = limite.to_crs(CRS_UTM).buffer(BUFFER_M)
    bounds_4326 = tuple(area_dem.to_crs("EPSG:4326").total_bounds)

    ruta_dem = OUT / "dem_utm.tif"
    if not ruta_dem.exists() or not dem_cubre(ruta_dem, area_dem.total_bounds):
        descargar_dem(bounds_4326, ruta_dem)

    cauces, cuenca = extraer_hidrologia(ruta_dem, limite_utm)
    area_utm = unary_union([limite_utm, cuenca])
    area_4326 = gpd.GeoSeries([area_utm], crs=CRS_UTM).to_crs("EPSG:4326").iloc[0]
    vias = obtener_vias(area_4326, area_utm)
    tramos = segmentar(vias)
    tramos = pendiente_y_elevacion(tramos, ruta_dem)
    tramos = relacion_cauce(tramos, cauces)
    tramos = cobertura_y_lluvia(tramos)
    tramos = clasificar(tramos, limite_utm, cuenca)
    guardar(limite, cuenca, cauces, tramos)


if __name__ == "__main__":
    main()
