import streamlit as st
import pandas as pd
import re
import io
import numpy as np
from fpdf import FPDF
from datetime import datetime
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

# --- Bloco 1: Funções de Processamento ---

def processar_relatorio_contabil(arquivo_carregado):
    """Lê e prepara o arquivo da contabilidade."""
    df = pd.read_excel(arquivo_carregado, engine='openpyxl')
    df.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Contabil', 'Saldo_Cta_Invest_Contabil', 'Saldo_Aplicado_Contabil']
    for col in ['Saldo_Corrente_Contabil', 'Saldo_Aplicado_Contabil']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df

def processar_extrato_bb(caminho_arquivo):
    """Lê e prepara o extrato do Banco do Brasil."""
    df = pd.read_excel(caminho_arquivo, engine='openpyxl', sheet_name='Table 1')
    if len(df.columns) == 7:
        df.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato', 'Vazio']
        df = df.drop(columns=['Vazio'])
    else:
        df.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato']
    for col in df.columns:
        if 'Saldo' in col:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df

def processar_extrato_cef(caminho_arquivo):
    """Nova função que lê e prepara o extrato da Caixa, pulando os cabeçalhos."""
    df = pd.read_excel(caminho_arquivo, engine='openpyxl', skiprows=13)
    df.columns = ['Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato', 'Saldo_Total']
    for col in ['Saldo_Corrente_Extrato', 'Saldo_Aplicado_Extrato']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    # Adiciona a coluna Agência que pode não estar presente no corpo da tabela da CEF
    if 'Agencia' not in df.columns:
        df['Agencia'] = '4064' # Valor padrão para CEF conforme arquivo
    return df

def realizar_conciliacao(df_contabil, df_extrato_unificado):
    """Recebe os DataFrames limpos e realiza a conciliação."""
    def extrair_chave(texto_conta):
        try: return int(re.sub(r'\D', '', str(texto_conta)))
        except (ValueError, IndexError): return None
            
    df_contabil['Conta_Chave'] = df_contabil['Conta'].apply(extrair_chave)
    df_extrato_unificado['Conta_Chave'] = df_extrato_unificado['Conta'].apply(extrair_chave)
    
    for df in [df_contabil, df_extrato_unificado]:
        df.dropna(subset=['Conta_Chave', 'Conta'], inplace=True)
        df['Conta_Chave'] = df['Conta_Chave'].astype(int)

    df_contabil_pivot = df_contabil.groupby('Conta_Chave').agg({'Conta': 'first','Saldo_Corrente_Contabil': 'sum','Saldo_Aplicado_Contabil': 'sum'}).reset_index()
    df_extrato_pivot = df_extrato_unificado.groupby('Conta_Chave')[['Saldo_Corrente_Extrato', 'Saldo_Aplicado_Extrato']].sum().reset_index()

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
        self.set_font('Arial', 'B', 12); self.cell(0, 8, 'Prefeitura da Cidade do Rio de Janeiro', 0, 1, 'C'); self.set_font('Arial', '', 11); self.cell(0, 8, 'Controladoria Geral do Município', 0, 1, 'C'); self.set_font('Arial', 'B', 10); self.cell(0, 8, 'Relatório de Conciliação de Saldos Bancários', 0, 1, 'C'); self.ln(5)
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
st.set_page_config(page_title="Conciliação Bancária", layout="wide", page_icon="🏦")
st.title("🏦 Prefeitura da Cidade do Rio de Janeiro")
st.header("Controladoria Geral do Município")
st.markdown("---")
st.subheader("Conciliação de Saldos Bancários e Contábeis")

meses = {1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho", 7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"}
ano_atual = datetime.now().year
opcoes_meses_formatadas = [f"{nome.capitalize()} {ano}" for ano in range(ano_atual, ano_atual + 2) for mes, nome in meses.items()]
try:
    index_padrao = opcoes_meses_formatadas.index(f"{meses[datetime.now().month].capitalize()} {ano_atual}")
except ValueError:
    index_padrao = 0

st.selectbox("Selecione o Mês da Conciliação:", options=opcoes_meses_formatadas, index=index_padrao, key='mes_selecionado')

st.sidebar.header("Carregar Relatório Contábil")
contabilidade = st.sidebar.file_uploader(f"Selecione o seu Relatório Contábil de {st.session_state.mes_selecionado}", type=['xlsx', 'xls'])

