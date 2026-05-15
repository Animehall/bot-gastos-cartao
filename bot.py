import os
import json
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

app = Flask(__name__)

# ── Google Sheets setup ──────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = os.environ["GOOGLE_SHEET_ID"]  # ID da sua planilha

def get_sheet():
    creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet("📝 Registros")

def salvar_gasto(data, pessoa, categoria, descricao, valor):
    sheet = get_sheet()
    sheet.append_row([data, pessoa, categoria, descricao, float(valor)])

# ── Estado da conversa (em memória) ─────────────────────────────────────────
# { numero: { "etapa": ..., "dados": {...} } }
conversas = {}

PESSOAS = ["Namorada", "Eu", "Mãe dela", "Pai dela"]
CATEGORIAS = ["Alimentação", "Transporte", "Saúde", "Lazer", "Compras", "Serviços", "Educação", "Outros"]

def menu_pessoas():
    linhas = ["👤 *Quem gastou?*\n"]
    for i, p in enumerate(PESSOAS, 1):
        linhas.append(f"{i}. {p}")
    return "\n".join(linhas)

def menu_categorias():
    linhas = ["📂 *Qual a categoria?*\n"]
    for i, c in enumerate(CATEGORIAS, 1):
        linhas.append(f"{i}. {c}")
    return "\n".join(linhas)

def resposta_inicial():
    return (
        "💳 *Bot de Gastos do Cartão*\n\n"
        "Me manda uma mensagem no formato:\n"
        "➡️ *gasto [valor] [descrição]*\n\n"
        "Exemplo: `gasto 45.90 uber`\n\n"
        "Ou digite *resumo* pra ver o total do mês."
    )

def processar_mensagem(numero, texto):
    texto = texto.strip().lower()
    estado = conversas.get(numero, {})
    etapa = estado.get("etapa", "inicio")

    # ── Resumo ───────────────────────────────────────────────────────────────
    if texto == "resumo":
        try:
            sheet = get_sheet()
            registros = sheet.get_all_records()
            mes_atual = datetime.now().strftime("%Y-%m")
            totais = {}
            for r in registros:
                data_str = str(r.get("Data", ""))
                if not data_str.startswith(mes_atual):
                    continue
                pessoa = r.get("Quem Gastou", "?")
                valor = float(str(r.get("Valor (R$)", 0)).replace(",", "."))
                totais[pessoa] = totais.get(pessoa, 0) + valor

            if not totais:
                return "📊 Nenhum gasto registrado este mês ainda."

            linhas = [f"📊 *Resumo de {datetime.now().strftime('%B/%Y')}*\n"]
            total_geral = 0
            for pessoa, val in totais.items():
                linhas.append(f"• {pessoa}: R$ {val:.2f}")
                total_geral += val
            linhas.append(f"\n💰 *Total: R$ {total_geral:.2f}*")
            return "\n".join(linhas)
        except Exception as e:
            return f"❌ Erro ao buscar resumo: {e}"

    # ── Início de novo gasto ─────────────────────────────────────────────────
    if texto.startswith("gasto "):
        partes = texto.split(" ", 2)
        if len(partes) < 3:
            return "❌ Formato inválido. Use: `gasto 45.90 descrição`"
        try:
            valor = float(partes[1].replace(",", "."))
        except ValueError:
            return "❌ Valor inválido. Ex: `gasto 45.90 mercado`"

        descricao = partes[2].strip().title()
        conversas[numero] = {
            "etapa": "aguardando_pessoa",
            "dados": {"valor": valor, "descricao": descricao}
        }
        return menu_pessoas()

    # ── Escolha de pessoa ────────────────────────────────────────────────────
    if etapa == "aguardando_pessoa":
        try:
            idx = int(texto) - 1
            if 0 <= idx < len(PESSOAS):
                conversas[numero]["dados"]["pessoa"] = PESSOAS[idx]
                conversas[numero]["etapa"] = "aguardando_categoria"
                return menu_categorias()
        except ValueError:
            pass
        return f"❌ Digite um número de 1 a {len(PESSOAS)}.\n\n" + menu_pessoas()

    # ── Escolha de categoria ─────────────────────────────────────────────────
    if etapa == "aguardando_categoria":
        try:
            idx = int(texto) - 1
            if 0 <= idx < len(CATEGORIAS):
                dados = conversas[numero]["dados"]
                dados["categoria"] = CATEGORIAS[idx]
                data_hoje = datetime.now().strftime("%Y-%m-%d")
                try:
                    salvar_gasto(
                        data_hoje,
                        dados["pessoa"],
                        dados["categoria"],
                        dados["descricao"],
                        dados["valor"]
                    )
                    del conversas[numero]
                    return (
                        f"✅ *Gasto registrado!*\n\n"
                        f"📅 {datetime.now().strftime('%d/%m/%Y')}\n"
                        f"👤 {dados['pessoa']}\n"
                        f"📂 {dados['categoria']}\n"
                        f"📝 {dados['descricao']}\n"
                        f"💰 R$ {dados['valor']:.2f}\n\n"
                        f"_Digite 'resumo' pra ver o total do mês._"
                    )
                except Exception as e:
                    del conversas[numero]
                    return f"❌ Erro ao salvar na planilha: {e}"
        except ValueError:
            pass
        return f"❌ Digite um número de 1 a {len(CATEGORIAS)}.\n\n" + menu_categorias()

    # ── Fallback ─────────────────────────────────────────────────────────────
    return resposta_inicial()


@app.route("/webhook", methods=["POST"])
def webhook():
    numero = request.form.get("From", "")
    texto = request.form.get("Body", "")
    resposta = processar_mensagem(numero, texto)
    resp = MessagingResponse()
    resp.message(resposta)
    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
