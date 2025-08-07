import streamlit as st
import pandas as pd
import re
import io
import csv
import numpy as np
from fpdf import FPDF
from datetime import datetime

# --- Bloco 1: Lógica Principal da Conciliação ---
def realizar_conciliacao(arquivo_relatorio, arquivo_extrato_consolidado):
    # --- Processamento do Relatório Contábil ---
    df_report = pd.read_csv(arquivo_relatorio, sep=';', encoding='latin-1')
    if "Unidade Gestora" in df_report.columns[0]:
        df_report.columns = ["Unidade_Gestora", "Domicilio_Bancario", "Conta_Contabil", "Conta_Corrente", "Saldo_Inicial", "Debito", "Credito", "Saldo_Final"]
        if "Unidade Gestora" in df_report.iloc[0].to_string():
            df_report = df_report.drop(df_report.index[0])
    
    colunas_numericas_report = ["Saldo_Final"]
    for col in colunas_numericas_report:
        if col in df_report.columns:
            df_report[col] = df_report[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df_report[col] = pd.to_numeric(df_report[col], errors='coerce')
    
    def extrair_conta_chave_report(texto_conta):
        match = re.search(r'\d{7,}', str(texto_conta))
        return int(match.group(0)) if match else None

    df_report['Conta_Chave'] = df_report['Conta_Corrente'].apply(extrair_conta_chave_report)
    df_report.dropna(subset=['Conta_Chave'], inplace=True)
    df_report['Conta_Chave'] = df_report['Conta_Chave'].astype(int)

    df_movimento_contabil = df_report[df_report['Conta_Contabil'].str.contains('111111901', na=False)]
    df_movimento_contabil = df_movimento_contabil.groupby('Conta_Chave')['Saldo_Final'].sum().reset_index()
    df_movimento_contabil.rename(columns={'Saldo_Final': 'Saldo_Contabil_Movimento'}, inplace=True)

    df_aplicacao_contabil = df_report[df_report['Conta_Contabil'].str.contains('111115001', na=False)]
    df_aplicacao_contabil = df_aplicacao_contabil.groupby('Conta_Chave')['Saldo_Final'].sum().reset_index()
    df_aplicacao_contabil.rename(columns={'Saldo_Final': 'Saldo_Contabil_Aplicacao'}, inplace=True)

    df_report_pivot = pd.merge(df_movimento_contabil, df_aplicacao_contabil, on='Conta_Chave', how='outer')
    mapa_domicilio = df_report[['Conta_Chave', 'Domicilio_Bancario']].drop_duplicates().set_index('Conta_Chave')

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
    df_extrato.rename(columns={'Saldo_Corrente': 'Saldo_Extrato_Movimento', 'Saldo_Aplicado': 'Saldo_Extrato_Aplicacao'}, inplace=True)

    def extrair_conta_chave_extrato(texto_conta):
        try:
            numeros = re.sub(r'\D', '', str(texto_conta))
            return int(numeros) if numeros else None
        except (ValueError, IndexError):
            return None
            
    df_extrato['Conta_Chave'] = df_extrato['Conta'].apply(extrair_conta_chave_extrato)
    
    df_extrato_pivot = df_extrato[['Conta_Chave', 'Saldo_Extrato_Movimento', 'Saldo_Extrato_Aplicacao']].dropna(subset=['Conta_Chave'])
    df_extrato_pivot['Conta_Chave'] = df_extrato_pivot['Conta_Chave'].astype(int)
    df_extrato_pivot = df_extrato_pivot.groupby('Conta_Chave').sum().reset_index()

    # --- Consolidação e Reestruturação Final ---
    df_final = pd.merge(df_report_pivot, df_extrato_pivot, on='Conta_Chave', how='outer')
    df_final.fillna(0, inplace=True)
    df_final = df_final.join(mapa_domicilio, on='Conta_Chave')
    df_final['Domicilio_Bancario'].fillna('Não encontrado no relatório', inplace=True)
    df_final = df_final[df_final['Conta_Chave'] != 0]

    df_final['Diferenca_Movimento'] = df_final['Saldo_Contabil_Movimento'] - df_final['Saldo_Extrato_Movimento']
    df_final['Diferenca_Aplicacao'] = df_final['Saldo_Contabil_Aplicacao'] - df_final['Saldo_Extrato_Aplicacao']
    
    df_final = df_final.set_index('Domicilio_Bancario')
    df_final = df_final[[
        'Saldo_Contabil_Movimento', 'Saldo_Extrato_Movimento', 'Diferenca_Movimento',
        'Saldo_Contabil_Aplicacao', 'Saldo_Extrato_Aplicacao', 'Diferenca_Aplicacao'
    ]]
    
    df_final.columns = pd.MultiIndex.from_tuples([
        ('Conta Movimento', 'Saldo Contábil'), ('Conta Movimento', 'Saldo Extrato'), ('Conta Movimento', 'Diferença'),
        ('Aplicação Financeira', 'Saldo Contábil'), ('Aplicação Financeira', 'Saldo Extrato'), ('Aplicação Financeira', 'Diferença')
    ], names=['Grupo', 'Item'])
    
    return df_final

# --- Bloco 2: Funções para Geração de Arquivos ---
@st.cache_data
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=True, sheet_name='Conciliacao_Consolidada')
    return output.getvalue()

