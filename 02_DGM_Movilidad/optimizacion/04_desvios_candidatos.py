"""
Desvíos pequeños candidatos para cada línea de bus (paso 1 de la optimización de recorridos).

Un desvío reemplaza un tramo del recorrido actual por otro camino por las calles donde puede circular el bus (red del
modelo calibrado de SUMO), y debe cumplir:
  - alarga el recorrido como máximo DESVIO_MAX_M (1 km) y DESVIO_MAX_FR (10 %) del recorrido en la red;
  - ninguna parada que el bus deja de atender queda a más de COBERTURA_M (400 m) de otra parada servida (de esta
    línea, de otra línea o del tranvía);
  - tiene un propósito:
      a) «tranvía»: pasar a menos de 60 m de una parada del tranvía que hoy queda a 150-700 m del recorrido, para
         permitir el transbordo;
      b) «paralelo»: dejar de circular en paralelo al tranvía (tramos de 400 m o más a menos de 40 m de su vía)
         usando calles vecinas;
      c) «cobertura»: acercarse a una celda de 500 m con demanda cuya parada más cercana está a más de 500 m.
Por cada línea y sentido, y por cada propósito, se guarda el desvío más corto que cumple; como máximo 4 por recorrido.

Entrada: red y recorridos del modelo calibrado (simulacion_sumo/buses/calibrada_..._jc/buses.rou.xml, paradas.add.xml),
         paradas de todas las líneas y del tranvía (datos/derivados/paradas_por_linea.csv), capa de paradas de la DGM
         (paradas nuevas sobre el desvío), celdas y demanda del grafo de pasajeros (02_grafo_pasajeros.py).
Salida:  optimizacion/desvios/candidatos.csv, candidatos.gpkg (tramo actual y desvío) y mapa_desvios.html.

Uso:  py optimizacion/04_desvios_candidatos.py
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import heapq
import importlib
import json
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import sumo
from shapely.geometry import LineString, Point

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
gp = importlib.import_module("02_grafo_pasajeros")
BASE = AQUI.parent
SIM = BASE / "simulacion_sumo"
RUN = gp.RUN
NET = SIM / "red" / "cuenca_piloto_v2s_vel.net.xml"
OUT = AQUI / "desvios"
OUT.mkdir(exist_ok=True)

DESVIO_MAX_M = 1000
DESVIO_MAX_FR = 0.10
COBERTURA_M = 400
TRANVIA_LEJOS = (150, 700)      # parada del tranvía a esta distancia del recorrido: candidata a «tranvía»
TRANVIA_LLEGAR = 60             # el desvío debe pasar a menos de 60 m de la parada del tranvía
PARALELO_M, PARALELO_LARGO = 40, 400
CELDA_LEJOS, CELDA_RADIO = 500, 1200
VENTANA = 15                    # aristas antes y después del punto más cercano para empalmar el desvío
MAX_POR_RUTA = 4

net = sumolib.net.readNet(str(NET))
a_utm = pyproj.Transformer.from_crs(4326, 32717, always_xy=True)
a_geo = pyproj.Transformer.from_crs(32717, 4326, always_xy=True)


def xy_de_utm(x, y):
    lon, lat = a_geo.transform(x, y)
    return net.convertLonLat2XY(lon, lat)


def utm_de_xy(x, y):
    return a_utm.transform(*net.convertXY2LonLat(x, y))


# ----------------------------------------------------------------------------- red de aristas para el bus
bus_ok = {e.getID(): e for e in net.getEdges() if e.allows("bus") and e.getFunction() != "internal"}
sale = {k: [f.getID() for f in e.getOutgoing() if f.getID() in bus_ok] for k, e in bus_ok.items()}
largo = {k: e.getLength() for k, e in bus_ok.items()}
forma = {k: LineString(e.getShape()) for k, e in bus_ok.items()}
medio = {k: g.interpolate(0.5, normalized=True) for k, g in forma.items()}


def camino(a, b, costo=None):
    """camino más corto de la arista a a la arista b (sin contar a); costo = factor por arista (por defecto 1)."""
    dist, prev, h = {a: 0.0}, {}, [(0.0, a)]
    while h:
        d, x = heapq.heappop(h)
        if x == b:
            break
        if d > dist.get(x, np.inf) or d > 6000:
            continue
        for y in sale[x]:
            nd = d + largo[y] * (costo.get(y, 1.0) if costo else 1.0)
            if nd < dist.get(y, np.inf):
                dist[y], prev[y] = nd, x
                heapq.heappush(h, (nd, y))
    if b not in prev and a != b:
        return None
    p = [b]
    while p[-1] != a:
        p.append(prev[p[-1]])
    return p[::-1]


# ----------------------------------------------------------------------------- recorridos, paradas y celdas
rutas, paradas_ruta = {}, {}
for r in sumolib.xml.parse(str(RUN / "buses.rou.xml"), "route"):
    if r.id.startswith("LRUTA"):
        continue
    rutas[r.id] = r.edges.split()
    paradas_ruta[r.id] = [s.busStop for s in (r.stop or [])]
pos_parada = {}
for s in sumolib.xml.parse(str(RUN / "paradas.add.xml"), "busStop"):
    e = s.lane.rsplit("_", 1)[0]
    if e in bus_ok:
        p = sumolib.geomhelper.positionAtShapeOffset(bus_ok[e].getShape(), (float(s.startPos) + float(s.endPos)) / 2)
        pos_parada[s.id] = (e, p, s.name)

lin, par = gp.cargar_oferta()
servidas = np.array([xy_de_utm(x, y) for x, y in par.drop_duplicates("parada")[["x", "y"]].values])
tranvia = par[par.parada.str.startswith("T")].drop_duplicates("parada")
tranvia_xy = {r.parada: (xy_de_utm(r.x, r.y), r.nombre) for r in tranvia.itertuples()}
via = LineString([xy_de_utm(x, y) for x, y in
                  par[par.id_ld == "RUTA TRANVIA|Ida"].sort_values("k")[["x", "y"]].values])
capa = gpd.read_file(BASE / "datos" / "GIS_Transporte" / "paradas.shp").to_crs(32717)
capa_xy = np.array([xy_de_utm(p.x, p.y) for p in capa.geometry.centroid])
kmh = lin.set_index("id_ld").kmh
EN_EJE = {e for e in bus_ok if via.distance(medio[e]) < PARALELO_M}
costo = {e: 50.0 for e in EN_EJE}                   # para evitar el eje del tranvía al buscar el desvío

# celdas con demanda y lejos de toda parada
zon, cel = gp.armar_celdas()
odc = gp.demanda_celdas(gp.cargar_demanda(), cel)
gen = odc.sum(axis=1) + odc.sum(axis=0)
cel_xy = {c: xy_de_utm(g.representative_point().x, g.representative_point().y) for c, g in cel.geometry.items()}
lejanas = []
for c, (x, y) in cel_xy.items():
    d = np.hypot(servidas[:, 0] - x, servidas[:, 1] - y).min()
    if d > CELDA_LEJOS and gen[c] >= 20:
        lejanas.append((c, (x, y), d, gen[c]))
print(f"celdas con demanda a más de {CELDA_LEJOS} m de una parada: {len(lejanas)}")


def aristas_cerca(pt, radio):
    x, y = pt
    return [e.getID() for e, d in net.getNeighboringEdges(x, y, radio) if e.getID() in bus_ok]


def evaluar_desvio(rid, nueva, i, j):
    """comprueba un recorrido nuevo; devuelve un dict con sus datos o None si no cumple."""
    vieja = rutas[rid]
    L0 = sum(largo[e] for e in vieja)
    L1 = sum(largo[e] for e in nueva)
    extra = L1 - L0
    if extra > min(DESVIO_MAX_M, DESVIO_MAX_FR * L0) or len(set(nueva)) < len(nueva) - 2:
        return None
    quitado = set(vieja[i + 1:j]) - set(nueva)
    agregado = [e for e in nueva if e not in set(vieja)]
    # sin ramales de ida y vuelta por la misma calle (el bus tendría que dar la vuelta en U)
    usadas = set(nueva)
    if any((e[1:] if e.startswith("-") else "-" + e) in usadas for e in agregado):
        return None
    sin = [s for s in paradas_ruta[rid] if pos_parada.get(s, (None,))[0] in quitado]
    geom_nueva = LineString([p for e in agregado for p in bus_ok[e].getShape()]) if len(agregado) else None
    nuevas = []
    if geom_nueva is not None and geom_nueva.length > 0:
        d = np.array([geom_nueva.distance(Point(p)) for p in capa_xy])
        nuevas = list(np.where(d < 25)[0])
    # cada parada que se deja de atender: otra parada servida a menos de 400 m (otras líneas, tranvía o el desvío)
    pts_desvio = capa_xy[nuevas] if nuevas else np.empty((0, 2))
    for s in sin:
        x, y = pos_parada[s][1]
        cerca = np.hypot(servidas[:, 0] - x, servidas[:, 1] - y)
        cerca = cerca[cerca > 5]                 # la misma parada no cuenta
        alt = min(cerca.min() if len(cerca) else np.inf,
                  np.hypot(pts_desvio[:, 0] - x, pts_desvio[:, 1] - y).min() if len(pts_desvio) else np.inf)
        if alt > COBERTURA_M:
            return None
    k = rid[1:].replace("_", "|", 1)
    return {"extra_m": round(extra), "extra_%": round(100 * extra / L0, 1),
            "extra_min": round(extra / 1000 / kmh.get(k, 20) * 60, 1), "paradas_sin_atender": len(sin),
            "paradas_nuevas_capa": len(nuevas), "acorta": extra < 0,
            "aristas_quitadas": [e for e in vieja[i + 1:j] if e in quitado], "aristas_nuevas": agregado,
            "nueva": nueva, "i": i, "j": j}


entra = {}
for x, ys in sale.items():
    for y in ys:
        entra.setdefault(y, []).append(x)


def arbol(origen, vecinos, hacia_atras=False, tope=4000):
    """Dijkstra desde una arista (hacia adelante: costo = largo de cada arista nueva; hacia atrás: hasta el origen,
    contando el largo del origen y de las intermedias). Devuelve distancias y predecesores."""
    dist, prev, h = {origen: 0.0}, {}, [(0.0, origen)]
    while h:
        d, x = heapq.heappop(h)
        if d > dist.get(x, np.inf) or d > tope:
            continue
        for y in vecinos.get(x, []):
            nd = d + (largo[x] if hacia_atras else largo[y])
            if nd < dist.get(y, np.inf):
                dist[y], prev[y] = nd, x
                heapq.heappush(h, (nd, y))
    return dist, prev


def empalmar(rid, k, destino):
    """desvío que sale del recorrido en el índice i ≤ k, pasa por la arista destino y vuelve en j ≥ k.
    Dos búsquedas por destino (hacia atrás y hacia adelante) dan el costo de todos los empalmes; se revisan los más
    cortos hasta encontrar uno que cumpla las condiciones."""
    r = rutas[rid]
    d_a, p_a = arbol(destino, entra, hacia_atras=True)       # de cada arista hasta el destino
    d_d, p_d = arbol(destino, sale)                           # del destino a cada arista
    acum = np.concatenate([[0], np.cumsum([largo[e] for e in r])])
    opciones = []
    for i in range(max(0, k - VENTANA), k + 1):
        if r[i] not in d_a:
            continue
        for j in range(max(k, i + 1), min(len(r), k + VENTANA + 1)):
            if r[j] not in d_d:
                continue
            # largo nuevo entre r[i] y r[j] (sin contar ambos) frente al actual
            nuevo = d_a[r[i]] + d_d[r[j]] - largo[r[j]]        # d_a incluye el destino; d_d incluye r[j]
            actual = acum[j] - acum[i + 1]
            opciones.append((nuevo - actual, i, j))
    for _, i, j in sorted(opciones)[:12]:
        p1, x = [], r[i]                                     # r[i] -> destino
        while x != destino:
            x = p_a[x]
            p1.append(x)
        p2, x = [], r[j]                                     # destino -> r[j]
        while x != destino:
            p2.append(x)
            x = p_d[x]
        nueva = r[:i + 1] + p1 + p2[::-1] + r[j + 1:]
        res = evaluar_desvio(rid, nueva, i, j)
        if res:
            return res
    return None


filas = []
for rid, r in rutas.items():
    geo = LineString([p for e in r for p in bus_ok[e].getShape()]) if all(e in bus_ok for e in r) else None
    if geo is None:
        continue
    k_ld = rid[1:].replace("_", "|", 1)
    cand = []
    # a) pasar por una parada del tranvía
    for t, (pt, nom) in tranvia_xy.items():
        d = geo.distance(Point(pt))
        if not TRANVIA_LEJOS[0] < d <= TRANVIA_LEJOS[1]:
            continue
        k = int(np.argmin([medio[e].distance(Point(pt)) for e in r]))
        for dest in aristas_cerca(pt, TRANVIA_LLEGAR)[:3]:
            res = empalmar(rid, k, dest)
            if res:
                cand.append({"tipo": "tranvía", "objetivo": f"parada del tranvía {nom} (hoy a {d:.0f} m)", **res})
                break
    # b) dejar de ir en paralelo al tranvía
    en_eje = [e in EN_EJE for e in r]
    i = 0
    while i < len(r):
        if not en_eje[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(r) and en_eje[j + 1]:
            j += 1
        L = sum(largo[e] for e in r[i:j + 1])
        if L >= PARALELO_LARGO and i > 0 and j + 1 < len(r):
            p = camino(r[i - 1], r[j + 1], costo)
            if p:
                nueva = r[:i] + p + r[j + 2:]
                res = evaluar_desvio(rid, nueva, i - 1, j + 1)
                if res:
                    cand.append({"tipo": "paralelo", "objetivo": f"deja {L:.0f} m en paralelo al tranvía", **res})
        i = j + 1
    # c) acercarse a una celda con demanda y sin parada cerca
    for c, pt, dmin, g in sorted(lejanas, key=lambda x: -x[3]):
        if geo.distance(Point(pt)) > CELDA_RADIO:
            continue
        k = int(np.argmin([medio[e].distance(Point(pt)) for e in r]))
        dest = aristas_cerca(pt, 250)
        if not dest:
            continue
        dest = min(dest, key=lambda e: medio[e].distance(Point(pt)))
        res = empalmar(rid, k, dest)
        if res:
            cand.append({"tipo": "cobertura", "objetivo": f"celda {c} ({g:.0f} viajes/h, parada más cercana a {dmin:.0f} m)",
                         **res})
    # el más corto por propósito, hasta 4 por recorrido
    vistos, n = set(), 0
    for c in sorted(cand, key=lambda x: (x["tipo"], x["extra_m"])):
        clave = (c["tipo"], tuple(c["aristas_nuevas"][:3]))
        if c["tipo"] in {v[0] for v in vistos} or clave in vistos or n >= MAX_POR_RUTA:
            continue
        vistos.add(clave)
        n += 1
        filas.append({"id_ld": k_ld, "ruta": rid, **c})
    print(f"{rid}: {n} candidatos", flush=True)

c = pd.DataFrame(filas)
c.insert(0, "id", [f"D{i + 1:03d}" for i in range(len(c))])


def geom(aristas):
    return LineString([utm_de_xy(*p) for e in aristas for p in bus_ok[e].getShape()]) if aristas else None


g_nuevo = gpd.GeoDataFrame(c[["id", "id_ld", "tipo", "objetivo", "extra_m", "extra_%", "extra_min", "acorta",
                              "paradas_sin_atender", "paradas_nuevas_capa"]],
                           geometry=[geom(a) for a in c.aristas_nuevas], crs=32717)
g_viejo = gpd.GeoDataFrame(c[["id"]], geometry=[geom(a) for a in c.aristas_quitadas], crs=32717)
g_nuevo.to_file(OUT / "candidatos.gpkg", layer="desvio")
g_viejo.dropna().to_file(OUT / "candidatos.gpkg", layer="tramo_actual")
c.drop(columns=["nueva"]).assign(aristas_quitadas=c.aristas_quitadas.map(" ".join),
                                 aristas_nuevas=c.aristas_nuevas.map(" ".join)).to_csv(
    OUT / "candidatos.csv", index=False, encoding="utf-8-sig")
c[["id", "ruta", "i", "j"]].assign(recorrido=c.nueva.map(" ".join)).to_csv(OUT / "recorridos_desvio.csv", index=False)
print(c.groupby("tipo").agg(candidatos=("id", "size"), recorridos=("ruta", "nunique"),
                            extra_m_mediana=("extra_m", "median")).to_string())

# ----------------------------------------------------------------------------- mapa
lineas_geo = {}
for rid, r in rutas.items():
    if all(e in bus_ok for e in r):
        lineas_geo[rid] = [[round(v, 6) for v in net.convertXY2LonLat(*p)[::-1]] for e in r for p in bus_ok[e].getShape()][::3]
cand_js = []
for x, gn, gv in zip(c.itertuples(), g_nuevo.to_crs(4326).geometry, g_viejo.to_crs(4326).geometry):
    cand_js.append({"id": x.id, "ruta": x.ruta, "tipo": x.tipo, "objetivo": x.objetivo, "extra_m": x.extra_m,
                    "extra_min": x.extra_min, "sin": x.paradas_sin_atender,
                    "nuevo": [[round(b, 6), round(a, 6)] for a, b in gn.coords] if gn is not None else [],
                    "viejo": [[round(b, 6), round(a, 6)] for a, b in gv.coords] if gv is not None else []})
tram_js = [[*[round(v, 6) for v in net.convertXY2LonLat(*pt)[::-1]], nom] for pt, nom in tranvia_xy.values()]
html = (AQUI / "desvios_plantilla.html").read_text(encoding="utf-8")
html = (html.replace("__CANDIDATOS__", json.dumps(cand_js, ensure_ascii=False))
        .replace("__LINEAS__", json.dumps(lineas_geo)).replace("__TRANVIA__", json.dumps(tram_js, ensure_ascii=False)))
(OUT / "mapa_desvios.html").write_text(html, encoding="utf-8")
print(f"{len(c)} candidatos -> {OUT}")
