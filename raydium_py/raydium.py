from solana.rpc.commitment import Processed
from solana.rpc.types import TokenAccountOpts, TxOpts
from solana.transaction import Transaction
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price  # type: ignore
from solders.keypair import Keypair  # type: ignore
from solders.system_program import CreateAccountParams, TransferParams, create_account, transfer
from spl.token.instructions import sync_native
from spl.token.client import Token
from spl.token.instructions import (
    InitializeAccountParams,
    create_associated_token_account,
    get_associated_token_address,
    initialize_account,
    sync_native,
    SyncNativeParams,
    close_account, 
    CloseAccountParams
)
from config import client, payer_keypair
from constants import SOL_DECIMAL, SOL, TOKEN_PROGRAM_ID, UNIT_BUDGET, UNIT_PRICE, WSOL
from layouts import ACCOUNT_LAYOUT
from utils import confirm_txn, fetch_pool_keys, get_token_price, make_swap_instruction, get_token_balance

def buy(pair_address:str, sol_in:float=.01, slippage:int=5) -> bool:
    try:
        print(f"Pair Address: {pair_address}")
        
        # Step 1: Fetch the pool keys 
        print("Fetching pool keys...")
        pool_keys = fetch_pool_keys(pair_address)

        if pool_keys is None:
            print("No pools keys found...")
            return False

        # Step 2: Determine the mint (sometimes base/quote are swapped)
        mint = pool_keys['base_mint'] if str(pool_keys['base_mint']) != SOL else pool_keys['quote_mint']
        
        # Step 3: Calculate the amount_in and minimum_amount_out
        amount_in = int(sol_in * SOL_DECIMAL)
        token_price, token_decimal = get_token_price(pool_keys)
        amount_out = float(sol_in) / float(token_price)
        slippage_adjustment = 1 - (slippage / 100)
        amount_out_with_slippage = amount_out * slippage_adjustment
        minimum_amount_out = int(amount_out_with_slippage * 10**token_decimal)
        print(f"Amount In: {amount_in} | Min Amount Out: {minimum_amount_out}")

        # Step 4: Retrieve the user's token account, or create one if it doesn't exist
        token_account_check = client.get_token_accounts_by_owner(payer_keypair.pubkey(), TokenAccountOpts(mint), Processed)
        if token_account_check.value:
            token_account = token_account_check.value[0].pubkey
            token_account_instr = None
        else:
            token_account = get_associated_token_address(payer_keypair.pubkey(), mint)
            token_account_instr = create_associated_token_account(payer_keypair.pubkey(), payer_keypair.pubkey(), mint)

        # Step 5: Check if the user already has a WSOL account, or create one
        wsol_token_account = None
        wsol_account_keypair = None
        create_wsol_account_instr = None
        init_wsol_account_instr = None
        fund_wsol_account_instr = None
        sync_native_instr = None
        wsol_account_check = client.get_token_accounts_by_owner(payer_keypair.pubkey(), TokenAccountOpts(WSOL), Processed)
        
        if wsol_account_check.value:
            wsol_token_account = wsol_account_check.value[0].pubkey
            
            # If WSOL account exists, fund it with the input amount and sync the account
            fund_wsol_account_instr = transfer(
                TransferParams(
                    from_pubkey=payer_keypair.pubkey(),
                    to_pubkey=wsol_token_account,
                    lamports=int(amount_in)
                )
            )
            sync_native_instr = sync_native(SyncNativeParams(TOKEN_PROGRAM_ID, wsol_token_account))

        # Step 6: If no WSOL account exists, create one
        if wsol_token_account is None:
            # Generate a new keypair for the WSOL account
            wsol_account_keypair = Keypair()
            wsol_token_account = wsol_account_keypair.pubkey()
            
            # Get the minimum balance required for the WSOL account to be rent-exempt
            balance_needed = Token.get_min_balance_rent_for_exempt_for_account(client)

            # Create the account and fund it with the necessary SOL
            create_wsol_account_instr = create_account(
                CreateAccountParams(
                    from_pubkey=payer_keypair.pubkey(),
                    to_pubkey=wsol_token_account,
                    lamports=int(balance_needed + amount_in),
                    space=ACCOUNT_LAYOUT.sizeof(),
                    owner=TOKEN_PROGRAM_ID,
                )
            )

            # Initialize the WSOL account
            init_wsol_account_instr = initialize_account(
                InitializeAccountParams(
                    program_id=TOKEN_PROGRAM_ID,
                    account=wsol_token_account,
                    mint=WSOL,
                    owner=payer_keypair.pubkey()
                )
            )

        # Step 7: Create the swap instructions for the trade
        swap_instructions = make_swap_instruction(amount_in, minimum_amount_out, wsol_token_account, token_account, pool_keys, payer_keypair)

        # Step 8: Construct the transaction, adding all necessary instructions
        print("Building transaction...")
        recent_blockhash = client.get_latest_blockhash().value.blockhash
        txn = Transaction(recent_blockhash=recent_blockhash, fee_payer=payer_keypair.pubkey())
        
        txn.add(set_compute_unit_price(UNIT_PRICE))
        txn.add(set_compute_unit_limit(UNIT_BUDGET))
        
        if create_wsol_account_instr:
            txn.add(create_wsol_account_instr)

        if init_wsol_account_instr:
            txn.add(init_wsol_account_instr)

        if fund_wsol_account_instr:
            txn.add(fund_wsol_account_instr)
            
        if sync_native_instr:
            txn.add(sync_native_instr)
        
        if token_account_instr:
            txn.add(token_account_instr)
            
        txn.add(swap_instructions)

        # Step 9: Sign and send the transaction, handling different signing scenarios
        if wsol_account_keypair:
            txn.sign(payer_keypair, wsol_account_keypair)
            txn_sig = client.send_transaction(txn, payer_keypair, wsol_account_keypair, opts=TxOpts(skip_preflight=True)).value
        else:
            txn.sign(payer_keypair)
            txn_sig = client.send_transaction(txn, payer_keypair, opts=TxOpts(skip_preflight=True)).value
        
        # Step 10: Confirm the transaction and return the result
        print("Transaction Signature", txn_sig)
        confirmed = confirm_txn(txn_sig)
        return confirmed
    
    except Exception as e:
        print("Error:", e)
        return False

