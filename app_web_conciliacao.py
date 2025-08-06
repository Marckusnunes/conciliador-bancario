import streamlit as st
import pandas as pd
import re
import io

# --- Bloco 1: A Lógica Principal da Conciliação ---
# Documentação: Esta função contém a lógica de processamento que já criamos.
# Ela não muda, o que demonstra o poder de separar a lógica da interface do usuário.
def realizar_conciliacao(arquivo_relatorio, lista_extratos):
    # Carregar e preparar o relatório
    # O arquivo do relatório já vem limpo, então usamos os tipos de dados corretos.
    df_report = pd.read_csv(arquivo_relatorio, sep=';', decimal=',')

    def extrair_conta_chave(texto_conta):
        # Expressão regular para encontrar uma sequência de 7 ou mais dígitos
        match = re.search(r'\d{7,}', str(texto_conta))
        return int(match.group(0)) if match else None

    df_report['Conta_Chave'] = df_report['Conta_Corrente'].apply(extrair_conta_chave)
    df_report = df_report[['Conta_Chave', 'Conta_Corrente', 'Saldo_Final']].dropna(subset=['Conta_Chave'])
    df_report['Conta_Chave'] = df_report['Conta_Chave'].astype(int)

    # Carregar e preparar os extratos bancários (agora múltiplos)
    lista_df_extratos = []
    for extrato_file in lista_extratos:
        # Lemos o extrato do banco, que pode vir com formatação "suja"
        df = pd.read_csv(extrato_file, sep=';', encoding='latin-1', decimal=',')
        lista_df_extratos.append(df)

    # Junta todos os extratos em uma única tabela
    df_statement = pd.concat(lista_df_extratos, ignore_index=True)

    # Limpa as colunas de valor do extrato
    colunas_saldo_extrato = ['SALDO_ANTERIOR_TOTAL', 'SALDO_ATUAL_TOTAL', 'VALOR']
    for col in colunas_saldo_extrato:
        if col in df_statement.columns:
            df_statement[col] = df_statement[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df_statement[col] = pd.to_numeric(df_statement[col], errors='coerce')

    # Trata as datas para encontrar a última movimentação
    df_statement['DT_LANCAMENTO'] = pd.to_datetime(df_statement['DT_LANCAMENTO'], format='%d/%m/%Y', errors='coerce')
    df_statement = df_statement.sort_values(by=['CONTA', 'DT_LANCAMENTO'])
    df_final_balances = df_statement.drop_duplicates(subset=['CONTA'], keep='last')

    # Seleciona as colunas de interesse para a junção
    df_final_balances = df_final_balances[['CONTA', 'SALDO_ATUAL_TOTAL']]
    df_final_balances.rename(columns={'CONTA': 'Conta_Chave', 'SALDO_ATUAL_TOTAL': 'Saldo_Extrato'}, inplace=True)

    # Realizar a conciliação (junção das tabelas)
    df_reconciliation = pd.merge(df_report, df_final_balances, on='Conta_Chave', how='left')
    df_reconciliation['Saldo_Extrato'].fillna(0, inplace=True)
    df_reconciliation['Diferenca'] = df_reconciliation['Saldo_Final'] - df_reconciliation['Saldo_Extrato']

    # Arredonda os valores para 2 casas decimais
    for col in ['Saldo_Final', 'Saldo_Extrato', 'Diferenca']:
        df_reconciliation[col] = df_reconciliation[col].round(2)

    # Seleciona e ordena as colunas finais do relatório
    df_reconciliation = df_reconciliation[['Conta_Corrente', 'Saldo_Final', 'Saldo_Extrato', 'Diferenca']]

    return df_reconciliation

# --- Bloco 2: Construção da Interface Web com Streamlit ---
# Documentação: Aqui montamos a página da web. Cada comando 'st.' adiciona um elemento visual.

st.set_page_config(page_title="Conciliador Bancário", layout="wide")

st.title(" ferramenta de Conciliação Bancária")
st.write("Uma aplicação para comparar o relatório contábil com os extratos bancários.")

# Barra lateral para fazer o upload dos arquivos
st.sidebar.header("1. Carregar Arquivos")

arquivo_relatorio_carregado = st.sidebar.file_uploader(
    "Selecione o Relatório Contábil (CSV)",
    type=['csv']
)

lista_extratos_carregados = st.sidebar.file_uploader(
    "Selecione os Extratos Bancários (CSV)",
    type=['csv'],
    accept_