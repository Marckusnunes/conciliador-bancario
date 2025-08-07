import streamlit as st
import pandas as pd
import re
import io
import numpy as np
from fpdf import FPDF
from datetime import datetime

# --- Bloco 1: Lógica Principal da Conciliação ---

def processar_relatorio_bruto(arquivo_bruto_contabil):
    """
    Esta função contém a sua lógica para transformar o relatório contábil bruto
    no formato limpo e consolidado, pronto para a conciliação.
    MUDANÇA: Agora lê o arquivo como Excel.
    """
    # Lê o arquivo como Excel, não mais como CSV
    df = pd.read_excel(arquivo_bruto_contabil, engine='openpyxl')
    
    # Atribui nomes de coluna consistentes
    df.columns = [
        'Unidade Gestora', 'Domicílio bancário', 'Conta contábil', 'Conta Corrente',
        'Saldo Inicial', 'No Mês', 'No Mês.1', 'Saldo Final'
    ]

    df.dropna(subset=['Domicílio bancário'], inplace=True)
    df = df[df['Conta contábil'] != 'Total por Domicílio Bancário'].copy()
    
    df['Saldo Final'] = pd.to_numeric(
        df['Saldo Final'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False),
        errors='coerce'
    ).fillna(0)

    df_pivot = df.pivot_table(
        index='Domicílio bancário',
        columns='Conta contábil',
        values='Saldo Final',
        aggfunc='sum'
    ).reset_index()

    df_pivot.rename(columns={
        '111111901 - BANCOS CONTA MOVIMENTO - DEMAIS CONTAS': 'Saldo Corrente',
        '111115001 - APLICAÇÕES FINANCEIRAS DE LIQUIDEZ IMEDIATA': 'Saldo Aplicado'
    }, inplace=True)

    def formatar_numero_conta(texto_conta):
        if not isinstance(texto_conta, str): return ""
        try:
            num_sem_zeros = texto_conta.lstrip('0')
            if not num_sem_zeros: return "0"
            principal = num_sem_zeros[:-1]
            verificador = num_sem_zeros[-1]
            principal_formatado = f"{int(principal):,}".replace(',', '.')
            return f"{principal_formatado}-{verificador}"
        except (ValueError, TypeError, IndexError): return texto_conta

    partes_domicilio = df_pivot['Domicílio bancário'].str.split(' - ', expand=True)
    
    df_final = pd.DataFrame()
    df_final['Agencia'] = partes_domicilio.get(1)
    df_final['Conta'] = partes_domicilio.get(2).apply(formatar_numero_conta)
    df_final['Titular'] = partes_domicilio.get(3)
    df_final['Saldo Corrente'] = df_pivot.get('Saldo Corrente')
    df_final['Saldo Cta Invest'] = np.nan
    df_final['Saldo Aplicado'] = df_pivot.get('Saldo Aplicado')
    df_final.fillna(0, inplace=True)
    
    return df_final