def sell(pair_address:str, percentage:int=100, slippage:int=5):
    try:
        print(f"Pair Address: {pair_address}")
        if not (1 <= percentage <= 100):
            print("Percentage must be between 1 and 100.")
            return False

        # Step 1: Fetch the pool keys 
        print("Fetching pool keys...")
        pool_keys = fetch_pool_keys(pair_address)

        if pool_keys is None:
            print("No pools keys found...")
            return False

        # Step 2: Determine the mint (sometimes base/quote are swapped)
        mint = pool_keys['base_mint'] if str(pool_keys['base_mint']) != SOL else pool_keys['quote_mint']
        
        # Step 3: Calculate the amount_in and minimum_amount_out
        token_balance = get_token_balance(str(mint))
        print("Token Balance:", token_balance)    
        if token_balance == 0:
            return False
        token_balance = token_balance * (percentage / 100)
        print(f"Selling {percentage}% of the token balance...")
        
        token_price, token_decimal = get_token_price(pool_keys)
        amount_out = float(token_balance) * float(token_price)
        slippage_adjustment = 1 - (slippage / 100)
        amount_out_with_slippage = amount_out * slippage_adjustment
        minimum_amount_out = int(amount_out_with_slippage * SOL_DECIMAL)
        amount_in = int(token_balance * 10**token_decimal)
        print(f"Amount In: {amount_in} | Min Amount Out: {minimum_amount_out}")

        # Step 4: Retrieve the user's token account
        token_account = get_associated_token_address(payer_keypair.pubkey(), mint)

        # Step 5: Check if the user already has a WSOL account, or create one
        wsol_token_account = None
        wsol_account_keypair = None
        create_wsol_account_instr = None
        init_wsol_account_instr = None
        wsol_account_check = client.get_token_accounts_by_owner(payer_keypair.pubkey(), TokenAccountOpts(WSOL), Processed)
        
        if wsol_account_check.value:
            wsol_token_account = wsol_account_check.value[0].pubkey
            
        # Step 6: If no WSOL account exists, create one with the necessary instructions
        if wsol_token_account is None:
            # Generate a new keypair for the WSOL account
            wsol_account_keypair = Keypair()
            wsol_token_account = wsol_account_keypair.pubkey()
            
            # Get the minimum balance required for the WSOL account to be rent-exempt
            balance_needed = Token.get_min_balance_rent_for_exempt_for_account(client)

            # Create the account and fund it with the necessary SOL
            create_wsol_account_instr = create_account(
                CreateAccountParams(
                    from_pubkey=payer_keypair.pubkey(),
                    to_pubkey=wsol_token_account,
                    lamports=int(balance_needed),
                    space=ACCOUNT_LAYOUT.sizeof(),
                    owner=TOKEN_PROGRAM_ID,
                )
            )

            # Initialize the WSOL account
            init_wsol_account_instr = initialize_account(
                InitializeAccountParams(
                    program_id=TOKEN_PROGRAM_ID,
                    account=wsol_token_account,
                    mint=WSOL,
                    owner=payer_keypair.pubkey()
                )
            )

        # Step 7: Create the swap instructions for the trade
        swap_instructions = make_swap_instruction(amount_in, minimum_amount_out, token_account, wsol_token_account, pool_keys, payer_keypair)

        # Step 8: Construct the transaction, adding all necessary instructions
        print("Building transaction...")
        recent_blockhash = client.get_latest_blockhash().value.blockhash
        txn = Transaction(recent_blockhash=recent_blockhash, fee_payer=payer_keypair.pubkey())
        
        # Set compute unit price and limit for the transaction
        txn.add(set_compute_unit_price(UNIT_PRICE))
        txn.add(set_compute_unit_limit(UNIT_BUDGET))
        
        # Add WSOL account creation and initialization instructions, if needed
        if create_wsol_account_instr:
            txn.add(create_wsol_account_instr)
        
        if init_wsol_account_instr:
            txn.add(init_wsol_account_instr)

        # Add the swap instructions to the transaction
        txn.add(swap_instructions)

        # Close the WSOL Account           
        close_wsol_account_instr = close_account(CloseAccountParams(TOKEN_PROGRAM_ID, wsol_token_account, payer_keypair.pubkey(), payer_keypair.pubkey()))
        txn.add(close_wsol_account_instr)        

        # Step 9: Sign and send the transaction, handling different signing scenarios
        if wsol_account_keypair:
            txn.sign(payer_keypair, wsol_account_keypair)
            txn_sig = client.send_transaction(txn, payer_keypair, wsol_account_keypair, opts=TxOpts(skip_preflight=True)).value
        else:
            txn.sign(payer_keypair)
            txn_sig = client.send_transaction(txn, payer_keypair, opts=TxOpts(skip_preflight=True)).value
        
        # Step 10: Confirm the transaction and return the result
        print("Transaction Signature", txn_sig)
        confirmed = confirm_txn(txn_sig)
        return confirmed
    
    except Exception as e:
        print("Error:", e)
        return False
