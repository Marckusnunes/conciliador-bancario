import streamlit as st
import pandas as pd
import re
import io

# --- Bloco 1: Lógica Principal da Conciliação ---

def processar_relatorio_contabil(arquivo_carregado):
    """Lê o relatório contábil bruto e aplica a nova lógica de extração de chave."""
    st.info("Processando Relatório Contábil para Diagnóstico...")
    df = pd.read_csv(arquivo_carregado, encoding='latin-1', sep=';', header=1)
    
    def extrair_chave_contabil(texto_conta):
        if isinstance(texto_conta, str):
            numeric_part = re.sub(r'\D', '', texto_conta)
            if len(numeric_part) > 7:
                return numeric_part[7:]
            return numeric_part
        return None
        
    df['Chave Primaria'] = df['Domicílio bancário'].apply(extrair_chave_contabil)
    df.dropna(subset=['Chave Primaria'], inplace=True)
    df = df[df['Chave Primaria'] != '']
    
    # Para o diagnóstico, retornamos a tabela com a chave para inspeção
    return df[['Domicílio bancário', 'Chave Primaria']].drop_duplicates()

def processar_extrato_bb(caminho_arquivo):
    df = pd.read_excel(caminho_arquivo, engine='openpyxl', sheet_name='Table 1')
    if len(df.columns) == 7:
        df.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato', 'Vazio']
    else:
        df.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato']
    
    # Usa uma chave genérica para unificar
    df['Chave Primaria'] = df['Conta'].astype(str).apply(lambda x: re.sub(r'\D', '', x))
    return df[['Conta', 'Chave Primaria']].drop_duplicates()

def processar_extrato_cef_bruto(caminho_arquivo):
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
    
    def extrair_chave_cef(texto_conta):
        if isinstance(texto_conta, str):
            numeric_part = re.sub(r'\D', '', texto_conta)
            if len(numeric_part) > 4:
                return numeric_part[4:]
        return None
    
    df['Chave Primaria'] = df['Conta Vinculada'].apply(extrair_chave_cef)
    return df[['Conta Vinculada', 'Chave Primaria']].drop_duplicates()


# --- Bloco 2: Interface Web de Diagnóstico ---
st.set_page_config(page_title="Diagnóstico de Conciliação", layout="wide", page_icon="🕵️")
st.title("🕵️ Ferramenta de Diagnóstico de Chaves Primárias")
st.warning("Esta é uma versão de diagnóstico para verificar a correspondência de contas entre os arquivos.")

st.sidebar.header("1. Carregar Arquivo")
contabilidade_bruto = st.sidebar.file_uploader("Selecione o Relatório Contábil Bruto (CSV)", type=['csv'])

st.sidebar.header("2. Processar")
if contabilidade_bruto:
    if st.sidebar.button("Diagnosticar Chaves"):
        with st.spinner("Processando..."):
            try:
                # Processa o relatório contábil
                df_chaves_contabil = processar_relatorio_contabil(contabilidade_bruto)
                st.session_state['debug_contabil'] = df_chaves_contabil

                # Processa os extratos
                extratos_encontrados = []
                try:
                    # Assumindo Junho 2025 para este teste, já que não há seletor de mês
                    caminho_bb = "extratos_consolidados/extrato_bb_junho_2025.xlsx"
                    df_bb = processar_extrato_bb(caminho_bb)
                    extratos_encontrados.append(df_bb)
                    st.info("Extrato do Banco do Brasil processado.")
                except FileNotFoundError:
                    st.warning("Aviso: Extrato do BB não encontrado.")
                
                try:
                    caminho_cef = "extratos_consolidados/extrato_cef_junho_2025.cef"
                    df_cef = processar_extrato_cef_bruto(caminho_cef)
                    extratos_encontrados.append(df_cef)
                    st.info("Extrato da Caixa (.cef) processado.")
                except FileNotFoundError:
                    st.warning("Aviso: Extrato da CEF (.cef) não encontrado.")

                if extratos_encontrados:
                    df_extrato_unificado = pd.concat(extratos_encontrados, ignore_index=True)
                    st.session_state['debug_extrato'] = df_extrato_unificado
                else:
                    st.error("Nenhum arquivo de extrato foi encontrado.")

            except Exception as e:
                st.error(f"Ocorreu um erro: {e}")

if 'debug_contabil' in st.session_state:
    st.header("1. Chaves Extraídas do Relatório Contábil")
    st.dataframe(st.session_state['debug_contabil'])

if 'debug_extrato' in st.session_state:
    st.header("2. Chaves Extraídas dos Extratos Bancários")
    st.dataframe(st.session_state['debug_extrato'][['Conta', 'Chave Primaria', 'Titular']].dropna(subset=['Chave Primaria']))
    
    st.header("3. Análise de Correspondência")
    df_c = st.session_state['debug_contabil']
    df_e = st.session_state['debug_extrato']
    df_c['Chave Primaria'] = df_c['Chave Primaria'].astype(str)
    df_e['Chave Primaria'] = df_e['Chave Primaria'].astype(str)
    
    chaves_comuns = pd.merge(df_c, df_e, on='Chave Primaria', how='inner')
    
    if chaves_comuns.empty:
        st.error("ANÁLISE: Nenhuma chave primária em comum foi encontrada.")
    else:
        st.success(f"ANÁLISE: Foram encontradas {len(chaves_comuns)} contas correspondentes!")
        st.dataframe(chaves_comuns)