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
LAST_BLOCK_FILE = "last_block.json"

WATCHED_ADDRESSES = {}
LAST_BLOCK = {}

BLOCKSCOUT_API = "https://soneium.blockscout.com/api"

# Fungsi Load dan Save JSON
def load_json(filename, default_value):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_value

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)

def load_data():
    global WATCHED_ADDRESSES, LAST_BLOCK
    WATCHED_ADDRESSES = load_json(WATCHED_ADDRESSES_FILE, {})
    LAST_BLOCK = load_json(LAST_BLOCK_FILE, {})

async def fetch_transactions(address):
    url = f"{BLOCKSCOUT_API}?module=account&action=tokentx&address={address}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            try:
                return await response.json()
            except json.JSONDecodeError:
                return {"result": []}

async def set_initial_last_block():
    """ Set LAST_BLOCK ke blok terbaru agar tidak ada transaksi lama yang dikirim """
    global LAST_BLOCK
    for address in WATCHED_ADDRESSES.keys():
        transactions = await fetch_transactions(address)
        if transactions.get("result"):
            latest_block = max(int(tx["blockNumber"]) for tx in transactions["result"])
            LAST_BLOCK[address] = latest_block
    save_json(LAST_BLOCK_FILE, LAST_BLOCK)

async def track_transactions():
    while True:
        new_tx_count = 0
        notification_queue = asyncio.Queue()

        for address, data in WATCHED_ADDRESSES.items():
            transactions = await fetch_transactions(address)
            if transactions.get("result"):
                last_block = LAST_BLOCK.get(address, 0)
                for tx in transactions["result"]:
                    block_number = int(tx.get("blockNumber", 0))
                    
                    # Jika transaksi dari blok lama, abaikan
                    if block_number <= last_block:
                        continue
                    
                    # Simpan blok terbaru
                    LAST_BLOCK[address] = block_number

                    # Masukkan ke dalam antrian notifikasi
                    notification_queue.put_nowait((tx, address, data.get("name", "Unknown"), data["chat_id"]))
                    new_tx_count += 1

        if new_tx_count > 0:
            save_json(LAST_BLOCK_FILE, LAST_BLOCK)
            await send_notifications(notification_queue)

        logging.info(f"✅ {new_tx_count} transaksi baru terdeteksi.")
        await asyncio.sleep(30)

async def send_notifications(queue):
    while not queue.empty():
        tx, address, name, chat_id = await queue.get()
        try:
            await notify_transaction(tx, address, name, chat_id)
            await asyncio.sleep(2)  # Hindari flood limit
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
    await bot.send_message(chat_id, msg)

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
    await message.answer(
        "🚀 Selamat datang di Soneium Tracker!\n"
        "Gunakan <code>/add &lt;alamat&gt; &lt;nama&gt;</code> untuk mulai melacak transaksi."
    )

@dp.message(Command("add"))
async def add_address(message: Message):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("⚠ Gunakan format: <code>/add &lt;alamat&gt; &lt;nama&gt;</code>")
        return
    address, name = parts[1], parts[2]
    WATCHED_ADDRESSES[address] = {"name": name, "chat_id": message.chat.id}
    save_json(WATCHED_ADDRESSES_FILE, WATCHED_ADDRESSES)

    # Set blok terakhir untuk alamat baru agar tidak memunculkan transaksi lama
    transactions = await fetch_transactions(address)
    if transactions.get("result"):
        latest_block = max(int(tx["blockNumber"]) for tx in transactions["result"])
        LAST_BLOCK[address] = latest_block
        save_json(LAST_BLOCK_FILE, LAST_BLOCK)

    await message.answer(f"✅ Alamat <code>{address}</code> dengan nama <b>{name}</b> berhasil ditambahkan!")

async def main():
    logging.info("🚀 Bot mulai berjalan...")
    load_data()
    
    # Set LAST_BLOCK ke blok terbaru agar tidak ada transaksi lama
    await set_initial_last_block()
    
    asyncio.create_task(track_transactions())
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
