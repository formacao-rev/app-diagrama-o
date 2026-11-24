#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_exe.py - Script para gerar o executável do Diagramar Livro

Execute: python gerar_exe.py

Requisitos:
  pip install pyinstaller
  (e todas as dependências do projeto: tkinterdnd2, pymupdf, reportlab, etc.)

Para distribuição completa:
  1. Rode este script: python gerar_exe.py
  2. Instale Inno Setup 6+
  3. Compile install.iss: iscc install.iss
  4. O instalador sai em dist/Setup_DiagramarLivro.exe
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path

def copy_fonts(script_dir: Path) -> Path:
    """Copia fontes do sistema para pasta local fonts/"""
    fonts_dir = script_dir / "fonts"
    fonts_dir.mkdir(exist_ok=True)

    # Fontes a procurar no Windows
    font_names = [
        "Verah__.ttf", "Verahb_.ttf", "Verahi_.ttf", "Verahbi.ttf",
        "VeraHumana95-Regular.ttf", "VeraHumana95-Bold.ttf",
        "VeraHumana95-Italic.ttf", "VeraHumana95-BoldItalic.ttf",
        "Marcellus-Regular.ttf", "MarcellusSC-Regular.ttf",
    ]

    system_font_dirs = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts",
        Path("C:/Windows/Fonts"),
    ]

    found = 0
    for font_dir in system_font_dirs:
        if font_dir.exists():
            for name in font_names:
                src = font_dir / name
                dst = fonts_dir / name
                if src.exists() and not dst.exists():
                    shutil.copy2(src, dst)
                    print(f"  📝 Fonte copiada: {name}")
                    found += 1

    if found == 0:
        print("  ⚠️  Nenhuma fonte Vera Humana/Marcellus encontrada no sistema")
        print("     O PDF usará fallback (Times New Roman / Liberation Serif)")

    return fonts_dir

def main():
    print("=" * 60)
    print("  GERADOR DE EXECUTÁVEL - Diagramar Livro")
    print("=" * 60)
    print()

    script_dir = Path(__file__).resolve().parent

    # 1. Copia fontes
    print("1️⃣  Copiando fontes do sistema...")
    fonts_dir = copy_fonts(script_dir)
    print()

    # 2. Módulos Python a incluir
    print("2️⃣  Preparando módulos...")
    modules = [
        "app.py",
        "diagramar_livro_v2.py",
        "dividir_paginas.py",
        "preprocessar_pdf.py",
        "corrigidor_avancado.py",
        "corrigir_diagramado.py",
    ]
    print(f"   {len(modules)} módulos")
    print()

    # Build add-data arguments
    add_data = []
    for mod in modules:
        if (script_dir / mod).exists():
            add_data.extend(["--add-data", f"{script_dir / mod};."])

    # Fonts
    if fonts_dir.exists() and any(fonts_dir.iterdir()):
        add_data.extend(["--add-data", f"{fonts_dir};fonts"])
        print(f"   Fontes incluídas: {len(list(fonts_dir.iterdir()))} arquivos")
    print()

    # 3. Hidden imports
    print("3️⃣  Configurando imports ocultos...")
    hidden = [
        "tkinterdnd2", "pymupdf", "reportlab", "PIL",
        "spellchecker", "pytesseract", "pyphen", "fontTools",
        "unicodedata", "html", "urllib", "email",
        "ebooklib", "xml", "json", "csv", "pathlib",
    ]
    print(f"   {len(hidden)} hidden imports")
    print()

    # 4. Comando PyInstaller
    cmd = [
        "pyinstaller",
        "--name=DiagramarLivro",
        "--windowed",           # Sem console (GUI)
        "--onefile",            # Arquivo único
        "--clean",
        "--noconfirm",
        "--icon=NONE",          # Adicione seu .ico aqui se tiver
    ]
    for ad in add_data:
        cmd.append(ad)
    for h in hidden:
        cmd.extend(["--hidden-import", h])
    cmd.append(str(script_dir / "app.py"))

    print("4️⃣  Executando PyInstaller...")
    print(f"   Comando: pyinstaller --name=DiagramarLivro --windowed --onefile ... app.py")
    print()

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=script_dir, timeout=300)

    if result.returncode == 0:
        exe_path = script_dir / "dist" / "DiagramarLivro.exe"
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print()
        print("✅  EXECUTÁVEL GERADO COM SUCESSO!")
        print(f"   📁 {exe_path}")
        print(f"   📦 Tamanho: {size_mb:.1f} MB")
        print()
        print("⚠️  IMPORTANTE PARA O USUÁRIO FINAL:")
        print("   • O Tesseract OCR DEVE estar instalado no Windows")
        print("     (não vem dentro do .exe por questões de licença/tamanho)")
        print("   • Baixe em: https://github.com/UB-Mannheim/tesseract/wiki")
        print("   • Durante a instalação, marque 'Additional language data' → Portuguese")
        print("   • Fontes Vera Humana + Marcellus são opcionais (fallback automático)")
        print()
        print("📋 PRÓXIMO PASSO: Criar instalador profissional")
        print("   Rode: python gerar_inno.py")
        print("   Ou compile manualmente: iscc install.iss")
        return True
    else:
        print(f"\n❌ Erro ao gerar executável:")
        print(result.stderr[-2000:])  # últimas 2000 chars
        print("\n💡 Dicas:")
        print("  - pip install pyinstaller")
        print("  - Verifique dependências: pip install -r requirements.txt")
        print("  - Teste primeiro: python app.py")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)