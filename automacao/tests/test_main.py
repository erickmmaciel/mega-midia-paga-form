import datetime as dt
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import main  # noqa: E402
from test_planejador import tarefa  # noqa: E402

CONFIG = json.loads(main.CONFIG.read_text())


class FakeMeta:
    def __init__(self, falhar_em_conta=None):
        self.chamadas, self.n, self.falhar = [], 0, falhar_em_conta
        self.deletados = []

    def _id(self, tipo):
        self.n += 1
        self.chamadas.append(tipo)
        return f"{tipo}{self.n}"

    def criar_campanha(self, act, *a):
        if act == self.falhar:
            raise RuntimeError("boom")
        return self._id("camp")

    def criar_conjunto(self, *a): return self._id("set")
    def enviar_imagem(self, *a): return self._id("hash")
    def criar_criativo(self, *a): return self._id("cr")
    def criar_anuncio(self, *a): return self._id("ad")
    def delete(self, i): self.deletados.append(i)
    def buscar_midia_instagram(self, ig, code): return "media1"


class FakeDrive:
    def listar_midias(self, link):
        return [{"id": "f1", "name": "a.jpg", "mimeType": "image/jpeg"},
                {"id": "f2", "name": "b.png", "mimeType": "image/png"}]

    def baixar(self, i): return b"img"


class FakeClickUp:
    def __init__(self, tarefas):
        self.tarefas, self.comentarios = tarefas, []

    def tarefas_abertas(self, list_id): return self.tarefas
    def tarefa(self, i): return next(t for t in self.tarefas if t["id"] == i)
    def comentar(self, i, txt): self.comentarios.append((i, txt))


def tarefa_nova(**kw):
    t = tarefa(**kw)
    t["date_created"] = str(int(dt.datetime(2026, 12, 1, tzinfo=dt.timezone.utc).timestamp() * 1000))
    due = int(dt.datetime(2030, 1, 10, 12, tzinfo=dt.timezone.utc).timestamp() * 1000)
    t["due_date"] = str(due)
    return t


class TestPublicar(unittest.TestCase):
    def test_publica_duas_contas_e_ignora_antigas(self):
        antiga = tarefa_nova()
        antiga["id"], antiga["date_created"] = "velha", "1000"
        cu = FakeClickUp([tarefa_nova(), antiga])
        estado = {"campanhas": {}}
        meta = FakeMeta()
        self.assertTrue(main.publicar(CONFIG, estado, meta, cu, FakeDrive()))
        reg = estado["campanhas"]["abc123"]
        self.assertEqual(reg["status"], "publicado")
        self.assertEqual(len(reg["contas"]), 2)
        self.assertEqual(len(reg["contas"][0]["anuncios"]), 2)
        self.assertNotIn("velha", estado["campanhas"])
        self.assertIn("✅", cu.comentarios[0][1])
        # segunda rodada não republica
        self.assertFalse(main.publicar(CONFIG, estado, meta, cu, FakeDrive()))

    def test_falha_parcial_e_reprocesso_sem_duplicar(self):
        cu = FakeClickUp([tarefa_nova()])
        estado = {"campanhas": {}}
        main.publicar(CONFIG, estado, FakeMeta(falhar_em_conta="567738345273546"), cu, FakeDrive())
        reg = estado["campanhas"]["abc123"]
        self.assertEqual(reg["status"], "erro")
        self.assertEqual(len(reg["contas"]), 1)
        meta = FakeMeta()
        main.publicar(CONFIG, estado, meta, cu, FakeDrive(), so_task="abc123")
        reg = estado["campanhas"]["abc123"]
        self.assertEqual(reg["status"], "publicado")
        self.assertEqual(len(reg["contas"]), 2)
        self.assertEqual(meta.chamadas.count("camp"), 1)

    def test_falha_no_meio_apaga_campanha(self):
        class Quebra(FakeMeta):
            def criar_anuncio(self, *a): raise RuntimeError("x")
        cu = FakeClickUp([tarefa_nova(nome="Triumph - 01/12/2026")])
        meta, estado = Quebra(), {"campanhas": {}}
        main.publicar(CONFIG, estado, meta, cu, FakeDrive())
        self.assertEqual(meta.deletados, ["camp1"])
        self.assertIn("⚠️", cu.comentarios[0][1])

    def test_dry_run_nao_altera(self):
        estado = {"campanhas": {}}
        self.assertFalse(main.publicar(CONFIG, estado, None, FakeClickUp([tarefa_nova()]),
                                       None, dry_run=True))
        self.assertEqual(estado["campanhas"], {})


if __name__ == "__main__":
    unittest.main()
