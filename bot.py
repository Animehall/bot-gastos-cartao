import os
import json
import logging
from flask import Flask, request
import telebot
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import pytz

logging.basicConfig(level=logging.INFO)
FUSO_BR  = pytz.timezone("America/Sao_Paulo")
SCOPES   = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN", "")
APP_URL  = os.environ.get("RENDER_EXTERNAL_URL", "")

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

def get_sheet():
    creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet("📝 Registros")

def salvar_gasto(data, pessoa, categoria, descricao, valor_total, pagamento, parcelas, valor_parcela):
    get_sheet().append_row([data, pessoa, categoria, descricao, float(valor_total), pagamento, int(parcelas), float(valor_parcela)])

conversas = {}
PESSOAS    = ["Namorada", "Eu", "Mãe dela", "Pai dela", "Casal"]
CATEGORIAS = ["Alimentação", "Transporte", "Saúde", "Lazer", "Compras", "Serviços", "Educação", "Outros"]
PARCELAS   = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

def menu_pessoas():
    return "👤 Quem gastou?\n\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(PESSOAS, 1))

def menu_categorias():
    return "📂 Qual a categoria?\n\n" + "\n".join(f"{i}. {c}" for i, c in enumerate(CATEGORIAS, 1))

def menu_pagamento():
    return "💳 Como foi o pagamento?\n\n1. À Vista\n2. Parcelado"

def menu_parcelas():
    return "🔢 Em quantas parcelas?\n\nDigite o número (2 a 12):\n\n" + "\n".join(f"{p}. {p}x" for p in PARCELAS)

def resposta_inicial():
    return (
        "💳 Bot de Gastos do Cartão\n\n"
        "Me manda uma mensagem no formato:\n"
        "➡️ gasto [valor] [descrição]\n\n"
        "Exemplo: gasto 45.90 uber\n\n"
        "Ou digite /resumo pra ver o total do mês."
    )

