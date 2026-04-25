# jurisprudencia-tjpi-mcp

Servidor MCP (Model Context Protocol) que expõe a [jurisprudência oficial do Tribunal de Justiça do Piauí](https://jurisprudencia.tjpi.jus.br/) ao Claude Desktop, permitindo pesquisar acórdãos em linguagem natural e gerar citações ABNT prontas para colar em peças processuais.

## O que faz

```
Você:    Busque 5 jurisprudências do TJ-PI sobre auto de infração ambiental em APP.
Claude:  [chama buscar_jurisprudencia] → 5 resultados com CNJ, ementa e URL.

Você:    A do desembargador Sebastião sobre competência supletiva é a melhor. Cita ABNT?
Claude:  [chama ler_decisao] →
         (TJ-PI - AGRAVO INTERNO CÍVEL: 0757817-66.2024.8.18.0000,
          Relator: SEBASTIAO RIBEIRO MARTINS,
          5ª Câmara de Direito Público,
          Data de Publicação: 05/02/2025)
```

## Tools expostas

### `buscar_jurisprudencia(query, limite=10, page=1)`

Pesquisa por palavra-chave. Suporta os mesmos [conectivos do site](https://jurisprudencia.tjpi.jus.br/jurisprudences/conectives) (`E`, `OU`, `NÃO`, `"frase exata"`).

Retorna lista de dicts com `titulo`, `numero_cnj` (já formatado), `tipo_decisao`, `assunto`, `publicacao`, `ementa` (preview) e `url`.

### `ler_decisao(url_or_id)`

Lê uma decisão individual e extrai todos os metadados formais.

Aceita URL completa, caminho relativo (`/jurisprudences/N/public`) ou apenas o ID numérico (`N`).

Retorna `numero_cnj`, `classe_judicial`, `tipo_decisao`, `relator`, `orgao_julgador`, `orgao_julgador_colegiado`, `competencia`, `autor`, `reu`, `publicacao`, `assunto_principal`, `ementa` (texto limpo), `inteiro_teor`, `citacao_oficial` (literal do site) e `citacao_abnt` (montada no formato `(TJ-PI - Classe: CNJ, Relator: X, Câmara, Data Pub. DD/MM/AAAA)`).

## Stack

- Python 3.12+ com [uv](https://docs.astral.sh/uv/)
- [httpx](https://www.python-httpx.org/) (HTTP async)
- [BeautifulSoup4 + lxml](https://www.crummy.com/software/BeautifulSoup/)
- [mcp[cli]](https://github.com/modelcontextprotocol/python-sdk) (FastMCP)

Sem login, sem Cloudflare, sem browser headless. O TJ-PI é um site Rails público server-rendered, então `httpx + bs4` basta.

## Instalação

```bash
git clone https://github.com/fxbarros/MCP-TJPI-Jurisprudencia.git jurisprudencia-tjpi-mcp
cd jurisprudencia-tjpi-mcp
uv sync
```

## Configuração no Claude Desktop

Abra `~/Library/Application Support/Claude/claude_desktop_config.json` e adicione o servidor (preservando outros que já existirem):

```json
{
  "mcpServers": {
    "jurisprudencia-tjpi": {
      "command": "/Users/SEU_USUARIO_MAC/.local/bin/uv",
      "args": [
        "--directory",
        "/Users/SEU_USUARIO_MAC/Desenvolvimento/jurisprudencia-tjpi-mcp",
        "run",
        "jurisprudencia-tjpi-mcp"
      ]
    }
  }
}
```

> ⚠️ **Substitua `SEU_USUARIO_MAC` pelo nome do seu usuário no macOS** (descubra rodando `whoami` no Terminal). Esse placeholder é da máquina de quem está instalando, não tem nada a ver com seu username do GitHub.
>
> ⚠️ Use também o caminho **absoluto** do `uv` (confirme com `which uv` — pode ser `/opt/homebrew/bin/uv` em vez de `/Users/.../.local/bin/uv` dependendo da instalação). O Claude Desktop não herda o `$PATH` do shell.

Reinicie o Claude Desktop (Cmd+Q e abra novamente). Em uma conversa nova, peça por exemplo: _"Busque jurisprudência do TJ-PI sobre dano moral por negativação indevida"_.

## Testes offline

Há fixtures HTML em `tests/fixtures/` para testar o parser sem rede:

```bash
uv run python tests/test_parser.py
```

Para diagnóstico verboso:

```bash
TJPI_DEBUG=1 uv run python tests/test_parser.py
```

## Estrutura

```
jurisprudencia-tjpi-mcp/
├── src/
│   └── jurisprudencia_tjpi_mcp/
│       ├── __init__.py
│       ├── tjpi_client.py     # cliente HTTP + parser bs4
│       └── server.py          # FastMCP entry point
├── tests/
│   ├── fixtures/              # HTML real do TJ-PI para teste offline
│   └── test_parser.py
└── pyproject.toml
```

## Limitações conhecidas

- **Preview da listagem trunca a ementa** em algumas decisões — o servidor corta o preview antes de "Ementa:" aparecer. Quando isso ocorre, devolvemos o cabeçalho do acórdão como fallback. Para a ementa real, chame `ler_decisao(url)`.
- **Filtros avançados não implementados**: hoje só `q` e `page`. Filtros por classe, tipo, relator e data ainda pendentes (PR welcome).

## Licença

MIT — veja [LICENSE](LICENSE).

## Autoria

Construído por [Fábio Ximenes Barros](https://github.com/fxbarros), com auxílio do Claude. Não tem afiliação com o TJ-PI; usa apenas o portal público de jurisprudência.
