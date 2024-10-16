from solana.rpc.api import Client
from solders.keypair import Keypair #type: ignore

PRIV_KEY = "base_58_priv_key_here"
RPC = "rpc_here"
client = Client(RPC)
payer_keypair = Keypair.from_base58_string(PRIV_KEY)