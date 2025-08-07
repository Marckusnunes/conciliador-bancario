import streamlit as st
import pandas as pd
import re
import io
import numpy as np
from fpdf import FPDF
from datetime import datetime

# --- Bloco 1: Lógica Principal da Conciliação ---
def realizar_conciliacao(contabilidade_file, extrato_file):
    # --- Processamento dos Arquivos Excel ---
    df_contabil = pd.read_excel(contabilidade_file, engine='openpyxl')
    df_extrato = pd.read_excel(extrato_file, engine='openpyxl', sheet_name='Table 1')

    df_contabil.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Contabil', 'Saldo_Cta_Invest_Contabil', 'Saldo_Aplicado_Contabil']
    df_extrato.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato']

    for df in [df_contabil, df_extrato]:
        for col in df.columns:
            if 'Saldo' in col:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    def extrair_chave(texto_conta):
        try: return int(re.sub(r'\D', '', str(texto_conta)))
        except (ValueError, IndexError): return None
            
    df_contabil['Conta_Chave'] = df_contabil['Conta'].apply(extrair_chave)
    df_extrato['Conta_Chave'] = df_extrato['Conta'].apply(extrair_chave)
    
    for df in [df_contabil, df_extrato]:
        df.dropna(subset=['Conta_Chave'], inplace=True)
        df['Conta_Chave'] = df['Conta_Chave'].astype(int)

    df_contabil_pivot = df_contabil.groupby('Conta_Chave').agg({'Titular': 'first','Saldo_Corrente_Contabil': 'sum','Saldo_Aplicado_Contabil': 'sum'}).reset_index()
    df_extrato_pivot = df_extrato.groupby('Conta_Chave')[['Saldo_Corrente_Extrato', 'Saldo_Aplicado_Extrato']].sum().reset_index()

    df_final = pd.merge(df_contabil_pivot, df_extrato_pivot, on='Conta_Chave', how='outer')
    df_final.fillna(0, inplace=True)
    df_final.rename(columns={'Titular': 'Domicilio_Bancario'}, inplace=True)
    df_final['Domicilio_Bancario'].fillna('Conta sem descrição no arquivo contábil', inplace=True)

    df_final['Diferenca_Movimento'] = df_final['Saldo_Corrente_Contabil'] - df_final['Saldo_Corrente_Extrato']
    df_final['Diferenca_Aplicacao'] = df_final['Saldo_Aplicado_Contabil'] - df_final['Saldo_Aplicado_Extrato']
    
    # MUDANÇA: A função agora retorna a tabela "plana", antes da formatação final.
    df_final = df_final[[
        'Domicilio_Bancario',
        'Saldo_Corrente_Contabil', 'Saldo_Corrente_Extrato', 'Diferenca_Movimento',
        'Saldo_Aplicado_Contabil', 'Saldo_Aplicado_Extrato', 'Diferenca_Aplicacao'
    ]]
    
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
contabilidade = st.sidebar.file_uploader("Selecione o Relatório Contábil (XLSX)", type=['xlsx', 'xls'])
extrato = st.sidebar.file_uploader("Selecione o Extrato Consolidado (XLSX)", type=['xlsx', 'xls'])

st.sidebar.header("2. Processar")
if contabilidade and extrato:
    if st.sidebar.button("Conciliar Agora"):
        with st.spinner("Processando..."):
            try:
                df_resultado = realizar_conciliacao(contabilidade, extrato)
                st.success("Conciliação Concluída com Sucesso!")
                st.session_state['df_resultado'] = df_resultado
            except Exception as e:
                st.error(f"Ocorreu um erro durante o processamento: {e}")
else:
    st.sidebar.warning("Por favor, carregue os dois arquivos Excel.")

if 'df_resultado' in st.session_state:
    df_plano = st.session_state['df_resultado']
    
    if df_plano is not None and not df_plano.empty:
        # MUDANÇA: A formatação de colunas agrupadas é aplicada aqui, no momento da exibição.
        df_formatado = df_plano.set_index('Domicilio_Bancario')
        df_formatado.columns = pd.MultiIndex.from_tuples([
            ('Conta Movimento', 'Saldo Contábil'), ('Conta Movimento', 'Saldo Extrato'), ('Conta Movimento', 'Diferença'),
            ('Aplicação Financeira', 'Saldo Contábil'), ('Aplicação Financeira', 'Saldo Extrato'), ('Aplicação Financeira', 'Diferença')
        ], names=['Grupo', 'Item'])
        
        st.header("Resultado da Conciliação Consolidada")
        df_para_mostrar = df_formatado[
            (df_formatado[('Conta Movimento', 'Diferença')].abs() > 0.01) | 
            (df_formatado[('Aplicação Financeira', 'Diferença')].abs() > 0.01)
        ].copy()
        
        if df_para_mostrar.empty:
            st.success("Ótima notícia! Nenhuma divergência encontrada.")
        else:
            st.write("A tabela abaixo mostra apenas as contas com divergência de saldo.")
            formatters = {col: (lambda x: f'{x:,.2f}'.replace(",", "X").replace(".", ",").replace("X", ".")) for col in df_para_mostrar.columns}
            
            # Ordem correta: .map() primeiro, .format() depois
            st.dataframe(df_para_mostrar.style
                .map(lambda x: 'color: red' if x < 0 else None, subset=[('Conta Movimento', 'Diferença'), ('Aplicação Financeira', 'Diferença')])
                .format(formatter=formatters)
            )

        st.header("Download do Relatório Completo")
        st.write("Os arquivos para download contêm todas as contas, incluindo as que não apresentaram divergência.")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button("Baixar em CSV", df_formatado.to_csv(index=True, sep=';', decimal=',').encode('utf-8-sig'), 'relatorio_consolidado.csv', 'text/csv')
        with col2:
            st.download_button("Baixar em Excel", to_excel(df_formatado), 'relatorio_consolidado.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        with col3:
            st.download_button("Baixar em PDF", create_pdf(df_formatado), 'relatorio_consolidado.pdf', 'application/pdf')