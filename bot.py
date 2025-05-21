import logging
import feedparser
import os
import time
from telegram import Update, BotCommand, Bot
from telegram.ext import Application, CommandHandler, CallbackContext, JobQueue
from telegram.constants import ParseMode
import html # For unescaping HTML entities if needed

# --- Configuration ---
# IMPORTANT: Replace with your actual Bot Token and Chat ID
# It's highly recommended to use environment variables for sensitive data
TELEGRAM_TOKEN = os.environ.get("BOT_TOKEN")
TARGET_CHAT_ID = os.environ.get("CHAT_ID") # Your personal chat ID or a group/channel ID

RSS_FEED_URL = "https://rss.app/feeds/OUYIM0VGlxqKueAS.xml"
CHECK_INTERVAL_SECONDS = 300  # Check every 5 minutes
SENT_ITEMS_FILE = "sent_rss_items.txt" # File to store IDs of sent items
MAX_MESSAGE_LENGTH = 4096 # Telegram's message length limit

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- State Management (Sent Items) ---
sent_item_ids = set()

def load_sent_items():
    """Loads sent item IDs from the file."""
    global sent_item_ids
    if os.path.exists(SENT_ITEMS_FILE):
        with open(SENT_ITEMS_FILE, "r") as f:
            sent_item_ids = {line.strip() for line in f if line.strip()}
    logger.info(f"Loaded {len(sent_item_ids)} sent item IDs from {SENT_ITEMS_FILE}")

def save_sent_item(item_id: str):
    """Saves a new sent item ID to the file and set."""
    sent_item_ids.add(item_id)
    with open(SENT_ITEMS_FILE, "a") as f:
        f.write(item_id + "\n")

# --- RSS Fetching and Sending Logic ---
async def check_rss_feed(context: CallbackContext):
    """Fetches the RSS feed, checks for new items, and sends them."""
    if not context.bot_data.get('chat_id_confirmed', False) and not TARGET_CHAT_ID:
        logger.warning("TARGET_CHAT_ID not set and no /start command received yet. Skipping RSS check.")
        return

    current_target_chat_id = TARGET_CHAT_ID or context.bot_data.get('user_chat_id')
    if not current_target_chat_id:
        logger.error("No target chat ID available to send messages.")
        return

    logger.info(f"Checking RSS feed: {RSS_FEED_URL}")
    try:
        feed = feedparser.parse(RSS_FEED_URL)
        if feed.bozo:
            logger.error(f"Error parsing RSS feed: {feed.bozo_exception}")
            # Optionally send an error message to the admin/chat
            # await context.bot.send_message(chat_id=current_target_chat_id, text=f"⚠️ Error parsing RSS feed: {RSS_FEED_URL}")
            return

        new_items_found = 0
        for entry in reversed(feed.entries): # Process oldest new items first
            # Determine a unique identifier for the item
            item_id = entry.get("id", entry.get("link")) # 'id' is preferred, fallback to 'link'
            if not item_id:
                logger.warning(f"Entry without id or link: {entry.get('title', 'N/A')}")
                continue

            if item_id not in sent_item_ids:
                logger.info(f"New item found: {entry.title}")

                title = entry.get("title", "No Title")
                link = entry.get("link", "")
                description = entry.get("summary", entry.get("description", "")) # summary often preferred

                # Clean up description (optional, depends on feed quality)
                # description = html.unescape(description) # Basic unescaping
                # For more complex HTML, consider BeautifulSoup to strip tags or reformat

                message = f"<b>{html.escape(title)}</b>\n\n"
                if description:
                    # Truncate description to avoid exceeding message limits
                    # Max length for caption is 1024, for message 4096.
                    # Let's keep it reasonably short.
                    max_desc_len = MAX_MESSAGE_LENGTH - len(message) - len(link) - 50 # 50 for safety and formatting
                    if len(description) > max_desc_len:
                        description = description[:max_desc_len] + "..."
                    message += f"{description}\n\n" # Telegram will parse common HTML tags like <b>, <i>, <a>

                if link:
                    message += f'<a href="{html.escape(link)}">Read more</a>'
                else:
                    message += "No link available."


                try:
                    await context.bot.send_message(
                        chat_id=current_target_chat_id,
                        text=message,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=False # Set to True if you don't want link previews
                    )
                    save_sent_item(item_id)
                    new_items_found += 1
                    await asyncio.sleep(1) # Small delay to avoid hitting rate limits if many new items
                except Exception as e:
                    logger.error(f"Error sending Telegram message for '{title}': {e}")
                    # If message is too long, try sending a shorter version
                    if "message is too long" in str(e).lower():
                        try:
                            short_message = f"<b>{html.escape(title)}</b>\n\n<a href='{html.escape(link)}'>Read more</a>"
                            await context.bot.send_message(
                                chat_id=current_target_chat_id,
                                text=short_message,
                                parse_mode=ParseMode.HTML
                            )
                            save_sent_item(item_id)
                            new_items_found += 1
                        except Exception as e_short:
                            logger.error(f"Error sending SHORTER Telegram message for '{title}': {e_short}")
                    # Potentially add more specific error handling here

        if new_items_found > 0:
            logger.info(f"Sent {new_items_found} new items to chat {current_target_chat_id}.")
        else:
            logger.info("No new items found in this check.")

    except Exception as e:
        logger.error(f"An error occurred during RSS check: {e}")
        # await context.bot.send_message(chat_id=current_target_chat_id, text=f"⚠️ An error occurred while checking RSS: {e}")


