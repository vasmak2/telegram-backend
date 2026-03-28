import os
import asyncio
import logging
import urllib.parse
import hmac
import hashlib
import json
import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, Update
from aiogram.filters import Command

from sqlalchemy import create_engine, Column, String, BigInteger, func
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = os.getenv("TOKEN_API")
RAW_DB_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")
WEB_APP_URL = "https://vasmak2.github.io"
# ВАЖНО: WEBHOOK_URL должен быть вашим адресом на Render (https://your-app.onrender.com)
WEBHOOK_PATH = "/webhook"
BASE_URL = os.getenv("BASE_URL", "https://telegram-backend-0l5i.onrender.com")
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

if RAW_DB_URL.startswith("postgres://"):
    DATABASE_URL = RAW_DB_URL.replace("postgres://", "postgresql://", 1)
else:
    DATABASE_URL = RAW_DB_URL

# --- ЛОГИ ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- БАЗА ДАННЫХ ---
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Bidder(Base):
    __tablename__ = "bidders"
    user_id = Column(BigInteger, primary_key=True)
    username = Column(String)
    total_bid = Column(BigInteger, default=0)


Base.metadata.create_all(engine)

# --- ИНИЦИАЛИЗАЦИЯ AIOGRAM ---
bot = Bot(token=API_TOKEN)
dp = Dispatcher()


# --- ФУНКЦИИ БД ---
def get_current_max_bid():
    with SessionLocal() as session:
        result = session.query(func.max(Bidder.total_bid)).scalar()
        return result or 0


def update_db_after_payment(user_id: int, username: str, amount: int) -> int:
    with SessionLocal() as session:
        try:
            bidder = session.query(Bidder).filter_by(user_id=user_id).with_for_update().first()
            if not bidder:
                bidder = Bidder(user_id=user_id, username=username, total_bid=amount)
                session.add(bidder)
            else:
                bidder.total_bid += amount
                bidder.username = username
            session.commit()
            return bidder.total_bid
        except Exception as e:
            session.rollback()
            logger.error(f"DB Error: {e}")
            return 0


# --- LIFESPAN (Замена polling) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Устанавливаем Webhook при запуске
    webhook_info = await bot.get_webhook_info()
    if webhook_info.url != WEBHOOK_URL:
        await bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
        logger.info(f"Webhook set to {WEBHOOK_URL}")

    yield

    # 2. Удаляем Webhook (опционально) и закрываем сессию
    await bot.delete_webhook()
    await bot.session.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://vasmak2.github.io"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- ОБРАБОТЧИК WEBHOOK ---
@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}


# --- API ЭНДПОИНТЫ ---
class BidRequest(BaseModel):
    initData: str
    amount: int


@app.get("/")
def root():
    return {"status": "ok", "current_bid": get_current_max_bid()}


@app.post("/create-bid-invoice")
async def create_invoice(request: BidRequest):
    user_data = validate_telegram_data(request.initData, API_TOKEN)
    if not user_data:
        raise HTTPException(status_code=403, detail="Invalid auth data")

    try:
        # Прямая генерация ссылки на оплату звездами (XTR)
        invoice_link = await bot.create_invoice_link(
            title="Пополнение ставки",
            description=f"Добавить {request.amount} ⭐️ к вашей ставке",
            payload=f"uid:{user_data['id']}",
            provider_token="",  # Для звезд пусто
            currency="XTR",
            prices=[LabeledPrice(label="Stars", amount=request.amount)]
        )
        return {"invoice_link": invoice_link}
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        raise HTTPException(status_code=500, detail="Error creating invoice")


# --- ЛОГИКА БОТА ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Аукцион", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])
    await message.answer("Жми кнопку, чтобы сделать ставку!", reply_markup=kb)


@dp.pre_checkout_query()
async def pre_checkout(query: types.PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def on_payment(message: types.Message):
    amount = message.successful_payment.total_amount
    user = message.from_user

    # Синхронный вызов БД в executor, чтобы не фризить event loop
    loop = asyncio.get_event_loop()
    new_total = await loop.run_in_executor(
        None, update_db_after_payment, user.id, user.username or user.first_name, amount
    )

    await message.answer(f"✅ Оплата принята! Ваша общая ставка: {new_total} ⭐️")


# --- УТИЛИТЫ ---
def validate_telegram_data(init_data: str, token: str):
    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data))
        hash_val = parsed_data.pop("hash", None)
        # Проверка auth_date (данные не старше 24ч)
        # auth_date = int(parsed_data.get("auth_date", 0))

        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if calc_hash == hash_val:
            return json.loads(parsed_data["user"])
        return None
    except:
        return None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    # reload=False обязателен для Webhooks, чтобы не множить процессы
    uvicorn.run(app, host="0.0.0.0", port=port)
