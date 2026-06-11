# PRD — NDados Pipedrive MCP

> **Vault wrapper:** `THE-SECOND/projetos/mcp-pipedrive/README.md` mantém Discovery, DoD do experimento, stakeholders, decisões de inovação. Leia primeiro para contexto humano.
>
> **Goal:** servidor MCP que conecta Claude (Code e Desktop) ao Pipedrive da Poli Júnior em leitura. Cinco cargos comerciais (DE, Diretor Comercial, Gerente, LO, CN) ganham acesso conversacional ao CRM via Skills da PJ que compõem em cima de primitives. O MCP substitui exportação manual de planilhas e bloco de notas paralelo.

## Princípios de design

1. **Primitives composáveis, não relatórios fechados.** Tools entregam blocos flexíveis (filtros, agregações, gets).
2. **Read-only no v1.** Sem escrita. Ações em massa (mover cards, preencher campo em lote, mover de funil — JTBD do Diretor) ficam para v2 com discussão de permissões.
3. **Filtros são o eixo transversal.** A primitive central é `list_deals_with_filters` composta por núcleo × portfólio × CN × canal × etapa × período × status × label × owner. Toda analytics depende dela.
4. **Histórico via event store próprio (v2), não snapshot periódico.** Pipedrive não expõe API histórica bulk; webhooks v2 entregam `current` + `previous` mas não retêm. v1 vive no estado atual; v2 introduz webhook listener + event store + backfill.
5. **TDD obrigatório.** Toda tool ganha unit test contra Pipedrive mockado antes do merge. Integration tests opcionais contra sandbox para intent tools que compõem múltiplas chamadas.
6. **Context window aware.** Toda tool de leitura aceita parâmetro `include_fields: list[str]` para o caller restringir campos retornados. Default é subset enxuto (id, title, value, stage, owner.name, status, label); custom fields opcionais só entram quando pedidos por chave Pipedrive ou alias legível (via `fields.py`). Reduz pressão na janela do LLM, força explicitude sobre o que importa em cada query e baixa custo de chamada. Implementação compartilhada em util de serialização.

## Personas e JTBD (resumo executivo)

| Persona | JTBD principal | Tools v1 que cobrem |
|---|---|---|
| Diretor Comercial (Enzo Rego) | Filtros granulares + agregação cross-núcleo + diagnóstico estratégico | A1 + B1 + B2 + B3 |
| Gerente Comercial de Núcleo (Matheus, NDados) | Planning, accomps, "como foi a proposta", projeção | A1 + B1 + B3 + C2 |
| Líder de Outbound (Felipe) | Estado de cada card + agregação por owner + SQL + hot/cold | A1 + B3 + C2 |
| CN (equipe NDados) | Briefing pré-AT + contexto rico de cards atrelados + montar propostas (CNs preferem UI do Pipedrive para CRUD operacional) | C1 + C2 |

Detalhamento das benchs em `THE-SECOND/projetos/mcp-pipedrive/materials/benchs/`.

## Status atual do código

| Componente | Estado | Arquivo |
|---|---|---|
| FastMCP server | ✅ scaffold | `server.py` |
| Pipedrive field map + resolvers | ✅ pronto | `fields.py` |
| Pipedrive async HTTP client | ✅ scaffold | `pipedrive.py` |
| Pipeline Drive + AssemblyAI + Docling | ✅ pronto | `pipeline/` |
| Tools CN write-side (`resolve_deal`, `log_meeting`, `register_prospect`, `advance_deal`) + `find_deals` | ⚠️ presentes mas pouco úteis — CNs preferem UI do Pipedrive para escrita; `find_deals` fica redundante com A1. Candidatas a deprecação em C5 (v2). Não contam como entrega de valor do v1. | `tools/*.py` |
| Tool intent `get_deal_context` | ✅ pronto — único do código existente que paga o uso | `tools/get_deal_context.py` + `plans/get-deal-context.md` |
| CRUD primitives Layer 1 robusta | ⏳ parcial | a portar do GarethWright/PipeDrive-MCP-Server (TS reference) para Python |
| Test harness | ❌ ausente | a criar em `tests/` (elemento D1) |
| Observabilidade | ❌ ausente | a definir (elemento D2) |

