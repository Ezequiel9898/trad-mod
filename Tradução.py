import json
import os
import zipfile
import requests
import hashlib
from tempfile import TemporaryDirectory
from datetime import datetime
import difflib
import re
import locale

locale.setlocale(locale.LC_TIME, 'pt_BR.utf8')

ARQUIVO_MODS = 'mods.json'
PASTA_SAIDA = 'mods_langs'
MODRINTH_API = 'https://api.modrinth.com/v2'
README_PRINCIPAL = 'README.md'

tabela_status = {}
mod_alterado = False


def carregar_mods(caminho):
    with open(caminho, 'r', encoding='utf-8') as f:
        return json.load(f)


def obter_ultima_versao(mod_id):
    url = f"{MODRINTH_API}/project/{mod_id}/version"
    resposta = requests.get(url)
    resposta.raise_for_status()
    versoes = resposta.json()
    return versoes[0]


def baixar_jar(versao):
    for arquivo in versao['files']:
        if arquivo['filename'].endswith('.jar'):
            url = arquivo['url']
            r = requests.get(url)
            r.raise_for_status()
            return arquivo['filename'], r.content
    return None, None


def hash_arquivo(conteudo):
    return hashlib.md5(conteudo).hexdigest()


def diferenca_json(antigo, novo):
    try:
        antigo_linhas = json.dumps(json.loads(antigo), indent=2, ensure_ascii=False).splitlines()
        novo_linhas = json.dumps(json.loads(novo), indent=2, ensure_ascii=False).splitlines()
        diff = [linha for linha in difflib.unified_diff(antigo_linhas, novo_linhas, lineterm='') if not linha.startswith('---') and not linha.startswith('+++')]
        return '\n'.join(diff)
    except json.JSONDecodeError:
        return ''


def substituir_valores_json(texto_original, dicionario_substituicao):
    def substituir(match):
        chave = match.group(1)
        if chave in dicionario_substituicao:
            valor_novo = json.dumps(dicionario_substituicao[chave], ensure_ascii=False)[1:-1]
            return f'"{chave}": "{valor_novo}"'
        return match.group(0)

    padrao = r'"(.*?)":\s*"((?:\\"|\\\\|\\/|\\b|\\f|\\n|\\r|\\t|\\u[0-9a-fA-F]{4}|[^"\\])*)"'
    return re.sub(padrao, substituir, texto_original)


def extrair_arquivos_lang(conteudo_jar, caminho_saida, nome_mod):
    import io
    global mod_alterado

    with zipfile.ZipFile(io.BytesIO(conteudo_jar)) as jar:
        arquivos_lang = [f for f in jar.namelist() if '/lang/pt_br.json' in f or '/lang/en_us.json' in f]
        os.makedirs(caminho_saida, exist_ok=True)

        atualizado = False
        changelog = []
        arquivos = {}

        for caminho_arquivo in arquivos_lang:
            nome_arquivo = os.path.basename(caminho_arquivo)
            with jar.open(caminho_arquivo) as f:
                arquivos[nome_arquivo] = f.read()

        if 'en_us.json' in arquivos:
            if 'pt_br.json' not in arquivos:
                arquivos['pt_br.json'] = arquivos['en_us.json']

        for nome_arquivo in ['en_us.json', 'pt_br.json']:
            if nome_arquivo not in arquivos:
                continue

            conteudo_novo = arquivos[nome_arquivo]
            caminho_arquivo = os.path.join(caminho_saida, nome_arquivo)
            novo_hash = hash_arquivo(conteudo_novo)

            acao = 'atualizado'
            diff = ''

            if os.path.exists(caminho_arquivo):
                with open(caminho_arquivo, 'rb') as existente:
                    conteudo_antigo = existente.read()
                    if hash_arquivo(conteudo_antigo) == novo_hash:
                        continue
                    diff = diferenca_json(conteudo_antigo.decode(), conteudo_novo.decode())
                    if not diff.strip():
                        continue
            else:
                acao = 'adicionado'
                diff = diferenca_json("{}", conteudo_novo.decode())
                if not diff.strip():
                    continue

            if nome_arquivo == 'pt_br.json' and 'en_us.json' in arquivos:
                try:
                    pt_br_texto = conteudo_novo.decode()
                    en_us_texto = arquivos['en_us.json'].decode()
                    pt_br_dict = json.loads(pt_br_texto)
                    mesclado = substituir_valores_json(en_us_texto, pt_br_dict)
                    conteudo_novo = mesclado.encode('utf-8')
                    diff = diferenca_json(open(caminho_arquivo, 'r', encoding='utf-8').read() if os.path.exists(caminho_arquivo) else '{}', mesclado)
                    if not diff.strip():
                        continue
                except json.JSONDecodeError as e:
                    print(f"Erro ao mesclar JSON de {nome_mod}: {e}")
                    continue

            with open(caminho_arquivo, 'wb') as saida:
                saida.write(conteudo_novo)

            data = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            changelog.insert(0, f"## {nome_arquivo} {acao} em {data}\n\n```diff\n{diff}\n```")
            atualizado = True
            mod_alterado = True

        tabela_status[nome_mod] = ('🟢 Atualizado' if atualizado else '🔴 Desatualizado', datetime.now().strftime('%d/%m/%Y'))

        if changelog:
            atualizar_readme_mod(caminho_saida, nome_mod, changelog)


def atualizar_readme_mod(caminho_mod, nome_mod, changelog):
    caminho_readme = os.path.join(caminho_mod, '..', 'README.md')
    bloco = '\n\n### Registro de Alterações\n\n' + '\n\n'.join(changelog)
    if os.path.exists(caminho_readme):
        with open(caminho_readme, 'r+', encoding='utf-8') as f:
            conteudo_antigo = f.read()
            f.seek(0)
            f.write(f"# Arquivos de Tradução: {nome_mod}\n{bloco}\n{conteudo_antigo}")
    else:
        with open(caminho_readme, 'w', encoding='utf-8') as f:
            f.write(f"# Arquivos de Tradução: {nome_mod}\n{bloco}")


def atualizar_readme_principal():
    if not mod_alterado:
        print("Nenhuma alteração detectada. README.md principal não será modificado.")
        return

    cabecalho = """# Status de Tradução dos Mods

Este repositório contém traduções de mods para Minecraft. O status das traduções é monitorado automaticamente.

## 📜 Lista de Mods

| Mod              | Status        | Última Atualização |
|------------------|---------------|--------------------|"""
    linhas = [
        f"| **{mod}** | {status} | {data} |" for mod, (status, data) in sorted(tabela_status.items())
    ]
    with open(README_PRINCIPAL, 'w', encoding='utf-8') as f:
        f.write(cabecalho + '\n' + '\n'.join(linhas))


def main():
    mods = carregar_mods(ARQUIVO_MODS)
    os.makedirs(PASTA_SAIDA, exist_ok=True)

    for nome_mod, id_mod in mods.items():
        try:
            print(f"Processando: {nome_mod} ({id_mod})")
            versao = obter_ultima_versao(id_mod)
            nome_arquivo, conteudo = baixar_jar(versao)
            if not conteudo:
                print(f"Erro ao baixar: {nome_mod}")
                continue
            pasta_mod = os.path.join(PASTA_SAIDA, nome_mod, 'lang')
            extrair_arquivos_lang(conteudo, pasta_mod, nome_mod)
            print(f"Verificado: {pasta_mod}\n")
        except Exception as e:
            print(f"Erro ao processar {nome_mod}: {e}\n")

    atualizar_readme_principal()


if __name__ == '__main__':
    main()
