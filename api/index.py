import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
import json
import re
from datetime import datetime
import google.generativeai as genai
import requests
from pymongo import MongoClient
from openai import OpenAI
from load_creds import load_creds
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": '*'}})

load_dotenv()

# Acessa as variáveis de ambiente
api_key = os.getenv('API_KEY')

# Configurações do MongoDB
client = MongoClient('mongodb://gogood:gogood24@gogood.brazilsouth.cloudapp.azure.com:27017/?authSource=admin')
db = client['propharmaco']
collection = db['reqs']

creds = load_creds()
genai.configure(credentials=creds)

# Configurações do Assistente
client_openai = OpenAI(api_key=api_key)
assistant_id = 'asst_0UdwfvwIpzwVLq8ZFFMxsDxJ'


def get_filter(prompt_input):
    valor_list = []
    model = genai.GenerativeModel(
        model_name="tunedModels/the-goat-hcbxhb1ke1wk",
    )
    prompt_to_gemini = """
    Com base no prompt, colete as informações mais relevantes e caso ele tenha relação com a lista "Propriedades", retorne um filtro:
    Prompt: '{0}'
    Propriedades: "codigoFilial,numeroOrcamento,codigoFilialDestino,codigoCliente,dataEntrada,valorRequisitado,valorDesconto,valorTaxa,numeroComprovanteManual,flagEnvio,nomePaciente,observacoesPaciente,enderecoPaciente,codigoConvenio,codigoFuncionario,condicaoPagamento,codigoCaptacao, dadosBanco"
    Filtro: '{{propriedade: "PROPRIEDADE", valor: "VALOR"}}'
    
    Ignore tudo que você conhece do mundo, apenas faça o que foi pedido.
    """.format(prompt_input)

    chat_session = model.start_chat(history=[])
    response = chat_session.send_message(prompt_to_gemini)
    response_text = response.text

    propriedades = [
        "codigoFilial", "numeroOrcamento", "codigoFilialDestino", "codigoCliente",
        "dataEntrada", "valorRequisitado", "valorDesconto", "valorTaxa",
        "numeroComprovanteManual", "flagEnvio", "nomePaciente", "observacoesPaciente",
        "enderecoPaciente", "codigoConvenio", "codigoFuncionario", "condicaoPagamento",
        "codigoCaptacao", "dadosBanco"
    ]
    if 'true' in response_text:
        response_text = response_text.replace('true', 'True')

    if response_text == 'dadosBanco':
        return response_text
    try:
        response_data = eval(response_text)

    except json.JSONDecodeError as e:
        print(f'Erro ao decodificar JSON: {e}')
        return []
    if 'nomePaciente' in response_data:
        response_data['nomePaciente'] = response_data['nomePaciente'].upper()

    return response_data


def gpt_generate(thread, objects, prompt_input):
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

    # Log da resposta completa para depuração
    print("Resposta da API:", json.dumps(resultado, indent=2))

    if 'choices' in resultado and len(resultado['choices']) > 0:
        resultadoGPT = resultado['choices'][0]['message']['content']
    else:
        # Lidar com a ausência de 'choices' na resposta
        resultadoGPT = "Erro: A resposta da API não contém a chave 'choices'. Verifique a solicitação e tente novamente."
        print("Erro na resposta da API:", resultado)

    # Adiciona a resposta ao thread
    client_openai.beta.threads.messages.create(
        thread_id=thread.id,
        role="assistant",
        content=resultadoGPT
    )

    return resultadoGPT


@app.route('/iniciar_chat', methods=['POST'])
def iniciar_chat():
    global limit
    data = request.json
    prompt_input = data['prompt']
    all_objects = []
    filter_query = get_filter(prompt_input)
    print("Filtro:", filter_query)
    if filter_query != 'dadosBanco':
        resultado = collection.find(filter_query).limit(limit)
        for documento in resultado:
            all_objects.append(documento)
        # Cria uma nova thread para cada nova interação
        thread = client_openai.beta.threads.create()
        client_openai.beta.threads.messages.create(
            thread_id=thread.id,
            role='user',
            content=prompt_input
        )
        resultadoGPT = gpt_generate(thread, all_objects, prompt_input)

        return jsonify({
            'thread_id': thread.id,
            'response': resultadoGPT
        })
    else:
        resultado = collection.find_one()
        all_objects.append(resultado)
        # Cria uma nova thread para cada nova interação
        thread = client_openai.beta.threads.create()
        client_openai.beta.threads.messages.create(
            thread_id=thread.id,
            role='user',
            content=prompt_input
        )
        resultadoGPT = gpt_generate(thread, all_objects, prompt_input)

        return jsonify({
            'thread_id': thread.id,
            'response': resultadoGPT
        })


limit = 50


@app.route('/mudar_limit', methods=['POST'])
def mudar_limite():
    global limit
    data = request.json
    limit = data['limit']
    return jsonify({
        'limit': limit
    })


@app.route('/continuar_chat', methods=['POST'])
def continuar_chat():
    data = request.json
    thread_id = data['thread_id']
    user_input = data['input']

    client_openai.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=user_input
    )
    run = client_openai.beta.threads.runs.create_and_poll(
        thread_id=thread_id,
        assistant_id=assistant_id,
    )
    if run.status == 'completed':
        messages = client_openai.beta.threads.messages.list(
            thread_id=thread_id
        )
        messages_list = list(messages)
        if messages_list:
            latest_message = messages_list[0]
            if latest_message.role == 'assistant':
                return jsonify({
                    'response': latest_message.content[0].text.value
                })
    else:
        return jsonify({
            'status': run.status
        })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
