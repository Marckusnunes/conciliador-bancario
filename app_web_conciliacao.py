def processar_extrato_bb_bruto_csv(caminho_arquivo):
    """
    Lê e transforma o arquivo .csv bruto do Banco do Brasil.
    """
    df = pd.read_csv(caminho_arquivo, sep=',', encoding='latin-1', dtype=str)
    df.rename(columns={
        'Saldo em conta': 'Saldo_Corrente_Extrato',
        'Saldo investido': 'Saldo_Aplicado_Extrato'
        # Adicione outros renames aqui se necessário, como para 'Saldo total'
    }, inplace=True)
    df['Chave Primaria'] = df['Conta'].apply(gerar_chave_padronizada)
    
    # Adiciona a coluna de agência como vazia para manter compatibilidade com o extrato da CEF.
    df['Agencia_Extrato'] = None
    
    # --- INÍCIO DO BLOCO MODIFICADO ---
    # Documentação: Converte as colunas de saldo para formato numérico.
    # Esta lógica remove todos os caracteres não-numéricos do valor em texto
    # e divide o resultado por 1000, conforme a necessidade do formato de origem do arquivo.
    for col in ['Saldo_Corrente_Extrato', 'Saldo_Aplicado_Extrato', 'Saldo total']:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(r'\D', '', regex=True), # Remove tudo que não for dígito
                errors='coerce'
            ).fillna(0) / 1000
    # --- FIM DO BLOCO MODIFICADO ---
            
    if 'Saldo_Corrente_Extrato' not in df.columns:
        df['Saldo_Corrente_Extrato'] = 0
    if 'Saldo_Aplicado_Extrato' not in df.columns:
        df['Saldo_Aplicado_Extrato'] = 0
            
    return df
