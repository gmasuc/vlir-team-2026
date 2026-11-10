"""
Registro de todas las simulaciones de la hora pico de Cuenca: para qué se hizo cada una, con qué parámetros, qué dio y
qué se decidió.

Entrada: buses/<corrida>/ (resumen_escenario.csv, sumo.log y, cuando existe, aristas_todos.xml) y la descripción de cada
         corrida en DESCRIPCION (abajo).
Proceso: lee los indicadores de cada corrida; si tiene aristas_todos.xml, calcula también el ajuste a los conteos de
         autos 2023 (38 accesos de 17 intersecciones) y a los tiempos de viaje de Google Maps (20 trayectos, salir a
         las 7:30 de un martes; 20_tiempos_viaje.py).
Salida:  simulacion_sumo/registro_simulaciones.csv y registro_simulaciones.xlsx (una fila por corrida).

Uso:  py simulacion_sumo/19_registro_simulaciones.py      (volver a correr después de cada simulación nueva)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SIM = Path(__file__).resolve().parent
sys.path.insert(0, str(SIM))
import validacion_independiente as vi  # noqa: E402
import importlib  # noqa: E402
tv = importlib.import_module("20_tiempos_viaje")

# carpeta -> (etapa, propósito, parámetros que cambian respecto de la corrida anterior, estado, decisión y por qué)
DESCRIPCION = {
    "equilibrio": ("1. Primeras pruebas", "Buses con la demanda sin calibrar", "demanda de equilibrio; paradas en la calle",
                   "descartada", "La demanda sin calibrar no reproduce los conteos"),
    "equilibrio_bahia": ("1. Primeras pruebas", "Paradas fuera de la calzada", "+ paradas en bahía", "descartada",
                         "Reemplazada por la demanda calibrada"),
    "equilibrio_bahia_reruteo": ("1. Primeras pruebas", "Autos que cambian de ruta", "+ cambio de ruta cada 5 min",
                                 "descartada", "Reemplazada por la demanda calibrada"),
    "equilibrio_contrato": ("1. Primeras pruebas", "Escenario 1 sin calibrar", "frecuencias de contrato", "descartada",
                            "Reemplazada por la demanda calibrada"),
    "equilibrio_contrato_bahia": ("1. Primeras pruebas", "Escenario 1 sin calibrar", "+ bahía", "descartada",
                                  "Reemplazada por la demanda calibrada"),
    "equilibrio_contrato_bahia_reruteo": ("1. Primeras pruebas", "Escenario 1 sin calibrar", "+ cambio de ruta",
                                          "descartada", "Reemplazada por la demanda calibrada"),
    "equilibrio_bahia_menoscarril_reruteo": ("1. Primeras pruebas", "Escenario 2 sin calibrar", "carril bus 14.4 km",
                                             "descartada", "Reemplazada por la demanda calibrada"),
    "calibrada": ("2. Demanda calibrada", "Buses con la demanda calibrada", "demanda calibrada; paradas en la calle",
                  "descartada", "Los buses detenidos bloqueaban toda la calle en el modo mesoscópico"),
    "calibrada_bahia": ("2. Demanda calibrada", "Paradas fuera de la calzada", "+ paradas en bahía", "descartada",
                        "Sin cambio de ruta: 10 000 autos atrapados a las 9:30, bus a 9 km/h"),
    "calibrada_contrato": ("2. Demanda calibrada", "Escenario 1", "frecuencias de contrato", "descartada",
                           "Misma razón que la base sin bahía"),
    "calibrada_contrato_bahia": ("2. Demanda calibrada", "Escenario 1", "+ bahía", "descartada",
                                 "Sin cambio de ruta"),
    "calibrada_bahia_reruteo": ("3. Semáforos genéricos", "Situación actual", "+ cambio de ruta cada 5 min; semáforos "
                                "genéricos de OSM", "reemplazada", "Reemplazada por los semáforos reales de SCATS"),
    "calibrada_contrato_bahia_reruteo": ("3. Semáforos genéricos", "Escenario 1: frecuencias de contrato",
                                         "frecuencias de contrato", "reemplazada", "Rehecha con semáforos SCATS"),
    "calibrada_bahia_menoscarril_reruteo": ("3. Semáforos genéricos", "Escenario 2: carril bus en 14.4 km",
                                            "1 carril menos para autos en 306 tramos", "reemplazada",
                                            "Rehecha con semáforos SCATS"),
    "calibrada_bahia_reruteo_scats_v1": ("4. Semáforos SCATS", "Primera versión con SCATS", "programas SCATS",
                                         "descartada", "Error: la prioridad del tranvía usaba tiempos genéricos"),
    "calibrada_bahia_reruteo_scats_v2_error": ("4. Semáforos SCATS", "Segunda versión con SCATS",
                                               "+ reguladores del tranvía por coordenadas", "descartada",
                                               "Error: en los cruces del tranvía la fase larga se daba al riel"),
    "calibrada_bahia_reruteo_scats": ("4. Semáforos SCATS", "Situación actual (base vigente)",
                                      "semáforos SCATS corregidos; paradas del recorrido municipal", "base vigente",
                                      "Base de los escenarios actuales"),
    "calibrada_contrato_bahia_reruteo_scats": ("4. Semáforos SCATS", "Escenario 1: frecuencias de contrato",
                                               "frecuencias de contrato", "exploratoria",
                                               "Espera 6.8 → 5.5 min sin costo de tráfico"),
    "calibrada_bahia_menoscarril_reruteo_scats": ("4. Semáforos SCATS", "Escenario 2: carril bus en 14.4 km",
                                                  "1 carril menos para autos en 306 tramos", "exploratoria",
                                                  "Auto +2.7 min"),
    "calibrada_bahia_menoscarril_reruteo_scats_2b": ("4. Semáforos SCATS", "Escenario 2b: carril bus solo en "
                                                     "Américas y 24 de Mayo", "1 carril menos en 82 tramos (4.8 km)",
                                                     "exploratoria", "Casi la mitad del ahorro con +0.3 min al auto"),
    "calibrada_bahia_reruteo_scats_centro": ("5. Calibración del centro", "Centro con menos capacidad (máxima)",
                                             "1 carril menos en 328 tramos del centro + paradas en el carril",
                                             "descartada", "Mejora los conteos pero bloquea la red (1 733 autos "
                                             "atrapados, bus 9.7 km/h)"),
    "calibrada_bahia_reruteo_scats_centro_parqueo": ("5. Calibración del centro", "Solo el carril ocupado por parqueo",
                                                     "1 carril menos en 328 tramos del centro", "descartada",
                                                     "Bloquea la red (bus 8.8 km/h)"),
    "calibrada_bahia_reruteo_scats_centro_paradas": ("5. Calibración del centro", "Solo paradas en el carril",
                                                     "paradas sin bahía en el centro", "descartada",
                                                     "Sin efecto sobre los conteos"),
    "calibrada_bahia_reruteo_scats_cap85": ("5. Calibración del centro", "Capacidad del centro al 85 %",
                                            "espaciamiento entre autos ÷ 0.85 en 328 tramos", "descartada",
                                            "Sin efecto"),
    "calibrada_bahia_reruteo_scats_cap70": ("5. Calibración del centro", "Capacidad del centro al 70 %",
                                            "espaciamiento ÷ 0.70", "descartada", "Sin efecto"),
    "calibrada_bahia_reruteo_scats_cap55": ("5. Calibración del centro", "Capacidad del centro al 55 %",
                                            "espaciamiento ÷ 0.55", "descartada", "Sin efecto"),
    "calibrada_bahia_reruteo_scats_tlsflow": ("6. Calibración de semáforos", "Semáforos que limitan el flujo",
                                              "--meso-tls-flow-penalty 1 + demora 100 %", "descartada",
                                              "Cuenta la demora dos veces: bus 15.2 km/h, r 0.61"),
    "calibrada_bahia_reruteo_scats_tlsflow_solo": ("6. Calibración de semáforos", "Solo limitar el flujo",
                                                   "flujo, demora 0 %", "descartada", "Bus 22.9 km/h, demasiado rápido"),
    "calibrada_bahia_reruteo_scats_tlsflow_p25": ("6. Calibración de semáforos", "Flujo + 25 % de demora",
                                                  "flujo, demora 25 %", "descartada", "Bus 21.6 km/h"),
    "calibrada_bahia_reruteo_scats_tlsflow_p50": ("6. Calibración de semáforos", "Flujo + 50 % de demora",
                                                  "flujo, demora 50 %", "descartada", "Bus 19.4 km/h, r 0.77"),
    "calibrada_bahia_reruteo_scats_vel_tlsflow_solo": ("7. Velocidades oficiales", "Velocidad oficial + flujo",
                                                       "velocidades de la jerarquía vial; flujo, demora 0 %",
                                                       "descartada", "Bus 21.3 km/h"),
    "calibrada_bahia_reruteo_scats_vel_tlsflow_p25": ("7. Velocidades oficiales", "Velocidad oficial + flujo + 25 %",
                                                      "velocidades de la jerarquía vial; flujo, demora 25 %",
                                                      "reemplazada", "Mejor ajuste a conteos (r 0.84), pero "
                                                      "tiempos de viaje = 46 % de Google: demasiado rápida"),
    "calibrada_bahia_reruteo_scats_vel_tlsflow_p50": ("7. Velocidades oficiales", "Velocidad oficial + flujo + 50 %",
                                                      "velocidades de la jerarquía vial; flujo, demora 50 %",
                                                      "descartada", "r 0.76, peor que 25 %"),
    "calibrada_contrato_bahia_reruteo_scats_vel_tlsflow_p25": ("8. Escenarios con la base candidata",
                                                               "Escenario 1: frecuencias de contrato",
                                                               "frecuencias de contrato", "exploratoria", ""),
    "calibrada_bahia_menoscarril_reruteo_scats_vel_tlsflow_p25": ("8. Escenarios con la base candidata",
                                                                  "Escenario 2: carril bus en 14.4 km",
                                                                  "1 carril menos para autos en 306 tramos",
                                                                  "exploratoria", ""),
    "calibrada_bahia_menoscarril_reruteo_scats_2b_vel_tlsflow_p25": ("8. Escenarios con la base candidata",
                                                                     "Escenario 2b: Américas y 24 de Mayo",
                                                                     "1 carril menos en 82 tramos (4.8 km)",
                                                                     "exploratoria", ""),
    "calibrada_bahia_reruteo_scats_vel_jc": ("9. Demoras en cruces (tiempos de viaje)",
                                            "Cruces que controlan el paso", "velocidades oficiales; --meso-junction-control",
                                            "reemplazada", "Reemplazada el 30-10 por la misma configuración con semáforos coordinados. Tiempos de viaje 69 % de Google (antes 54 %), 65 % "
                                            "de trayectos en el rango de Google y se sostiene en los no usados; conteos "
                                            "r 0.77; sin bloqueos; bus 14.6 km/h (programado 18.5): falta GPS de buses"),
    "calibrada_bahia_reruteo_scats_vel_minor10_tlsflow_p25": ("9. Demoras en cruces (tiempos de viaje)",
                                                              "Candidata + 10 s en cruces sin semáforo",
                                                              "candidata; --meso-minor-penalty 10", "descartada",
                                                              "Tiempos 64 % de Google, peor que cruces que controlan "
                                                              "el paso, con bus 13.3 km/h"),
    "calibrada_bahia_reruteo_scats_vel_minor20_tlsflow_p25": ("9. Demoras en cruces (tiempos de viaje)",
                                                              "Candidata + 20 s en cruces sin semáforo",
                                                              "candidata; --meso-minor-penalty 20", "descartada",
                                                              "Tiempos 78 % de Google, pero bloquea la red (598 autos "
                                                              "atrapados, bus 10.2 km/h) y empeora los conteos"),
    "calibrada_bahia_reruteo_scats_vel_coord_jc": ("12. Calibración del bus (semáforos coordinados)",
                                                  "Bus al 67 % de la velocidad observada (Escenario 0): coordinar los "
                                                  "semáforos según los enlaces de SCATS",
                                                  "candidata + desfases de SCATS en 84 cruces (ondas verdes)",
                                                  "reemplazada",
                                                  "Bus 15.2 km/h (69 % de lo observado, antes 67 %); conteos y Google "
                                                  "iguales dentro del azar. Se mantiene por tener base en SCATS; no "
                                                  "explica la brecha del bus. Reemplazada por la etapa 13"),
    "calibrada_bahia_reruteo_scats_vel_coord_fases_sinvueltas_jc": (
        "13. Calibración del bus (fases de SCATS y recorridos)",
        "Diagnóstico de las líneas 7 y 10: 43 semáforos sin las fases de SCATS y buses que dan vueltas a la manzana",
        "etapa 12 + fases de SCATS por calle en 43 semáforos + rutas sin vueltas que no están en la traza oficial",
        "modelo calibrado",
        "Adoptado el 30-10-2026. Bus 15.5 km/h (72 % de lo observado); conteos: volumen 95 %, GEH<5 42 %, r 0.76; "
        "Google 64 %. La brecha restante del bus (~28 %) se atribuye al modo mesoscópico"),
    "calibrada_contrato_bahia_reruteo_scats_vel_jc": ("10. Escenarios con cruces que controlan el paso",
                                                      "Escenario 1: frecuencias de contrato", "frecuencias de contrato",
                                                      "exploratoria", "Espera 6.8 → 5.5 min; auto +0.5 min (dentro "
                                                      "del azar del modelo); 92 % de los buses terminan"),
    "calibrada_bahia_menoscarril_reruteo_scats_vel_jc": ("10. Escenarios con cruces que controlan el paso",
                                                         "Escenario 2: carril bus en 14.4 km",
                                                         "1 carril menos para autos en 306 tramos", "exploratoria",
                                                         "Auto +3.7 min; ahorro de bus 9.1–24.3 horas-bus por "
                                                         "hora; 85 % de los buses terminan"),
    "calibrada_bahia_menoscarril_reruteo_scats_2b_vel_jc": ("10. Escenarios con cruces que controlan el paso",
                                                            "Escenario 2b: Américas y 24 de Mayo",
                                                            "1 carril menos en 82 tramos (4.8 km)", "exploratoria",
                                                            "Auto +0.9 min; ahorro de bus 2.9–12.3 horas-bus por "
                                                            "hora; 97 % de los buses terminan"),
    "calibrada_contrato_bahia_reruteo_scats_vel_coord_fases_sinvueltas_jc": (
        "14. Escenarios y robustez del modelo calibrado", "Escenario 1: frecuencias de contrato",
        "frecuencias de contrato", "exploratoria", "Auto +0.3 min (dentro del azar del modelo); 100 % de los buses terminan"),
    "calibrada_bahia_menoscarril_reruteo_scats_vel_coord_fases_sinvueltas_jc": (
        "14. Escenarios y robustez del modelo calibrado", "Escenario 2: carril bus en 14.4 km",
        "1 carril menos para autos en 306 tramos", "exploratoria",
        "Auto +2.9 min; ahorro de bus 4.8–13.6 horas-bus por hora; 90 % de los buses terminan"),
    "calibrada_bahia_menoscarril_reruteo_scats_2b_vel_coord_fases_sinvueltas_jc": (
        "14. Escenarios y robustez del modelo calibrado", "Escenario 2b: Américas y 24 de Mayo",
        "1 carril menos en 82 tramos (4.8 km)", "exploratoria",
        "Auto +0.4 min; ahorro de bus 1.6–6.1 horas-bus por hora; 100 % de los buses terminan"),
}
for _k in ("", "contrato_"):
    for _m in ("", "menoscarril_", "menoscarril_2b_"):
        if _k and _m:
            continue
        _n = (f"calibrada_{_k}bahia_{_m.replace('_2b_', '_')}reruteo_scats{'_2b' if '2b' in _m else ''}"
              "_vel_coord_fases_sinvueltas_tlsflow_p25")
        DESCRIPCION[_n] = ("14. Escenarios y robustez del modelo calibrado", "Misma situación en otra condición",
                           "sin cruces que controlan el paso", "robustez",
                           "Las tres conclusiones de los escenarios se mantienen "
                           "(robustez/robustez_vel_coord_fases_sinvueltas_jc.csv)")


def fecha(d):
    log = d / "sumo.log"
    return dt.datetime.fromtimestamp((log if log.exists() else d).stat().st_mtime).strftime("%Y-%m-%d %H:%M")


acc = pd.read_csv(SIM / "calibracion" / "ambos_v2" / "comparacion_accesos.csv")[["arista", "contados"]]
filas = []
for d in sorted((SIM / "buses").iterdir()):
    if not (d / "resumen_escenario.csv").exists():
        continue
    r = pd.read_csv(d / "resumen_escenario.csv").iloc[0].to_dict()
    etapa, proposito, parametros, estado, decision = DESCRIPCION.get(d.name, ("?", "", "", "sin describir", ""))
    if d.name not in DESCRIPCION and any(x in d.name for x in ("_seed", "_dem90", "_dem110", "_sin2carriles")):
        nuevo = "_fases_sinvueltas_jc" in d.name
        var = d.name.split("_fases_sinvueltas_jc" if nuevo else "_vel_jc")[-1].strip("_")
        etapa, proposito, parametros, estado = ("14. Escenarios y robustez del modelo calibrado" if nuevo else
                                                "11. Prueba de robustez", "Misma situación en otra condición",
                                                var.replace("seed", "semilla ").replace("dem90", "demanda -10 %")
                                                .replace("dem110", "demanda +10 %")
                                                .replace("sin2carriles", "sin avenidas a 2 carriles"), "robustez")
        decision = ("Las tres conclusiones de los escenarios se mantienen (robustez/robustez"
                    f"{'_vel_coord_fases_sinvueltas_jc' if nuevo else ''}.csv)")
    fila = {"corrida": d.name, "fecha": fecha(d), "etapa": etapa, "proposito": proposito,
            "parametros": parametros, "estado": estado, "decision_y_por_que": decision,
            "buses_h": r.get("buses_h"), "bus_kmh_mediana": r.get("bus_kmh_mediana"),
            "tranvia_kmh": r.get("tranvia_kmh"), "auto_viaje_min": r.get("auto_viaje_min"),
            "autos_atrapados_9_30": r.get("en_calle_9_30"), "teletransportes": r.get("teletransportes")}
    if (d / "aristas_todos.xml").exists():
        sim = acc.arista.map(vi.volumenes_por_arista(d.name)).fillna(0)
        ind = vi.indicadores(sim, acc.contados)
        tg = tv.tiempos_trayectos(d.name).merge(tv.google(), on="n")
        it = tv.indicadores_tiempos(tg)
        fila.update({"tiempos_viaje_modelo/google_%": round(it["modelo/google_%"]), "tiempos_viaje_r": round(it["r"], 2),
                     "tiempos_viaje_dentro_rango_%": round(it["dentro_del_rango_%"])})
        fila.update({"conteos_r": round(ind["r"], 2), "conteos_error_tipico_%": round(ind["error_tipico_%"]),
                     "conteos_volumen_%": round(ind["volumen_%"]), "conteos_GEH<5_%": round(ind["GEH<5_%"])})
    filas.append(fila)
t = pd.DataFrame(filas).sort_values(["etapa", "fecha"])
t.to_csv(SIM / "registro_simulaciones.csv", index=False, encoding="utf-8-sig")
t.to_excel(SIM / "registro_simulaciones.xlsx", index=False)
print(f"{len(t)} corridas registradas; estados:", t.estado.value_counts().to_dict())
print(t[["corrida", "estado", "bus_kmh_mediana", "auto_viaje_min", "conteos_r"]].to_string(index=False))
