@echo off
REM Gera o HBI.exe neste computador (Windows, com Python 3.10+ instalado).
REM Resultado: dist\HBI\HBI.exe  e  dist\HBI-windows.zip  (para distribuir)
cd /d "%~dp0"
echo == Criando ambiente isolado para a compilacao ==
python -m venv .venv-exe || goto erro
call .venv-exe\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt pyinstaller || goto erro
echo == Testes ==
python tests\test_pipeline.py || goto erro
echo == Compilando ==
pyinstaller --noconfirm hbi.spec || goto erro
powershell -NoProfile -Command "Compress-Archive -Path dist\HBI -DestinationPath dist\HBI-windows.zip -Force" || goto erro
echo.
echo Pronto!  Programa: dist\HBI\HBI.exe   Pacote para distribuir: dist\HBI-windows.zip
pause
exit /b 0
:erro
echo.
echo Falhou. Veja a mensagem acima.
pause
exit /b 1
