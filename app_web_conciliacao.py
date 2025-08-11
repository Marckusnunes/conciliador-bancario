import streamlit as st
import pandas as pd
import re
import io
import numpy as np
import csv
from fpdf import FPDF
from datetime import datetime
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

# --- Bloco 1: Lógica Principal da Conciliação (Tudo em uma única função) ---

def realizar_conciliacao_completa(contabilidade_file, extrato_bb_path, extrato_cef_path):
    # --- ETAPA 1: Ler e preparar o arquivo da Contabilidade ---
    df_contabil = pd.DataFrame()
    nome_arquivo = contabilidade_file.name
    contabilidade_file.seek(0)
    try:
        if nome_arquivo.endswith('.xlsx') or nome_arquivo.endswith('.xls'):
            df_contabil = pd.read_excel(contabilidade_file, engine='openpyxl')
        elif nome_arquivo.endswith('.csv'):
            df_contabil = pd.read_csv(contabilidade_file, sep=';', encoding='latin-1', on_bad_lines='skip', header=None)
            if len(df_contabil.columns) <= 1:
                contabilidade_file.seek(0)
                df_contabil = pd.read_csv(contabilidade_file, sep=',', encoding='latin-1', on_bad_lines='skip', header=None)
    except Exception as e:
        st.error(f"Não foi possível ler o arquivo contábil: {e}")
        return pd.DataFrame()

    if df_contabil.empty: return pd.DataFrame()

    # Verifica se é o arquivo bruto (8+ colunas) ou o ajustado (6 colunas)
    if len(df_contabil.columns) >= 8:
        st.info("Detectado arquivo contábil bruto (8 colunas). Aplicando transformação...")
        if isinstance(df_contabil.iloc[0,0], str) and 'Unidade Gestora' in df_contabil.iloc[0,0]:
             df_contabil = df_contabil.iloc[2:].reset_index(drop=True)
        df_contabil = df_contabil.iloc[:,:8]
        df_contabil.columns = ['Unidade Gestora', 'Domicílio bancário', 'Conta contábil', 'Conta Corrente', 'Saldo Inicial', 'Débito', 'Crédito', 'Saldo Final']
        df_contabil.dropna(subset=['Domicílio bancário'], inplace=True)
        df_contabil = df_contabil[~df_contabil['Conta contábil'].astype(str).str.contains('Total por', na=False)].copy()
        df_contabil['Saldo Final'] = pd.to_numeric(df_contabil['Saldo Final'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), errors='coerce').fillna(0)
        
        df_pivot = df_contabil.pivot_table(index='Domicílio bancário', columns='Conta contábil', values='Saldo Final', aggfunc='sum').reset_index()
        rename_dict = {c: 'Saldo_Corrente_Contabil' for c in df_pivot.columns if '111111901' in c}
        rename_dict.update({c: 'Saldo_Aplicado_Contabil' for c in df_pivot.columns if '111115001' in c})
        df_pivot.rename(columns=rename_dict, inplace=True)

        def formatar_conta(texto_conta):
            if not isinstance(texto_conta, str): return ""
            try:
                num_sem_zeros = texto_conta.lstrip('0');
                if not num_sem_zeros: return "0"
                principal, verificador = num_sem_zeros[:-1], num_sem_zeros[-1]
                return f"{int(principal):,}".replace(',', '.') + f"-{verificador}"
            except: return texto_conta
        
        partes_domicilio = df_pivot['Domicílio bancário'].str.split(' - ', expand=True)
        df_contabil_limpo = pd.DataFrame()
        df_contabil_limpo['Conta'] = partes_domicilio.get(2).apply(formatar_conta)
        df_contabil_limpo['Titular'] = partes_domicilio.get(3)
        df_contabil_limpo['Saldo_Corrente_Contabil'] = df_pivot.get('Saldo_Corrente_Contabil')
        df_contabil_limpo['Saldo_Aplicado_Contabil'] = df_pivot.get('Saldo Aplicado')
        df_contabil_limpo.fillna(0, inplace=True)
    else: # Se for o arquivo ajustado de 6 colunas
        st.info("Detectado arquivo contábil ajustado.")
        df_contabil.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Contabil', 'Saldo_Cta_Invest_Contabil', 'Saldo_Aplicado_Contabil']
        df_contabil_limpo = df_contabil
        for col in ['Saldo_Corrente_Contabil', 'Saldo_Aplicado_Contabil']:
            df_contabil_limpo[col] = pd.to_numeric(df_contabil_limpo[col], errors='coerce').fillna(0)

    # --- ETAPA 2: Ler e preparar os arquivos do Extrato ---
    extratos_encontrados = []
    try:
        df_bb = pd.read_excel(extrato_bb_path, engine='openpyxl', sheet_name='Table 1')
        if len(df_bb.columns) == 7:
            df_bb.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato', 'Vazio']
            df_bb = df_bb.drop(columns=['Vazio'])
        else:
            df_bb.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato']
        for col in df_bb.columns:
            if 'Saldo' in col: df_bb[col] = pd.to_numeric(df_bb[col], errors='coerce').fillna(0)
        extratos_encontrados.append(df_bb)
        st.info("Extrato do Banco do Brasil carregado.")
    except FileNotFoundError:
        st.warning("Aviso: Extrato do BB não encontrado.")
    
    try:
        df_cef = pd.read_excel(extrato_cef_path, engine='openpyxl', skiprows=13)
        df_cef.columns = ['Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato', 'Saldo_Total']
        for col in ['Saldo_Corrente_Extrato', 'Saldo_Aplicado_Extrato']:
            df_cef[col] = pd.to_numeric(df_cef[col], errors='coerce').fillna(0)
        if 'Agencia' not in df_cef.columns: df_cef['Agencia'] = '4064'
        extratos_encontrados.append(df_cef)
        st.info("Extrato da Caixa Econômica carregado.")
    except FileNotFoundError:
        st.warning("Aviso: Extrato da CEF não encontrado.")

    if not extratos_encontrados:
        st.error("Nenhum arquivo de extrato foi encontrado no repositório.")
        return pd.DataFrame()
        
    df_extrato_unificado = pd.concat(extratos_encontrados, ignore_index=True)

    # --- ETAPA 3: Conciliação ---
    def extrair_chave(texto_conta):
        try:
            numeros = re.sub(r'\D', '', str(texto_conta))
            if not numeros or len(numeros) > 18: return None
            return int(numeros)
        except: return None
            
    df_contabil_limpo['Conta_Chave'] = df_contabil_limpo['Conta'].apply(extrair_chave)
    df_extrato_unificado['Conta_Chave'] = df_extrato_unificado['Conta'].apply(extrair_chave)
    
    for df in [df_contabil_limpo, df_extrato_unificado]:
        df.dropna(subset=['Conta_Chave', 'Conta'], inplace=True)
        df['Conta_Chave'] = df['Conta_Chave'].astype('int64')

    df_contabil_pivot = df_contabil_limpo.groupby('Conta_Chave').agg({'Conta': 'first','Saldo_Corrente_Contabil': 'sum','Saldo_Aplicado_Contabil': 'sum'}).reset_index()
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
contabilidade_bruto = st.sidebar.file_uploader(f"Selecione o seu Relatório Contábil de {st.session_state.mes_selecionado}", type=['csv', 'xlsx', 'xls'])

