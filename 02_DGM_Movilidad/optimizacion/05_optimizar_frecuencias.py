"""
Optimización de las frecuencias de los buses en hora pico (paso 4 del README, primera parte: solo frecuencias).

Variables: intervalo de cada una de las 38 líneas de bus (el mismo en ida y retorno), de un conjunto discreto. El tranvía
           no cambia.
Objetivos (los tres se minimizan; NSGA-II, Deb et al. 2002):
  1. pasajero: tiempo puerta a puerta medio (min) del evaluador rápido (evaluador.py, estrategias óptimas);
  2. tranvía: − subidas al tranvía por hora (más es mejor);
  3. tráfico (indicador provisorio): exposición de los buses a la congestión = Σ líneas buses/h × Σ calles de su
     recorrido (autos que entran a la calle de 7:00 a 8:00 × minutos que tarda el bus en ella), según el modelo
     calibrado de SUMO, relativa a la situación actual (1.00 = hoy). Se reemplazará por un modelo sustituto entrenado
     con corridas de SUMO, y las alternativas finalistas se verifican en SUMO.
Restricciones (≤ 0):
  - flota: buses en circulación en hora pico (Σ 2 × tiempo de recorrido observado / intervalo, Escenario 0) ≤ los de hoy;
  - intervalo de cada línea: no más de MAX_PEOR (5 min) peor que hoy y no mayor a 30 min (o al de hoy, si ya es mayor);
    se cumple por construcción (valores permitidos por línea);
  - equidad: ninguna celda de 500 m empeora su costo generalizado medio en más de MAX_CELDA (5 min).

Uso:  py optimizacion/05_optimizar_frecuencias.py [poblacion] [generaciones] [nombre] [continuar]
      p. ej. prueba: 16 6 prueba;  completa: 100 60 completa
      «continuar» retoma una corrida cortada desde su historial.csv (las generaciones previas se descuentan)
Salida: optimizacion/frecuencias/<nombre>/ (frente.csv, historial.csv, resumen.txt, frente.png)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import sys
import time
from pathlib import Path

import os

import numpy as np
import pandas as pd
import sumo
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.callback import Callback
from pymoo.core.problem import Problem
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.operators.repair.rounding import RoundingRepair
from pymoo.operators.sampling.rnd import IntegerRandomSampling
from pymoo.optimize import minimize

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from evaluador import Evaluador  # noqa: E402

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

POB = int(sys.argv[1]) if len(sys.argv) > 1 else 16
GEN = int(sys.argv[2]) if len(sys.argv) > 2 else 6
NOMBRE = sys.argv[3] if len(sys.argv) > 3 else "prueba"
OUT = AQUI / "frecuencias" / NOMBRE
OUT.mkdir(parents=True, exist_ok=True)
INTERVALOS = [5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 60]
MAX_PEOR, MAX_INT, MAX_CELDA = 5, 30, 5.0


def exposicion_por_ruta(ev):
    """minutos de bus × autos por calle de cada recorrido (por bus), con el modelo calibrado de SUMO."""
    run = AQUI.parent / "simulacion_sumo" / "buses" / "calibrada_bahia_reruteo_scats_vel_coord_fases_sinvueltas_jc"
    autos, tt = {}, {}
    for iv in sumolib.xml.parse(str(run / "aristas_todos.xml"), "interval"):
        for e in iv.edge or []:
            autos[e.id] = float(e.entered or 0)
            tt[e.id] = float(e.traveltime or 0)
    exp = {}
    for r in sumolib.xml.parse(str(run / "buses.rou.xml"), "route"):
        k = r.id[1:].replace("RUTA_TRANVIA", "RUTA TRANVIA").rsplit("_", 1)
        k = "|".join(k)
        exp[k] = sum(autos.get(e, 0) * tt.get(e, 0) / 60 for e in r.edges.split()) / 1000   # miles de auto·min
    return exp


# en Windows los procesos del evaluador vuelven a importar este archivo: todo lo que corre va bajo __main__
if __name__ == "__main__":
    ev = Evaluador()
    lin = ev.lin[ev.lin.modo == "bus"].copy()
    lineas = sorted(lin.linea.unique(), key=lambda x: (len(x), x))
    e0 = pd.read_csv(AQUI.parent / "datos" / "derivados" / "escenario0_lineas_lv.csv", dtype={"linea": str})
    e0 = e0[e0.tipo != "Alargue"].set_index("linea")
    info = lin.groupby("linea").agg(id_ld=("id_ld", list), h0=("intervalo_min", "first"), esc0=("linea_esc0", "first"))
    info = info.loc[lineas]
    info["tr_pico"] = info.esc0.map(e0.tr_pico)
    exp = exposicion_por_ruta(ev)
    info["exposicion"] = info.id_ld.map(lambda ks: sum(exp.get(k, 0) for k in ks))
    # valores permitidos por línea
    permitidos = []
    for l, x in info.iterrows():
        tope = max(MAX_INT, x.h0)
        v = [h for h in INTERVALOS if h <= min(x.h0 + MAX_PEOR, tope)]
        if x.h0 not in v:
            v = sorted(set(v) | {x.h0})
        permitidos.append(v)
    info["permitidos"] = permitidos
    FLOTA0 = float((2 * info.tr_pico / info.h0).sum())
    EXP0 = float((60 / info.h0 * info.exposicion).sum())
    print(f"{len(lineas)} líneas; buses en circulación hoy: {FLOTA0:.0f}", flush=True)


    def intervalos_de(x):
        return {l: info.permitidos.iloc[i][int(x[i])] for i, l in enumerate(lineas)}


    def indicadores(h_linea):
        inter = {k: h for l, h in h_linea.items() for k in info.loc[l, "id_ld"]}
        r = ev.evaluar(intervalos=inter)
        flota = sum(2 * info.loc[l, "tr_pico"] / h for l, h in h_linea.items())
        exposicion = sum(60 / h * info.loc[l, "exposicion"] for l, h in h_linea.items()) / EXP0
        return r, flota, exposicion


    base, _, _ = indicadores(dict(info.h0))
    COSTO0 = base["costo_celda"]
    PUERTA0 = base["indicadores"]["min_puerta_a_puerta"]
    TRAN0 = base["totales"]["subidas_tranvia"]
    print(f"hoy: puerta a puerta {PUERTA0} min, tranvía {TRAN0:.0f} subidas/h", flush=True)
    historial = []


    class Frecuencias(Problem):
        def __init__(self):
            super().__init__(n_var=len(lineas), n_obj=3, n_ieq_constr=2, xl=0,
                             xu=np.array([len(p) - 1 for p in info.permitidos]), vtype=int)

        def _evaluate(self, X, out, *args, **kwargs):
            F, G = [], []
            for x in X:
                h = intervalos_de(x)
                r, flota, expo = indicadores(h)
                t = r["totales"]
                puerta = (t["acceso"] + t["espera"] + t["viaje"] + t["caminar"]) / t["viajes"]
                peor = max((r["costo_celda"].get(c, np.inf) - c0 for c, c0 in COSTO0.items()), default=0)
                F.append([puerta, -t["subidas_tranvia"], expo])
                G.append([flota - FLOTA0, peor - MAX_CELDA])
                historial.append({"puerta_min": puerta, "subidas_tranvia": t["subidas_tranvia"], "exposicion": expo,
                                  "flota": flota, "peor_celda_min": peor, **{f"L{l}": v for l, v in h.items()}})
            out["F"], out["G"] = np.array(F), np.array(G)


    class Avance(Callback):
        def notify(self, algorithm):
            F = algorithm.opt.get("F")
            print(f"generación {algorithm.n_gen}: {len(historial)} evaluaciones; mejor puerta a puerta "
                  f"{F[:, 0].min():.2f} min; más tranvía {-F[:, 1].min():.0f} subidas/h ({time.strftime('%H:%M')})",
                  flush=True)
            pd.DataFrame(historial).to_csv(OUT / "historial.csv", index=False)


    t0 = time.time()
    # la población inicial incluye la situación actual (para que el frente nunca sea peor que hoy)
    x0 = np.array([[p.index(h) for p, h in zip(info.permitidos, info.h0)]])
    muestra = np.vstack([x0, IntegerRandomSampling()(Frecuencias(), POB - 1).get("X")])
    if "continuar" in sys.argv[4:]:
        # retoma una corrida cortada: parte de las mejores alternativas de historial.csv (factibles y no dominadas
        # primero, luego las que menos violan las restricciones) y corre solo las generaciones que faltan
        from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting
        prev = pd.read_csv(OUT / "historial.csv")
        historial.extend(prev.to_dict("records"))
        X = np.array([[info.permitidos.iloc[i].index(v) for i, v in enumerate(fila)]
                      for fila in prev[[f"L{l}" for l in lineas]].to_numpy()])
        F = np.c_[prev.puerta_min, -prev.subidas_tranvia, prev.exposicion]
        cv = np.maximum(prev.flota - FLOTA0, 0) + np.maximum(prev.peor_celda_min - MAX_CELDA, 0)
        X, unicos = np.unique(X, axis=0, return_index=True)
        F, cv = F[unicos], cv.to_numpy()[unicos]
        fact = np.flatnonzero(cv <= 0)
        orden = [fact[i] for frente in NonDominatedSorting().do(F[fact]) for i in frente]
        orden += list(np.flatnonzero(cv > 0)[np.argsort(cv[cv > 0])])
        muestra = X[orden[:POB]]
        hechas = len(prev) // POB
        print(f"continúa: {len(prev)} evaluaciones previas ({hechas} generaciones), faltan {GEN - hechas}", flush=True)
        GEN -= hechas
    alg = NSGA2(pop_size=POB, sampling=muestra,
                crossover=SBX(prob=0.9, eta=15, vtype=float, repair=RoundingRepair()),
                mutation=PM(eta=20, vtype=float, repair=RoundingRepair()), eliminate_duplicates=True)
    res = minimize(Frecuencias(), alg, ("n_gen", GEN), seed=1, callback=Avance(), verbose=False)

    # ----------------------------------------------------------------------------- salidas
    filas = []
    for x, f, g in zip(np.atleast_2d(res.X), np.atleast_2d(res.F), np.atleast_2d(res.G)):
        h = intervalos_de(x)
        filas.append({"puerta_min": round(f[0], 2), "ahorro_min": round(PUERTA0 - f[0], 2),
                      "subidas_tranvia": round(-f[1]), "cambio_tranvia_%": round(100 * (-f[1] / TRAN0 - 1), 1),
                      "exposicion_vs_hoy": round(f[2], 3), "flota": round(g[0] + FLOTA0, 1),
                      "peor_celda_min": round(g[1] + MAX_CELDA, 2),
                      "lineas_que_cambian": sum(h[l] != info.loc[l, "h0"] for l in lineas),
                      **{f"L{l}": h[l] for l in lineas}})
    fr = pd.DataFrame(filas).sort_values("puerta_min")
    fr.to_csv(OUT / "frente.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(historial).to_csv(OUT / "historial.csv", index=False)
    hoy = pd.DataFrame([{"linea": l, "intervalo_hoy": info.loc[l, "h0"], "tr_pico": info.loc[l, "tr_pico"],
                         "exposicion": round(info.loc[l, "exposicion"], 2)} for l in lineas])
    hoy.to_csv(OUT / "lineas_hoy.csv", index=False, encoding="utf-8-sig")
    txt = (f"Población {POB}, generaciones {GEN}, evaluaciones {len(historial)}, {(time.time() - t0) / 60:.0f} min\n"
           f"Hoy: puerta a puerta {PUERTA0} min; tranvía {TRAN0:.0f} subidas/h; buses en circulación {FLOTA0:.0f}\n"
           f"Alternativas en el frente: {len(fr)}\n")
    (OUT / "resumen.txt").write_text(txt, encoding="utf-8")
    print(txt)
    print(fr.iloc[:, :8].to_string(index=False))

    import matplotlib.pyplot as plt  # noqa: E402
    fig, axs = plt.subplots(1, 2, figsize=(12, 5))
    h = pd.DataFrame(historial)
    ok = (h.flota <= FLOTA0 + 1e-6) & (h.peor_celda_min <= MAX_CELDA)
    for ax, (col, et) in zip(axs, [("subidas_tranvia", "Subidas al tranvía por hora"), ("exposicion", "Exposición a la congestión (1 = hoy)")]):
        ax.scatter(h[~ok].puerta_min, h[~ok][col], s=6, c="#ccc", label="no cumple restricciones")
        ax.scatter(h[ok].puerta_min, h[ok][col], s=8, c="#7fa7d1", label="cumple")
        ax.scatter(fr.puerta_min, fr["subidas_tranvia" if col == "subidas_tranvia" else "exposicion_vs_hoy"], s=25,
                   c="#c0392b", label="frente (no dominadas)")
        ax.scatter([PUERTA0], [TRAN0 if col == "subidas_tranvia" else 1.0], marker="*", s=200, c="k", label="hoy")
        ax.set_xlabel("Tiempo puerta a puerta medio (min)")
        ax.set_ylabel(et)
        ax.legend(fontsize=8)
    fig.suptitle(f"Optimización de frecuencias ({NOMBRE}): {len(historial)} alternativas evaluadas")
    fig.tight_layout()
    fig.savefig(OUT / "frente.png", dpi=130)
    ev.cerrar()
