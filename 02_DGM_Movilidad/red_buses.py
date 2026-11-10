"""
Funciones para el analisis de buses por hora en cada calle (usadas por 02_buses_por_hora.ipynb).
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import re
import unicodedata
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
import shapely
import shapely.ops
from shapely import STRtree
from shapely.geometry import LineString, Point
from shapely.ops import substring

CRS = 32717


def minutos(s):
    """'00:07', '01:05' o '00:10:00' -> minutos. '00:00' -> NaN (no opera)."""
    t = s.astype(str).str.strip()
    t = t.where(t.str.count(":") >= 2, t + ":00")
    m = pd.to_timedelta(t, errors="coerce").dt.total_seconds() / 60
    return m.replace(0, np.nan)


def lineas_operativas(lineas):
    """Una fila por linea y sentido (Ida/Retorno) con buses por hora; sin alargues."""
    op = lineas[lineas["sentido"].isin(["Ida", "Retorno"])
                & ~lineas["name"].str.upper().str.startswith("ALARGUE", na=False)].copy()
    for col, dia in [("intervalo_", "lv"), ("interval_1", "sab"), ("interval_2", "dom")]:
        op[f"bh_{dia}"] = 60 / minutos(op[col])          # buses por hora en ese sentido
    op["modo"] = np.where(op["linename"] == "RUTA TRANVIA", "tranvia", "bus")
    op["id_ld"] = op["linename"] + "|" + op["sentido"]
    return op.reset_index(drop=True)


def red_calles(area_utm, cache):
    """Red vial de OSM (no dirigida) recortada al area, con cache en disco."""
    cache = Path(cache)
    if cache.exists():
        return gpd.read_file(cache)
    poly = gpd.GeoSeries([area_utm], crs=CRS).to_crs(4326).iloc[0]
    G = ox.graph_from_polygon(poly, network_type="drive_service", simplify=True)
    Gu = ox.convert.to_undirected(G)
    e = ox.graph_to_gdfs(Gu, nodes=False).reset_index()[["u", "v", "key", "name", "highway", "oneway", "geometry"]]
    for c in ["name", "highway"]:
        e[c] = e[c].apply(lambda x: "; ".join(map(str, x)) if isinstance(x, list) else x)
    e["oneway"] = e["oneway"].astype(bool)
    e = e.to_crs(CRS)
    e.to_file(cache, driver="GPKG")
    return e


def segmentar(edges, largo=50):
    """Corta cada calle en tramos de <= largo metros (para ver por donde va cada linea con detalle)."""
    filas = []
    for r in edges.itertuples():
        g = r.geometry
        n = max(1, int(np.ceil(g.length / largo)))
        cortes = np.linspace(0, g.length, n + 1)
        for i in range(n):
            s = substring(g, cortes[i], cortes[i + 1])
            if s.length > 1:
                filas.append((r.u, r.v, r.key, i, r.name, r.highway, r.oneway, s))
    seg = gpd.GeoDataFrame(filas, columns=["u", "v", "key", "parte", "calle", "tipo_via", "un_sentido", "geometry"], crs=CRS)
    seg["seg_id"] = np.arange(len(seg))
    return seg


def _rumbo_xy(a, b):
    """Rumbo (0-360, 0 = norte) de los puntos a hacia b; a y b son arreglos de puntos shapely."""
    ca, cb = shapely.get_coordinates(a), shapely.get_coordinates(b)
    return np.degrees(np.arctan2(cb[:, 0] - ca[:, 0], cb[:, 1] - ca[:, 1])) % 360


def asignar(op, seg, dist=15, angulo=40, paso=10):
    """
    Asigna cada linea-sentido a los tramos de calle que recorre.
    Se recorre la linea cada `paso` m; cada punto se asigna al tramo MAS CERCANO (a menos de `dist` m)
    que sea paralelo a la linea (diferencia de rumbo < `angulo`) y, si la calle es de un solo
    sentido, que el bus circule a favor. Asi una avenida de dos calzadas no se cuenta dos veces.
    'dir' = AB si la linea va en el sentido en que esta dibujado el tramo, BA si va al reves.
    """
    geoms = seg.geometry.values
    arbol = STRtree(geoms)
    rumbo_seg = _rumbo_xy(shapely.get_point(geoms, 0), shapely.get_point(geoms, -1))
    un_sentido = seg["un_sentido"].values.astype(bool)
    salida, control = [], []
    for r in op.itertuples():
        g = r.geometry
        if g is None or g.is_empty:
            continue
        if g.geom_type == "MultiLineString":
            g = shapely.line_merge(g)
            if g.geom_type == "MultiLineString":
                g = max(g.geoms, key=lambda x: x.length)
        d = np.arange(0, g.length, paso)
        pts = shapely.line_interpolate_point(g, d)
        rumbo_lin = _rumbo_xy(shapely.line_interpolate_point(g, np.clip(d - 5, 0, g.length)),
                              shapely.line_interpolate_point(g, np.clip(d + 5, 0, g.length)))
        ip, js = arbol.query(pts, predicate="dwithin", distance=dist)
        if len(ip) == 0:
            continue
        dist_ij = shapely.distance(pts[ip], geoms[js])
        dif = np.abs((rumbo_lin[ip] - rumbo_seg[js] + 180) % 360 - 180)
        ab = dif < angulo
        ba = (dif > 180 - angulo) & ~un_sentido[js]          # al reves solo si la calle es de doble sentido
        valido = ab | ba
        c = pd.DataFrame({"p": ip, "j": js, "d": dist_ij, "ab": ab})[valido]
        c = c.sort_values("d").drop_duplicates("p")           # un tramo por punto: el mas cercano
        control.append((r.id_ld, len(d), len(c), int((~valido & (dif > 180 - angulo)).sum())))
        for (j, es_ab), n in c.groupby(["j", "ab"]).size().items():
            salida.append((r.id_ld, r.linename, r.sentido, r.modo, j, "AB" if es_ab else "BA", n))
    asig = pd.DataFrame(salida, columns=["id_ld", "linea", "sentido_linea", "modo", "seg_id", "dir", "puntos"])
    asig = asig.sort_values("puntos").drop_duplicates(["id_ld", "seg_id"], keep="last")
    asig.attrs["control"] = pd.DataFrame(control, columns=["id_ld", "puntos", "asignados", "contra_sentido"]).set_index("id_ld")
    return asig


def resumen_tramos(seg, asig, op):
    """Suma buses por hora por tramo y por direccion (AB = como esta dibujado el tramo, BA = al reves)."""
    a = asig.merge(op[["id_ld", "bh_lv", "bh_sab", "bh_dom"]], on="id_ld")
    a = a[a["modo"] == "bus"]
    out = seg.copy()
    for dia in ["lv", "sab", "dom"]:
        p = a.pivot_table(index="seg_id", columns="dir", values=f"bh_{dia}", aggfunc="sum").reindex(columns=["AB", "BA"]).fillna(0)
        out[f"bh_{dia}_AB"] = out["seg_id"].map(p["AB"]).fillna(0)
        out[f"bh_{dia}_BA"] = out["seg_id"].map(p["BA"]).fillna(0)
        out[f"bh_{dia}"] = out[f"bh_{dia}_AB"] + out[f"bh_{dia}_BA"]
        out[f"bh_{dia}_max_sentido"] = out[[f"bh_{dia}_AB", f"bh_{dia}_BA"]].max(axis=1)
    lin = a.groupby("seg_id")["linea"].agg(lambda x: sorted(set(x), key=lambda s: (len(s), s)))
    out["n_lineas"] = out["seg_id"].map(lin.apply(len)).fillna(0).astype(int)
    out["lineas"] = out["seg_id"].map(lin.apply(", ".join)).fillna("")
    tr = asig[asig["modo"] == "tranvia"]["seg_id"].unique()
    out["tranvia"] = out["seg_id"].isin(tr)
    out["largo_m"] = out.length.round(1)
    return out


def cobertura_asignacion(op, asig, seg):
    """Que parte de cada linea quedo asignada a calles (deberia ser cercana al 100 %)."""
    largo = seg.set_index("seg_id").length
    a = asig.assign(m=asig["seg_id"].map(largo)).groupby("id_ld")["m"].sum()
    c = op.set_index("id_ld")[["linename", "sentido"]].copy()
    c["km_linea"] = (op.set_index("id_ld").length / 1000).round(2)
    c["km_asignado"] = (a / 1000).reindex(c.index).fillna(0).round(2)
    c["cobertura"] = (c["km_asignado"] / c["km_linea"]).round(2)
    return c.sort_values("cobertura")


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\b(av|avenida|calle|y|de|del|la|el|los|las)\b|\.", " ", s).split()


def ubicar_interseccion(texto, edges, tolerancia=40):
    """
    Ubica el cruce de 'Calle A y Calle B' en la red de OSM.
    El nombre debe aparecer como frase completa ('remigio crespo' no coincide con 'remigio tamariz crespo').
    Si las calles comparten nodos, devuelve el centro de esos nodos; si no (pasos a desnivel, redondeles),
    el punto donde estan mas cerca, siempre que sea a menos de `tolerancia` m.
    Devuelve None si no la encuentra o si es ambigua (cruces a mas de 150 m entre si).
    """
    partes = re.split(r"\s+[yY]\s+", texto.strip(), maxsplit=1)
    if len(partes) != 2:
        return None
    fa, fb = [" ".join(_norm(p)) for p in partes]
    if not fa or not fb:
        return None
    nombres = edges["name"].fillna("").map(lambda n: " " + " ".join(_norm(n)) + " ")
    ea = edges[nombres.str.contains(f" {fa} ", regex=False)]
    eb = edges[nombres.str.contains(f" {fb} ", regex=False)]
    if ea.empty or eb.empty:
        return None
    comunes = (set(ea["u"]) | set(ea["v"])) & (set(eb["u"]) | set(eb["v"]))
    if comunes:
        pts = []
        for nodo in comunes:
            f = ea[(ea["u"] == nodo) | (ea["v"] == nodo)].iloc[0]
            pts.append(Point(f.geometry.coords[0]) if f["u"] == nodo else Point(f.geometry.coords[-1]))
        grupo = gpd.GeoSeries(pts)
        if grupo.total_bounds[2] - grupo.total_bounds[0] > 150 or grupo.total_bounds[3] - grupo.total_bounds[1] > 150:
            return None
        return grupo.union_all().centroid
    ga, gb = ea.union_all(), eb.union_all()
    if ga.distance(gb) > tolerancia:
        return None
    pa, pb = shapely.ops.nearest_points(ga, gb)
    return Point((pa.x + pb.x) / 2, (pa.y + pb.y) / 2)


def tramos_paralelos(tramos, lineas_ref, dist=30, angulo=30):
    """
    Tramos que corren PARALELOS a otra linea (p. ej. el tranvia): a menos de `dist` m y con una
    diferencia de rumbo menor a `angulo` grados. Excluye las calles que solo la cruzan.
    """
    ref = list(lineas_ref.geometry)
    cerca = tramos[tramos.geometry.centroid.within(shapely.union_all(ref).buffer(dist))]

    def es_paralelo(seg):
        p = seg.interpolate(0.5, normalized=True)
        c0, c1 = seg.coords[0], seg.coords[-1]
        r_seg = np.degrees(np.arctan2(c1[0] - c0[0], c1[1] - c0[1]))
        for lg in ref:
            if lg.distance(p) > dist:
                continue
            d = lg.project(p)
            a, b = lg.interpolate(max(d - 10, 0)), lg.interpolate(min(d + 10, lg.length))
            r_ref = np.degrees(np.arctan2(b.x - a.x, b.y - a.y))
            if abs((r_ref - r_seg + 90) % 180 - 90) < angulo:
                return True
        return False

    return cerca[cerca.geometry.apply(es_paralelo)]
