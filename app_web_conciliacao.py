def realizar_conciliacao(df_contabil, df_extrato_unificado):
    df_contabil_pivot = df_contabil[['Chave Primaria', 'Domicílio bancário', 'Saldo_Corrente_Contabil', 'Saldo_Aplicado_Contabil']]
    df_extrato_pivot = df_extrato_unificado.groupby('Chave Primaria').agg({
        'Saldo_Corrente_Extrato': 'sum',
        'Saldo_Aplicado_Extrato': 'sum'
    }).reset_index()
    
    df_contabil_pivot['Chave Primaria'] = df_contabil_pivot['Chave Primaria'].astype(str)
    df_extrato_pivot['Chave Primaria'] = df_extrato_pivot['Chave Primaria'].astype(str)

    df_final = pd.merge(df_contabil_pivot, df_extrato_pivot, on='Chave Primaria', how='outer')

    if df_final.empty:
        return pd.DataFrame()

    saldos_cols = ['Saldo_Corrente_Contabil', 'Saldo_Aplicado_Contabil', 'Saldo_Corrente_Extrato', 'Saldo_Aplicado_Extrato']
    for col in saldos_cols:
        if col not in df_final.columns:
            df_final[col] = 0
        df_final[col].fillna(0, inplace=True)

    # --- INÍCIO DA CORREÇÃO ---
    # Usando um método seguro para preencher os nomes das contas faltantes
    mask = df_final['Domicílio bancário'].isnull()
    df_final.loc[mask, 'Domicílio bancário'] = "[Conta Apenas no Extrato: Chave " + df_final.loc[mask, 'Chave Primaria'] + "]"
    # --- FIM DA CORREÇÃO ---
    
    df_final.rename(columns={'Domicílio bancário': 'Conta Bancária'}, inplace=True)

    df_final['Diferenca_Movimento'] = df_final['Saldo_Corrente_Contabil'] - df_final['Saldo_Corrente_Extrato']
    df_final['Diferenca_Aplicacao'] = df_final['Saldo_Aplicado_Contabil'] - df_final['Saldo_Aplicado_Extrato']

    df_final = df_final.set_index('Conta Bancária')
    
    df_final = df_final[['Saldo_Corrente_Contabil', 'Saldo_Corrente_Extrato', 'Diferenca_Movimento', 'Saldo_Aplicado_Contabil', 'Saldo_Aplicado_Extrato', 'Diferenca_Aplicacao']]
    df_final.columns = pd.MultiIndex.from_tuples([
        ('Conta Movimento', 'Saldo Contábil'), ('Conta Movimento', 'Saldo Extrato'), ('Conta Movimento', 'Diferença'),
        ('Aplicação Financeira', 'Saldo Contábil'), ('Aplicação Financeira', 'Saldo Extrato'), ('Aplicação Financeira', 'Diferença')
    ], names=['Grupo', 'Item'])
    
    return df_final
