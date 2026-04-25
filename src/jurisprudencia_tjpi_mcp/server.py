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

    ⚠️ IMPORTANTE — ANTI-ALUCINAÇÃO:
    O campo `ementa` retornado é apenas um PREVIEW da listagem do servidor
    e pode estar TRUNCADO. NUNCA cite trechos do campo `ementa` desta tool
    em peças processuais, nem afirme que uma decisão "diz X" baseado apenas
    nesta resposta. Para qualquer afirmação sobre o conteúdo da decisão,
    chame `ler_decisao(url)` e use o campo `inteiro_teor`.

    Quando o servidor trunca antes da seção "Ementa:", o resultado virá com
    `ementa_truncada=true` e um campo `_aviso` explicando o problema. Nesses
    casos é OBRIGATÓRIO chamar `ler_decisao(url)` antes de qualquer citação.

    Site oficial: https://jurisprudencia.tjpi.jus.br/
    Suporta conectivos (E, OU, NÃO, ASPAS para frase exata).

    Args:
        query: termos de busca. Ex: "dano moral", "responsabilidade civil objetiva",
               "construcao APP nascente", "súmula 18 TJPI".
        limite: número máximo de resultados a retornar (1-50). Default: 10.
        page: página dos resultados (25 por página no servidor). Default: 1.

    Returns:
        Lista de dicts com: titulo, numero_cnj, tipo_decisao, assunto,
        publicacao, ementa (PREVIEW — pode estar truncado), ementa_truncada,
        url. Use `url` em `ler_decisao` antes de citar a decisão.
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

    Use SEMPRE esta tool antes de citar uma decisão em peça processual,
    mesmo que `buscar_jurisprudencia` já tenha retornado uma `ementa`. O
    preview da busca é insuficiente e pode ser apenas o cabeçalho do acórdão.

    ⚠️ REGRAS DE CITAÇÃO:
    - Para citações DIRETAS entre aspas, use APENAS texto presente no
      `inteiro_teor`. Confira a presença literal antes de citar.
    - Para teses, fundamentos ou trechos parafraseados, baseie-se no
      `inteiro_teor`, não em conclusões inferidas da `ementa` da listagem.
    - O campo `ementa` retornado por ESTA tool é confiável (extraído da
      página de detalhe), diferente da `ementa` truncada da listagem.

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
        - inteiro_teor (texto completo da decisão — fonte para citações)
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
