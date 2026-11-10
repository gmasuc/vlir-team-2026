"""
Evaluador rápido de la oferta de transporte público: la asignación por estrategias óptimas de 02_grafo_pasajeros.py,
reescrita para que el optimizador pueda llamarla miles de veces.

Diferencias con asignar_estrategias() (mismo método y mismos resultados):
  - la red se prepara una sola vez (listas de Python, no el grafo de networkx); para probar otra oferta solo cambia la
    frecuencia de las aristas de subida (evaluar(intervalos=...));
  - el bucle interno usa listas y variables locales (sin numpy elemento por elemento, que es lento en Python);
  - los destinos se reparten entre los núcleos del procesador (multiprocessing), porque cada destino es independiente.

Uso como módulo:
    ev = Evaluador()                          # arma el grafo de la situación actual (una vez, ~5 s)
    r = ev.evaluar()                          # situación actual
    r = ev.evaluar(intervalos={"7|Ida": 6.0})  # otra oferta: {id_ld: minutos}
    ev.cerrar()
Uso como script (prueba de velocidad y comparación con 02_grafo_pasajeros.py):
    py optimizacion/evaluador.py [procesos]
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import heapq
import importlib
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
gp = importlib.import_module("02_grafo_pasajeros")
INF = float("inf")
T_VIAJAR, T_SUBIR, T_ACCESO, T_CAMINAR, T_OTRO = 0, 1, 2, 3, 4
_R = None                                      # red de cada proceso (multiprocessing)


def _sin_ahorro_de_energia():
    """Windows 11 manda los procesos en segundo plano a los núcleos de eficiencia y a menor frecuencia («EcoQoS»):
    la misma evaluación tardaba de 3 a 40 s. Se desactiva para este proceso y se sube su prioridad."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class Estado(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]
    k32 = ctypes.windll.kernel32
    yo = k32.GetCurrentProcess()
    e = Estado(1, 1, 0)                        # PROCESS_POWER_THROTTLING_EXECUTION_SPEED: control sí, estado no
    k32.SetProcessInformation(yo, 4, ctypes.byref(e), ctypes.sizeof(e))     # 4 = ProcessPowerThrottling
    k32.SetPriorityClass(yo, 0x8000)           # ABOVE_NORMAL_PRIORITY_CLASS
    k32.SetThreadExecutionState(0x80000000 | 0x00000001)                    # no suspender mientras calcula


def _iniciar(red):
    global _R
    _R = red
    _sin_ahorro_de_energia()


def _destinos(args):
    """estrategias óptimas hacia cada destino del lote; acumula cargas por arista y totales."""
    ids, frec = args
    R = _R
    lote = [R["lotes"][i] for i in ids]
    ini, fin, costo, tipo, real, entran, origenes = R["ini"], R["fin"], R["costo"], R["tipo"], R["real"], R["entran"], R["origenes"]
    n_nodos, n_ar = R["n_nodos"], len(ini)
    flujo = [0.0] * n_ar
    tot = [0.0] * 6
    por_origen = {}                            # nodo de origen -> [viajes, viajes × costo generalizado]                            # viajes, acceso, espera, viaje, caminar, sin_camino
    hpush, hpop = heapq.heappush, heapq.heappop
    for r, demanda in lote:                    # demanda = [(nodo_origen, viajes), ...]
        u = [INF] * n_nodos
        f = [0.0] * n_nodos
        sel = [-1] * n_nodos
        hecho = bytearray(n_ar)
        u[r] = 0.0
        heap = [(costo[k], k) for k in entran[r]]
        heapq.heapify(heap)
        orden = []
        while heap:
            key, k = hpop(heap)
            if hecho[k]:
                continue
            j = fin[k]
            if key != u[j] + costo[k]:
                continue
            hecho[k] = 1
            i = ini[k]
            ui = u[i]
            if ui < key:
                continue
            fa = frec[k]
            fi = f[i]
            if fa == INF:
                u[i] = key
                f[i] = INF
                sel[i] = k
            elif fi == INF:
                continue
            elif fi == 0.0:
                u[i] = 0.5 / fa + key
                f[i] = fa
            else:
                u[i] = (fi * ui + fa * key) / (fi + fa)
                f[i] = fi + fa
            orden.append(k)
            ui = u[i]
            for k2 in entran[i]:
                if not hecho[k2]:
                    hpush(heap, (ui + costo[k2], k2))
        V = [0.0] * n_nodos
        for o, q in demanda:
            if u[o] == INF:
                tot[5] += q
            else:
                V[o] += q
                tot[0] += q
                a = por_origen.setdefault(o, [0.0, 0.0])
                a[0] += q
                a[1] += q * u[o]
        espera_nodos = set()
        for k in reversed(orden):
            i = ini[k]
            Vi = V[i]
            if Vi <= 0.0:
                continue
            fa = frec[k]
            if fa == INF:
                if sel[i] != k:
                    continue
                v = Vi
            else:
                fi = f[i]
                if fi == INF:
                    continue
                v = Vi * fa / fi
                espera_nodos.add(i)
            V[fin[k]] += v
            flujo[k] += v
            t = tipo[k]
            if t == T_VIAJAR:
                tot[3] += v * real[k]
            elif t == T_ACCESO:
                tot[1] += v * costo[k]
            elif t == T_CAMINAR:
                tot[4] += v * costo[k]
        for i in espera_nodos:
            tot[2] += V[i] * 0.5 / f[i]
    return flujo, tot, por_origen


