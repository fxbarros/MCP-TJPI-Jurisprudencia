"""Cliente HTTP do site jurisprudencia.tjpi.jus.br.

Site Rails server-rendered, sem Cloudflare, sem login. Stack: httpx + bs4.
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://jurisprudencia.tjpi.jus.br"
SEARCH_PATH = "/jurisprudences/search"
DEBUG = os.environ.get("TJPI_DEBUG") == "1"

# O servidor pagina de 25 em 25; usado pra detectar última página.
PAGE_SIZE = 25

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

# Formato CNJ (Recomendação 154/2024): decisões de 2025+ não têm o rótulo
# "Ementa:" — a ementa estruturada começa direto com o ramo do direito em
# caixa alta ("DIREITO CIVIL E PROCESSUAL CIVIL. APELAÇÃO CÍVEL. ...").
# Só vale como âncora se for caixa alta (o assunto do cabeçalho traz
# "Direito de Imagem" capitalizado, que não casa).
_EMENTA_CNJ_START_RE = re.compile(r"\bDIREITO\s+[A-ZÁÂÃÀÉÊÍÓÔÕÚÜÇ]{2,}")

# A âncora CNJ só é procurada no começo do texto: depois do cabeçalho
# (gabinete/processo/classe/partes) e antes do corpo, onde "DIREITO X"
# pode aparecer em citações.
_EMENTA_CNJ_JANELA = 3000

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


def _clean_multiline(s: Optional[str]) -> Optional[str]:
    """Como _clean, mas preserva quebras de linha entre parágrafos:
    colapsa espaços dentro de cada linha e descarta linhas vazias.
    """
    if s is None:
        return None
    linhas = (re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in s.splitlines())
    out = "\n".join(ln for ln in linhas if ln)
    return out or None


_BLOCK_TAGS = ("p", "div", "li", "tr", "blockquote",
               "h1", "h2", "h3", "h4", "h5", "h6")


def _block_text(el) -> str:
    """Extrai texto com \\n entre blocos (<p>, <div>, <br>...) e SEM separador
    dentro de cada bloco. Os dois lados do trade-off documentado na nota
    06b: get_text(" ") quebra palavras fragmentadas em tags inline
    ("E menta"); get_text() puro cola fim de parágrafo no início do
    seguinte ("CARDOSOAPELADO:"). Inserir \\n só nas fronteiras de bloco
    resolve ambos. Atenção: muta a árvore do `el` (parsear por chamada).
    """
    for br in el.find_all("br"):
        br.replace_with("\n")
    for tag in el.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.append("\n")
    return el.get_text()


def _extract_ementa(text: Optional[str]) -> Optional[str]:
    """Localiza o início da ementa e fatia até o próximo marcador de
    RELATORIO/VOTO/etc. Sem lookahead/non-greedy — busca-por-índice.

    Dois formatos reconhecidos:
    1. Clássico: rótulo "Ementa:" (decisões até ~2024).
    2. CNJ (Recomendação 154/2024, decisões 2025+): sem rótulo; a ementa
       estruturada começa com o ramo do direito em caixa alta
       ("DIREITO CIVIL E PROCESSUAL CIVIL. ...").
    """
    if not text:
        return None
    m = _EMENTA_START_RE.search(text)
    if m:
        rest = text[m.end():]
        formato = "classico"
    else:
        m_cnj = _EMENTA_CNJ_START_RE.search(text[:_EMENTA_CNJ_JANELA])
        if not m_cnj:
            if DEBUG:
                print(
                    "  [DEBUG] _extract_ementa: nem 'Ementa:' nem inicio CNJ "
                    "encontrados", file=sys.stderr,
                )
            return None
        rest = text[m_cnj.start():]
        formato = "cnj"
    m_end = _EMENTA_END_RE.search(rest)
    end = m_end.start() if m_end else len(rest)
    if DEBUG:
        print(
            f"  [DEBUG] _extract_ementa: formato={formato} text_len={len(text)} "
            f"end_offset={end} marker={'sim' if m_end else 'nao'}",
            file=sys.stderr,
        )
    return _clean_multiline(rest[:end])


# Padrões usados pra detectar quando o preview da listagem é só o cabeçalho do
# acórdão (sem chegar à seção "Ementa:"). Vide nota 06a-preview-trunca-listagem.
_CABECALHO_RE = re.compile(
    r"^\s*(?:"
    r"poder\s+judici"
    r"|tribunal\s+de\s+justi"
    r"|gabinete\s+d[oa]"
    r"|processo\s+n[º°\.:]"
    r"|classe\s*[:\.]"
    r"|apelante\s*[:\.]"
    r"|apelado\s*[:\.]"
    r")",
    re.IGNORECASE,
)


def _eh_cabecalho_acordao(texto: Optional[str]) -> bool:
    """Heurística: True quando `texto` parece ser apenas o cabeçalho do
    acórdão (sem ementa). Usada no fallback de `_parse_resultados` para
    decidir se é mais honesto retornar `ementa=None` em vez de devolver o
    cabeçalho como se fosse ementa.
    """
    if not texto:
        return False
    # Se "ementa" aparece no texto, definitivamente não é só cabeçalho.
    if "ementa" in texto.lower()[:1000]:
        return False
    return bool(_CABECALHO_RE.match(texto))

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

def _normalize_para_comparacao(s: str) -> str:
    """Normaliza texto para comparação tolerante: sem acentos, lowercase,
    espacos multiplos colapsados. Usada por verificar_citacao para que
    diferencas triviais (acentuacao, quebras de linha, multiplos espacos)
    nao causem falsos negativos.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


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
        raw_text = _clean_multiline(_block_text(txt_div)) if txt_div else None

        ementa_extraida = _extract_ementa(raw_text)
        if ementa_extraida:
            ementa = ementa_extraida
            ementa_truncada = False
        elif _eh_cabecalho_acordao(raw_text):
            # Servidor truncou antes da secao "Ementa:" e raw_text e so cabecalho.
            # Devolver None e mais honesto que entregar o cabecalho como ementa.
            ementa = None
            ementa_truncada = True
        else:
            # raw_text nao tem "Ementa:" mas tampouco e cabecalho tipico —
            # mantem comportamento antigo (preview cru, sem flag de truncado).
            ementa = raw_text
            ementa_truncada = False

        resultados.append(Resultado(
            titulo=full_text,
            numero_cnj=numero_cnj,
            tipo_decisao=tipo_decisao,
            assunto=assunto,
            publicacao=publicacao,
            ementa=ementa,
            url=url,
            ementa_truncada=ementa_truncada,
        ))
        if limite and len(resultados) >= limite:
            break

    return resultados


