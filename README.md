# raydium_py

This repo is for my python lovers who want to trade on Raydium.

Clone the repo, and add your Public Key (wallet), Private Key and RPC to the config.py.

### Examples

See the example_buy.py and example_sell.py. 

### FAQS

**What format should my private key be in?** 

The private key should be in the base58 string format, not bytes. 

**Why are my transactions being dropped?** 

You get what you pay for. If you use the public RPC, you're going to get rekt. Spend the money for Helius or Quick Node. Also, play around with the compute limits and lamports.

**What format is slippage in?** 

There is no slippage in this implementation. Tokens out is set to 0 (any amount) for buys and sells. Feel free to change it. 

### Contact

Contact me if you need help integrating the code into your own project. 

Telegram: Allen_A_Taylor (AL The Bot Father)
