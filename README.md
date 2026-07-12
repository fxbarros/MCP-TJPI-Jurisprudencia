<h1 align="center">
    <img alt="MCP TJPI-Jurisprudência" src="https://raw.githubusercontent.com/fxbarros/MCP-TJPI-Jurisprudencia/main/docs/assets/banner.svg?sanitize=true">
    <br>
    <small>Pesquise acórdãos em linguagem natural. Cite com verificação literal.</small>
</h1>

<p align="center">
    <img alt="Python" src="https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white">
    <img alt="Testes" src="https://img.shields.io/badge/testes-10%20%E2%9C%93%20offline-brightgreen">
    <img alt="MCP" src="https://img.shields.io/badge/MCP-Claude%20Desktop-d97757">
    <img alt="Sem login" src="https://img.shields.io/badge/TJ--PI-sem%20login%20%C2%B7%20sem%20headless-8b0000">
    <img alt="Licença" src="https://img.shields.io/badge/licen%C3%A7a-MIT-blue">
</p>

<p align="center">
    <a href="#-o-que-faz"><strong>O que faz</strong></a>
    &middot;
    <a href="#%EF%B8%8F-as-3-ferramentas"><strong>Ferramentas</strong></a>
    &middot;
    <a href="#-anti-alucina%C3%A7%C3%A3o"><strong>Anti-alucinação</strong></a>
    &middot;
    <a href="#-instala%C3%A7%C3%A3o"><strong>Instalação</strong></a>
    &middot;
    <a href="#-testes"><strong>Testes</strong></a>
    &middot;
    <a href="#-limita%C3%A7%C3%B5es-conhecidas"><strong>Limitações</strong></a>
</p>

Servidor [MCP](https://modelcontextprotocol.io) que expõe a [jurisprudência oficial do Tribunal de Justiça do Piauí](https://jurisprudencia.tjpi.jus.br/) ao Claude Desktop: pesquisa de acórdãos em linguagem natural, leitura do inteiro teor e **citação ABNT pronta para colar na peça** — com verificação literal de cada trecho citado.

Sem login, sem Cloudflare, sem browser headless: o portal do TJ-PI é um site Rails público server-rendered, então `httpx + BeautifulSoup` bastam. Rápido, leve e sem fricção.

## ⚖️ O que faz

```
Você:    Busque 5 jurisprudências do TJ-PI sobre auto de infração ambiental em APP.
Claude:  [buscar_jurisprudencia] → 5 resultados com nº CNJ, ementa e URL.

Você:    A do desembargador Sebastião sobre competência supletiva é a melhor. Cita ABNT?
Claude:  [ler_decisao] →
         (TJ-PI - AGRAVO INTERNO CÍVEL: 0757817-66.2024.8.18.0000,
          Relator: SEBASTIAO RIBEIRO MARTINS,
          5ª Câmara de Direito Público,
          Data de Publicação: 05/02/2025)

Você:    Confere se esse trecho está mesmo no acórdão antes de eu citar.
Claude:  [verificar_citacao] → valido: True ✓
```

## 🛠️ As 3 ferramentas

| Ferramenta | O que faz |
|---|---|
| `buscar_jurisprudencia(query, limite, page)` | pesquisa com os [conectivos do site](https://jurisprudencia.tjpi.jus.br/jurisprudences/conectives) em português — `e`, `ou` (entre parênteses), `nao`, `"frase exata"`. Devolve título, nº CNJ formatado, tipo, assunto, publicação, preview da ementa, URL e o **total real** de resultados no servidor |
| `ler_decisao(url_or_id)` | metadados formais completos (relator, órgão colegiado, competência, partes...), ementa limpa, `inteiro_teor`, citação oficial do site e `citacao_abnt` montada. Aceita URL completa, caminho ou só o ID |
| `verificar_citacao(url_or_id, trecho)` | confere se o trecho aparece **literalmente** no inteiro teor — tolerante a acentos/caixa/espaços, implacável com paráfrase, omissão ou inversão de palavras |

## 🛡️ Anti-alucinação

Este servidor foi desenhado para uso forense real, onde citação inventada custa caro:

- **Ementas no formato CNJ**: o parser acompanha o padrão da Recomendação CNJ 154/2024 (sem rótulo "Ementa:"), adotado pelo TJ-PI desde 2025.
- **Dedup**: o portal do TJ-PI devolve a mesma decisão sob IDs diferentes — o servidor deduplica e ainda expõe o `total_no_servidor` para você saber o universo real.
- **Preview ≠ fonte**: a ementa da listagem pode vir truncada; a docstring instrui o modelo a sempre chamar `ler_decisao` antes de citar.
- **`verificar_citacao` como portão final**: citação direta entre aspas só entra na peça se conferir literalmente no `inteiro_teor`.

## 📦 Instalação

```bash
git clone https://github.com/fxbarros/MCP-TJPI-Jurisprudencia.git jurisprudencia-tjpi-mcp
cd jurisprudencia-tjpi-mcp
uv sync
```

Registro no Claude Desktop — `~/Library/Application Support/Claude/claude_desktop_config.json` (preservando outros servidores que já existirem):

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

> ⚠️ **Substitua `SEU_USUARIO_MAC` pelo nome do seu usuário no macOS** (descubra com `whoami` no Terminal) — o placeholder é da máquina de quem instala, não do GitHub.
>
> ⚠️ Use o caminho **absoluto** do `uv` (confirme com `which uv` — pode ser `/opt/homebrew/bin/uv`). O Claude Desktop não herda o `$PATH` do shell.

Reinicie o Claude Desktop (Cmd+Q e abra de novo) e peça: *"Busque jurisprudência do TJ-PI sobre dano moral por negativação indevida"*.

## ✅ Testes

```bash
uv run pytest
```

10 testes, 100% offline: o parser é exercitado contra fixtures de HTML **real** do TJ-PI em `tests/fixtures/` — nenhuma requisição de rede. Diagnóstico verboso com `TJPI_DEBUG=1`.

## 🔍 Limitações conhecidas

- **Preview da listagem trunca a ementa** em algumas decisões (o servidor do TJ-PI corta antes de o texto começar). Quando ocorre, devolvemos o cabeçalho do acórdão como fallback — a ementa real vem via `ler_decisao`.
- **Filtros avançados não implementados**: hoje só `q` e `page`; classe, relator e data ficam para o futuro (PR welcome).

## ⚖️ Licença e autoria

[MIT](LICENSE). Construído por [Fábio Ximenes Barros](https://github.com/fxbarros). Sem afiliação com o TJ-PI — usa apenas o portal público de jurisprudência.

<p align="center"><sub>Arte do banner: original — marca dos projetos MCP do autor.</sub></p>
