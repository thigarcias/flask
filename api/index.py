import os
import time

import openai
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
# Use o ID do assistente existente
assistant_id = 'asst_RyyyPn8XYQpptDfh2VFd8EZC'

openai.api_key = api_key
assistant_id = 'asst_O8Vy1pvfycCpWSVFqu7mkRJl'
def get_from_gpt(prompt):
    global cleaned_input

    def create_thread_and_run(assistant_id, user_input):
        # Cria uma nova thread
        thread = openai.beta.threads.create()
        thread_id = thread.id

        # Cria uma mensagem na thread
        openai.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_input
        )

        # Inicia a execução do assistente
        run = openai.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id
        )

        return run.id, thread_id

    def check_run_status(thread_id, run_id):
        run = openai.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run_id
        )
        return run.status

    def get_response(thread_id):
        messages = openai.beta.threads.messages.list(thread_id=thread_id)
        return messages.data

    # Cria a thread e inicia o assistente
    run_id, thread_id = create_thread_and_run(assistant_id, prompt)

    # Aguarda a conclusão
    status = check_run_status(thread_id, run_id)
    while status not in ["completed", "failed"]:
        time.sleep(2)
        status = check_run_status(thread_id, run_id)

    # Obtém a resposta
    response_messages = get_response(thread_id)
    for message in response_messages:
        if message.role == "assistant":
            content = message.content[0].text.value
            if content.startswith('```json\n') and content.endswith('\n```'):
                cleaned_input = content.replace('```json\n', '').replace('\n```', '')
            else:
                cleaned_input = content
    return cleaned_input

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
    global limit, collection, client_openai

    data = request.json
    prompt_input = data['prompt']
    all_objects = []

    # Obter query a partir do GPT
    query = get_from_gpt(prompt_input)

    # Verifica se a string da query contém 'ISODate'
    if 'ISODate' in query:
        # Substitui ISODate por datetime.fromisoformat
        query = query.replace("ISODate(", "datetime.fromisoformat(").replace("Z')", "')").replace("T", " ")

        # Tenta avaliar a string como um dicionário Python
        try:
            query_dict = eval(query, {'datetime': datetime})
        except Exception as e:
            return jsonify({'error': f'Erro ao avaliar a query: {e}', 'query': query}), 400
    else:
        # Tenta converter a string em um dicionário JSON
        try:
            query_dict = json.loads(query)
        except json.JSONDecodeError:
            # Se não for uma query válida, retorna a resposta diretamente
            thread = client_openai.beta.threads.create()
            client_openai.beta.threads.messages.create(
                thread_id=thread.id,
                role='user',
                content=prompt_input
            )
            return jsonify({
                'thread_id': thread.id,
                'response': query
            })

    # Executa a consulta no MongoDB
    resultado = collection.find(query_dict).limit(limit)
    for documento in resultado:
        all_objects.append(documento)

    # Cria um novo thread e gera resposta GPT
    thread = client_openai.beta.threads.create()
    client_openai.beta.threads.messages.create(
        thread_id=thread.id,
        role='user',
        content=prompt_input
    )
    resultado_gpt = gpt_generate(thread, all_objects, prompt_input)

    return jsonify({
        'thread_id': thread.id,
        'response': resultado_gpt
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
