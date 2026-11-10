# VLIR-UOS TEAM 2026

*Science-Based Decision Support Tools for Sustainable Cities and the Environment.* Universidad de Cuenca, con KU Leuven.

Un método común para dos casos: simulador → modelo sustituto → optimizador multiobjetivo.

| Carpeta | Caso |
|---|---|
| `01_Cumbe/` | Sedimento de las vías de lastre (Cumbe) |
| `02_DGM_Movilidad/` | Transporte público de Cuenca, eje 3 |

## Qué contiene este repositorio

**Solo el código del método.** Los datos no están aquí:
- Los datos entregados por la Dirección General de Movilidad (DGM) del GAD Municipal de Cuenca son privados. No se suben ni crudos ni derivados: SCATS, Escenario 0, capas de transporte, vías hábiles para el bus, conteos, etc.
- Los datos del proyecto CAMF (Cumbe) tampoco se suben.
- Las salidas de las simulaciones (SUMO, varios GB) se regeneran con los programas.

El archivo `.gitignore` funciona como lista de permitidos: se ignora todo salvo el código (`*.py`, `*.bat`).

Los informes técnicos, el registro de decisiones y el registro de corridas se mantienen fuera del repositorio mientras no se confirme con la DGM qué cifras derivadas pueden publicarse.

## Caso Cuenca: orden de los programas

1. `02_DGM_Movilidad/*.py`: exploración, verificación de los datos y figuras.
2. `02_DGM_Movilidad/simulacion_sumo/`: red, demanda, calibración, escenarios y robustez del simulador SUMO (numerados en orden de ejecución).
3. `02_DGM_Movilidad/optimizacion/`: grafo de pasajeros (`02`), evaluador rápido, desvíos candidatos (`04`), optimización de frecuencias (`05`) y robustez del grafo (`06`).

Requisitos: Python 3.14 y SUMO 1.28 (`pip install eclipse-sumo`), además de pandas, geopandas, networkx, sumolib y pymoo 0.6.2.
