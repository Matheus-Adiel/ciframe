# coding: utf-8
"""Contratos de contexto da feature que não são exercitados pela API.

Estes testes não substituem o smoke de browser nem o teste no Docker; eles
apenas travam decisões do plano que quebrariam silenciosamente se alguém
voltasse a usar múltiplos workers, montasse o volume no lugar errado ou
reintroduzisse a lista hardcoded no frontend.
"""
import os
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ler(caminho):
    with open(os.path.join(RAIZ, caminho), encoding='utf-8') as arquivo:
        return arquivo.read()


class TestDeploy(unittest.TestCase):

    def test_dockerfile_usa_um_worker_e_volume_em_data(self):
        dockerfile = ler('Dockerfile')

        self.assertIn('DECIFRAME_DB=/data/deciframe.db', dockerfile)
        self.assertIn('mkdir -p /data', dockerfile)
        self.assertIn('VOLUME ["/data"]', dockerfile)
        self.assertIn('"--workers", "1"', dockerfile)

    def test_comandos_documentados_montam_o_volume_em_data(self):
        for arquivo in ('README.md', 'AGENTS.md'):
            for linha in ler(arquivo).splitlines():
                if 'docker run' not in linha or ' -v ' not in linha:
                    continue
                with self.subTest(arquivo=arquivo, linha=linha):
                    self.assertIn(':/data', linha)
                    self.assertNotIn(':/app/data', linha)

    def test_arquivos_de_banco_e_var_sao_ignorados(self):
        for arquivo in ('.gitignore', '.dockerignore'):
            conteudo = ler(arquivo)
            for padrao in ('var/', '*.db', '*.db-wal', '*.db-shm'):
                with self.subTest(arquivo=arquivo, padrao=padrao):
                    self.assertIn(padrao, conteudo)


class TestFrontendSequencias(unittest.TestCase):

    def setUp(self):
        self.controller = ler(
            'static/assets/js/controllers/sequencia.js'
        )
        self.template = ler('static/templates/sequencia.html')

    def test_controller_le_o_catalogo_do_backend(self):
        self.assertIn("$http.get('/sequencias')", self.controller)
        self.assertIn("$http.post('/sequencias'", self.controller)
        self.assertIn("'/similares?sequencia_id='", self.controller)

    def test_template_tem_dica_de_cadastro(self):
        self.assertIn('2 a 8 acordes', self.template)

    def test_template_nao_esconde_resultados_por_diferenca_ausente(self):
        self.assertIn(
            'music.diferenca && music.diferenca.length',
            self.template,
        )
        self.assertNotIn(
            'ng-hide="music.diferenca.length"',
            self.template,
        )


if __name__ == '__main__':
    unittest.main()
