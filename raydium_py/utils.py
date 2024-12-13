import json
import struct
import time
from dataclasses import dataclass
from typing import Optional
import requests
from solana.rpc.commitment import Confirmed, Processed
from solana.rpc.types import MemcmpOpts, TokenAccountOpts
from solana.transaction import AccountMeta, Signature
from solders.instruction import Instruction  # type: ignore
from solders.keypair import Keypair  # type: ignore
from solders.pubkey import Pubkey  # type: ignore
from config import client, payer_keypair
from constants import (
    OPEN_BOOK_PROGRAM,
    RAY_AUTHORITY_V4,
    RAY_V4,
    TOKEN_PROGRAM_ID,
    WSOL,
)
from layouts import (
    LIQUIDITY_STATE_LAYOUT_V4,
    MARKET_STATE_LAYOUT_V3,
    SWAP_LAYOUT,
)

@dataclass
class PoolKeys:
    amm_id: Pubkey
    base_mint: Pubkey
    quote_mint: Pubkey
    base_decimals: int
    quote_decimals: int
    open_orders: Pubkey
    target_orders: Pubkey
    base_vault: Pubkey
    quote_vault: Pubkey
    market_id: Pubkey
    market_authority: Pubkey
    market_base_vault: Pubkey
    market_quote_vault: Pubkey
    bids: Pubkey
    asks: Pubkey
    event_queue: Pubkey

def fetch_pool_keys(pair_address: str) -> Optional[PoolKeys]:
    try:
        amm_id = Pubkey.from_string(pair_address)
        amm_data = client.get_account_info_json_parsed(amm_id, commitment=Processed).value.data
        amm_data_decoded = LIQUIDITY_STATE_LAYOUT_V4.parse(amm_data)
        marketId = Pubkey.from_bytes(amm_data_decoded.serumMarket)
        marketInfo = client.get_account_info_json_parsed(marketId, commitment=Processed).value.data
        market_decoded = MARKET_STATE_LAYOUT_V3.parse(marketInfo)
        vault_signer_nonce = market_decoded.vault_signer_nonce

        pool_keys = PoolKeys(
            amm_id=amm_id,
            base_mint=Pubkey.from_bytes(market_decoded.base_mint),
            quote_mint=Pubkey.from_bytes(market_decoded.quote_mint),
            base_decimals=amm_data_decoded.coinDecimals,
            quote_decimals=amm_data_decoded.pcDecimals,
            open_orders=Pubkey.from_bytes(amm_data_decoded.ammOpenOrders),
            target_orders=Pubkey.from_bytes(amm_data_decoded.ammTargetOrders),
            base_vault=Pubkey.from_bytes(amm_data_decoded.poolCoinTokenAccount),
            quote_vault=Pubkey.from_bytes(amm_data_decoded.poolPcTokenAccount),
            market_id=marketId,
            market_authority=Pubkey.create_program_address( 
                [bytes(marketId), bytes_of(vault_signer_nonce)],
                OPEN_BOOK_PROGRAM,
            ),
            market_base_vault=Pubkey.from_bytes(market_decoded.base_vault),
            market_quote_vault=Pubkey.from_bytes(market_decoded.quote_vault),
            bids=Pubkey.from_bytes(market_decoded.bids),
            asks=Pubkey.from_bytes(market_decoded.asks),
            event_queue=Pubkey.from_bytes(market_decoded.event_queue),
        )

        return pool_keys
    except Exception as e:
        print(f"Error fetching pool keys: {e}")
        return None

def bytes_of(value):
    if not (0 <= value < 2**64):
        raise ValueError("Value must be in the range of a u64 (0 to 2^64 - 1).")
    return struct.pack('<Q', value)

def get_pair_address_from_api(mint):
    url = f"https://api-v3.raydium.io/pools/info/mint?mint1={mint}&poolType=all&poolSortField=default&sortType=desc&pageSize=1&page=1"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        pools = data.get('data', {}).get('data', [])
        if not pools:
            return None

        pool = pools[0]
        program_id = pool.get('programId')
        if program_id == "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": # AMM v4 Program 
            pair_address = pool.get('id')
            return pair_address

        return None
    except:
        return None

def get_pair_address_from_rpc(token_address: str) -> str:
    print("Getting pair address from RPC...")
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
                commitment=Processed, 
                filters=[DATA_LENGTH_FILTER, memcmp_filter_base, memcmp_filter_quote]
            )
            accounts = response.value
            if accounts:
                return str(accounts[0].pubkey)
        except Exception as e:
            print(f"Error fetching AMM ID: {e}")
        return None

    pair_address = fetch_amm_id(token_address, QUOTE_MINT)
    
    if not pair_address:
        pair_address = fetch_amm_id(QUOTE_MINT, token_address)
    
    return pair_address

