#!/usr/bin/env python3
"""Servidor da automação: agenda as rodadas e serve o painel com controle.

- A cada INTERVALO_MIN minutos (padrão 5): publicar + sincronizar.
- GET  /painel/        painel (protegido por usuário/senha)
- GET  /api/estado     estado das campanhas
- POST /api/acao       {"acao": "pausar|ativar|publicar|sincronizar", "task_id": "..."}
- GET  /saude          status da última rodada (sem senha, para monitoramento)

Variáveis: PAINEL_SENHA (obrigatória), PAINEL_USUARIO (padrão "mega"),
PORTA (padrão 8080), INTERVALO_MIN, além das usadas por main.py.
"""
import base64
import contextlib
import datetime as dt
import hmac
import io
import json
import os
import pathlib
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import main

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PAINEL = RAIZ / "painel" / "index.html"

USUARIO = os.environ.get("PAINEL_USUARIO", "mega")
SENHA = os.environ.get("PAINEL_SENHA", "")
PORTA = int(os.environ.get("PORTA", "8080"))
INTERVALO = max(1, int(os.environ.get("INTERVALO_MIN", "5"))) * 60

trava = threading.Lock()  # uma execução por vez: evita publicar a mesma demanda duas vezes
saude = {"ultima_rodada": None, "ultimo_erro": False, "rodando": False}


def log(msg):
    print(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def rodar(cmd, alvo=None):
    """Executa um comando capturando a saída; devolve (ok, texto)."""
    saida = io.StringIO()
    try:
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(saida):
            main.executar(cmd, alvo)
        ok = True
    except main.ErroComando as exc:
        saida.write(f"Erro: {exc}\n")
        ok = False
    except Exception:
        saida.write(traceback.format_exc())
        ok = False
    texto = saida.getvalue().strip()
    if texto:
        log(f"{cmd} {alvo or ''}\n{texto}")
    return ok, texto


def agendador():
    while True:
        with trava:
            saude["rodando"] = True
            ok1, _ = rodar("publicar")
            ok2, _ = rodar("sincronizar")
            saude.update(rodando=False, ultima_rodada=main.agora_iso(), ultimo_erro=not (ok1 and ok2))
        time.sleep(INTERVALO)


class Handler(BaseHTTPRequestHandler):
    server_version = "MegaAds"

    def log_message(self, fmt, *args):  # silencia log de cada requisição
        pass

    def _autorizado(self):
        esperado = "Basic " + base64.b64encode(f"{USUARIO}:{SENHA}".encode()).decode()
        return hmac.compare_digest(self.headers.get("Authorization", ""), esperado)

    def _resposta(self, status, corpo, tipo="application/json; charset=utf-8"):
        dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(dados)

    def _pedir_senha(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Painel Mega Ads", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        rota = self.path.split("?")[0]
        if rota == "/saude":
            return self._resposta(200, saude)
        if not self._autorizado():
            return self._pedir_senha()
        if rota in ("/", "/painel"):
            self.send_response(302)
            self.send_header("Location", "/painel/")
            self.end_headers()
        elif rota == "/painel/":
            self._resposta(200, PAINEL.read_bytes(), "text/html; charset=utf-8")
        elif rota == "/api/estado":
            self._resposta(200, main.carregar_estado())
        else:
            self._resposta(404, {"erro": "não encontrado"})

    def do_POST(self):
        if not self._autorizado():
            return self._pedir_senha()
        if self.path.split("?")[0] != "/api/acao":
            return self._resposta(404, {"erro": "não encontrado"})
        try:
            tamanho = min(int(self.headers.get("Content-Length", 0)), 10_000)
            pedido = json.loads(self.rfile.read(tamanho) or b"{}")
            acao, task_id = pedido.get("acao"), (pedido.get("task_id") or "").strip() or None
        except (ValueError, AttributeError):
            return self._resposta(400, {"erro": "pedido inválido"})
        if acao not in main.COMANDOS:
            return self._resposta(400, {"erro": "ação inválida"})
        if not trava.acquire(timeout=90):
            return self._resposta(409, {"erro": "Automação ocupada. Tente de novo em 1 minuto."})
        try:
            ok, texto = rodar(acao, task_id)
        finally:
            trava.release()
        self._resposta(200 if ok else 500, {"ok": ok, "saida": texto[-2000:]})


def iniciar():
    if not SENHA:
        sys.exit("Defina PAINEL_SENHA para proteger o painel.")
    threading.Thread(target=agendador, daemon=True).start()
    log(f"Servidor na porta {PORTA}; rodadas a cada {INTERVALO // 60} min")
    ThreadingHTTPServer(("0.0.0.0", PORTA), Handler).serve_forever()


if __name__ == "__main__":
    iniciar()
