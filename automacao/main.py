#!/usr/bin/env python3
"""Automação de publicação e controle de anúncios Meta a partir das demandas do ClickUp.

Comandos:
  publicar [task_id]     cria campanhas para demandas novas (ou só a tarefa indicada)
  sincronizar            atualiza status/métricas e pausa o que passou da data
  pausar <task_id>       pausa todas as campanhas da demanda
  ativar <task_id>       reativa todas as campanhas da demanda

Variáveis de ambiente: META_ACCESS_TOKEN, CLICKUP_TOKEN, GOOGLE_API_KEY.
Sem META_ACCESS_TOKEN roda em modo simulação (DRY RUN): planeja e não publica nada.
Imprime "CHANGED" quando o estado.json foi alterado.
"""
import datetime as dt
import json
import os
import pathlib
import sys
import traceback

import planejador
from clickup_api import ClickUpApi
from drive import Drive
from http_util import ApiError
from meta_api import MetaApi

DIR = pathlib.Path(__file__).resolve().parent
CONFIG = DIR / "config.json"
ESTADO = DIR / "estado.json"


def agora_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def carregar(path):
    return json.loads(path.read_text(encoding="utf-8"))


def salvar_estado(estado, config):
    estado["atualizado_em"] = agora_iso()
    estado["verba_mes"] = planejador.resumo_verba_mes(config, estado)
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CHANGED")


def link_ads_manager(act, campanha_id):
    return ("https://adsmanager.facebook.com/adsmanager/manage/campaigns"
            f"?act={act}&selected_campaign_ids={campanha_id}")


def erro_legivel(exc):
    if isinstance(exc, ApiError) and isinstance(exc.body, dict):
        e = exc.body.get("error", {})
        return e.get("error_user_msg") or e.get("message") or str(exc)
    return str(exc)


# ── publicação ─────────────────────────────────────────────────
def preparar_midias(meta, drive, plano, demanda):
    """Sobe criativos na conta e devolve [(tipo, nome, midia)]."""
    conta, act = plano["conta"], plano["conta"]["ad_account_id"]
    midias = []
    if demanda["instagram"]:
        if not conta.get("instagram_user_id"):
            conta["instagram_user_id"] = meta.instagram_da_pagina(conta["page_id"])
        code = planejador.shortcode_instagram(demanda["instagram"])
        media_id = code and conta.get("instagram_user_id") and \
            meta.buscar_midia_instagram(conta["instagram_user_id"], code)
        if not media_id:
            raise planejador.DemandaInvalida(
                f"Post do Instagram não encontrado na conta da página: {demanda['instagram']}")
        midias.append(("instagram", f"IG {code}", {"media_id": media_id}))
    if demanda["drive"]:
        if not drive:
            raise planejador.DemandaInvalida("GOOGLE_API_KEY não configurada para ler o Drive")
        arquivos = drive.listar_midias(demanda["drive"])
        if not arquivos:
            raise planejador.DemandaInvalida(
                "Nenhuma imagem/vídeo no Drive (confira se o link está público)")
        for arq in arquivos[:10]:
            if arq["mimeType"].startswith("image/"):
                h = meta.enviar_imagem(act, drive.baixar(arq["id"]))
                midias.append(("imagem", arq["name"], {"hash": h}))
            else:
                vid, thumb = meta.enviar_video(act, drive.url_download(arq["id"]), arq["name"])
                midias.append(("video", arq["name"], {"video_id": vid, "thumb": thumb}))
    return midias


