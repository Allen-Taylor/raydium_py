from raydium import sell
from utils import get_pair_address

# Sell Example
token_address = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr" # POPCAT
pair_address = get_pair_address(token_address)
percentage = 100
slippage = 10
sell(pair_address, percentage, slippage)