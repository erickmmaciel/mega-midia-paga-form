import datetime as dt
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import planejador  # noqa: E402
from drive import extrair_id  # noqa: E402

CONFIG = json.loads((pathlib.Path(__file__).resolve().parent.parent / "config.json").read_text())

DESCRICAO = """👤 Responsável: Ana

🎯 Objetivo da campanha: Leads

📝 Observações: Feirão

📁 Drive (imagens): https://drive.google.com/drive/folders/1AbC-dEf_123

✍️ Copy:
Linha um do anúncio.

Linha dois com Copy: no meio.

💰 Verba total: R$ 1.500,50

📊 Meta Ads:
[Abrir Meta Ads →](https://adsmanager.facebook.com/x)"""

AGORA = dt.datetime(2026, 11, 1, 12, tzinfo=dt.timezone.utc)


def tarefa(nome="GWM (Cacoal + Pvh) - 01/11/2026", desc=DESCRICAO):
    due = int(dt.datetime(2026, 11, 15, 12, tzinfo=dt.timezone.utc).timestamp() * 1000)
    return {"id": "abc123", "name": nome, "description": desc, "due_date": str(due)}


class TestParse(unittest.TestCase):
    def test_demanda(self):
        d = planejador.demanda_da_tarefa(tarefa())
        self.assertEqual(d["projeto"], "GWM (Cacoal + Pvh)")
        self.assertEqual(d["objetivo"], "Leads")
        self.assertEqual(d["drive"], "https://drive.google.com/drive/folders/1AbC-dEf_123")
        self.assertEqual(d["copy"], "Linha um do anúncio.\n\nLinha dois com Copy: no meio.")
        self.assertEqual(d["verba_total"], 1500.5)
        self.assertEqual(d["data_fim"], "2026-11-15")
        self.assertIsNone(d["instagram"])

    def test_tarefa_fora_do_formulario(self):
        self.assertIsNone(planejador.demanda_da_tarefa(tarefa(desc="qualquer coisa")))

    def test_verba(self):
        self.assertEqual(planejador.parse_verba("R$ 700"), 700)
        self.assertEqual(planejador.parse_verba("1.200,00"), 1200)
        self.assertEqual(planejador.parse_verba("1.500"), 1500)
        self.assertEqual(planejador.parse_verba("1500.50"), 1500.5)
        self.assertIsNone(planejador.parse_verba(""))

    def test_links(self):
        self.assertEqual(planejador.shortcode_instagram("https://www.instagram.com/reel/DAbc_1-x/?igsh=z"), "DAbc_1-x")
        self.assertEqual(planejador.shortcode_instagram("https://www.instagram.com/gwm/p/XyZ/"), "XyZ")
        self.assertEqual(extrair_id("https://drive.google.com/file/d/1Qw-E/view?usp=sharing"), "1Qw-E")
        self.assertEqual(extrair_id("https://drive.google.com/open?id=9Zz"), "9Zz")


class TestPlano(unittest.TestCase):
    def test_projeto_duplo_divide_verba(self):
        d = planejador.demanda_da_tarefa(tarefa())
        planos = planejador.planejar(CONFIG, d, agora=AGORA)
        self.assertEqual([p["conta"]["ad_account_id"] for p in planos],
                         ["9320864484661329", "567738345273546"])
        self.assertEqual([p["verba_centavos"] for p in planos], [75025, 75025])
        self.assertEqual(planos[0]["fim"], "2026-11-15T23:59:00-04:00")
        self.assertEqual(planos[0]["objective"], "OUTCOME_LEADS")
        self.assertIn("#abc123", planos[0]["nome"])

    def test_verba_padrao(self):
        d = planejador.demanda_da_tarefa(tarefa(nome="Triumph - 01/11/2026"))
        d["verba_total"] = None
        self.assertEqual(planejador.planejar(CONFIG, d, agora=AGORA)[0]["verba_centavos"], 70000)

    def test_data_passada(self):
        d = planejador.demanda_da_tarefa(tarefa())
        with self.assertRaises(planejador.DemandaInvalida):
            planejador.planejar(CONFIG, d, agora=dt.datetime(2026, 11, 15, 12, tzinfo=dt.timezone.utc))

    def test_projeto_desconhecido(self):
        d = planejador.demanda_da_tarefa(tarefa(nome="Outro - 01/11/2026"))
        with self.assertRaises(planejador.DemandaInvalida):
            planejador.planejar(CONFIG, d, agora=AGORA)

    def test_teto_verba_mensal(self):
        d = planejador.demanda_da_tarefa(tarefa(nome="Mega Seminovos - 01/11/2026"))
        d["verba_total"] = 1500
        estado = {"campanhas": {"x": {"processado_em": "2026-11-01T10:00:00+00:00", "contas": [
            {"ad_account_id": "3502170010043877", "verba_centavos": 300000}]}}}
        with self.assertRaises(planejador.DemandaInvalida):  # 3000 + 1500 > 4000
            planejador.planejar(CONFIG, d, agora=AGORA, estado=estado)
        d["verba_total"] = 1000
        self.assertEqual(len(planejador.planejar(CONFIG, d, agora=AGORA, estado=estado)), 1)
        # mês anterior não conta
        estado["campanhas"]["x"]["processado_em"] = "2026-10-20T10:00:00+00:00"
        d["verba_total"] = 4000
        self.assertEqual(len(planejador.planejar(CONFIG, d, agora=AGORA, estado=estado)), 1)
        resumo = planejador.resumo_verba_mes(CONFIG, estado, agora=AGORA)
        self.assertEqual(resumo["Mega Seminovos"]["verba_mensal"], 4000)
        self.assertNotIn("GWM (Cacoal + Pvh)", resumo)

    def test_criativos(self):
        conta = planejador.contas_do_projeto(CONFIG, "Mega Seminovos")[0]
        img = planejador.spec_criativo("imagem", conta, "whatsapp", "Texto", {"hash": "h1"})
        ld = img["object_story_spec"]["link_data"]
        self.assertEqual(ld["call_to_action"]["type"], "WHATSAPP_MESSAGE")
        self.assertEqual(ld["image_hash"], "h1")
        ig = planejador.spec_criativo("instagram", conta, "site", None, {"media_id": "m1"})
        self.assertEqual(ig["source_instagram_media_id"], "m1")
        self.assertEqual(ig["call_to_action"]["value"]["link"], conta["site"])
        with self.assertRaises(planejador.DemandaInvalida):
            planejador.spec_criativo("imagem", conta, "formulario", "x", {"hash": "h"})


if __name__ == "__main__":
    unittest.main()
