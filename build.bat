@echo off
echo ============================================
echo   Construccion de pruebas.exe (todo-en-uno)
echo ============================================
echo.

echo [1/3] Instalando PyInstaller...
pip install pyinstaller --quiet

echo.
echo [2/3] Verificando wkhtmltopdf...
if not exist "C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe" (
    echo.
    echo  ADVERTENCIA: wkhtmltopdf no encontrado en la ruta por defecto.
    echo  Los PDFs no funcionaran en el ejecutable final.
    echo  Instala wkhtmltopdf desde: https://wkhtmltopdf.org/downloads.html
    echo.
    pause
)

echo.
echo [3/3] Construyendo ejecutable...
pyinstaller pruebas.spec --clean --noconfirm

echo.
if exist "dist\pruebas.exe" (
    echo ============================================
    echo   LISTO!
    echo   Ejecutable: dist\pruebas.exe
    echo.
    echo   Contiene todo incluido:
    echo   - Python y todas las librerias
    echo   - wkhtmltopdf  (generacion de PDFs)
    echo   - Lista EFOS / 69-B
    echo   - Plantillas HTML/CSS
    echo.
    echo   Solo copia dist\pruebas.exe a la USB.
    echo   No requiere instalar nada en la otra PC.
    echo ============================================
) else (
    echo ERROR: No se genero el ejecutable.
    echo Revisa los mensajes de arriba.
)

echo.
pause