## Decisões de arquitetura (pinned)

- **Linguagem:** Python (decidido pelo código existente).
- **Framework MCP:** FastMCP.
- **HTTP client:** httpx async, com `asyncio.gather` para chamadas paralelas.
- **Transport:** stdio (Claude Desktop e Claude Code local).
- **Auth Pipedrive:** API token via query param `?api_token=...` (v1 padrão).
- **Histórico (v2):** webhooks v2 `change.deal` → event store próprio (SQLite local na v2.0, Supabase na v2.1) + backfill on-demand via `GET /v1/deals/{id}/flow` + reconciliação noturna via `GET /api/v2/deals?updated_since=...` como safety net. Decisão validada contra API docs em 2026-06-09.
- **Histórico (v1):** sem event store. Analytics no estado atual: B1 (conversão) usa `won_time` / `lost_time` / `add_time` filtrados por período; B2 (lost reasons) usa `status=lost` + `lost_time` no período; B3 (atividade) usa activities filtradas por `add_time` e owner.
- **TDD:** pytest. Unit tests obrigatórios via `respx` ou `httpx_mock`. Integration tests via marker `@pytest.mark.integration`, rodados sob demanda contra Pipedrive da PJ.
- **Output das tools:** markdown para humano (padrão de `get_deal_context`) + JSON estruturado via `structuredContent` quando aplicável para downstream/scripts.

### Realidades da API validadas em 2026-06-09 (durante implementação de A1)

- **Schema:** display names corretos da instância PJ — `"Motivo da perda"` (p minúsculo), `"Link (Drive) das Gravações"` (com parênteses), e existe um campo `"Núcleo"` separado de `"Etiqueta"`. Esses nomes oficiais ficam congelados nos integration tests.
- **`/v1/deals` filtro de data:** `start_date`/`end_date` filtram por `update_time`, NÃO por `add_time`. A1 aplica filtro de data em memória sobre `add_time` para honrar o contrato documentado. Implicação: B1, B2, B3 devem fazer o mesmo se filtrarem por janela.
- **Volume real:** instância PJ tem > 5000 deals. Paginação precisa de early-termination (A1 implementa `fetch_target = 5×limit` quando há post-filter, senão pára em `limit`).
- **`/v1/deals` filtra owner via `user_id`, NÃO `owner_id`.** O parâmetro `owner_id` é silenciosamente ignorado (retorna toda a base). Descoberto em 2026-06-09 quando A1 com `cn_name="Moreno"` retornou deals de outros owners. Corrigido em A1 e em `_fetch_filtered_deals` de analytics. Futuras tools devem usar `user_id`.
- **FieldsRegistry como infra implícita:** v1 tools dependem da classe `FieldsRegistry` (em `field_registry.py`). Carrega lazy via `await registry.ensure_loaded()` na primeira invocação de uma tool. Cache em disco em `.cache/pipedrive_schema.json`, TTL 6h. Spec em `plans/registry-field-registry.md`.
- **Layer 1 helper `pd_raw()`:** adicionado a `pipedrive.py` para casos paginados (devolve envelope completo incluindo `additional_data.pagination`). `pd()` original permanece intocada para chamadas não paginadas.
- **Docling removido (2026-06-09).** `process_pdf` e a dependência `docling` foram removidos de `requirements.txt` e do código (`pipeline/pipeline.py`, `pipeline/node_process_media_at_drive.py`). Motivo: docling traz transformers + torch como deps pesadas e PDF processing não é essencial para a frente comercial. Áudio/vídeo via AssemblyAI segue funcionando. PDFs no Drive folder são listados com nota "PDF processing disabled in v1".
- **Pagination cap escalado para 50000 deals em analytics tools.** A1 fica em 5000 (filtros precisam ser apertados); B1/B2/B3 precisam varrer toda a base para agregar. Helper `_fetch_filtered_deals` em `tools/analytics.py` aceita também `date_field` para B2 filtrar por `lost_time` em vez de `add_time`.
- **Observabilidade (D2):** `observability.py:instrument(fn)` envolve cada tool registrada e grava 1 linha JSON em `.observability/usage.jsonl` por chamada com `{timestamp, tool, latency_ms, status, error_type?, error_message?}`. Integrado em `server.py` via monkey-patch do `mcp.tool` antes das chamadas de `register()`. Falhas de log nunca propagam para o tool. Consulta: `wc -l .observability/usage.jsonl` para contagem; `jq` para análise.
- **Transcrição removida do escopo (2026-06-10).** A integração Drive + AssemblyAI dentro de `get_deal_context` foi removida. Motivo: diagnóstico revelou que folders típicos de gravação têm 7-8 arquivos `.mkv` de 500MB-1.4GB cada (~5-6 min só de download + minutos por arquivo no AssemblyAI). Trabalho desse tamanho não cabe no modelo síncrono de tool MCP em chat. Decisão estratégica: transcrição não é responsabilidade do MCP Pipedrive; deve ser uma tool separada (futuro MCP de meeting intelligence). `get_deal_context` agora retorna apenas dados de CRM (deal + contato + organização + notas + atividades). Removidos: `pipeline/`, deps `assemblyai`/`google-*`, scripts de diagnóstico de transcrição.

