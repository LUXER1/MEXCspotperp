import asyncio
import aiohttp
import time
import re

_last_request_time = 0
_API_RATE_LIMIT = 5  # например, 5 запросов в секунду
_min_interval = 1 / _API_RATE_LIMIT

async def rate_limit():
    global _last_request_time, _min_interval
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < _min_interval:
        await asyncio.sleep(_min_interval - elapsed)
    _last_request_time = time.time()

async def fetch_futures_price_debug(symbol):
    await rate_limit()
    url = f"https://contract.mexc.com/api/v1/contract/ticker?symbol={symbol}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            print(f"--- Ответ API фьючерсов для {symbol} ---")
            print(data)
            # Попытка безопасно получить цену
            if "data" in data:
                if isinstance(data["data"], list) and len(data["data"]) > 0:
                    print(f"Цена (из списка): {data['data'][0].get('lastPrice')}")
                elif isinstance(data["data"], dict) and "lastPrice" in data["data"]:
                    print(f"Цена (из словаря): {data['data']['lastPrice']}")
                else:
                    print("Поле 'lastPrice' не найдено в 'data'")
            else:
                print("Поле 'data' отсутствует в ответе")

async def main():
    # Примеры символов для проверки
    test_symbols = [
        "BTC_USDT",
        "ETH_USDT",
        "ENAUSDT",
        "SUIUSDT",
        "BNBUSDT",
    ]
    for symbol in test_symbols:
        try:
            await fetch_futures_price_debug(symbol)
        except Exception as e:
            print(f"Ошибка при запросе {symbol}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
