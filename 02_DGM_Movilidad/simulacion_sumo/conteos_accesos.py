"""
Conteos vehiculares 2023 por ACCESO de interseccion, ubicados en las aristas de la red SUMO.

Cada interseccion del portal tiene un diagrama (datos/portal/diagramas/NN_c.png) donde la letra (A, B, C...) es un
acceso y el numero el giro (1 recto, 2 izquierda, 3 derecha, U retorno). Sumando todos los giros de una letra se
obtiene el volumen que ENTRA por ese acceso, que se compara con los vehiculos que entran a la arista de la red que
llega al cruce por esa calle y en ese sentido.

ACCESOS: transcrito a mano de los diagramas. Rumbo = direccion hacia donde circula el vehiculo al llegar al cruce
(grados desde el norte, en sentido horario). Se omiten las intersecciones perifericas (fuera de la red piloto o
redondeles) y Puente Fabian Alarcon (sin diagrama).
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import glob
import re
import unicodedata

import numpy as np
import pandas as pd

#       nombre en el CSV                          (calle 1, calle 2)          {acceso: (rumbo, calle del acceso)}
ACCESOS = {
    "Av 24 de Mayo y Cuzco":                  (("24 de mayo", "cuzco"),        {"A": (70, "24 de mayo"), "B": (350, "cuzco"), "C": (250, "24 de mayo")}),
    "SEBASTIAN DE BENALCAZAR Y AV ESPAÑA":    (("benalcazar", "espana"),       {"A": (140, "benalcazar"), "B": (320, "benalcazar"), "C": (235, "espana"), "D": (55, "espana")}),
    "Miguel Velez Y Mariscal Sucre":          (("velez", "sucre"),             {"A": (110, "sucre")}),
    "Miguel Velez y Simon Bolivar":           (("velez", "bolivar"),           {"A": (10, "velez"), "B": (280, "bolivar")}),
    "Miguel Velez y Mariscal Lamar":          (("velez", "lamar"),             {"A": (10, "velez"), "B": (280, "lamar")}),
    "Av Miguel Velez y Sangurima":            (("velez", "sangurima"),         {"A": (105, "sangurima"), "B": (10, "velez")}),
    "MIGUEL VELEZ Y PIO BRAVO":               (("velez", "pio bravo"),         {"A": (10, "velez")}),
    "Av Rafael M Arizaga y Miguel Velez":     (("arizaga", "velez"),           {"A": (260, "arizaga"), "B": (345, "velez")}),
    "SEBASTIAN DE BENALCAZAR Y DEL CHORRO":   (("benalcazar", "chorro"),       {"A": (135, "benalcazar"), "B": (315, "benalcazar"), "C": (240, "chorro")}),
    "LUIS CORDERO Y GRAN COLOMBIA":           (("=luis cordero", "gran colombia"), {"A": (105, "gran colombia"), "B": (10, "=luis cordero")}),
    "Av. Tomas Ordoñez y Honorato Vazquez":   (("ordonez", "vazquez"),         {"A": (290, "vazquez"), "B": (190, "ordonez")}),
    "CALLE VIEJA Y ELIA LIUT":                (("calle vieja", "liut"),        {"A": (45, "calle vieja"), "B": (315, "liut"), "C": (225, "calle vieja")}),
    "General Artigas y Gabriela Mistral":     (("artigas", "mistral"),         {"A": (340, "mistral"), "B": (260, "alegre")}),
    "Av Remigio Crespo y Lorenzo Piedra":     (("remigio crespo", "piedra"),   {"A": (145, "remigio crespo"), "B": (325, "remigio crespo"), "C": (225, "piedra")}),
    "AV ESPAÑA Y CHAPETONES":                 (("espana", "chapetones"),       {"A": (235, "espana")}),
    "AV. AMERICAS Y LOS LADEROS":             (("americas", "laderas"),        {"A": (250, "americas"), "B": (70, "americas"), "C": (350, "laderas")}),
    "MANUELA CAÑIZARES Y FRANCISCO ASCASUBI":  (("canizares", "ascazubi"),     {"A": (180, "canizares"), "B": (250, "ascazubi"), "C": (0, "canizares")}),
}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", s)


def conteos_por_acceso(base, hora, clase="LIVIANOS"):
    """vehiculos por hora de una clase (LIVIANOS, BUSES, CAMIONES) que entran por cada acceso (suma de sus giros)."""
    c = pd.read_csv(glob.glob(str(base / "datos" / "portal" / "gadcuenca_conteovehicular*.csv"))[0],
                    sep=None, engine="python", encoding="latin-1")
    c.columns = [x.strip() for x in c.columns]
    c["DIRECCION"] = c.DIRECCION.str.strip()
    c["hora"] = pd.to_numeric(c["HORA INICIO"].astype(str).str.extract(r"(\d{1,2})\s*:")[0], errors="coerce")
    c = c[c.hora == hora]
    filas = []
    for col in c.columns:
        if not col.startswith(clase):
            continue
        m = re.match(rf"{clase} ([A-G])\d", col) or re.match(rf"{clase} GIRO EN U ([A-G])$", col)
        if m is None:                                   # "GIRO EN U" sin letra: acceso ambiguo, se omite
            continue
        v = pd.to_numeric(c[col], errors="coerce").fillna(0)
        filas.append(pd.DataFrame({"interseccion": c.DIRECCION, "acceso": m.group(1), "vehiculos": v}))
    t = pd.concat(filas).groupby(["interseccion", "acceso"]).vehiculos.sum()
    return t[t > 0]


def coincide(clave, nombre):
    """'=texto' exige el nombre exacto; 'texto' basta con que aparezca dentro del nombre."""
    return nombre.strip() == clave[1:] if clave.startswith("=") else clave in nombre


def rumbo(p, q):
    return np.degrees(np.arctan2(q[0] - p[0], q[1] - p[1])) % 360


def ubicar_accesos(net, radio=60):
    """{(interseccion, acceso): arista} buscando el nodo donde se cruzan ambas calles y, entre las aristas que
    llegan a ese cruce por la calle del acceso, la de rumbo mas parecido al del diagrama."""
    aristas = [e for e in net.getEdges() if e.getFunction() != "internal" and e.allows("passenger")]
    nombre = {e.getID(): norm(e.getName()) for e in aristas}
    res, notas = {}, []
    for inter, ((c1, c2), acc) in ACCESOS.items():
        nodos = [n for n in net.getNodes()
                 if any(coincide(c1, nombre.get(e.getID(), "")) for e in n.getIncoming() + n.getOutgoing())
                 and any(coincide(c2, nombre.get(e.getID(), "")) for e in n.getIncoming() + n.getOutgoing())]
        if not nodos:
            notas.append(f"{inter}: no se encontro el cruce '{c1}' x '{c2}'")
            continue
        # si hay varios nodos (avenidas con parterre), se usa su centro y todos los nodos cercanos
        xy = np.mean([n.getCoord() for n in nodos], axis=0)
        if max(np.hypot(*(np.array(n.getCoord()) - xy)) for n in nodos) > 150:
            notas.append(f"{inter}: cruce ambiguo ({len(nodos)} nodos dispersos)")
            continue
        cerca = [n for n in net.getNodes() if np.hypot(*(np.array(n.getCoord()) - xy)) < radio]
        for letra, (rb, calle) in acc.items():
            cand = []
            for n in cerca:
                for e in n.getIncoming():
                    if e.getID() in nombre and coincide(calle, nombre[e.getID()]):
                        s = e.getShape()
                        d = abs((rumbo(s[-2], s[-1]) - rb + 180) % 360 - 180)
                        # el acceso es la arista que viene de FUERA del cruce (su origen esta lejos del centro)
                        afuera = np.hypot(*(np.array(e.getFromNode().getCoord()) - xy)) >= radio * 0.5
                        cand.append((not afuera, d, e.getID()))
            cand = [x for x in cand if x[1] <= 45]
            if not cand:
                notas.append(f"{inter} {letra}: sin arista de '{calle}' con rumbo {rb}")
                continue
            res[(inter, letra)] = min(cand)[2]
    return res, notas
