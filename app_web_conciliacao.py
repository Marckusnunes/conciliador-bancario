import streamlit as st
import pandas as pd
import re
import io
from fpdf import FPDF
from datetime import datetime

# --- Bloco 1: Lógica Principal da Conciliação (sem alterações) ---
def realizar_conciliacao(arquivo_relatorio, lista_extratos):
    # Etapa de limpeza automática do relatório
    df_report = pd.read_csv(arquivo_relatorio, sep=';', encoding='latin-1')
    if "Unidade Gestora" in df_report.columns[0]:
        df_report.columns = ["Unidade_Gestora", "Domicilio_Bancario", "Conta_Contabil", "Conta_Corrente", "Saldo_Inicial", "Debito", "Credito", "Saldo_Final"]
        if "Unidade Gestora" in df_report.iloc[0].to_string():
            df_report = df_report.drop(df_report.index[0])
    
    colunas_numericas_report = ["Saldo_Inicial", "Debito", "Credito", "Saldo_Final"]
    for col in colunas_numericas_report:
        if col in df_report.columns: # Adicionada verificação se a coluna existe
            df_report[col] = df_report[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df_report[col] = pd.to_numeric(df_report[col], errors='coerce')
    
    # Lógica de extração de chave e processamento
    def extrair_conta_chave(texto_conta):
        match = re.search(r'\d{7,}', str(texto_conta))
        return int(match.group(0)) if match else None

    df_report['Conta_Chave'] = df_report['Conta_Corrente'].apply(extrair_conta_chave)
    df_report = df_report[['Conta_Chave', 'Conta_Corrente', 'Saldo_Final']].dropna(subset=['Conta_Chave'])
    df_report['Conta_Chave'] = df_report['Conta_Chave'].astype(int)

    # Lógica dos extratos bancários
    lista_df_extratos = []
    for extrato_file in lista_extratos:
        df = pd.read_csv(extrato_file, sep=';', encoding='latin-1', decimal=',')
        lista_df_extratos.append(df)
    df_statement = pd.concat(lista_df_extratos, ignore_index=True)
    colunas_saldo_extrato = ['SALDO_ANTERIOR_TOTAL', 'SALDO_ATUAL_TOTAL', 'VALOR']
    for col in colunas_saldo_extrato:
        if col in df_statement.columns:
            df_statement[col] = df_statement[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df_statement[col] = pd.to_numeric(df_statement[col], errors='coerce')
    df_statement['DT_LANCAMENTO'] = pd.to_datetime(df_statement['DT_LANCAMENTO'], format='%d/%m/%Y', errors='coerce')
    df_statement = df_statement.sort_values(by=['CONTA', 'DT_LANCAMENTO'])
    df_final_balances = df_statement.drop_duplicates(subset=['CONTA'], keep='last')
    df_final_balances = df_final_balances[['CONTA', 'SALDO_ATUAL_TOTAL']]
    df_final_balances.rename(columns={'CONTA': 'Conta_Chave', 'SALDO_ATUAL_TOTAL': 'Saldo_Extrato'}, inplace=True)

    # Lógica da conciliação
    df_reconciliation = pd.merge(df_report, df_final_balances, on='Conta_Chave', how='left')
    df_reconciliation['Saldo_Extrato'].fillna(0, inplace=True)
    df_reconciliation['Diferenca'] = df_reconciliation['Saldo_Final'] - df_reconciliation['Saldo_Extrato']
    for col in ['Saldo_Final', 'Saldo_Extrato', 'Diferenca']:
        df_reconciliation[col] = df_reconciliation[col].round(2)
    df_reconciliation = df_reconciliation[['Conta_Corrente', 'Saldo_Final', 'Saldo_Extrato', 'Diferenca']]
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
        self.cell(0, 10, 'Relatório de Conciliação Bancária', 0, 1, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, title):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, title, 0, 1, 'L')
        self.ln(5)

    def create_table(self, data):
        self.set_font('Arial', 'B', 8)
        col_widths = [65, 30, 30, 30] 
        headers = list(data.columns)
        for i, header in enumerate(headers):
            self.cell(col_widths[i], 10, header, 1)
        self.ln()
        
        self.set_font('Arial', '', 8)
        for index, row in data.iterrows():
            for i, item in enumerate(row):
                self.cell(col_widths[i], 10, str(item), 1)
            self.ln()

def create_pdf(df):
    pdf = PDF('P', 'mm', 'A4')
    pdf.add_page()
    pdf.chapter_title(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    pdf.create_table(df)
    # LINHA CORRIGIDA: Removemos o .encode('latin-1') que causava o erro.
    return pdf.output()

# --- Bloco 3: Interface Web com Streamlit ---
st.set_page_config(page_title="Conciliador Bancário", layout="wide")
st.title("Ferramenta de Conciliação Bancária")
st.write("Uma aplicação para comparar o relatório contábil com os extratos bancários.")

st.sidebar.header("1. Carregar Arquivos")
arquivo_relatorio_carregado = st.sidebar.file_uploader("Selecione o Relatório Contábil (CSV Original)", type=['csv'])
lista_extratos_carregados = st.sidebar.file_uploader("Selecione os Extratos Bancários (CSV)", type=['csv'], accept_multiple_files=True)

st.sidebar.header("2. Processar")
if arquivo_relatorio_carregado and lista_extratos_carregados:
    if st.sidebar.button("Conciliar Agora"):
        with st.spinner("Processando..."):
            try:
                df_resultado = realizar_conciliacao(arquivo_relatorio_carregado, lista_extratos_carregados)
                st.success("Conciliação Concluída com Sucesso!")
                st.header("Resultado da Conciliação")
                st.dataframe(df_resultado)
                st.session_state['df_resultado'] = df_resultado
            except Exception as e:
                st.error(f"Ocorreu um erro durante o processamento: {e}")
else:
    st.sidebar.warning("Por favor, carregue o relatório e pelo menos um extrato.")

if 'df_resultado' in st.session_state:
    st.header("Download do Relatório")
    df_final = st.session_state['df_resultado']
    
    col1, col2, col3 = st.columns(3)

    with col1:
        st.download_button(
           label="Baixar em CSV",
           data=df_final.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig'),
           file_name='relatorio_conciliacao.csv',
           mime='text/csv',
        )
    with col2:
        st.download_button(
           label="Baixar em Excel",
           data=to_excel(df_final),
           file_name='relatorio_conciliacao.xlsx',
           mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
    with col3:
        st.download_button(
           label="Baixar em PDF",
           data=create_pdf(df_final),
           file_name='relatorio_conciliacao.pdf',
           mime='application/pdf',
        )