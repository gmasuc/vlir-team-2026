"""
Paso 1 del ciclo de optimización de frecuencias (herramienta 2.2 de la Cartera, Eje 3): línea base del pasajero.

Espera en la parada de cada línea = mitad del intervalo (pasajeros que llegan al azar), promedio de los dos sentidos.
Se pondera por los pasajeros de cada línea: validaciones Movilízate 2023 por mes (datos/demanda_dgm_2023.csv, tomadas
del gráfico del informe DGM 2025, redondeadas a 10 000 viajes/mes). Se compara la oferta de la capa de líneas (situación
actual de la simulación) con la de los contratos de operación (escenario 1).

Supuestos y límites:
  - una validación = un pasajero que sube y espera una vez;
  - la mitad del intervalo subestima la espera si los buses llegan irregulares, y la sobreestima en intervalos largos
    (> 12 min), donde la gente consulta el horario;
  - la demanda es de 2023 y solo cubre 24 líneas urbanas ("Troncal Norte" = línea 100, según Pedro); las líneas sin
    dato quedan fuera del promedio ponderado.

Uso:  py optimizacion/01_linea_base_pasajeros.py
Salida: optimizacion/linea_base/lineas.csv y resumen.csv
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE))
import red_buses as rb  # noqa: E402

OUT = Path(__file__).resolve().parent / "linea_base"
OUT.mkdir(exist_ok=True)

# ----------------------------------------------------------------------------- oferta: capa y contrato
op = rb.lineas_operativas(gpd.read_file(BASE / "datos" / "derivados" / "Lineas_corregido.gpkg"))
op = op[op.modo == "bus"].copy()
op["int_capa"] = rb.minutos(op.intervalo_)
con = pd.read_csv(BASE / "datos_originales" / "Contratos_Operacion_Buses.csv", sep=None, engine="python",
                  encoding="utf-8-sig")
con["n_linea"] = con.n_linea.astype(str).str.strip().str.upper()
op["int_contrato"] = np.nan
for s, sentido in [("s1", "Ida"), ("s2", "Retorno")]:
    m = dict(zip(con.n_linea, con[f"{s}_intervalo_paso_min"]))
    sel = op.sentido == sentido
    op.loc[sel, "int_contrato"] = op.loc[sel, "linename"].str.upper().map(m)
op["int_contrato"] = op.int_contrato.fillna(op.int_capa)        # sin contrato: se mantiene la capa
op["flota_capa"] = pd.to_numeric(op.flota, errors="coerce")
lin = op.groupby("linename").agg(int_capa=("int_capa", "mean"), int_contrato=("int_contrato", "mean"),
                                 flota_capa=("flota_capa", "sum")).reset_index()
fl_con = con.assign(flota=con.s1_flota_unidades + con.s2_flota_unidades).set_index("n_linea").flota
lin["flota_contrato"] = lin.linename.str.upper().map(fl_con)

# ----------------------------------------------------------------------------- demanda Movilízate 2023
dem = pd.read_csv(BASE / "datos" / "demanda_dgm_2023.csv", dtype={"id": str})
mes = dem[dem.tipo == "linea_mensual"].set_index("id").valor * 1e6
mes = mes.rename({"TRONCAL NORTE": "100"})          # la Troncal Norte es la línea 100 (Pedro, 20-10-2026)
lin["pasajeros_mes"] = lin.linename.map(mes)
for f in ["capa", "contrato"]:
    lin[f"espera_{f}_min"] = lin[f"int_{f}"] / 2
lin = lin.sort_values("pasajeros_mes", ascending=False)
lin.round(2).to_csv(OUT / "lineas.csv", index=False, encoding="utf-8-sig")

# ----------------------------------------------------------------------------- indicadores
con_dato = lin[lin.pasajeros_mes.notna()]
filas = []
for f in ["capa", "contrato"]:
    w = con_dato[f"espera_{f}_min"]
    p = con_dato.pasajeros_mes
    filas.append({"oferta": f,
                  "espera_mediana_lineas_min": round(lin[f"espera_{f}_min"].median(), 1),
                  "espera_ponderada_pasajeros_min": round((w * p).sum() / p.sum(), 2),
                  "horas_espera_al_mes": round((w * p).sum() / 60),
                  "pasajeros_en_lineas_cada_12_min_o_mas_%": round(100 * p[con_dato[f"int_{f}"] >= 12].sum() / p.sum(), 1),
                  "flota": round(lin[f"flota_{f}"].sum())})
r = pd.DataFrame(filas)
r["lineas_con_demanda"] = f"{len(con_dato)} de {len(lin)}"
r["pasajeros_mes_cubiertos"] = round(con_dato.pasajeros_mes.sum())
r.to_csv(OUT / "resumen.csv", index=False, encoding="utf-8-sig")
print(r.T.to_string())
print("\nlíneas sin dato de demanda:", ", ".join(sorted(lin[lin.pasajeros_mes.isna()].linename, key=lambda x: (len(x), x))))
cols = ["linename", "pasajeros_mes", "int_capa", "int_contrato", "espera_capa_min", "espera_contrato_min"]
print(con_dato[cols].round(1).to_string(index=False))
