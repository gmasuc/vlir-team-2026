"""
Buses y tranvia en la simulacion de la hora pico (red v2 + demanda de autos calibrada).

1. Recorridos: cada linea y sentido (Lineas_corregido.gpkg, 38 lineas + tranvia) se convierte en una secuencia de
   aristas de la red SUMO (sumolib.route.mapTrace sobre puntos cada 20 m). Solo se usa la parte del recorrido que
   esta dentro del area piloto (el tramo continuo mas largo).
2. Paradas: las del recorrido publicado por el GAD (CSV de abril de 2026, ubicadas con paradas.shp; ver paradas_de);
   la linea 100, las de paradas.shp marcadas para ella; el tranvia, sus 27 paradas. Solo las que quedan a menos de
   25 m del recorrido. Cada parada se ubica en el carril derecho
   de la arista del recorrido mas cercana.
3. Oferta: un flujo por linea y sentido de 6:00 a 9:00 con el intervalo de lunes a viernes (capa de lineas).
   Tiempo de parada: 20 s en bus, 30 s en tranvia.
4. Simulacion mesoscopica 6:00-9:30 con los autos calibrados (07, red v2) y comparacion:
   - velocidad comercial simulada de cada linea (buses que salen entre 7:00 y 8:00) contra la programada
     (largo / tiempo de recorrido de la capa de lineas);
   - buses por hora en los accesos contados contra los conteos 2023 (columna BUSES).

Uso:  py simulacion_sumo/09_buses.py [escenario] [calibrada|equilibrio] [capa|contrato]
Salida: simulacion_sumo/buses/<demanda>[_contrato]/  (buses.rou.xml, paradas.add.xml, velocidad_lineas.csv, buses_accesos.csv)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import difflib
import functools
import os
import re
import subprocess
import sys
import unicodedata
import zlib
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import sumo
from shapely.geometry import Point

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
BASE = SIM.parent
sys.path += [str(SIM), str(BASE)]
import conteos_accesos as ca  # noqa: E402
import red_buses as rb  # noqa: E402

ESC = sys.argv[1] if len(sys.argv) > 1 else "ambos"
DEMANDA = sys.argv[2] if len(sys.argv) > 2 else "calibrada"     # calibrada (07, red v2) o equilibrio (06, sin calibrar)
FREC = sys.argv[3] if len(sys.argv) > 3 else "capa"     # capa (intervalo de la capa de lineas) o contrato (escenario 1)
# En el modelo mesoscopico un bus detenido en una parada bloquea toda la calle (una sola cola por calle), y con mas
# buses la red se traba de forma artificial. Con "bahia" la parada se modela fuera de la calzada (parking="true"):
# el bus se hace a un lado y los autos siguen. (--meso-lane-queue, la alternativa, hace caer a SUMO en esta red.)
BAHIA = "bahia" in sys.argv
COLA_CARRIL = "cola_carril" in sys.argv     # una cola por carril (--meso-lane-queue: hace caer a SUMO 1.28, no usar)
# Un carril exclusivo de bus no tiene efecto en el modo mesoscopico (una sola cola por calle): el escenario 2 se corre
# en modo microscopico ("micro"), y la situacion actual tambien, para comparar en igualdad de condiciones.
MICRO = "micro" in sys.argv
CARRIL_BUS = "carril_bus" in sys.argv      # escenario 2: red v3 con carriles exclusivos (10_carriles_bus.py)
MENOS_CARRIL = "menos_carril" in sys.argv  # escenario 2 en meso: corredores con un carril menos (costo para los autos)
# Con "reruteo" los autos pueden cambiar de ruta durante el viaje segun el trafico del momento (cada 5 min); los buses y
# el tranvia mantienen su recorrido. Sin esto, al quitar un carril los autos siguen rutas que ya no les convienen.
RERUTEO = "reruteo" in sys.argv
# Con "scats" se usa la red v2s (semáforos que faltaban en OSM) y los programas reales de SCATS (13_semaforos_scats.py)
SCATS = "scats" in sys.argv
# Con "2b" (junto con menos_carril y scats) el carril menos es solo en la Av. de las Americas y la Av. 24 de Mayo
VAR = "_2b" if "2b" in sys.argv else ""
# Con "centro" (junto con scats): Centro Histórico con un carril menos y buses que paran en el carril (16_centro_realista.py).
# Versiones intermedias: "centro_parqueo" (solo el carril menos) y "centro_paradas" (solo las paradas en el carril).
CENTRO_RED = "centro" in sys.argv or "centro_parqueo" in sys.argv
CENTRO_PARADAS = "centro" in sys.argv or "centro_paradas" in sys.argv
CENTRO = CENTRO_RED or CENTRO_PARADAS
# Con "cap85", "cap70" o "cap55": las mismas calles conservan sus carriles pero con 85/70/55 % de su capacidad
CAP = next((a[3:] for a in sys.argv if a in ("cap85", "cap70", "cap55")), None)
# Con "vel_oficial" (junto con scats): velocidades máximas de la jerarquía vial oficial (18_velocidades_oficiales.py)
VEL = "vel_oficial" in sys.argv
# Semáforos en el modo mesoscópico: por defecto solo penalizan tiempo (--meso-tls-penalty). Con "tlsflow" además reducen
# el flujo según el tiempo de rojo (--meso-tls-flow-penalty), es decir, limitan cuántos vehículos pasan; con
# "tlsflow_solo", solo la reducción de flujo.
TLSFLOW = "tlsflow" in sys.argv
TLSFLOW_SOLO = "tlsflow_solo" in sys.argv
# "tlsflow_p25" / "tlsflow_p50": reducción de flujo + 25 % / 50 % de la demora de tiempo (calibración de la demora)
TLS_P = next((a[-2:] for a in sys.argv if a in ("tlsflow_p25", "tlsflow_p50")), None)
MESO_TLS = (["--meso-tls-flow-penalty", "1", "--meso-tls-penalty", str(int(TLS_P) / 100)] if TLS_P else
            ["--meso-tls-flow-penalty", "1"] if TLSFLOW_SOLO else
            ["--meso-tls-penalty", "1", "--meso-tls-flow-penalty", "1"] if TLSFLOW else ["--meso-tls-penalty", "1"])
# Demoras en los cruces (validación con tiempos de viaje, 23-10-2026):
#   "jc": los cruces controlan el paso (semáforos y prioridad de paso; --meso-junction-control) en vez de penalizarlo;
#   "minorNN": NN segundos de demora al cruzar por la vía secundaria de un cruce sin semáforo (--meso-minor-penalty).
JC = "jc" in sys.argv
MINOR = next((a[5:] for a in sys.argv if a.startswith("minor") and a[5:].isdigit()), None)
if JC:
    MESO_TLS = ["--meso-junction-control"]
if MINOR:
    MESO_TLS = MESO_TLS + ["--meso-minor-penalty", MINOR]
# Prueba de robustez (26-10-2026): "seedN" (otra semilla aleatoria), "dem90"/"dem110" (demanda de autos -10 % / +10 %),
# "sin2carriles" (red sin el paso de avenidas a 2 carriles de 08_capacidad_red.py; solo situación actual y contrato)
SEED = next((a[4:] for a in sys.argv if a.startswith("seed") and a[4:].isdigit()), None)
DEM = next((a[3:] for a in sys.argv if a in ("dem90", "dem110")), None)
SIN2 = "sin2carriles" in sys.argv
# "coord": semáforos de SCATS coordinados con el desfase de su enlace (ondas verdes; 24_coordinacion_scats.py)
COORD = "coord" in sys.argv
# "fases": además, las fases de SCATS corregidas en los 43 semáforos donde no coincidían (24_coordinacion_scats.py fases);
# "sin_vueltas": rutas sin las vueltas a la manzana que no están en la traza oficial (quitar_vueltas)
FASES_SCATS = "fases" in sys.argv
SUF_ROB = (f"_seed{SEED}" if SEED else "") + (f"_dem{DEM}" if DEM else "") + ("_sin2carriles" if SIN2 else "")
SUF_CENTRO = ("_vel" if VEL else "") + ("_coord" if COORD else "") + ("_fases" if FASES_SCATS else "") + ("_sinvueltas" if "sin_vueltas" in sys.argv else "") + ("_jc" if JC else "") + (f"_minor{MINOR}" if MINOR else "") + (f"_tlsflow_p{TLS_P}" if TLS_P else "_tlsflow_solo" if TLSFLOW_SOLO else "_tlsflow" if TLSFLOW else "") + (f"_cap{CAP}" if CAP else "_centro" if CENTRO_RED and CENTRO_PARADAS else "_centro_parqueo" if CENTRO_RED
              else "_centro_paradas" if CENTRO_PARADAS else "")
OUT = SIM / "buses" / (DEMANDA + ("" if FREC == "capa" else "_" + FREC) + ("_bahia" if BAHIA else "")
                       + ("_cc" if COLA_CARRIL else "") + ("_micro" if MICRO else "") + ("_carrilbus" if CARRIL_BUS else "") + ("_menoscarril" if MENOS_CARRIL else "") + ("_reruteo" if RERUTEO else "") + ("_scats" if SCATS else "") + VAR + SUF_CENTRO + SUF_ROB)
OUT.mkdir(parents=True, exist_ok=True)
NET = SIM / "red" / ("cuenca_piloto_v3_carril_bus.net.xml" if CARRIL_BUS else
                     f"cuenca_piloto_v3bs{VAR}_vel_menos_carril.net.xml" if MENOS_CARRIL and SCATS and VEL else
                     f"cuenca_piloto_v3bs{VAR}_menos_carril.net.xml" if MENOS_CARRIL and SCATS else
                     "cuenca_piloto_v3b_menos_carril.net.xml" if MENOS_CARRIL else
                     "cuenca_piloto_v2sc_centro.net.xml" if CENTRO_RED and SCATS else
                     "cuenca_piloto_v2scap_centro.net.xml" if CAP and SCATS else
                     "cuenca_piloto_v1s_vel.net.xml" if SIN2 and VEL and SCATS else
                     "cuenca_piloto_v2s_vel.net.xml" if VEL and SCATS else
                     "cuenca_piloto_v2s.net.xml" if SCATS else "cuenca_piloto_v2.net.xml")
_SEM = (f"semaforos_scats_v3b{VAR}" if MENOS_CARRIL else "semaforos_scats_v1" if SIN2 else
        "semaforos_scats_centro" if CENTRO_RED else "semaforos_scats")
SEMAFOROS = SIM / "red" / (_SEM + ("_coord" if COORD else "") + ("_fases" if COORD and FASES_SCATS else "") + ".add.xml")
EN_CENTRO = set((SIM / "red" / "aristas_centro.txt").read_text().split()) if CENTRO_PARADAS else set()
AUTOS = (SIM / "calibracion" / f"{ESC}_v2" / (f"demanda_final_dem{DEM}.rou.xml" if DEM else "demanda_final.rou.xml")
         if DEMANDA == "calibrada" else
         SIM / "asignacion" / ESC / "009" / "viajes_validos_009.rou.xml.gz")
B_BUS, E_BUS = 6 * 3600, 9 * 3600            # buses de 6:00 a 9:00 (a las 7:00 la red ya tiene buses circulando)
B, E = 7 * 3600, 8 * 3600                   # hora de comparacion
# Tiempo de parada promedio. En el bus es 10 s porque se marcan todas las paradas de la capa y en la realidad el bus
# no se detiene en todas (con 20 s en cada una, sin trafico, iba a 12 km/h contra 18.5 programados).
PARADA_S = {"bus": 10, "tranvia": 30}
env = dict(os.environ, SUMO_HOME=sumo.SUMO_HOME)
net = sumolib.net.readNet(str(NET))
xmin, ymin, xmax, ymax = net.getBoundary()

# ----------------------------------------------------------------------------- 1. recorridos en la red
op = rb.lineas_operativas(gpd.read_file(BASE / "datos" / "derivados" / "Lineas_corregido.gpkg"))
if FREC == "contrato":      # escenario 1: intervalo de paso de los contratos de operacion (sentido 1 = Ida, 2 = Retorno)
    con = pd.read_csv(BASE / "datos_originales" / "Contratos_Operacion_Buses.csv", sep=None, engine="python",
                      encoding="utf-8-sig")
    con["n_linea"] = con.n_linea.astype(str).str.strip().str.upper()
    antes = op.bh_lv.copy()
    for s, sentido in [("s1", "Ida"), ("s2", "Retorno")]:
        bh = dict(zip(con.n_linea, 60 / con[f"{s}_intervalo_paso_min"]))
        sel = (op.modo == "bus") & (op.sentido == sentido) & op.linename.str.upper().isin(bh)
        op.loc[sel, "bh_lv"] = op.loc[sel, "linename"].str.upper().map(bh)
    print(f"frecuencias del contrato: {(op.bh_lv.round(2) != antes.round(2)).sum()} lineas-sentido cambian; "
          f"buses/h {antes[op.modo == 'bus'].sum():.0f} -> {op.bh_lv[op.modo == 'bus'].sum():.0f}")
op = op[op.bh_lv > 0].copy()
op["tiempo_min"] = rb.minutos(op.tiempo_rec)
op["largo_km"] = op.geometry.length / 1000


def a_red(geom):
    """puntos cada 20 m de la linea, en coordenadas de la red; se queda con el tramo continuo mas largo dentro."""
    pts = gpd.GeoSeries([geom.segmentize(20)], crs=32717).to_crs(4326).iloc[0].coords
    xy = [net.convertLonLat2XY(lon, lat) for lon, lat in pts]
    dentro = [xmin + 50 < x < xmax - 50 and ymin + 50 < y < ymax - 50 for x, y in xy]
    tramos, actual = [], []
    for p, d in zip(xy, dentro):
        if d:
            actual.append(p)
        elif actual:
            tramos.append(actual)
            actual = []
    if actual:
        tramos.append(actual)
    return max(tramos, key=len) if tramos else []


def reparar(edges, clase):
    """une los saltos entre aristas no conectadas con el camino mas corto (calles que OSM tiene en otro sentido, etc.);
    si no hay camino, se queda con el tramo conectado mas largo."""
    piezas, actual = [], [edges[0]] if edges else []
    for a, b in zip(edges, edges[1:]):
        if b in a.getOutgoing():
            actual.append(b)
            continue
        camino, _ = net.getShortestPath(a, b, vClass=clase)
        if camino:
            actual += list(camino[1:])
        else:
            piezas.append(actual)
            actual = [b]
    piezas.append(actual)
    return max(piezas, key=lambda p: sum(e.getLength() for e in p)) if edges else []


a_utm_red = pyproj.Transformer.from_crs(4326, 32717, always_xy=True)


def pasadas_oficiales(e, geom):
    """veces que la traza oficial de la línea pasa a menos de 20 m del punto medio de la arista."""
    x, y = e.getShape()[len(e.getShape()) // 2]
    px, py = a_utm_red.transform(*net.convertXY2LonLat(x, y))
    pts = np.array(geom.segmentize(10).coords)
    cerca = (np.hypot(pts[:, 0] - px, pts[:, 1] - py) < 20).astype(int)
    return int(np.sum(np.diff(np.r_[0, cerca]) == 1))


def quitar_vueltas(edges, geom):
    """quita las vueltas que vuelven a una misma arista si la traza oficial pasa por ella menos veces que la ruta
    (vueltas a la manzana creadas al unir saltos del ajuste a la red, que el bus real no da)."""
    i = 0
    while i < len(edges):
        j = next((k for k in range(len(edges) - 1, i, -1) if edges[k] is edges[i]), None)
        if (j is not None and sum(e.getLength() for e in edges[i:j]) < 3000
                and pasadas_oficiales(edges[i], geom) < sum(1 for e in edges if e is edges[i])):
            edges = edges[:i] + edges[j:]
        i += 1
    return edges


SIN_VUELTAS = "sin_vueltas" in sys.argv
filas, rutas = [], {}
for r in op.itertuples():
    clase = "tram" if r.modo == "tranvia" else "bus"
    traza = a_red(r.geometry)
    edges = sumolib.route.mapTrace(traza, net, 25, fillGaps=800, direction=True, vClass=clase) if len(traza) > 10 else []
    edges = reparar(edges, clase)
    if SIN_VUELTAS and r.modo == "bus":
        edges = quitar_vueltas(edges, r.geometry)
    largo = sum(e.getLength() for e in edges) / 1000
    filas.append({"id_ld": r.id_ld, "linea": r.linename, "sentido": r.sentido, "modo": r.modo,
                  "km_total": round(r.largo_km, 1), "km_en_red": round(largo, 1), "aristas": len(edges)})
    if largo > 1:
        rutas[r.id_ld] = edges
cob = pd.DataFrame(filas)
print(f"lineas-sentido con recorrido en la red: {len(rutas)} de {len(op)}; km en la red: {cob.km_en_red.sum():.0f}")

# ----------------------------------------------------------------------------- 2. paradas
par = gpd.read_file(BASE / "datos" / "GIS_Transporte" / "paradas.shp").to_crs(32717)
tram_par = gpd.read_file(BASE / "datos" / "derivados" / "tranvia_corregido.gpkg", layer="paradas").to_crs(32717)
cols = {c.lower(): c for c in par.columns}


# Paradas de cada línea. Fuente principal: el recorrido publicado por el GAD Municipal (Cuenca en Datos, abril de 2026,
# datos/gadcuenca_recorridotransporte_2026abril.csv): por línea y sentido, la lista ordenada de puntos del recorrido,
# solo con nombres. Cada nombre se busca en paradas.shp (igual, o con 85 % de parecido) y, entre las paradas con ese
# nombre (suele haber una a cada lado de la calle), se toma la más cercana al recorrido (< 40 m). El sentido del CSV
# que corresponde a cada sentido de la capa de líneas se elige por el orden: en 12 líneas (10, 16, 21, 22, 23, 29,
# 30-34, 50) "Ida" y "Retorno" están al revés entre el CSV y la capa. Comparación (15-10-2026): el 76 % de los puntos
# se encuentra en la capa de paradas y el 87 % de esos queda sobre el recorrido; confirma además que las columnas l31
# y l34 de la capa son códigos antiguos de las líneas 9 y 11. Las líneas que no están en el CSV (100) usan las columnas
# de paradas.shp (l<linea>, o IL/RL por sentido); el tranvía, sus 27 paradas.
def nombre_norm(x):
    x = unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode().upper()
    x = re.sub(r"[^A-Z0-9 ]", " ", x)
    return " ".join(re.sub(r"\b(AV|AVENIDA|CALLE|Y|E|DE|LA|EL|LOS|LAS|DEL)\b", " ", x).split())


par["n"] = par.nombres.map(nombre_norm)
par_pt = par.geometry.centroid
par_w = par.n.str.split().map(set)
nombres_capa = sorted(set(par.n))
rec = pd.read_csv(BASE / "datos" / "gadcuenca_recorridotransporte_2026abril.csv", encoding="latin-1", dtype=str)
rec["n"] = rec.PUNTO_RECORRIDO.map(nombre_norm)
_igual = {n: n for n in nombres_capa}
rec["en_capa"] = rec.n.map(lambda n: _igual.get(n) or next(iter(difflib.get_close_matches(n, nombres_capa, 1, 0.85)), None))
origen_paradas, estado_puntos = {}, []
NO_CALLE = {"VIA", "ENTRADA", "SALIDA", "SECTOR", "FRENTE", "REDONDEL", "PUENTE", "PARADA", "BARRIO", "SAN", "SANTA"}
a_utm = pyproj.Transformer.from_crs(4326, 32717, always_xy=True)


def mayus(x):
    return re.sub(r"[^A-Z0-9 ]", " ", unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode().upper())


@functools.lru_cache(maxsize=None)
def es_calle(palabras, nombre_red):
    """todas las palabras de la calle están (85 % de parecido) en el nombre de la calle de la red."""
    red = nombre_norm(nombre_red).split()
    return all(any(w == x or (len(w) > 3 and difflib.SequenceMatcher(None, w, x).ratio() >= 0.85) for x in red)
               for w in palabras)


def cruces_en_ruta(id_ld, texto):
    """puntos (UTM) de los cruces del recorrido con la calle o las dos calles que nombra el texto."""
    calles = [tuple(w for w in nombre_norm(c).split() if (len(w) >= 3 or w.isdigit()) and w not in NO_CALLE)
              for c in re.split(r"\s+(?:Y|E)\s+", mayus(texto))]
    calles = [c for c in calles if c]
    if not calles or len(calles) > 2:
        return []
    out = []
    for e in rutas.get(id_ld, []):              # fuera del área simulada no hay red: sin cruces
        n = e.getToNode()
        nombres = {x.getName() for x in n.getIncoming() + n.getOutgoing() if x.getName()}
        if all(any(es_calle(c, nm) for nm in nombres) for c in calles):
            out.append(Point(a_utm.transform(*net.convertXY2LonLat(*n.getCoord()))))
    return out


def paradas_de(r):
    if r.modo == "tranvia":
        origen_paradas[r.id_ld] = "capa del tranvía"
        return tram_par[tram_par.sentido == r.sentido].assign(id2=lambda d: "T" + d.numero.astype(str))
    if r.linename in set(rec.LINEA):
        opciones = []
        for sen in ["IDA", "RETORNO"]:
            pos = []
            for n in rec[(rec.LINEA == r.linename) & (rec.SENTIDO == sen)].en_capa.dropna():
                d = par_pt[par.n == n].distance(r.geometry)
                if d.min() < 40:
                    pos.append(r.geometry.project(par_pt[d.idxmin()]))
            opciones.append((np.corrcoef(range(len(pos)), pos)[0, 1] if len(pos) > 2 else -1, sen))
        orden, sen = max(opciones)
        # en el orden del CSV: paradas de la capa y, para los puntos que no están en ella, el cruce de calles
        # ("TARQUI Y SANGURIMA") o la calle ("LUIS CORDERO") sobre el recorrido, el primero después del punto anterior
        filas, nuevos, ultimo, contenidos = [], [], -np.inf, 0
        for f in rec[(rec.LINEA == r.linename) & (rec.SENTIDO == sen)].itertuples():
            if isinstance(f.en_capa, str):
                d = par_pt[par.n == f.en_capa].distance(r.geometry)
                if d.min() < 40:
                    filas.append(d.idxmin())
                    ultimo = r.geometry.project(par_pt[d.idxmin()])
                estado_puntos.append((r.id_ld, sen, f.PUNTO_RECORRIDO, "capa" if d.min() < 40 else "capa, lejos del recorrido"))
                continue
            if orden <= 0:
                estado_puntos.append((r.id_ld, sen, f.PUNTO_RECORRIDO, "sin ubicar"))
                continue
            # nombre contenido en el de una parada de la capa: "REDONDEL DE MIRAFLORES" está en "AMERICAS Y DEL SILBAN
            # (REDONDEL MIRAFLORES)" y "PUMAPUNGO" en "HUAYNA CAPAC Y PISARCAPAC (PUMAPUNGO)"
            # (primero con todas las palabras; si no, sin las genéricas: "REDONDEL DEL OTORONGO" -> "OTORONGO")
            ws = {w for w in str(f.n).split() if len(w) >= 3 or w.isdigit()} if isinstance(f.n, str) else set()
            hallada = None
            for w in (ws, ws - NO_CALLE):
                m = par_w.map(w.issubset) if w else None
                if m is None or not m.any():
                    continue
                d = par_pt[m].distance(r.geometry)
                c = sorted(((r.geometry.project(par_pt[k]), k) for k in d[d < 40].index), key=lambda x: x[0])
                c = [x for x in c if x[0] >= ultimo - 30]
                if c:
                    hallada = c[0]
                    break
            if hallada:
                ultimo, k = hallada
                filas.append(k)
                contenidos += 1
                estado_puntos.append((r.id_ld, sen, f.PUNTO_RECORRIDO, "nombre contenido"))
                continue
            cands = sorted(((r.geometry.project(pt), pt) for pt in cruces_en_ruta(r.id_ld, f.PUNTO_RECORRIDO)),
                           key=lambda c: c[0])
            cands = [c for c in cands if c[0] >= ultimo - 30 and r.geometry.distance(c[1]) < 25]
            if cands:
                ultimo, pt = cands[0]
                nuevos.append({"id2": f"x{zlib.crc32(f'{r.id_ld}{f.Index}'.encode())}",
                               "nombres": f.PUNTO_RECORRIDO.strip(), "geometry": pt})
            estado_puntos.append((r.id_ld, sen, f.PUNTO_RECORRIDO, "cruce de calles" if cands else "sin ubicar"))
        origen_paradas[r.id_ld] = (f"recorrido municipal 2026 ({sen.lower()}"
                                   + (", sentido invertido respecto a la capa" if sen.capitalize() != r.sentido else "")
                                   + (f"; {contenidos} por nombre contenido" if contenidos else "")
                                   + (f"; {len(nuevos)} por cruce de calles" if nuevos else "") + ")")
        base = par.loc[sorted(set(filas)), ["id2", "nombres", "geometry"]]
        if not nuevos:
            return base
        return pd.concat([base, gpd.GeoDataFrame(nuevos, geometry="geometry", crs=32717)], ignore_index=True)
    pref = "il" if r.sentido == "Ida" else "rl"
    col = cols.get(pref + r.linename.lower()) or cols.get("l" + r.linename.lower())
    if col is None:
        origen_paradas[r.id_ld] = "sin paradas"
        return par.iloc[0:0]
    origen_paradas[r.id_ld] = "capa de paradas"
    return par[pd.to_numeric(par[col], errors="coerce").fillna(0) > 0]


# "solo_paradas": exporta las paradas de cada línea en todo su recorrido (también fuera del área simulada), en orden,
# para el grafo de pasajeros (optimizacion/02_grafo_pasajeros.py), y termina sin simular
if "solo_paradas" in sys.argv:
    filas_p, filas_l = [], []
    for r in op.itertuples():
        cand = paradas_de(r)
        cand = cand[cand.distance(r.geometry) < 25]
        for p in cand.itertuples():
            c = p.geometry.centroid
            filas_p.append({"id_ld": r.id_ld, "parada": str(p.id2), "nombre": getattr(p, "nombres", None) or
                            getattr(p, "nombre", ""), "x": round(c.x, 1), "y": round(c.y, 1),
                            "pos_m": round(r.geometry.project(c), 1)})
        filas_l.append({"id_ld": r.id_ld, "linea": r.linename, "sentido": r.sentido, "modo": r.modo,
                        "buses_h": r.bh_lv, "largo_km": round(r.largo_km, 2), "tiempo_capa_min": r.tiempo_min,
                        "origen_paradas": origen_paradas.get(r.id_ld), "wkt": r.geometry.wkt})
    pd.DataFrame(filas_p).sort_values(["id_ld", "pos_m"]).to_csv(
        BASE / "datos" / "derivados" / "paradas_por_linea.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(filas_l).to_csv(BASE / "datos" / "derivados" / "lineas_recorrido.csv", index=False, encoding="utf-8-sig")
    print(f"paradas por línea: {len(filas_p)} en {len(filas_l)} recorridos -> datos/derivados/paradas_por_linea.csv")
    sys.exit(0)

paradas, stops_ruta = {}, {}
for r in op.itertuples():
    if r.id_ld not in rutas:
        continue
    edges = rutas[r.id_ld]
    cand = paradas_de(r)
    cand = cand[cand.distance(r.geometry) < 25].to_crs(4326)
    lista = []
    for p in cand.itertuples():
        c = p.geometry.centroid                     # algunas paradas vienen como MultiPoint
        x, y = net.convertLonLat2XY(c.x, c.y)
        mejor = None
        for i, e in enumerate(edges):
            lane = next((l for l in e.getLanes() if l.allows("tram" if r.modo == "tranvia" else "bus")), None)
            if lane is None:
                continue
            pos, d = sumolib.geomhelper.polygonOffsetAndDistanceToPoint((x, y), lane.getShape())
            if d < 30 and (mejor is None or d < mejor[0]):
                mejor = (d, i, lane, pos)
        if mejor is None:
            continue
        _, i, lane, pos = mejor
        L = lane.getLength() - 0.2                  # margen para que el redondeo no pase el final del carril
        ini = max(0.0, min(pos - 10, L - 20)) if L > 20 else 0.0
        fin = min(L, ini + 20)
        if fin - ini < 2:
            continue
        sid = f"pa{p.id2}_{lane.getID()}"
        paradas[sid] = (lane.getID(), ini, fin, getattr(p, "nombres", None) or getattr(p, "nombre", ""))
        lista.append((i, ini, sid))
    lista = sorted(set(lista))
    vistos, orden = set(), []
    for i, ini, sid in lista:                  # una sola parada por arista y linea (la primera)
        if i not in vistos:
            vistos.add(i)
            orden.append(sid)
    stops_ruta[r.id_ld] = orden
cob["paradas"] = cob.id_ld.map(lambda k: len(stops_ruta.get(k, [])))
cob["origen_paradas"] = cob.id_ld.map(origen_paradas)
pd.DataFrame(estado_puntos, columns=["id_ld", "sentido_csv", "punto", "estado"]).to_csv(
    OUT / "puntos_recorrido.csv", index=False, encoding="utf-8-sig")

with open(OUT / "paradas.add.xml", "w", encoding="utf-8") as f:
    f.write("<additional>\n")
    for sid, (lane, ini, fin, nom) in paradas.items():
        nom = str(nom).replace("&", "y").replace('"', "'")
        f.write(f'  <busStop id="{sid}" lane="{lane}" startPos="{ini:.1f}" endPos="{fin:.1f}" name="{nom}"/>\n')
    f.write(f'  <edgeData id="buses" file="buses_aristas.xml" begin="{B}" end="{E}" excludeEmpty="true" '
            f'vTypes="bus"/>\n'
            f'  <edgeData id="todos" file="aristas_todos.xml" begin="{B}" end="{E}" excludeEmpty="true"/>\n'
            '</additional>\n')

# ----------------------------------------------------------------------------- 3. flujos de buses y tranvia
with open(OUT / "buses.rou.xml", "w", encoding="utf-8") as f:
    f.write('<routes>\n  <vType id="bus" vClass="bus" color="220,40,40" length="12" maxSpeed="13.9" accel="1.0" decel="3.0">'
            '<param key="has.rerouting.device" value="false"/></vType>\n'
            # el tranvia real mide ~33 m, pero en el modelo mesoscopico no cabe en los tramos cortos de riel y se
            # queda trabado; como la via es exclusiva, su largo no afecta a otros vehiculos.
            # maxSpeed 8.3 m/s (30 km/h): con 50 km/h hacia el recorrido en 22 min; el horario dice 31-32 min
            '  <vType id="tranvia" vClass="tram" color="0,170,90" length="10" maxSpeed="8.3" accel="1.0" decel="2.5">'
            '<param key="has.rerouting.device" value="false"/></vType>\n')
    for r in op.itertuples():
        if r.id_ld not in rutas:
            continue
        rid = "L" + r.id_ld.replace("|", "_").replace(" ", "_")
        tipo = "tranvia" if r.modo == "tranvia" else "bus"
        f.write(f'  <route id="{rid}" edges="{" ".join(e.getID() for e in rutas[r.id_ld])}">\n')
        for sid in stops_ruta[r.id_ld]:
            # en el centro realista el bus para en el carril (sin bahía)
            fuera = (' parking="true"' if BAHIA and r.modo == "bus"
                     and paradas[sid][0].rsplit("_", 1)[0] not in EN_CENTRO else "")
            f.write(f'    <stop busStop="{sid}" duration="{PARADA_S[r.modo]}"{fuera}/>\n')
        f.write("  </route>\n")
        f.write(f'  <flow id="{rid}" type="{tipo}" route="{rid}" begin="{B_BUS}" end="{E_BUS}" '
                f'period="{3600 / r.bh_lv:.0f}" departLane="best"/>\n')
    f.write("</routes>\n")
cob.to_csv(OUT / "cobertura_lineas.csv", index=False, encoding="utf-8-sig")
print(f"paradas ubicadas: {len(paradas)}; buses y tranvias por hora: {op[op.id_ld.isin(rutas)].bh_lv.sum():.0f}")
if "solo_paradas" in sys.argv:               # para revisar las paradas sin simular
    sys.exit(0)

# ----------------------------------------------------------------------------- 4. prioridad del tranvia
# El tranvia tiene via propia y prioridad en los cruces: en cada semaforo, los movimientos que salen de los rieles
# quedan siempre en verde (programa "tranvia"; los autos mantienen sus tiempos). Con "scats" se parte de los tiempos de
# SCATS de ese semáforo (si los hay), porque este programa se carga al final y es el que queda activo.
net_tls = sumolib.net.readNet(str(NET), withPrograms=True)
dur_scats, off_scats = {}, {}
if SCATS:
    for t in sumolib.xml.parse(str(SEMAFOROS), "tlLogic"):
        dur_scats[t.id] = [(float(p.duration), p.state) for p in t.phase]
        off_scats[t.id] = t.offset
with open(OUT / "tranvia_prioridad.add.xml", "w", encoding="utf-8") as f:
    f.write("<additional>\n")
    n_tls = 0
    for tl in net_tls.getTrafficLights():
        idx = {i for i, conns in tl.getLinks().items() for (carril_desde, _, _) in conns
               if carril_desde.getEdge().getType() == "railway.tram"}
        if not idx:
            continue
        n_tls += 1
        for pid, prog in tl.getPrograms().items():
            f.write(f'  <tlLogic id="{tl.getID()}" programID="tranvia" offset="{off_scats.get(tl.getID(), 0)}" type="static">\n')
            # fases del programa de SCATS si lo hay (puede tener otra estructura que la red), si no las de la red
            fases = dur_scats.get(tl.getID(), [(ph.duration, ph.state) for ph in prog.getPhases()])
            for dur, estado in fases:
                st = "".join("G" if i in idx else c for i, c in enumerate(estado))
                f.write(f'    <phase duration="{dur:.0f}" state="{st}"/>\n')
            f.write("  </tlLogic>\n")
            break
    f.write("</additional>\n")
print(f"semaforos con prioridad para el tranvia: {n_tls}")

# ----------------------------------------------------------------------------- 5. simular
cmd = [Path(sumo.SUMO_HOME) / "bin" / "sumo", "-n", NET, "-r", f"{OUT / 'buses.rou.xml'},{AUTOS}",
       "-a", ",".join([*( [str(SEMAFOROS)] if SCATS else []),
                       *([str(SIM / "red" / f"meso_centro_cap{CAP}.add.xml")] if CAP else []),
                 str(OUT / "tranvia_prioridad.add.xml"), str(OUT / "paradas.add.xml")]), *([] if MICRO else ["--mesosim", *MESO_TLS]), *(["--meso-lane-queue"] if COLA_CARRIL else []),
       *(["--device.rerouting.probability", "1", "--device.rerouting.period", "300",
          "--device.rerouting.adaptation-steps", "18"] if RERUTEO else []), "-b", B_BUS, "-e", E_BUS + 1800,
       "--time-to-teleport", "300", "--ignore-route-errors", "--no-step-log", "--threads", "4",
       *(["--seed", SEED] if SEED else []),
       "--tripinfo-output", "viajes.xml", "--tripinfo-output.write-unfinished",
       "--summary-output", "resumen.xml", "--duration-log.statistics",
       # "paradas_salida": además, la hora de llegada y salida de cada bus en cada parada (para 15_tiempos_parada_a_parada.py)
       *(["--stop-output", "paradas_salida.xml"] if "paradas_salida" in sys.argv else [])]
if os.name == "nt":                       # que Windows no suspenda la computadora mientras corre
    import ctypes
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
with open(OUT / "sumo.log", "w") as log:
    rc = subprocess.run([str(x) for x in cmd], cwd=OUT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
if rc != 0:
    sys.exit(f"fallo sumo (ver {OUT / 'sumo.log'})")

# ----------------------------------------------------------------------------- 5. comparar
todos = pd.DataFrame([{"id": v.id, "tipo": v.vType, "salida": float(v.depart), "llegada": float(v.arrival),
                       "duracion": float(v.duration), "km": float(v.routeLength) / 1000}
                      for v in sumolib.xml.parse(str(OUT / "viajes.xml"), "tripinfo")])
t = todos[todos.tipo.isin(["bus", "tranvia"])].copy()
autos = todos[~todos.tipo.isin(["bus", "tranvia"]) & (todos.salida >= B) & (todos.salida < E)]
t["ruta"] = t.id.str.rsplit(".", n=1).str[0]
t = t[(t.salida >= B) & (t.salida < E)]
t["terminado"] = t.llegada > 0
vel = t[t.terminado].groupby("ruta").agg(viajes=("id", "size"), km=("km", "mean"), min_sim=("duracion", lambda s: s.mean() / 60))
vel["kmh_sim"] = vel.km / (vel.min_sim / 60)
op["ruta"] = "L" + op.id_ld.str.replace("|", "_").str.replace(" ", "_")
op["kmh_programada"] = op.largo_km / (op.tiempo_min / 60)
vel = vel.join(op.set_index("ruta")[["linename", "sentido", "kmh_programada"]])
vel["no_terminaron"] = t[~t.terminado].groupby("ruta").size().reindex(vel.index).fillna(0).astype(int)
vel = vel.round(1).sort_values("kmh_sim")
vel.to_csv(OUT / "velocidad_lineas.csv", encoding="utf-8-sig")

bus_acc = ca.conteos_por_acceso(BASE, 7, "BUSES")
aristas, _ = ca.ubicar_accesos(net)
sim = {}
for iv in sumolib.xml.parse(str(OUT / "buses_aristas.xml"), "interval"):
    for e in iv.edge or []:
        sim[e.id] = float(e.entered or 0)
acc = pd.DataFrame([{"interseccion": i, "acceso": l, "contados": bus_acc.get((i, l), 0), "simulados": sim.get(e, 0)}
                    for (i, l), e in aristas.items()])
acc = acc[(acc.contados > 0) | (acc.simulados > 0)]
acc.to_csv(OUT / "buses_accesos.csv", index=False, encoding="utf-8-sig")

bus = vel[vel.linename != "RUTA TRANVIA"]
tb = t[t.tipo == "bus"]
ult = list(sumolib.xml.parse(str(OUT / "resumen.xml"), "step"))[-1]
pd.DataFrame([{"demanda": DEMANDA, "frecuencias": FREC, "buses_h": round(op.bh_lv[op.modo == "bus"].sum()),
               "buses_salen_7_8": len(tb), "buses_terminan_%": round(100 * tb.terminado.mean()),
               "bus_kmh_mediana": round(bus.kmh_sim.median(), 1),
               "bus_kmh_flota": round(tb[tb.terminado].km.sum() / (tb[tb.terminado].duracion.sum() / 3600), 1),
               "autos_salen_7_8": len(autos), "autos_terminan_%": round(100 * (autos.llegada > 0).mean(), 1),
               "auto_viaje_min": round(autos[autos.llegada > 0].duracion.mean() / 60, 1),
               "en_calle_9_30": int(ult.running), "teletransportes": int(ult.teleports)}]).to_csv(
    OUT / "resumen_escenario.csv", index=False)
print(f"\nbuses que salen 7-8 h: {len(t)}; terminaron su recorrido: {t.terminado.mean():.0%}")
print(f"velocidad comercial simulada (mediana de las lineas): {bus.kmh_sim.median():.1f} km/h; "
      f"programada: {bus.kmh_programada.median():.1f} km/h")
print(vel.to_string())
ok = acc[acc.contados > 20]
print(f"\nbuses en accesos contados (>20 buses/h): contados {ok.contados.sum():.0f}, simulados {ok.simulados.sum():.0f}, "
      f"correlacion {np.corrcoef(ok.contados, ok.simulados)[0, 1]:.2f}")
print(acc.sort_values("contados", ascending=False).to_string(index=False))

# ----------------------------------------------------------------------------- 6. velocidades corregidas
# routeLength de SUMO (mesoscopico) es ~29 % mayor que el largo real de la ruta: se recalculan las velocidades con
# el largo de las calles (velocidades_bus.py) y se reescriben velocidad_lineas.csv y resumen_escenario.csv.
subprocess.run([sys.executable, "-W", "ignore", str(SIM / "velocidades_bus.py")], cwd=SIM,
               env=dict(env, PYTHONPATH=str(BASE)), check=True)
