#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
metadados_dublin.py - Extrai metadados Dublin Core (XMP) do PDF
e propaga para EPUB/PDF de saída.

Dublin Core Elements (15 elementos principais):
- dc:title, dc:creator, dc:subject, dc:description
- dc:publisher, dc:contributor, dc:date, dc:type
- dc:format, dc:identifier, dc:source, dc:language
- dc:relation, dc:coverage, dc:rights

XMP (Extensible Metadata Platform) - formato RDF/XML embutido no PDF.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from pathlib import Path

try:
    import pymupdf as fitz
    FITZ_DISPONIVEL = True
except ImportError:
    FITZ_DISPONIVEL = False

# Namespaces Dublin Core / XMP
NS = {
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'xmp': 'http://ns.adobe.com/xap/1.0/',
    'pdf': 'http://ns.adobe.com/pdf/1.3/',
    'xmpMM': 'http://ns.adobe.com/xap/1.0/mm/',
    'stEvt': 'http://ns.adobe.com/xap/1.0/sType/ResourceEvent#',
}

@dataclass
class DublinCore:
    """Metadados Dublin Core extraídos do PDF."""
    title: Optional[str] = None
    creator: List[str] = field(default_factory=list)
    subject: List[str] = field(default_factory=list)  # keywords/tags
    description: Optional[str] = None
    publisher: Optional[str] = None
    contributor: List[str] = field(default_factory=list)
    date: Optional[str] = None
    type_: Optional[str] = None
    format_: Optional[str] = None
    identifier: List[str] = field(default_factory=list)  # ISBN, DOI, etc.
    source: Optional[str] = None
    language: Optional[str] = None
    relation: Optional[str] = None
    coverage: Optional[str] = None
    rights: Optional[str] = None

    # XMP extras
    create_date: Optional[str] = None
    modify_date: Optional[str] = None
    creator_tool: Optional[str] = None
    producer: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.title,
            'creator': self.creator,
            'subject': self.subject,
            'description': self.description,
            'publisher': self.publisher,
            'contributor': self.contributor,
            'date': self.date,
            'type': self.type_,
            'format': self.format_,
            'identifier': self.identifier,
            'source': self.source,
            'language': self.language,
            'relation': self.relation,
            'coverage': self.coverage,
            'rights': self.rights,
            'create_date': self.create_date,
            'modify_date': self.modify_date,
            'creator_tool': self.creator_tool,
            'producer': self.producer,
        }

    def get_first_creator(self) -> Optional[str]:
        return self.creator[0] if self.creator else None

    def get_subjects_str(self) -> str:
        return "; ".join(self.subject) if self.subject else ""

    def get_identifiers_str(self) -> str:
        return ", ".join(self.identifier) if self.identifier else ""


def limpa_metadado(valor: str) -> str:
    """Limpa string de metadado (remove chars de controle, normaliza espaços)."""
    if not valor:
        return ""
    # Remove chars de controle
    valor = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', valor)
    # Normaliza whitespace
    valor = re.sub(r'\s+', ' ', valor)
    return valor.strip()


def extrai_xmp_do_pdf(pdf_path: str) -> Optional[str]:
    """
    Extrai o stream XMP (XML) do PDF.
    Retorna string XML ou None se não houver.
    """
    if not FITZ_DISPONIVEL:
        return None

    doc = fitz.open(pdf_path)
    try:
        # PyMuPDF expõe metadados XMP via doc.metadata (já parseado)
        # Mas para XMP bruto, acessa o stream do catálogo
        xmp_stream = None

        # Tenta pelo metadado padrão primeiro
        meta = doc.metadata
        if meta and meta.get('title'):
            return None  # Já temos metadados básicos

        # Acessa XMP raw do catálogo
        try:
            catalog = doc.pdf_catalog()
            if catalog and 'Metadata' in catalog:
                meta_obj = catalog['Metadata']
                if hasattr(meta_obj, 'get_data'):
                    xmp_stream = meta_obj.get_data()
                elif isinstance(meta_obj, bytes):
                    xmp_stream = meta_obj
        except Exception:
            pass

        doc.close()

        if xmp_stream:
            if isinstance(xmp_stream, bytes):
                return xmp_stream.decode('utf-8', errors='ignore')
            return str(xmp_stream)

        return None
    except Exception:
        return None


