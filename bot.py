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
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

WATCHED_ADDRESSES_FILE = "watched_addresses.json"
TX_CACHE_FILE = "tx_cache.json"
LAST_BLOCK_FILE = "last_block.json"

WATCHED_ADDRESSES = {}
TX_CACHE = set()
LAST_BLOCK = {}

BLOCKSCOUT_API = "https://soneium.blockscout.com/api"

# Load functions
def load_json(filename, default_value):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_value

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f)

def load_data():
    global WATCHED_ADDRESSES, TX_CACHE, LAST_BLOCK
    WATCHED_ADDRESSES = load_json(WATCHED_ADDRESSES_FILE, {})
    TX_CACHE = set(load_json(TX_CACHE_FILE, []))
    LAST_BLOCK = load_json(LAST_BLOCK_FILE, {})

def save_data():
    save_json(TX_CACHE_FILE, list(TX_CACHE))
    save_json(LAST_BLOCK_FILE, LAST_BLOCK)

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
                last_block = LAST_BLOCK.get(address, 0)
                for tx in transactions["result"]:
                    tx_hash = tx.get("hash")
                    block_number = int(tx.get("blockNumber", 0))

                    if tx_hash and tx_hash not in TX_CACHE and block_number > last_block:
                        TX_CACHE.add(tx_hash)
                        LAST_BLOCK[address] = block_number
                        notification_queue.put_nowait((tx, address, data.get("name", "Unknown"), data["chat_id"]))
                        new_tx_count += 1

        if new_tx_count > 0:
            save_data()
            await send_notifications(notification_queue)
        
        logging.info(f"✅ {new_tx_count} transaksi baru terdeteksi.")
        await asyncio.sleep(30)

async def send_notifications(queue):
    while not queue.empty():
        tx, address, name, chat_id = await queue.get()
        try:
            await notify_transaction(tx, address, name, chat_id)
            await asyncio.sleep(2)
        except TelegramRetryAfter as e:
            logging.error(f"⚠ Rate limit! Menunggu {e.retry_after} detik.")
            await asyncio.sleep(e.retry_after)
        except TelegramBadRequest as e:
            logging.error(f"❌ Bad Request: {e}")
        except Exception as e:
            logging.error(f"❌ Gagal mengirim notifikasi: {e}")

async def notify_transaction(tx, address, name, chat_id):
    tx_type = await detect_transaction_type(tx, address)
    msg = (f"🔔 <b>Transaksi Baru</b> 🔔\n"
           f"👤 <b>{name}</b>\n"
           f"🔹 Type: {tx_type}\n"
           f"🔗 <a href='https://soneium.blockscout.com/tx/{tx.get('hash')}'>Lihat di Block Explorer</a>")

    if len(msg) > 4096:
        msg = msg[:4090] + "..."

    try:
        await bot.send_message(chat_id, msg)
    except TelegramRetryAfter as e:
        logging.error(f"⚠ Rate limit! Menunggu {e.retry_after} detik.")
        await asyncio.sleep(e.retry_after)
        await bot.send_message(chat_id, msg)
    except TelegramBadRequest as e:
        logging.error(f"❌ Bad Request: {e}")

async def detect_transaction_type(tx, address):
    sender = tx.get("from", "").lower()
    receiver = tx.get("to", "").lower()
    if "tokenSymbol" in tx and "NFT" in tx["tokenSymbol"]:
        return "🎨 NFT Sale" if sender == address.lower() else "🛒 NFT Purchase"
    if "tokenSymbol" in tx:
        return "🔁 Token Transfer"
    if tx.get("input") and tx["input"] != "0x":
        return "🔄 Swap"
    return "🔍 Unknown"

@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer("🚀 Selamat datang di Soneium Tracker!\nGunakan <code>/add alamat_wallet nama</code> untuk mulai melacak transaksi.", parse_mode="HTML")

@dp.message(Command("add"))
async def add_address(message: Message):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("⚠ Gunakan format: <code>/add alamat_wallet nama</code>", parse_mode="HTML")
        return
    address, name = parts[1], parts[2]
    WATCHED_ADDRESSES[address] = {"name": name, "chat_id": message.chat.id}
    save_json(WATCHED_ADDRESSES_FILE, WATCHED_ADDRESSES)
    await message.answer(f"✅ Alamat <code>{address}</code> dengan nama <b>{name}</b> berhasil ditambahkan!", parse_mode="HTML")

async def main():
    logging.info("🚀 Bot mulai berjalan...")
    load_data()
    asyncio.create_task(track_transactions())
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
