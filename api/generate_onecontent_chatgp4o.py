import json
import re
from datetime import datetime

import google.generativeai as genai
import requests
from pymongo import MongoClient

from load_creds import load_creds

client = MongoClient('mongodb://localhost:27017/')
db = client['propharmaco']
collection = db['reqs']
api_key = 'sk-proj-UUwQVhrVPj11a57FSanoT3BlbkFJG1Ad4aCgvAtzNKe57yor'

creds = load_creds()
genai.configure(credentials=creds)


def get_filter(prompt_input):
    model = genai.GenerativeModel(
        model_name="tunedModels/propharmaco-vtrodga63yfr",
    )
    prompt_to_gemini = """
    Com base no prompt, colete as informações mais relevantes e caso ele tenha relação com a lista "Propriedades", retorne um filtro:
    Prompt: '{0}'
    Propriedades: "codigoFilial,numeroOrcamento,codigoFilialDestino,codigoCliente,dataEntrada,valorRequisitado,valorDesconto,valorTaxa,numeroComprovanteManual,flagEnvio,nomePaciente,observacoesPaciente,enderecoPaciente,codigoConvenio,codigoFuncionario,condicaoPagamento,codigoCaptacao"
    Filtro: '{{propriedade: "PROPRIEDADE", valor: "VALOR"}}'
    
    Ignore tudo que você conhece do mundo, apenas faça o que foi pedido.
    """.format(prompt_input)

    chat_session = model.start_chat(history=[])
    response = chat_session.send_message(prompt_to_gemini)
    response_text = response.text
    response_text = re.sub(r'[^\x20-\x7E]+', '', response_text)

    propriedades = [
        "codigoFilial", "numeroOrcamento", "codigoFilialDestino", "codigoCliente",
        "dataEntrada", "valorRequisitado", "valorDesconto", "valorTaxa",
        "numeroComprovanteManual", "flagEnvio", "nomePaciente", "observacoesPaciente",
        "enderecoPaciente", "codigoConvenio", "codigoFuncionario", "condicaoPagamento",
        "codigoCaptacao"
    ]

    try:
        response_data = json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f'Erro ao decodificar JSON: {e}')
        return []

    filtros_resultado = []

    if isinstance(response_data, list):
        for filtro_obj in response_data:
            filtro = filtro_obj.get('filtro', [])
            valor = filtro_obj.get('valor', [])
            operador = filtro_obj.get('operador', 'None')

            for prop in filtro:
                if prop in propriedades:
                    valor_atual = valor[filtro.index(prop)]
                    try:
                        valor_atual = int(valor_atual)
                    except ValueError:
                        pass
                    filtros_resultado.append({
                        'propriedade': prop,
                        'valor': valor_atual,
                        'operador': operador
                    })
    else:
        filtro = response_data.get('filtro', [])
        valor = response_data.get('valor', [])
        operador = response_data.get('operador', 'None')

        for prop in filtro:
            if prop in propriedades:
                valor_atual = valor[filtro.index(prop)]
                try:
                    valor_atual = int(valor_atual)
                except ValueError:
                    pass

                if prop == 'dataEntrada':
                    valor_atual = []
                    data_inicio = datetime(valor, 1, 1)
                    data_fim = datetime(valor, 12, 31)
                    valor.append(data_inicio)
                    valor.append(data_fim)
                filtros_resultado.append({
                    'propriedade': prop,
                    'valor': valor_atual,
                    'operador': operador
                })

    return filtros_resultado


def gpt_generate(objects, prompt_input):
    prompt = (
        f"Com base nesses dados em um contexto farmacêutico:\n{objects}\n"
        f"\n{prompt_input}\n"
    )
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "Você é um excelente assistente."},
            {"role": "user", "content": prompt}
        ],
    }
    response = requests.post(url, headers=headers, json=data)
    resultado = response.json()
    resultadoGPT = resultado['choices'][0]['message']['content']
    print()
    print(resultadoGPT)


def buscar_dados_pelo_nome():
    global query
    qtd = 0
    all_objects = []
    filter_query = []
    prompt_input = input('O que deseja saber da ProPharmacos?: ')
    filter_query = get_filter(prompt_input)
    if len(filter_query) > 0:
        for filtro in filter_query:
            if isinstance(filtro['valor'], list) and filtro['propriedade'] == 'dataEntrada':
                query = {filtro['propriedade']: {"$gte": filtro['valor'][0], "$lt": filtro['valor'][1]}}
            elif filtro['operador'] == 'None':
                query = {filtro['propriedade']: filtro['valor']}
            else:
                query = {filtro['propriedade']: {filtro['operador']: filtro['valor']}}
    resultado = collection.find(query).limit(20)
    for documento in resultado:
        all_objects.append(documento)
        qtd += 1
    print(f'Quantidade de registros encontrados: {qtd}')
    gpt_generate(all_objects, prompt_input)


buscar_dados_pelo_nome()
