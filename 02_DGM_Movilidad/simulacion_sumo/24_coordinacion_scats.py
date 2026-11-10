"""
Coordinación de los semáforos de SCATS (ondas verdes) a partir del enlace de cada captura.

Base: cada captura de SCATS trae el campo "link", p. ej. Vega Muñoz y General Torres (TCS 7): "-12, 0 B 6" = el cruce
está enlazado con el TCS 6 con un desfase de -12 s. 153 de 173 capturas tienen enlace. Hasta ahora los programas de
13_semaforos_scats.py arrancaban todos a la vez (offset 0), es decir, sin coordinación.

Convención (comprobada con los datos, no ajustada): inicio del verde de la calle común en el cruce local = inicio del
verde de esa calle en el cruce enlazado + desfase. En los dos ejes de un solo sentido del centro esto da una onda verde
en el sentido del tráfico: en la Vega Muñoz (circula de este a oeste) cada cruce arranca 12 s antes que el siguiente
hacia el oeste; en la Gaspar Sangurima (de oeste a este), 12 s después.
Los cruces enlazados (subsistemas "married") funcionan en SCATS con un ciclo común: el ciclo de cada grupo es el más
frecuente del grupo (119 o 120 s en las capturas) y la diferencia se descuenta de la fase verde más larga.
Desfase en SUMO (comprobado con TraCI): la fase k empieza en t = offset + inicio_k (módulo el ciclo).

Con "fases" (30-10-2026) se corrigen además los 43 semáforos de SCATS en los que la red tiene otro número de fases que
la captura (13_semaforos_scats.py les dejaba el reparto estándar; p. ej. Av. España y J. de Olmedo: 12 % de verde para
la Av. España en vez del 42 % de SCATS). Las fases de la red se agrupan por la calle a la que dan verde (la de más
carriles primero) y cada grupo toma una fase de SCATS en orden de duración; si SCATS tiene más fases que calles, la
fase sobrante (p. ej. "B=15s", fija) es exclusiva (peatonal) y queda como una fase en rojo para los vehículos; si la red
tiene más calles que fases de SCATS, las calles menores comparten la fase de SCATS más corta. En los cruces del tranvía
no se agrega la fase en rojo: allí la fase sobrante es la del tranvía, que ya tiene prioridad.

Entrada: datos/scats/scats_ubicados.csv, datos/scats/programas_fuente.csv, red/semaforos_scats.add.xml, red v2s_vel
Salida:  red/semaforos_scats_coord.add.xml (o _coord_fases con "fases") y datos/scats/coordinacion_scats.csv
Uso:     py simulacion_sumo/24_coordinacion_scats.py [fases]
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd
import sumo

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
BASE = SIM.parent
FASES = "fases" in sys.argv
# redes de los escenarios con carril bus ("v3b", con "2b" para el focalizado) y la red sin avenidas a 2 carriles ("v1"):
# sus semáforos se rehacen al quitar carriles, así que cada una necesita su propio archivo coordinado
VAR = "_2b" if "2b" in sys.argv else ""
RED, PREFIJO = (("v2s_vel", "semaforos_scats"), ("v1s_vel", "semaforos_scats_v1"))["v1" in sys.argv]
if "v3b" in sys.argv:
    RED, PREFIJO = f"v3bs{VAR}_vel_menos_carril", f"semaforos_scats_v3b{VAR}"
ENTRADA = SIM / "red" / f"{PREFIJO}.add.xml"
SALIDA = SIM / "red" / f"{PREFIJO}_coord{'_fases' if FASES else ''}.add.xml"
FUENTE = BASE / "datos" / "scats" / f"programas_fuente{PREFIJO[len('semaforos_scats'):]}.csv"

net = sumolib.net.readNet(str(SIM / "red" / f"cuenca_piloto_{RED}.net.xml"))
fuente = dict(pd.read_csv(FUENTE, dtype=str).values)
prog = {t.id: [(float(p.duration), p.state) for p in t.phase] for t in sumolib.xml.parse(str(ENTRADA), "tlLogic")}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", s)


# ----------------------------------------------------------------------------- fases de SCATS que no coincidían
def es_verde(st):
    return ("G" in st or "g" in st) and "y" not in st


def corregir_fases(tid, ciclo, seg):
    tl = net.getTLS(tid)
    links = tl.getLinks()
    ph = prog[tid]
    verdes = [k for k, (_, st) in enumerate(ph) if es_verde(st)]
    calle_de, carriles = {}, Counter()
    for k in verdes:
        c = Counter(norm(links[j][0][0].getEdge().getName()) or links[j][0][0].getEdge().getID()
                    for j, ch in enumerate(ph[k][1]) if ch in "Gg" and j in links
                    and not links[j][0][0].getEdge().getType().startswith("railway"))
        if c:
            calle_de[k] = c.most_common(1)[0][0]
            carriles[calle_de[k]] += sum(c.values())
    grupos = [s for s, _ in carriles.most_common()]
    if not grupos:
        return False
    seg = sorted(seg, reverse=True)
    peso = {}
    for j, s in enumerate(grupos):
        if j < len(seg) - 1 or len(grupos) <= len(seg):
            peso[s] = seg[j]
        else:                                           # calles menores: comparten la fase de SCATS más corta
            resto = grupos[len(seg) - 1:]
            peso[s] = seg[-1] * carriles[s] / sum(carriles[x] for x in resto)
    rojo = sum(seg[len(grupos):]) if len(seg) > len(grupos) else 0
    # una fase por calle, como en SCATS: verde a la vez para todos los accesos de esa calle (en la red venían en fases
    # separadas); los giros a la izquierda y en U ceden el paso ("g"). Cada fase verde va seguida de 3 s de amarillo.
    n = len(ph[0][1])
    izq = set()
    for j, conns in links.items():
        a, b = conns[0][0].getEdge(), conns[0][1].getEdge()
        c = a.getConnections(b)
        if c and c[0].getDirection() in ("l", "L", "t"):
            izq.add(j)
    disponible = max(ciclo - 3 * len(grupos) - rojo, 5 * len(grupos))
    total = sum(peso.values())
    nuevo = []
    for s in grupos:
        verde_j = {j for k in verdes if calle_de.get(k) == s for j, ch in enumerate(ph[k][1]) if ch in "Gg"}
        # el riel (tranvía) conserva su verde solo en las fases donde ya lo tenía; el programa "tranvia" lo prioriza
        st = "".join(("g" if j in izq else "G") if j in verde_j else "r" for j in range(n))
        nuevo.append((max(5.0, round(disponible * peso[s] / total)), st))
        nuevo.append((3.0, "".join("y" if c in "Gg" else "r" for c in st)))
    if rojo:
        nuevo.append((round(rojo), "r" * n))
    prog[tid] = nuevo
    return True


corregidos = 0
if FASES:
    capt = pd.read_csv(BASE / "datos" / "scats" / "scats_ubicados.csv", dtype=str).set_index("tcs")
    for tid, f in fuente.items():
        if not f.startswith("SCATS") or tid not in prog:
            continue
        r = capt.loc[f.split()[1]]
        seg = [float(m.group(2)) for m in re.finditer(r"([A-G])=[\d.]+(?:%|s)?/([\d.]+)", str(r.fases_plan))]
        ciclo = pd.to_numeric(re.sub(r"\D", "", str(r.ciclo_s)) or "nan", errors="coerce")
        if seg and ciclo == ciclo and sum(1 for _, st in prog[tid] if es_verde(st)) != len(seg):
            corregidos += corregir_fases(tid, ciclo, seg)
    print(f"semáforos de SCATS con fases corregidas: {corregidos}")


def calles(nombre):
    return {" ".join(w for w in norm(c).split() if w not in ("av", "avenida", "calle")) for c in str(nombre).split(",")}


sc = pd.read_csv(BASE / "datos" / "scats" / "scats_ubicados.csv", dtype=str)
sc = sc[sc.ubicacion == "ubicado"].copy()
# semáforos de cada captura en esta red (según programas_fuente de la red)
tls_de = {}
for t, f in fuente.items():
    if f.startswith("SCATS"):
        tls_de.setdefault(f.split()[1], []).append(t)
sc["tls"] = sc.tcs.map(lambda c: tls_de.get(c, []))
sc = sc[sc.tls.str.len() > 0]
# solo programas de SCATS (las intersecciones conflictivas usan los tiempos de hora pico de la DGM, sin enlace)
sc = sc[sc.tls.apply(lambda ts: all(fuente.get(t, "").startswith("SCATS") and t in prog for t in ts))]
sitio = sc.set_index("tcs")
enlace = {}
for r in sc.itertuples():
    m = re.match(r"\s*(-?\d+)\s*,\s*-?\d+\s*([A-G])\s+(\d+)", str(r.link))
    if m and m.group(3) in sitio.index:
        enlace[r.tcs] = (int(m.group(1)), m.group(3))


def fase_calle(tid, calle):
    """índice de la fase verde de la red que más conexiones da a la calle (por nombre de la calle de llegada)."""
    tl = net.getTLS(tid)
    links = tl.getLinks()
    mejor, k_mejor = 0, None
    for k, (_, st) in enumerate(prog[tid]):
        if "y" in st:
            continue
        n = sum(1 for j, c in enumerate(st) if c in "Gg" and j in links
                and calle and calle in norm(links[j][0][0].getEdge().getName()))
        if n > mejor:
            mejor, k_mejor = n, k
    return k_mejor


def inicio(tid, k):
    return sum(d for d, _ in prog[tid][:k])


# ----------------------------------------------------------------------------- ciclo común por grupo enlazado
padre = {t: t for t in sitio.index}


def raiz(t):
    while padre[t] != t:
        padre[t] = padre[padre[t]]
        t = padre[t]
    return t


for a, (_, b) in enlace.items():
    padre[raiz(a)] = raiz(b)
grupos = {}
for t in sitio.index:
    grupos.setdefault(raiz(t), []).append(t)
for miembros in grupos.values():
    if len(miembros) < 2:
        continue
    ciclos = [round(sum(d for d, _ in prog[sitio.loc[t, "tls"][0]])) for t in miembros]
    comun = Counter(ciclos).most_common(1)[0][0]
    for t in miembros:
        for tid in sitio.loc[t, "tls"]:
            ph = prog[tid]
            dif = comun - sum(d for d, _ in ph)
            if dif:
                k = max((k for k, (_, st) in enumerate(ph) if "y" not in st), key=lambda k: ph[k][0])
                ph[k] = (ph[k][0] + dif, ph[k][1])

# ----------------------------------------------------------------------------- desfases
offset, filas = {}, []


def resolver(t, visitados=()):
    """desfase del sitio t (segundos) siguiendo su enlace; las raíces y los ciclos de enlaces quedan en 0."""
    if t in offset:
        return offset[t]
    if t not in enlace or t in visitados:
        offset[t] = 0.0
        return 0.0
    x, otro = enlace[t]
    comun = calles(sitio.loc[t, "nombre"]) & calles(sitio.loc[otro, "nombre"])
    calle = max(comun, key=len) if comun else ""
    tid, tid_o = sitio.loc[t, "tls"][0], sitio.loc[otro, "tls"][0]
    k, k_o = fase_calle(tid, calle), fase_calle(tid_o, calle)
    off_o = resolver(otro, visitados + (t,))
    if k is None or k_o is None:
        offset[t] = 0.0
        filas.append({"tcs": t, "enlazado_con": otro, "desfase_scats_s": x, "calle_comun": calle, "aplicado": False})
        return 0.0
    ciclo = sum(d for d, _ in prog[tid])
    # offset_t + inicio_t(k) = offset_o + inicio_o(k_o) + x
    offset[t] = (off_o + inicio(tid_o, k_o) + x - inicio(tid, k)) % ciclo
    filas.append({"tcs": t, "enlazado_con": otro, "desfase_scats_s": x, "calle_comun": calle, "aplicado": True,
                  "offset_sumo_s": round(offset[t])})
    return offset[t]


for t in sitio.index:
    resolver(t)

off_tls = {tid: offset[t] for t in sitio.index for tid in sitio.loc[t, "tls"]}
with open(SALIDA, "w", encoding="utf-8") as f:
    f.write("<additional>\n")
    for tid, ph in prog.items():
        f.write(f'  <tlLogic id="{tid}" programID="scats" offset="{off_tls.get(tid, 0):.0f}" type="static">\n')
        for d, st in ph:
            f.write(f'    <phase duration="{d:.0f}" state="{st}"/>\n')
        f.write("  </tlLogic>\n")
    f.write("</additional>\n")
t = pd.DataFrame(filas)
t.to_csv(BASE / "datos" / "scats" / "coordinacion_scats.csv", index=False, encoding="utf-8-sig")
print(f"enlaces en las capturas ubicadas: {len(enlace)}; desfases aplicados: {int(t.aplicado.sum())}; "
      f"sin calle común en la red: {int((~t.aplicado).sum())}; grupos con ciclo común: "
      f"{sum(1 for g in grupos.values() if len(g) > 1)}")
print(f"salida: {SALIDA}")
