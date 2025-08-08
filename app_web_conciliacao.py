import streamlit as st
import pandas as pd
import re
import io
import numpy as np
import csv
from fpdf import FPDF
from datetime import datetime

# --- Bloco 1: Funções de Processamento ---

def processar_relatorio_bruto(arquivo_bruto_contabil):
    df = pd.DataFrame()
    nome_arquivo = arquivo_bruto_contabil.name
    arquivo_bruto_contabil.seek(0)
    try:
        if nome_arquivo.endswith('.xlsx') or nome_arquivo.endswith('.xls'):
            df = pd.read_excel(arquivo_bruto_contabil, engine='openpyxl')
        elif nome_arquivo.endswith('.csv'):
            df = pd.read_csv(arquivo_bruto_contabil, sep=';', encoding='latin-1', on_bad_lines='skip', header=None)
            if len(df.columns) <= 1:
                arquivo_bruto_contabil.seek(0)
                df = pd.read_csv(arquivo_bruto_contabil, sep=',', encoding='latin-1', on_bad_lines='skip', header=None)
    except Exception as e:
        st.error(f"Não foi possível ler o arquivo contábil: {e}")
        return pd.DataFrame()

    if df.empty: return pd.DataFrame()

    if len(df.columns) >= 8:
        st.info("Detectado arquivo contábil bruto (8 colunas). Aplicando transformação...")
        if isinstance(df.iloc[0,0], str) and 'Unidade Gestora' in df.iloc[0,0]:
             df = df.iloc[2:].reset_index(drop=True)
        df = df.iloc[:,:8]
        df.columns = [
            'Unidade Gestora', 'Domicílio bancário', 'Conta contábil', 'Conta Corrente',
            'Saldo Inicial', 'Débito', 'Crédito', 'Saldo Final'
        ]
        df.dropna(subset=['Domicílio bancário'], inplace=True)
        df = df[~df['Conta contábil'].astype(str).str.contains('Total por', na=False)].copy()
        df['Saldo Final'] = pd.to_numeric(
            df['Saldo Final'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False),
            errors='coerce'
        ).fillna(0)
        df_pivot = df.pivot_table(
            index='Domicílio bancário', columns='Conta contábil', values='Saldo Final', aggfunc='sum'
        ).reset_index()
        rename_dict = {c: 'Saldo Corrente' for c in df_pivot.columns if '111111901' in c}
        rename_dict.update({c: 'Saldo Aplicado' for c in df_pivot.columns if '111115001' in c})
        df_pivot.rename(columns=rename_dict, inplace=True)
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

def processar_extrato_bb(caminho_arquivo):
    df = pd.read_excel(caminho_arquivo, engine='openpyxl', sheet_name='Table 1')
    if len(df.columns) == 7:
        df.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato', 'Vazio']
        df = df.drop(columns=['Vazio'])
    else:
        df.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato']
    for col in df.columns:
        if 'Saldo' in col: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df

def processar_extrato_cef(caminho_arquivo):
    df = pd.read_excel(caminho_arquivo, engine='openpyxl', skiprows=13)
    df.columns = ['Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato', 'Saldo_Total']
    for col in ['Saldo_Corrente_Extrato', 'Saldo_Aplicado_Extrato']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    if 'Agencia' not in df.columns: df['Agencia'] = '4064' 
    return df

# --- Bloco 2: Interface Web de Inspeção ---
st.set_page_config(page_title="Inspeção de Conciliação", layout="wide", page_icon="🕵️")
st.title("🕵️ Ferramenta de Inspeção de Dados")
st.warning("Esta é uma versão de diagnóstico para verificar os dados antes da conciliação.")

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

if st.sidebar.button("Inspecionar Dados"):
    if contabilidade_bruto is not None:
        with st.spinner("Processando arquivos..."):
            try:
                # --- Processa Relatório Contábil ---
                st.header("1. Dados Processados do Relatório Contábil")
                df_contabil_limpo = processar_relatorio_bruto(contabilidade_bruto)
                
                if not df_contabil_limpo.empty:
                    def extrair_chave(texto_conta):
                        try: return int(re.sub(r'\D', '', str(texto_conta)))
                        except: return None
                    df_contabil_limpo['Conta_Chave'] = df_contabil_limpo['Conta'].apply(extrair_chave)
                    st.dataframe(df_contabil_limpo)
                    st.session_state['contabil_inspecao'] = df_contabil_limpo
                else:
                    st.error("Não foi possível processar o relatório contábil.")

                # --- Processa Extratos ---
                st.markdown("---")
                st.header("2. Dados Processados dos Extratos Bancários")
                partes_mes = st.session_state.mes_selecionado.lower().split()
                mes_ano = f"{partes_mes[0]}_{partes_mes[1]}"
                extratos_encontrados = []
                try:
                    caminho_bb = f"extratos_consolidados/extrato_bb_{mes_ano}.xlsx"
                    df_bb = processar_extrato_bb(caminho_bb)
                    extratos_encontrados.append(df_bb)
                    st.info(f"Extrato do Banco do Brasil para {st.session_state.mes_selecionado} carregado.")
                except FileNotFoundError:
                    st.warning(f"Aviso: Extrato do BB para {st.session_state.mes_selecionado} não encontrado.")
                
                try:
                    caminho_cef = f"extratos_consolidados/extrato_cef_{mes_ano}.cef"
                    df_cef = processar_extrato_cef(caminho_cef)
                    extratos_encontrados.append(df_cef)
                    st.info(f"Extrato da Caixa Econômica para {st.session_state.mes_selecionado} carregado.")
                except FileNotFoundError:
                    st.warning(f"Aviso: Extrato da CEF para {st.session_state.mes_selecionado} não encontrado.")

                if not extratos_encontrados:
                    st.error("Nenhum arquivo de extrato foi encontrado no repositório para o mês selecionado.")
                else:
                    df_extrato_unificado = pd.concat(extratos_encontrados, ignore_index=True)
                    df_extrato_unificado['Conta_Chave'] = df_extrato_unificado['Conta'].apply(extrair_chave)
                    st.dataframe(df_extrato_unificado)
                    st.session_state['extrato_inspecao'] = df_extrato_unificado

            except Exception as e:
                st.error(f"Ocorreu um erro durante o processamento: {e}")
    else:
        st.sidebar.warning("Por favor, carregue o seu arquivo de relatório contábil.")

if 'contabil_inspecao' in st.session_state and 'extrato_inspecao' in st.session_state:
    st.markdown("---")
    st.header("3. Análise de Correspondência de Chaves")
    df_c = st.session_state['contabil_inspecao']
    df_e = st.session_state['extrato_inspecao']
    
    chaves_comuns = pd.merge(df_c[['Conta_Chave']], df_e[['Conta_Chave']], on='Conta_Chave', how='inner')
    
    if chaves_comuns.empty:
        st.error("NENHUMA CONTA EM COMUM FOI ENCONTRADA.")
        st.write("Isso explica por que o relatório final não mostra divergências. Os números de conta (`Conta_Chave`) gerados para cada arquivo não são iguais.")
    else:
        st.success(f"Foram encontradas {len(chaves_comuns)} contas em comum!")
        st.write("A conciliação deveria funcionar para estas contas. Se o resultado final ainda mostra 'nenhuma divergência', pode haver um erro na leitura dos valores de saldo.")