def publicar_plano(meta, drive, plano, demanda, status):
    conta, act = plano["conta"], plano["conta"]["ad_account_id"]
    campanha_id = meta.criar_campanha(act, plano["nome"], plano["objective"], status)
    try:
        conjunto_id = meta.criar_conjunto(
            act, campanha_id, plano["nome"], plano["otimizacao"], plano["destino"],
            plano["verba_centavos"], plano["inicio"], plano["fim"], plano["targeting"],
            conta["page_id"], status, conta.get("whatsapp"))
        anuncios = []
        for tipo, nome, midia in preparar_midias(meta, drive, plano, demanda):
            spec = planejador.spec_criativo(tipo, conta, plano["destino"], demanda["copy"], midia)
            criativo_id = meta.criar_criativo(act, f"{plano['nome']} | {nome}", spec)
            anuncios.append(meta.criar_anuncio(act, conjunto_id, f"{nome}", criativo_id, status))
    except Exception:
        # Não deixa campanha órfã pela metade na conta
        try:
            meta.delete(campanha_id)
        except Exception:
            pass
        raise
    return {
        "ad_account_id": act,
        "campanha_id": campanha_id,
        "conjunto_id": conjunto_id,
        "anuncios": anuncios,
        "verba_centavos": plano["verba_centavos"],
        "inicio": plano["inicio"],
        "fim": plano["fim"],
        "nome": plano["nome"],
        "link": link_ads_manager(act, campanha_id),
    }


def publicar(config, estado, meta, clickup, drive, so_task=None, dry_run=False):
    if so_task:
        tarefas = [clickup.tarefa(so_task)]
    else:
        corte = dt.datetime.fromisoformat(config["publicar_tarefas_criadas_apos"])
        tarefas = [t for t in clickup.tarefas_abertas(config["clickup_list_id"])
                   if int(t.get("date_created") or 0) / 1000 >= corte.timestamp()]
    mudou = False
    for tarefa in tarefas:
        demanda = planejador.demanda_da_tarefa(tarefa)
        if not demanda:
            continue
        atual = estado["campanhas"].get(demanda["task_id"])
        if atual and not so_task:
            continue  # já processada (publicada ou com erro: reprocessar via comando manual)
        if atual and atual["status"] in ("publicado", "pausado"):
            print(f"SKIP {demanda['task_id']}: já publicada")
            continue
        # Em reprocesso mantém as contas que já deram certo para não duplicar campanhas
        feitas = (atual or {}).get("contas", [])
        registro = {**demanda, "processado_em": agora_iso(), "contas": list(feitas)}
        try:
            planos = planejador.planejar(config, demanda, estado=estado)
            if dry_run:
                print(f"DRY RUN {demanda['task_id']} {demanda['projeto']}:")
                print(json.dumps(planos, ensure_ascii=False, indent=2))
                continue
            ja_publicadas = {c["ad_account_id"] for c in feitas}
            for plano in planos:
                if plano["conta"]["ad_account_id"] in ja_publicadas:
                    continue
                registro["contas"].append(
                    publicar_plano(meta, drive, plano, demanda, config["status_inicial"]))
            registro["status"] = "publicado"
            linhas = [f"✅ Anúncios publicados automaticamente ({config['status_inicial']})."]
            for c in registro["contas"]:
                linhas.append(f"• {c['nome']}\n  {len(c['anuncios'])} anúncio(s), "
                              f"verba R$ {c['verba_centavos'] / 100:.2f} até {c['fim'][:10]}\n"
                              f"  {c['link']}")
            comentario = "\n".join(linhas)
            print(f"PUBLICADO {demanda['task_id']} {demanda['projeto']}")
        except Exception as exc:
            registro["status"] = "erro"
            registro["erro"] = erro_legivel(exc)
            comentario = (f"⚠️ Publicação automática falhou: {registro['erro']}\n"
                          "Corrija e reprocesse pela aba Actions (publicar + ID da tarefa).")
            print(f"ERRO {demanda['task_id']}: {registro['erro']}", file=sys.stderr)
            if not isinstance(exc, planejador.DemandaInvalida):
                traceback.print_exc()
        estado["campanhas"][demanda["task_id"]] = registro
        mudou = True
        try:
            clickup.comentar(demanda["task_id"], comentario)
        except Exception as exc:
            print(f"Aviso: não comentou no ClickUp: {exc}", file=sys.stderr)
    return mudou


