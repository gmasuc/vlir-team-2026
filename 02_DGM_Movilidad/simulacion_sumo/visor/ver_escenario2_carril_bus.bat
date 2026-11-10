@echo off
rem Escenario 2: corredores con carril exclusivo de bus (solo para ver los corredores; los numeros salen de la estimacion del informe)
rem Pulsar el boton verde (Play). Rueda del raton = zoom. Buses en amarillo grande, tranvia en los rieles.
cd /d "%~dp0"
start "" "%LOCALAPPDATA%\Python\pythoncore-3.14-64\Lib\site-packages\sumo\bin\sumo-gui.exe" -c escenario2_carril_bus.sumocfg

