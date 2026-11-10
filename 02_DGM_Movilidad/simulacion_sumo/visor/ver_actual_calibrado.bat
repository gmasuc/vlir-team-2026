@echo off
rem Situacion actual con el modelo calibrado (semaforos reales, velocidades oficiales, cruces que controlan el paso)
rem Pulsar el boton verde (Play). Rueda del raton = zoom. Autos en amarillo, buses en rojo, tranvia en verde.
cd /d "%~dp0"
start "" "C:\Users\pedri\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\sumo\bin\sumo-gui.exe" -c actual_calibrado.sumocfg