def realizar_conciliacao(df_contabil_limpo, extrato_file):
    df_extrato = pd.read_excel(extrato_file, engine='openpyxl', sheet_name='Table 1')
    
    df_contabil_limpo.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Contabil', 'Saldo_Cta_Invest_Contabil', 'Saldo_Aplicado_Contabil']
    df_extrato.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato']

    for df in [df_contabil_limpo, df_extrato]:
        for col in df.columns:
            if 'Saldo' in col:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    def extrair_chave(texto_conta):
        try: return int(re.sub(r'\D', '', str(texto_conta)))
        except (ValueError, IndexError): return None
            
    df_contabil_limpo['Conta_Chave'] = df_contabil_limpo['Conta'].apply(extrair_chave)
    df_extrato['Conta_Chave'] = df_extrato['Conta'].apply(extrair_chave)
    
    for df in [df_contabil_limpo, df_extrato]:
        df.dropna(subset=['Conta_Chave', 'Conta'], inplace=True)
        df['Conta_Chave'] = df['Conta_Chave'].astype(int)

    df_contabil_pivot = df_contabil_limpo.groupby('Conta_Chave').agg({'Conta': 'first','Saldo_Corrente_Contabil': 'sum','Saldo_Aplicado_Contabil': 'sum'}).reset_index()
    df_extrato_pivot = df_extrato.groupby('Conta_Chave')[['Saldo_Corrente_Extrato', 'Saldo_Aplicado_Extrato']].sum().reset_index()

    df_final = pd.merge(df_contabil_pivot, df_extrato_pivot, on='Conta_Chave', how='outer')
    df_final.fillna(0, inplace=True)
    df_final.rename(columns={'Conta': 'Conta Bancária'}, inplace=True)
    
    df_final['Diferenca_Movimento'] = df_final['Saldo_Corrente_Contabil'] - df_final['Saldo_Corrente_Extrato']
    df_final['Diferenca_Aplicacao'] = df_final['Saldo_Aplicado_Contabil'] - df_final['Saldo_Aplicado_Extrato']
    
    df_final = df_final.set_index('Conta Bancária')
    df_final = df_final[['Saldo_Corrente_Contabil', 'Saldo_Corrente_Extrato', 'Diferenca_Movimento','Saldo_Aplicado_Contabil', 'Saldo_Aplicado_Extrato', 'Diferenca_Aplicacao']]
    
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
        self.cell(40, line_height, index_name, 1, 0, 'C')
        self.cell(col_width * 3, line_height, 'Conta Movimento', 1, 0, 'C')
        self.cell(col_width * 3, line_height, 'Aplicação Financeira', 1, 0, 'C')
        self.ln(line_height)
        
        self.set_font('Arial', 'B', 7)
        self.cell(40, line_height, '', 1, 0, 'C')
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
            display_index = str(index)
            self.cell(40, line_height, display_index, 1, 0, 'L')
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
# MUDANÇA: O primeiro arquivo agora aceita Excel
contabilidade_bruto = st.sidebar.file_uploader("Selecione o Relatório Contábil Bruto (XLSX/XLS)", type=['xlsx', 'xls'])
extrato = st.sidebar.file_uploader("Selecione o Extrato Consolidado (XLSX)", type=['xlsx', 'xls'])

st.sidebar.header("2. Processar")
if contabilidade_bruto and extrato:
    if st.sidebar.button("Conciliar Agora"):
        with st.spinner("Processando..."):
            try:
                # Primeiro, processa o arquivo bruto para o formato limpo
                df_contabil_processado = processar_relatorio_bruto(contabilidade_bruto)
                
                # Depois, realiza a conciliação com o resultado
                df_resultado_final = realizar_conciliacao(df_contabil_processado, extrato)

                st.success("Conciliação Concluída com Sucesso!")
                st.session_state['df_resultado'] = df_resultado_final
            except Exception as e:
                st.error(f"Ocorreu um erro durante o processamento: {e}")
else:
    st.sidebar.warning("Por favor, carregue o relatório bruto e o extrato consolidado.")

if 'df_resultado' in st.session_state:
    df_final_formatado = st.session_state['df_resultado']
    
    if df_final_formatado is not None and not df_final_formatado.empty:
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
            st.dataframe(df_para_mostrar.style.format(formatter=formatters))

        st.header("Download do Relatório Completo")
        st.write("Os arquivos para download contêm todas as contas que foram encontradas em ambos os arquivos.")
        col1, col2, col3 = st.columns(3)
        with col1:
            df_csv = df_final_formatado.copy()
            df_csv.columns = [' - '.join(col).strip() for col in df_csv.columns.values]
            st.download_button("Baixar em CSV", df_csv.to_csv(index=True, sep=';', decimal=',').encode('utf-8-sig'), 'relatorio_consolidado.csv', 'text/csv')
        with col2:
            st.download_button("Baixar em Excel", to_excel(df_final_formatado), 'relatorio_consolidado.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        with col3:
            st.download_button("Baixar em PDF", create_pdf(df_final_formatado), 'relatorio_consolidado.pdf', 'application/pdf')