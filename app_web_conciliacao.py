import streamlit as st
import pandas as pd
import re
import io
from fpdf import FPDF
from datetime import datetime
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

# --- Bloco 1: Lógica Principal da Conciliação ---

def gerar_chave_padronizada(texto_conta):
    """
    Padroniza a criação da chave primária:
    1. Extrai apenas os dígitos.
    2. Pega os últimos 8 dígitos.
    3. Remove os zeros à esquerda.
    """
    if isinstance(texto_conta, str):
        parte_numerica = re.sub(r'\D', '', texto_conta)
        # Alterado de -14 para -8
        ultimos_8_digitos = parte_numerica[-8:]
        return ultimos_8_digitos.lstrip('0')
    return None

def carregar_depara():
    """Carrega o arquivo DE-PARA do repositório."""
    try:
        df_depara = pd.read_excel("depara/DEPARA_CONTAS BANCÁRIAS_CEF.xlsx", sheet_name="2025_JUNHO (2)")
        df_depara.columns = ['Conta Antiga', 'Conta Nova']
        df_depara['Chave Antiga'] = df_depara['Conta Antiga'].apply(gerar_chave_padronizada)
        df_depara['Chave Nova'] = df_depara['Conta Nova'].apply(gerar_chave_padronizada)
        st.info("Arquivo DE-PARA carregado e processado com sucesso.")
        return df_depara[['Chave Antiga', 'Chave Nova']]
    except FileNotFoundError:
        st.warning("Aviso: Arquivo DE-PARA 'depara/DEPARA_CONTAS BANCÁRIAS_CEF.xlsx' não encontrado. A tradução de contas não será aplicada.")
        return pd.DataFrame()

def processar_relatorio_contabil(arquivo_carregado, df_depara):
    """Lê o relatório contábil e aplica a tradução DE-PARA."""
    st.info("A processar Relatório Contabilístico...")
    df = pd.read_csv(arquivo_carregado, encoding='latin-1', sep=';', header=1)
    
    df['Chave Primaria'] = df['Domicílio bancário'].apply(gerar_chave_padronizada)
    df.dropna(subset=['Chave Primaria'], inplace=True)
    df = df[df['Chave Primaria'] != '']

    if not df_depara.empty:
        st.info("A aplicar tradução de contas DE-PARA no relatório contábil...")
        df = pd.merge(df, df_depara, left_on='Chave Primaria', right_on='Chave Antiga', how='left')
        df['Chave Primaria'] = df['Chave Nova'].fillna(df['Chave Primaria'])
        df.drop(columns=['Chave Antiga', 'Chave Nova'], inplace=True)
    
    df['Saldo Final'] = pd.to_numeric(
        df['Saldo Final'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False),
        errors='coerce'
    ).fillna(0)
    
    df_pivot = df.pivot_table(index='Chave Primaria', columns='Conta contábil', values='Saldo Final', aggfunc='sum').reset_index()
    
    rename_dict = {c: 'Saldo_Corrente_Contabil' for c in df_pivot.columns if '111111901' in str(c)}
    rename_dict.update({c: 'Saldo_Aplicado_Contabil' for c in df_pivot.columns if '111115001' in str(c)})
    df_pivot.rename(columns=rename_dict, inplace=True)

    mapa_conta = df[['Chave Primaria', 'Domicílio bancário']].drop_duplicates().set_index('Chave Primaria')
    df_final = df_pivot.join(mapa_conta, on='Chave Primaria')
    
    if 'Saldo_Corrente_Contabil' not in df_final.columns:
        df_final['Saldo_Corrente_Contabil'] = 0
    if 'Saldo_Aplicado_Contabil' not in df_final.columns:
        df_final['Saldo_Aplicado_Contabil'] = 0
        
    return df_final

