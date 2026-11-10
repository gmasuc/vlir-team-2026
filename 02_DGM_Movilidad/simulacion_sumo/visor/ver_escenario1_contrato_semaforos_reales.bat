@echo off
rem Escenario 1: frecuencias del contrato, con semaforos reales
rem Pulsar el boton verde (Play). Rueda del raton = zoom. Autos en amarillo, buses en rojo, tranvia en verde.
cd /d "%~dp0"
start "" "%LOCALAPPDATA%\Python\pythoncore-3.14-64\Lib\site-packages\sumo\bin\sumo-gui.exe" -c escenario1_contrato_semaforos_reales.sumocfg
