@echo off
REM Gera RouteTelemetryConverter.exe (pasta dist\)
REM requirements-build.txt = app + matplotlib (relatório) + pyinstaller
pip install -r requirements-build.txt
flet pack app.py --name RouteTelemetryConverter ^
  --add-data "motec_lib;motec_lib" ^
  --add-data "assets;assets" ^
  --pyinstaller-build-args="--paths=motec_lib" ^
  --pyinstaller-build-args="--hidden-import=data_log" ^
  --pyinstaller-build-args="--hidden-import=motec_log" ^
  --pyinstaller-build-args="--hidden-import=ldparser.ldparser" ^
  --pyinstaller-build-args="--hidden-import=matplotlib.backends.backend_agg" ^
  --pyinstaller-build-args="--hidden-import=matplotlib.backends.backend_svg" ^
  --pyinstaller-build-args="--hidden-import=matplotlib.backends.backend_pdf"
echo Pronto: dist\RouteTelemetryConverter.exe
