from raydium import buy
from utils import get_pair_address

def main():
    token_address = 'token_address_to_buy'
    amount_in_sol = .01
    pair_address = get_pair_address(token_address)
    print(f"Token Address: {token_address}")
    print(f"Pair Address: {pair_address}")
    if pair_address:
        buy(pair_address, amount_in_sol)
    else:
        print("Pair Address not found...")

if __name__ == "__main__":
    main()