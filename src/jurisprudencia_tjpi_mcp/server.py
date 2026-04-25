"""Servidor MCP para o jurisprudencia.tjpi.jus.br.

Expõe duas tools ao Claude Desktop:
- buscar_jurisprudencia: pesquisa por palavra-chave
- ler_decisao: extrai metadados completos de uma decisão
"""
from __future__ import annotations

import asyncio
from typing import Optional

from mcp.server.fastmcp import FastMCP

from jurisprudencia_tjpi_mcp.tjpi_client import TJPIClient

mcp = FastMCP("jurisprudencia-tjpi")

_client: Optional[TJPIClient] = None
_client_lock = asyncio.Lock()


async def _get_client() -> TJPIClient:
    """Singleton do client, criado preguiçosamente na primeira chamada."""
    global _client
    async with _client_lock:
        if _client is None:
            _client = TJPIClient()
        return _client


@mcp.tool()
async def buscar_jurisprudencia(
    query: str,
    limite: int = 10,
    page: int = 1,
) -> list[dict]:
    """Pesquisa jurisprudência do TJ-PI por palavra-chave.

    Site oficial: https://jurisprudencia.tjpi.jus.br/
    Suporta conectivos (E, OU, NÃO, ASPAS para frase exata).

    Args:
        query: termos de busca. Ex: "dano moral", "responsabilidade civil objetiva",
               "construcao APP nascente", "súmula 18 TJPI".
        limite: número máximo de resultados a retornar (1-50). Default: 10.
        page: página dos resultados (25 por página no servidor). Default: 1.

    Returns:
        Lista de dicts com: titulo, numero_cnj, tipo_decisao, assunto,
        publicacao, ementa (preview), url. Use a `url` em `ler_decisao`
        para obter metadados formais completos.
    """
    limite = max(1, min(limite, 50))
    client = await _get_client()
    resultados = await client.buscar_jurisprudencia(
        query=query, limite=limite, page=page,
    )
    return [r.to_dict() for r in resultados]


@mcp.tool()
async def ler_decisao(url_or_id: str) -> dict:
    """Lê uma decisão individual do TJ-PI e extrai todos os metadados formais.

    Use APÓS `buscar_jurisprudencia` para montar citações em peças processuais.

    Args:
        url_or_id: URL completa (https://jurisprudencia.tjpi.jus.br/...),
                   caminho (/jurisprudences/N/public) ou apenas o ID numérico
                   (ex: "27629540").

    Returns:
        Dict com:
        - numero_cnj, classe_judicial, tipo_decisao
        - relator, orgao_julgador, orgao_julgador_colegiado, competencia
        - autor, reu, publicacao, assunto_principal
        - ementa (texto limpo, sem o cabeçalho do acórdão)
        - inteiro_teor (texto completo da decisão)
        - citacao_oficial (string já formatada pelo próprio site)
        - citacao_abnt (montada por nós: "(TJ-PI - Classe: CNJ, Relator: X, ...)")
    """
    client = await _get_client()
    d = await client.ler_decisao(url_or_id)
    out = d.to_dict()
    out["citacao_abnt"] = d.citacao_abnt()
    return out


def main() -> None:
    """Entry point pro `uv run jurisprudencia-tjpi-mcp`."""
    mcp.run()


if __name__ == "__main__":
    main()