if st.sidebar.button("Conciliar Agora"):
    if contabilidade is not None:
        with st.spinner("Processando..."):
            try:
                partes_mes = st.session_state.mes_selecionado.lower().split()
                mes_ano = f"{partes_mes[0]}_{partes_mes[1]}"
                
                extratos_encontrados = []
                # Tenta carregar extrato do BB
                try:
                    caminho_bb = f"extratos_consolidados/extrato_bb_{mes_ano}.xlsx"
                    df_bb = processar_extrato_bb(caminho_bb)
                    extratos_encontrados.append(df_bb)
                    st.info(f"Extrato do Banco do Brasil para {st.session_state.mes_selecionado} carregado com sucesso.")
                except FileNotFoundError:
                    st.warning(f"Aviso: Extrato do Banco do Brasil para {st.session_state.mes_selecionado} não encontrado.")
                
                # Tenta carregar extrato da CEF
                try:
                    caminho_cef = f"extratos_consolidados/extrato_cef_{mes_ano}.xlsx"
                    df_cef = processar_extrato_cef(caminho_cef)
                    extratos_encontrados.append(df_cef)
                    st.info(f"Extrato da Caixa Econômica para {st.session_state.mes_selecionado} carregado com sucesso.")
                except FileNotFoundError:
                    st.warning(f"Aviso: Extrato da Caixa Econômica para {st.session_state.mes_selecionado} não encontrado.")

                if not extratos_encontrados:
                    st.error("Nenhum arquivo de extrato foi encontrado para o mês selecionado. Peça ao administrador para carregá-los.")
                    st.session_state['df_resultado'] = None
                else:
                    df_extrato_unificado = pd.concat(extratos_encontrados, ignore_index=True)
                    df_contabil_limpo = processar_relatorio_contabil(contabilidade)
                    df_resultado_final = realizar_conciliacao(df_contabil_limpo, df_extrato_unificado)
                    st.success("Conciliação Concluída com Sucesso!")
                    st.session_state['df_resultado'] = df_resultado_final
                    
            except Exception as e:
                st.error(f"Ocorreu um erro durante o processamento: {e}")
    else:
        st.sidebar.warning("Por favor, carregue o seu arquivo de relatório contábil.")

if 'df_resultado' in st.session_state:
    df_final_formatado = st.session_state['df_resultado']
    if df_final_formatado is not None and not df_final_formatado.empty:
        st.markdown("---")
        st.header(f"Resultado da Conciliação de {st.session_state.mes_selecionado}")
        df_para_mostrar = df_final_formatado[
            (df_final_formatado[('Conta Movimento', 'Diferença')].abs() > 0.01) | 
            (df_final_formatado[('Aplicação Financeira', 'Diferença')].abs() > 0.01)
        ].copy()
        if df_para_mostrar.empty:
            st.success("✅ Ótima notícia! Nenhuma divergência encontrada.")
        else:
            st.write("A tabela abaixo mostra apenas as contas com divergência de saldo.")
            formatters = {col: (lambda x: f'{x:,.2f}'.replace(",", "X").replace(".", ",").replace("X", ".")) for col in df_para_mostrar.columns}
            st.dataframe(df_para_mostrar.style.format(formatter=formatters))
        st.markdown("---")
        st.header("Download do Relatório Completo")
        st.write("Os arquivos para download contêm todas as contas que foram encontradas em ambos os arquivos.")
        col1, col2, col3 = st.columns(3)
        with col1:
            df_csv = df_final_formatado.copy(); df_csv.columns = [' - '.join(col).strip() for col in df_csv.columns.values]; st.download_button("Baixar em CSV", df_csv.to_csv(index=True, sep=';', decimal=',').encode('utf-8-sig'), 'relatorio_consolidado.csv', 'text/csv')
        with col2:
            st.download_button("Baixar em Excel", to_excel(df_final_formatado), 'relatorio_consolidado.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        with col3:
            st.download_button("Baixar em PDF", create_pdf(df_final_formatado), 'relatorio_consolidado.pdf', 'application/pdf')
    elif df_final_formatado is not None:
         st.info("Processamento concluído. Nenhuma conta correspondente foi encontrada entre os arquivos.")