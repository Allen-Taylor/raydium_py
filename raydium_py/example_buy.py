from raydium import buy
from utils import get_pair_address

# Buy Example
token_address = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr" # POPCAT
pair_address = get_pair_address(token_address)
sol_in = .1
slippage = 10
buy(pair_address, sol_in, slippage)