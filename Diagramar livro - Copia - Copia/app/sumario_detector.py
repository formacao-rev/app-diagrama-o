#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sumario_detector.py - Detector de sumário baseado em ML (scikit-learn)

Uso:
    from sumario_detector import SumarioDetector
    detector = SumarioDetector()
    pags_sumario, tipo = detector.detecta(paginas)
"""

import os
import joblib
import numpy as np
from pathlib import Path

# Features na mesma ordem do treino
FEATURE_NAMES = [
    'n_linhas', 'n_palavras', 'media_chars_linha',
    'tem_sumario_kw', 'tem_capitulo_kw',
    'linhas_com_num_dir', 'prop_linhas_num_dir', 'linhas_hierarquicas',
    'tem_numeracao_hierarquica', 'linhas_simples',
    'media_fonte', 'cv_fonte', 'max_fonte', 'range_fonte',
    'y_medio_rel', 'y_span_rel',
    'pos_relativa', 'no_inicio',
    'prop_caixa_alta'
]

CLASSES = {
    0: 'não_sumario',
    1: 'sumario_resumido',
    2: 'sumario_analitico',
    3: 'indice_remissivo'
}

def extrai_features_pagina(pg, pg_idx, total_paginas):
    """Extrai features numéricas de uma página para o classificador."""
    linhas = pg["linhas"]
    if not linhas:
        return {k: 0.0 for k in FEATURE_NAMES}

    textos_raw = [l["raw"].strip() for l in linhas if l["raw"].strip()]
    textos_norm = [l["norm"] for l in linhas if l["raw"].strip()]
    tamanhos = [l["size"] for l in linhas if l["raw"].strip()]
    y_pos = [l["y0"] for l in linhas if l["raw"].strip()]

    n_linhas = len(textos_raw)
    n_palavras = sum(len(t.split()) for t in textos_raw)
    media_chars_linha = np.mean([len(t) for t in textos_raw]) if textos_raw else 0

    # Palavras-chave
    tem_sumario_kw = any(
        'sumario' in t or 'indice' in t or 'conteudo' in t or 'contents' in t or 'toc' in t
        for t in textos_norm
    )
    tem_capitulo_kw = any(
        'capitulo' in t or 'chapter' in t or 'parte' in t or 'part' in t
        for t in textos_norm
    )

    # Linhas com número à direita
    import re
    linhas_com_num_dir = sum(
        1 for t in textos_raw if re.search(r'[\.…]{3,}\s*\d+\s*$|^\s*\d+\s*$', t)
    )
    prop_linhas_num_dir = linhas_com_num_dir / n_linhas if n_linhas else 0

    # Numeração hierárquica (1.1, 1.2.1, etc.)
    linhas_hierarquicas = sum(
        1 for t in textos_raw if re.match(r'^\s*\d+(\.\d+)+\s', t.strip())
    )
    tem_numeracao_hierarquica = linhas_hierarquicas > 2

    # Numeração simples (1., 2., 12.)
    linhas_simples = sum(
        1 for t in textos_raw if re.match(r'^\s*\d{1,3}[\.\)]\s', t.strip())
    )

    # Tipografia
    media_fonte = np.mean(tamanhos) if tamanhos else 0
    desvio_fonte = np.std(tamanhos) if len(tamanhos) > 1 else 0
    max_fonte = max(tamanhos) if tamanhos else 0
    min_fonte = min(tamanhos) if tamanhos else 0
    cv_fonte = desvio_fonte / media_fonte if media_fonte else 0

    # Layout vertical
    y_medio = np.mean(y_pos) / pg["H"] if y_pos else 0
    y_span = (max(y_pos) - min(y_pos)) / pg["H"] if len(y_pos) > 1 else 0

    # Posição no livro
    pos_relativa = pg_idx / max(1, total_paginas)
    no_inicio = int(pos_relativa < 0.15)

    # Caixa alta
    prop_caixa_alta = sum(1 for t in textos_raw if t.isupper() and len(t) > 3) / n_linhas if n_linhas else 0

    return {
        'n_linhas': float(n_linhas),
        'n_palavras': float(n_palavras),
        'media_chars_linha': media_chars_linha,
        'tem_sumario_kw': float(tem_sumario_kw),
        'tem_capitulo_kw': float(tem_capitulo_kw),
        'linhas_com_num_dir': float(linhas_com_num_dir),
        'prop_linhas_num_dir': prop_linhas_num_dir,
        'linhas_hierarquicas': float(linhas_hierarquicas),
        'tem_numeracao_hierarquica': float(tem_numeracao_hierarquica),
        'linhas_simples': float(linhas_simples),
        'media_fonte': media_fonte,
        'cv_fonte': cv_fonte,
        'max_fonte': float(max_fonte),
        'range_fonte': float(max_fonte - min_fonte),
        'y_medio_rel': y_medio,
        'y_span_rel': y_span,
        'pos_relativa': pos_relativa,
        'no_inicio': float(no_inicio),
        'prop_caixa_alta': prop_caixa_alta
    }


class SumarioDetector:
    """Detector de sumário usando classificador ML treinado."""

    def __init__(self, modelo_path=None, confidence_threshold=0.7):
        """
        Args:
            modelo_path: Caminho para o .pkl do modelo. Se None, usa heurística.
            confidence_threshold: Threshold mínimo de confiança para aceitar predição ML.
        """
        self.confidence_threshold = confidence_threshold
        self.modelo = None
        self.feature_names = FEATURE_NAMES

        if modelo_path is None:
            # Procura padrão
            candidatos = [
                Path("app/sumario_classifier.pkl"),
                Path("sumario_classifier.pkl"),
                Path(__file__).parent / "sumario_classifier.pkl",
            ]
            for p in candidatos:
                if p.exists():
                    modelo_path = p
                    break

        if modelo_path and Path(modelo_path).exists():
            try:
                data = joblib.load(modelo_path)
                if isinstance(data, dict) and 'pipeline' in data:
                    self.modelo = data['pipeline']
                    self.feature_names = data.get('feature_names', FEATURE_NAMES)
                else:
                    self.modelo = data  # modelo antigo direto
                print(f"✅ SumarioDetector: modelo ML carregado de {modelo_path}")
            except Exception as e:
                print(f"⚠️  SumarioDetector: erro ao carregar modelo ML: {e}")
                print("   Usando heurística como fallback.")
                self.modelo = None
        else:
            print("⚠️  SumarioDetector: modelo ML não encontrado. Usando heurística.")

    def detecta(self, paginas):
        """
        Detecta páginas de sumário e tipo.

        Args:
            paginas: Lista de dicts com 'linhas', 'W', 'H', 'n'

        Returns:
            tuple: (set_paginas_sumario, tipo_sumario, confianca_media)
                   tipo_sumario: 0=nenhum, 1=resumido, 2=analitico, 3=remissivo
        """
        if self.modelo is None:
            return self._detecta_heuristico(paginas)

        predicoes = []
        for i, pg in enumerate(paginas):
            feat = extrai_features_pagina(pg, i, len(paginas))
            x = np.array([[feat[k] for k in self.feature_names]])
            try:
                proba = self.modelo.predict_proba(x)[0]
                cls = self.modelo.predict(x)[0]
                conf = max(proba)
            except Exception:
                # Fallback se modelo falhar
                cls, conf = self._heuristico_pagina(pg, i, len(paginas))

            predicoes.append({
                'pagina_idx': i,
                'classe': int(cls),
                'confianca': float(conf)
            })

        # Filtra por confiança
        paginas_sumario = set()
        confiancas = []
        classes_detectadas = []

        for p in predicoes:
            if p['classe'] in (1, 2, 3) and p['confianca'] >= self.confidence_threshold:
                paginas_sumario.add(p['pagina_idx'])
                confiancas.append(p['confianca'])
                classes_detectadas.append(p['classe'])

        # Determina tipo dominante
        tipo = 0
        if 2 in classes_detectadas:
            tipo = 2  # analítico vence
        elif 1 in classes_detectadas:
            tipo = 1  # resumido
        elif 3 in classes_detectadas:
            tipo = 3  # remissivo

        conf_media = np.mean(confiancas) if confiancas else 0.0

        return paginas_sumario, tipo, conf_media

    def _detecta_heuristico(self, paginas):
        """Fallback puramente heurístico."""
        from diagramar_livro_v2 import detecta_paginas_sumario_original
        pags_sumario, entradas_toc, entradas_sub = detecta_paginas_sumario_original(paginas)

        # Determina tipo: analítico se tem subcapítulos nas entradas
        tipo = 1
        if entradas_sub and len(entradas_sub) > 0:
            tipo = 2
        else:
            for _, raw in entradas_toc:
                if re.search(r'^\s*\d+(\.\d+)+\s', raw.strip()):
                    tipo = 2
                    break

        return pags_sumario, tipo, 0.8

    def _heuristico_pagina(self, pg, pg_idx, total):
        """Heurística para uma página."""
        from diagramar_livro_v2 import detecta_paginas_sumario_original
        pags_sumario, _, _ = detecta_paginas_sumario_original([pg])
        if pags_sumario:
            return 1, 0.8
        return 0, 0.0


# Para uso standalone
if __name__ == "__main__":
    import sys
    import pymupdf as fitz
    sys.path.insert(0, str(Path(__file__).parent))

    if len(sys.argv) < 2:
        print("Uso: python sumario_detector.py arquivo.pdf")
        sys.exit(1)

    pdf_path = sys.argv[1]
    doc = fitz.open(pdf_path)
    paginas = [
        {"n": i, "W": p.rect.width, "H": p.rect.height, "linhas": extrai_linhas_pagina(p)}
        for i, p in enumerate(doc, 1)
    ]
    doc.close()

    detector = SumarioDetector()
    pags_sumario, tipo, conf = detector.detecta(paginas)

    print(f"Páginas de sumário: {sorted([p+1 for p in pags_sumario])}")
    print(f"Tipo: {CLASSES.get(tipo, 'desconhecido')}")
    print(f"Confiança média: {conf:.2f}")