## Decomposição completa

Cada elemento aponta para plan próprio em `plans/<id>-<nome>.md` no padrão de `plans/get-deal-context.md` (signature, fluxo interno, field resolution, output, error handling, dependências).

### Fluxo A — Read primitives

| ID | Elemento | Persona-alvo | JTBD | v1 | Plan |
|---|---|---|---|---|---|
| A1 | `list_deals_with_filters` | todas | "listar cards com filtros compostos (núcleo, portfólio, CN, canal, etapa, período, status, label, owner) + `include_fields` para especificar campos retornados" | ✅ entregue 2026-06-09 | `plans/A1-list-deals-with-filters.md` |
| A2 | `get_deal_history` | Diretor, Gerente | "timeline completa de mudanças de um card (stage, value, owner, status)" | ❌ v2 | `plans/A2-get-deal-history.md` |
| A3 | event store pipeline (webhook listener + storage + backfill + reconciliação) | Gerente, Diretor | "comparação semana-a-semana do funil" | ❌ v2 | `plans/A3-event-store-pipeline.md` |
| A4 | gets básicos (`get_person`, `get_organization`, `get_notes`, `get_activities`, `list_stages`, `list_users`, `list_pipelines`) | todas | base composicional | ✅ entregue 2026-06-09 | `plans/A4-base-gets.md` |

### Fluxo B — Analytics

| ID | Elemento | Persona-alvo | JTBD | v1 | Plan |
|---|---|---|---|---|---|
| B1 | `get_conversion_rates` | DE, Diretor, Gerente | "taxa close/win por CN/portfólio/núcleo/canal/período. v1 não cobre transição entre etapas (precisa A2/A3)" | ✅ entregue 2026-06-09 | `plans/B-analytics.md` |
| B2 | `get_lost_reasons_analysis` | Diretor, Gerente | "motivos de perda agregados por período, owner, canal, portfólio" | ✅ entregue 2026-06-09 | `plans/B-analytics.md` |
| B3 | `get_owner_activity` | Diretor, LO | "quem tocou mais card no período, tasks atrasadas, hot/cold count" | ✅ entregue 2026-06-09 | `plans/B-analytics.md` |
| B4 | `get_funnel_time_analysis` | Diretor, Gerente | "tempo médio por etapa, com opção de excluir etapas, por CN/núcleo" | ❌ v2 (depende A2) | `plans/B4-get-funnel-time-analysis.md` |
| B5 | `get_forecast` | Gerente | "projeção de faturamento: cards no funil × taxa histórica do CN/núcleo" | ❌ v2 (depende A2) | `plans/B5-get-forecast.md` |
| B6 | `get_funnel_snapshot` | Gerente, Diretor | "distribuição atual do funil + diff vs ponto temporal anterior" | ❌ v2 (depende A3) | `plans/B6-get-funnel-snapshot.md` |