class Evaluador:
    def __init__(self, procesos=None, agrupar_destinos=None):
        lin, par = gp.cargar_oferta()
        fac = gp.factores_sumo(par)
        od = gp.cargar_demanda()
        zon, cel = gp.armar_celdas()
        odc = gp.demanda_celdas(od, cel)
        G = gp.construir_grafo(lin, par, fac)
        gp.conectar_celdas(G, par, cel)
        self.lin, self.par, self.G, self.odc = lin, par, G, odc
        nodos = list(G.nodes)
        idx = {n: i for i, n in enumerate(nodos)}
        ini, fin, costo, tipo, real, lin_k, tramo, espera = [], [], [], [], [], [], [], []
        cod = {"viajar": T_VIAJAR, "subir": T_SUBIR, "acceso": T_ACCESO, "salida": T_ACCESO, "caminar": T_CAMINAR}
        for a, b, e in G.edges(data=True):
            ini.append(idx[a]); fin.append(idx[b]); tipo.append(cod.get(e["tipo"], T_OTRO))
            real.append(float(e.get("min_real", e["w"]))); lin_k.append(e.get("id_ld")); tramo.append(e.get("tramo"))
            espera.append(float(e.get("espera", 0.0)))
            costo.append(gp.PEN_SUBIDA if e["tipo"] == "subir" else float(e["w"]))
        entran = [[] for _ in nodos]
        for k, j in enumerate(fin):
            entran[j].append(k)
        self.lin_k, self.tramo, self.tipo, self.espera0 = lin_k, tramo, tipo, espera
        self.subir = [k for k, t in enumerate(tipo) if t == T_SUBIR]
        # factor de la espera de cada línea (1 + CV²), para recalcular la espera con otro intervalo
        li = lin.set_index("id_ld")
        self.cv2 = {k: 1 + li.loc[k, "cv_intervalo"] ** 2 for k in li.index}
        self.int0 = li.intervalo_min.to_dict()
        # demanda por destino: [(nodo_origen, viajes)]
        m = odc.values
        self.lotes = []
        for jd, d in enumerate(odc.columns):
            r = idx.get(("D", d))
            if r is None:
                continue
            col = m[:, jd]
            dem = [(idx[("O", o)], float(col[io])) for io, o in enumerate(odc.index)
                   if col[io] > 0 and o != d and ("O", o) in idx]
            if dem:
                self.lotes.append((r, dem))
        self.intrazonal = float(np.trace(m))
        self.celda_de = {idx[("O", o)]: o for o in odc.index if ("O", o) in idx}
        _sin_ahorro_de_energia()
        # la demanda viaja a los procesos una sola vez (en la red), no en cada evaluación
        self.red = {"ini": ini, "fin": fin, "costo": costo, "tipo": tipo, "real": real, "entran": entran,
                    "origenes": None, "n_nodos": len(nodos), "lotes": self.lotes}
        self.procesos = procesos or max(1, (os.cpu_count() or 2) - 2)
        self.pool = Pool(self.procesos, initializer=_iniciar, initargs=(self.red,)) if self.procesos > 1 else None
        if self.pool is None:
            _iniciar(self.red)

    def frecuencias(self, intervalos=None):
        """frecuencia efectiva de cada arista: subir = 1 / (intervalo × (1 + CV²)); las demás, infinita."""
        frec = [INF] * len(self.tipo)
        for k in self.subir:
            l = self.lin_k[k]
            h = (intervalos or {}).get(l, self.int0[l])
            frec[k] = 1.0 / (h * self.cv2[l])
        return frec

    def evaluar(self, intervalos=None):
        frec = self.frecuencias(intervalos)
        n = self.procesos * 3
        lotes = [(list(range(i, len(self.lotes), n)), frec) for i in range(n)]
        res = self.pool.map(_destinos, lotes) if self.pool else [_destinos(x) for x in lotes]
        flujo = np.sum([r[0] for r in res], axis=0)
        tot = np.sum([r[1] for r in res], axis=0)
        # costo generalizado medio por celda de origen (minutos; incluye esperas, transbordos y la preferencia por el
        # tranvía): para la restricción de que ningún barrio empeore
        po = {}
        for r in res:
            for o, (q, qc) in r[2].items():
                a = po.setdefault(o, [0.0, 0.0])
                a[0] += q
                a[1] += qc
        costo_celda = {self.celda_de[o]: qc / q for o, (q, qc) in po.items() if q > 0}
        carga, subidas = {}, {}
        sub_tranvia = sub_total = 0.0
        for k, v in enumerate(flujo):
            if v <= 0:
                continue
            t = self.tipo[k]
            if t == T_VIAJAR:
                carga[(self.lin_k[k], self.tramo[k])] = carga.get((self.lin_k[k], self.tramo[k]), 0.0) + v
            elif t == T_SUBIR:
                subidas[self.lin_k[k]] = subidas.get(self.lin_k[k], 0.0) + v
                sub_total += v
                if self.lin_k[k].startswith("RUTA TRANVIA"):
                    sub_tranvia += v
        t = {"viajes": tot[0], "acceso": tot[1], "espera": tot[2], "viaje": tot[3], "caminar": tot[4],
             "sin_camino": tot[5], "subidas": sub_total, "subidas_tranvia": sub_tranvia}
        return {"carga": carga, "subidas": subidas, "totales": t, "costo_celda": costo_celda,
                "indicadores": gp.indicadores_estrategias(t, self.intrazonal)}

    def cerrar(self):
        if self.pool:
            self.pool.close()
            self.pool.join()


