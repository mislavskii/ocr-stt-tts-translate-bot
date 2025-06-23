import tracemalloc
tracemalloc.start()

import os
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# from dotenv import load_dotenv

from bot_utils import *
from auth import *

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f'/start command issued by {update.effective_user.full_name}')
    try:
        await update.message.reply_text(
            START_MESSAGE,
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f'start message sent to {update.effective_user.full_name}')
    except Exception as e:
        logger.warning(f'failed sending start message to {update.effective_user.full_name}: {e}')
        await send_failure_note(update.message, context)


async def service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message.text:
        logger.info(f'incoming text message from {update.effective_user.full_name}')
        word = obtain_query(message)
        if word:
            await do_lookup(message, context, word)
        else:
            await send_hint(message, context)
    elif message.photo or message.document:
        file = None
        if message.photo:
            logger.info(f'incoming photo from {update.effective_user.full_name} detected by service handler.')
            file = await context.bot.get_file(message.photo[0].file_id)
            await send_compressed_confirmation(message, context)
        elif message.document:
            logger.info(f'incoming file from {update.effective_user.full_name} detected by service handler.')
            file = await context.bot.get_file(message.document.file_id)
            if file.file_path.endswith('.png') or file.file_path.endswith('.jpg'):
                await send_uncompressed_confirmation(message, context)
            else:
                await send_rejection_note(message, context)
                return
        logger.info(f'loading {file.file_path}')
        r = await dlp.retry_or_none(rq.get, 3, 1, file.file_path, timeout=30)
        if not r:
            await send_failure_note(message, context)
            return
        results_dict[message.from_user.id] = await do_recognize(r, message, context)  # TODO: catch exception, notify user
        suggestions = results_dict[message.from_user.id]
        choices = generate_choices(suggestions)
        await send_choices(message, context, choices)
        return
    else:
        await send_baffled(message, context)
        return

async def simulated_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raise Exception('Intentional error for testing purposes')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = getattr(update, "message", None)
    logger.info(f'error handler invoked in relation to {getattr(message, "text", "unknown message")}')
    logger.error(f"Update {getattr(update, 'update_id', None)} caused error: {context.error}")
    tb_logger.error(context.error, exc_info=True)
    # Optionally send a message to the user
    if message:
        await send_failure_note(message, context)
    

def main() -> None:
    app = ApplicationBuilder().token(TOKEN).read_timeout(15).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("error", simulated_error))
    app.add_handler(MessageHandler(filters.ALL, service))

    app.add_error_handler(error_handler)

    app.run_polling()

if __name__ == '__main__':
    main()