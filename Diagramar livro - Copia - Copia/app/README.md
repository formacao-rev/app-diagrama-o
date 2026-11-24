# Diagramar Livro - Documentação Técnica

## 📦 Pacote de Processamento de PDF

Aplicação avançada para processar PDFs com OCR, rediagramação editorial e correção ortográfica.

---

## 🛠 Arquivos

| Arquivo | Descrição |
|---------|-----------|
| `app.py` | Interface gráfica principal com tkinter/tkinterdnd2 |
| `preprocessar_pdf.py` | Módulo OCR - adiciona camada de texto a PDFs escaneados |
| `corrigidor_avancado.py` | Correção ortográfica com dicionário especializado |
| `diagramar_livro_v2.py` | Extrai, reorganiza e estrutura texto de livros |
| `dividir_paginas.py` | Divide páginas xerocadas em folhas separadas |
| `executar_app.bat` | Script de inicialização com verificação de dependências |
| `gerar_exe.py` | Script para gerar executável com PyInstaller |

---

## 🔄 Fluxo de Processamento

```
PDF Entrante
     │
     ├─► Verificar se tem texto (PyMuPDF)
     │       │
     │       ├─► TEM texto ──────► Diagramar Livro
     │       │                      │
     │       │                      ├─► livro_limpo.txt
     │       │                      ├─► livro_editavel.docx
     │       │                      └─► livro_diagramado.pdf
     │       │
     │       └─► NÃO tem texto ───► Adicionar OCR (Tesseract)
     │                              │
     │                              └─► Diagramar Livro
     │                                     │
     │                                     ├─► Opcional: Correção ortográfica
     │                                     │
     │                                     └─► livro_corrigido.txt
     │
     └─► Gerar relatórios
              ├─► correcoes_ocr.txt
              └─► correcoes_ortografia.txt
```

---

## 🔧 Configurações Tesseract

Para melhor precisão OCR, o `processar_pdf.py` usa:
```python
config='--oem 1 --psm 6'  # LSTM OCR, assume uniform block of text
```

### Parâmetros recomendados:
- **DPI:** 300 (padrão)
- **Língua:** Portuguese (`por`)
- **OEM:** 1 (LSTM neural nets only)
- **PSM:** 6 (Assume a single uniform block of text)

---

## 📝 Correção Ortográfica

### Como funciona:
1. Detecta palavras com até 2 caracteres de diferença
2. Verifica dicionário especializado (acadêmico/administrativo)
3. Aplica correções contextuais (a → à, de → d, etc.)
4. Classifica por confiança (alta/baixa)

### Termos que NÃO são corrigidos:
- Citações: `fig`, `tab`, `cap`, `art`, `pág`, etc.
- Abreviações: `sr`, `dr`, `prof`, `etc`
- Termos de PDF: `[PDF pág. N]`

---

## 📊 Dependências

| Pacote | Versão | Uso |
|--------|--------|-----|
| pymupdf | ≥1.28 | Manipulação PDF |
| pytesseract | ≥0.3 | OCR |
| pillow | ≥10.0 | Processamento de imagem |
| pyspellchecker | ≥0.9 | Correção ortográfica |
| tkinterdnd2 | ≥0.7 | Drag & Drop |
| python-docx | ≥1.2 | Exportação Word |
| reportlab | ≥4.0 | PDF generation |

---

## 🧪 Testes

```bash
# Verificar instalação
python -c "
from app import PDFApp, OCR_DISPONIVEL, HAS_DND
from preprocessar_pdf import pdf_tem_texto, adiciona_ocr
from corrigidor_avancado import corrige_texto_avancado
print('OCR:', OCR_DISPONIVEL, '| DND:', HAS_DND)
"

# Testar OCR
python preprocessar_pdf.py teste.pdf teste_ocr.pdf

# Testar correção
python -c "corrigidor_avancado.py"
```

---

## ⚠️ Solução de Problemas

### Tesseract não encontrado
```bash
# Verificar instalação
tesseract --version
tesseract --list-langs

# Windows - adicionar ao PATH
set PATH=%PATH%;C:\Program Files\Tesseract-OCR
```

### PDF não processa
1. Verifique se o PDF não está corrompido
2. Para PDFs com senha, remova a criptografia
3. Tente abrir no Preview/Adobe Reader primeiro

### Correções erradas
- Consulte `correcoes_ortografia.txt`
- Ajuste o limiar de confiança no `corrigidor_avancado.py`
- Adicione termos ao dicionário `TERMOS_ACADEMICOS`