def parseia_xmp_dublin_core(xmp_xml: str) -> DublinCore:
    """
    Parseia XML XMP e extrai elementos Dublin Core.
    """
    dc = DublinCore()

    if not xmp_xml:
        return dc

    try:
        # Remove namespace declarations para parsing mais fácil
        # Mas mantemos para xpath
        root = ET.fromstring(xmp_xml)

        # Helper para buscar com namespaces
        def find_dc(tag: str) -> Optional[str]:
            elem = root.find(f".//dc:{tag}", NS)
            if elem is not None and elem.text:
                return limpa_metadado(elem.text)
            return None

        def find_all_dc(tag: str) -> List[str]:
            elems = root.findall(f".//dc:{tag}", NS)
            return [limpa_metadado(e.text) for e in elems if e.text]

        def find_xmp(tag: str) -> Optional[str]:
            elem = root.find(f".//xmp:{tag}", NS)
            if elem is not None and elem.text:
                return limpa_metadado(elem.text)
            return None

        def find_pdf(tag: str) -> Optional[str]:
            elem = root.find(f".//pdf:{tag}", NS)
            if elem is not None and elem.text:
                return limpa_metadado(elem.text)
            return None

        # Dublin Core 15 elementos
        dc.title = find_dc('title')
        dc.creator = find_all_dc('creator')
        dc.subject = find_all_dc('subject')
        dc.description = find_dc('description')
        dc.publisher = find_dc('publisher')
        dc.contributor = find_all_dc('contributor')
        dc.date = find_dc('date')
        dc.type_ = find_dc('type')
        dc.format_ = find_dc('format')
        dc.identifier = find_all_dc('identifier')
        dc.source = find_dc('source')
        dc.language = find_dc('language')
        dc.relation = find_dc('relation')
        dc.coverage = find_dc('coverage')
        dc.rights = find_dc('rights')

        # XMP extras
        dc.create_date = find_xmp('CreateDate') or find_pdf('CreationDate')
        dc.modify_date = find_xmp('ModifyDate') or find_pdf('ModDate')
        dc.creator_tool = find_xmp('CreatorTool') or find_pdf('Producer')
        dc.producer = find_pdf('Producer')

    except ET.ParseError:
        pass  # XML malformado, retorna vazio

    return dc


def extrai_metadados_pdf_completo(pdf_path: str) -> DublinCore:
    """
    Extrai metadados completos do PDF combinando:
    1. XMP (RDF/XML) - mais completo
    2. Metadados padrão PyMuPDF (fallback)
    """
    dc = DublinCore()

    # 1. Tenta XMP primeiro
    xmp_xml = extrai_xmp_do_pdf(pdf_path)
    if xmp_xml:
        dc = parseia_xmp_dublin_core(xmp_xml)

    # 2. Completa com metadados PyMuPDF (fallback para campos vazios)
    if FITZ_DISPONIVEL:
        doc = fitz.open(pdf_path)
        meta = doc.metadata or {}
        doc.close()

        if not dc.title and meta.get('title'):
            dc.title = limpa_metadado(meta['title'])
        if not dc.creator and meta.get('author'):
            dc.creator = [limpa_metadado(meta['author'])]
        if not dc.subject and meta.get('subject'):
            dc.subject = [limpa_metadado(meta['subject'])]
        if not dc.description and meta.get('subject'):  # subject às vezes é description
            pass
        if not dc.create_date and meta.get('creationDate'):
            dc.create_date = limpa_metadado(meta['creationDate'])
        if not dc.modify_date and meta.get('modDate'):
            dc.modify_date = limpa_metadado(meta['modDate'])
        if not dc.creator_tool and meta.get('creator'):
            dc.creator_tool = limpa_metadado(meta['creator'])
        if not dc.producer and meta.get('producer'):
            dc.producer = limpa_metadado(meta['producer'])

    return dc


def propaga_para_epub(dc: DublinCore, book) -> None:
    """
    Propaga metadados Dublin Core para objeto ebooklib EPUB.
    """
    if dc.title:
        book.set_title(dc.title)
    if dc.creator:
        for c in dc.creator:
            book.add_author(c)
    if dc.subject:
        for s in dc.subject:
            book.add_metadata('DC', 'subject', s)
    if dc.description:
        book.set_metadata('DC', 'description', dc.description)
    if dc.publisher:
        book.set_metadata('DC', 'publisher', dc.publisher)
    if dc.contributor:
        for c in dc.contributor:
            book.add_metadata('DC', 'contributor', c)
    if dc.date:
        book.set_metadata('DC', 'date', dc.date)
    if dc.type_:
        book.set_metadata('DC', 'type', dc.type_)
    if dc.format_:
        book.set_metadata('DC', 'format', dc.format_)
    for ident in dc.identifier:
        book.set_metadata('DC', 'identifier', ident)
    if dc.source:
        book.set_metadata('DC', 'source', dc.source)
    if dc.language:
        book.set_metadata('DC', 'language', dc.language)
    if dc.relation:
        book.set_metadata('DC', 'relation', dc.relation)
    if dc.coverage:
        book.set_metadata('DC', 'coverage', dc.coverage)
    if dc.rights:
        book.set_metadata('DC', 'rights', dc.rights)


