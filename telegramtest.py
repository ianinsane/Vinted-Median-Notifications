# Testskript für Telegram-Bot
import os
import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("TELEGRAM_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")
msg = "Testnachricht von Vinted-Bot"

url = f"https://api.telegram.org/bot{token}/sendMessage"
resp = requests.post(url, data={"chat_id": chat_id, "text": msg})
print(resp.status_code, resp.text)