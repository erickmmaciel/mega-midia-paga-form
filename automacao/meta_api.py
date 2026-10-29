"""Wrapper da Meta Marketing API (Graph API) para criar e controlar anúncios."""
import base64
import time

from http_util import request

GRAPH = "https://graph.facebook.com"


class MetaApi:
    def __init__(self, token, version):
        self.token = token
        self.base = f"{GRAPH}/{version}"

    # ── baixo nível ────────────────────────────────────────────
    def get(self, path, **params):
        params["access_token"] = self.token
        return request("GET", f"{self.base}/{path}", params=params)

    def post(self, path, **data):
        data["access_token"] = self.token
        return request("POST", f"{self.base}/{path}", data=data)

    def delete(self, path):
        return request("DELETE", f"{self.base}/{path}",
                       params={"access_token": self.token})

    # ── descoberta ─────────────────────────────────────────────
    def instagram_da_pagina(self, page_id):
        data = self.get(page_id, fields="instagram_business_account")
        acc = data.get("instagram_business_account")
        return acc["id"] if acc else None

    def buscar_midia_instagram(self, ig_user_id, shortcode, max_paginas=10):
        """Procura o post/reel pelo shortcode do link nas últimas mídias da conta."""
        after = None
        for _ in range(max_paginas):
            params = {"fields": "id,permalink,shortcode", "limit": 50}
            if after:
                params["after"] = after
            data = self.get(f"{ig_user_id}/media", **params)
            for m in data.get("data", []):
                if m.get("shortcode") == shortcode or f"/{shortcode}/" in (m.get("permalink") or ""):
                    return m["id"]
            after = data.get("paging", {}).get("cursors", {}).get("after")
            if not after or "next" not in data.get("paging", {}):
                break
        return None

    # ── criação ────────────────────────────────────────────────
    def criar_campanha(self, act, nome, objective, status):
        return self.post(f"act_{act}/campaigns",
                         name=nome, objective=objective, status=status,
                         special_ad_categories=[],
                         is_adset_budget_sharing_enabled="false")["id"]

    def criar_conjunto(self, act, campanha_id, nome, otimizacao, destino,
                       verba_centavos, inicio, fim, targeting, page_id, status,
                       whatsapp=None):
        payload = dict(
            name=nome, campaign_id=campanha_id, status=status,
            lifetime_budget=verba_centavos, start_time=inicio, end_time=fim,
            billing_event="IMPRESSIONS", optimization_goal=otimizacao,
            bid_strategy="LOWEST_COST_WITHOUT_CAP", targeting=targeting,
            promoted_object={"page_id": page_id},
        )
        if destino == "whatsapp":
            payload["destination_type"] = "WHATSAPP"
            if whatsapp:
                payload["promoted_object"]["whatsapp_phone_number"] = whatsapp
        elif destino == "formulario":
            payload["destination_type"] = "ON_AD"
        return self.post(f"act_{act}/adsets", **payload)["id"]

    def enviar_imagem(self, act, conteudo):
        data = self.post(f"act_{act}/adimages",
                         bytes=base64.b64encode(conteudo).decode())
        return next(iter(data["images"].values()))["hash"]

    def enviar_video(self, act, file_url, nome, timeout=600):
        """Sobe vídeo por URL e espera o processamento para obter a thumbnail."""
        video_id = self.post(f"act_{act}/advideos", file_url=file_url, name=nome)["id"]
        limite = time.time() + timeout
        while time.time() < limite:
            info = self.get(video_id, fields="status,picture")
            estado = info.get("status", {}).get("video_status")
            if estado == "ready" and info.get("picture"):
                return video_id, info["picture"]
            if estado == "error":
                raise RuntimeError(f"Meta não conseguiu processar o vídeo {nome}")
            time.sleep(10)
        raise RuntimeError(f"Tempo esgotado processando o vídeo {nome}")

    def criar_criativo(self, act, nome, spec):
        return self.post(f"act_{act}/adcreatives", name=nome, **spec)["id"]

    def criar_anuncio(self, act, conjunto_id, nome, criativo_id, status):
        return self.post(f"act_{act}/ads", name=nome, adset_id=conjunto_id,
                         creative={"creative_id": criativo_id}, status=status)["id"]

    # ── controle ───────────────────────────────────────────────
    def definir_status(self, objeto_id, status):
        return self.post(objeto_id, status=status)

    def status(self, objeto_id):
        return self.get(objeto_id, fields="effective_status,status")

    def metricas(self, campanha_id):
        data = self.get(f"{campanha_id}/insights", date_preset="maximum",
                        fields="spend,impressions,reach,clicks,ctr,cpm,actions")
        rows = data.get("data", [])
        return rows[0] if rows else {}
