import logging
import asyncio
import aiohttp
import json
import os
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties

TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

WATCHED_ADDRESSES_FILE = "watched_addresses.json"
TX_CACHE_FILE = "tx_cache.json"
LAST_BLOCK_FILE = "last_block.json"

WATCHED_ADDRESSES = {}
TX_CACHE = set()
LAST_BLOCK = 0

BLOCKSCOUT_API = "https://soneium.blockscout.com/api"

def load_watched_addresses():
    global WATCHED_ADDRESSES
    try:
        with open(WATCHED_ADDRESSES_FILE, "r") as f:
            WATCHED_ADDRESSES = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        WATCHED_ADDRESSES = {}

def save_watched_addresses():
    with open(WATCHED_ADDRESSES_FILE, "w") as f:
        json.dump(WATCHED_ADDRESSES, f)

def load_tx_cache():
    global TX_CACHE
    try:
        with open(TX_CACHE_FILE, "r") as f:
            TX_CACHE = set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        TX_CACHE = set()

def save_tx_cache():
    with open(TX_CACHE_FILE, "w") as f:
        json.dump(list(TX_CACHE), f)

def load_last_block():
    global LAST_BLOCK
    try:
        with open(LAST_BLOCK_FILE, "r") as f:
            LAST_BLOCK = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        LAST_BLOCK = 0

def save_last_block(block):
    with open(LAST_BLOCK_FILE, "w") as f:
        json.dump(block, f)

async def fetch_transactions(address):
    url = f"{BLOCKSCOUT_API}?module=account&action=tokentx&address={address}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            try:
                return await response.json()
            except json.JSONDecodeError:
                return {"result": []}

async def track_transactions():
    while True:
        new_tx_count = 0
        notification_queue = asyncio.Queue()
        
        for address, data in WATCHED_ADDRESSES.items():
            transactions = await fetch_transactions(address)
            if transactions.get("result"):
                for tx in transactions["result"]:
                    tx_hash = tx.get("hash")
                    tx_block = int(tx.get("blockNumber", 0))
                    
                    if tx_block > LAST_BLOCK and tx_hash not in TX_CACHE:
                        TX_CACHE.add(tx_hash)
                        notification_queue.put_nowait((tx, address, data.get("name", "Unknown"), data["chat_id"]))
                        new_tx_count += 1

        if new_tx_count > 0:
            save_tx_cache()
            save_last_block(tx_block)
            await send_notifications(notification_queue)

        logging.info(f"✅ {new_tx_count} transaksi baru terdeteksi.")
        await asyncio.sleep(30)

async def send_notifications(queue):
    while not queue.empty():
        tx, address, name, chat_id = await queue.get()
        try:
            await notify_transaction(tx, address, name, chat_id)
            await asyncio.sleep(2)
        except Exception as e:
            logging.error(f"❌ Gagal mengirim notifikasi: {e}")

async def notify_transaction(tx, address, name, chat_id):
    try:
        tx_type = await detect_transaction_type(tx, address)
        msg = (f"🔔 <b>Transaksi Baru</b> 🔔\n"
               f"👤 <b>{name}</b>\n"
               f"🔹 Type: {tx_type}\n"
               f"🔗 <a href='https://soneium.blockscout.com/tx/{tx.get('hash')}'>Lihat di Block Explorer</a>")
        await bot.send_message(chat_id, msg[:4096])  # Hindari error teks terlalu panjang
    except Exception as e:
        logging.error(f"❌ Gagal mengirim notifikasi: {e}")

async def detect_transaction_type(tx, address):
    sender = tx.get("from", "").lower()
    receiver = tx.get("to", "").lower()
    value = int(tx.get("value", "0")) if tx.get("value") else 0

    if "tokenSymbol" in tx and "NFT" in tx["tokenSymbol"]:
        return "🎨 NFT Sale" if sender == address.lower() else "🛒 NFT Purchase"
    
    if "tokenSymbol" in tx:
        return "🔁 Token Transfer"
    
    if tx.get("input") and tx["input"] != "0x":
        return "🔄 Swap"
    
    if value > 0:
        return "🔁 ETH Transfer"
    
    return "🔍 Unknown"

@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer("🚀 Selamat datang di Soneium Tracker!\n"
                         "Gunakan /add <address> <nama> untuk mulai melacak transaksi.")

async def main():
    logging.info("🚀 Bot mulai berjalan...")
    load_watched_addresses()
    load_tx_cache()
    load_last_block()
    asyncio.create_task(track_transactions())
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
