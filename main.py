import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import LabeledPrice
import uvicorn
import asyncio

# --- НАСТРОЙКИ ---
API_TOKEN = "8774294837:AAGbfx_yGbPU9GugIvPdzTBgIdVyyyDtnKk" # Получите у @BotFather
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
app = FastAPI()

# Разрешаем запросы с GitHub Pages (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Состояние аукциона (в идеале хранить в БД)
auction_state = {
    "current_bid": 100,
    "item_name": "NFT Gift #123",
    "winner_id": None
}

class BidRequest(BaseModel):
    user_id: int
    amount: int

# --- API ДЛЯ MINI APP ---

@app.get("/")
async def root():
    return {"status": "ok", "current_bid": auction_state["current_bid"]}

@app.post("/create-bid-invoice")
async def create_bid_invoice(request: BidRequest):
    if request.amount <= auction_state["current_bid"]:
        raise HTTPException(status_code=400, detail="Ставка ниже текущей")

    try:
        # Создаем ссылку на оплату в Telegram Stars (XTR)
        invoice_link = await bot.create_invoice_link(
            title="Ставка в аукционе",
            description=f"Лот: {auction_state['item_name']}",
            payload=f"bid:{request.user_id}:{request.amount}",
            provider_token="", # Для Stars пусто
            currency="XTR",
            prices=[LabeledPrice(label="Stars", amount=request.amount)]
        )
        return {"invoice_link": invoice_link}
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Ошибка создания счета")

# --- ОБРАБОТКА ПЛАТЕЖЕЙ (BOT) ---

@dp.pre_checkout_query()
async def process_pre_checkout(query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)

@dp.message(F.successful_payment)
async def on_successful_payment(message: types.Message):
    amount = message.successful_payment.total_amount
    user_id = message.from_user.id
    
    # Обновляем состояние аукциона
    auction_state["current_bid"] = amount
    auction_state["winner_id"] = user_id
    
    await message.answer(f"🔥 Новая ставка: {amount} ⭐️ от {message.from_user.first_name}!")

# --- ЗАПУСК ---

async def run_bot():
    # Запуск бота в фоновом режиме
    await dp.start_polling(bot)

@app.on_event("startup")
async def startup_event():
    # Запускаем бота при старте FastAPI
    asyncio.create_task(run_bot())

if __name__ == "__main__":
    # Порт для Render берем из переменной окружения
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
