#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_inno.py - Gera instalador Windows (Inno Setup) para Diagramar Livro

Pré-requisitos:
  1. Inno Setup 6.2+ instalado (https://jrsoftware.org/isdl.php)
  2. Executável já gerado (rode gerar_exe.py primeiro)
  3. iscc.exe no PATH (ou caminho completo)

Execute: python gerar_inno.py
"""

import subprocess
import sys
from pathlib import Path

def main():
    print("=" * 60)
    print("  GERADOR DE INSTALADOR - Diagramar Livro")
    print("=" * 60)
    print()

    script_dir = Path(__file__).resolve().parent

    # Verifica se executável existe
    exe_path = script_dir / "dist" / "DiagramarLivro.exe"
    if not exe_path.exists():
        print(f"❌ Executável não encontrado: {exe_path}")
        print("   Rode primeiro: python gerar_exe.py")
        return False

    # Verifica se iscc existe
    iscc_cmd = "iscc"
    try:
        subprocess.run([iscc_cmd, "/?"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Tenta caminhos comuns
        common_paths = [
            r"C:\Program Files (x86)\Inno Setup 6\iscc.exe",
            r"C:\Program Files\Inno Setup 6\iscc.exe",
        ]
        found = False
        for p in common_paths:
            if Path(p).exists():
                iscc_cmd = p
                found = True
                break
        if not found:
            print("❌ Inno Setup Compiler (iscc.exe) não encontrado!")
            print("   Instale: https://jrsoftware.org/isdl.php")
            print("   Ou adicione ao PATH")
            return False

    # Verifica install.iss
    iss_path = script_dir / "install.iss"
    if not iss_path.exists():
        print(f"❌ install.iss não encontrado")
        return False

    # Verifica LICENSE.txt
    license_path = script_dir / "LICENSE.txt"
    if not license_path.exists():
        print("⚠️  LICENSE.txt não encontrado, criando padrão...")
        license_path.write_text(
            "Diagramar Livro - Processador de PDF para diagramação editorial\n\n"
            "Copyright (c) 2024 Enzo Andrade\n\n"
            "Este software é fornecido 'como está', sem garantias.\n"
            "Uso por sua conta e risco.\n\n"
            "Dependências de terceiros:\n"
            "  - PyMuPDF (fitz) - AGPL-3.0\n"
            "  - ReportLab - BSD\n"
            "  - python-docx - MIT\n"
            "  - tkinterdnd2 - MIT\n"
            "  - pytesseract - Apache-2.0\n"
            "  - Tesseract OCR - Apache-2.0\n"
            "  - pyphen - GPL-2.0 / LGPL-2.1 / MPL-1.1\n"
            "  - fontTools - MIT\n"
            "  - ebooklib - BSD\n"
            "  - spellchecker - MIT\n"
            "  - Pillow - HPND\n",
            encoding="utf-8"
        )

    # Verifica ícone (opcional)
    icon_path = script_dir / "icon.ico"
    if not icon_path.exists():
        print("⚠️  icon.ico não encontrado, instalador usará ícone padrão")

    print("🔨 Compilando instalador com Inno Setup...")
    print(f"   Comando: {iscc_cmd} install.iss")
    print()

    result = subprocess.run([iscc_cmd, str(iss_path)], capture_output=True, text=True, cwd=script_dir, timeout=120)

    if result.returncode == 0:
        # Procura o instalador gerado
        setup_files = list(script_dir.glob("dist/Setup_*.exe"))
        if setup_files:
            setup_exe = max(setup_files, key=lambda p: p.stat().st_mtime)
            size_mb = setup_exe.stat().st_size / (1024 * 1024)
            print()
            print("✅  INSTALADOR GERADO COM SUCESSO!")
            print(f"   📁 {setup_exe}")
            print(f"   📦 Tamanho: {size_mb:.1f} MB")
            print()
            print("📋  O instalador inclui:")
            print("   • DiagramarLivro.exe (aplicação principal)")
            print("   • Fontes Vera Humana + Marcellus (opcional)")
            print("   • Verificação de Tesseract OCR na instalação")
            print("   • Atalhos no Menu Iniciar / Área de trabalho")
            print("   • Desinstalador limpo")
            return True
        else:
            print("⚠️  Compilou mas não encontrou o .exe em dist/")
            return False
    else:
        print(f"\n❌ Erro na compilação:")
        print(result.stdout[-1000:])
        print(result.stderr[-1000:])
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)