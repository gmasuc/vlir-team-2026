"""
Validación con tiempos de viaje reales: 20 trayectos en auto en la hora pico de la mañana.

Entrada: pares de cruces de calles (TRAYECTOS, abajo), ubicados en la red por el nombre de sus calles; el tiempo de
         viaje simulado de cada tramo de calle entre 7:00 y 8:00 (aristas_todos.xml) de la base vigente y de la candidata.
Proceso: para cada trayecto se busca el camino más rápido según los tiempos simulados (como hace un navegador) y se
         suma su tiempo. Para los tramos sin vehículos simulados se usa largo ÷ velocidad máxima.
Salida:  simulacion_sumo/validacion_tiempos/trayectos_para_llenar.xlsx (sin los tiempos simulados, para no influir
         al anotar) y trayectos_modelo.xlsx (con ellos). La primera trae el enlace de Google Maps de cada trayecto y dos
         columnas vacías para anotar el tiempo que da Google Maps («salir a las 7:30» de un martes, rango mín.–máx.).
         Con esas columnas llenas, `py simulacion_sumo/20_tiempos_viaje.py comparar` calcula el ajuste de cada modelo.

Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import heapq
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import sumo

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
sys.path.insert(0, str(SIM))
from conteos_accesos import norm  # noqa: E402

OUT = SIM / "validacion_tiempos"
OUT.mkdir(exist_ok=True)
MODELOS = {"base vigente": ("calibrada_bahia_reruteo_scats", "cuenca_piloto_v2s.net.xml"),
           "candidata": ("calibrada_bahia_reruteo_scats_vel_tlsflow_p25", "cuenca_piloto_v2s_vel.net.xml")}
PUNTOS = {   # cruce = (calle 1, calle 2), por palabras que deben aparecer en el nombre de la calle
    "a": ("americas", "carlos arizaga vega"), "b": ("americas", "1 de mayo"), "c": ("espana", "benalcazar"),
    "d": ("simon bolivar", "benigno malo"), "e": ("12 de abril", "solano"), "f": ("max uhle", "pumapungo"),
    "g": ("24 de mayo", "cuzco"), "h": ("loja", "don bosco"), "i": ("unidad nacional", "12 de abril"),
    "j": ("hurtado de mendoza", "los andes"), "k": ("americas", "don bosco"), "l": ("gonzalez suarez", "rayoloma"),
    "m": ("ordonez lasso", "cerezos"), "n": ("1 de mayo", "12 de octubre"),
}
TRAYECTOS = ["ad", "da", "cd", "dc", "be", "eb", "hd", "fd", "df", "ge", "ic", "ci", "ka", "ak", "md", "ne", "jf",
             "lc", "bc", "nf"]


def cruce(net, c1, c2):
    """nodo de la red donde se encuentran dos calles (por palabras del nombre)."""
    cand = []
    for n in net.getNodes():
        nombres = {norm(e.getName()) for e in n.getIncoming() + n.getOutgoing() if e.getName()}
        if any(c1 in x for x in nombres) and any(c2 in x for x in nombres):
            cand.append(n)
    if not cand:
        return None
    return max(cand, key=lambda n: len(n.getIncoming()) + len(n.getOutgoing()))


def tiempos_simulados(carpeta, net):
    t = {}
    for iv in sumolib.xml.parse(str(SIM / "buses" / carpeta / "aristas_todos.xml"), "interval"):
        for e in iv.edge or []:
            if e.traveltime and float(e.entered or 0) > 0:
                t[e.id] = float(e.traveltime)
    return t


def camino_mas_rapido(net, tt, origen, destino):
    """Dijkstra sobre tramos de calle para autos; devuelve (segundos, metros)."""
    destinos = {e.getID() for e in destino.getIncoming() if e.allows("passenger")}
    cola, visto = [], {}
    for e in origen.getOutgoing():
        if e.allows("passenger"):
            c = tt.get(e.getID(), e.getLength() / e.getSpeed())
            heapq.heappush(cola, (c, e.getLength(), e.getID()))
    while cola:
        c, m, eid = heapq.heappop(cola)
        if eid in visto:
            continue
        visto[eid] = c
        if eid in destinos:
            return c, m
        for sig in net.getEdge(eid).getOutgoing():
            if sig.allows("passenger") and sig.getID() not in visto:
                heapq.heappush(cola, (c + tt.get(sig.getID(), sig.getLength() / sig.getSpeed()),
                                      m + sig.getLength(), sig.getID()))
    return np.nan, np.nan


def preparar():
    nets = {k: sumolib.net.readNet(str(SIM / "red" / red)) for k, (_, red) in MODELOS.items()}
    net0 = nets["base vigente"]
    nodos = {p: cruce(net0, *c) for p, c in PUNTOS.items()}
    faltan = [p for p, n in nodos.items() if n is None]
    if faltan:
        print("cruces no encontrados:", {p: PUNTOS[p] for p in faltan})
    filas = []
    tts = {k: tiempos_simulados(MODELOS[k][0], nets[k]) for k in MODELOS}
    for i, od in enumerate(TRAYECTOS, 1):
        o, d = nodos.get(od[0]), nodos.get(od[1])
        if o is None or d is None:
            continue
        lo, la = net0.convertXY2LonLat(*o.getCoord())
        ld, lad = net0.convertXY2LonLat(*d.getCoord())
        fila = {"n": i, "origen": " y ".join(PUNTOS[od[0]]).title(), "destino": " y ".join(PUNTOS[od[1]]).title(),
                "origen_lat_lon": f"{la:.6f},{lo:.6f}", "destino_lat_lon": f"{lad:.6f},{ld:.6f}",
                "google_maps": (f"https://www.google.com/maps/dir/?api=1&origin={la:.6f},{lo:.6f}"
                                f"&destination={lad:.6f},{ld:.6f}&travelmode=driving")}
        for k in MODELOS:
            s, m = camino_mas_rapido(nets[k], tts[k], nets[k].getNode(o.getID()), nets[k].getNode(d.getID()))
            fila[f"km_{k}"] = round(m / 1000, 1)
            fila[f"min_{k}"] = round(s / 60, 1)
        fila["google_min_minimo"] = None
        fila["google_min_maximo"] = None
        filas.append(fila)
    t = pd.DataFrame(filas)
    t.to_excel(OUT / "trayectos_modelo.xlsx", index=False)       # con los tiempos simulados (no mirar al llenar)
    t[["n", "origen", "destino", "origen_lat_lon", "destino_lat_lon", "google_maps", "google_min_minimo",
       "google_min_maximo"]].to_excel(OUT / "trayectos_para_llenar.xlsx", index=False)
    print(t.drop(columns=["google_maps"]).to_string(index=False))


def comparar():
    g = pd.read_excel(OUT / "trayectos_para_llenar.xlsx")[["n", "google_min_minimo", "google_min_maximo"]]
    t = pd.read_excel(OUT / "trayectos_modelo.xlsx").drop(columns=["google_min_minimo", "google_min_maximo"])
    t = t.merge(g, on="n").dropna(subset=["google_min_minimo", "google_min_maximo"])
    t["google_medio"] = (t.google_min_minimo + t.google_min_maximo) / 2
    res = {}
    for k in MODELOS:
        s = t[f"min_{k}"]
        res[k] = {"trayectos": len(t), "r": np.corrcoef(s, t.google_medio)[0, 1],
                  "error_medio_%": np.median(100 * (s - t.google_medio).abs() / t.google_medio),
                  "dentro_del_rango_%": 100 * ((s >= t.google_min_minimo) & (s <= t.google_min_maximo)).mean(),
                  "modelo/google_%": 100 * s.sum() / t.google_medio.sum()}
    r = pd.DataFrame(res).T.round(2)
    r.to_csv(OUT / "comparacion.csv", encoding="utf-8-sig")
    print(r.to_string())


# ----------------------------------------------------------------------------- evaluar cualquier corrida
_CACHE = {}


def _red_y_nodos():
    """red v2s (misma topología en todas las variantes, cambian velocidades o carriles) y nodos de los 20 trayectos."""
    if "net" not in _CACHE:
        net = sumolib.net.readNet(str(SIM / "red" / "cuenca_piloto_v2s.net.xml"))
        _CACHE["net"] = net
        _CACHE["nodos"] = {p: cruce(net, *c) for p, c in PUNTOS.items()}
    return _CACHE["net"], _CACHE["nodos"]


def google():
    g = pd.read_excel(OUT / "trayectos_para_llenar.xlsx")[["n", "google_min_minimo", "google_min_maximo"]]
    g["google_medio"] = (g.google_min_minimo + g.google_min_maximo) / 2
    return g


def tiempos_trayectos(carpeta):
    """minutos simulados en auto de los 20 trayectos (7:00-8:00) en una corrida con aristas_todos.xml."""
    net, nodos = _red_y_nodos()
    tt = tiempos_simulados(carpeta, net)
    filas = []
    for i, od in enumerate(TRAYECTOS, 1):
        s, m = camino_mas_rapido(net, tt, nodos[od[0]], nodos[od[1]])
        filas.append({"n": i, "min_modelo": s / 60, "km": m / 1000})
    return pd.DataFrame(filas)


def indicadores_tiempos(t):
    s, g = t.min_modelo, t.google_medio
    return {"trayectos": len(t), "r": np.corrcoef(s, g)[0, 1], "modelo/google_%": 100 * s.sum() / g.sum(),
            "error_medio_%": np.median(100 * (s - g).abs() / g),
            "dentro_del_rango_%": 100 * ((s >= t.google_min_minimo) & (s <= t.google_min_maximo)).mean()}


def evaluar(carpetas):
    """ajuste a Google en los trayectos impares (para elegir) y pares (para comprobar, no se usan al elegir)."""
    g, filas = google(), []
    for c in carpetas:
        t = tiempos_trayectos(c).merge(g, on="n")
        for parte, sel in [("elegir (impares)", t.n % 2 == 1), ("comprobar (pares)", t.n % 2 == 0), ("todos", t.n > 0)]:
            filas.append({"corrida": c, "grupo": parte, **indicadores_tiempos(t[sel])})
    r = pd.DataFrame(filas)
    print(r.round(2).to_string(index=False))
    return r


if __name__ == "__main__":
    if "evaluar" in sys.argv:
        evaluar([a for a in sys.argv[1:] if a != "evaluar"])
    elif "comparar" in sys.argv:
        comparar()
    else:
        preparar()
