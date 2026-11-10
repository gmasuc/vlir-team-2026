"""
Grafo de pasajeros del transporte público de Cuenca (situación actual, hora pico 7:00-8:00) y asignación de la demanda.

Para qué: evaluar en segundos cuánto tarda el pasajero con una oferta dada (frecuencias, recorridos), sin correr SUMO.
Es la pieza que usará el optimizador; SUMO queda para dar los tiempos de cada tramo y verificar las mejores alternativas.

Grafo (dirigido, pesos en minutos):
  - parada (945 paradas físicas, compartidas entre líneas: mismo identificador de la capa de paradas);
  - parada de una línea en un sentido (una por parada del recorrido, en orden);
  - viajar: de una parada de la línea a la siguiente = distancia por el recorrido / velocidad;
  - subir: de la parada a la línea = espera (mitad del intervalo) + penalización por cada subida (transbordo);
  - bajar: de la línea a la parada = 0;
  - caminar: entre paradas a menos de 300 m (transbordo a pie) y de la zona a sus paradas (acceso y salida).
Entradas:
  - recorridos y paradas en orden: datos/derivados/lineas_recorrido.csv y paradas_por_linea.csv
    (09_buses.py ... solo_paradas: recorrido municipal 2026 + capa de paradas, línea completa);
  - velocidad e intervalo en hora pico de cada línea: Escenario 0 de la DGM (datos/derivados/escenario0_lineas_lv.csv,
    velocidad de operación observada); sin dato, la capa de líneas;
  - reparto de la velocidad a lo largo de la línea (opcional): tiempos de parada a parada del modelo calibrado de SUMO
    (paradas_salida.xml de la corrida); el centro es más lento que las avenidas, y el promedio de la línea se mantiene;
  - demanda: viajes en bus y tranvía de 7:00 a 8:00 (datosmov 2025: viajes por hora y modo, reparto por zona y matriz
    origen-destino de 65 zonas).
Proceso: camino de menor costo para cada par de zonas (Dijkstra) y carga de cada tramo, subidas por línea, transbordos.
Salida:  optimizacion/grafo_pasajeros/: nodos.csv, aristas.csv, cargas_tramos.csv, lineas.csv, resumen.csv,
         validacion_lineas.csv, mapa_cargas.png

Uso:  py optimizacion/02_grafo_pasajeros.py
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import sys
import time
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
from shapely import wkt
from shapely.geometry import LineString

BASE = Path(__file__).resolve().parents[1]
D = BASE / "datos"
RUN = BASE / "simulacion_sumo" / "buses" / "calibrada_bahia_reruteo_scats_vel_coord_fases_sinvueltas_jc"

HORA = 7
CAMINAR_M_MIN = 75          # 4.5 km/h
RODEO = 1.3                 # la distancia por las calles es ~30 % mayor que en línea recta
TRANSBORDO_M = 300          # se camina entre paradas a menos de 300 m
PEN_SUBIDA = 5.0            # minutos de penalización por cada subida (molestia de transbordar)
# preferencia por el tranvía (adoptada el 04-11-2026): cada minuto a bordo del tranvía pesa 0.6 de uno en bus al elegir
# el camino. Literatura: 0.6 con datos de tarjetas en Países Bajos (Yap, Cats y van Arem; ver README, «Base
# metodológica», [R7]) y 0.67-0.80 en encuestas citadas allí. Se
# elige el valor medido con viajes reales; "tranvia0.8" o "tranvia1" para la sensibilidad
F_TRANVIA = next((float(a[7:]) for a in sys.argv if a.startswith("tranvia")), 0.6)
# irregularidad de los buses (por defecto, la de SUMO): espera = intervalo × (1 + CV²) / 2 (Welding, 1957; Osuna y
# Newell, 1972), donde CV = desviación / promedio de los intervalos entre llegadas a una parada. "regular" = CV 0
REGULAR = "regular" in sys.argv
OUT = Path(__file__).resolve().parent / "grafo_pasajeros" / (
    "" if F_TRANVIA == 0.6 and not REGULAR else f"sensibilidad_tranvia{F_TRANVIA}{'_regular' if REGULAR else ''}")
OUT.mkdir(parents=True, exist_ok=True)
ACCESO_BUFFER = 300         # (conectar_zonas) paradas de la zona: dentro del polígono o a menos de 300 m
CELDA = 500                 # las zonas se dividen en celdas de 500 m
ACCESO_M = 600              # cada celda camina a las paradas a menos de 600 m (~10 min por las calles)
# líneas con otro número en el Escenario 0 (emparejadas por sus terminales)
CAPA_A_ESC0 = {"30": "41", "31": "43", "32": "40", "33": "42", "34": "33", "RUTA TRANVIA": "4000"}


# ----------------------------------------------------------------------------- 1. oferta
def cargar_oferta():
    lin = pd.read_csv(D / "derivados" / "lineas_recorrido.csv", dtype={"linea": str})
    par = pd.read_csv(D / "derivados" / "paradas_por_linea.csv", dtype={"parada": str})
    e0 = pd.read_csv(D / "derivados" / "escenario0_lineas_lv.csv", dtype={"linea": str})
    e0 = e0[e0.tipo != "Alargue"].set_index("linea")
    lin["linea_esc0"] = lin.linea.map(lambda x: CAPA_A_ESC0.get(x, x))
    lin["en_esc0"] = lin.linea_esc0.isin(e0.index)
    lin["kmh"] = lin.linea_esc0.map(e0.vo_pico)
    lin["intervalo_min"] = lin.linea_esc0.map(e0.int_pico)
    lin["fuente"] = np.where(lin.en_esc0, "Escenario 0", "capa de líneas")
    # CV de los intervalos de cada línea en SUMO (mediana de sus paradas, 7:00-8:30; regularidad_sumo.csv); con menos
    # de 5 paradas medidas, la mediana de los buses
    reg = pd.read_csv(Path(__file__).resolve().parent / "grafo_pasajeros" / "regularidad_sumo.csv", index_col=0)
    ruta = "L" + lin.id_ld.str.replace("|", "_").str.replace(" ", "_")
    cv = ruta.map(reg.cv_mediana.where(reg.paradas >= 5))
    lin["cv_intervalo"] = 0.0 if REGULAR else cv.fillna(reg.cv_mediana[~reg.index.str.contains("TRANVIA") & (reg.paradas >= 5)].median())
    sin = ~lin.en_esc0
    lin.loc[sin, "kmh"] = lin.largo_km / (lin.tiempo_capa_min / 60)
    lin.loc[sin, "intervalo_min"] = 60 / lin.buses_h
    # paradas en orden, sin repetir la misma parada seguida ni paradas a menos de 30 m de la anterior
    filas = []
    for k, g in par.sort_values(["id_ld", "pos_m"]).groupby("id_ld"):
        ult_p, ult_pos = None, -1e9
        for r in g.itertuples():
            if r.parada == ult_p or r.pos_m - ult_pos < 30:
                continue
            filas.append(r._asdict())
            ult_p, ult_pos = r.parada, r.pos_m
    par = pd.DataFrame(filas).drop(columns="Index")
    par["k"] = par.groupby("id_ld").cumcount()
    return lin, par


def velocidades_sumo(par):
    """metros por minuto de cada tramo de parada a parada en el modelo calibrado de SUMO (mediana de los buses)."""
    f = RUN / "paradas_salida.xml"
    if not f.exists():
        return pd.Series(dtype=float)
    import xml.etree.ElementTree as ET
    filas = []
    try:
        for _, el in ET.iterparse(f):
            if el.tag == "stopinfo" and el.get("busStop"):
                filas.append((el.get("id"), el.get("busStop"), float(el.get("started")), float(el.get("ended"))))
            el.clear()
    except ET.ParseError:
        print("paradas_salida.xml incompleto (¿la simulación sigue corriendo?): velocidad uniforme en cada línea")
        return pd.Series(dtype=float)
    s = pd.DataFrame(filas, columns=["veh", "stop", "llega", "sale"])
    s["parada"] = s.stop.str.extract(r"^pa(.+?)_[^_]*_\d+$")[0]          # "pa<id2>_<carril>"
    ruta = s.veh.str.rsplit(".", n=1).str[0].str[1:].str.replace("RUTA_TRANVIA", "RUTA TRANVIA", regex=False)
    s["id_ld"] = ruta.str.rsplit("_", n=1).str.join("|")                  # "L100_Ida.3" -> "100|Ida"
    s = s.sort_values(["veh", "llega"])
    s["sig"] = s.groupby("veh").parada.shift(-1)
    # de llegada a llegada: incluye la detención en la parada, como la velocidad de operación del Escenario 0
    s["min"] = (s.groupby("veh").llega.shift(-1) - s.llega) / 60
    t = s.dropna(subset=["sig"]).groupby(["id_ld", "parada", "sig"])["min"].median()
    pos = par.set_index(["id_ld", "parada"]).pos_m
    out = {}
    for (k, a, b), m in t.items():
        if (k, a) in pos.index and (k, b) in pos.index and m > 0:
            dist = pos[(k, b)] - pos[(k, a)]
            if dist > 0:
                out[(k, a, b)] = dist / m          # metros por minuto en SUMO
    return pd.Series(out)


def factores_sumo(par):
    """velocidad relativa de cada tramo en SUMO (tramo / mediana de su línea): reparte la velocidad observada."""
    v = velocidades_sumo(par)
    if v.empty:
        return {}
    pos = par.set_index(["id_ld", "parada"]).pos_m
    dist = pd.Series([pos[(k, b)] - pos[(k, a)] for k, a, b in v.index], index=v.index)
    f = v.clip(v.groupby(level=0).transform("median") * 0.4, v.groupby(level=0).transform("median") * 2.0)
    # normalizado por distancia (km totales / horas totales): el tiempo de la línea completa sigue siendo el observado
    media = (dist.groupby(level=0).transform("sum") / (dist / f).groupby(level=0).transform("sum"))
    return (f / media).to_dict()


# ----------------------------------------------------------------------------- 2. demanda
def cargar_demanda():
    od = pd.read_excel(D / "matriz_OD_65zonas.xlsx", index_col=0)
    vt = pd.read_excel(BASE / "datos_originales" / "viajes_transporte.xlsx", index_col=0) / 100
    gen = pd.Series(0.0, index=od.index)
    for f in ["viajes_laborales.xlsx", "viajes_no_laborales.xlsx"]:
        d = pd.read_excel(BASE / "datos_originales" / f, index_col=0)
        h = d[d["Franja Horaria"] == HORA].set_index("Modo")["Viajes"]
        for m in ["Bus", "Tranvía"]:
            gen += h[m] * vt.loc[m].reindex(od.index).fillna(0)
    return od.mul(gen, axis=0)


# ----------------------------------------------------------------------------- 3. grafo
def construir_grafo(lin, par, factores, intervalos=None):
    """intervalos: {id_ld: minutos} para probar otra oferta (si falta, el de la situación actual)."""
    G = nx.DiGraph()
    lin = lin.set_index("id_ld")
    for k, g in par.groupby("id_ld"):
        L = lin.loc[k]
        h = (intervalos or {}).get(k, L.intervalo_min)
        v = L.kmh * 1000 / 60                                   # metros por minuto
        g = g.sort_values("k")
        filas = list(g.itertuples())
        for i, r in enumerate(filas):
            nodo = ("R", k, r.k)
            if i < len(filas) - 1:
                e = h * (1 + L.cv_intervalo ** 2) / 2                 # espera con buses irregulares
                G.add_edge(("S", r.parada), nodo, w=e + PEN_SUBIDA, tipo="subir", id_ld=k, espera=e)
                s = filas[i + 1]
                vel = v * factores.get((k, r.parada, s.parada), 1.0)
                G.add_edge(nodo, ("R", k, s.k), w=(s.pos_m - r.pos_m) / vel * (F_TRANVIA if L.modo == "tranvia" else 1.0), min_real=(s.pos_m - r.pos_m) / vel, tipo="viajar", id_ld=k, tramo=r.k)
            if i > 0:
                G.add_edge(nodo, ("S", r.parada), w=0.0, tipo="bajar", id_ld=k)
    # caminar entre paradas cercanas
    pt = par.drop_duplicates("parada").set_index("parada")[["x", "y"]]
    xy = pt.values
    for i, a in enumerate(pt.index):
        d = np.hypot(*(xy - xy[i]).T)
        for j in np.where((d > 0) & (d < TRANSBORDO_M))[0]:
            G.add_edge(("S", a), ("S", pt.index[j]), w=d[j] * RODEO / CAMINAR_M_MIN, tipo="caminar")
    return G


def armar_celdas():
    """
    Divide cada zona en celdas de CELDA m. Las zonas OD miden hasta 7 km²: medir la caminata desde su centro hace que
    quien vive junto a una parada camine 15-30 min. Cada celda recibe una parte de los viajes de su zona según los km
    de calles que tiene (más calles = más viviendas y actividad; red de OpenStreetMap, datos/derivados/red_calles_osm.gpkg).
    """
    zon = gpd.read_file(D / "zonas" / "zonas_od_2025.gpkg").to_crs(32717)[["zona_od", "geometry"]]
    x0, y0, x1, y1 = zon.total_bounds
    xs, ys = np.arange(x0, x1, CELDA), np.arange(y0, y1, CELDA)
    from shapely.geometry import box
    rej = gpd.GeoDataFrame(geometry=[box(x, y, x + CELDA, y + CELDA) for x in xs for y in ys], crs=32717)
    cel = gpd.overlay(rej, zon, how="intersection")
    cel = cel[cel.area > 0.05 * CELDA ** 2].reset_index(drop=True)
    calles = gpd.read_file(D / "derivados" / "red_calles_osm.gpkg").to_crs(32717)[["geometry"]]
    pedazos = gpd.overlay(calles, cel.reset_index()[["index", "geometry"]], how="intersection", keep_geom_type=True)
    cel["km_calles"] = pedazos.groupby("index").geometry.apply(lambda g: g.length.sum() / 1000).reindex(cel.index).fillna(0)
    cel = cel[cel.km_calles > 0.2].copy()                     # sin calles: sin viajes
    cel["peso"] = cel.km_calles / cel.groupby("zona_od").km_calles.transform("sum")
    cel["celda"] = cel.zona_od + "#" + cel.groupby("zona_od").cumcount().astype(str)
    return zon.set_index("zona_od"), cel.set_index("celda")


def demanda_celdas(od, cel):
    """viajes entre celdas = viajes entre sus zonas × peso de la celda de origen × peso de la de destino."""
    w = cel.peso.values
    m = od.loc[cel.zona_od, cel.zona_od].values * np.outer(w, w)
    return pd.DataFrame(m, index=cel.index, columns=cel.index)


def conectar_celdas(G, par, cel):
    """cada celda camina a las paradas a menos de ACCESO_M (en línea recta) de su punto central; si no hay, a las 3 más cercanas."""
    pt = par.drop_duplicates("parada").set_index("parada")
    xy = pt[["x", "y"]].values
    for c, r in cel.iterrows():
        p = r.geometry.representative_point()
        d = np.hypot(xy[:, 0] - p.x, xy[:, 1] - p.y)
        sel = np.where(d < ACCESO_M)[0]
        if len(sel) == 0:
            sel = np.argsort(d)[:3]
        for j in sel:
            t = d[j] * RODEO / CAMINAR_M_MIN
            G.add_edge(("O", c), ("S", pt.index[j]), w=t, tipo="acceso")
            G.add_edge(("S", pt.index[j]), ("D", c), w=t, tipo="salida")


def conectar_zonas(G, par):
    zon = gpd.read_file(D / "zonas" / "zonas_od_2025.gpkg").to_crs(32717).set_index("zona_od")
    pt = par.drop_duplicates("parada").set_index("parada")
    pts = gpd.GeoSeries(gpd.points_from_xy(pt.x, pt.y), index=pt.index, crs=32717)
    acceso = {}
    for z, r in zon.iterrows():
        c = r.geometry.representative_point()
        dentro = pts[pts.within(r.geometry.buffer(ACCESO_BUFFER))]
        if dentro.empty:
            dentro = pts.loc[pts.distance(c).nsmallest(3).index]
        for p, g in dentro.items():
            t = g.distance(c) * RODEO / CAMINAR_M_MIN
            G.add_edge(("O", z), ("S", p), w=t, tipo="acceso")
            G.add_edge(("S", p), ("D", z), w=t, tipo="salida")
        acceso[z] = len(dentro)
    return zon, acceso


# ----------------------------------------------------------------------------- 4. asignación
def asignar(G, od):
    """todo o nada por el camino de menor costo; devuelve cargas por tramo, subidas por línea y viajes."""
    carga, subidas, viajes = {}, {}, []
    for o in od.index:
        if ("O", o) not in G:
            continue
        _, caminos = nx.single_source_dijkstra(G, ("O", o), weight="w")
        for d, q in od.loc[o].items():
            if q <= 0 or d == o or ("D", d) not in caminos:
                continue
            c = caminos[("D", d)]
            comp = {"acceso": 0.0, "espera": 0.0, "viaje": 0.0, "caminar": 0.0, "subidas": 0, "tranvia": False}
            for a, b in zip(c, c[1:]):
                e = G.edges[a, b]
                if e["tipo"] == "viajar":
                    comp["viaje"] += e["w"]
                    carga[(e["id_ld"], e["tramo"])] = carga.get((e["id_ld"], e["tramo"]), 0) + q
                elif e["tipo"] == "subir":
                    comp["espera"] += e["espera"]
                    comp["subidas"] += 1
                    subidas[e["id_ld"]] = subidas.get(e["id_ld"], 0) + q
                    comp["tranvia"] |= e["id_ld"].startswith("RUTA TRANVIA")
                elif e["tipo"] in ("acceso", "salida"):
                    comp["acceso"] += e["w"]
                elif e["tipo"] == "caminar":
                    comp["caminar"] += e["w"]
            viajes.append({"o": o, "d": d, "viajes": q, **comp})
    return carga, subidas, pd.DataFrame(viajes)


def asignar_estrategias(G, od):
    """
    Asignación por estrategias óptimas (Spiess y Florian, 1989), el método estándar para transporte público:
    en una parada por donde pasan varias líneas útiles, el pasajero sube a la primera que llega. La espera es la mitad
    del intervalo combinado de esas líneas y cada línea lleva una parte proporcional a su frecuencia.
    Devuelve carga por tramo, subidas por línea y los totales (pasajeros-minuto) de cada parte del viaje.
    """
    nodos = list(G.nodes)
    idx = {n: i for i, n in enumerate(nodos)}
    ini, fin, costo, frec, tipo, lin, tramo, real = [], [], [], [], [], [], [], []
    for a, b, e in G.edges(data=True):
        ini.append(idx[a]); fin.append(idx[b]); tipo.append(e["tipo"]); lin.append(e.get("id_ld"))
        real.append(e.get("min_real", e["w"]))
        tramo.append(e.get("tramo"))
        if e["tipo"] == "subir":
            costo.append(PEN_SUBIDA); frec.append(1 / (2 * e["espera"]))       # espera = 1/(2 f)
        else:
            costo.append(e["w"]); frec.append(np.inf)
    entran = [[] for _ in nodos]
    for k, j in enumerate(fin):
        entran[j].append(k)
    carga, subidas = {}, {}
    tot = {"viajes": 0.0, "acceso": 0.0, "espera": 0.0, "viaje": 0.0, "caminar": 0.0, "subidas": 0.0,
           "subidas_tranvia": 0.0, "sin_camino": 0.0}
    import heapq
    for d in od.columns:
        r = idx.get(("D", d))
        q_d = od[d]
        if r is None:
            continue
        u = np.full(len(nodos), np.inf)
        f = np.zeros(len(nodos))
        u[r] = 0.0
        heap = [(costo[k], k) for k in entran[r]]
        heapq.heapify(heap)
        hecho = np.zeros(len(ini), bool)
        orden, sel_inf = [], {}
        while heap:
            key, k = heapq.heappop(heap)
            if hecho[k] or key != u[fin[k]] + costo[k]:
                continue
            hecho[k] = True
            i = ini[k]
            if u[i] < key:
                continue
            fa = frec[k]
            if np.isinf(fa):
                u[i], f[i] = key, np.inf
                sel_inf[i] = k
            elif np.isinf(f[i]):
                continue
            elif f[i] == 0:
                u[i], f[i] = 0.5 / fa + key, fa                    # espera regular: la mitad del intervalo
            else:
                u[i] = (f[i] * u[i] + fa * key) / (f[i] + fa)
                f[i] += fa
            orden.append(k)
            for k2 in entran[i]:
                if not hecho[k2]:
                    heapq.heappush(heap, (u[i] + costo[k2], k2))
        # carga: de los nodos más lejos del destino a los más cercanos
        V = np.zeros(len(nodos))
        for o, q in q_d.items():
            if o == d or q <= 0 or ("O", o) not in idx:
                continue
            if np.isinf(u[idx[("O", o)]]):
                tot["sin_camino"] += q
                continue
            V[idx[("O", o)]] += q
            tot["viajes"] += q
        for k in reversed(orden):
            i = ini[k]
            if V[i] <= 0:
                continue
            if np.isinf(frec[k]):
                if sel_inf.get(i) != k:
                    continue
                v = V[i]
            else:
                if np.isinf(f[i]):
                    continue
                v = V[i] * frec[k] / f[i]
            if v <= 0:
                continue
            V[fin[k]] += v
            t = tipo[k]
            if t == "viajar":
                carga[(lin[k], tramo[k])] = carga.get((lin[k], tramo[k]), 0) + v
                tot["viaje"] += v * real[k]                       # minutos reales (sin la preferencia)
            elif t == "subir":
                subidas[lin[k]] = subidas.get(lin[k], 0) + v
                tot["subidas"] += v
                tot["subidas_tranvia"] += v if lin[k].startswith("RUTA TRANVIA") else 0
            elif t in ("acceso", "salida"):
                tot["acceso"] += v * costo[k]
            elif t == "caminar":
                tot["caminar"] += v * costo[k]
        # espera: en cada nodo donde se sube, la mitad del intervalo combinado de las líneas útiles
        sube = {ini[k] for k in orden if not np.isinf(frec[k])}
        tot["espera"] += sum(V[i] * 0.5 / f[i] for i in sube if not np.isinf(f[i]) and f[i] > 0 and V[i] > 0)
    return carga, subidas, tot


def indicadores_estrategias(tot, intrazonal):
    n = tot["viajes"]
    return {"viajes_asignados_hora": round(n), "viajes_dentro_de_la_misma_celda_hora (no asignados)": round(intrazonal),
            "sin_camino_hora": round(tot["sin_camino"]),
            "min_puerta_a_puerta": round((tot["acceso"] + tot["espera"] + tot["viaje"] + tot["caminar"]) / n, 1),
            "min_acceso_y_salida": round(tot["acceso"] / n, 1), "min_espera": round(tot["espera"] / n, 1),
            "min_en_vehiculo": round(tot["viaje"] / n, 1), "min_caminar_transbordo": round(tot["caminar"] / n, 1),
            "subidas_por_viaje": round(tot["subidas"] / n, 2),
            "subidas_tranvia_%": round(100 * tot["subidas_tranvia"] / tot["subidas"], 1)}


def indicadores(v):
    t = v[v.subidas > 0]
    w = t.viajes
    m = lambda c: (t[c] * w).sum() / w.sum()
    return {"viajes_hora": round(v.viajes.sum()), "viajes_en_transporte_publico": round(w.sum()),
            "solo_caminando_%": round(100 * v[v.subidas == 0].viajes.sum() / v.viajes.sum(), 1),
            "min_puerta_a_puerta": round(m("acceso") + m("espera") + m("viaje") + m("caminar"), 1),
            "min_acceso_y_salida": round(m("acceso"), 1), "min_espera": round(m("espera"), 1),
            "min_en_vehiculo": round(m("viaje"), 1), "min_caminar_transbordo": round(m("caminar"), 1),
            "subidas_por_viaje": round(m("subidas"), 2),
            "con_transbordo_%": round(100 * w[t.subidas > 1].sum() / w.sum(), 1),
            "usan_tranvia_%": round(100 * w[t.tranvia].sum() / w.sum(), 1)}


if __name__ == "__main__":
    lin, par = cargar_oferta()
    fac = factores_sumo(par)
    od = cargar_demanda()
    t0 = time.time()
    zon, cel = armar_celdas()
    odc = demanda_celdas(od, cel)
    G = construir_grafo(lin, par, fac)
    conectar_celdas(G, par, cel)
    t1 = time.time()
    carga, subidas, tot = asignar_estrategias(G, odc)
    t2 = time.time()
    ind = indicadores_estrategias(tot, np.trace(odc.values))
    print(f"celdas: {len(cel)} (de {CELDA} m) en {cel.zona_od.nunique()} zonas")
    print(f"grafo: {G.number_of_nodes()} nodos, {G.number_of_edges()} aristas; tramos con velocidad de SUMO: {len(fac)}")
    print(f"tiempo: armar {t1 - t0:.1f} s, asignar {t2 - t1:.1f} s")
    for k, x in ind.items():
        print(f"  {k}: {x}")

    # ------------------------------------------------------------------------- salidas
    pd.DataFrame([{"nodo": "|".join(map(str, n))} for n in G.nodes]).to_csv(OUT / "nodos.csv", index=False)
    pd.DataFrame([{"desde": "|".join(map(str, a)), "hasta": "|".join(map(str, b)), "tipo": e["tipo"],
                   "minutos": round(e["w"], 3), "id_ld": e.get("id_ld")} for a, b, e in G.edges(data=True)]
                 ).to_csv(OUT / "aristas.csv", index=False, encoding="utf-8-sig")
    ct = par.copy()
    ct["pasajeros_h"] = [carga.get((r.id_ld, r.k), 0) for r in par.itertuples()]
    ct.to_csv(OUT / "cargas_tramos.csv", index=False, encoding="utf-8-sig")
    lin["subidas_h"] = lin.id_ld.map(subidas).fillna(0).round()
    lin["carga_max_h"] = lin.id_ld.map(ct.groupby("id_ld").pasajeros_h.max()).round()
    lin["capacidad_h"] = (60 / lin.intervalo_min * 80).round()          # bus de ~80 pasajeros
    lin["min_recorrido"] = lin.id_ld.map(ct.groupby("id_ld").pos_m.agg(lambda s: s.max() - s.min())) / 1000 / lin.kmh * 60
    lin.drop(columns="wkt").to_csv(OUT / "lineas.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([ind]).to_csv(OUT / "resumen.csv", index=False, encoding="utf-8-sig")

    # ------------------------------------------------------------------------- validación con el Escenario 0
    e0 = pd.read_csv(D / "derivados" / "escenario0_lineas_lv.csv", dtype={"linea": str})
    e0 = e0[e0.tipo != "Alargue"].set_index("linea")
    val = lin.groupby("linea_esc0").agg(linea_capa=("linea", "first"), subidas_h=("subidas_h", "sum")).reset_index()
    val["demanda_dia_esc0"] = val.linea_esc0.map(e0.demanda_dia)
    val = val.dropna(subset=["demanda_dia_esc0"])
    val["parte_modelo_%"] = (100 * val.subidas_h / val.subidas_h.sum()).round(1)
    val["parte_esc0_%"] = (100 * val.demanda_dia_esc0 / val.demanda_dia_esc0.sum()).round(1)
    val.sort_values("parte_esc0_%", ascending=False).to_csv(OUT / "validacion_lineas.csv", index=False,
                                                              encoding="utf-8-sig")
    r = np.corrcoef(val["parte_modelo_%"], val["parte_esc0_%"])[0, 1]
    tram = val.set_index("linea_esc0").loc["4000"]
    print(f"validación con la demanda por línea del Escenario 0 ({len(val)} líneas): r = {r:.2f}; "
          f"tranvía {tram['parte_modelo_%']} % de las subidas (Escenario 0: {tram['parte_esc0_%']} %)")

    # ------------------------------------------------------------------------- mapa de cargas
    fig, ax = plt.subplots(figsize=(10, 10))
    zon.boundary.plot(ax=ax, color="0.85", lw=0.5)
    segs = []
    for k, g in ct.sort_values(["id_ld", "k"]).groupby("id_ld"):
        xy = g[["x", "y"]].values
        for i in range(len(g) - 1):
            segs.append({"q": g.pasajeros_h.iloc[i], "tranvia": k.startswith("RUTA"),
                         "geometry": LineString([xy[i], xy[i + 1]])})
    s = gpd.GeoDataFrame(segs, crs=32717)
    s = s[s.q > 0].sort_values("q")
    s[~s.tranvia].plot(ax=ax, color="#c0392b", lw=0.3 + s[~s.tranvia].q / 150, alpha=0.6)
    s[s.tranvia].plot(ax=ax, color="#1e8449", lw=0.3 + s[s.tranvia].q / 150, alpha=0.9)
    b = gpd.GeoSeries(gpd.points_from_xy(par.x, par.y), crs=32717).total_bounds
    ax.set_xlim(b[0] - 500, b[2] + 500)
    ax.set_ylim(b[1] - 500, b[3] + 500)
    ax.set_axis_off()
    ax.set_title("Pasajeros por hora en cada tramo, 7:00-8:00 (rojo: bus; verde: tranvía; grosor = pasajeros)")
    fig.savefig(OUT / "mapa_cargas.png", dpi=150, bbox_inches="tight")
