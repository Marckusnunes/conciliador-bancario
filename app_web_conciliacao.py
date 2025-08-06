import streamlit as st
import pandas as pd
import re
import io
import csv
import numpy as np
from fpdf import FPDF
from datetime import datetime

# --- Bloco 1: Lógica Principal da Conciliação (com ajustes) ---
def realizar_conciliacao(arquivo_relatorio, arquivo_extrato_consolidado):
    # --- Processamento do Relatório Contábil ---
    df_report = pd.read_csv(arquivo_relatorio, sep=';', encoding='latin-1')
    if "Unidade Gestora" in df_report.columns[0]:
        df_report.columns = ["Unidade_Gestora", "Domicilio_Bancario", "Conta_Contabil", "Conta_Corrente", "Saldo_Inicial", "Debito", "Credito", "Saldo_Final"]
        if "Unidade Gestora" in df_report.iloc[0].to_string():
            df_report = df_report.drop(df_report.index[0])
    
    colunas_numericas_report = ["Saldo_Inicial", "Debito", "Credito", "Saldo_Final"]
    for col in colunas_numericas_report:
        if col in df_report.columns:
            df_report[col] = df_report[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df_report[col] = pd.to_numeric(df_report[col], errors='coerce')
    
    contas_de_interesse = ['111111901', '111115001']
    df_report = df_report[df_report['Conta_Contabil'].str.contains('|'.join(contas_de_interesse), na=False)].copy()

    def extrair_conta_chave_report(texto_conta):
        match = re.search(r'\d{7,}', str(texto_conta))
        return int(match.group(0)) if match else None

    df_report['Conta_Chave'] = df_report['Conta_Corrente'].apply(extrair_conta_chave_report)
    df_report = df_report[['Conta_Chave', 'Conta_Corrente', 'Conta_Contabil', 'Saldo_Final']].dropna(subset=['Conta_Chave'])
    df_report['Conta_Chave'] = df_report['Conta_Chave'].astype(int)

    # --- Processamento do Extrato Consolidado ---
    dados_extrato = []
    stringio = io.StringIO(arquivo_extrato_consolidado.getvalue().decode('latin-1'))
    next(stringio) 
    reader = csv.reader(stringio, quotechar='"', delimiter=',')
    for row in reader:
        if len(row) >= 6:
            dados_extrato.append(row[:6])

    colunas_extrato = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente', 'Saldo_Invest', 'Saldo_Aplicado']
    df_extrato = pd.DataFrame(dados_extrato, columns=colunas_extrato)
    
    colunas_saldo_extrato = ['Saldo_Corrente', 'Saldo_Aplicado']
    for col in colunas_saldo_extrato:
        df_extrato[col] = df_extrato[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df_extrato[col] = pd.to_numeric(df_extrato[col], errors='coerce').fillna(0)

    def extrair_conta_chave_extrato(texto_conta):
        try:
            numeros = re.sub(r'[\.\-]', '', str(texto_conta).split('-')[0])
            return int(numeros) if numeros else None
        except (ValueError, IndexError):
            return None
            
    df_extrato['Conta_Chave'] = df_extrato['Conta'].apply(extrair_conta_chave_extrato)
    
    df_final_balances = df_extrato[['Conta_Chave', 'Saldo_Corrente', 'Saldo_Aplicado']].dropna(subset=['Conta_Chave'])
    df_final_balances['Conta_Chave'] = df_final_balances['Conta_Chave'].astype(int)
    df_final_balances = df_final_balances.groupby('Conta_Chave')[['Saldo_Corrente', 'Saldo_Aplicado']].sum().reset_index()

    # --- Lógica da Conciliação ---
    df_reconciliation = pd.merge(df_report, df_final_balances, on='Conta_Chave', how='left')
    df_reconciliation['Saldo_Corrente'].fillna(0, inplace=True)
    df_reconciliation['Saldo_Aplicado'].fillna(0, inplace=True)
    
    # MUDANÇA: Lógica condicional corrigida conforme sua instrução "É o contrário"
    condicoes = [
        df_reconciliation['Conta_Contabil'].str.contains('111115001', na=False), # Se for Aplicação...
        df_reconciliation['Conta_Contabil'].str.contains('111111901', na=False)  # Se for Conta Movimento...
    ]
    escolhas = [
        df_reconciliation['Saldo_Aplicado'],  # ...use o Saldo Aplicado do extrato.
        df_reconciliation['Saldo_Corrente']   # ...use o Saldo Corrente do extrato.
    ]
    df_reconciliation['Saldo_Extrato'] = np.select(condicoes, escolhas, default=0)

    df_reconciliation['Diferenca'] = df_reconciliation['Saldo_Final'] - df_reconciliation['Saldo_Extrato']
    for col in ['Saldo_Final', 'Saldo_Extrato', 'Diferenca']:
        df_reconciliation[col] = df_reconciliation[col].round(2)
    
    df_reconciliation = df_reconciliation[['Conta_Contabil', 'Conta_Corrente', 'Saldo_Final', 'Saldo_Extrato', 'Diferenca']]
    return df_reconciliation

# --- Bloco 2: Funções para Geração de Arquivos ---
@st.cache_data
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Conciliacao')
    processed_data = output.getvalue()
    return processed_data

class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Relatório de Conciliação de Saldos Bancários', 0, 1, 'C')
        self.ln(5)
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')
    def chapter_title(self, title):
        self.set_font('Arial', 'B', 10)
        self.cell(0, 10, title, 0, 1, 'L')
        self.ln(5)
    def create_table(self, data):
        self.set_font('Arial', 'B', 7)
        col_widths = [55, 55, 25, 25, 25]
        headers = list(data.columns)
        formatted_data = data.copy()
        for col in ['Saldo_Final', 'Saldo_Extrato', 'Diferenca']:
            formatted_data[col] = formatted_data[col].apply(lambda x: f'{x:,.2f}'.replace(",", "X").replace(".", ",").replace("X", "."))
        for i, header in enumerate(headers):
            self.cell(col_widths[i], 8, header, 1, 0, 'C')
        self.ln()
        self.set_font('Arial', '', 6)
        for index, row in formatted_data.iterrows():
            row['Conta_Contabil'] = (row['Conta_Contabil'][:30] + '...') if len(str(row['Conta_Contabil'])) > 30 else row['Conta_Contabil']
            row['Conta_Corrente'] = (row['Conta_Corrente'][:32] + '...') if len(str(row['Conta_Corrente'])) > 32 else row['Conta_Corrente']
            for i, item in enumerate(row):
                self.cell(col_widths[i], 8, str(item), 1)
            self.ln()

def create_pdf(df):
    pdf = PDF('P', 'mm', 'A4')
    pdf.add_page()
    pdf.chapter_title(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    pdf.create_table(df)
    return bytes(pdf.output())

# --- Bloco 3: Interface Web com Streamlit ---
st.set_page_config(page_title="Conciliação Bancária", layout="wide")
st.title("Ferramenta de Conciliação de Saldos Bancários")

st.sidebar.header("1. Carregar Arquivos")
arquivo_relatorio_carregado = st.sidebar.file_uploader("Selecione o Relatório Contábil (CSV Original)", type=['csv'])
arquivo_extrato_consolidado_carregado = st.sidebar.file_uploader("Selecione o Extrato Consolidado (CSV)", type=['csv'])

st.sidebar.header("2. Processar")
if arquivo_relatorio_carregado and arquivo_extrato_consolidado_carregado:
    if st.sidebar.button("Conciliar Agora"):
        with st.spinner("Processando..."):
            try:
                df_resultado = realizar_conciliacao(arquivo_relatorio_carregado, arquivo_extrato_consolidado_carregado)
                st.success("Conciliação Concluída com Sucesso!")
                st.session_state['df_resultado'] = df_resultado
            except Exception as e:
                st.error(f"Ocorreu um erro durante o processamento: {e}")
else:
    st.sidebar.warning("Por favor, carregue o relatório e o extrato consolidado.")

if 'df_resultado' in st.session_state:
    df_final = st.session_state['df_resultado']
    st.header("Resultado da Conciliação")
    df_para_mostrar = df_final[df_final['Diferenca'] != 0].copy()
    if df_para_mostrar.empty:
        st.success("Ótima notícia! Nenhuma divergência encontrada. Todos os saldos foram conciliados.")
    else:
        st.write("A tabela abaixo mostra apenas as contas com divergência de saldo.")
        st.dataframe(df_para_mostrar.style.format(
            formatter={
                'Saldo_Final': lambda x: f'{x:,.2f}'.replace(",", "X").replace(".", ",").replace("X", "."),
                'Saldo_Extrato': lambda x: f'{x:,.2f}'.replace(",", "X").replace(".", ",").replace("X", "."),
                'Diferenca': lambda x: f'{x:,.2f}'.replace(",", "X").replace(".", ",").replace("X", ".")
            }
        ).map(lambda x: 'color: red' if x < 0 else 'color: black', subset=['Diferenca']))

    st.header("Download do Relatório Completo")
    st.write("Os arquivos para download contêm todas as contas, incluindo as que não apresentaram divergência.")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button("Baixar em CSV", df_final.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig'), 'relatorio_conciliacao.csv', 'text/csv')
    with col2:
        st.download_button("Baixar em Excel", to_excel(df_final), 'relatorio_conciliacao.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    with col3:
        st.download_button("Baixar em PDF", create_pdf(df_final), 'relatorio_conciliacao.pdf', 'application/pdf')