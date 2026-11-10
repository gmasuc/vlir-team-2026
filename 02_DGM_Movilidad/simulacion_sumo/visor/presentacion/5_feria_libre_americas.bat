@echo off
rem Feria Libre y Av. de las Americas (buses junto al tranvia)
rem Situacion actual, modelo calibrado. Avanza solo hasta las 7:30 y se detiene. Luego subir Delay (p. ej. 50) y pulsar Play.
cd /d "%~dp0.."
start "" "C:\Users\pedri\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\sumo\bin\sumo-gui.exe" -c actual_calibrado.sumocfg --gui-settings-file presentacion\vista_5_feria_libre_americas.xml --breakpoints 27000 --start