class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 10)
        self.cell(0, 10, 'Relatório de Conciliação Consolidado por Conta', 0, 1, 'C')
        self.ln(5)
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')
    def create_table(self, data):
        self.set_font('Arial', '', 7)
        line_height = self.font_size * 2.5
        col_width = 30 
        
        self.set_font('Arial', 'B', 8)
        index_name = data.index.name if data.index.name else 'ID'
        self.cell(55, line_height, index_name, 1, 0, 'C')
        self.cell(col_width * 3, line_height, 'Conta Movimento', 1, 0, 'C')
        self.cell(col_width * 3, line_height, 'Aplicação Financeira', 1, 0, 'C')
        self.ln(line_height)
        
        self.set_font('Arial', 'B', 7)
        self.cell(55, line_height, '', 1, 0, 'C')
        sub_headers = ['Saldo Contábil', 'Saldo Extrato', 'Diferença']
        for _ in range(2):
            for sub_header in sub_headers:
                self.cell(col_width, line_height, sub_header, 1, 0, 'C')
        self.ln(line_height)

        self.set_font('Arial', '', 6)
        formatted_data = data.copy()
        for col_tuple in formatted_data.columns:
             formatted_data[col_tuple] = formatted_data[col_tuple].apply(lambda x: f'{x:,.2f}'.replace(",", "X").replace(".", ",").replace("X", "."))

        for index, row in formatted_data.iterrows():
            display_index = (index[:35] + '...') if len(str(index)) > 35 else index
            self.cell(55, line_height, str(display_index), 1, 0, 'L')
            for item in row:
                self.cell(col_width, line_height, str(item), 1, 0, 'R')
            self.ln(line_height)

def create_pdf(df):
    pdf = PDF('L', 'mm', 'A4')
    pdf.add_page()
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
                df_resultado_formatado = realizar_conciliacao(arquivo_relatorio_carregado, arquivo_extrato_consolidado_carregado)
                st.success("Conciliação Concluída com Sucesso!")
                st.session_state['df_resultado'] = df_resultado_formatado
            except Exception as e:
                st.error(f"Ocorreu um erro durante o processamento: {e}")
else:
    st.sidebar.warning("Por favor, carregue o relatório e o extrato consolidado.")

if 'df_resultado' in st.session_state:
    df_final_formatado = st.session_state['df_resultado']
    st.header("Resultado da Conciliação Consolidada")
    
    df_para_mostrar = df_final_formatado[
        (df_final_formatado[('Conta Movimento', 'Diferença')].abs() > 0.01) | 
        (df_final_formatado[('Aplicação Financeira', 'Diferença')].abs() > 0.01)
    ].copy()
    
    if df_para_mostrar.empty:
        st.success("Ótima notícia! Nenhuma divergência encontrada.")
    else:
        st.write("A tabela abaixo mostra apenas as contas com divergência de saldo.")
        formatters = {col: (lambda x: f'{x:,.2f}'.replace(",", "X").replace(".", ",").replace("X", ".")) for col in df_para_mostrar.columns}
        st.dataframe(df_para_mostrar.style.format(formatter=formatters).map(lambda x: 'color: red' if x < 0 else 'color: black', subset=[('Conta Movimento', 'Diferença'), ('Aplicação Financeira', 'Diferença')]))

    st.header("Download do Relatório Completo")
    st.write("Os arquivos para download contêm todas as contas, incluindo as que não apresentaram divergência.")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button("Baixar em CSV", df_final_formatado.to_csv(index=True, sep=';', decimal=',').encode('utf-8-sig'), 'relatorio_consolidado.csv', 'text/csv')
    with col2:
        st.download_button("Baixar em Excel", to_excel(df_final_formatado), 'relatorio_consolidado.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    with col3:
        st.download_button("Baixar em PDF", create_pdf(df_final_formatado), 'relatorio_consolidado.pdf', 'application/pdf')
