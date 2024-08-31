from solana.rpc.api import Client
from solders.keypair import Keypair #type: ignore

PRIV_KEY = "priv_key"
RPC = "rpc_url"
client = Client(RPC)
payer_keypair = Keypair.from_base58_string(PRIV_KEY)