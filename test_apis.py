import requests
import json

def test_bsky():
    handle = "did:plc:z72i7hdynmk6r22z27h6tvur" # example did or use handle like 'bsky.app'
    # Actually let's just use the HTTP API directly
    # To get a DID from handle:
    # https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?handle=bsky.app
    handle = "rtve.es"
    res = requests.get(f"https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?handle={handle}")
    print("Resolve Handle:", res.status_code, res.text)
    
test_bsky()
