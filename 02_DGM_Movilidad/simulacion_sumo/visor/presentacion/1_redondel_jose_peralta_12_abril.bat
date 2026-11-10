@echo off
rem Redondel Jose Peralta y Av. 12 de Abril (la zona mas congestionada)
rem Situacion actual, modelo calibrado. Avanza solo hasta las 7:30 y se detiene. Luego subir Delay (p. ej. 50) y pulsar Play.
cd /d "%~dp0.."
start "" "C:\Users\pedri\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\sumo\bin\sumo-gui.exe" -c actual_calibrado.sumocfg --gui-settings-file presentacion\vista_1_redondel_jose_peralta_12_abril.xml --breakpoints 27000 --start

