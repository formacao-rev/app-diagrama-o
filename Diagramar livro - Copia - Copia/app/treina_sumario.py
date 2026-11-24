#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
treina_sumario.py - Treina classificador de sumário (scikit-learn)

Uso:
    python treina_sumario.py [labels_sumario.json]

Gera: sumario_classifier.pkl
"""

import sys
import json
import numpy as np
import joblib
from pathlib import Path
from collections import Counter

from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.model_selection import cross_val_score, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, confusion_matrix

import pymupdf as fitz

# Adiciona o diretório do app ao path
sys.path.insert(0, str(Path(__file__).parent))
from diagramar_livro_v2 import extrai_linhas_pagina, norm

CLASSES = {
    0: 'não_sumario',
    1: 'sumario_resumido',
    2: 'sumario_analitico',
    3: 'indice_remissivo'
}

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

def carrega_dados(labels_path):
    """Carrega labels e extrai features dos PDFs correspondentes."""
    with open(labels_path, 'r', encoding='utf-8') as f:
        labels = json.load(f)

    # Agrupa por PDF
    pdfs_labels = {}
    for key, cls in labels.items():
        pdf_name, page_idx = key.rsplit(':', 1)
        page_idx = int(page_idx)
        if pdf_name not in pdfs_labels:
            pdfs_labels[pdf_name] = {}
        pdfs_labels[pdf_name][page_idx] = cls

    X, y = [], []
    feature_names = FEATURE_NAMES

    for pdf_name, page_labels in pdfs_labels.items():
        # Procura o PDF
        pdf_path = None
        for base in [Path("PDFS para treino"), Path("app/output"), Path(".")]:
            candidate = base / pdf_name
            if candidate.exists():
                pdf_path = candidate
                break

        if not pdf_path:
            print(f"⚠️  PDF não encontrado: {pdf_name}")
            continue

        print(f"📖 Processando: {pdf_name}")
        doc = fitz.open(str(pdf_path))

        for page_idx, cls in page_labels.items():
            if page_idx >= len(doc):
                continue
            page = doc[page_idx]
            linhas = extrai_linhas_pagina(page)
            pg = {"linhas": linhas, "W": page.rect.width, "H": page.rect.height, "n": page_idx + 1}

            feat = extrai_features_pagina(pg, page_idx, len(doc))
            x = [feat[k] for k in feature_names]

            X.append(x)
            y.append(cls)

        doc.close()

    return np.array(X), np.array(y), feature_names

def treina(X, y, feature_names):
    """Treina e avalia o classificador."""
    print(f"\n📊 Dataset: {len(X)} amostras, {len(feature_names)} features")
    print(f"📈 Distribuição: {Counter(y)}")

    # Pipeline com scaling
    pipe = Pipeline([
        ('scaler', StandardScaler()),
        ('clf', GradientBoostingClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.03,
            subsample=0.9,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42
        ))
    ])

    # Validação cruzada estratificada
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(pipe, X, y, cv=cv, scoring='f1_macro', n_jobs=-1)
    print(f"\n🔄 Cross-validation (5-fold):")
    print(f"   F1-macro: {scores.mean():.4f} ± {scores.std():.4f}")

    # Treina final
    print("\n🏋️ Treinando modelo final...")
    pipe.fit(X, y)

    # Avaliação no treino (apenas referência)
    y_pred = pipe.predict(X)
    print("\n📋 Classification Report (treino):")
    classes_presentes = sorted(set(y))
    target_names = [CLASSES[i] for i in classes_presentes]
    print(classification_report(y, y_pred, labels=classes_presentes, target_names=target_names))

    # Feature importance
    if hasattr(pipe.named_steps['clf'], 'feature_importances_'):
        importances = pipe.named_steps['clf'].feature_importances_
        idx = np.argsort(importances)[::-1]
        print("\n🔍 Top 10 Features mais importantes:")
        for i in idx[:10]:
            print(f"   {feature_names[i]}: {importances[i]:.4f}")

    return pipe

def main():
    labels_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("app/labels_sumario.json")
    modelo_path = Path("app/sumario_classifier.pkl")

    if not labels_path.exists():
        print(f"❌ Arquivo de labels não encontrado: {labels_path}")
        print("   Rode primeiro: python anotador_sumario.py")
        return

    print("🚀 Iniciando treino do classificador de sumário")
    print(f"📂 Labels: {labels_path}")
    print(f"💾 Modelo será salvo em: {modelo_path}")

    X, y, feature_names = carrega_dados(labels_path)

    if len(X) == 0:
        print("❌ Nenhum dado de treino extraído")
        return

    pipe = treina(X, y, feature_names)

    # Salva modelo + metadata
    modelo_data = {
        'pipeline': pipe,
        'feature_names': feature_names,
        'classes': CLASSES,
        'version': '1.0'
    }

    joblib.dump(modelo_data, modelo_path)
    print(f"\n✅ Modelo salvo em: {modelo_path}")
    print(f"📦 Tamanho: {modelo_path.stat().st_size / 1024:.1f} KB")

if __name__ == "__main__":
    import re
    main()