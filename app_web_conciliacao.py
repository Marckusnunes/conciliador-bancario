import streamlit as st
import pandas as pd
import re
import io

# --- Bloco 1: Lógica de Diagnóstico ---
def realizar_diagnostico(contabilidade_file, extrato_file):
    
    # --- Processamento do Relatório Contábil ---
    df_contabil = pd.read_excel(contabilidade_file, engine='openpyxl')
    df_contabil.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Contabil', 'Saldo_Cta_Invest_Contabil', 'Saldo_Aplicado_Contabil']

    def extrair_chave(texto_conta):
        try:
            return int(re.sub(r'\D', '', str(texto_conta)))
        except (ValueError, IndexError):
            return None
            
    df_contabil['Conta_Chave'] = df_contabil['Conta'].apply(extrair_chave)
    debug_contabil = df_contabil[['Conta', 'Titular', 'Conta_Chave']].dropna(subset=['Conta_Chave']).drop_duplicates()
    debug_contabil['Conta_Chave'] = debug_contabil['Conta_Chave'].astype(int)

    # --- Processamento do Extrato Consolidado ---
    df_extrato = pd.read_excel(extrato_file, engine='openpyxl', sheet_name='Table 1')
    df_extrato.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato']
    
    df_extrato['Conta_Chave'] = df_extrato['Conta'].apply(extrair_chave)
    debug_extrato = df_extrato[['Conta', 'Titular', 'Conta_Chave']].dropna(subset=['Conta_Chave']).drop_duplicates()
    debug_extrato['Conta_Chave'] = debug_extrato['Conta_Chave'].astype(int)
    
    return debug_contabil, debug_extrato

# --- Bloco 2: Interface Web de Diagnóstico ---
st.set_page_config(page_title="Diagnóstico de Conciliação", layout="wide")
st.title("Ferramenta de Diagnóstico de Chaves")
st.warning("Esta é uma versão de diagnóstico para verificar a correspondência de contas entre os arquivos.")

st.sidebar.header("1. Carregar Arquivos")
contabilidade = st.sidebar.file_uploader("Selecione o Relatório Contábil (XLSX)", type=['xlsx', 'xls'])
extrato = st.sidebar.file_uploader("Selecione o Extrato Consolidado (XLSX)", type=['xlsx', 'xls'])

st.sidebar.header("2. Processar")
if contabilidade and extrato:
    if st.sidebar.button("Diagnosticar Chaves Agora"):
        with st.spinner("Extraindo chaves de ambos os arquivos..."):
            try:
                debug_df_report, debug_df_extrato = realizar_diagnostico(contabilidade, extrato)
                st.success("Diagnóstico concluído!")
                st.session_state['debug_report'] = debug_df_report
                st.session_state['debug_extrato'] = debug_df_extrato
            except Exception as e:
                st.error(f"Ocorreu um erro durante o processamento: {e}")
else:
    st.sidebar.warning("Por favor, carregue os dois arquivos para diagnóstico.")

if 'debug_report' in st.session_state and 'debug_extrato' in st.session_state:
    debug_report = st.session_state['debug_report']
    debug_extrato = st.session_state['debug_extrato']
    
    st.header("Chaves Extraídas do Relatório Contábil")
    st.write(f"Total de chaves únicas encontradas: {len(debug_report)}")
    st.dataframe(debug_report)
    st.download_button(
        "Baixar Chaves do Relatório", 
        debug_report.to_csv(index=False, sep=';').encode('utf-8-sig'), 
        'debug_chaves_relatorio.csv', 
        'text/csv'
    )

    st.header("Chaves Extraídas do Extrato Consolidado")
    st.write(f"Total de chaves únicas encontradas: {len(debug_extrato)}")
    st.dataframe(debug_extrato)
    st.download_button(
        "Baixar Chaves do Extrato", 
        debug_extrato.to_csv(index=False, sep=';').encode('utf-8-sig'), 
        'debug_chaves_extrato.csv', 
        'text/csv'
    )
    
    st.header("Análise de Correspondência")
    chaves_comuns = pd.merge(debug_report, debug_extrato, on='Conta_Chave', how='inner', suffixes=('_contabil', '_extrato'))
    if chaves_comuns.empty:
        st.error("ANÁLISE: Nenhuma chave em comum foi encontrada entre os dois arquivos.")
    else:
        st.success(f"ANÁLISE: Foram encontradas {len(chaves_comuns)} contas correspondentes entre os dois arquivos.")
        st.write("Amostra de contas correspondentes:")
        st.dataframe(chaves_comuns.head())