def make_swap_instruction(
    amount_in: int, 
    minimum_amount_out: int, 
    token_account_in: Pubkey, 
    token_account_out: Pubkey, 
    accounts: PoolKeys,
    owner: Keypair
) -> Instruction:
    try:
        keys = [
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=accounts.amm_id, is_signer=False, is_writable=True),
            AccountMeta(pubkey=RAY_AUTHORITY_V4, is_signer=False, is_writable=False),
            AccountMeta(pubkey=accounts.open_orders, is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts.target_orders, is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts.base_vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts.quote_vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=OPEN_BOOK_PROGRAM, is_signer=False, is_writable=False), 
            AccountMeta(pubkey=accounts.market_id, is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts.bids, is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts.asks, is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts.event_queue, is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts.market_base_vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts.market_quote_vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=accounts.market_authority, is_signer=False, is_writable=False),
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
    except Exception as e:
        print(f"Error occurred: {e}")
        return None

def get_token_balance(mint_str: str) -> float | None:
    try:
        mint = Pubkey.from_string(mint_str)
        response = client.get_token_accounts_by_owner_json_parsed(
            payer_keypair.pubkey(),
            TokenAccountOpts(mint=mint),
            commitment=Processed
        )

        accounts = response.value
        if accounts:
            token_amount = accounts[0].account.data.parsed['info']['tokenAmount']['uiAmount']
            if token_amount:
                return float(token_amount)
        return None
    except Exception as e:
        print(f"Error fetching token balance: {e}")
        return None
    
def confirm_txn(txn_sig: Signature, max_retries: int = 20, retry_interval: int = 3) -> bool:
    retries = 1
    
    while retries < max_retries:
        try:
            txn_res = client.get_transaction(txn_sig, encoding="json", commitment=Confirmed, max_supported_transaction_version=0)
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

def get_token_reserves(pool_keys: PoolKeys) -> tuple:
    try:
        base_vault = pool_keys.base_vault
        quote_vault = pool_keys.quote_vault
        base_decimal = pool_keys.base_decimals
        quote_decimal = pool_keys.quote_decimals
        base_mint = pool_keys.base_mint
        quote_mint = pool_keys.quote_mint
        
        balances_response = client.get_multiple_accounts_json_parsed(
            [base_vault, quote_vault], 
            Processed
        )
        balances = balances_response.value

        token_account = balances[0]
        sol_account = balances[1]
        
        token_account_balance = token_account.data.parsed['info']['tokenAmount']['uiAmount']
        sol_account_balance = sol_account.data.parsed['info']['tokenAmount']['uiAmount']

        if token_account_balance is None or sol_account_balance is None:
            return None, None
        
        # Determine the assignment of base and quote reserves based on the base mint
        if base_mint == WSOL:
            base_reserve = sol_account_balance  # SOL is the base
            quote_reserve = token_account_balance  # Tokens are the quote
            token_decimal = quote_decimal
        else:
            base_reserve = token_account_balance  # Tokens are the base
            quote_reserve = sol_account_balance  # SOL is the quote
            token_decimal = base_decimal

        print(f"Base Mint: {base_mint} | Quote Mint: {quote_mint}")
        print(f"Base Reserve: {base_reserve} | Quote Reserve: {quote_reserve} | Token Decimal: {token_decimal}")
        return base_reserve, quote_reserve, token_decimal

    except Exception as e:
        print(f"Error occurred: {e}")
        return None, None, None

def sol_for_tokens(spend_sol_amount, base_vault_balance, quote_vault_balance, swap_fee=0.25):
    effective_sol_used = spend_sol_amount - (spend_sol_amount * (swap_fee / 100))
    constant_product = base_vault_balance * quote_vault_balance
    updated_base_vault_balance = constant_product / (quote_vault_balance + effective_sol_used)
    tokens_received = base_vault_balance - updated_base_vault_balance
    return round(tokens_received, 9)

def tokens_for_sol(sell_token_amount, base_vault_balance, quote_vault_balance, swap_fee=0.25):
    effective_tokens_sold = sell_token_amount * (1 - (swap_fee / 100))
    constant_product = base_vault_balance * quote_vault_balance
    updated_quote_vault_balance = constant_product / (base_vault_balance + effective_tokens_sold)
    sol_received = quote_vault_balance - updated_quote_vault_balance
    return round(sol_received, 9)
