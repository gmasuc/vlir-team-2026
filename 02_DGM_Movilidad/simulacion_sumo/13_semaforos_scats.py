"""
Semáforos reales (capturas de SCATS) en la red del simulador.

1. Ubicación: cada cruce de SCATS (TCS) se busca entre los cruces de la red v2 por los nombres de sus calles (título
   de la captura y nombres del mapa). La comparación tolera diferencias de escritura: una calle coincide si su
   apellido (última palabra) coincide, con al menos 85 % de parecido, y al menos la mitad de sus palabras también
   (así "Antonio Borrero" encuentra "Calle Presidente Borrero" y "Honorato Vasquez" encuentra "Honorato Vázquez").
   Se elige el cruce de la red que coincide con más calles (al menos 2, o 1 si el cruce nombra una sola). Si los
   mejores candidatos están a más de 150 m entre sí, el cruce queda ambiguo.
2. Red v2s: los cruces ubicados que en la red no tenían semáforo (OSM no lo marcaba) pasan a tenerlo
   (netconvert --tls.set). Hallazgo: varios cruces de la Vega Muñoz, la Mariscal Lamar, la Gran Colombia y la
   Av. España tienen semáforo en SCATS pero no en OpenStreetMap.
3. Programas "scats" sobre la red v2s: se mantiene la estructura de fases de la red (qué movimientos tienen verde
   juntos) y sus amarillos; el ciclo pasa a ser el de SCATS. Si SCATS y la red tienen el mismo número de fases, la
   fase de SCATS con más verde va a la fase de la red que da paso a más carriles (la avenida principal), y así en
   orden; si no coinciden, el verde se reparte en las proporciones de la red, escaladas al ciclo de SCATS.
   Las capturas son de media mañana (no hora pico) y SCATS es adaptativo: es una aproximación mejor que los tiempos
   genéricos, no los tiempos exactos de la hora pico.
4. KML de la DGM (15-10-2026): los reguladores del tranvía en la Av. de las Américas se ubican por sus coordenadas
   (no por nombre); en las intersecciones conflictivas con tiempos de fase de hora pico, esos tiempos reemplazan a los
   de SCATS y cada fase se empareja con la fase de la red por el nombre de la calle que tiene el verde.

Uso:  py simulacion_sumo/13_semaforos_scats.py [menos_carril [2b]]
      Con "menos_carril" también construye la red v3bs (v2s con un carril menos en los corredores del escenario 2,
      red/carriles_bus_v3b.edg.xml de 10_carriles_bus.py) y escribe sus programas en red/semaforos_scats_v3b.add.xml.
      Con "2b", lo mismo solo para la Av. de las Américas y la Av. 24 de Mayo (archivos con _2b).
Entrada: datos/scats/scats_cruces.csv, red/cuenca_piloto_v2.net.xml
Salida: red/cuenca_piloto_v2s.net.xml, red/semaforos_scats.add.xml, datos/scats/scats_ubicados.csv
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import difflib
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import sumo

sys.path.append(str(Path(sumo.SUMO_HOME) / "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
BASE = SIM.parent
NET2 = SIM / "red" / "cuenca_piloto_v2.net.xml"
NET2S = SIM / "red" / "cuenca_piloto_v2s.net.xml"
V1 = "v1" in sys.argv                       # red v1 (sin avenidas a 2 carriles), para la prueba de robustez
if V1:
    NET2, NET2S = SIM / "red" / "cuenca_piloto.net.xml", SIM / "red" / "cuenca_piloto_v1s.net.xml"
MENOS = "menos_carril" in sys.argv
VAR = "_2b" if "2b" in sys.argv else ""
NET3BS = SIM / "red" / f"cuenca_piloto_v3bs{VAR}_menos_carril.net.xml"
ADD = SIM / "red" / (f"semaforos_scats_v3b{VAR}.add.xml" if MENOS else
                     "semaforos_scats_v1.add.xml" if V1 else "semaforos_scats.add.xml")
EDG = SIM / "red" / f"carriles_bus_v3b{VAR}.edg.xml"
if "centro" in sys.argv:                    # centro realista (16_centro_realista.py): un carril menos en el centro
    MENOS, VAR = True, "_centro"
    EDG = SIM / "red" / "carriles_centro.edg.xml"
    NET3BS = SIM / "red" / "cuenca_piloto_v2sc_centro.net.xml"
    ADD = SIM / "red" / "semaforos_scats_centro.add.xml"
GENERICAS = {"av", "avenida", "calle", "y", "de", "del", "la", "las", "los", "el", "pasaje", "cuenca", "tranvia",
             "estacion", "est", "redondel", "puente", "sector", "entrada", "salida", "ingreso", "frente", "junto",
             "via", "presidente", "coronel", "general", "mariscal", "doctor"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", s)


def palabras(s):
    return [x for x in norm(s).split() if len(x) >= 4 and x not in GENERICAS]


def calles_de(fila):
    """calles nombradas en la captura, cada una como lista de palabras significativas (la última = apellido)."""
    nombre = re.split(r"\s:\s|\s-\s(?=cuenca)", str(fila.nombre))[0]
    partes = re.split(r",|/|\s-\s|\sy\s|\se\s", nombre) + str(fila.calles_mapa).split("|")
    out = []
    for p in partes:
        w = palabras(p)
        if w and w not in out:
            out.append(w)
    return out


def parecida(a, b):
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def coincide(calle, nombre_red, tolerante):
    w = set(palabras(nombre_red))
    if not tolerante:                                   # todas las palabras de la calle están en el nombre
        return bool(w) and set(calle) <= w
    if not w or not any(parecida(calle[-1], x) for x in w):
        return False
    return sum(any(parecida(p, x) for x in w) for p in calle) >= len(calle) / 2


def buscar(calles, tolerante):
    punt = []
    for n, nombres in nodos:
        hit = sum(any(coincide(c, nm, tolerante) for nm in nombres) for c in calles)
        if hit:
            punt.append((hit, n))
    if not punt:
        return None
    mejor = max(p[0] for p in punt)
    top = [p[1] for p in punt if p[0] == mejor]
    xy = np.mean([n.getCoord() for n in top], axis=0)
    disp = max(np.hypot(*(np.array(n.getCoord()) - xy)) for n in top)
    if mejor < min(2, len(calles)):
        est = "solo una calle coincide"
    elif disp > 150:
        est = f"ambiguo ({len(top)} candidatos)"
    else:
        est = "ubicado"
    return est, mejor, top, xy


# ----------------------------------------------------------------------------- 1. ubicación en la red v2
net = sumolib.net.readNet(str(NET2))
nodos = [(n, {e.getName() for e in n.getIncoming() + n.getOutgoing() if e.getName()}) for n in net.getNodes()
         if n.getType() not in ("dead_end", "internal")]
sc = pd.read_csv(BASE / "datos" / "scats" / "scats_cruces.csv", dtype=str).fillna("")
filas = []
for r in sc.itertuples():
    calles = calles_de(r)
    res = buscar(calles, tolerante=False)               # primero exacta; si no ubica, tolerante
    if res is None or res[0] != "ubicado":
        res2 = buscar(calles, tolerante=True)
        if res2 is not None and (res is None or res2[0] == "ubicado"):
            res = res2
    if res is None:
        filas.append({"tcs": r.tcs, "nodos_red": "", "coincidencias": 0, "ubicacion": "no encontrado"})
        continue
    est, mejor, top, xy = res
    lon, lat = net.convertXY2LonLat(*xy)
    filas.append({"tcs": r.tcs, "nodos_red": " ".join(n.getID() for n in top) if est == "ubicado" else "",
                  "tenia_semaforo": any(n.getType() == "traffic_light" for n in top) if est == "ubicado" else "",
                  "coincidencias": mejor, "ubicacion": est, "lat": round(lat, 6), "lon": round(lon, 6)})
ub = pd.DataFrame(filas)


def cercanos(lat, lon, radio, filtro=lambda n: True):
    x, y = net.convertLonLat2XY(lon, lat)
    d = [(np.hypot(n.getCoord()[0] - x, n.getCoord()[1] - y), n) for n, _ in nodos if filtro(n)]
    return sorted([p for p in d if p[0] < radio], key=lambda p: p[0])


# Reguladores del tranvía (KML de la DGM): su ubicación exacta reemplaza a la búsqueda por nombre. Para cada punto se
# toma el cruce de la red más cercano (< 50 m) por el que pasan los rieles.
def con_riel(n):
    return any(e.getType() == "railway.tram" for e in n.getIncoming())


reg = pd.read_csv(BASE / "datos" / "scats" / "reguladores_tranvia.csv", dtype={"tcs": str})
for tcs, g in reg.groupby("tcs"):
    top = [c[0][1] for c in (cercanos(r.lat, r.lon, 50, con_riel) for r in g.itertuples()) if c]
    if not top:
        continue
    xy = np.mean([n.getCoord() for n in top], axis=0)
    lon, lat = net.convertXY2LonLat(*xy)
    ub = ub[ub.tcs != tcs]
    ub = pd.concat([ub, pd.DataFrame([{"tcs": tcs, "nodos_red": " ".join(sorted({n.getID() for n in top})),
                                       "tenia_semaforo": any(n.getType() == "traffic_light" for n in top),
                                       "coincidencias": 0, "ubicacion": "ubicado", "metodo": "coordenadas KML",
                                       "lat": round(lat, 6), "lon": round(lon, 6)}])])
ub["metodo"] = ub.get("metodo", pd.Series(index=ub.index, dtype=object)).fillna("nombres de calles")
sc = sc.merge(ub, on="tcs", how="left")

# Intersecciones conflictivas (KML de la DGM) con tiempos de fase en hora pico: cruces de la red a menos de 60 m.
conf = pd.read_csv(BASE / "datos" / "scats" / "intersecciones_conflictivas.csv")
conf_fases = pd.read_csv(BASE / "datos" / "scats" / "intersecciones_conflictivas_fases.csv")
conf = conf[conf.id.isin(conf_fases.id)].copy()
conf["nodos_red"] = [" ".join(c[1].getID() for c in cercanos(r.lat, r.lon, 60)) for r in conf.itertuples()]
nuevos_conf = []
for r in conf.itertuples():
    cand = cercanos(r.lat, r.lon, 60)
    if cand and not any(c[1].getType() == "traffic_light" for c in cand):   # ninguno tenía semáforo
        nuevos_conf.append(max(cand, key=lambda c: len(c[1].getIncoming()))[1].getID())
print("ubicación de los cruces SCATS en la red:")
print(sc.ubicacion.str.replace(r" \(.*\)", "", regex=True).value_counts().to_string())
ok = sc.ubicacion == "ubicado"
nuevos = sorted({n for r in sc[ok & (sc.tenia_semaforo == False)].itertuples()  # noqa: E712
                 for n in r.nodos_red.split()})
print(f"ubicados que en OSM no tenían semáforo: {(ok & (sc.tenia_semaforo == False)).sum()} cruces "  # noqa: E712
      f"({len(nuevos)} nodos de la red)")
print(f"ubicados por coordenadas (reguladores del tranvía): {(ok & (sc.metodo == 'coordenadas KML')).sum()} | "
      f"intersecciones conflictivas con tiempos: {len(conf)} (sin ningún cruce a < 60 m: "
      f"{(conf.nodos_red == '').sum()}; sin semáforo en OSM: {len(nuevos_conf)})")
nuevos = sorted(set(nuevos) | set(nuevos_conf))

# ----------------------------------------------------------------------------- 2. red v2s con esos semáforos
env = dict(os.environ, SUMO_HOME=sumo.SUMO_HOME)
lista = SIM / "red" / ("nodos_semaforo_scats_v1.txt" if V1 else "nodos_semaforo_scats.txt")
lista.write_text(",".join(nuevos))
rc = subprocess.run([str(Path(sumo.SUMO_HOME) / "bin" / "netconvert"), "-s", str(NET2), "--tls.set",
                     ",".join(nuevos), "--tls.default-type", "static", "-o", str(NET2S), "--no-warnings"],
                    env=env, capture_output=True, text=True)
if rc.returncode != 0:
    sys.exit(rc.stderr[-2000:])

if MENOS:                                               # red v3bs: los semáforos de una calle que pierde un
    rc = subprocess.run([str(Path(sumo.SUMO_HOME) / "bin" / "netconvert"), "-s", str(NET2S), "-e",   # carril se
                         str(EDG), "-o", str(NET3BS), "--no-warnings"],  # rehacen
                        env=env, capture_output=True, text=True)
    if rc.returncode != 0:
        sys.exit(rc.stderr[-2000:])

# ----------------------------------------------------------------------------- 3. programas "scats"
net = sumolib.net.readNet(str(NET3BS if MENOS else NET2S), withPrograms=True)
tls = {tl.getID(): tl for tl in net.getTrafficLights()}
nodo_tl = {}
for tid, tl in tls.items():
    for conns in tl.getLinks().values():
        for (a, _, _) in conns:
            nodo_tl[a.getEdge().getToNode().getID()] = tid


def fases_scats(txt):
    """'A=39%/51, B=61%/79' -> [51, 79] (segundos por fase, en orden)."""
    return [float(m.group(2)) for m in re.finditer(r"([A-G])=[\d.]+(?:%|s)?/([\d.]+)", txt)]


escritos, sin_plan, distinto, por_nombre = 0, 0, 0, 0
plan = {}          # semáforo de la red -> (ciclo, segundos por fase, calles de cada fase o None, fuente)
sc["tls_sumo"] = ""
for i, r in sc[ok].iterrows():
    tids = sorted({nodo_tl[n] for n in r.nodos_red.split() if n in nodo_tl})
    sc.at[i, "tls_sumo"] = " ".join(tids)
    ciclo = pd.to_numeric(re.sub(r"\D", "", r.ciclo_s) or np.nan, errors="coerce")
    seg = fases_scats(r.fases_plan)
    if np.isnan(ciclo) or not seg:
        sin_plan += 1
        continue
    for tid in tids:
        plan.setdefault(tid, (ciclo, seg, None, f"SCATS {r.tcs}"))
# los tiempos de hora pico de las intersecciones conflictivas reemplazan a los de SCATS (capturas de media mañana)
for r in conf.itertuples():
    fs = conf_fases[conf_fases.id == r.id].sort_values("fase")
    for tid in sorted({nodo_tl[n] for n in r.nodos_red.split() if n in nodo_tl}):
        plan[tid] = (fs.segundos.sum(), list(fs.segundos.astype(float)), list(fs.movimiento), f"DGM hora pico {r.id}")


def asignar_por_nombre(movs, seg_m, verdes, fases, links):
    """reparto del verde (fase de la red -> proporción) según la calle que nombra cada fase de la DGM."""
    pts = {}
    for m, mov in enumerate(movs):
        calle = palabras(re.split(r"\s(?:giro|sur|norte|este|oeste|todo)\b", norm(mov))[0])
        for k in verdes:                                 # conexiones en verde que salen de esa calle
            pts[m, k] = sum(1 for j, c in enumerate(fases[k].state) if c in "Gg" and calle and links.get(j)
                            and coincide(calle, links[j][0][0].getEdge().getName(), True))
    # cada fase de la red toma la fase de la DGM de la calle a la que más verde da; si varias fases de la red toman la
    # misma, se reparten sus segundos. Las que no coinciden con ninguna calle mantienen su duración de la red.
    dom = {k: max(range(len(movs)), key=lambda m: pts[m, k]) for k in verdes if max(pts[m, k] for m in range(len(movs)))}
    if len(set(dom.values())) < len(movs) / 2:
        return None
    peso = {k: seg_m[dom[k]] / sum(1 for x in dom.values() if x == dom[k]) if k in dom else fases[k].duration
            for k in verdes}
    return {k: p / sum(peso.values()) for k, p in peso.items()}


fuente = {}
with open(ADD, "w", encoding="utf-8") as f:
    f.write("<additional>\n")
    for tid, (ciclo, seg, movs, fte) in sorted(plan.items()):
        tl = tls[tid]
        fases = list(tl.getPrograms().values())[0].getPhases()
        links = tl.getLinks()
        verdes = [k for k, ph in enumerate(fases) if ("G" in ph.state or "g" in ph.state) and "y" not in ph.state]
        fijas = sum(ph.duration for k, ph in enumerate(fases) if k not in verdes)
        disponible = max(ciclo - fijas, 5 * len(verdes))
        prop = asignar_por_nombre(movs, seg, verdes, fases, links) if movs else None
        if prop:
            por_nombre += 1
        elif len(seg) == len(verdes):
            # solo cuentan los carriles de calle: en los cruces del tranvía la fase larga de SCATS es la de la calle y
            # la corta es el paso del tranvía (que además tiene siempre verde por el programa "tranvia")
            carr = {k: sum(1 for j, c in enumerate(fases[k].state) if c in "Gg" for (a, _, _) in links.get(j, [])
                           if not a.getEdge().getType().startswith("railway")) for k in verdes}
            orden_red = sorted(verdes, key=lambda k: carr[k], reverse=True)
            orden_sc = sorted(range(len(seg)), key=lambda k: seg[k], reverse=True)
            prop = {orden_red[j]: seg[orden_sc[j]] / sum(seg) for j in range(len(seg))}
        else:
            distinto += 1
            tot = sum(fases[k].duration for k in verdes)
            prop = {k: fases[k].duration / tot for k in verdes}
        fuente[tid] = fte
        f.write(f'  <tlLogic id="{tid}" programID="scats" offset="0" type="static">\n')
        for k, ph in enumerate(fases):
            dur = max(5.0, round(disponible * prop[k])) if k in prop else ph.duration
            f.write(f'    <phase duration="{dur:.0f}" state="{ph.state}"/>\n')
        f.write("  </tlLogic>\n")
        escritos += 1
    f.write("</additional>\n")
if not MENOS and not V1:
    sc.to_csv(BASE / "datos" / "scats" / "scats_ubicados.csv", index=False, encoding="utf-8-sig")
print(f"programas SCATS escritos: {escritos} semáforos de la red | ubicados sin plan en la captura: {sin_plan} | "
      f"con distinto número de fases (reparto proporcional): {distinto}")
dgm = sorted(t for t, v in fuente.items() if v.startswith("DGM"))
print(f"con tiempos de hora pico de la DGM: {len(dgm)} semáforos ({len({fuente[t] for t in dgm})} intersecciones; "
      f"fases emparejadas por el nombre de la calle: {por_nombre})")
pd.DataFrame(sorted(fuente.items()), columns=["tls_sumo", "fuente"]).to_csv(
    BASE / "datos" / "scats" / (f"programas_fuente_v3b{VAR}.csv" if MENOS else "programas_fuente_v1.csv" if V1 else "programas_fuente.csv"), index=False, encoding="utf-8-sig")
print(f"semáforos en la red: v2 {sum(1 for _ in sumolib.net.readNet(str(NET2)).getTrafficLights())} -> v2s {len(tls)}")
