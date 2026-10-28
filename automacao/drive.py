"""Baixa criativos de links públicos do Google Drive (arquivo ou pasta)."""
import re

from http_util import request

API = "https://www.googleapis.com/drive/v3/files"
TIPOS = ("image/", "video/")


def extrair_id(url):
    for padrao in (r"/folders/([\w-]+)", r"/file/d/([\w-]+)", r"[?&]id=([\w-]+)"):
        m = re.search(padrao, url)
        if m:
            return m.group(1)
    return None


class Drive:
    def __init__(self, api_key):
        self.key = api_key

    def url_download(self, file_id):
        return f"{API}/{file_id}?alt=media&key={self.key}"

    def listar_midias(self, link):
        """Devolve [{id, name, mimeType}] de imagens/vídeos do link (pasta ou arquivo)."""
        file_id = extrair_id(link)
        if not file_id:
            raise ValueError(f"Link do Drive sem ID reconhecível: {link}")
        meta = request("GET", f"{API}/{file_id}", params={
            "key": self.key, "fields": "id,name,mimeType", "supportsAllDrives": "true"})
        if meta["mimeType"] != "application/vnd.google-apps.folder":
            arquivos = [meta]
        else:
            data = request("GET", API, params={
                "key": self.key, "q": f"'{file_id}' in parents and trashed = false",
                "fields": "files(id,name,mimeType)", "orderBy": "name", "pageSize": 100,
                "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"})
            arquivos = data.get("files", [])
        return [a for a in arquivos if a["mimeType"].startswith(TIPOS)]

    def baixar(self, file_id):
        return request("GET", self.url_download(file_id), raw=True)
