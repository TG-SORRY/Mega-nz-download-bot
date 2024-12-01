import os
import re
import shutil
import zipfile
import time
import asyncio
import logging
from pyrogram import Client, filters
from mega import Mega
from dotenv import load_dotenv
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize bot and Mega client
bot_token = os.getenv("BOT_TOKEN")
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")

app = Client("mega_download_bot", bot_token=bot_token, api_id=api_id, api_hash=api_hash)
mega = Mega()

try:
    mega_client = mega.login()
    logger.info("Logged into Mega.nz successfully.")
except Exception as e:
    logger.error(f"Error logging into Mega.nz: {e}")
    exit(1)

@app.on_message(filters.command("start"))
async def start_command(client, message):
    """Sends a welcome message with buttons."""
    welcome_text = (
        "👋 Hi there! I am your Mega.nz file downloader bot. \n\n"
        "🔗 Send me a Mega.nz link, and I'll download and send the file to you.\n\n"
        "For help or more information, use the buttons below."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
        [InlineKeyboardButton("📄 About", callback_data="about")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])
    await message.reply_text(welcome_text, reply_markup=keyboard)

@app.on_callback_query(filters.regex("help"))
async def help_callback(client, callback_query):
    """Displays help information."""
    help_text = (
        "🛠️ **Help**\n\n"
        "1. Send a valid Mega.nz link (file or folder).\n"
        "2. The bot will download and send the file to you.\n"
        "3. Files larger than 2 GB will be split into chunks for upload.\n"
        "4. For ZIP files, they will be extracted and sent as individual files.\n\n"
        "If you need assistance, contact support."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])
    await callback_query.answer()
    await callback_query.message.edit_text(help_text, reply_markup=keyboard)

@app.on_callback_query(filters.regex("about"))
async def about_callback(client, callback_query):
    """Displays information about the bot."""
    about_text = (
        "🔹 **About**\n\n"
        "I am a bot that helps you download files from Mega.nz and send them to you on Telegram.\n"
        "I can handle files up to 2 GB and will split larger files for uploading.\n\n"
        "Created with ❤️ by @NT_BOT_CHANNEL"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])
    await callback_query.answer()
    await callback_query.message.edit_text(about_text, reply_markup=keyboard)

@app.on_callback_query(filters.regex("cancel"))
async def cancel_callback(client, callback_query):
    """Handles cancellation of the current operation."""
    cancel_text = "❌ **Action Cancelled**\n\nThe current action has been cancelled. You can start over or request help if needed."
    await callback_query.answer()
    await callback_query.message.edit_text(cancel_text, reply_markup=None)

@app.on_callback_query(filters.regex("back"))
async def back_callback(client, callback_query):
    """Returns the user to the start message."""
    start_text = (
        "👋 Hi there! I am your Mega.nz file downloader bot. \n\n"
        "🔗 Send me a Mega.nz link, and I'll download and send the file to you.\n\n"
        "For help or more information, use the buttons below."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
        [InlineKeyboardButton("📄 About", callback_data="about")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])
    await callback_query.answer()
    await callback_query.message.edit_text(start_text, reply_markup=keyboard)

async def split_and_upload(file_path, chat_id, client, progress_message):
    """Splits large files and uploads each part."""
    chunk_size = 2 * 1024 * 1024 * 1024  # 2 GB
    file_size = os.path.getsize(file_path)
    base_name = os.path.basename(file_path)

    await progress_message.edit_text("The file is larger than 2 GB and will be split into chunks for upload. Please wait...")

    with open(file_path, 'rb') as f:
        chunk_index = 0
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break

            chunk_path = f"{file_path}.part{chunk_index}"
            with open(chunk_path, 'wb') as chunk_file:
                chunk_file.write(chunk)

            await client.send_document(
                chat_id=chat_id,
                document=chunk_path,
                caption=f"Part {chunk_index + 1}/{(file_size // chunk_size) + 1} of {base_name}"
            )
            os.remove(chunk_path)
            chunk_index += 1

async def update_progress(file_path, message, task_type):
    """Updates the progress of a task."""
    file_size = os.path.getsize(file_path)
    while os.path.exists(file_path):
        current_size = os.path.getsize(file_path)
        progress_percentage = (current_size / file_size) * 100 if file_size > 0 else 0
        progress_text = f"{task_type} Progress: {progress_percentage:.2f}% ({current_size // (1024 * 1024)}MB/{file_size // (1024 * 1024)}MB)"
        try:
            await message.edit_text(progress_text)
        except Exception:
            logger.warning("Failed to update progress message.")
            pass
        if current_size >= file_size:
            break
        await asyncio.sleep(1)

@app.on_message(filters.text & filters.regex(r"https://mega\.nz/(file|folder)/[A-Za-z0-9_-]+(?:#[A-Za-z0-9_-]+)?"))
async def download_file(client, message):
    """Handles file download and processing from Mega.nz links."""
    mega_link_match = re.search(r"https://mega\.nz/(file|folder)/[A-Za-z0-9_-]+(?:#[A-Za-z0-9_-]+)?", message.text)
    if not mega_link_match:
        await message.reply("❌ No valid Mega.nz link found.")
        return

    mega_link = mega_link_match.group(0)
    if "folder" in mega_link:
        await message.reply("❌ Folder downloads are not supported at the moment. Please provide a file link.")
        return

    dest_path = "downloads/"
    os.makedirs(dest_path, exist_ok=True)

    progress_message = await message.reply("Starting download...")

    try:
        start_time = time.time()
        file_path = mega_client.download_url(mega_link, dest_path=dest_path)
        elapsed_time = time.time() - start_time

        await update_progress(file_path, progress_message, "Download")

        if zipfile.is_zipfile(file_path):
            extracted_path = os.path.join(dest_path, "extracted")
            os.makedirs(extracted_path, exist_ok=True)

            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(extracted_path)

            os.remove(file_path)

            await progress_message.edit_text("Uploading extracted files...")
            for root, _, files in os.walk(extracted_path):
                for file in files:
                    file_to_send = os.path.join(root, file)
                    await client.send_document(
                        chat_id=message.chat.id,
                        document=file_to_send,
                        caption=f"Extracted file: {file}"
                    )
                    os.remove(file_to_send)

            os.rmdir(extracted_path)
        else:
            if os.path.getsize(file_path) > 2 * 1024 * 1024 * 1024:
                await split_and_upload(file_path, message.chat.id, client, progress_message)
            else:
                await progress_message.edit_text("Uploading file...")
                await client.send_document(
                    chat_id=message.chat.id,
                    document=file_path,
                    caption="❤️ Created by @NT_BOT_CHANNEL"
                )
                os.remove(file_path)

        await progress_message.edit_text(f"Task completed in {elapsed_time:.2f} seconds.")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        await progress_message.edit_text(f"❌ An error occurred while processing your link: {e}")

if __name__ == "__main__":
    app.run()
