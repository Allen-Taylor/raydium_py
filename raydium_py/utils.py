import json
import time
import threading
import requests
from config import RPC, PUB_KEY, client
from constants import OPEN_BOOK_PROGRAM, RAY_AUTHORITY_V4, RAY_V4, TOKEN_PROGRAM_ID, WSOL
from layouts import LIQUIDITY_STATE_LAYOUT_V4, MARKET_STATE_LAYOUT_V3, SWAP_LAYOUT, OPEN_ORDERS_LAYOUT
from solana.rpc.types import TokenAccountOpts
from solana.transaction import AccountMeta, Signature
from solders.instruction import Instruction  # type: ignore
from solders.pubkey import Pubkey  # type: ignore
from spl.token.instructions import create_associated_token_account, get_associated_token_address
from solana.rpc.types import TokenAccountOpts, MemcmpOpts

def make_swap_instruction(amount_in: int, token_account_in: Pubkey, token_account_out: Pubkey, accounts: dict, owner: Pubkey) -> Instruction:
    try:
        keys = [
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=accounts["amm_id"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts["authority"], is_signer=False, is_writable=False),
            AccountMeta(pubkey=accounts["open_orders"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts["target_orders"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts["base_vault"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts["quote_vault"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=OPEN_BOOK_PROGRAM, is_signer=False, is_writable=False), 
            AccountMeta(pubkey=accounts["market_id"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts["bids"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts["asks"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts["event_queue"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts["market_base_vault"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts["market_quote_vault"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts["market_authority"], is_signer=False, is_writable=False),
            AccountMeta(pubkey=token_account_in, is_signer=False, is_writable=True),  
            AccountMeta(pubkey=token_account_out, is_signer=False, is_writable=True), 
            AccountMeta(pubkey=owner.pubkey(), is_signer=True, is_writable=False) 
        ]
        
        data = SWAP_LAYOUT.build(
            dict(
                instruction=9,
                amount_in=int(amount_in),
                min_amount_out=0
            )
        )
        return Instruction(RAY_V4, data, keys)
    except:
        return None

def get_token_account(owner: Pubkey, mint: Pubkey):
    try:
        account_data = client.get_token_accounts_by_owner(owner, TokenAccountOpts(mint))
        token_account = account_data.value[0].pubkey
        token_account_instructions = None
        return token_account, token_account_instructions
    except:
        token_account = get_associated_token_address(owner, mint)
        token_account_instructions = create_associated_token_account(owner, owner, mint)
        return token_account, token_account_instructions

def fetch_pool_keys(pair_address: str) -> dict:
    try:
        amm_id = Pubkey.from_string(pair_address)
        amm_data = client.get_account_info_json_parsed(amm_id).value.data
        amm_data_decoded = LIQUIDITY_STATE_LAYOUT_V4.parse(amm_data)
        OPEN_BOOK_PROGRAM = Pubkey.from_bytes(amm_data_decoded.serumProgramId)
        marketId = Pubkey.from_bytes(amm_data_decoded.serumMarket)
        marketInfo = client.get_account_info_json_parsed(marketId).value.data
        market_decoded = MARKET_STATE_LAYOUT_V3.parse(marketInfo)

        pool_keys = {
            "amm_id": amm_id,
            "base_mint": Pubkey.from_bytes(market_decoded.base_mint),
            "quote_mint": Pubkey.from_bytes(market_decoded.quote_mint),
            "lp_mint": Pubkey.from_bytes(amm_data_decoded.lpMintAddress),
            "version": 4,
            "base_decimals": amm_data_decoded.coinDecimals,
            "quote_decimals": amm_data_decoded.pcDecimals,
            "lpDecimals": amm_data_decoded.coinDecimals,
            "programId": RAY_V4,
            "authority": RAY_AUTHORITY_V4,
            "open_orders": Pubkey.from_bytes(amm_data_decoded.ammOpenOrders),
            "target_orders": Pubkey.from_bytes(amm_data_decoded.ammTargetOrders),
            "base_vault": Pubkey.from_bytes(amm_data_decoded.poolCoinTokenAccount),
            "quote_vault": Pubkey.from_bytes(amm_data_decoded.poolPcTokenAccount),
            "withdrawQueue": Pubkey.from_bytes(amm_data_decoded.poolWithdrawQueue),
            "lpVault": Pubkey.from_bytes(amm_data_decoded.poolTempLpTokenAccount),
            "marketProgramId": OPEN_BOOK_PROGRAM,
            "market_id": marketId,
            "market_authority": Pubkey.create_program_address(
                [bytes(marketId)]
                + [bytes([market_decoded.vault_signer_nonce])]
                + [bytes(7)],
                OPEN_BOOK_PROGRAM,
            ),
            "market_base_vault": Pubkey.from_bytes(market_decoded.base_vault),
            "market_quote_vault": Pubkey.from_bytes(market_decoded.quote_vault),
            "bids": Pubkey.from_bytes(market_decoded.bids),
            "asks": Pubkey.from_bytes(market_decoded.asks),
            "event_queue": Pubkey.from_bytes(market_decoded.event_queue),
            "pool_open_time": amm_data_decoded.poolOpenTime
        }
        
        return pool_keys
    except:
        return None
    
def find_data(data: dict, field: str) -> str:
    if isinstance(data, dict):
        if field in data:
            return data[field]
        else:
            for value in data.values():
                result = find_data(value, field)
                if result is not None:
                    return result
    elif isinstance(data, list):
        for item in data:
            result = find_data(item, field)
            if result is not None:
                return result
    return None

def get_token_balance(token_address: str) -> float:
    try:

        headers = {"accept": "application/json", "content-type": "application/json"}

        payload = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "getTokenAccountsByOwner",
            "params": [
                PUB_KEY,
                {"mint": token_address},
                {"encoding": "jsonParsed"},
            ],
        }
        
        response = requests.post(RPC, json=payload, headers=headers)
        ui_amount = find_data(response.json(), "uiAmount")
        return float(ui_amount)
    except:
        return None

def get_token_balance_lamports(token_address: str) -> int:
    try:

        headers = {"accept": "application/json", "content-type": "application/json"}

        payload = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "getTokenAccountsByOwner",
            "params": [
                PUB_KEY,
                {"mint": token_address},
                {"encoding": "jsonParsed"},
            ],
        }
        
        response = requests.post(RPC, json=payload, headers=headers)
        amount = find_data(response.json(), "amount")
        return int(amount)
    except:
        return None

def confirm_txn(txn_sig: Signature, max_retries: int = 20, retry_interval: int = 3) -> bool:
    retries = 0
    
    while retries < max_retries:
        try:
            txn_res = client.get_transaction(txn_sig, encoding="json", commitment="confirmed", max_supported_transaction_version=0)
            txn_json = json.loads(txn_res.value.transaction.meta.to_json())
            
            if txn_json['err'] is None:
                print("Transaction confirmed... try count:", retries)
                return True
            
            print("Error: Transaction not confirmed. Retrying...")
            if txn_json['err']:
                print("Transaction failed.")
                return False
        except Exception as e:
            print("Awaiting confirmation... try count:", retries)
            retries += 1
            time.sleep(retry_interval)
    
    print("Max retries reached. Transaction confirmation failed.")
    return None

def get_pair_address_from_rpc(token_address: str) -> str:
    BASE_OFFSET = 400
    QUOTE_OFFSET = 432
    DATA_LENGTH_FILTER = 752
    QUOTE_MINT = "So11111111111111111111111111111111111111112"
    RAYDIUM_PROGRAM_ID = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
    
    def fetch_amm_id(base_mint: str, quote_mint: str) -> str:
        memcmp_filter_base = MemcmpOpts(offset=BASE_OFFSET, bytes=base_mint)
        memcmp_filter_quote = MemcmpOpts(offset=QUOTE_OFFSET, bytes=quote_mint)
        try:
            response = client.get_program_accounts(
                RAYDIUM_PROGRAM_ID, 
                filters=[DATA_LENGTH_FILTER, memcmp_filter_base, memcmp_filter_quote]
            )
            accounts = response.value
            if accounts:
                return str(accounts[0].pubkey)
        except Exception as e:
            print(f"Error fetching AMM ID: {e}")
        return None

    # First attempt: base_mint at BASE_OFFSET, QUOTE_MINT at QUOTE_OFFSET
    pair_address = fetch_amm_id(token_address, QUOTE_MINT)
    
    # Second attempt: QUOTE_MINT at BASE_OFFSET, base_mint at QUOTE_OFFSET
    if not pair_address:
        pair_address = fetch_amm_id(QUOTE_MINT, token_address)
    
    return pair_address

def get_pair_address(token_address) -> str:
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_address}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site"
    }

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()['pairs'][0]['pairAddress']
    else:
        return None

def get_token_price(pair_address: str) -> float:
    try:
        # Get AMM data and parse
        amm_pubkey = Pubkey.from_string(pair_address)
        amm_data = client.get_account_info(amm_pubkey).value.data
        liquidity_state = LIQUIDITY_STATE_LAYOUT_V4.parse(amm_data)
        
        # Extract relevant attributes with improved names
        amm_open_orders_pubkey = liquidity_state.ammOpenOrders
        pool_coin_token_account_pubkey = liquidity_state.poolCoinTokenAccount
        pool_pc_token_account_pubkey = liquidity_state.poolPcTokenAccount
        coin_decimals = liquidity_state.coinDecimals
        pc_decimals = liquidity_state.pcDecimals
        coin_mint_address = liquidity_state.coinMintAddress
         
        need_take_pnl_coin = liquidity_state.needTakePnlCoin
        need_take_pnl_pc = liquidity_state.needTakePnlPc

        # Create a dictionary to store fetched data
        fetched_data = {}
        try:
            # Create threads for fetching account info and token balances
            account_info_thread = threading.Thread(target=lambda: fetched_data.update({'open_orders_data': client.get_account_info(Pubkey.from_bytes(amm_open_orders_pubkey)).value.data}))
            base_balance_thread = threading.Thread(target=lambda: fetched_data.update({pool_coin_token_account_pubkey: client.get_token_account_balance(Pubkey.from_bytes(pool_coin_token_account_pubkey)).value.ui_amount}))
            quote_balance_thread = threading.Thread(target=lambda: fetched_data.update({pool_pc_token_account_pubkey: client.get_token_account_balance(Pubkey.from_bytes(pool_pc_token_account_pubkey)).value.ui_amount}))

            # Start threads
            account_info_thread.start()
            base_balance_thread.start()
            quote_balance_thread.start()

            # Wait for threads to complete
            account_info_thread.join()
            base_balance_thread.join()
            quote_balance_thread.join()
        except:
            return

        # Parse fetched data
        open_orders_data = fetched_data['open_orders_data']
        open_orders = OPEN_ORDERS_LAYOUT.parse(open_orders_data)
        base_token_total = open_orders.base_token_total
        quote_token_total = open_orders.quote_token_total
        
        # Get decimal factors
        base_decimal = 10 ** coin_decimals
        quote_decimal = 10 ** pc_decimals

        # Calculate PnL
        base_pnl = need_take_pnl_coin / base_decimal
        quote_pnl = need_take_pnl_pc / quote_decimal

        # Calculate token totals from open orders
        open_orders_base_token_total = base_token_total / base_decimal
        open_orders_quote_token_total = quote_token_total/ quote_decimal

        # Get token balances from fetched data
        base_token_amount = fetched_data[pool_coin_token_account_pubkey]
        quote_token_amount = fetched_data[pool_pc_token_account_pubkey]

        # Calculate total token amounts
        base = (base_token_amount or 0) + open_orders_base_token_total - base_pnl
        quote = (quote_token_amount or 0) + open_orders_quote_token_total - quote_pnl

        # Determine price in SOL
        price_in_sol = 0
        if Pubkey.from_bytes(coin_mint_address) == WSOL:
            price_in_sol = str(base / quote)
        else:
            price_in_sol = str(quote / base)

        return float(price_in_sol)

    except:
        return None