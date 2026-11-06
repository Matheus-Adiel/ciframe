# coding: utf-8
"""Smoke test de browser (headless) do fluxo ``#/porsequencia``.

Este teste é opcional e não faz parte de ``python -m unittest discover``:
ele depende de Selenium, geckodriver, Firefox e acesso aos CDNs usados pelo
``static/index.html``. O backend é iniciado com um banco SQLite temporário.

Pré-requisitos:

    .venv/bin/pip install selenium
    geckodriver --version

Execução (com o venv do projeto no PATH ou via ``SMOKE_PYTHON``):

    .venv/bin/python artifacts/smoke_frontend.py

Variáveis opcionais:
    SMOKE_PYTHON       interpretador que tem Flask/main.py (default: .venv/bin/python)
    GECKODRIVER        caminho do geckodriver (default: geckodriver do PATH)
    SMOKE_PORTA        porta do servidor Flask (default: 5058)
    SMOKE_SCREENSHOT   caminho do PNG final (default: nenhum)
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import Select, WebDriverWait

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTA = int(os.environ.get('SMOKE_PORTA', '5058'))
BASE = 'http://127.0.0.1:%d' % PORTA
GECKODRIVER = os.environ.get(
    'GECKODRIVER', shutil.which('geckodriver') or 'geckodriver'
)
PYTHON = os.environ.get(
    'SMOKE_PYTHON',
    os.path.join(RAIZ, '.venv', 'bin', 'python')
    if os.path.exists(os.path.join(RAIZ, '.venv', 'bin', 'python'))
    else sys.executable,
)
SELETOR_CATALOGO = '.viewWindow-panel-container > .acordes-container'


def esperar_servidor(limite=180):
    fim = time.time() + limite
    while time.time() < fim:
        try:
            with urllib.request.urlopen(BASE + '/generos', timeout=2) as resposta:
                if resposta.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.5)
    raise RuntimeError('servidor não respondeu em %ss' % limite)


def subir_servidor(banco, log):
    ambiente = dict(os.environ, DECIFRAME_DB=banco)
    return subprocess.Popen(
        [PYTHON, '-c',
         'import main; main.app.run(port=%d, debug=False, use_reloader=False)'
         % PORTA],
        cwd=RAIZ,
        env=ambiente,
        stdout=log,
        stderr=subprocess.STDOUT,
    )


def esperar_contar(navegador, seletor, minimo, limite=30):
    return WebDriverWait(navegador, limite).until(
        lambda driver: len(driver.find_elements(By.CSS_SELECTOR, seletor))
        >= minimo
    )


def cards_visiveis(navegador):
    return [
        card for card in navegador.find_elements(
            By.CSS_SELECTOR, '.music-card'
        )
        if card.is_displayed()
    ]


def clicar_js(navegador, elemento):
    navegador.execute_script('arguments[0].click();', elemento)


def esperar_mensagem(navegador, trecho, limite=30):
    def encontrou(driver):
        return any(
            trecho in paragrafo.text.lower()
            for paragrafo in driver.find_elements(
                By.CSS_SELECTOR, '.sequencia-cadastro p'
            )
        )
    WebDriverWait(navegador, limite).until(encontrou)


def main():
    diretorio = tempfile.mkdtemp(prefix='deciframe-e2e-')
    banco = os.path.join(diretorio, 'deciframe.db')
    log = open(os.path.join(diretorio, 'servidor.log'), 'w+b')
    servidor = None
    navegador = None
    try:
        servidor = subir_servidor(banco, log)
        esperar_servidor()

        opcoes = Options()
        opcoes.add_argument('-headless')
        navegador = webdriver.Firefox(
            service=Service(GECKODRIVER), options=opcoes
        )
        navegador.set_page_load_timeout(90)
        navegador.get(BASE + '/#/porsequencia')

        # 6 seeds renderizadas no painel esquerdo.
        esperar_contar(navegador, SELETOR_CATALOGO, 6)
        paineis = navegador.find_elements(By.CSS_SELECTOR, SELETOR_CATALOGO)
        assert len(paineis) == 6, len(paineis)
        print('seeds renderizadas:', len(paineis))

        # Clicar na seed 1 (C, G, Am, F) e esperar os cards.
        clicar_js(navegador, paineis[1])
        esperar_contar(navegador, '.music-card', 1, limite=60)
        titulo = navegador.find_element(
            By.CSS_SELECTOR, '#results h4'
        ).text.strip()
        assert 'Encontrei' in titulo, titulo
        assert cards_visiveis(navegador), 'cards escondidos pelo ng-hide'
        print('busca por seed:', titulo)
        print('cards visíveis na busca por seed:', len(cards_visiveis(navegador)))

        # Cadastrar uma sequência nova.
        campo = navegador.find_element(
            By.CSS_SELECTOR, '.sequencia-cadastro input'
        )
        campo.clear()
        campo.send_keys('E, B, C#m, A')
        navegador.find_element(
            By.CSS_SELECTOR, '.sequencia-cadastro button'
        ).click()
        esperar_mensagem(navegador, 'cadastrada')
        esperar_contar(navegador, SELETOR_CATALOGO, 7)
        esperar_contar(navegador, '.music-card', 1, limite=60)
        assert cards_visiveis(navegador)
        print('cadastro novo: sequência visível no catálogo e busca com cards')

        # Duplicata normalizada: mesmo ID, sem criar nova sequência.
        campo = navegador.find_element(
            By.CSS_SELECTOR, '.sequencia-cadastro input'
        )
        campo.clear()
        campo.send_keys(' e , b , C#M , a ')
        navegador.find_element(
            By.CSS_SELECTOR, '.sequencia-cadastro button'
        ).click()
        esperar_mensagem(navegador, 'já existe')
        time.sleep(1)
        paineis = navegador.find_elements(By.CSS_SELECTOR, SELETOR_CATALOGO)
        assert len(paineis) == 7, len(paineis)
        print('duplicata: catálogo continua com 7 sequências')

        # Filtro por gênero: escolhe um gênero que tenha resultado.
        seletor = Select(navegador.find_element(
            By.CSS_SELECTOR, '#results select'
        ))
        genero = None
        for opcao in seletor.options:
            valor = opcao.get_attribute('value')
            if not valor:
                continue
            seletor.select_by_value(valor)
            time.sleep(1)
            if navegador.find_elements(By.CSS_SELECTOR, '.music-card'):
                genero = opcao.text.strip()
                break
        assert genero, 'nenhum gênero retornou resultados'
        WebDriverWait(navegador, 30).until(
            lambda driver: all(
                genero == card.find_element(
                    By.CSS_SELECTOR, '.music-gender span'
                ).text.strip()
                for card in driver.find_elements(
                    By.CSS_SELECTOR, '.music-card'
                )
            )
        )
        print('filtro por gênero:', genero)

        # Abrir cifra: intercepta window.open para não depender da rede.
        navegador.execute_script(
            'window.__abriu = null; window.open = function(url) { '
            'window.__abriu = url; return null; };'
        )
        clicar_js(
            navegador,
            navegador.find_element(By.CSS_SELECTOR, '.music-card'),
        )
        url = navegador.execute_script('return window.__abriu;')
        assert url and url.startswith('http'), url
        print('abrir cifra: window.open chamado')

        destino = os.environ.get('SMOKE_SCREENSHOT')
        if destino:
            navegador.save_screenshot(destino)
            print('screenshot:', destino)

        print('SMOKE FRONTEND OK')
    except Exception:
        log.seek(0)
        saida = log.read().decode('utf-8', 'replace')
        if saida.strip():
            print('--- log do servidor ---')
            print(saida[-4000:])
        raise
    finally:
        if navegador is not None:
            navegador.quit()
        if servidor is not None:
            servidor.terminate()
            try:
                servidor.wait(timeout=30)
            except subprocess.TimeoutExpired:
                servidor.kill()
        log.close()
        shutil.rmtree(diretorio, ignore_errors=True)


if __name__ == '__main__':
    main()