def processar_extrato_bb_bruto(caminho_arquivo):
    """Lê e transforma o arquivo .bbt bruto do Banco do Brasil."""
    st.info("A processar extrato do Banco do Brasil (.bbt)...")
    df = pd.read_csv(caminho_arquivo, sep=';', header=None, encoding='latin-1', dtype=str)
    df = df.iloc[:, [1, 2, 3, 5]].copy()
    df.columns = ['Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Aplicado_Extrato']
    
    df['Chave Primaria'] = df['Conta'].apply(gerar_chave_padronizada)
    
    def formatar_saldo_bbt(valor):
        valor_str = str(valor)
        valor_limpo = re.sub(r'\D', '', valor_str)
        if len(valor_limpo) > 2:
            return float(f"{valor_limpo[:-2]}.{valor_limpo[-2:]}")
        elif valor_limpo:
            return float(f"0.{valor_limpo}")
        return 0.0
    for col in ['Saldo_Corrente_Extrato', 'Saldo_Aplicado_Extrato']:
        df[col] = df[col].apply(formatar_saldo_bbt)
    return df

def processar_extrato_cef_bruto(caminho_arquivo):
    """Lê o arquivo .cef da Caixa."""
    st.info("A processar extrato da Caixa Econômica (.cef)...")
    with open(caminho_arquivo, 'r', encoding='latin-1') as f:
        cef_content = f.readlines()
    header_line_index = -1
    for i, line in enumerate(cef_content):
        if line.strip().startswith("Conta Vinculada;"):
            header_line_index = i
            break
    if header_line_index == -1: return pd.DataFrame()
    data_io = io.StringIO("".join(cef_content[header_line_index:]))
    df = pd.read_csv(data_io, sep=';')

    df['Chave Primaria'] = df['Conta Vinculada'].apply(gerar_chave_padronizada)

    df.rename(columns={
        'Saldo Conta Corrente (R$)': 'Saldo_Corrente_Extrato',
        'Saldo Aplicado (R$)': 'Saldo_Aplicado_Extrato'
    }, inplace=True)
    for col in ['Saldo_Corrente_Extrato', 'Saldo_Aplicado_Extrato']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False), errors='coerce').fillna(0)
    if 'Saldo_Corrente_Extrato' not in df.columns:
        df['Saldo_Corrente_Extrato'] = 0
    if 'Saldo_Aplicado_Extrato' not in df.columns:
        df['Saldo_Aplicado_Extrato'] = 0
    return df

