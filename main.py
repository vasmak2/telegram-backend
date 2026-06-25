import hmac
import hashlib
import urllib.parse
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# НАСТРОЙКА CORS: Разрешаем фронтенду с GitHub Pages слать запросы к бэкенду
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене замени "*" на твой URL типа https://yourname.github.io
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Переменные окружения (задаются в панели Render)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "MOCK_TOKEN")
MARKETPLACE_API_KEY = os.getenv("MARKETPLACE_API_KEY")

class OrderSchema(BaseModel):
    init_data: str  # Данные авторизации от Telegram
    item_id: str
    quantity: int

def verify_telegram_data(init_data: str, token: str) -> bool:
    """Безопасная проверка: действительно ли запрос подпиcaн Telegram"""
    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data))
        if "hash" not in parsed_data:
            return False
        
        received_hash = parsed_data.pop("hash")
        # Сортируем параметры по алфавиту, как требует Telegram
        data_check_string = "\n".join([f"{k}={v}" for k, v in sorted(parsed_data.items())])
        
        # Вычисляем секретный ключ на основе токена бота
        secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        # Вычисляем финальный хэш
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        return hmac.compare_digest(calculated_hash, received_hash)
    except Exception:
        return False

@app.get("/api/health")
def health():
    return {"status": "alive", "message": "Склад очков готов к работе!"}

@app.post("/api/checkout")
def create_order(order: OrderSchema):
    # 1. Защита конфиденциальности и подлинности
    if not verify_telegram_data(order.init_data, BOT_TOKEN):
        raise HTTPException(status_code=403, detail="Ошибка безопасности: Неверные данные Telegram")
    
    # 2. Имитация синхронизации с маркетплейсом
    # Здесь ты используешь MARKETPLACE_API_KEY для запроса к Ozon/WB (проверить/списать очки с остатков)
    
    # 3. Формирование ссылки на оплату
    # Интегрируешь API ЮKassa/Stripe и генерируешь платежную сессию
    mock_payment_url = "https://yookassa.ru/integration/mock-payment" 

    return {
        "success": True,
        "message": f"Очки (ID: {order.item_id}) забронированы. Перейдите к оплате.",
        "payment_url": mock_payment_url
    }