def _extract_total(html: str) -> Optional[int]:
    """Extrai o total real reportado pelo servidor na linha
    'Exibindo 1 - 25 de um total de <b>1262</b> jurisprudência(s)'.
    O <b> quebra o nó de texto, então acha o nó e pega o <b> seguinte.
    """
    soup = BeautifulSoup(html, "lxml")
    node = soup.find(string=re.compile(r"de um total de"))
    if node is None:
        return None
    b = node.find_next("b")
    if b is None:
        return None
    digitos = re.sub(r"\D", "", b.get_text())
    return int(digitos) if digitos else None


def _chave_dedup(r: Resultado):
    """O servidor às vezes indexa a mesma decisão sob IDs diferentes (mesmo
    CNJ, mesma publicação, URLs distintas). Dedup por conteúdo; sem CNJ,
    cai pra URL (não deduplica).
    """
    if r.numero_cnj:
        return (r.numero_cnj, r.publicacao, r.tipo_decisao, r.assunto)
    return r.url


@dataclass
class Busca:
    """Resultado de uma busca: itens + metadados do servidor."""
    resultados: list[Resultado] = field(default_factory=list)
    total_no_servidor: Optional[int] = None
    paginas_consultadas: int = 0
    duplicatas_removidas: int = 0


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
            d.inteiro_teor = _clean_multiline(_block_text(text_just_divs[0]))
            for tj in text_just_divs[1:]:
                t = _clean(tj.get_text(" ", strip=True))
                if t and "TJPI" in t and ")" in t:
                    d.citacao_oficial = t
                    break

    d.ementa = _extract_ementa(d.inteiro_teor)
    return d


