#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
anotador_sumario.py - Ferramenta para anotar páginas de sumário em PDFs de treino

Uso:
    python anotador_sumario.py [pasta_pdfs]

Classes:
    0 = não é sumário (texto normal)
    1 = sumário resumido (apenas capítulos principais)
    2 = sumário analítico (com subcapítulos: 1.1, 1.2, etc.)
    3 = índice remissivo (autor/assunto com páginas)
"""

import sys
import json
from pathlib import Path
import pymupdf as fitz

# Adiciona o diretório do app ao path
sys.path.insert(0, str(Path(__file__).parent))
from diagramar_livro_v2 import extrai_linhas_pagina

CLASSES = {
    '0': 'não_sumario',
    '1': 'sumario_resumido',
    '2': 'sumario_analitico',
    '3': 'indice_remissivo'
}

def extrai_texto_pagina(page):
    """Extrai texto limpo da página para exibição."""
    linhas = extrai_linhas_pagina(page)
    textos = [l["raw"].strip() for l in linhas if l["raw"].strip()]
    return "\n".join(textos)

def mostra_preview(texto, max_chars=500):
    """Mostra preview do texto da página."""
    preview = texto[:max_chars].replace('\n', ' | ')
    if len(texto) > max_chars:
        preview += "..."
    return preview

def anota_pdfs(pasta_pdfs, arquivo_labels="labels_sumario.json"):
    """Loop principal de anotação."""
    pasta = Path(pasta_pdfs)
    pdfs = sorted(pasta.glob("*.pdf"))

    if not pdfs:
        print(f"❌ Nenhum PDF encontrado em: {pasta}")
        return

    print(f"📚 Encontrados {len(pdfs)} PDFs para anotação")
    print(f"💾 Labels serão salvos em: {arquivo_labels}")
    print()

    # Carrega labels existentes se houver
    labels = {}
    if Path(arquivo_labels).exists():
        with open(arquivo_labels, 'r', encoding='utf-8') as f:
            labels = json.load(f)
        print(f"📂 Carregados {len(labels)} labels existentes")

    total_anotados = 0

    for pdf_path in pdfs:
        key_base = pdf_path.name
        print(f"\n{'='*70}")
        print(f"📖 {key_base}")
        print(f"{'='*70}")

        try:
            doc = fitz.open(str(pdf_path))
        except Exception as e:
            print(f"❌ Erro ao abrir: {e}")
            continue

        for i, page in enumerate(doc):
            key = f"{key_base}:{i}"

            # Pula se já anotado
            if key in labels:
                continue

            texto = extrai_texto_pagina(page)

            # Pula páginas sem texto significativo
            if len(texto.strip()) < 20:
                labels[key] = 0
                continue

            print(f"\n--- Página {i+1}/{len(doc)} ---")
            print(mostra_preview(texto, 600))
            print()
            print("Classes:")
            for k, v in CLASSES.items():
                print(f"  {k} = {v}")
            print("  s = pular esta página")
            print("  q = sair e salvar")

            while True:
                cls = input("👉 Classe: ").strip().lower()

                if cls in CLASSES:
                    labels[key] = int(cls)
                    total_anotados += 1
                    print(f"  ✅ {CLASSES[cls]}")
                    break
                elif cls == 's':
                    print("  ⏭️  Pulado")
                    break
                elif cls == 'q':
                    print("\n💾 Salvando e saindo...")
                    with open(arquivo_labels, 'w', encoding='utf-8') as f:
                        json.dump(labels, f, ensure_ascii=False, indent=2)
                    print(f"✅ {len(labels)} labels salvos ({total_anotados} novos)")
                    doc.close()
                    return
                else:
                    print("  ❌ Inválido. Use 0, 1, 2, 3, s ou q")

        doc.close()

        # Salva progresso a cada PDF
        with open(arquivo_labels, 'w', encoding='utf-8') as f:
            json.dump(labels, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*70}")
    print(f"🎉 Anotação concluída!")
    print(f"📊 Total: {len(labels)} páginas ({total_anotados} novas)")
    print(f"💾 Salvo em: {arquivo_labels}")

    # Estatísticas
    from collections import Counter
    stats = Counter(labels.values())
    print("\n📈 Distribuição:")
    for k, v in sorted(stats.items()):
        print(f"   {k} ({CLASSES.get(str(k), '?')}): {v}")

def main():
    if len(sys.argv) < 2:
        pasta = Path(__file__).parent.parent / "PDFS para treino"
        print(f"Uso: python anotador_sumario.py <pasta_pdfs>")
        print(f"Padrão: {pasta}")
        if not pasta.exists():
            print("❌ Pasta padrão não encontrada")
            return
    else:
        pasta = sys.argv[1]

    arquivo_labels = Path(__file__).parent / "labels_sumario.json"
    anota_pdfs(pasta, str(arquivo_labels))

if __name__ == "__main__":
    main()