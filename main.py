import asyncio
import logging
import pytz
import httpx
import xml.etree.ElementTree as ET
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.error import TelegramError

# --- Настройки ---
BOT_TOKEN = "8999461719:AAHd3d8TkIAo2EbMY4icwd4L1sTVrfm2lv4"
CHAT_ID = 1019178017
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

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


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
        if hour % 1 == 0:  # каждые 3 часа
            desc = WEATHER_CODES.get(code, "—")
            lines.append(f"  {time_str[11:16]}  {temp:+.0f}°C  {desc}")
    return "\n".join(lines)


async def send_good_morning():
    day_of_week = datetime.now(TIMEZONE).weekday()
    greeting = MESSAGES[day_of_week % len(MESSAGES)]

    try:
        rates = await get_currency_rates()
        usd = rates.get("USD", 0)
        cny = rates.get("CNY", 0)
        btc_usd, btc_rub = await get_bitcoin_price(usd)
        weather = await get_weather()
    except Exception as e:
        logger.error("Ошибка получения данных: %s", e)
        usd = cny = btc_usd = btc_rub = 0
        weather = "не удалось загрузить"

    message = (
        f"{greeting}\n\n"
        f"💰 Курсы (ЦБ РФ):\n"
        f"  💵 Доллар: {usd:.2f} ₽\n"
        f"  🇨🇳 Юань:  {cny:.2f} ₽\n"
        f"  ₿ Биткоин: ${btc_usd:,.0f}  ({btc_rub:,.0f} ₽)\n\n"
        f"🌤 Погода в Краснодаре:\n{weather}"
    )

    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=CHAT_ID, text=message)
        logger.info("Сообщение отправлено")
    except TelegramError as e:
        logger.error("Ошибка при отправке: %s", e)


async def main():
    logger.info("Бот запущен. Жду 8:00 по Москве...")
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(send_good_morning, "cron", hour=7, minute=0)
    scheduler.start()

    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())