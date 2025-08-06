import streamlit as st
import pandas as pd
import re
import io
import csv
import numpy as np

# --- Bloco 1: Lógica Principal (Modificada para Diagnóstico) ---
def realizar_diagnostico(arquivo_relatorio, arquivo_extrato_consolidado):
    # --- Processamento do Relatório Contábil ---
    df_report = pd.read_csv(arquivo_relatorio, sep=';', encoding='latin-1')
    if "Unidade Gestora" in df_report.columns[0]:
        df_report.columns = ["Unidade_Gestora", "Domicilio_Bancario", "Conta_Contabil", "Conta_Corrente", "Saldo_Inicial", "Debito", "Credito", "Saldo_Final"]
        if "Unidade Gestora" in df_report.iloc[0].to_string():
            df_report = df_report.drop(df_report.index[0])

    def extrair_conta_chave_report(texto_conta):
        match = re.search(r'\d{7,}', str(texto_conta))
        return int(match.group(0)) if match else None

    df_report['Conta_Chave'] = df_report['Conta_Corrente'].apply(extrair_conta_chave_report)
    df_report.dropna(subset=['Conta_Chave'], inplace=True)
    df_report['Conta_Chave'] = df_report['Conta_Chave'].astype(int)
    
    # Prepara o arquivo de debug do relatório
    debug_report = df_report[['Domicilio_Bancario', 'Conta_Corrente', 'Conta_Chave']].drop_duplicates()

    # --- Processamento do Extrato Consolidado ---
    dados_extrato = []
    stringio = io.StringIO(arquivo_extrato_consolidado.getvalue().decode('latin-1'))
    next(stringio)
    reader = csv.reader(stringio, quotechar='"', delimiter=',')
    for row in reader:
        if len(row) >= 6:
            dados_extrato.append(row[:6])

    colunas_extrato = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente', 'Saldo_Invest', 'Saldo_Aplicado']
    df_extrato = pd.DataFrame(dados_extrato, columns=colunas_extrato)

    def extrair_conta_chave_extrato(texto_conta):
        try:
            numeros = re.sub(r'\D', '', str(texto_conta))
            return int(numeros) if numeros else None
        except (ValueError, IndexError):
            return None
            
    df_extrato['Conta_Chave'] = df_extrato['Conta'].apply(extrair_conta_chave_extrato)
    
    # Prepara o arquivo de debug do extrato
    debug_extrato = df_extrato[['Conta', 'Titular', 'Conta_Chave']].drop_duplicates().dropna(subset=['Conta_Chave'])
    debug_extrato['Conta_Chave'] = debug_extrato['Conta_Chave'].astype(int)
    
    return debug_report, debug_extrato

# --- Bloco 2: Interface Web (Modificada para Diagnóstico) ---
st.set_page_config(page_title="Diagnóstico de Conciliação", layout="wide")
st.title("Ferramenta de Diagnóstico de Chaves")
st.warning("Esta é uma versão de diagnóstico para verificar a correspondência de contas entre os arquivos.")

st.sidebar.header("1. Carregar Arquivos")
arquivo_relatorio_carregado = st.sidebar.file_uploader("Selecione o Relatório Contábil (CSV Original)", type=['csv'])
arquivo_extrato_consolidado_carregado = st.sidebar.file_uploader("Selecione o Extrato Consolidado (CSV)", type=['csv'])

st.sidebar.header("2. Processar")
if arquivo_relatorio_carregado and arquivo_extrato_consolidado_carregado:
    if st.sidebar.button("Diagnosticar Chaves Agora"):
        with st.spinner("Extraindo chaves de ambos os arquivos..."):
            try:
                debug_df_report, debug_df_extrato = realizar_diagnostico(arquivo_relatorio_carregado, arquivo_extrato_consolidado_carregado)
                st.success("Diagnóstico concluído!")
                st.session_state['debug_report'] = debug_df_report
                st.session_state['debug_extrato'] = debug_df_extrato
            except Exception as e:
                st.error(f"Ocorreu um erro durante o processamento: {e}")
else:
    st.sidebar.warning("Por favor, carregue ambos os arquivos para diagnóstico.")

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
    chaves_comuns = pd.merge(debug_report, debug_extrato, on='Conta_Chave', how='inner')
    if chaves_comuns.empty:
        st.error("ANÁLISE: Nenhuma chave em comum foi encontrada entre os dois arquivos. A conciliação não pode prosseguir pois não há dados para cruzar.")
    else:
        st.success(f"ANÁLISE: Foram encontradas {len(chaves_comuns)} contas correspondentes entre os dois arquivos.")
        st.write("Contas correspondentes:")
        st.dataframe(chaves_comuns)