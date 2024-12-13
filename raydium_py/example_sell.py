from raydium import sell
from utils import get_pair_address_from_api, get_pair_address_from_rpc

# Sell Example
token_address = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"  # POPCAT
percentage = 100
slippage = 1

# Fetch pair address, fallback to RPC if not found
pair_address = get_pair_address_from_api(token_address) or get_pair_address_from_rpc(token_address)

# Execute sell if pair address is found
if pair_address:
    sell(pair_address, percentage, slippage)
else:
    print("Error: Pair address not found.")