# --- Telegram Bot Command Handlers ---
async def start(update: Update, context: CallbackContext):
    """Sends a welcome message and instructions, captures chat_id."""
    user_chat_id = update.effective_chat.id
    context.bot_data['user_chat_id'] = str(user_chat_id) # Store for job
    context.bot_data['chat_id_confirmed'] = True

    welcome_message = (
        "👋 Hello! I am your Updated Biharan Feed Bot.\n\n"
        "I will periodically check the RSS feed and send new items.\n\"
    )
    if TARGET_CHAT_ID:T_CHAT_ID:
         welcome_message = (
            f"👋 Hello! I am your RSS Feed Bot.\n\n"
            f"I am configured to send updates to chat ID: `{TARGET_CHAT_ID}`.\n"
            "I will periodically check the RSS feed and send new items there."
        )

    await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN_V2)
    logger.info(f"/start command received from chat_id: {user_chat_id}. Bot will now post to {TARGET_CHAT_ID or user_chat_id}")

    # Manually trigger the first check if desired, or wait for the job
    # await check_rss_feed(context)


async def set_commands(application: Application):
    """Sets the bot commands."""
    commands = [
        BotCommand("start", "Start the bot and get chat ID"),
    ]
    await application.bot.set_my_commands(commands)

# --- Main Bot Setup ---
def main() -> None:
    """Starts the bot."""
    if not TELEGRAM_TOKEN:
        logger.critical("BOT_TOKEN environment variable not set. Exiting.")
        return
    if not TARGET_CHAT_ID:
        logger.warning("CHAT_ID environment variable not set. "
                       "The bot will only send messages to the chat where /start is first used.")

    load_sent_items()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Store chat_id_confirmed flag in bot_data, initially False
    application.bot_data['chat_id_confirmed'] = False
    if TARGET_CHAT_ID: # If configured via env var, consider it confirmed
        application.bot_data['chat_id_confirmed'] = True
        application.bot_data['user_chat_id'] = TARGET_CHAT_ID # Use this as the primary target

    # Add command handlers
    application.add_handler(CommandHandler("start", start))

    # Setup job queue for periodic RSS checks
    job_queue = application.job_queue
    # Run the first check shortly after start, then repeat
    job_queue.run_repeating(check_rss_feed, interval=CHECK_INTERVAL_SECONDS, first=10) # First check after 10s

    # Set bot commands (optional, but good practice)
    application.post_init = set_commands

    logger.info("Bot starting...")
    application.run_polling()

if __name__ == "__main__":
    # For asyncio related parts when running directly
    import asyncio
    asyncio.run(main())