def realizar_conciliacao(df_contabil, df_extrato_unificado):
    st.info("A realizar a conciliação final...")
    df_contabil_pivot = df_contabil[['Chave Primaria', 'Domicílio bancário', 'Saldo_Corrente_Contabil', 'Saldo_Aplicado_Contabil']]
    df_extrato_pivot = df_extrato_unificado.groupby('Chave Primaria').agg({
        'Saldo_Corrente_Extrato': 'sum',
        'Saldo_Aplicado_Extrato': 'sum'
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

# --- Bloco 2: Funções para Geração de Arquivos (Sem alterações) ---
@st.cache_data
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=True, sheet_name='Conciliacao', startrow=1)
        workbook = writer.book
        worksheet = writer.sheets['Conciliacao']
        font_header = Font(bold=True, color="FFFFFF")
        align_header = Alignment(horizontal='center', vertical='center')
        fill_header = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
        border_thin = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        number_format_br = '#,##0.00'
        worksheet.merge_cells('B1:D1'); cell_movimento = worksheet['B1']; cell_movimento.value = 'Conta Movimento'; cell_movimento.font = font_header; cell_movimento.alignment = align_header; cell_movimento.fill = fill_header
        worksheet.merge_cells('E1:G1'); cell_aplicacao = worksheet['E1']; cell_aplicacao.value = 'Aplicação Financeira'; cell_aplicacao.font = font_header; cell_aplicacao.alignment = align_header; cell_aplicacao.fill = fill_header
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
        self.set_font('Arial', 'B', 8); index_name = data.index.name if data.index.name else 'ID'; self.cell(40, line_height, index_name, 1, 0, 'C'); self.cell(col_width * 3, line_height, 'Conta Movimento', 1, 0, 'C'); self.cell(col_width * 3, line_height, 'Aplicação Financeira', 1, 0, 'C'); self.ln(line_height)
        self.set_font('Arial', 'B', 7); self.cell(40, line_height, '', 1, 0, 'C'); sub_headers = ['Saldo Contábil', 'Saldo Extrato', 'Diferença'];
        for _ in range(2):
            for sub_header in sub_headers: self.cell(col_width, line_height, sub_header, 1, 0, 'C')
        self.ln(line_height)
        self.set_font('Arial', '', 6); formatted_data = data.copy()
        for col_tuple in formatted_data.columns: formatted_data[col_tuple] = formatted_data[col_tuple].apply(lambda x: f'{x:,.2f}'.replace(",", "X").replace(".", ",").replace("X", "."))
        for index, row in formatted_data.iterrows():
            display_index = str(index); self.cell(40, line_height, display_index, 1, 0, 'L')
            for item in row: self.cell(col_width, line_height, str(item), 1, 0, 'R')
            self.ln(line_height)

def create_pdf(df):
    pdf = PDF('L', 'mm', 'A4'); pdf.add_page(); pdf.create_table(df); return bytes(pdf.output())

# --- Bloco 3: Interface Web com Streamlit (Sem alterações) ---
st.set_page_config(page_title="Conciliação Bancária", layout="wide", page_icon="🏦")
st.title("🏦 Prefeitura da Cidade do Rio de Janeiro"); st.header("Controladoria Geral do Município"); st.markdown("---"); st.subheader("Conciliação de Saldos Bancários e Contábeis")

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
                    caminho_bb = f"extratos_consolidados/extrato_bb_{mes_ano}.bbt"
                    df_bb = processar_extrato_bb_bruto(caminho_bb)
                    extratos_encontrados.append(df_bb)
                except FileNotFoundError:
                    st.warning(f"Aviso: Extrato do BB (.bbt) para {st.session_state.mes_selecionado} não encontrado.")
                
                try:
                    caminho_cef = f"extratos_consolidados/extrato_cef_{mes_ano}.cef"
                    df_cef = processar_extrato_cef_bruto(caminho_cef)
                    extratos_encontrados.append(df_cef)
                except FileNotFoundError:
                    st.warning(f"Aviso: Extrato da CEF (.cef) para {st.session_state.mes_selecionado} não encontrado.")

                extratos_encontrados = [df for df in extratos_encontrados if df is not None and not df.empty]

                if not extratos_enconrados:
                    st.error("Nenhum arquivo de extrato válido foi encontrado no repositório para o mês selecionado.")
                    st.session_state['df_resultado'] = None
                else:
                    df_extrato_unificado = pd.concat(extratos_encontrados, ignore_index=True)
                    df_contabil_limpo = processar_relatorio_contabil(contabilidade_bruto, df_depara)
                    
                    st.session_state['audit_contabil'] = df_contabil_limpo
                    st.session_state['audit_extrato'] = df_extrato_unificado

                    df_resultado_final = realizar_conciliacao(df_contabil_limpo, df_extrato_unificado)
                    st.success("Conciliação Concluída com Sucesso!")
                    st.session_state['df_resultado'] = df_resultado_final
            except Exception as e:
                st.error(f"Ocorreu um erro durante o processamento: {e}")
                st.session_state['df_resultado'] = None
    else:
        st.sidebar.warning("Por favor, carregue o seu arquivo de relatório contábil.")

if 'df_resultado' in st.session_state and st.session_state['df_resultado'] is not None:
    resultado = st.session_state['df_resultado']
    if isinstance(resultado, pd.DataFrame):
        if resultado.empty:
            st.warning("Processamento concluído. Nenhuma conta correspondente foi encontrada entre o relatório contábil e os extratos para gerar um relatório de conciliação.")
        else:
            st.header("Resultado da Conciliação Consolidada")
            df_para_mostrar = resultado[(resultado[('Conta Movimento', 'Diferença')].abs() > 0.01) | (resultado[('Aplicação Financeira', 'Diferença')].abs() > 0.01)].copy()
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
        st.markdown("---")
        with st.expander("Clique aqui para auditar os dados de origem"):
            st.subheader("Dados Extraídos do Relatório Contábil (Com DE-PARA e chave padronizada)")
            if 'audit_contabil' in st.session_state and st.session_state['audit_contabil'] is not None:
                st.dataframe(st.session_state['audit_contabil'])
            st.subheader("Dados Extraídos dos Extratos Bancários (Unificados e com chave padronizada)")
            if 'audit_extrato' in st.session_state and st.session_state['audit_extrato'] is not None:
                st.dataframe(st.session_state['audit_extrato'])
