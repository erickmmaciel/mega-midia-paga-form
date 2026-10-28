"""Leitura das demandas (tarefas criadas pelo formulário) e retorno no ClickUp."""
from http_util import request

API = "https://api.clickup.com/api/v2"


class ClickUpApi:
    def __init__(self, token):
        self.headers = {"Authorization": token}

    def tarefas_abertas(self, list_id):
        tarefas, page = [], 0
        while True:
            data = request("GET", f"{API}/list/{list_id}/task", headers=self.headers,
                           params={"page": page, "include_closed": "false",
                                   "subtasks": "false"})
            tarefas += data.get("tasks", [])
            if data.get("last_page", True) or not data.get("tasks"):
                return tarefas
            page += 1

    def tarefa(self, task_id):
        return request("GET", f"{API}/task/{task_id}", headers=self.headers)

    def comentar(self, task_id, texto):
        request("POST", f"{API}/task/{task_id}/comment", headers=self.headers,
                json_body={"comment_text": texto, "notify_all": False})
