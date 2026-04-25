"""Cliente HTTP do site jurisprudencia.tjpi.jus.br.

Site Rails server-rendered, sem Cloudflare, sem login. Stack: httpx + bs4.
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://jurisprudencia.tjpi.jus.br"
SEARCH_PATH = "/jurisprudences/search"
DEBUG = os.environ.get("TJPI_DEBUG") == "1"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


@dataclass
class Resultado:
    titulo: str
    numero_cnj: Optional[str]
    tipo_decisao: Optional[str]
    assunto: Optional[str]
    publicacao: Optional[str]
    ementa: Optional[str]
    url: str
    ementa_truncada: bool = False  # True quando o preview do servidor cortou antes de "Ementa:"

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.ementa_truncada:
            d["_aviso"] = (
                "Ementa nao disponivel na listagem (preview do servidor truncado "
                "antes da secao 'Ementa:'). Para obter a ementa real e o inteiro teor, "
                "chame ler_decisao(url). NAO cite o conteudo deste campo em pecas."
            )
        return d

@dataclass
class Decisao:
    url: str
    numero_cnj: Optional[str] = None
    tipo_decisao: Optional[str] = None
    classe_judicial: Optional[str] = None
    relator: Optional[str] = None
    orgao_julgador: Optional[str] = None
    orgao_julgador_colegiado: Optional[str] = None
    competencia: Optional[str] = None
    assunto_principal: Optional[str] = None
    autor: Optional[str] = None
    reu: Optional[str] = None
    publicacao: Optional[str] = None
    ementa: Optional[str] = None
    inteiro_teor: Optional[str] = None
    citacao_oficial: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def citacao_abnt(self) -> str:
        head = "TJ-PI"
        if self.classe_judicial:
            head = f"{head} - {self.classe_judicial}"
        if self.numero_cnj:
            head = f"{head}: {self.numero_cnj}"
        partes = [head]
        if self.relator:
            partes.append(f"Relator: {self.relator}")
        if self.orgao_julgador_colegiado:
            partes.append(self.orgao_julgador_colegiado)
        if self.publicacao:
            partes.append(f"Data de Publicação: {self.publicacao}")
        return f"({', '.join(partes)})"


_CNJ_RE = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
_DATA_RE = re.compile(r"\d{2}/\d{2}/\d{4}")

# Regex para o INICIO da ementa
_EMENTA_START_RE = re.compile(r"\bEmenta\s*[:\-–]\s*", re.I)

# Regex para o FIM da ementa (primeiro marcador encontrado)
_EMENTA_END_RE = re.compile(
    r"\s+(?:"
    r"DECIS[ÃA]O\s+TERMINATIVA"
    r"|I\s*[-–]\s*RELAT[ÓO]RIO"
    r"|RELAT[ÓO]RIO\b"
    r"|VOTO\b"
    r"|AC[ÓO]RD[ÃA]O\b"
    r"|ACORDAM\b"
    r"|Cumpra-se"
    r"|Teresina,"
    r")",
    re.I,
)


def _clean(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    out = re.sub(r"\s+", " ", s).strip()
    return out or None


def _extract_ementa(text: Optional[str]) -> Optional[str]:
    """Localiza 'Ementa:' e fatia até o próximo marcador de RELATORIO/VOTO/etc.
    Sem lookahead/non-greedy — busca-por-índice, mais robusto que regex composto.
    """
    if not text:
        return None
    m = _EMENTA_START_RE.search(text)
    if not m:
        if DEBUG:
            print("  [DEBUG] _extract_ementa: 'Ementa' nao encontrada", file=sys.stderr)
        return None
    rest = text[m.end():]
    m_end = _EMENTA_END_RE.search(rest)
    end = m_end.start() if m_end else len(rest)
    if DEBUG:
        print(
            f"  [DEBUG] _extract_ementa: text_len={len(text)} "
            f"start={m.end()} end_offset={end} marker={'sim' if m_end else 'nao'}",
            file=sys.stderr,
        )
    return _clean(rest[:end])


_SIDEBAR_LABELS = {
    "processo": "numero_cnj",
    "relator(a)": "relator",
    "relator": "relator",
    "orgao julgador": "orgao_julgador",
    "orgao julgador colegiado": "orgao_julgador_colegiado",
    "classe judicial": "classe_judicial",
    "competencia": "competencia",
    "assunto principal": "assunto_principal",
    "autor": "autor",
    "reu": "reu",
    "publicacao": "publicacao",
}


def _norm_label(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip().rstrip(":")


def _parse_resultados(html: str, base_url: str = BASE_URL,
                      limite: Optional[int] = None) -> list[Resultado]:
    soup = BeautifulSoup(html, "lxml")
    resultados: list[Resultado] = []
    seen = set()

    selector = 'h5 a[href*="/jurisprudences/"][href*="/public"]'
    for a_tag in soup.select(selector):
        href = a_tag.get("href")
        if not href or href in seen:
            continue
        seen.add(href)
        url = urljoin(base_url, href)

        badge = a_tag.select_one("span.badge")
        tipo_decisao = _clean(badge.get_text()) if badge else None

        full_text = _clean(a_tag.get_text(" ", strip=True)) or "(sem titulo)"

        m_cnj = _CNJ_RE.search(full_text)
        numero_cnj = m_cnj.group(0) if m_cnj else None

        assunto = full_text
        if numero_cnj:
            assunto = full_text.split(numero_cnj, 1)[0]
        if tipo_decisao:
            assunto = (assunto or "").replace(tipo_decisao, "")
        assunto = _clean(assunto)

        h6 = a_tag.find_next("h6")
        publicacao = None
        if h6:
            t = _clean(h6.get_text(" ", strip=True))
            if t:
                m = _DATA_RE.search(t)
                publicacao = m.group(0) if m else t.replace("Publicação:", "").strip()

        txt_div = a_tag.find_next("div", class_="text-justify")
        raw_text = _clean(txt_div.get_text()) if txt_div else None
        ementa = _extract_ementa(raw_text) or raw_text

        resultados.append(Resultado(
            titulo=full_text,
            numero_cnj=numero_cnj,
            tipo_decisao=tipo_decisao,
            assunto=assunto,
            publicacao=publicacao,
            ementa=ementa,
            url=url,
        ))

        if limite and len(resultados) >= limite:
            break

    return resultados


def _parse_decisao(html: str, url: str) -> Decisao:
    soup = BeautifulSoup(html, "lxml")
    d = Decisao(url=url)

    for strong in soup.find_all("strong"):
        text = _clean(strong.get_text(" ", strip=True))
        if not text:
            continue
        key = _norm_label(text)
        if key not in _SIDEBAR_LABELS:
            continue
        p = strong.find_next("p", class_="text-muted")
        if p is None:
            continue
        value = _clean(p.get_text(" ", strip=True))
        if value:
            setattr(d, _SIDEBAR_LABELS[key], value)

    badge = soup.find("span", class_=re.compile(r"\bbg-danger\b"))
    if badge:
        d.tipo_decisao = _clean(badge.get_text(" ", strip=True))

    main_card = soup.find("div", class_=re.compile(r"\bcard-body\b"))
    if main_card:
        text_just_divs = main_card.find_all("div", class_="text-justify")
        if text_just_divs:
            d.inteiro_teor = _clean(text_just_divs[0].get_text())
            for tj in text_just_divs[1:]:
                t = _clean(tj.get_text(" ", strip=True))
                if t and "TJPI" in t and ")" in t:
                    d.citacao_oficial = t
                    break

    d.ementa = _extract_ementa(d.inteiro_teor)
    return d


class TJPIClient:
    def __init__(self, timeout: float = 30.0):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def buscar_jurisprudencia(
        self, query: str, limite: int = 10, page: int = 1,
    ) -> list[Resultado]:
        if not query or not query.strip():
            raise ValueError("query vazia")
        params = {"q": query.strip()}
        if page and page > 1:
            params["page"] = str(page)
        r = await self._client.get(SEARCH_PATH, params=params)
        r.raise_for_status()
        return _parse_resultados(r.text, base_url=BASE_URL, limite=limite)

    async def ler_decisao(self, url_or_id: str) -> Decisao:
        if not url_or_id:
            raise ValueError("url_or_id vazio")
        if url_or_id.isdigit():
            url = f"{BASE_URL}/jurisprudences/{url_or_id}/public"
        elif url_or_id.startswith("http"):
            url = url_or_id
        elif url_or_id.startswith("/"):
            url = urljoin(BASE_URL, url_or_id)
        else:
            raise ValueError(f"URL ou ID invalido: {url_or_id}")
        r = await self._client.get(url)
        r.raise_for_status()
        return _parse_decisao(r.text, url)