def propaga_para_pdf_metadata(dc: DublinCore, pdf_path: str) -> None:
    """
    Atualiza metadados do PDF de saída (PyMuPDF).
    """
    if not FITZ_DISPONIVEL:
        return

    doc = fitz.open(pdf_path)
    meta = doc.metadata or {}

    if dc.title:
        meta['title'] = dc.title
    if dc.creator:
        meta['author'] = dc.get_first_creator() or "; ".join(dc.creator)
    if dc.subject:
        meta['subject'] = dc.get_subjects_str()
    if dc.description:
        meta['keywords'] = dc.description[:500]  # keywords field
    if dc.publisher:
        meta['producer'] = dc.publisher  # producer ≈ publisher
    if dc.date:
        meta['creationDate'] = dc.date
    if dc.rights:
        meta['creator'] = dc.rights  # creator field sometimes used for rights

    doc.set_metadata(meta)
    doc.saveIncr()
    doc.close()


def extrai_isbn_doi(texto: str) -> Dict[str, List[str]]:
    """
    Extrai ISBNs e DOIs de texto livre (útil para popular identifier).
    """
    isbns = re.findall(r'(?:ISBN[\s:-]*)?(?:97[89][\s-]?)?\d{1,5}[\s-]?\d{1,7}[\s-]?\d{1,7}[\s-]?[\dX]', texto, re.I)
    dois = re.findall(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', texto, re.I)

    return {
        'isbn': list(set(isbns)),
        'doi': list(set(dois))
    }


# Integração com diagramar_livro_v2
def enriquece_metadados_livro(pdf_original: str, dc_existente: DublinCore) -> DublinCore:
    """
    Enriquece metadados existentes com extração do PDF original.
    Mantém o que já tem, preenche o que falta.
    """
    dc_pdf = extrai_metadados_pdf_completo(pdf_original)

    # Mescla: dc_existente tem prioridade, dc_pdf preenche lacunas
    if not dc_existente.title and dc_pdf.title:
        dc_existente.title = dc_pdf.title
    if not dc_existente.creator and dc_pdf.creator:
        dc_existente.creator = dc_pdf.creator
    if not dc_existente.subject and dc_pdf.subject:
        dc_existente.subject = dc_pdf.subject
    if not dc_existente.description and dc_pdf.description:
        dc_existente.description = dc_pdf.description
    if not dc_existente.publisher and dc_pdf.publisher:
        dc_existente.publisher = dc_pdf.publisher
    if not dc_existente.contributor and dc_pdf.contributor:
        dc_existente.contributor = dc_pdf.contributor
    if not dc_existente.date and dc_pdf.date:
        dc_existente.date = dc_pdf.date
    if not dc_existente.type_ and dc_pdf.type_:
        dc_existente.type_ = dc_pdf.type_
    if not dc_existente.format_ and dc_pdf.format_:
        dc_existente.format_ = dc_pdf.format_
    if not dc_existente.identifier and dc_pdf.identifier:
        dc_existente.identifier = dc_pdf.identifier
    if not dc_existente.source and dc_pdf.source:
        dc_existente.source = dc_pdf.source
    if not dc_existente.language and dc_pdf.language:
        dc_existente.language = dc_pdf.language
    if not dc_existente.relation and dc_pdf.relation:
        dc_existente.relation = dc_pdf.relation
    if not dc_existente.coverage and dc_pdf.coverage:
        dc_existente.coverage = dc_pdf.coverage
    if not dc_existente.rights and dc_pdf.rights:
        dc_existente.rights = dc_pdf.rights

    # Extrai ISBN/DOI do texto se disponível
    # (precisaria do texto extraído - opcional)

    return dc_existente


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python metadados_dublin.py arquivo.pdf")
        sys.exit(1)

    dc = extrai_metadados_pdf_completo(sys.argv[1])
    print("=== Metadados Dublin Core ===")
    for k, v in dc.to_dict().items():
        if v:
            if isinstance(v, list):
                print(f"  {k}: {', '.join(v)}")
            else:
                print(f"  {k}: {v}")