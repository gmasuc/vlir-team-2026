@echo off
rem Escenario 1: frecuencias del contrato
rem Pulsar el boton verde (Play). Rueda del raton = zoom. Buses en amarillo grande, tranvia en los rieles.
cd /d "%~dp0"
start "" "%LOCALAPPDATA%\Python\pythoncore-3.14-64\Lib\site-packages\sumo\bin\sumo-gui.exe" -c escenario1_contrato.sumocfg

