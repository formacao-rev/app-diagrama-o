@echo off
title Diagramar Livro - Processador PDF
color 1F

echo ===============================================
echo   Diagramar Livro - Processador PDF
echo ===============================================
echo.

cd /d "%~dp0"

echo Verificando dependências...
python -c "import tkinter; print('Tkinter OK')" 2>nul
if errorlevel 1 (
    echo ERROR: Python não encontrado!
    echo Instale Python 3.8+ antes de continuar.
    pause
    exit /b 1
)

echo Verificando bibliotecas Python...
python -c "import pymupdf; import pyspellchecker; print('Pacotes principais OK')" 2>nul
if errorlevel 1 (
    echo WARNING: Algumas bibliotecas podem estar faltando.
    echo Execute: pip install pymupdf pyspellchecker tkinterdnd2
)

echo Verificando Tesseract OCR...
python -c "import pytesseract; print('pytesseract OK')" 2>nul
if errorlevel 1 (
    echo WARNING: pytesseract não encontrado.
    echo Para PDFs escaneados, instale: pip install pytesseract pillow
    echo Opcionalmente instale Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
)

echo.
echo Iniciando aplicação...
python app.py
pause