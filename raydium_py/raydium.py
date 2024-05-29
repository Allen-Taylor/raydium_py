from solana.rpc.types import TokenAccountOpts, TxOpts
from solana.rpc.types import TxOpts
import solders.system_program as system_program
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price #type: ignore
from solders.keypair import Keypair #type: ignore
from solders.transaction import VersionedTransaction #type: ignore
from solders.message import MessageV0 #type: ignore
from spl.token.client import Token
from spl.token.constants import WRAPPED_SOL_MINT
from spl.token.instructions import close_account, CloseAccountParams
import spl.token.instructions as spl_token_instructions
from config import client, payer_keypair
from constants import LAMPORTS_PER_SOL, UNIT_BUDGET, UNIT_PRICE, WSOL, SOL, TOKEN_PROGRAM_ID
from layouts import ACCOUNT_LAYOUT
from utils import fetch_pool_keys, make_swap_instruction, get_token_account, confirm_txn

def buy(pair_address: str, amount_in_sol: float):

    # Fetch pool keys
    print("Fetching pool keys...")
    pool_keys = fetch_pool_keys(pair_address)
    
    # Check if pool keys exist
    if pool_keys is None:
        print("No pools keys found...")
        return None

    # Determine the mint based on pool keys
    mint = pool_keys['base_mint'] if str(pool_keys['base_mint']) != SOL else pool_keys['quote_mint']
    amount_in = int(amount_in_sol * LAMPORTS_PER_SOL)

    # Get token account and token account instructions
    print("Getting token account...")
    token_account, token_account_instructions = get_token_account(payer_keypair.pubkey(), mint)

    # Get minimum balance needed for token account
    print("Getting minimum balance for token account...")
    balance_needed = Token.get_min_balance_rent_for_exempt_for_account(client)

    # Create a keypair for wrapped SOL (wSOL)
    print("Creating keypair for wSOL...")
    wsol_account_keypair = Keypair()
    wsol_token_account = wsol_account_keypair.pubkey()
    
    instructions = []

    # Create instructions to create a wSOL account, include the amount in 
    print("Creating wSOL account instructions...")
    create_wsol_account_instructions = system_program.create_account(
        system_program.CreateAccountParams(
            from_pubkey=payer_keypair.pubkey(),
            to_pubkey=wsol_account_keypair.pubkey(),
            lamports=int(balance_needed + amount_in),
            space=ACCOUNT_LAYOUT.sizeof(),
            owner=TOKEN_PROGRAM_ID,
        )
    )

    # Initialize wSOL account
    print("Initializing wSOL account...")
    init_wsol_account_instructions = spl_token_instructions.initialize_account(
        spl_token_instructions.InitializeAccountParams(
            account=wsol_account_keypair.pubkey(),
            mint=WSOL,
            owner=payer_keypair.pubkey(),
            program_id=TOKEN_PROGRAM_ID,
        )
    )

    # Create swap instructions
    print("Creating swap instructions...")
    swap_instructions = make_swap_instruction(amount_in, wsol_token_account, token_account, pool_keys, payer_keypair)

    # Create close account instructions for wSOL account
    print("Creating close account instructions...")
    close_account_instructions = close_account(CloseAccountParams(TOKEN_PROGRAM_ID, wsol_token_account, payer_keypair.pubkey(), payer_keypair.pubkey()))

    # Append instructions to the list
    print("Appending instructions...")
    instructions.append(set_compute_unit_limit(UNIT_BUDGET)) 
    instructions.append(set_compute_unit_price(UNIT_PRICE))
    instructions.append(create_wsol_account_instructions)
    instructions.append(init_wsol_account_instructions)
    if token_account_instructions:
        instructions.append(token_account_instructions)
    instructions.append(swap_instructions)
    instructions.append(close_account_instructions)

    # Compile the message
    print("Compiling message...")
    compiled_message = MessageV0.try_compile(
        payer_keypair.pubkey(),
        instructions,
        [],  
        client.get_latest_blockhash().value.blockhash,
    )

    # Create and send transaction
    print("Creating and sending transaction...")
    transaction = VersionedTransaction(compiled_message, [payer_keypair, wsol_account_keypair])
    txn_sig = client.send_transaction(transaction, opts=TxOpts(skip_preflight=True, preflight_commitment="confirmed")).value
    print("Transaction Signature:", txn_sig)
    
    # Confirm transaction
    print("Confirming transaction...")
    confirm = confirm_txn(txn_sig)
    print(confirm)

def sell(pair_address: str, amount_in_lamports: int):

    # Convert amount to integer
    amount_in = int(amount_in_lamports)
    
    # Fetch pool keys
    print("Fetching pool keys...")
    pool_keys = fetch_pool_keys(pair_address)
    
    # Check if pool keys exist
    if pool_keys is None:
        print("No pools keys found...")
        return None
        
    # Determine the mint based on pool keys
    mint = pool_keys['base_mint'] if str(pool_keys['base_mint']) != SOL else pool_keys['quote_mint']
    
    # Get token account
    print("Getting token account...")
    token_account = client.get_token_accounts_by_owner(payer_keypair.pubkey(), TokenAccountOpts(mint)).value[0].pubkey
    
    # Get wSOL token account and instructions
    print("Getting wSOL token account...")
    wsol_token_account, wsol_token_account_instructions = get_token_account(payer_keypair.pubkey(), WRAPPED_SOL_MINT)
    
    # Create swap instructions
    print("Creating swap instructions...")
    swap_instructions = make_swap_instruction(amount_in, token_account, wsol_token_account, pool_keys, payer_keypair)
    
    # Create close account instructions for wSOL account
    print("Creating close account instructions...")
    close_account_instructions = close_account(CloseAccountParams(TOKEN_PROGRAM_ID, wsol_token_account, payer_keypair.pubkey(), payer_keypair.pubkey()))

    # Initialize instructions list
    instructions = []
    print("Appending instructions...")
    instructions.append(set_compute_unit_limit(UNIT_BUDGET)) 
    instructions.append(set_compute_unit_price(UNIT_PRICE))
    if wsol_token_account_instructions:
        instructions.append(wsol_token_account_instructions)
    instructions.append(swap_instructions)
    instructions.append(close_account_instructions)
    
    # Compile the message
    print("Compiling message...")
    compiled_message = MessageV0.try_compile(
        payer_keypair.pubkey(),
        instructions,
        [],  
        client.get_latest_blockhash().value.blockhash,
    )

    # Create and send transaction
    print("Creating and sending transaction...")
    transaction = VersionedTransaction(compiled_message, [payer_keypair])
    txn_sig = client.send_transaction(transaction, opts=TxOpts(skip_preflight=True, preflight_commitment="confirmed")).value
    print("Transaction Signature:", txn_sig)
    
    # Confirm transaction
    print("Confirming transaction...")
    confirm = confirm_txn(txn_sig)
    print(confirm)
