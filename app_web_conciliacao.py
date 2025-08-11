import streamlit as st
import pandas as pd
import re
import io

# --- Bloco 1: Lógica de Diagnóstico ---
def realizar_diagnostico(contabilidade_file, extrato_bb_path, extrato_cef_path):
    
    # --- Processamento do Relatório Contábil ---
    st.header("1. Chaves Extraídas do Relatório Contábil")
    df_contabil = pd.read_csv(contabilidade_file, encoding='latin-1', sep=';', header=1)
    
    def extrair_chave_contabil(texto_conta):
        if isinstance(texto_conta, str):
            numeric_part = re.sub(r'\D', '', texto_conta)
            if len(numeric_part) > 7: return numeric_part[7:]
            return numeric_part
        return None
        
    df_contabil['Chave Primaria'] = df_contabil['Domicílio bancário'].apply(extrair_chave_contabil)
    df_contabil.dropna(subset=['Chave Primaria'], inplace=True)
    debug_contabil = df_contabil[['Domicílio bancário', 'Chave Primaria']].drop_duplicates()
    st.dataframe(debug_contabil)

    # --- Processamento dos Extratos ---
    st.header("2. Chaves Extraídas dos Extratos Bancários")
    extratos_encontrados = []
    try:
        df_bb = pd.read_excel(extrato_bb_path, engine='openpyxl', sheet_name='Table 1')
        df_bb.columns = ['Agencia', 'Conta', 'Titular', 'Saldo_Corrente_Extrato', 'Saldo_Cta_Invest_Extrato', 'Saldo_Aplicado_Extrato']
        df_bb['Chave Primaria'] = df_bb['Conta'].astype(str).apply(lambda x: re.sub(r'\D', '', x))
        extratos_encontrados.append(df_bb[['Conta', 'Titular', 'Chave Primaria']])
        st.info("Extrato do Banco do Brasil processado.")
    except FileNotFoundError:
        st.warning("Aviso: Extrato do BB não encontrado.")
    except Exception as e:
        st.error(f"Erro ao processar extrato BB: {e}")

    try:
        with open(extrato_cef_path, 'r', encoding='latin-1') as f:
            cef_content = f.readlines()
        header_line_index = -1
        for i, line in enumerate(cef_content):
            if line.strip().startswith("Conta Vinculada;"):
                header_line_index = i
                break
        if header_line_index != -1:
            data_io = io.StringIO("".join(cef_content[header_line_index:]))
            df_cef = pd.read_csv(data_io, sep=';')
            def extrair_chave_cef(texto_conta):
                if isinstance(texto_conta, str):
                    numeric_part = re.sub(r'\D', '', texto_conta)
                    if len(numeric_part) > 4: return numeric_part[4:]
                return None
            df_cef['Chave Primaria'] = df_cef['Conta Vinculada'].apply(extrair_chave_cef)
            # MUDANÇA: Renomeia 'Conta Vinculada' para 'Conta' e 'Nome' para 'Titular' para padronizar
            df_cef.rename(columns={'Conta Vinculada': 'Conta', 'Nome': 'Titular'}, inplace=True)
            extratos_encontrados.append(df_cef[['Conta', 'Titular', 'Chave Primaria']])
            st.info("Extrato da Caixa (.cef) processado.")
        else:
             st.warning("Cabeçalho 'Conta Vinculada;' não encontrado no arquivo CEF.")
    except FileNotFoundError:
        st.warning("Aviso: Extrato da CEF (.cef) não encontrado.")
    except Exception as e:
        st.error(f"Erro ao processar extrato CEF: {e}")

    if extratos_encontrados:
        df_extrato_unificado = pd.concat(extratos_encontrados, ignore_index=True)
        df_extrato_unificado.dropna(subset=['Chave Primaria'], inplace=True)
        st.dataframe(df_extrato_unificado)
        
        st.header("3. Análise de Correspondência")
        df_c = debug_contabil.copy()
        df_e = df_extrato_unificado.copy()
        df_c['Chave Primaria'] = df_c['Chave Primaria'].astype(str)
        df_e['Chave Primaria'] = df_e['Chave Primaria'].astype(str)
        
        chaves_comuns = pd.merge(df_c, df_e, on='Chave Primaria', how='inner', suffixes=('_contabil', '_extrato'))
        
        if chaves_comuns.empty:
            st.error("ANÁLISE: Nenhuma chave primária em comum foi encontrada.")
        else:
            st.success(f"ANÁLISE: Foram encontradas {len(chaves_comuns)} contas correspondentes!")
            st.dataframe(chaves_comuns)

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
            # Assumindo Junho 2025 para este teste
            mes_ano = "junho_2025"
            caminho_bb = f"extratos_consolidados/extrato_bb_{mes_ano}.xlsx"
            caminho_cef = f"extratos_consolidados/extrato_cef_{mes_ano}.cef"
            realizar_diagnostico(contabilidade_bruto, caminho_bb, caminho_cef)
