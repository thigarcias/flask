import json
import re
from datetime import datetime

import google.generativeai as genai
import requests
from pymongo import MongoClient
from openai import OpenAI

from load_creds import load_creds

# Configurações do MongoDB
client = MongoClient('mongodb://localhost:27017/')
db = client['propharmaco']
collection = db['reqs']
api_key = 'sk-proj-haFqxKIaSvo73sH8dSEbT3BlbkFJCOfPR6vSd7qiRicR4QKH'

creds = load_creds()
genai.configure(credentials=creds)

# Configurações do Assistente
client_openai = OpenAI(api_key=api_key)
assistant = client_openai.beta.assistants.create(
    name="Pharma Assistant",
    instructions="You are a helpful assistant specialized in pharmacological data.",
    tools=[{"type": "code_interpreter"}],
    model="gpt-4o",
)

def get_filter(prompt_input):
    global valor_list
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
                    valor_list = []
                    data_inicio = datetime(valor_atual, 1, 1)
                    data_fim = datetime(valor_atual, 12, 31)
                    valor_list.append(data_inicio)
                    valor_list.append(data_fim)
                filtros_resultado.append({
                    'propriedade': prop,
                    'valor': valor_list,
                    'operador': operador
                })

    return filtros_resultado

def gpt_generate(assistant, thread, objects, prompt_input):
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

    # Adiciona a resposta ao thread
    client_openai.beta.threads.messages.create(
        thread_id=thread.id,
        role="assistant",
        content=resultadoGPT
    )
    print()
    print(resultadoGPT)

def iniciar_chat():
    collection.find_one()
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

    # Criar thread para a conversa
    thread = client_openai.beta.threads.create()

    # Adiciona mensagem inicial ao thread
    client_openai.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=prompt_input
    )

    gpt_generate(assistant, thread, all_objects, prompt_input)

    # Inicia o chat contínuo
    while True:
        user_input = input("Você: ")
        client_openai.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_input
        )
        run = client_openai.beta.threads.runs.create_and_poll(
            thread_id=thread.id,
            assistant_id=assistant.id,
        )
        if run.status == 'completed':
            messages = client_openai.beta.threads.messages.list(
                thread_id=thread.id
            )
            messages_list = list(messages)
            if messages_list:
                latest_message = messages_list[0]
                if latest_message.role == 'assistant':
                    print(latest_message.content[0].text.value)
        else:
            print(run.status)

iniciar_chat()
