import json
import time
import requests
from config import RPC, client, payer_keypair
from constants import (
    OPEN_BOOK_PROGRAM, 
    RAY_AUTHORITY_V4, 
    RAY_V4, 
    TOKEN_PROGRAM_ID, 
    SOL
)
from layouts import (
    LIQUIDITY_STATE_LAYOUT_V4, 
    MARKET_STATE_LAYOUT_V3, 
    SWAP_LAYOUT
)
from solana.rpc.commitment import Processed
from solana.transaction import AccountMeta, Signature
from solders.instruction import Instruction  # type: ignore
from solders.keypair import Keypair  # type: ignore
from solders.pubkey import Pubkey  # type: ignore

def make_swap_instruction(amount_in:int, minimum_amount_out:int, token_account_in:Pubkey, token_account_out:Pubkey, accounts:dict, owner:Keypair) -> Instruction:
    try:
        keys = [
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=accounts["amm_id"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=RAY_AUTHORITY_V4, is_signer=False, is_writable=False),
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
                amount_in=amount_in,
                min_amount_out=minimum_amount_out
            )
        )
        return Instruction(RAY_V4, data, keys)
    except:
        return None

def fetch_pool_keys(pair_address: str) -> dict:
    try:
        amm_id = Pubkey.from_string(pair_address)
        amm_data = client.get_account_info_json_parsed(amm_id).value.data
        amm_data_decoded = LIQUIDITY_STATE_LAYOUT_V4.parse(amm_data)
        marketId = Pubkey.from_bytes(amm_data_decoded.serumMarket)
        marketInfo = client.get_account_info_json_parsed(marketId).value.data
        market_decoded = MARKET_STATE_LAYOUT_V3.parse(marketInfo)

        pool_keys = {
            "amm_id": amm_id, 
            "base_mint": Pubkey.from_bytes(market_decoded.base_mint), 
            "quote_mint": Pubkey.from_bytes(market_decoded.quote_mint), 
            "base_decimals": amm_data_decoded.coinDecimals, 
            "quote_decimals": amm_data_decoded.pcDecimals,
            "open_orders": Pubkey.from_bytes(amm_data_decoded.ammOpenOrders),
            "target_orders": Pubkey.from_bytes(amm_data_decoded.ammTargetOrders),
            "base_vault": Pubkey.from_bytes(amm_data_decoded.poolCoinTokenAccount),
            "quote_vault": Pubkey.from_bytes(amm_data_decoded.poolPcTokenAccount),
            "withdrawQueue": Pubkey.from_bytes(amm_data_decoded.poolWithdrawQueue),
            "market_id": marketId,
            "market_authority": Pubkey.create_program_address([bytes(marketId)] + [bytes([market_decoded.vault_signer_nonce])] + [bytes(7)], OPEN_BOOK_PROGRAM), 
            "market_base_vault": Pubkey.from_bytes(market_decoded.base_vault), 
            "market_quote_vault": Pubkey.from_bytes(market_decoded.quote_vault), 
            "bids": Pubkey.from_bytes(market_decoded.bids), 
            "asks": Pubkey.from_bytes(market_decoded.asks),
            "event_queue": Pubkey.from_bytes(market_decoded.event_queue)
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

def get_token_balance(mint_str: str):
    try:
        pubkey_str = str(payer_keypair.pubkey())
        headers = {"accept": "application/json", "content-type": "application/json"}

        payload = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "getTokenAccountsByOwner",
            "params": [
                pubkey_str,
                {"mint": mint_str},
                {"encoding": "jsonParsed"}
            ],
        }
        
        response = requests.post(RPC, json=payload, headers=headers)
        ui_amount = find_data(response.json(), "uiAmount")
        return float(ui_amount)
    except Exception as e:
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

def get_pair_address(mint: str):
    url = f"https://api-v3.raydium.io/pools/info/mint?mint1={mint}&poolType=all&poolSortField=default&sortType=desc&pageSize=1&page=1"
    try:
        response = requests.get(url)
        response.raise_for_status() 
        return response.json()['data']['data'][0]['id']
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None

def get_token_price(pool_keys: dict) -> tuple:
    try:
        # Get vault accounts and decimals
        base_vault = pool_keys["base_vault"]
        quote_vault = pool_keys["quote_vault"]
        base_decimal = pool_keys["base_decimals"]
        quote_decimal = pool_keys["quote_decimals"]
        base_mint = pool_keys["base_mint"]
        
        # Fetch both token account balances
        balances_response = client.get_multiple_accounts_json_parsed(
            [base_vault, quote_vault], 
            Processed
        )
        balances = balances_response.value

        # Extract and parse the balances from the JSON-parsed response data
        pool_coin_account = balances[0]
        pool_pc_account = balances[1]

        pool_coin_account_balance = pool_coin_account.data.parsed['info']['tokenAmount']['uiAmount']
        pool_pc_account_balance = pool_pc_account.data.parsed['info']['tokenAmount']['uiAmount']

        # If either balance could not be retrieved, return None
        if pool_coin_account_balance is None or pool_pc_account_balance is None:
            return None, None
        
        # Determine which reserves to use based on whether the coin is SOL or another token
        sol_mint_address = Pubkey.from_string(SOL)
        
        if base_mint == sol_mint_address:
            base_reserve = pool_coin_account_balance
            quote_reserve = pool_pc_account_balance
            token_decimal = quote_decimal
        else:
            base_reserve = pool_pc_account_balance
            quote_reserve = pool_coin_account_balance
            token_decimal = base_decimal
        
        # Calculate the token price based on the reserves
        token_price = base_reserve / quote_reserve
        
        # Output the calculated token price and the decimal places of the token
        print(f"Token Price: {token_price:.20f} SOL | Token Decimal: {token_decimal}")

        # Return the token price and its decimal places as a tuple
        return token_price, token_decimal

    except Exception as e:
        # Handle any exceptions that occur during execution and return None
        print(f"Error occurred: {e}")
        return None, None   
