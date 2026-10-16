"""Dry-run the adapted tier resolution. No outbound calls."""
import sys

sys.path.insert(0, r"D:\deepchoice-precodex\src")

from deepchoice.utils import llm

for name, cfg in llm.TIERS.items():
    print(f"  {name:16} model={cfg['model']}")
    print(f"  {'':16} base={cfg['base']}")
    print(f"  {'':16} key_set={bool(cfg['key'])} extra_body={cfg.get('extra_body')}")
print("  _MAX_RETRIES =", llm._MAX_RETRIES)
print("  retryable    =", sorted(llm._RETRYABLE_STATUSES))


class _Fake:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


real = llm.AsyncOpenAI
llm.AsyncOpenAI = _Fake
try:
    for tier in ("deepseek-flash", "qwen-flash"):
        client = llm._get_client(timeout=60.0, tier=tier, max_retries=0)
        print(f"  _get_client({tier}) -> base={client.kwargs['base_url']} "
              f"timeout={client.kwargs['timeout']} retries={client.kwargs.get('max_retries')} "
              f"key_set={bool(client.kwargs['api_key'])}")
finally:
    llm.AsyncOpenAI = real
