import requests
import time

_cache = {"timestamp": 0, "data": []}
CACHE_TTL = 60  # 60 секунд

def get_top_symbols(limit=20):
    global _cache
    now = time.time()
    if now - _cache["timestamp"] < CACHE_TTL and _cache["data"]:
        return _cache["data"][:limit]

    url = "https://api.mexc.com/api/v3/ticker/24hr"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        usdt_pairs = [item for item in data if item['symbol'].endswith("USDT")]
        sorted_by_volume = sorted(usdt_pairs, key=lambda x: float(x['quoteVolume']), reverse=True)

        top_symbols = [item['symbol'] for item in sorted_by_volume[:limit]]
        _cache = {"timestamp": now, "data": top_symbols}
        return top_symbols
    except Exception as e:
        print(f"Ошибка загрузки топ монет: {e}")
        return []