# ── controle ───────────────────────────────────────────────────
def resumir_metricas(insights):
    acoes = {a["action_type"]: float(a["value"]) for a in insights.get("actions", [])}
    return {
        "gasto": float(insights.get("spend", 0) or 0),
        "impressoes": int(insights.get("impressions", 0) or 0),
        "alcance": int(insights.get("reach", 0) or 0),
        "cliques": int(insights.get("clicks", 0) or 0),
        "conversas": int(acoes.get("onsite_conversion.messaging_conversation_started_7d", 0)),
        "leads": int(acoes.get("lead", 0)),
    }


def sincronizar(estado, meta):
    hoje = dt.date.today().isoformat()
    for registro in estado["campanhas"].values():
        if registro.get("status") not in ("publicado", "pausado"):
            continue
        for conta in registro["contas"]:
            try:
                st = meta.status(conta["campanha_id"])
                if registro["data_fim"] < hoje and st.get("status") == "ACTIVE":
                    meta.definir_status(conta["campanha_id"], "PAUSED")
                    st["status"] = "PAUSED"
                conta["status_meta"] = st.get("effective_status") or st.get("status")
                conta["metricas"] = resumir_metricas(meta.metricas(conta["campanha_id"]))
            except Exception as exc:
                conta["status_meta"] = f"erro: {erro_legivel(exc)}"
        ativos = [c for c in registro["contas"] if c.get("status_meta") == "ACTIVE"]
        registro["status"] = "publicado" if ativos else "pausado"
        registro["sincronizado_em"] = agora_iso()
    return True


def alterar_status(estado, meta, clickup, task_id, novo):
    registro = estado["campanhas"].get(task_id)
    if not registro or not registro.get("contas"):
        raise SystemExit(f"Tarefa {task_id} não tem campanhas publicadas")
    for conta in registro["contas"]:
        meta.definir_status(conta["campanha_id"], novo)
        conta["status_meta"] = novo
    registro["status"] = "publicado" if novo == "ACTIVE" else "pausado"
    acao = "reativadas" if novo == "ACTIVE" else "pausadas"
    try:
        clickup.comentar(task_id, f"⏯️ Campanhas {acao} manualmente pelo painel de automação.")
    except Exception as exc:
        print(f"Aviso: não comentou no ClickUp: {exc}", file=sys.stderr)
    return True


def main(argv):
    if not argv or argv[0] not in ("publicar", "sincronizar", "pausar", "ativar"):
        print(__doc__)
        return 2
    cmd, alvo = argv[0], (argv[1].strip() if len(argv) > 1 and argv[1].strip() else None)
    config, estado = carregar(CONFIG), carregar(ESTADO)

    token = os.environ.get("META_ACCESS_TOKEN")
    dry_run = not token
    if dry_run:
        print("META_ACCESS_TOKEN ausente: modo simulação (nada será publicado)")
    meta = MetaApi(token, config["graph_api_version"]) if token else None
    clickup_token = os.environ.get("CLICKUP_TOKEN")
    clickup = ClickUpApi(clickup_token) if clickup_token else None
    google_key = os.environ.get("GOOGLE_API_KEY")
    drive = Drive(google_key) if google_key else None

    if cmd == "publicar":
        if not clickup:
            raise SystemExit("CLICKUP_TOKEN é obrigatório para ler as demandas")
        mudou = publicar(config, estado, meta, clickup, drive, alvo, dry_run)
    elif dry_run:
        return 0
    elif cmd == "sincronizar":
        mudou = sincronizar(estado, meta)
    else:
        if not alvo:
            raise SystemExit(f"Informe o ID da tarefa do ClickUp para {cmd}")
        mudou = alterar_status(estado, meta, clickup, alvo,
                               "PAUSED" if cmd == "pausar" else "ACTIVE")
    if mudou:
        salvar_estado(estado, config)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
