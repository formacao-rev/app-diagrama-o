#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
corrigidor_avancado.py - Correção ortográfica avançada com dicionário especializado

Melhorias:
1. Dicionário de termos acadêmicos/administrativos (evita falsos positivos)
2. Correções contextuais (a → à, o → ó, etc.)
3. Validação humana de correções com confiança baixa
"""

import re
from spellchecker import SpellChecker
from collections import Counter

# Initialize spell checker for Portuguese
spell = SpellChecker(language='pt', distance=2)

# ============================================================================
# DICIONÁRIOS ESPECIALIZADOS
# ============================================================================

# Academic/admin terms - should NOT be corrected
TERMOS_ACADEMICOS = {
    # Citations and references
    'fig', 'figura', 'tab', 'tabela', 'cap', 'capítulo', 'parágrafo', 'par',
    'art', 'artigo', 'autores', 'autor', 'eds', 'ed', 'edtr',
    'pág', 'pgs', 'pp', 'p', 'vol', 'vols', 'n', 'no',
    'isbn', 'issn', 'doi', 'lat', 'cpt',

    # Legal/Administrative
    'c/c', 'p/p', 's/n', 'fato', 'fictício',
    'sanc', 'sancionado', 'cond', 'condenado',

    # Common abbreviations (lowercase forms)
    'sr', 'sra', 'dr', 'dra', 'prof', 'profa',
    'exmo', 'exmo.', 'exmo-sr', 'exmo-sra', 'sr(a)',
    'etc', 'vs', 'e', 'ou', 'e',
}

# Prepositions that need contextual correction
PREPOSICOES = {
    'a': ['à', 'á', 'às', 'ás'],  # a → à (de/feminine), á (verbo vir), às (plural)
    'de': ['d'],  # de → d (abbreviação)
    'em': ['êm'],  # não usa abreviação, mas pode confundir
}

# Common OCR errors and their fixes (higher priority)
CORRECOES_OCR_DIRETAS = {
    'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬀ': 'ff', 'ﬃ': 'ffi', 'ﬄ': 'ffl',
}

# Words to ALWAYS correct (high confidence)
CORRECOES_FIXAS = {
    'gracas': 'graças',
    'pessoas': 'pessoas',  # common OCR error
    'existe': 'existe',
}


def contextualiza_preposicao(errada, preceder='', seguir=''):
    """
    Decide qual forma da preposição usar com base no contexto.
    """
    # a → à (de/feminine article)
    if errada == 'a':
        # Check if followed by feminine article
        if re.match(r'^\s+(uma|aquela|essa|quelas?|quelas?|as?)\b', seguir, re.I):
            return 'à'
        # Check if preceded by verb (like "chegar a", "ir a")
        if re.match(r'\b(vai|ir|vem|chega|faz|dá|volta|retorna)\b', preceder, re.I):
            return 'à'
        # Check if followed by verb starting with a
        if re.match(r'^\s+[a-z]', seguir):
            return 'à'
        return 'a'

    # de → d (in abbreviations like "c/c" but not in normal text)
    if errada == 'de' and len(preceder.strip() + seguir.strip()) < 15:
        return 'd'

    return errada


def obtem_confianca_correcao(errada, corrigida):
    """Returns a confidence score (0.0 to 1.0) for the correction."""
    # Exact match in fixed corrections = high confidence
    if errada in CORRECOES_FIXAS:
        return 0.95

    # OCR direct patterns = high confidence
    if errada in CORRECOES_OCR_DIRETAS:
        return 0.90

    # Similar word in dictionary = medium-high confidence
    if errada.lower() in spell:
        return 0.85

    # Spell checker suggestion = medium confidence
    if corrigida and corrigida in spell:
        # Check for common diacritic swaps
        if (errada.replace('ç', 'c') == corrigida.replace('ç', 'c') and 'ç' in errada) or \
           (errada.replace('á', 'a') == corrigida.replace('á', 'a')):
            return 0.75

    return 0.50


def corrige_texto_avancado(texto, num_pagina=None, titulo_capitulo=None):
    """
    Advanced text correction with specialized dictionaries and context.
    Returns: (texto_corrigido, correcoes_altas, correcoes_baixas)
    """
    correcoes = []
    correcoes_altas = []  # High confidence corrections
    correcoes_baixas = []  # Low confidence - needs review

    # Build the corrected text
    texto_corrigido = texto

    # Split into words preserving punctuation
    palavras = re.findall(r"[^\s]+", texto)

    for i, palavra in enumerate(palavras):
        # Skip if too short
        if len(palavra) <= 2:
            continue

        # Extract clean word
        match = re.match(r'^([^A-Za-zÀ-ÿ]*)([A-Za-zÀ-ÿ]+)([^A-Za-zÀ-ÿ]*)$', palavra)
        if not match:
            continue

        antes, limpa, depois = match.groups()

        # Skip specialized terms
        if limpa.lower() in TERMOS_ACADEMICOS or limpa.lower() in CORRECOES_OCR_DIRETAS:
            continue

        # Skip all caps (titles, acronyms)
        if limpa.isupper():
            continue

        # Skip numbers
        if any(c.isdigit() for c in limpa):
            continue

        corrigida = None

        # Check fixed corrections first
        if limpa.lower() in CORRECOES_FIXAS:
            corrigida = CORRECOES_FIXAS[limpa.lower()]
            confianca = 0.95

        # Check OCR direct fixes
        elif limpa in CORRECOES_OCR_DIRETAS:
            corrigida = CORRECOES_OCR_DIRETAS[limpa]
            confianca = 0.90

        # Check spell checker
        else:
            sugestao = spell.correction(limpa.lower())
            if sugestao and sugestao != limpa.lower():
                # Check similarity
                dif = sum(1 for a, b in zip(limpa.lower(), sugestao) if a != b)
                if 0 < dif <= 2:
                    # Contextualize prepositions
                    seguir = ''
                    if i + 1 < len(palavras):
                        seguir = palavras[i + 1]
                    preceder = ''
                    if i > 0:
                        preceder = palavras[i - 1]

                    corrigida = contextualiza_preposicao(sugestao, preceder, seguir)
                    confianca = obtem_confianca_correcao(limpa, corrigida)

        if corrigida and corrigida != limpa:
            # Preserve capitalization
            corrigida_final = corrigida.capitalize() if limpa[0].isupper() else corrigida

            detalhe = {
                'errada': limpa,
                'correta': corrigida_final,
                'pagina': num_pagina,
                'capitulo': titulo_capitulo,
                'confianca': confianca
            }
            correcoes.append(detalhe)

            # Separate by confidence
            if confianca < 0.7:
                correcoes_baixas.append(detalhe)
            else:
                correcoes_altas.append(detalhe)

            # Apply correction to the text
            # Replace the original word with the corrected one
            texto_corrigido = texto_corrigido.replace(palavra, corrigida_final, 1)

    return texto_corrigido, correcoes_altas, correcoes_baixas


def gera_relatorio_avancado(correcoes_todas, caminho_saida):
    """Generate comprehensive correction report."""
    if not correcoes_todas:
        with open(caminho_saida, 'w', encoding='utf-8') as f:
            f.write("Nenhuma correção necessária.\n")
        return

    # Group by chapter
    por_capitulo = {}
    for c in correcoes_todas:
        cap = c.get('capitulo', 'Preliminares')
        if cap not in por_capitulo:
            por_capitulo[cap] = []
        por_capitulo[cap].append(c)

    with open(caminho_saida, 'w', encoding='utf-8') as f:
        f.write("=" * 70 + "\n")
        f.write("RELATÓRIO DE CORREÇÕES ORTOGRÁFICAS AVANÇADO\n")
        f.write("=" * 70 + "\n\n")

        total = len(correcoes_todas)
        altas = len([c for c in correcoes_todas if c['confianca'] >= 0.7])
        baixas = total - altas

        f.write(f"Total de correções: {total}\n")
        f.write(f"Correções de alta confiança: {altas}\n")
        f.write(f"Correções a revisar manualmente: {baixas}\n\n")

        for capitulo in sorted(por_capitulo.keys(), key=str):
            correcoes_cap = por_capitulo[capitulo]
            f.write(f"\n{'─' * 70}\n")
            f.write(f"CAPÍTULO: {capitulo}\n")
            f.write(f"{'─' * 70}\n\n")

            for c in sorted(correcoes_cap, key=lambda x: x['pagina'] or 0):
                pag = c.get('pagina', 'desconhecida')
                conf = c.get('confianca', 0)
                conf_str = f"[Conf: {conf:.0%}]" if conf < 1.0 else ""
                f.write(f"  Pág. {pag} {conf_str}\n")
                f.write(f"    '{c['errada']}' → '{c['correta']}'\n")

        f.write(f"\n{'=' * 70}\n")


def inicializa_dicionarios(pasta_livro=None):
    """
    Inicializa/expande os dicionários com vocabulário do próprio livro.
    Carrega palavras frequentes do livro_limpo.txt para evitar falsos positivos.
    """
    global spell
    if pasta_livro:
        from pathlib import Path
        txt_path = Path(pasta_livro) / "livro_limpo.txt"
        if txt_path.exists():
            try:
                with open(txt_path, 'r', encoding='utf-8') as f:
                    texto = f.read()
                # Extrai palavras com 5+ letras, minúsculas
                palavras_livro = re.findall(r"[A-Za-zÀ-ÿ]{5,}", texto.lower())
                cont = Counter(palavras_livro)
                # Adiciona palavras que aparecem 3+ vezes ao dicionário
                for palavra, freq in cont.items():
                    if freq >= 3 and palavra not in spell:
                        spell.word_frequency.add(palavra)
                print(f"  Dicionário expandido com {sum(1 for p, f in cont.items() if f >= 3)} palavras do livro")
            except Exception as e:
                print(f"  Aviso: não foi possível expandir dicionário: {e}")


if __name__ == "__main__":
    # Test
    texto = "Este é um teste. Gracas pela ajuda. O autor irá a biblioteca."
    correcoes, altas, baixas = corrige_texto_avancado(texto)
    print(f"Correções: {correcoes}")
    print(f"Altas confiança: {len(altas)}")
    print(f"Baixa confiança: {len(baixas)}")