if __name__ == "__main__":
    import pandas as pd
    t0 = time.time()
    ev = Evaluador(procesos=int(sys.argv[1]) if len(sys.argv) > 1 else None)
    print(f"preparar: {time.time() - t0:.1f} s; {ev.procesos} procesos; {len(ev.lotes)} destinos")
    for _ in range(3):
        t1 = time.time()
        r = ev.evaluar()
        print(f"evaluar: {time.time() - t1:.2f} s")
    for k, v in r["indicadores"].items():
        print(f"  {k}: {v}")
    # comparación con la versión de 02_grafo_pasajeros.py
    t2 = time.time()
    c0, s0, tot0 = gp.asignar_estrategias(ev.G, ev.odc)
    print(f"versión anterior: {time.time() - t2:.1f} s")
    ind0 = gp.indicadores_estrategias(tot0, ev.intrazonal)
    dif = {k: (ind0[k], r["indicadores"][k]) for k in ind0 if ind0[k] != r["indicadores"][k]}
    print("indicadores distintos:", dif or "ninguno")
    s = pd.DataFrame({"antes": pd.Series(s0), "ahora": pd.Series(r["subidas"])}).fillna(0)
    print(f"subidas por línea: diferencia máxima {(s.antes - s.ahora).abs().max():.4f} pasajeros/h")
    c = pd.DataFrame({"antes": pd.Series(c0), "ahora": pd.Series(r["carga"])}).fillna(0)
    print(f"carga por tramo: diferencia máxima {(c.antes - c.ahora).abs().max():.4f} pasajeros/h")
    # otra oferta: línea 7 cada 6 min en vez de 8
    t3 = time.time()
    r2 = ev.evaluar(intervalos={"7|Ida": 6.0, "7|Retorno": 6.0})
    print(f"línea 7 cada 6 min: {time.time() - t3:.2f} s; puerta a puerta {r2['indicadores']['min_puerta_a_puerta']} min; "
          f"subidas L7 {r['subidas'].get('7|Ida', 0) + r['subidas'].get('7|Retorno', 0):.0f} -> "
          f"{r2['subidas'].get('7|Ida', 0) + r2['subidas'].get('7|Retorno', 0):.0f}")
    ev.cerrar()
