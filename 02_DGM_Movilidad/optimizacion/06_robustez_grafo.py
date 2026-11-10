"""
Prueba de robustez del grafo de pasajeros para la optimización de frecuencias (paso 4 del README).

Las alternativas del frente de Pareto se vuelven a evaluar cambiando los valores inciertos del grafo, uno a la vez. En
cada variante se compara cada alternativa con la situación actual evaluada con esa misma variante. Si las alternativas
siguen siendo mejores que hoy y conservan su orden, la conclusión no depende de esos valores.

Variantes (base = valores adoptados):
  - peso del minuto en tranvía: 0.6 (base), 0.8 y 1.0 [R7];
  - penalización por subida (molestia de transbordar): 5 min (base), 3 y 10 min;
  - irregularidad de los buses: la de SUMO (base) o buses regulares (CV = 0) [R10, R11];
  - distancia máxima a pie hasta la parada: 600 m (base), 400 y 800 m [R9].

Indicadores por alternativa y variante: ahorro de tiempo puerta a puerta frente a hoy (min), cambio de subidas al
tranvía (%), peor empeoramiento de una celda de 500 m (min de costo generalizado; límite 5 min).
Resumen por variante: % de alternativas que siguen ahorrando tiempo, que siguen subiendo el tranvía y que cumplen el
límite por celda; correlación de rangos (Spearman) con la base: si el orden de las alternativas se conserva.

Uso:  py optimizacion/06_robustez_grafo.py [nombre de la corrida]   (por defecto «completa»)
Entrada: optimizacion/frecuencias/<nombre>/frente.csv
Salida: optimizacion/frecuencias/<nombre>/robustez_grafo/ (evaluaciones.csv, resumen.csv, robustez.png)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import importlib
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
gp = importlib.import_module("02_grafo_pasajeros")
from evaluador import Evaluador  # noqa: E402

NOMBRE = sys.argv[1] if len(sys.argv) > 1 else "completa"
CORRIDA = AQUI / "frecuencias" / NOMBRE
OUT = CORRIDA / "robustez_grafo"
MAX_CELDA = 5.0
BASE = {"F_TRANVIA": 0.6, "PEN_SUBIDA": 5.0, "REGULAR": False, "ACCESO_M": 600}
VARIANTES = {
    "base": {},
    "tranvía 0.8": {"F_TRANVIA": 0.8},
    "tranvía 1.0": {"F_TRANVIA": 1.0},
    "transbordo 3 min": {"PEN_SUBIDA": 3.0},
    "transbordo 10 min": {"PEN_SUBIDA": 10.0},
    "buses regulares": {"REGULAR": True},
    "acceso 400 m": {"ACCESO_M": 400},
    "acceso 800 m": {"ACCESO_M": 800},
}


def representativas(fr):
    """la mejor para el pasajero, la mejor para el tranvía y la de compromiso (la más cercana al ideal en los dos
    objetivos normalizados, entre las que no alargan el viaje)."""
    a = fr.puerta_min.idxmin()
    b = fr.subidas_tranvia.idxmax()
    n = fr[fr.ahorro_min >= 0]
    p = (n.puerta_min - fr.puerta_min.min()) / (fr.puerta_min.max() - fr.puerta_min.min())
    t = (fr.subidas_tranvia.max() - n.subidas_tranvia) / (fr.subidas_tranvia.max() - fr.subidas_tranvia.min())
    c = np.hypot(p, t).idxmin()
    return {a: "mejor pasajero", b: "mejor tranvía", c: "compromiso"}


# en Windows los procesos del evaluador vuelven a importar este archivo: todo lo que corre va bajo __main__
if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fr = pd.read_csv(CORRIDA / "frente.csv").reset_index(drop=True)
    cols = [c for c in fr.columns if c.startswith("L")]          # intervalo de cada línea (L1, L2, …, L11B)
    rep = representativas(fr)
    print(f"{len(fr)} alternativas del frente; {len(VARIANTES)} variantes", flush=True)

    filas = []
    for nombre, cambios in VARIANTES.items():
        t0 = time.time()
        for k, v in {**BASE, **cambios}.items():
            setattr(gp, k, v)
        ev = Evaluador()
        id_ld = ev.lin[ev.lin.modo == "bus"].groupby("linea").id_ld.agg(list)
        hoy = ev.evaluar()
        th = hoy["totales"]
        puerta0 = (th["acceso"] + th["espera"] + th["viaje"] + th["caminar"]) / th["viajes"]
        for i, x in fr.iterrows():
            inter = {k: float(x[c]) for c in cols for k in id_ld[c[1:]]}
            r = ev.evaluar(intervalos=inter)
            t = r["totales"]
            puerta = (t["acceso"] + t["espera"] + t["viaje"] + t["caminar"]) / t["viajes"]
            peor = max((r["costo_celda"].get(c, np.inf) - c0 for c, c0 in hoy["costo_celda"].items()), default=0)
            filas.append({"variante": nombre, "alternativa": i, "representativa": rep.get(i, ""),
                          "puerta_hoy": round(puerta0, 3), "puerta_min": round(puerta, 3),
                          "ahorro_min": round(puerta0 - puerta, 3),
                          "tranvia_hoy": round(th["subidas_tranvia"]), "subidas_tranvia": round(t["subidas_tranvia"]),
                          "cambio_tranvia_%": round(100 * (t["subidas_tranvia"] / th["subidas_tranvia"] - 1), 1),
                          "peor_celda_min": round(peor, 2)})
        ev.cerrar()
        print(f"{nombre}: hoy {puerta0:.2f} min, tranvía {th['subidas_tranvia']:.0f} subidas/h "
              f"({(time.time() - t0) / 60:.1f} min)", flush=True)
        pd.DataFrame(filas).to_csv(OUT / "evaluaciones.csv", index=False, encoding="utf-8-sig")

    ev_ = pd.DataFrame(filas)
    b = ev_[ev_.variante == "base"].set_index("alternativa")
    res = []
    for nombre, g in ev_.groupby("variante", sort=False):
        g = g.set_index("alternativa")
        fila = {"variante": nombre, "puerta_hoy_min": g.puerta_hoy.iloc[0], "tranvia_hoy": g.tranvia_hoy.iloc[0],
                "ahorran_tiempo_%": round(100 * (g.ahorro_min > 0).mean()),
                "suben_tranvia_%": round(100 * (g["cambio_tranvia_%"] > 0).mean()),
                "cumplen_celda_%": round(100 * (g.peor_celda_min <= MAX_CELDA).mean()),
                "spearman_puerta": round(g.puerta_min.corr(b.puerta_min, method="spearman"), 2),
                "spearman_tranvia": round(g.subidas_tranvia.corr(b.subidas_tranvia, method="spearman"), 2)}
        for i, et in rep.items():
            fila[f"{et}: ahorro_min"] = g.loc[i, "ahorro_min"]
            fila[f"{et}: tranvía_%"] = g.loc[i, "cambio_tranvia_%"]
            fila[f"{et}: peor_celda"] = g.loc[i, "peor_celda_min"]
        res.append(fila)
    res = pd.DataFrame(res)
    res.to_csv(OUT / "resumen.csv", index=False, encoding="utf-8-sig")
    print(res.iloc[:, :9].to_string(index=False))

    import matplotlib.pyplot as plt  # noqa: E402
    fig, axs = plt.subplots(2, 4, figsize=(16, 7.5), sharex=True, sharey=True)
    colores = {"mejor pasajero": "#1f77b4", "mejor tranvía": "#2ca02c", "compromiso": "#d62728"}
    for ax, (nombre, g) in zip(axs.flat, ev_.groupby("variante", sort=False)):
        ax.axhline(0, c="#999", lw=0.8)
        ax.axvline(0, c="#999", lw=0.8)
        ax.scatter(g.ahorro_min, g["cambio_tranvia_%"], s=10, c="#aaa")
        for et, c in colores.items():
            s = g[g.representativa == et]
            ax.scatter(s.ahorro_min, s["cambio_tranvia_%"], s=45, c=c, label=et)
        ax.set_title(nombre, fontsize=10)
    for ax in axs[1]:
        ax.set_xlabel("Ahorro puerta a puerta frente a hoy (min)")
    for ax in axs[:, 0]:
        ax.set_ylabel("Cambio de subidas al tranvía (%)")
    axs[0, 0].legend(fontsize=8)
    fig.suptitle(f"Robustez del frente ({NOMBRE}) ante los valores inciertos del grafo de pasajeros")
    fig.tight_layout()
    fig.savefig(OUT / "robustez.png", dpi=130)
