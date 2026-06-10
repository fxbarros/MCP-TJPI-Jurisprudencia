"""Testes offline do parser usando fixtures HTML reais.

Roda sem rede:
    uv run pytest

Fixtures:
- busca_dano_moral.html / decisao_27629540.html: formato antigo, com
  rótulo "Ementa:" (capturadas em 04/2026, decisões de 2025).
- busca_dano_moral_municipio.html / decisao_32603698.html: formato CNJ
  (Recomendação 154/2024), SEM rótulo "Ementa:" (capturadas em 06/2026).
"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jurisprudencia_tjpi_mcp.tjpi_client import (  # noqa: E402
    _chave_dedup,
    _extract_ementa,
    _extract_total,
    _parse_decisao,
    _parse_resultados,
)

FIXTURES = ROOT / "tests" / "fixtures"


def _html(nome: str) -> str:
    return (FIXTURES / nome).read_text(encoding="utf-8")


# ---------------------------------------------------------------- formato antigo

def test_busca_formato_antigo():
    resultados = _parse_resultados(_html("busca_dano_moral.html"), limite=3)
    assert len(resultados) == 3
    r1 = resultados[0]
    assert r1.numero_cnj == "0800002-98.2022.8.18.0062"
    assert r1.tipo_decisao == "Decisão Terminativa de 2º Grau"
    assert r1.ementa and "DANO MORAL CONFIGURADO" in r1.ementa
    assert r1.ementa_truncada is False
    assert r1.url.startswith("https://jurisprudencia.tjpi.jus.br/jurisprudences/")


def test_decisao_formato_antigo():
    d = _parse_decisao(_html("decisao_27629540.html"), "test")
    assert d.numero_cnj == "0802237-49.2024.8.18.0068"
    assert d.relator == "JOSE WILSON FERREIRA DE ARAUJO JUNIOR"
    assert d.orgao_julgador_colegiado == "2ª Câmara Especializada Cível"
    assert d.ementa and "APELAÇÃO CÍVEL" in d.ementa
    assert d.inteiro_teor
    assert d.citacao_oficial and "TJPI" in d.citacao_oficial
    abnt = d.citacao_abnt()
    assert "TJ-PI" in abnt and "0802237-49.2024.8.18.0068" in abnt


# ---------------------------------------------------------------- formato CNJ

def test_decisao_formato_cnj_extrai_ementa():
    """Decisões 2025+ não têm rótulo 'Ementa:' — a ementa estruturada do CNJ
    começa com o ramo do direito em caixa alta. Era o bug do ementa=null."""
    d = _parse_decisao(_html("decisao_32603698.html"), "test")
    assert d.numero_cnj == "0817942-07.2020.8.18.0140"
    assert d.relator == "JOAO GABRIEL FURTADO BAPTISTA"
    assert d.ementa is not None
    assert d.ementa.startswith("DIREITO CIVIL E PROCESSUAL CIVIL")
    assert "RECURSO DESPROVIDO" in d.ementa
    # ementa termina antes do relatório
    assert "Trata-se de apelação" not in d.ementa


def test_inteiro_teor_preserva_paragrafos_sem_colar_palavras():
    """get_text() puro colava fim de parágrafo no início do seguinte
    ('CARDOSOAPELADO:'); _block_text insere \\n nas fronteiras de bloco."""
    d = _parse_decisao(_html("decisao_32603698.html"), "test")
    assert d.inteiro_teor
    assert "CARDOSOAPELADO" not in d.inteiro_teor
    assert "\n" in d.inteiro_teor


def test_busca_formato_cnj_previews_com_ementa():
    """Preview da listagem nova contém a ementa CNJ inteira — não pode mais
    ser marcado como ementa_truncada (era o falso positivo)."""
    resultados = _parse_resultados(_html("busca_dano_moral_municipio.html"))
    assert len(resultados) > 0
    com_ementa = [r for r in resultados if r.ementa and not r.ementa_truncada]
    # a grande maioria dos previews novos traz a ementa CNJ completa
    assert len(com_ementa) >= len(resultados) // 2
    assert any(r.ementa and r.ementa.startswith("DIREITO") for r in com_ementa)


def test_extract_total():
    total = _extract_total(_html("busca_dano_moral_municipio.html"))
    assert total == 1262


def test_chave_dedup_detecta_mesma_decisao_com_ids_diferentes():
    """O servidor indexa a mesma decisão sob IDs distintos; a chave de dedup
    por conteúdo (CNJ + publicação + tipo + assunto) precisa colidir."""
    resultados = _parse_resultados(_html("busca_dano_moral_municipio.html"))
    chaves = Counter(_chave_dedup(r) for r in resultados)
    urls = {r.url for r in resultados}
    assert len(urls) == len(resultados)  # URLs todas distintas...
    assert chaves.most_common(1)[0][1] >= 2  # ...mas há decisão repetida


# ---------------------------------------------------------------- _extract_ementa

def test_extract_ementa_rotulo_classico():
    texto = "PROCESSO N 123 Ementa: AGRAVO. PROVIMENTO. VOTO O relator decidiu"
    assert _extract_ementa(texto) == "AGRAVO. PROVIMENTO."


def test_extract_ementa_formato_cnj_sem_rotulo():
    texto = (
        "poder judiciário GABINETE APELADO: BANCO X "
        "DIREITO CIVIL. APELAÇÃO. RECURSO DESPROVIDO. "
        "DECISÃO TERMINATIVA RELATÓRIO Trata-se de apelação"
    )
    ementa = _extract_ementa(texto)
    assert ementa == "DIREITO CIVIL. APELAÇÃO. RECURSO DESPROVIDO."


def test_extract_ementa_nao_confunde_assunto_capitalizado():
    # "Direito de Imagem" (capitalizado, não caixa alta) não é âncora CNJ
    texto = "ASSUNTO: Direito de Imagem APELANTE: FULANO"
    assert _extract_ementa(texto) is None
