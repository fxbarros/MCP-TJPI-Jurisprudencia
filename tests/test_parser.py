"""Teste offline do parser usando fixtures HTML.

Roda sem rede:
    uv run python tests/test_parser.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jurisprudencia_tjpi_mcp.tjpi_client import _parse_resultados, _parse_decisao


def _truncate(s, n=200):
    if not s:
        return s
    return s if len(s) <= n else s[:n] + " [...]"


def teste_busca():
    print("=" * 72)
    print("TESTE 1: parser de listagem (busca por 'dano moral')")
    print("=" * 72)
    fixture = ROOT / "tests" / "fixtures" / "busca_dano_moral.html"
    html = fixture.read_text(encoding="utf-8")
    resultados = _parse_resultados(html, limite=3)
    print(f"Resultados extraidos (limite=3): {len(resultados)}")
    for i, r in enumerate(resultados, 1):
        print(f"\n--- Resultado {i} ---")
        d = r.to_dict()
        d["ementa"] = _truncate(d.get("ementa"), 220)
        print(json.dumps(d, indent=2, ensure_ascii=False))


def teste_decisao():
    print("\n" + "=" * 72)
    print("TESTE 2: parser de decisao individual")
    print("=" * 72)
    fixture = ROOT / "tests" / "fixtures" / "decisao_27629540.html"
    html = fixture.read_text(encoding="utf-8")
    url = "https://jurisprudencia.tjpi.jus.br/jurisprudences/27629540/public"
    d = _parse_decisao(html, url)
    out = d.to_dict()
    out["inteiro_teor"] = _truncate(out.get("inteiro_teor"), 250)
    out["ementa"] = _truncate(out.get("ementa"), 250)
    out["citacao_oficial"] = _truncate(out.get("citacao_oficial"), 250)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nCitacao ABNT (montada): {d.citacao_abnt()}")


if __name__ == "__main__":
    teste_busca()
    teste_decisao()
