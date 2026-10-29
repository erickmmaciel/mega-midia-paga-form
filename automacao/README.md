# Automação Meta Ads

Publica automaticamente nas contas da Meta as demandas enviadas pelo formulário
e dá controle centralizado pelo painel (`/painel/`).

## Fluxo

1. Formulário (`/index.html`) cria a tarefa no ClickUp (lista Mega - Tasks).
2. GitHub Actions roda a cada 30 min (`.github/workflows/ads-automacao.yml`):
   - `publicar`: lê tarefas novas, cria campanha + conjunto + anúncios na conta do projeto.
   - `sincronizar`: atualiza status e métricas, pausa o que passou da data.
3. Resultado vai como comentário na tarefa do ClickUp e em `automacao/estado.json`.
4. Painel lê o `estado.json`: status, investimento, alcance, conversas, links.

## O que é criado por demanda

| Campo do form | Na Meta |
|---|---|
| Projeto | Conta(s) de anúncio, página, Instagram e cidade (config.json). "GWM (Cacoal + Pvh)" cria nas duas contas e divide a verba |
| Objetivo | Leads → `OUTCOME_LEADS` com conversas no WhatsApp. Branding/Evento → `OUTCOME_AWARENESS` (alcance) |
| Data de pausa | `end_time` do conjunto às 23:59 (horário de Rondônia) |
| Verba total | Orçamento vitalício do conjunto. Em branco usa `verba_total_padrao` do projeto |
| Drive + copy | Um anúncio por imagem/vídeo da pasta (até 10), com o copy como texto principal |
| Instagram | Usa o próprio post/reel como anúncio (mantém curtidas e comentários) |

Público: raio de 40 km da cidade, 18-65, Advantage+ público, posicionamentos automáticos.
Nome: `[AUTO] <projeto> | <objetivo> | até dd/mm | #<id da tarefa>`.

## Configuração (uma vez)

Secrets em Settings → Secrets and variables → Actions:

| Secret | Como obter |
|---|---|
| `META_ACCESS_TOKEN` | Business Manager → Usuários do sistema → gerar token com `ads_management`, `ads_read`, `business_management`, `pages_read_engagement`, `instagram_basic`. Dar acesso ao usuário do sistema nas contas e páginas dos projetos |
| `CLICKUP_TOKEN` | ClickUp → Settings → Apps → API Token |
| `GOOGLE_API_KEY` | Google Cloud → APIs → ativar Drive API → criar chave de API. Pastas do Drive precisam estar como "qualquer pessoa com o link" |

Sem `META_ACCESS_TOKEN` tudo roda em simulação (nada é publicado).

## Segurança

- Só publica tarefas criadas depois de `publicar_tarefas_criadas_apos` (config.json). Demandas antigas não são duplicadas.
- Cada tarefa é publicada uma vez. Se falhar no meio, a campanha incompleta é apagada e o erro aparece no ClickUp e no painel.
- `status_inicial`: `ACTIVE` publica direto. Troque para `PAUSED` se quiser revisar antes de ativar.

## Controle manual

Actions → "Automação Meta Ads" → Run workflow:

- `publicar` + ID da tarefa: reprocessa uma demanda com erro.
- `pausar` / `ativar` + ID da tarefa: pausa/reativa todas as campanhas da demanda.
- `sincronizar`: atualiza o painel na hora.

Pelo painel, o botão de cada campanha copia o ID e abre essa tela.

## Ajustes comuns (config.json)

- Novo projeto: adicionar em `projetos` (conta, página, Instagram, cidade) e a opção no `<select id="projeto">` do formulário.
- Leads por formulário instantâneo em vez de WhatsApp: em `objetivos.Leads` usar `"destino": "formulario"`, `"otimizacao": "LEAD_GENERATION"` e colocar `lead_form_id` na conta. A página Triumph ainda não aceitou os termos de Lead Ads.
- Verba mensal: `verba_mensal` por projeto é o teto do mês. Demanda que estoura o teto não é publicada e o erro aparece no ClickUp e no painel.
- WhatsApp: `whatsapp` em cada conta define o número dos anúncios de Leads. O número precisa estar conectado à página no Business Manager.

## Testes

```bash
python3 -m unittest discover -s automacao/tests
```
