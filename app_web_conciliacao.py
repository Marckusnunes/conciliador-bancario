import streamlit as st
import pandas as pd
import re
import io
import csv
import numpy as np
from fpdf import FPDF
from datetime import datetime

# --- Bloco 1: Lógica Principal da Conciliação ---
def realizar_conciliacao(arquivo_relatorio, arquivo_extrato_consolidado):
    # --- Processamento do Relatório Contábil ---
    df_report = pd.read_csv(arquivo_relatorio, sep=';', encoding='latin-1')
    if "Unidade Gestora" in df_report.columns[0]:
        df_report.columns = ["Unidade_Gestora", "Domicilio_Bancario", "Conta_Contabil", "Conta_Corrente", "Saldo_Inicial", "Debito", "Credito", "Saldo_Final"]
        if "Unidade Gestora" in df_report.iloc[0].to_string():
            df_report = df_report.drop(df_report.index[0])

    colunas_numericas_report = ["Saldo_Final"]
    for col in colunas_numericas_report:
        if col in df_report.columns:
            df_report[col] = df_report[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df_report[col] = pd.to_numeric(df_report[col], errors='coerce')

    def extrair_conta_chave_report(texto_conta):
        match = re.search(r'\d{7,}', str(texto_conta))
        return int(match.group(0)) if match else None

    df_report['Conta_Chave'] = df_report['Conta_Corrente'].apply(extrair_conta_chave_report)
    df_report.dropna(subset=['Conta_Chave'], inplace=True)
    df_report['Conta_Chave'] = df_report['Conta_Chave'].astype(int)

    df_movimento_contabil = df_report[df_report['Conta_Contabil'].str.contains('111111901', na=False)]
    df_movimento_contabil = df_movimento_contabil.groupby('Conta_Chave')['Saldo_Final'].sum().reset_index()
    df_movimento_contabil.rename(columns={'Saldo_Final': 'Saldo_Contabil_Movimento'}, inplace=True)

    df_aplicacao_contabil = df_report[df_report['Conta_Contabil'].str.contains('111115001', na=False)]
    df_aplicacao_contabil = df_aplicacao_contabil.groupby('Conta_Chave')['Saldo_Final'].sum().reset_index()
    df_aplicacao_contabil.rename(columns={'Saldo_Final': 'Saldo_Contabil_Aplicacao'}, inplace=True)

    df_report_pivot = pd.merge(df_movimento_contabil, df_aplicacao_contabil, on='Conta_Chave', how='outer')
    mapa_domicilio = df_report[['Conta_Chave', 'Domicilio_Bancario']].drop_duplicates().set_index('Conta_Chave')

    # --- Processamento do Extrato Consolidado ---
    df_extrato = pd.read_csv(arquivo_extrato_consolidado, encoding='latin-1', sep=',', quotechar='"')

    df_extrato.rename(columns={
        'Conta': 'Conta',
        'Saldo Corrente': 'Saldo_Extrato_Movimento',
        'Saldo Aplicado': 'Saldo_Extrato_Aplicacao'
    }, inplace=True)

    for col in ['Saldo_Extrato_Movimento', 'Saldo_Extrato_Aplicacao']:
        df_extrato[col] = (
            df_extrato[col]
            .astype(str)
            .str.replace('.', '', regex=False)
            .str.replace(',', '.', regex=False)
        )
        df_extrato[col] = pd.to_numeric(df_extrato[col], errors='coerce').fillna(0)

    def extrair_conta_chave_extrato(texto_conta):
        try:
            numeros = re.sub(r'\D', '', str(texto_conta))
            return int(numeros) if numeros else None
        except:
            return None

    df_extrato['Conta_Chave'] = df_extrato['Conta'].apply(extrair_conta_chave_extrato)

    df_extrato_pivot = df_extrato[['Conta_Chave', 'Saldo_Extrato_Movimento', 'Saldo_Extrato_Aplicacao']].dropna()
    df_extrato_pivot['Conta_Chave'] = df_extrato_pivot['Conta_Chave'].astype(int)
    df_extrato_pivot = df_extrato_pivot.groupby('Conta_Chave').sum().reset_index()

    # --- Consolidação e Reestruturação Final ---
    df_final = pd.merge(df_report_pivot, df_extrato_pivot, on='Conta_Chave', how='outer')
    df_final.fillna(0, inplace=True)
    df_final = df_final.join(mapa_domicilio, on='Conta_Chave')
    df_final['Domicilio_Bancario'].fillna('Não encontrado no relatório', inplace=True)
    df_final = df_final[df_final['Conta_Chave'] != 0]

    df_final['Diferenca_Movimento'] = df_final['Saldo_Contabil_Movimento'] - df_final['Saldo_Extrato_Movimento']
    df_final['Diferenca_Aplicacao'] = df_final['Saldo_Contabil_Aplicacao'] - df_final['Saldo_Extrato_Aplicacao']

    df_final = df_final.set_index('Domicilio_Bancario')
    df_final = df_final[[
        'Saldo_Contabil_Movimento', 'Saldo_Extrato_Movimento', 'Diferenca_Movimento',
        'Saldo_Contabil_Aplicacao', 'Saldo_Extrato_Aplicacao', 'Diferenca_Aplicacao'
    ]]

    df_final.columns = pd.MultiIndex.from_tuples([
        ('Conta Movimento', 'Saldo Contábil'), ('Conta Movimento', 'Saldo Extrato'), ('Conta Movimento', 'Diferença'),
        ('Aplicação Financeira', 'Saldo Contábil'), ('Aplicação Financeira', 'Saldo Extrato'), ('Aplicação Financeira', 'Diferença')
    ], names=['Grupo', 'Item'])

    return df_final

# Bloco 2 e 3 permanecem inalterados
# (to_excel, PDF, Streamlit interface)
# Copie o restante da interface e funções normalmente, pois não há alteração nesses trechos