### Fluxo C — Card-level

| ID | Elemento | Persona-alvo | JTBD | v1 | Plan |
|---|---|---|---|---|---|
| C1 | `get_deal_context` | CN, todas | briefing completo de um deal com notas, atividades, transcrições | ✅ feito | `plans/get-deal-context.md` |
| C2 | ~~`ask_about_deal`~~ — cancelado | LO, Gerente | sobreposição com C1 `get_deal_context` (decidido 2026-06-09). v1.1 vai refatorar C1 para usar FieldsRegistry + adicionar `format='dict'` em vez de criar nova tool. | ❌ cancelado | — |
| C3 | `get_proposals_in_week` | Gerente | "propostas marcadas/apresentadas na semana, com canal, owner, ticket" | ❌ v2 | `plans/C3-get-proposals-in-week.md` |
| C4 | `get_card_activities_summary` | Gerente | "como foi a proposta X — resumo de notas e atividades, objeções" | ❌ v2 | `plans/C4-get-card-activities-summary.md` |
| C5 | deprecação/remoção das tools CN write-side (`resolve_deal`, `log_meeting`, `register_prospect`, `advance_deal`) e `find_deals` | mantém repo limpo, remove ruído da superfície de tools para o LLM | ❌ v2 | `plans/C5-deprecacao-tools-cn.md` |

### Fluxo D — Infra transversal

| ID | Elemento | Cobre | v1 | Plan |
|---|---|---|---|---|
| D1 | test harness (pytest + respx + fixtures + integration marker) | TDD obrigatório, baseline de qualidade | ✅ mínimo entregue 2026-06-09 (sustenta A1+FieldsRegistry) | `plans/D1-test-harness.md` |
| D2 | observabilidade (uso por tool, latência, erros em log estruturado) | sustenta DoD outlier ("uso documentado") | ✅ entregue 2026-06-09 | `plans/D2-observabilidade.md` |
| D3 | skills PJ que orquestram por cargo | especialização por persona | ❌ v2 | `plans/D3-skills-pj.md` |

## v1 — escopo congelado

**8 elementos:** A1, A4, B1, B2, B3, C2, D1, D2.

**Mais:** tools já existentes (C1) entram no v1 sem retrabalho. C5 (revisão CN à luz das benchs) fica fora — entra como hotfix se pilot revelar gap.

**Fora do v1, justificativa:**

- A2, A3 → event store próprio é projeto sozinho; v1 entrega valor sobre estado atual sem ele.
- B4, B5, B6 → dependem de A2 (timeline per-deal) ou A3 (event store cross-deal).
- C3, C4 → derivados triviais sobre A1+A4 após v1 estabilizar; melhor adicionar em resposta a feedback do pilot.
- D3 → skills PJ vivem fora deste repo; entram após v1 ter early adopter validando que as primitives certas existem.

## Priority order do v1

Sequência rígida nos primeiros três, depois paralelo:

1. **D1 — test harness.** Sem isso, TDD não roda. Define `tests/unit/`, `tests/integration/`, `conftest.py` com fixtures, marker `integration`, mocks de Pipedrive.
2. **A1 — `list_deals_with_filters`.** Toda analytics descansa em filtros. Sem A1, B1/B2/B3 não compilam.
3. **A4 — gets básicos.** Persons, orgs, notes, activities, stages, users, pipelines. Downstream depende.
4. **B1, B2, B3, C2 em paralelo.** Após A1+A4, esses quatro podem ser desenvolvidos por agentes em paralelo. Plans próprios, suites próprias, sem dependência cruzada.
5. **D2 — observabilidade.** Plugada como decorador/middleware nas tools existentes. Não bloqueia entrega; é critério para DoD outlier.

## TDD approach

**Unit tests (obrigatório por tool):**

