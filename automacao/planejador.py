"""Transforma uma tarefa do ClickUp em um plano de publicação (sem chamar APIs)."""
import datetime as dt
import re

ROTULOS = ("Responsável", "Objetivo da campanha", "Observações", "Drive (imagens)",
           "Copy", "Instagram (Reels)", "Meta Ads", "Verba total")
_HEADER = re.compile(
    r"^[^\w\n]*(" + "|".join(re.escape(r) for r in ROTULOS) + r"):[ \t]*",
    re.MULTILINE)

WHATSAPP_LINK = "https://api.whatsapp.com/send"


class DemandaInvalida(Exception):
    pass


def parse_descricao(texto):
    """Lê os blocos "<emoji> Rótulo: valor" gerados pelo formulário."""
    campos = {}
    partes = list(_HEADER.finditer(texto or ""))
    for i, m in enumerate(partes):
        fim = partes[i + 1].start() if i + 1 < len(partes) else len(texto)
        campos[m.group(1)] = texto[m.end():fim].strip()
    return campos


def parse_verba(valor):
    """'R$ 1.500,50' -> 1500.5"""
    if not valor:
        return None
    num = re.sub(r"[^\d,\.]", "", valor)
    if "," in num or re.fullmatch(r"\d{1,3}(\.\d{3})+", num):
        num = num.replace(".", "").replace(",", ".")
    try:
        return float(num) if num else None
    except ValueError:
        return None


def shortcode_instagram(url):
    m = re.search(r"instagram\.com/(?:[\w.]+/)?(?:p|reel|reels|tv)/([\w-]+)", url or "")
    return m.group(1) if m else None


def demanda_da_tarefa(tarefa):
    projeto = tarefa["name"].rsplit(" - ", 1)[0].strip()
    campos = parse_descricao(tarefa.get("description") or tarefa.get("text_content") or "")
    if "Objetivo da campanha" not in campos:
        return None  # não foi criada pelo formulário
    due = tarefa.get("due_date")
    return {
        "task_id": tarefa["id"],
        "task_url": tarefa.get("url"),
        "projeto": projeto,
        "objetivo": campos["Objetivo da campanha"],
        "responsavel": campos.get("Responsável"),
        "drive": campos.get("Drive (imagens)") or None,
        "instagram": campos.get("Instagram (Reels)") or None,
        "copy": campos.get("Copy") or None,
        "verba_total": parse_verba(campos.get("Verba total")),
        "data_fim": (dt.datetime.fromtimestamp(int(due) / 1000, dt.timezone.utc).date().isoformat()
                     if due else None),
    }


def contas_do_projeto(config, projeto):
    proj = config["projetos"].get(projeto)
    if not proj:
        raise DemandaInvalida(f"Projeto '{projeto}' não está em automacao/config.json")
    if "usar_projetos" in proj:
        saida = []
        for nome in proj["usar_projetos"]:
            saida += contas_do_projeto(config, nome)
        return saida
    return [dict(conta, projeto=projeto, site=proj.get("site"),
                 verba_total_padrao=proj.get("verba_total_padrao"))
            for conta in proj["contas"]]


def targeting(cidade):
    return {
        "geo_locations": {
            "custom_locations": [{
                "latitude": cidade["latitude"], "longitude": cidade["longitude"],
                "radius": cidade["raio_km"], "distance_unit": "kilometer"}],
            "location_types": ["home", "recent"],
        },
        "age_min": 18,
        "age_max": 65,
        "targeting_automation": {"advantage_audience": 1},
    }


def call_to_action(destino, conta):
    if destino == "whatsapp":
        return {"type": "WHATSAPP_MESSAGE",
                "value": {"app_destination": "WHATSAPP", "link": WHATSAPP_LINK}}
    if destino == "formulario":
        if not conta.get("lead_form_id"):
            raise DemandaInvalida("Destino 'formulario' exige lead_form_id na conta do config.json")
        return {"type": "SIGN_UP",
                "value": {"lead_gen_form_id": conta["lead_form_id"], "link": "http://fb.me/"}}
    return {"type": "LEARN_MORE", "value": {"link": conta["site"]}}


def link_destino(destino, conta):
    return {"whatsapp": WHATSAPP_LINK, "formulario": "http://fb.me/"}.get(destino, conta["site"])


def spec_criativo(tipo, conta, destino, copy, midia):
    """Monta o payload de /adcreatives para imagem, vídeo ou post do Instagram."""
    cta = call_to_action(destino, conta)
    ig = conta.get("instagram_user_id")
    if tipo == "instagram":
        spec = {"object_id": conta["page_id"], "instagram_user_id": ig,
                "source_instagram_media_id": midia["media_id"], "call_to_action": cta}
        return spec
    story = {"page_id": conta["page_id"]}
    if ig:
        story["instagram_user_id"] = ig
    if tipo == "imagem":
        story["link_data"] = {"image_hash": midia["hash"], "message": copy,
                              "link": link_destino(destino, conta), "call_to_action": cta}
    else:
        story["video_data"] = {"video_id": midia["video_id"], "image_url": midia["thumb"],
                               "message": copy, "call_to_action": cta}
    return {"object_story_spec": story}


def periodo(data_fim, offset, agora=None):
    """Início em ~10 min; fim às 23:59 (fuso local) do dia em que os ads devem pausar."""
    agora = agora or dt.datetime.now(dt.timezone.utc)
    inicio = agora + dt.timedelta(minutes=10)
    fim = dt.datetime.fromisoformat(f"{data_fim}T23:59:00{offset}")
    if fim - inicio < dt.timedelta(days=1):
        raise DemandaInvalida(f"Data de pausa ({data_fim}) muito próxima ou já passou")
    return inicio.replace(microsecond=0).isoformat(), fim.isoformat()


def planejar(config, demanda, agora=None):
    obj = config["objetivos"].get(demanda["objetivo"])
    if not obj:
        raise DemandaInvalida(f"Objetivo '{demanda['objetivo']}' sem mapeamento no config.json")
    if not demanda["data_fim"]:
        raise DemandaInvalida("Tarefa sem data de pausa (due date)")
    if not (demanda["drive"] or demanda["instagram"]):
        raise DemandaInvalida("Tarefa sem link de Drive ou Instagram")
    if demanda["drive"] and not demanda["copy"]:
        raise DemandaInvalida("Criativos do Drive precisam de copy")

    contas = contas_do_projeto(config, demanda["projeto"])
    inicio, fim = periodo(demanda["data_fim"], config["timezone_offset"], agora)
    verba_total = demanda["verba_total"] or sum(c["verba_total_padrao"] for c in contas)
    data_nome = dt.date.fromisoformat(demanda["data_fim"]).strftime("%d/%m")
    planos = []
    for conta in contas:
        nome = (f"{config['prefixo_nome']} {conta['projeto']} | {demanda['objetivo']} | "
                f"até {data_nome} | #{demanda['task_id']}")
        planos.append({
            "conta": conta,
            "nome": nome,
            "objective": obj["objective"],
            "otimizacao": obj["otimizacao"],
            "destino": obj["destino"],
            "verba_centavos": int(round(verba_total / len(contas) * 100)),
            "inicio": inicio,
            "fim": fim,
            "targeting": targeting(conta["cidade"]),
        })
    return planos
