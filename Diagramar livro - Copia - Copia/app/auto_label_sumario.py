#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_label_sumario.py - Gera labels iniciais usando heurísticas atuais
para acelerar anotação manual posterior.

Uso:
    python auto_label_sumario.py [pasta_pdfs] [labels_sumario.json]
"""

import sys
import json
import re
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).parent))
from diagramar_livro_v2 import (
    extrai_linhas_pagina,
    detecta_paginas_sumario_original,
    detecta_folha_de_rosto,
    detecta_ficha_catalografica,
)

CLASSES = {
    0: 'não_sumario',
    1: 'sumario_resumido',
    2: 'sumario_analitico',
    3: 'indice_remissivo'
}

def classifica_pagina_heuristica(pg, pg_idx, total_paginas, pags_sumario_set, entradas_toc):
    """Classifica uma página usando heurísticas atuais + features extras."""
    linhas = pg["linhas"]
    if not linhas:
        return 0

    textos = [l["raw"].strip() for l in linhas if l["raw"].strip()]
    textos_norm = [l["norm"] for l in linhas if l["raw"].strip()]

    # Se já detectado como sumário pelo método original
    if pg_idx in pags_sumario_set:
        # Verifica se é analítico (tem subcapítulos tipo 1.1, 2.3.1)
        tem_hierarquico = any(
            re.match(r'^\s*\d+(\.\d+)+\s', t.strip()) for t in textos
        )
        # Verifica se é índice remissivo (autor, sobrenome, páginas múltiplas)
        tem_autor_paginas = any(
            re.search(r'[A-ZÀ-Ý][a-zà-ÿ]+,\s+[A-ZÀ-Ý][a-z]+.*\d{1,4}(,\s*\d{1,4})*', t)
            for t in textos
        )
        if tem_hierarquico:
            return 2  # analítico
        elif tem_autor_paginas:
            return 3  # remissivo
        else:
            return 1  # resumido

    # Heurísticas adicionais para páginas NÃO detectadas originalmente
    texto_completo = " ".join(textos)

    # Palavras-chave de sumário
    if any(re.search(r'\b(sumario|indice|conteudo|contents|toc)\b', t, re.I) for t in textos):
        # Verifica se tem numeração hierárquica
        if any(re.match(r'^\s*\d+(\.\d+)+\s', t.strip()) for t in textos):
            return 2
        return 1

    # Índice remissivo: "Autor, Nome ... 12, 45, 78"
    if any(re.search(r'[A-ZÀ-Ý][a-zà-ÿ]+,\s+[A-ZÀ-Ý][a-z]+.*\d{1,4}(,\s*\d{1,4}){2,}', t) for t in textos):
        return 3

    # Páginas no início do livro com muitas linhas numeradas
    if pg_idx < 20:
        linhas_com_num = sum(1 for t in textos if re.search(r'[\.…]{3,}\s*\d+\s*$', t))
        if linhas_com_num >= 5:
            return 1

    return 0

def auto_label_pasta(pasta_pdfs, labels_path):
    """Processa todos os PDFs da pasta e gera labels automáticos."""
    pasta = Path(pasta_pdfs)
    pdfs = sorted(pasta.glob("*.pdf"))

    labels = {}
    total = 0
    dist = {0: 0, 1: 0, 2: 0, 3: 0}

    print(f"🤖 Auto-labeling {len(pdfs)} PDFs...")

    for pdf_path in pdfs:
        print(f"\n📖 {pdf_path.name}")
        doc = fitz.open(str(pdf_path))

        # Usa detecção original
        paginas = [
            {"n": i, "W": p.rect.width, "H": p.rect.height, "linhas": extrai_linhas_pagina(p)}
            for i, p in enumerate(doc, 1)
        ]

        # Remove folha de rosto e ficha
        corpo = [l["size"] for pg in paginas for l in pg["linhas"] if l["raw"].strip()]
        if corpo:
            corpo_tam = sorted(corpo)[len(corpo)//2]
        else:
            corpo_tam = 10

        # Detecta folha de rosto
        rosto = detecta_folha_de_rosto(paginas, corpo_tam)
        if rosto:
            idx_rosto, *_ = rosto
            for idx in idx_rosto:
                labels[f"{pdf_path.name}:{idx}"] = 0

        # Detecta ficha
        ficha = detecta_ficha_catalografica(paginas)
        for idx in ficha:
            labels[f"{pdf_path.name}:{idx}"] = 0

        # Detecta sumário original
        pags_sumario, entradas_toc, _ = detecta_paginas_sumario_original(paginas)

        # Classifica cada página
        for pg_idx, pg in enumerate(paginas):
            key = f"{pdf_path.name}:{pg_idx}"
            if key in labels:
                continue

            cls = classifica_pagina_heuristica(pg, pg_idx, len(paginas), pags_sumario, entradas_toc)
            labels[key] = cls
            dist[cls] += 1
            total += 1

        doc.close()

    # Salva
    with open(labels_path, 'w', encoding='utf-8') as f:
        json.dump(labels, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Auto-labeling concluído!")
    print(f"📊 Total: {total} páginas")
    for cls, count in sorted(dist.items()):
        print(f"   {cls} ({['não_sumario','resumido','analítico','remissivo'][cls]}): {count}")

    return labels

def main():
    pasta_pdfs = sys.argv[1] if len(sys.argv) > 1 else "PDFS para treino"
    labels_path = sys.argv[2] if len(sys.argv) > 2 else "app/labels_sumario.json"

    labels = auto_label_pasta(pasta_pdfs, labels_path)
    print(f"\n💾 Labels salvos em: {labels_path}")
    print("👉 Agora rode: python anotador_sumario.py para revisar/corrigir")

if __name__ == "__main__":
    main()