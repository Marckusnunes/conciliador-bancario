import streamlit as st
import pandas as pd
import re
import io
import numpy as np
from fpdf import FPDF
from datetime import datetime

# --- Bloco 1: Lógica Principal da Conciliação ---

def ler_e_preparar_contabil(arquivo_carregado):
    """
    Função universal que lê o arquivo contábil, detecta seu formato (bruto com 8 colunas
    ou ajustado com 5/6 colunas) e o transforma no formato limpo e padronizado.
    """
    df = pd.DataFrame()
    nome_arquivo = arquivo_carregado.name
    arquivo_carregado.seek(0)

    try:
        if nome_arquivo.endswith('.xlsx') or nome_arquivo.endswith('.xls'):
            df = pd.read_excel(arquivo_carregado, engine='openpyxl')
        elif nome_arquivo.endswith('.csv'):
            # Tenta ler com diferentes separadores
            df = pd.read_csv(arquivo_carregado, sep=';', encoding='latin-1', on_bad_lines='skip')
            if len(df.columns) <= 1:
                arquivo_carregado.seek(0)
                df = pd.read_csv(arquivo_carregado, sep=',', encoding='latin-1', on_bad_lines='skip')
    except Exception as e:
        st.error(f"Não foi possível ler o arquivo contábil: {e}")
        return pd.DataFrame()

    if df.empty: return pd.DataFrame()

    # Verifica o número de colunas para decidir o que fazer
    if len(df.columns) >= 8:
        st.info("Detectado arquivo contábil bruto (8 colunas). Aplicando transformação...")
        df = df.iloc[:,:8]
        df.columns = [
            'Unidade Gestora', 'Domicílio bancário', 'Conta contábil', 'Conta Corrente',
            'Saldo Inicial', 'No Mês', 'No Mês.1', 'Saldo Final'
        ]
        df.dropna(subset=['Domicílio bancário'], inplace=True)
        df = df[~df['Conta contábil'].str.contains('Total por', na=False)].copy()
        df['Saldo Final'] = pd.to_numeric(
            df['Saldo Final'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False),
            errors='coerce'
        ).fillna(0)

        df_pivot = df.pivot_table(
            index='Domicílio bancário', columns='Conta contábil', values='Saldo Final', aggfunc='sum'
        ).reset_index()

        rename_dict = {
            '111111901 - BANCOS CONTA MOVIMENTO - DEMAIS CONTAS': 'Saldo Corrente',
            '111115001 - APLICAÇÕES FINANCEIRAS DE LIQUIDEZ IMEDIATA': 'Saldo Aplicado'
        }
        df_pivot.rename(columns=lambda c: rename_dict.get(c.strip(), c), inplace=True)

        def formatar_numero_conta(texto_conta):
            if not isinstance(texto_conta, str): return ""
            try:
                num_sem_zeros = texto_conta.lstrip('0')
                if not num_sem_zeros: return "0"
                principal, verificador = num_sem_zeros[:-1], num_sem_zeros[-1]
                return f"{int(principal):,}".replace(',', '.') + f"-{verificador}"
            except: return texto_conta

        partes_domicilio = df_pivot['Domicílio bancário'].str.split(' - ', expand=True)
        df_final = pd.DataFrame()
        df_final['Agencia'] = partes_domicilio.get(1)
        df_final['Conta'] = partes_domicilio.get(2).apply(formatar_numero_conta)
        df_final['Titular'] = partes_domicilio.get(3)
        df_final['Saldo_Corrente_Contabil'] = df_pivot.get('Saldo Corrente')
        df_final['Saldo_Aplicado_Contabil'] = df_pivot.get('Saldo Aplicado')
        df_final.fillna(0, inplace=True)
        return df_final

    elif len(df.columns) >= 5:
        st.info("Detectado arquivo contábil ajustado (5/6 colunas).")
        df = df.iloc[:,:6]
        df.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Contabil', 'Saldo_Cta_Invest_Contabil', 'Saldo_Aplicado_Contabil']
        for col in ['Saldo_Corrente_Contabil', 'Saldo_Aplicado_Contabil']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        return df
    
    else:
        st.error("Formato do arquivo contábil não reconhecido.")
        return pd.DataFrame()