if st.sidebar.button("Conciliar Agora"):
    if contabilidade_bruto is not None:
        with st.spinner("Processando..."):
            try:
                partes_mes = st.session_state.mes_selecionado.lower().split()
                mes_ano = f"{partes_mes[0]}_{partes_mes[1]}"
                
                caminho_bb = f"extratos_consolidados/extrato_bb_{mes_ano}.xlsx"
                caminho_cef = f"extratos_consolidados/extrato_cef_{mes_ano}.xlsx"

                df_resultado_final = realizar_conciliacao_completa(contabilidade_bruto, caminho_bb, caminho_cef)
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
            st.info("Processamento concluído. Nenhuma conta correspondente foi encontrada entre os arquivos para gerar um relatório.")
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
                formatters = {col: (lambda x: f'{x:,.2f}'.replace(",", "X").replace(".", ",").replace("X", ".")) for col in df_para_mostrar.columns}
                st.dataframe(df_para_mostrar.style.format(formatter=formatters))
            st.header("Download do Relatório Completo")
            col1, col2, col3 = st.columns(3)
            with col1:
                df_csv = resultado.copy(); df_csv.columns = [' - '.join(map(str,col)).strip() for col in df_csv.columns.values]; st.download_button("Baixar em CSV", df_csv.to_csv(index=True, sep=';', decimal=',').encode('utf-8-sig'), 'relatorio_consolidado.csv', 'text/csv')
            with col2:
                st.download_button("Baixar em Excel", to_excel(resultado), 'relatorio_consolidado.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            with col3:
                st.download_button("Baixar em PDF", create_pdf(resultado), 'relatorio_consolidado.pdf', 'application/pdf')