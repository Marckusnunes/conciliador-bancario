def processar_extrato_cef_bruto(caminho_arquivo):
    """
    Lê o arquivo .cef da Caixa e extrai o prefixo de banco/agência.
    Esta versão é mais robusta e lida com variações no nome da coluna da conta.
    """
    with open(caminho_arquivo, 'r', encoding='latin-1') as f:
        cef_content = f.readlines()
        
    header_line_index = -1
    # Documentação: Procura pela linha de cabeçalho no arquivo.
    # Esta busca foi aprimorada para aceitar as duas possíveis nomenclaturas.
    for i, line in enumerate(cef_content):
        if line.strip().startswith("Conta Vinculada;") or line.strip().startswith("Nome Conta Vinculada;"):
            header_line_index = i
            break
            
    if header_line_index == -1:
        st.error("Erro no arquivo da CEF: Não foi possível encontrar a linha de cabeçalho ('Conta Vinculada;' ou 'Nome Conta Vinculada;').")
        return pd.DataFrame()

    data_io = io.StringIO("".join(cef_content[header_line_index:]))
    df = pd.read_csv(data_io, sep=';', dtype=str)
    
    # --- LÓGICA DE CORREÇÃO ---
    # Documentação: Identifica dinamicamente o nome correto da coluna de conta.
    # O programa verifica qual dos nomes ('Conta Vinculada' ou 'Nome Conta Vinculada') existe
    # no arquivo carregado.
    nome_coluna_conta = None
    if 'Conta Vinculada' in df.columns:
        nome_coluna_conta = 'Conta Vinculada'
    elif 'Nome Conta Vinculada' in df.columns:
        nome_coluna_conta = 'Nome Conta Vinculada'
    
    # Documentação: Se nenhuma das colunas esperadas for encontrada, o programa para e notifica o usuário.
    if nome_coluna_conta is None:
        st.error("Erro no arquivo da CEF: Não foi possível encontrar a coluna de identificação da conta ('Conta Vinculada' ou 'Nome Conta Vinculada').")
        return pd.DataFrame()

    # Documentação: A partir daqui, o código usa a variável 'nome_coluna_conta' para garantir que está
    # acessando a coluna correta, independentemente do nome exato no arquivo.
    df['Chave Primaria'] = df[nome_coluna_conta].apply(gerar_chave_padronizada)
    df['Agencia_Extrato'] = df[nome_coluna_conta].str[:9]
    
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
