"""Servidor MCP para o jurisprudencia.tjpi.jus.br.

Expõe três tools ao Claude Desktop:
- buscar_jurisprudencia: pesquisa por palavra-chave
- ler_decisao: extrai metadados completos de uma decisão
- verificar_citacao: confere se um trecho aparece literalmente no inteiro teor
"""
from __future__ import annotations

import asyncio
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

from jurisprudencia_tjpi_mcp.tjpi_client import TJPIClient


def _erro_http(e: httpx.HTTPError) -> dict:
    """Resposta amigável pra falha de rede/HTTP — melhor que traceback cru."""
    return {
        "erro": (
            f"Falha ao consultar o site do TJ-PI ({type(e).__name__}: {e}). "
            "O site pode estar lento ou fora do ar. Tente novamente em "
            "instantes; se persistir, avise o usuário em vez de inventar "
            "resultados."
        ),
    }

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
) -> dict:
    """Pesquisa jurisprudência do TJ-PI por palavra-chave.

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    SINTAXE DE BUSCA — booleana, em PORTUGUÊS (não AND/OR/NOT em inglês)
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    Conectivos disponíveis:

      e          → todos os termos devem aparecer
                   Ex:  dano e moral e municipio

      ou         → pelo menos um termo (SEMPRE entre parênteses)
                   Ex:  (dano ou prejuizo) e municipio
                   ❌ ERRADO: dano ou prejuizo      (sem parênteses = erro)

      nao        → exclui termo (precede o termo a excluir)
                   Ex:  dano e moral nao trabalhista

      "..."      → frase exata (ordem e palavras literais)
                   Ex:  "responsabilidade civil objetiva"

      (...)      → agrupa para definir prioridade (como na matemática)
                   Ex:  (dano e (moral ou material)) nao familiar

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ESTRATÉGIA recomendada
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    1. Começar ESPECÍFICO (frase exata + 1-2 termos âncora):
         "responsabilidade objetiva" e municipio

    2. Se vier <5 resultados, AFROUXAR com sinônimos via OU:
         ("responsabilidade objetiva" ou "responsabilidade civil") e municipio

    3. Se vier muitos resultados ou ruído, RESTRINGIR com E ou NÃO:
         "responsabilidade objetiva" e municipio nao tributario

    4. Termos jurídicos compostos (ex: "boa-fé objetiva", "dano in re ipsa")
       SEMPRE entre aspas — sem aspas o servidor quebra em tokens soltos.

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ARMADILHAS — NÃO FAZER
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    ❌ NÃO use AND/OR/NOT em inglês — o servidor não interpreta.
    ❌ NÃO escreva em linguagem natural:
         "processos sobre dano moral envolvendo município de Teresina"
       Isso vira soup de tokens com E implícito → muito ruído.
       USE:  "dano moral" e teresina
    ❌ NÃO use OU sem parênteses — sintaxe inválida.
    ❌ NÃO chute conectivos em outros idiomas (et, vel, OR…) — só PT-BR.

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ANTI-ALUCINAÇÃO — uso do campo `ementa`
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    O campo `ementa` retornado é apenas um PREVIEW da listagem do servidor
    e pode estar TRUNCADO. NUNCA cite trechos do campo `ementa` desta tool
    em peças processuais, nem afirme que uma decisão "diz X" baseado apenas
    nesta resposta. Para qualquer afirmação sobre o conteúdo da decisão,
    chame `ler_decisao(url)` e use o campo `inteiro_teor`.

    Quando o servidor trunca antes da seção "Ementa:", o resultado virá com
    `ementa_truncada=true` e um campo `_aviso` explicando o problema. Nesses
    casos é OBRIGATÓRIO chamar `ler_decisao(url)` antes de qualquer citação.

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    Site oficial: https://jurisprudencia.tjpi.jus.br/
    Documentação dos conectivos: /jurisprudences/conectives

    Args:
        query: termos de busca usando a sintaxe booleana acima.
               Exemplos válidos:
                 - "dano moral" e municipio
                 - (apelacao ou agravo) e tributario nao iss
                 - "construcao em APP" e (nascente ou mata)
                 - sumula e tjpi nao revogada
        limite: número máximo de resultados a retornar (1-50). Default: 10.
                Acima de 25 o cliente busca páginas extras automaticamente.
        page: página inicial dos resultados (25 por página no servidor).
              Default: 1.

    Returns:
        Dict com:
        - resultados: lista de dicts (titulo, numero_cnj, tipo_decisao, assunto,
          publicacao, ementa [PREVIEW — pode estar truncado], ementa_truncada,
          url). Use `url` em `ler_decisao` antes de citar a decisão.
        - total_retornado: tamanho da lista
        - total_no_servidor: TOTAL REAL de decisões que a query encontrou no
          TJ-PI (independe de `limite`). Use ESTE número pra afirmar
          quantidades ("há N decisões sobre X no TJ-PI").
        - duplicatas_removidas (opcional): o servidor às vezes indexa a mesma
          decisão sob IDs diferentes; informa quantas repetições foram tiradas.
        - query_executada, page, limite: ecoa os parâmetros
        - erro (opcional): falha de rede/HTTP — não invente resultados.
        - _aviso (opcional): instrução de refino quando a busca volta vazia ou
          atinge o limite. PRESTE ATENÇÃO a este campo — ele indica que a query
          provavelmente precisa ser ajustada antes de prosseguir.
    """
    limite = max(1, min(limite, 50))
    client = await _get_client()
    try:
        busca = await client.buscar_jurisprudencia(
            query=query, limite=limite, page=page,
        )
    except httpx.HTTPError as e:
        return _erro_http(e)
    itens = [r.to_dict() for r in busca.resultados]
    resposta: dict = {
        "resultados": itens,
        "total_retornado": len(itens),
        "total_no_servidor": busca.total_no_servidor,
        "query_executada": query,
        "page": page,
        "limite": limite,
    }
    if busca.duplicatas_removidas:
        resposta["duplicatas_removidas"] = busca.duplicatas_removidas
    if len(itens) == 0:
        resposta["_aviso"] = (
            "ZERO RESULTADOS. A query provavelmente está restrita demais ou usa "
            "termos que o TJPI não emprega. Reformule antes de relatar 'nada "
            "encontrado' ao usuário. Tente, NESTA ORDEM: "
            "(1) afrouxar com OU adicionando sinônimos jurídicos "
            "(ex.: trocar 'dano e moral' por '(dano ou prejuizo) e (moral ou extrapatrimonial)'); "
            "(2) remover o termo menos essencial; "
            "(3) tirar aspas de frases muito específicas; "
            "(4) checar typo. Só conclua 'sem precedentes' após 2-3 reformulações."
        )
    elif (busca.total_no_servidor or 0) > len(itens):
        resposta["_aviso"] = (
            f"Mostrando {len(itens)} de {busca.total_no_servidor} resultado(s) "
            "que existem no servidor pra essa query. Para ver mais: aumente "
            "`limite`, chame com page seguinte, OU refine a query com "
            "'e <termo>' / 'nao <termo>' pra reduzir o universo. Ao afirmar "
            "quantidades, use total_no_servidor, não total_retornado."
        )
    return resposta


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
        - erro (opcional): falha de rede/HTTP — não invente conteúdo.
    """
    client = await _get_client()
    try:
        d = await client.ler_decisao(url_or_id)
    except httpx.HTTPError as e:
        return _erro_http(e)
    out = d.to_dict()
    out["citacao_abnt"] = d.citacao_abnt()
    return out

@mcp.tool()
async def verificar_citacao(url_or_id: str, trecho: str) -> dict:
    """Confere se um trecho aparece literalmente no inteiro_teor de uma decisão.

    ⚠️ USE SEMPRE antes de incluir uma citação direta entre aspas em peças
    processuais ou respostas finais. Se o resultado for `valido: False`,
    NÃO cite o trecho — reescreva como paráfrase ou abra a decisão.

    A comparação é tolerante a:
    - Diferenças de acentuação (ex: "decisao" casa com "decisão")
    - Diferenças de caixa (maiúscula/minúscula)
    - Espaços múltiplos, quebras de linha

    A comparação NÃO é tolerante a:
    - Substituição de palavras (paráfrase reescrita)
    - Omissão de palavras no meio do trecho
    - Inversão de ordem das palavras

    Args:
        url_or_id: URL completa, caminho ou ID numérico da decisão (mesmo
                   formato aceito por `ler_decisao`).
        trecho: o texto que se pretende citar entre aspas. Pode ter de
                3 palavras a vários parágrafos.

    Returns:
        Dict com:
        - valido (bool): True se o trecho foi encontrado no inteiro_teor.
        - motivo (str): explicação textual do resultado.
        - url (str | None): URL canônica da decisão verificada.
        - erro (opcional): falha de rede/HTTP — nesse caso NÃO conclua nada
          sobre a validade do trecho.
    """
    client = await _get_client()
    try:
        return await client.verificar_citacao(url_or_id, trecho)
    except httpx.HTTPError as e:
        return _erro_http(e)


def main() -> None:
    """Entry point pro `uv run jurisprudencia-tjpi-mcp`."""
    mcp.run()


if __name__ == "__main__":
    main()