class TJPIClient:
    # Decisões publicadas não mudam; cache em memória evita re-fetch no fluxo
    # típico buscar -> ler_decisao(X) -> verificar_citacao(X, trecho).
    _CACHE_MAX = 32

    # Teto de páginas por busca: limite máx (50) cabe em 2 páginas de 25;
    # a 3ª cobre perdas por dedup.
    _MAX_PAGINAS = 3

    def __init__(self, timeout: float = 30.0):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            follow_redirects=True,
        )
        self._cache_decisoes: OrderedDict[str, Decisao] = OrderedDict()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def buscar_jurisprudencia(
        self, query: str, limite: int = 10, page: int = 1,
    ) -> Busca:
        if not query or not query.strip():
            raise ValueError("query vazia")
        busca = Busca()
        vistos: set = set()
        pagina = max(1, page)
        while (len(busca.resultados) < limite
               and busca.paginas_consultadas < self._MAX_PAGINAS):
            params = {"q": query.strip()}
            if pagina > 1:
                params["page"] = str(pagina)
            r = await self._client.get(SEARCH_PATH, params=params)
            r.raise_for_status()
            busca.paginas_consultadas += 1
            if busca.total_no_servidor is None:
                busca.total_no_servidor = _extract_total(r.text)
            itens = _parse_resultados(r.text, base_url=BASE_URL)
            if not itens:
                break
            for res in itens:
                k = _chave_dedup(res)
                if k in vistos:
                    busca.duplicatas_removidas += 1
                    continue
                vistos.add(k)
                busca.resultados.append(res)
                if len(busca.resultados) >= limite:
                    break
            if len(itens) < PAGE_SIZE:
                break  # última página do servidor
            pagina += 1
        return busca

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
        if url in self._cache_decisoes:
            self._cache_decisoes.move_to_end(url)
            return self._cache_decisoes[url]
        r = await self._client.get(url)
        r.raise_for_status()
        decisao = _parse_decisao(r.text, url)
        self._cache_decisoes[url] = decisao
        if len(self._cache_decisoes) > self._CACHE_MAX:
            self._cache_decisoes.popitem(last=False)
        return decisao
    
    async def verificar_citacao(self, url_or_id: str, trecho: str) -> dict:
        """Confere se `trecho` aparece literalmente no inteiro_teor da decisao
        identificada por `url_or_id`. Comparacao tolerante a acentos, caixa
        e espacos multiplos. Usar antes de citar trechos entre aspas em pecas.
        """
        if not trecho or not trecho.strip():
            return {
                "valido": False,
                "motivo": "trecho vazio",
                "url": None,
            }
        decisao = await self.ler_decisao(url_or_id)
        if not decisao.inteiro_teor:
            return {
                "valido": False,
                "motivo": "inteiro_teor vazio ou nao extraido",
                "url": decisao.url,
            }
        teor_norm = _normalize_para_comparacao(decisao.inteiro_teor)
        trecho_norm = _normalize_para_comparacao(trecho)
        if trecho_norm in teor_norm:
            return {
                "valido": True,
                "motivo": "trecho encontrado no inteiro_teor",
                "url": decisao.url,
            }
        return {
            "valido": False,
            "motivo": (
                "trecho NAO encontrado no inteiro_teor. NAO cite entre aspas. "
                "Reescreva como parafrase ou abra a decisao manualmente."
            ),
            "url": decisao.url,
        }