def realizar_conciliacao(df_contabil_limpo, extrato_file):
    df_extrato = pd.read_excel(extrato_file, engine='openpyxl', sheet_name='Table 1')
    df_extrato.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato']
    for col in df_extrato.columns:
        if 'Saldo' in col:
            df_extrato[col] = pd.to_numeric(df_extrato[col], errors='coerce').fillna(0)

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

    df_final = pd.merge(df_contabil_pivot, df_extrato_pivot, on='Conta_Chave', how='inner')
    if df_final.empty: return pd.DataFrame()
        
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
        self.set_font('Arial', 'B', 10); self.cell(0, 10, 'Relatório de Conciliação Consolidado por Conta', 0, 1, 'C'); self.ln(5)
    def footer(self):
        self.set_y(-15); self.set_font('Arial', 'I', 8); self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')
    def create_table(self, data):
        self.set_font('Arial', '', 7); line_height = self.font_size * 2.5; col_width = 30 
        self.set_font('Arial', 'B', 8)
        index_name = data.index.name if data.index.name else 'ID'
        self.cell(40, line_height, index_name, 1, 0, 'C'); self.cell(col_width * 3, line_height, 'Conta Movimento', 1, 0, 'C'); self.cell(col_width * 3, line_height, 'Aplicação Financeira', 1, 0, 'C'); self.ln(line_height)
        self.set_font('Arial', 'B', 7)
        self.cell(40, line_height, '', 1, 0, 'C')
        sub_headers = ['Saldo Contábil', 'Saldo Extrato', 'Diferença']
        for _ in range(2):
            for sub_header in sub_headers: self.cell(col_width, line_height, sub_header, 1, 0, 'C')
        self.ln(line_height)
        self.set_font('Arial', '', 6)
        formatted_data = data.copy()
        for col_tuple in formatted_data.columns:
             formatted_data[col_tuple] = formatted_data[col_tuple].apply(lambda x: f'{x:,.2f}'.replace(",", "X").replace(".", ",").replace("X", "."))
        for index, row in formatted_data.iterrows():
            display_index = str(index); self.cell(40, line_height, display_index, 1, 0, 'L')
            for item in row: self.cell(col_width, line_height, str(item), 1, 0, 'R')
            self.ln(line_height)

def create_pdf(df):
    pdf = PDF('L', 'mm', 'A4'); pdf.add_page(); pdf.create_table(df); return bytes(pdf.output())

# --- Bloco 3: Interface Web com Streamlit ---
st.set_page_config(page_title="Conciliação Bancária", layout="wide")
st.title("Ferramenta de Conciliação de Saldos Bancários")

st.sidebar.header("1. Carregar Arquivos")
contabilidade_bruto = st.sidebar.file_uploader("Selecione o Relatório Contábil (CSV ou XLSX)", type=['csv', 'xlsx', 'xls'])
extrato = st.sidebar.file_uploader("Selecione o Extrato Consolidado (XLSX)", type=['xlsx', 'xls'])

st.sidebar.header("2. Processar")
if contabilidade_bruto and extrato:
    if st.sidebar.button("Conciliar Agora"):
        with st.spinner("Processando..."):
            try:
                df_contabil_processado = ler_e_preparar_contabil(contabilidade_bruto)
                if not df_contabil_processado.empty:
                    df_resultado_final = realizar_conciliacao(df_contabil_processado, extrato)
                    st.success("Conciliação Concluída com Sucesso!")
                    st.session_state['df_resultado'] = df_resultado_final
            except Exception as e:
                st.error(f"Ocorreu um erro durante o processamento: {e}")
                st.session_state['df_resultado'] = None
else:
    st.sidebar.warning("Por favor, carregue os dois arquivos.")

if 'df_resultado' in st.session_state:
    resultado = st.session_state['df_resultado']
    if isinstance(resultado, pd.DataFrame):
        if resultado.empty:
            st.info("Processamento concluído. Nenhuma conta correspondente foi encontrada entre os dois arquivos para gerar um relatório.")
        else:
            st.header("Resultado da Conciliação Consolidada")
            df_para_mostrar = resultado[
                (resultado[('Conta Movimento', 'Diferença')].abs() > 0.01) | 
                (resultado[('Aplicação Financeira', 'Diferença')].abs() > 0.01)
            ].copy()
            
            if df_para_mostrar.empty:
                st.success("Ótima notícia! Nenhuma divergência encontrada.")
            else:
                st.write("A tabela abaixo mostra apenas as contas com divergência de saldo.")
                formatters = {col: (lambda x: f'{x:,.2f}'.replace(",", "X").replace(".", ",").replace("X", ".")) for col in df_para_mostrar.columns}
                st.dataframe(df_para_mostrar.style.format(formatter=formatters))

            st.header("Download do Relatório Completo")
            col1, col2, col3 = st.columns(3)
            with col1:
                df_csv = resultado.copy()
                df_csv.columns = [' - '.join(col).strip() for col in df_csv.columns.values]
                st.download_button("Baixar em CSV", df_csv.to_csv(index=True, sep=';', decimal=',').encode('utf-8-sig'), 'relatorio_consolidado.csv', 'text/csv')
            with col2:
                st.download_button("Baixar em Excel", to_excel(resultado), 'relatorio_consolidado.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            with col3:
                st.download_button("Baixar em PDF", create_pdf(resultado), 'relatorio_consolidado.pdf', 'application/pdf')