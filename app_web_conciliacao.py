import streamlit as st
import pandas as pd
import re
import io
import numpy as np
from fpdf import FPDF
from datetime import datetime
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

# --- Bloco 1: Lógica Principal da Conciliação ---

def carregar_depara():
    """Carrega o arquivo DE-PARA do repositório."""
    try:
        df_depara = pd.read_excel("depara/DEPARA_CONTAS BANCÁRIAS_CEF.xlsx", sheet_name="2025_JUNHO (2)")
        df_depara.columns = ['Conta Antiga', 'Conta Nova']
        # Limpa as chaves para garantir a correspondência
        df_depara['Chave Antiga'] = df_depara['Conta Antiga'].astype(str).apply(lambda x: re.sub(r'\D', '', x).lstrip('0'))
        df_depara['Chave Nova'] = df_depara['Conta Nova'].astype(str).apply(lambda x: re.sub(r'\D', '', x).lstrip('0'))
        st.info("Arquivo DE-PARA carregado e processado com sucesso.")
        return df_depara[['Chave Antiga', 'Chave Nova']]
    except FileNotFoundError:
        st.warning("Aviso: Arquivo DE-PARA 'depara/DEPARA_CONTAS BANCÁRIAS_CEF.xlsx' não encontrado. A tradução de contas da CEF não será aplicada.")
        return pd.DataFrame()

def processar_relatorio_contabil(arquivo_carregado, df_depara):
    """Lê o relatório contabilístico bruto (CSV) e aplica a nova lógica de extração de chave."""
    st.info("A processar Relatório Contabilístico...")
    df = pd.read_csv(arquivo_carregado, encoding='latin-1', sep=';', header=1)
    
    def extrair_chave_contabil(texto_conta):
        if isinstance(texto_conta, str):
            numeric_part = re.sub(r'\D', '', texto_conta)
            if len(numeric_part) > 7:
                return numeric_part[7:].lstrip('0')
            return numeric_part.lstrip('0')
        return None
        
    df['Chave Primaria'] = df['Domicílio bancário'].apply(extrair_chave_contabil)
    df.dropna(subset=['Chave Primaria'], inplace=True)
    df = df[df['Chave Primaria'] != '']
    
    # --- Lógica DE-PARA aplicada aqui ---
    if not df_depara.empty:
        st.info("A aplicar tradução de contas DE-PARA...")
        df = pd.merge(df, df_depara, left_on='Chave Primaria', right_on='Chave Antiga', how='left')
        df['Chave Primaria Final'] = df['Chave Nova'].fillna(df['Chave Primaria'])
    else:
        df['Chave Primaria Final'] = df['Chave Primaria']

    df['Saldo Final'] = pd.to_numeric(
        df['Saldo Final'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False),
        errors='coerce'
    ).fillna(0)

    df_pivot = df.pivot_table(index='Chave Primaria Final', columns='Conta contábil', values='Saldo Final', aggfunc='sum').reset_index()
    
    rename_dict = {c: 'Saldo_Corrente_Contabil' for c in df_pivot.columns if '111111901' in c}
    rename_dict.update({c: 'Saldo_Aplicado_Contabil' for c in df_pivot.columns if '111115001' in c})
    df_pivot.rename(columns=rename_dict, inplace=True)

    mapa_conta = df[['Chave Primaria Final', 'Domicílio bancário']].drop_duplicates().set_index('Chave Primaria Final')
    df_final = df_pivot.join(mapa_conta, on='Chave Primaria Final')
    df_final.rename(columns={'Chave Primaria Final': 'Chave Primaria'}, inplace=True)
    
    return df_final

def processar_extrato_bb(caminho_arquivo):
    df = pd.read_excel(caminho_arquivo, engine='openpyxl', sheet_name='Table 1')
    df.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato']
    for col in df.columns:
        if 'Saldo' in col: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    df['Chave Primaria'] = df['Conta'].astype(str).apply(lambda x: re.sub(r'\D', '', x).lstrip('0'))
    return df

def processar_extrato_cef(caminho_arquivo):
    df = pd.read_excel(caminho_arquivo, engine='openpyxl', skiprows=13)
    df.columns = ['Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato', 'Saldo_Total']
    for col in ['Saldo_Corrente_Extrato', 'Saldo_Aplicado_Extrato']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    if 'Agencia' not in df.columns: df['Agencia'] = '4064'
    df['Chave Primaria'] = df['Conta'].astype(str).apply(lambda x: re.sub(r'\D', '', x).lstrip('0'))
    return df

