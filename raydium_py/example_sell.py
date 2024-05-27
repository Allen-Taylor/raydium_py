from raydium import sell
from utils import get_token_price, get_pair_address, get_token_balance_lamports

def main():
    token_address = 'token_address_to_sell'
    pair_address = get_pair_address(token_address)
    
    print(f"Token Address: {token_address}")
    print(f"Pair Address: {pair_address}")

    token_price = get_token_price(pair_address)
    formatted_price = f"${token_price:.20f}" 
    
    print(f"Native Token Price: {formatted_price}")

    token_balance = get_token_balance_lamports(token_address)

    if token_balance > 0 and token_balance is not None:
        print(f"Token Balance (lamports): {token_balance}")
        sell(pair_address, token_balance)
    else:
        print("No tokens to sell.")

if __name__ == "__main__":
    main()