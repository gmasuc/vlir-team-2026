"""
Prueba de robustez: ¿las conclusiones de los escenarios cambian si cambian los supuestos del modelo?

Entrada: corridas de 09_buses.py del modelo calibrado (scats vel_oficial jc) con cuatro situaciones —actual (A),
         frecuencias de contrato (B), carril bus en 14.4 km (C) y carril bus solo en Américas y 24 de Mayo (D)— y
         estas variantes de los supuestos:
           semilla 2 a 5 (azar del modelo), demanda de autos -10 % y +10 %, sin cruces que controlan el paso
           (semáforos que limitan el flujo), y red sin el paso de avenidas a 2 carriles (solo A y B).
Proceso: para cada variante calcula el costo para el auto de cada escenario (minutos de viaje frente a A), el tiempo
         de bus ahorrado con el carril exclusivo (demora de los buses de A en los tramos del corredor: mínimo = tiempo
         detenidos, máximo = toda la demora) y revisa tres conclusiones:
           1. el contrato cuesta poco al auto (menos de 1 minuto);
           2. el carril en toda la red le cuesta al auto más que el carril focalizado;
           3. el carril focalizado ahorra más tiempo de bus por minuto de costo al auto que el carril en toda la red.
Salida:  simulacion_sumo/robustez/robustez.csv (modelo de la etapa 9, "_vel_jc") o robustez_<modelo>.csv y la tabla en
         pantalla.

Uso:  py simulacion_sumo/21_robustez.py [modelo]      modelo = sufijo de carpeta, p. ej. vel_coord_fases_sinvueltas_jc
      (el modelo calibrado del 30-10-2026; su variante sin cruces que controlan el paso usa "..._tlsflow_p25")
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import os
import sys
from pathlib import Path

import pandas as pd
import sumo

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
B = SIM / "buses"
OUT = SIM / "robustez"
OUT.mkdir(exist_ok=True)


MODELO = "_" + sys.argv[1] if len(sys.argv) > 1 else "_vel_jc"
SIN_JC = MODELO.replace("_jc", "_tlsflow_p25")


def carpetas(suf, modelo=MODELO):
    return {"A": f"calibrada_bahia_reruteo_scats{modelo}{suf}",
            "B": f"calibrada_contrato_bahia_reruteo_scats{modelo}{suf}",
            "C": f"calibrada_bahia_menoscarril_reruteo_scats{modelo}{suf}",
            "D": f"calibrada_bahia_menoscarril_reruteo_scats_2b{modelo}{suf}"}


VARIANTES = {"modelo calibrado (semilla por defecto)": carpetas("")}
VARIANTES.update({f"semilla {k}": carpetas(f"_seed{k}") for k in range(2, 6)})
VARIANTES["demanda -10 %"] = carpetas("_dem90")
VARIANTES["demanda +10 %"] = carpetas("_dem110")
VARIANTES["sin cruces que controlan el paso"] = carpetas("", SIN_JC)
VARIANTES["sin avenidas a 2 carriles"] = {k: v for k, v in carpetas("_sin2carriles").items() if k in "AB"}
CORR = {"C": set(pd.read_csv(SIM / "red" / "carriles_bus_v3.csv").arista),
        "D": set(pd.read_csv(SIM / "red" / "carriles_bus_v3_2b.csv").arista)}


def resumen(carpeta):
    f = B / carpeta / "resumen_escenario.csv"
    return pd.read_csv(f).iloc[0] if f.exists() else None


def ahorro_bus(carpeta_actual, corredor):
    """horas-bus por hora de demora de los buses de la situación actual en los tramos del corredor (mín, máx)."""
    tl = wt = 0.0
    for iv in sumolib.xml.parse(str(B / carpeta_actual / "buses_aristas.xml"), "interval"):
        for e in iv.edge or []:
            if e.id in corredor:
                tl += float(e.timeLoss or 0)
                wt += float(e.waitingTime or 0)
    return wt / 3600, tl / 3600


filas = []
for nombre, c in VARIANTES.items():
    r = {k: resumen(v) for k, v in c.items()}
    if r["A"] is None:
        print(f"falta la corrida actual de «{nombre}» ({c['A']})")
        continue
    a = r["A"].auto_viaje_min
    fila = {"variante": nombre, "auto_actual_min": a, "bus_actual_kmh": r["A"].bus_kmh_mediana,
            "autos_atrapados_actual": r["A"].en_calle_9_30}
    for k, esc in [("B", "contrato"), ("C", "carril_14km"), ("D", "carril_focalizado")]:
        if r.get(k) is not None:
            fila[f"costo_auto_{esc}_min"] = round(r[k].auto_viaje_min - a, 2)
            fila[f"buses_terminan_{esc}_%"] = r[k]["buses_terminan_%"]
    for k, esc in [("C", "carril_14km"), ("D", "carril_focalizado")]:
        if r.get(k) is not None:
            mn, mx = ahorro_bus(c["A"], CORR[k])
            fila[f"ahorro_bus_{esc}_h"] = f"{mn:.1f}–{mx:.1f}"
            fila[f"ahorro_max_por_min_costo_{esc}"] = round(mx / max(fila[f"costo_auto_{esc}_min"], 0.05), 1)
    filas.append(fila)
t = pd.DataFrame(filas)


def cumple(f, regla, columnas):
    if any(pd.isna(f.get(c)) for c in columnas):
        return "—"
    try:
        return "sí" if regla(f) else "NO"
    except (KeyError, TypeError):
        return "—"


t["1_contrato_cuesta_menos_de_1_min"] = [cumple(f, lambda f: f["costo_auto_contrato_min"] < 1, ["costo_auto_contrato_min"]) for _, f in t.iterrows()]
t["2_carril_red_cuesta_mas_que_focalizado"] = [cumple(f, lambda f: f["costo_auto_carril_14km_min"] >
                                                      f["costo_auto_carril_focalizado_min"],
                                                      ["costo_auto_carril_14km_min", "costo_auto_carril_focalizado_min"]) for _, f in t.iterrows()]
t["3_focalizado_mas_eficiente"] = [cumple(f, lambda f: f["ahorro_max_por_min_costo_carril_focalizado"] >
                                          f["ahorro_max_por_min_costo_carril_14km"],
                                          ["ahorro_max_por_min_costo_carril_14km"]) for _, f in t.iterrows()]
t.to_csv(OUT / ("robustez.csv" if MODELO == "_vel_jc" else f"robustez{MODELO}.csv"), index=False, encoding="utf-8-sig")
pd.set_option("display.width", 250)
print(t.T.to_string())