def processar_mensagem(user_id, texto):
    texto_lower = texto.strip().lower()
    estado = conversas.get(user_id, {})
    etapa  = estado.get("etapa", "inicio")

    if texto_lower in ("resumo", "/resumo"):
        try:
            registros = get_sheet().get_all_records()
            mes_atual = datetime.now(FUSO_BR).strftime("%Y-%m")
            totais    = {}
            for r in registros:
                if not str(r.get("Data", "")).startswith(mes_atual):
                    continue
                pessoa    = r.get("Quem Gastou", "?")
                valor_raw = str(r.get("Valor Total (R$)", 0)).replace("R$","").replace(" ","").replace(".","").replace(",",".")
                try: valor = float(valor_raw) if valor_raw else 0.0
                except: valor = 0.0
                totais[pessoa] = totais.get(pessoa, 0) + valor
            if not totais:
                return "📊 Nenhum gasto registrado este mês ainda."
            linhas = [f"📊 Resumo de {datetime.now(FUSO_BR).strftime('%B/%Y')}\n"]
            total_geral = 0
            for pessoa, val in totais.items():
                linhas.append(f"• {pessoa}: R$ {val:.2f}")
                total_geral += val
            linhas.append(f"\n💰 Total: R$ {total_geral:.2f}")
            return "\n".join(linhas)
        except Exception as e:
            return f"❌ Erro ao buscar resumo: {e}"

    if texto_lower.startswith("gasto "):
        partes = texto_lower.split(" ", 2)
        if len(partes) < 3:
            return "❌ Formato inválido. Use: gasto 45.90 descrição"
        try: valor = float(partes[1].replace(",", "."))
        except: return "❌ Valor inválido. Ex: gasto 45.90 mercado"
        conversas[user_id] = {"etapa": "aguardando_pessoa", "dados": {"valor": valor, "descricao": partes[2].strip().title()}}
        return menu_pessoas()

    if etapa == "aguardando_pessoa":
        try:
            idx = int(texto_lower) - 1
            if 0 <= idx < len(PESSOAS):
                conversas[user_id]["dados"]["pessoa"] = PESSOAS[idx]
                conversas[user_id]["etapa"] = "aguardando_categoria"
                return menu_categorias()
        except: pass
        return f"❌ Digite um número de 1 a {len(PESSOAS)}.\n\n" + menu_pessoas()

    if etapa == "aguardando_categoria":
        try:
            idx = int(texto_lower) - 1
            if 0 <= idx < len(CATEGORIAS):
                conversas[user_id]["dados"]["categoria"] = CATEGORIAS[idx]
                conversas[user_id]["etapa"] = "aguardando_pagamento"
                return menu_pagamento()
        except: pass
        return f"❌ Digite um número de 1 a {len(CATEGORIAS)}.\n\n" + menu_categorias()

    if etapa == "aguardando_pagamento":
        if texto_lower in ("1", "à vista", "a vista"):
            dados = conversas[user_id]["dados"]
            dados.update({"pagamento": "À Vista", "parcelas": 1, "valor_parcela": dados["valor"]})
            conversas[user_id]["etapa"] = "confirmando"
            return (f"✅ Confirma o lançamento?\n\n📝 {dados['descricao']}\n👤 {dados['pessoa']}\n"
                    f"📂 {dados['categoria']}\n💳 À Vista\n💰 R$ {dados['valor']:.2f}\n\n1. Sim\n2. Não")
        elif texto_lower in ("2", "parcelado"):
            conversas[user_id]["dados"]["pagamento"] = "Parcelado"
            conversas[user_id]["etapa"] = "aguardando_parcelas"
            return menu_parcelas()
        return "❌ Digite 1 para À Vista ou 2 para Parcelado.\n\n" + menu_pagamento()

    if etapa == "aguardando_parcelas":
        try:
            num_parcelas = int(texto_lower)
            if num_parcelas in PARCELAS:
                dados = conversas[user_id]["dados"]
                dados.update({"parcelas": num_parcelas, "valor_parcela": dados["valor"] / num_parcelas})
                conversas[user_id]["etapa"] = "confirmando"
                return (f"✅ Confirma o lançamento?\n\n📝 {dados['descricao']}\n👤 {dados['pessoa']}\n"
                        f"📂 {dados['categoria']}\n💳 {num_parcelas}x\n💰 Total: R$ {dados['valor']:.2f}\n"
                        f"📆 Parcela: R$ {dados['valor_parcela']:.2f}/mês\n\n1. Sim\n2. Não")
        except: pass
        return "❌ Digite um número entre 2 e 12.\n\n" + menu_parcelas()

    if etapa == "confirmando":
        if texto_lower in ("1", "sim", "s"):
            dados = conversas[user_id]["dados"]
            try:
                salvar_gasto(datetime.now(FUSO_BR).strftime("%Y-%m-%d"), dados["pessoa"], dados["categoria"],
                             dados["descricao"], dados["valor"], dados["pagamento"], dados["parcelas"], dados["valor_parcela"])
                del conversas[user_id]
                parcela_txt = "💳 À Vista" if dados["parcelas"] == 1 else f"💳 {dados['parcelas']}x de R$ {dados['valor_parcela']:.2f}"
                return (f"✅ Gasto salvo!\n\n📅 {datetime.now(FUSO_BR).strftime('%d/%m/%Y')}\n"
                        f"👤 {dados['pessoa']}\n📂 {dados['categoria']}\n📝 {dados['descricao']}\n"
                        f"💰 R$ {dados['valor']:.2f}\n{parcela_txt}\n\nDigite /resumo pra ver o total do mês.")
            except Exception as e:
                del conversas[user_id]
                return f"❌ Erro ao salvar: {e}"
        elif texto_lower in ("2", "nao", "não", "n", "cancelar"):
            del conversas[user_id]
            return "❌ Cancelado. Digite gasto [valor] [descrição] pra começar de novo."
        return "Digite 1 para confirmar ou 2 para cancelar."

    return resposta_inicial()

# ── Handlers ──────────────────────────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def handle_start(message):
    bot.reply_to(message, resposta_inicial())

@bot.message_handler(commands=["resumo"])
def handle_resumo(message):
    bot.reply_to(message, processar_mensagem(message.from_user.id, "resumo"))

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    bot.reply_to(message, processar_mensagem(message.from_user.id, message.text or ""))

# ── Webhook Flask ─────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    return "Bot rodando!", 200

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.get_json())
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    url = f"{APP_URL}/{TOKEN}"
    bot.remove_webhook()
    bot.set_webhook(url=url)
    return f"Webhook definido: {url}", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    # Define o webhook automaticamente ao iniciar
    if APP_URL:
        bot.remove_webhook()
        bot.set_webhook(url=f"{APP_URL}/{TOKEN}")
        print(f"Webhook definido: {APP_URL}/{TOKEN}")
    app.run(host="0.0.0.0", port=port)