- Arquivo: `tests/unit/test_<tool>.py` para cada tool registrada.
- Pipedrive HTTP layer mockado via `respx` (preferido) ou `httpx_mock`.
- Cobertura mínima: happy path, edge cases (campo vazio, deal não encontrado, filtros conflitantes ou vazios), erro de API (timeout, 401, 5xx).
- Roda em <5s por test, sem rede, sem env vars secretas.

**Integration tests (opcional por tool, obrigatório para intent tools de Fluxo B e C):**

- Arquivo: `tests/integration/test_<tool>.py` com marker `@pytest.mark.integration`.
- Roda contra Pipedrive da PJ usando token de teste (ou conta sandbox se existir).
- Skipped por padrão; rodados via `pytest -m integration` antes de merge significativo ou release.
- Valida: shape de resposta real, presença de fields críticos, comportamento com dados de produção.

**Test-first workflow para cada novo elemento:**

1. Ler ou escrever spec no plan correspondente (`plans/<id>.md`).
2. Escrever unit tests cobrindo a spec — vermelho.
3. Implementar tool até passar — verde.
4. Refatorar mantendo verde.
5. Adicionar integration test se intent tool de B ou C.
6. Atualizar status do elemento na tabela deste PRD (`✅`).

**Fixtures compartilhadas (em `tests/conftest.py`):**

- `mock_pipedrive_client` — httpx mock pré-configurado com base URL e token fake.
- `sample_deal_response`, `sample_person_response`, `sample_org_response`, etc. — JSONs realistas baseados na API v1.
- `fields_resolver` — instância usando `fields.py` para resolução de enums em testes.
- `pipedrive_api_token` (integration) — lido de env var `PIPEDRIVE_API_TOKEN_TEST`.

## Definition of Done

**Por elemento v1:**

- Plan escrito em `plans/<id>-<nome>.md` seguindo o padrão de `plans/get-deal-context.md`.
- Unit tests verdes localmente, `pytest tests/unit/test_<tool>.py -v` passa.
- Integration test rodado se intent tool de B ou C, saída comparada à expectativa do plan.
- Tool registrada em `server.py` com `@mcp.tool()`.
- Anotações MCP corretas: `readOnlyHint=true` para tudo do v1, `idempotentHint=true` para queries, `openWorldHint=false`.
- Output respeita formato definido no plan (markdown + structuredContent quando aplicável).
- Mensagens de erro actionable: indicar qual campo falta, qual deal não foi encontrado, qual filtro entrou em conflito.

**Para o v1 inteiro sair para pilot:**

- 8 elementos com DoD individual atendido.
- Suite completa: `pytest tests/unit/ -v` e `pytest -m integration -v` passam.
- Pelo menos 1 sessão de uso real registrada por persona (CN, LO, Gerente, Diretor) em `THE-SECOND/projetos/mcp-pipedrive/sessions/`.
- README de instalação no repo atualizado para usuário não-dev (assume Claude Desktop instalado, configura via `mcp.json`).
- Métricas básicas (D2) gravando em log estruturado consultável.
- Card de Experimento atualizado em `THE-SECOND/projetos/mcp-pipedrive/materials/Experiment Description.md` com Learning Card preenchido.

## Como usar este PRD (para agente de IA)

1. **Leia o vault wrapper:** `THE-SECOND/projetos/mcp-pipedrive/README.md` e `THE-SECOND/projetos/mcp-pipedrive/state.md`.
2. **Leia este PRD inteiro.**
3. **Leia `plans/get-deal-context.md`** como referência do padrão de plan que os outros devem seguir.
4. **Escolha um elemento v1 ainda não feito**, seguindo a priority order acima.
5. **Leia o plan dele:** `plans/<id>.md`. Se ainda não existir, criar primeiro seguindo o padrão.
6. **Implemente seguindo TDD:** plan → test (vermelho) → tool (verde) → refator.
7. **Atualize o status do elemento** na tabela "Decomposição completa" deste PRD (`✅`).
8. **Anote a sessão de trabalho** em `THE-SECOND/projetos/mcp-pipedrive/sessions/YYYY-MM-DD-<elemento>.md` no vault (append-only, episódico).
