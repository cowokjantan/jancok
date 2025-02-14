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
    try:
        with open(filename, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logging.error(f"❌ Gagal menyimpan data ke {filename}: {e}")

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
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    logging.error(f"❌ API Error {response.status} saat mengambil transaksi {address}")
                    return {"result": []}
                return await response.json()
        except (aiohttp.ClientError, json.JSONDecodeError) as e:
            logging.error(f"❌ Gagal mengambil transaksi dari API: {e}")
            return {"result": []}

async def track_transactions():
    while True:
        new_tx_count = 0
        notification_queue = asyncio.Queue()

        # Gunakan salinan dictionary agar tidak berubah saat iterasi
        for address, data in WATCHED_ADDRESSES.copy().items():
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
            await asyncio.sleep(2)  # Hindari spam Telegram
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
    except Exception as e:
        logging.error(f"❌ Gagal mengirim pesan ke {chat_id}: {e}")

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
    await message.answer("🚀 Selamat datang di Soneium Tracker!\nGunakan /add <address> <nama> untuk mulai melacak transaksi.")

@dp.message(Command("add"))
async def add_address(message: Message):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("⚠ Gunakan format: /add <address> <nama>")
        return
    address, name = parts[1], parts[2]
    WATCHED_ADDRESSES[address] = {"name": name, "chat_id": message.chat.id}
    save_json(WATCHED_ADDRESSES_FILE, WATCHED_ADDRESSES)
    await message.answer(f"✅ Alamat {address} dengan nama {name} berhasil ditambahkan!")

async def main():
    logging.info("🚀 Bot mulai berjalan...")
    load_data()
    asyncio.create_task(track_transactions())
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