def realizar_conciliacao(df_contabil, df_extrato_unificado):
    df_contabil_pivot = df_contabil[['Chave Primaria', 'Domicílio bancário', 'Saldo_Corrente_Contabil', 'Saldo_Aplicado_Contabil']]
    df_extrato_pivot = df_extrato_unificado.groupby('Chave Primaria').agg({
        'Saldo_Corrente_Extrato': 'sum', 'Saldo_Aplicado_Extrato': 'sum'
    }).reset_index()

    df_contabil_pivot['Chave Primaria'] = df_contabil_pivot['Chave Primaria'].astype(str)
    df_extrato_pivot['Chave Primaria'] = df_extrato_pivot['Chave Primaria'].astype(str)

    df_final = pd.merge(df_contabil_pivot, df_extrato_pivot, on='Chave Primaria', how='inner')
    if df_final.empty: return pd.DataFrame()
        
    df_final.rename(columns={'Domicílio bancário': 'Conta Bancária'}, inplace=True)
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
    output = io.BytesIO();
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=True, sheet_name='Conciliacao', startrow=1)
        workbook = writer.book; worksheet = writer.sheets['Conciliacao']
        font_header = Font(bold=True, color="FFFFFF"); align_header = Alignment(horizontal='center', vertical='center')
        fill_header = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
        border_thin = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        number_format_br = '#,##0.00'
        worksheet.merge_cells('B1:D1'); cell_movimento = worksheet['B1']; cell_movimento.value = 'Conta Movimento'
        cell_movimento.font = font_header; cell_movimento.alignment = align_header; cell_movimento.fill = fill_header
        worksheet.merge_cells('E1:G1'); cell_aplicacao = worksheet['E1']; cell_aplicacao.value = 'Aplicação Financeira'
        cell_aplicacao.font = font_header; cell_aplicacao.alignment = align_header; cell_aplicacao.fill = fill_header
        for row in worksheet['A2:G2']:
            for cell in row: cell.font = Font(bold=True); cell.alignment = Alignment(horizontal='center', vertical='center')
        for col_idx, col in enumerate(worksheet.columns, 1):
            max_length = 0; column_letter = get_column_letter(col_idx)
            for cell_idx, cell in enumerate(col, 0):
                if cell_idx > 0: cell.border = border_thin
                if cell_idx > 1:
                    if col_idx == 1: cell.alignment = Alignment(horizontal='left', vertical='center')
                    else: cell.number_format = number_format_br; cell.alignment = Alignment(horizontal='right', vertical='center')
                try:
                    if len(str(cell.value)) > max_length: max_length = len(str(cell.value))
                except: pass
            adjusted_width = (max_length + 2); worksheet.column_dimensions[column_letter].width = adjusted_width
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
contabilidade_bruto = st.sidebar.file_uploader(f"Selecione o seu Relatório Contábil Bruto de {st.session_state.mes_selecionado}", type=['csv'])

if st.sidebar.button("Conciliar Agora"):
    if contabilidade_bruto is not None:
        with st.spinner("Processando..."):
            try:
                partes_mes = st.session_state.mes_selecionado.lower().split()
                mes_ano = f"{partes_mes[0]}_{partes_mes[1]}"
                
                df_depara = carregar_depara()

                extratos_encontrados = []
                try:
                    caminho_bb = f"extratos_consolidados/extrato_bb_{mes_ano}.xlsx"
                    df_bb = processar_extrato_bb(caminho_bb)
                    extratos_encontrados.append(df_bb)
                    st.info(f"Extrato do Banco do Brasil para {st.session_state.mes_selecionado} carregado.")
                except FileNotFoundError:
                    st.warning(f"Aviso: Extrato do BB para {st.session_state.mes_selecionado} não encontrado.")
                
                try:
                    caminho_cef = f"extratos_consolidados/extrato_cef_{mes_ano}.xlsx"
                    df_cef = processar_extrato_cef(caminho_cef)
                    extratos_encontrados.append(df_cef)
                    st.info(f"Extrato da Caixa Econômica para {st.session_state.mes_selecionado} carregado.")
                except FileNotFoundError:
                    st.warning(f"Aviso: Extrato da CEF para {st.session_state.mes_selecionado} não encontrado.")

                if not extratos_encontrados:
                    st.error("Nenhum arquivo de extrato foi encontrado no repositório para o mês selecionado.")
                    st.session_state['df_resultado'] = None
                else:
                    df_extrato_unificado = pd.concat(extratos_encontrados, ignore_index=True)
                    df_contabil_limpo = processar_relatorio_contabil(contabilidade_bruto, df_depara)
                    df_resultado_final = realizar_conciliacao(df_contabil_limpo, df_extrato_unificado)
                    st.success("Conciliação Concluída com Sucesso!")
                    st.session_state['df_resultado'] = df_resultado_final
                    
            except Exception as e:
                st.error(f"Ocorreu um erro durante o processamento: {e}")
                st.session_state['df_resultado'] = None
    else:
        st.sidebar.warning("Por favor, carregue o seu arquivo de relatório contábil.")

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
                st.success("✅ Ótima notícia! Nenhuma divergência encontrada.")
            else:
                st.write("A tabela abaixo mostra apenas as contas com divergência de saldo.")
                formatters = {col: (lambda x: f'{x:,.2f}'.replace(",", "X").replace(".", ",").replace("X", ".")) for col in resultado.columns}
                st.dataframe(df_para_mostrar.style.format(formatter=formatters))
            st.header("Download do Relatório Completo")
            col1, col2, col3 = st.columns(3)
            with col1:
                df_csv = resultado.copy(); df_csv.columns = [' - '.join(map(str,col)).strip() for col in df_csv.columns.values]; st.download_button("Baixar em CSV", df_csv.to_csv(index=True, sep=';', decimal=',').encode('utf-8-sig'), 'relatorio_consolidado.csv', 'text/csv')
            with col2:
                st.download_button("Baixar em Excel", to_excel(resultado), 'relatorio_consolidado.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            with col3:
                st.download_button("Baixar em PDF", create_pdf(resultado), 'relatorio_consolidado.pdf', 'application/pdf')
