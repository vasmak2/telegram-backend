from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from aiogram import Bot
import uvicorn

# Конфиг
API_TOKEN = "8774294837:AAGbfx_yGbPU9GugIvPdzTBgIdVyyyDtnKk"
bot = Bot(token=API_TOKEN)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Разрешить запросы со всех доменов (включая GitHub Pages)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Простая база данных в памяти (в продакшне используйте Redis/PostgreSQL)
auction_state = {
    "current_bid": 100,
    "item_id": "nft_gift_001",
    "history": []
}

class BidRequest(BaseModel):
    user_id: int
    amount: int

@app.post("/create-bid-invoice")
async def create_bid_invoice(request: BidRequest):
    # Проверяем, выше ли ставка текущей
    if request.amount <= auction_state["current_bid"]:
        raise HTTPException(status_code=400, detail="Ставка слишком низкая")

    # Генерируем Invoice Link для Telegram Stars (XTR)
    try:
        invoice_link = await bot.create_invoice_link(
            title="Ставка в аукционе",
            description=f"Лот: {auction_state['item_id']}",
            payload=f"uid:{request.user_id}|amt:{request.amount}",
            provider_token="", # Пусто для Stars
            currency="XTR",
            prices=[{"label": "Stars", "amount": request.amount}]
        )
        return {"invoice_link": invoice_link}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
