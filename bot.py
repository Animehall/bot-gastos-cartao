import os
import json
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import pytz

FUSO_BR = pytz.timezone("America/Sao_Paulo")

app = Flask(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")

def get_sheet():
    creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet("📝 Registros")

def salvar_gasto(data, pessoa, categoria, descricao, valor_total, pagamento, parcelas, valor_parcela):
    sheet = get_sheet()
    sheet.append_row([data, pessoa, categoria, descricao, float(valor_total), pagamento, int(parcelas), float(valor_parcela)])

conversas = {}

PESSOAS    = ["Namorada", "Eu", "Mãe dela", "Pai dela", "Casal"]
CATEGORIAS = ["Alimentação", "Transporte", "Saúde", "Lazer", "Compras", "Serviços", "Educação", "Outros"]
PARCELAS   = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

def menu_pessoas():
    return "👤 *Quem gastou?*\n\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(PESSOAS, 1))

def menu_categorias():
    return "📂 *Qual a categoria?*\n\n" + "\n".join(f"{i}. {c}" for i, c in enumerate(CATEGORIAS, 1))

def menu_pagamento():
    return "💳 *Como foi o pagamento?*\n\n1. À Vista\n2. Parcelado"

def menu_parcelas():
    return "🔢 *Em quantas parcelas?*\n\nDigite o número de parcelas (2 a 12):\n\n" + "\n".join(f"{p}. {p}x" for p in PARCELAS)

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
            mes_atual = datetime.now(FUSO_BR).strftime("%Y-%m")
            totais = {}
            for r in registros:
                data_str = str(r.get("Data", ""))
                if not data_str.startswith(mes_atual):
                    continue
                pessoa = r.get("Quem Gastou", "?")
                valor = float(str(r.get("Valor Total (R$)", 0)).replace(",", "."))
                totais[pessoa] = totais.get(pessoa, 0) + valor

            if not totais:
                return "📊 Nenhum gasto registrado este mês ainda."

            linhas = [f"📊 *Resumo de {datetime.now(FUSO_BR).strftime('%B/%Y')}*\n"]
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
        conversas[numero] = {"etapa": "aguardando_pessoa", "dados": {"valor": valor, "descricao": descricao}}
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
                conversas[numero]["dados"]["categoria"] = CATEGORIAS[idx]
                conversas[numero]["etapa"] = "aguardando_pagamento"
                return menu_pagamento()
        except ValueError:
            pass
        return f"❌ Digite um número de 1 a {len(CATEGORIAS)}.\n\n" + menu_categorias()

    # ── Escolha de pagamento ─────────────────────────────────────────────────
    if etapa == "aguardando_pagamento":
        if texto in ("1", "à vista", "a vista"):
            dados = conversas[numero]["dados"]
            dados["pagamento"] = "À Vista"
            dados["parcelas"] = 1
            dados["valor_parcela"] = dados["valor"]
            conversas[numero]["etapa"] = "confirmando"
            return (
                f"✅ *Confirma o lançamento?*\n\n"
                f"📝 {dados['descricao']}\n"
                f"👤 {dados['pessoa']}\n"
                f"📂 {dados['categoria']}\n"
                f"💳 À Vista\n"
                f"💰 R$ {dados['valor']:.2f}\n\n"
                f"1. Sim, salvar\n2. Não, cancelar"
            )
        elif texto in ("2", "parcelado"):
            conversas[numero]["dados"]["pagamento"] = "Parcelado"
            conversas[numero]["etapa"] = "aguardando_parcelas"
            return menu_parcelas()
        return "❌ Digite 1 para À Vista ou 2 para Parcelado.\n\n" + menu_pagamento()

    # ── Escolha de parcelas ──────────────────────────────────────────────────
    if etapa == "aguardando_parcelas":
        try:
            num_parcelas = int(texto)
            if num_parcelas in PARCELAS:
                dados = conversas[numero]["dados"]
                dados["parcelas"] = num_parcelas
                dados["valor_parcela"] = dados["valor"] / num_parcelas
                conversas[numero]["etapa"] = "confirmando"
                return (
                    f"✅ *Confirma o lançamento?*\n\n"
                    f"📝 {dados['descricao']}\n"
                    f"👤 {dados['pessoa']}\n"
                    f"📂 {dados['categoria']}\n"
                    f"💳 Parcelado em {num_parcelas}x\n"
                    f"💰 Total: R$ {dados['valor']:.2f}\n"
                    f"📆 Parcela: R$ {dados['valor_parcela']:.2f}/mês\n\n"
                    f"1. Sim, salvar\n2. Não, cancelar"
                )
        except ValueError:
            pass
        return "❌ Digite um número entre 2 e 12.\n\n" + menu_parcelas()

    # ── Confirmação ──────────────────────────────────────────────────────────
    if etapa == "confirmando":
        if texto in ("1", "sim", "s"):
            dados = conversas[numero]["dados"]
            data_hoje = datetime.now(FUSO_BR).strftime("%Y-%m-%d")
            try:
                salvar_gasto(
                    data_hoje,
                    dados["pessoa"],
                    dados["categoria"],
                    dados["descricao"],
                    dados["valor"],
                    dados["pagamento"],
                    dados["parcelas"],
                    dados["valor_parcela"]
                )
                del conversas[numero]
                parcela_txt = (
                    f"💳 À Vista" if dados["parcelas"] == 1
                    else f"💳 {dados['parcelas']}x de R$ {dados['valor_parcela']:.2f}"
                )
                return (
                    f"✅ *Gasto salvo na planilha!*\n\n"
                    f"📅 {datetime.now(FUSO_BR).strftime('%d/%m/%Y')}\n"
                    f"👤 {dados['pessoa']}\n"
                    f"📂 {dados['categoria']}\n"
                    f"📝 {dados['descricao']}\n"
                    f"💰 R$ {dados['valor']:.2f}\n"
                    f"{parcela_txt}\n\n"
                    f"_Digite 'resumo' pra ver o total do mês._"
                )
            except Exception as e:
                del conversas[numero]
                return f"❌ Erro ao salvar na planilha: {e}"
        elif texto in ("2", "nao", "não", "n", "cancelar"):
            del conversas[numero]
            return "❌ Lançamento cancelado.\n\nDigite `gasto [valor] [descrição]` pra começar de novo."
        return "Digite 1 para confirmar ou 2 para cancelar."

    return resposta_inicial()


@app.route("/webhook", methods=["POST"])
def webhook():
    numero = request.form.get("From", "")
    texto  = request.form.get("Body", "")
    resp   = MessagingResponse()
    resp.message(processar_mensagem(numero, texto))
    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
