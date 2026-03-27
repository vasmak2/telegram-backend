import os
import asyncio
import uvicorn
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import LabeledPrice
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, BigInteger
from sqlalchemy.orm import sessionmaker, declarative_base
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

load_dotenv()

# --- НАСТРОЙКИ И БД ---
API_TOKEN = os.getenv("TOKEN_API")
RAW_DB_URL = os.getenv("DATABASE_URL")
WEB_APP_URL = "https://vasmak2.github.io/telegram-backend/"

if not API_TOKEN:
    print("КРИТИЧЕСКАЯ ОШИБКА: Переменная TOKEN_API не найдена!")

# Исправляем протокол для SQLAlchemy
if RAW_DB_URL and RAW_DB_URL.startswith("postgres://"):
    DATABASE_URL = RAW_DB_URL.replace("postgres://", "postgresql://", 1)
else:
    DATABASE_URL = RAW_DB_URL

# Настройка SQLAlchemy
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# Модель таблицы участников
class Bidder(Base):
    __tablename__ = "bidders"
    user_id = Column(BigInteger, primary_key=True)
    username = Column(String)
    total_bid = Column(Integer, default=0)

# Создание таблиц
Base.metadata.create_all(engine)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальное состояние для быстрого доступа (синхронизируется с БД)
auction_state = {
    "current_bid": 0,
    "item_name": "NFT Gift #123",
    "winner_id": None
}

class BidRequest(BaseModel):
    user_id: int
    amount: int

@dp.message(Command("start"))
async def start_command(message: types.Message):
    # Создаем красивую инлайн-кнопку
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🚀 Открыть Аукцион", 
                web_app=WebAppInfo(url=WEB_APP_URL)
            )
        ]
    ])
    
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        f"Добро пожаловать в аукцион. Нажми на кнопку ниже, чтобы посмотреть лот и сделать свою ставку.",
        reply_markup=markup
    )

# --- API ДЛЯ MINI APP ---

@app.get("/")
async def root():
    # При запуске подтягиваем актуальную макс. ставку из БД
    with SessionLocal() as session:
        max_bid = session.query(Bidder).order_by(Bidder.total_bid.desc()).first()
        if max_bid:
            auction_state["current_bid"] = max_bid.total_bid
    return {"status": "ok", "current_bid": auction_state["current_bid"]}

@app.post("/create-bid-invoice")
async def create_bid_invoice(request: BidRequest):
    # Проверка: новая сумма + уже вложенные звезды должна быть > текущего рекорда
    with SessionLocal() as session:
        bidder = session.query(Bidder).filter_by(user_id=request.user_id).first()
        already_paid = bidder.total_bid if bidder else 0
        
        if (already_paid + request.amount) <= auction_state["current_bid"]:
            raise HTTPException(status_code=400, detail="Твоя суммарная ставка не бьет рекорд")

    try:
        invoice_link = await bot.create_invoice_link(
            title="Повышение ставки",
            description=f"Доплата за {auction_state['item_name']}",
            payload=f"bid:{request.user_id}:{request.amount}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Stars", amount=request.amount)]
        )
        return {"invoice_link": invoice_link}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {e}")

# --- ОБРАБОТКА ПЛАТЕЖЕЙ (BOT) ---

@dp.pre_checkout_query()
async def process_pre_checkout(query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)

@dp.message(F.successful_payment)
async def on_successful_payment(message: types.Message):
    amount = message.successful_payment.total_amount
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    with SessionLocal() as session:
        bidder = session.query(Bidder).filter_by(user_id=user_id).first()
        if not bidder:
            bidder = Bidder(user_id=user_id, username=username, total_bid=amount)
            session.add(bidder)
        else:
            bidder.total_bid += amount
            bidder.username = username # Обновляем юзернейм на всякий случай
        
        session.commit()
        new_total = bidder.total_bid
        
        # Обновляем глобальный рекорд
        if new_total > auction_state["current_bid"]:
            auction_state["current_bid"] = new_total
            auction_state["winner_id"] = user_id

    await message.answer(f"✅ Ставка принята! Твой текущий итог: {new_total} ⭐️\nЛидер аукциона: {username}")

# --- ЗАПУСК ---

async def run_bot():
    await dp.start_polling(bot)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(run_bot())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

async def keep_alive():
    """Фоновая задача, которая пингует сервер раз в 10 минут"""
    url = "https://telegram-backend-0l5i.onrender.com" # Замени на свой URL
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await client.get(url)
                print("Ping success: Server is awake!")
            except Exception as e:
                print(f"Ping failed: {e}")
            await asyncio.sleep(600) # 600 секунд = 10 минут

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(run_bot())
    asyncio.create_task(keep_alive()) # Запускаем само-пинг
