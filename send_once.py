import asyncio
import httpx
import pytz
import xml.etree.ElementTree as ET
import os
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta
from telegram import Bot
from telegram.error import TelegramError

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_IDS = [int(x.strip()) for x in os.environ["CHAT_ID"].split(",")]
TIMEZONE = pytz.timezone("Europe/Moscow")

MESSAGES = [
    "Доброе утро! Пусть этот день принесёт тебе только хорошее ☀️",
    "С добрым утром! Желаю тебе прекрасного дня 🌸",
    "Доброе утро! Улыбнись — день будет замечательным 😊",
    "С добрым утром! Пусть всё идёт по плану и даже лучше 🌟",
    "Доброе утро! Хорошего тебе дня и отличного настроения 💫",
]

WEATHER_CODES = {
    0: "Ясно ☀️", 1: "Преим. ясно 🌤", 2: "Переменно ⛅", 3: "Пасмурно ☁️",
    45: "Туман 🌫", 48: "Туман 🌫",
    51: "Лёгкая морось 🌦", 53: "Морось 🌦", 55: "Сильная морось 🌧",
    61: "Небольшой дождь 🌧", 63: "Дождь 🌧", 65: "Сильный дождь 🌧",
    71: "Небольшой снег 🌨", 73: "Снег 🌨", 75: "Сильный снег ❄️",
    77: "Снежная крупа 🌨",
    80: "Ливень 🌦", 81: "Умеренный ливень 🌧", 82: "Сильный ливень ⛈",
    85: "Снегопад 🌨", 86: "Сильный снегопад ❄️",
    95: "Гроза ⛈", 96: "Гроза с градом ⛈", 99: "Гроза с сильным градом ⛈",
}


async def get_currency_rates():
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://www.cbr.ru/scripts/XML_daily.asp", timeout=10)
        root = ET.fromstring(resp.text)
    rates = {}
    for valute in root.findall("Valute"):
        char_code = valute.find("CharCode").text
        if char_code in ("USD", "CNY"):
            value = float(valute.find("Value").text.replace(",", "."))
            nominal = int(valute.find("Nominal").text)
            rates[char_code] = value / nominal
    return rates


async def get_bitcoin_price(usd_rate: float):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            timeout=10,
        )
    btc_usd = resp.json()["bitcoin"]["usd"]
    return btc_usd, btc_usd * usd_rate


async def get_weather():
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 45.0448,
                "longitude": 38.9760,
                "hourly": "temperature_2m,weathercode",
                "timezone": "Europe/Moscow",
                "forecast_days": 1,
            },
            timeout=10,
        )
    data = resp.json()["hourly"]
    lines = []
    for time_str, temp, code in zip(data["time"], data["temperature_2m"], data["weathercode"]):
        hour = int(time_str[11:13])
        if hour % 3 == 0:
            desc = WEATHER_CODES.get(code, "—")
            lines.append(f"  {time_str[11:16]}  {temp:+.0f}°C  {desc}")
    return "\n".join(lines)


async def get_news():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://ria.ru/export/rss2/archive/index.xml",
            headers=headers,
            timeout=10,
            follow_redirects=True,
        )
        resp.raise_for_status()
    root = ET.fromstring(resp.content)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    items = []
    for item in root.findall(".//item"):
        title_el = item.find("title")
        pubdate_el = item.find("pubDate")
        if title_el is None:
            continue
        if pubdate_el is not None:
            try:
                published = parsedate_to_datetime(pubdate_el.text)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                if published < cutoff:
                    continue
            except Exception:
                pass
        items.append(title_el.text)
        if len(items) == 10:
            break
    return items


async def main():
    day_of_week = datetime.now(TIMEZONE).weekday()
    greeting = MESSAGES[day_of_week % len(MESSAGES)]

    try:
        rates = await get_currency_rates()
        usd = rates.get("USD", 0)
        cny = rates.get("CNY", 0)
        btc_usd, btc_rub = await get_bitcoin_price(usd)
        weather = await get_weather()
    except Exception as e:
        print(f"Ошибка получения данных: {e}")
        usd = cny = btc_usd = btc_rub = 0
        weather = "не удалось загрузить"

    try:
        news = await get_news()
        news_text = "\n".join(f"  {i+1}. {title}" for i, title in enumerate(news))
    except Exception as e:
        print(f"Ошибка получения новостей: {e}")
        news_text = "  не удалось загрузить"

    message = (
        f"{greeting}\n\n"
        f"💰 Курсы (ЦБ РФ):\n"
        f"  💵 Доллар: {usd:.2f} ₽\n"
        f"  🇨🇳 Юань:  {cny:.2f} ₽\n"
        f"  ₿ Биткоин: ${btc_usd:,.0f}  ({btc_rub:,.0f} ₽)\n\n"
        f"🌤 Погода в Краснодаре:\n{weather}\n\n"
        f"📰 Новости за 24 часа (Лента.ру):\n{news_text}"
    )

    bot = Bot(token=BOT_TOKEN)
    for chat_id in CHAT_IDS:
        try:
            await bot.send_message(chat_id=chat_id, text=message)
            print(f"Отправлено: {chat_id}")
        except TelegramError as e:
            print(f"Ошибка {chat_id}: {e}")


asyncio.run(main())