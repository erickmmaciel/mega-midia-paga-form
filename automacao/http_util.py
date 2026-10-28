"""Cliente HTTP mínimo (só biblioteca padrão) usado pelas integrações."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request


class ApiError(Exception):
    def __init__(self, status, body, url):
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"HTTP {status} em {url.split('?')[0]}: {body}")


def request(method, url, params=None, data=None, json_body=None, headers=None,
            raw=False, retries=3, timeout=120):
    """Faz a requisição e devolve JSON (ou bytes se raw=True).

    `data` vai como form-urlencoded; `json_body` como JSON.
    Repete em erros 5xx/429 e falhas de rede com backoff exponencial.
    """
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    body = None
    hdrs = dict(headers or {})
    if json_body is not None:
        body = json.dumps(json_body).encode()
        hdrs["Content-Type"] = "application/json"
    elif data is not None:
        enc = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
               for k, v in data.items() if v is not None}
        body = urllib.parse.urlencode(enc).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"

    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read()
                if raw:
                    return content
                return json.loads(content or b"{}")
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            if (e.code >= 500 or e.code == 429) and attempt < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            try:
                text = json.loads(text)
            except ValueError:
                pass
            raise ApiError(e.code, text, url) from None
        except urllib.error.URLError:
            if attempt < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
