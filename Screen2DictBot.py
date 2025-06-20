from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

from telegram.ext import ApplicationBuilder, CommandHandler
from telegram.utils.request import Request

from bot_config import token
from bot_utils import *


# TODO: Testing
def start(update: Update, context: CallbackContext) -> None:
    """
    Start command handler.
    """
    message = update.message
    logger.info(f'/start command issued by {message.from_user.full_name}')
    sent = dlp.retry_or_none(context.bot.send_message, 2, 1,
                             message.from_user.id,
                             START_MESSAGE,
                             parse_mode=ParseMode.MARKDOWN
                             )
    if sent:
        logger.info(f'start message sent to {message.from_user.full_name}')
    else:
        logger.warning(f'failed sending start message to {message.from_user.full_name}')
        send_failure_note(message, context)
    return


def service(update: Update, context: CallbackContext) -> None:
    """
    This function is added to the dispatcher as a general handler for messages coming from the Bot API.
    If message has text and a word to look up can be obtained from it, dictionary lookup is performed;
    If message has image, compressed or uncompressed, that image is being processed;
    If none of the above, baffled message is issued to the original sender.
    """
    message = update.message
    if message.text:
        logger.info(f'incoming text message from {message.from_user.full_name}')
        word = obtain_query(message)
        if word:
            do_lookup(message, context, word)
        else:
            send_hint(message, context)
    elif message.photo or message.document:
        file = None
        if message.photo:
            logger.info(f'incoming photo from {message.from_user.full_name} detected by service handler.')
            file = context.bot.get_file(message.photo[0].file_id)
            send_compressed_confirmation(message, context)
        elif message.document:
            logger.info(f'incoming file from {message.from_user.full_name} detected by service handler.')
            file = context.bot.get_file(message.document.file_id)
            if file.file_path.endswith('.png') or file.file_path.endswith('.jpg'):
                send_uncompressed_confirmation(message, context)
            else:
                send_rejection_note(message, context)
                return
        logger.info(f'loading {file.file_path}')
        r = dlp.retry_or_none(rq.get, 3, 1, file.file_path, timeout=30)
        if not r:
            send_failure_note(message, context)
            return
        results_dict[message.from_user.id] = do_recognize(r, message, context)  # TODO: catch exception, notify user
        suggestions = results_dict[message.from_user.id]
        choices = generate_choices(suggestions)
        send_choices(message, context, choices)
        return
    else:
        send_baffled(message, context)
        return


def simulated_error(update: Update, context: CallbackContext):
    raise Exception('Intentional error for testing purposes')


def error_handler(update: Update, context: CallbackContext):
    """Handles errors raised by handlers."""
    logger.info(f'error handler invoked in relation to {update.message.text if update else None}')
    logger.error(f"Update {update.update_id if update else None} caused error: {context.error}")
    tb_logger.error(context.error, exc_info=True)


def main() -> None:
    # updater = Updater(token, request_kwargs={'read_timeout': 10})

    request = Request(read_timeout=10)
    app = ApplicationBuilder().token(token).request(request).build()

    # Get the dispatcher to register handlers
    # Then, we register each handler and the conditions the update must meet to trigger it
    # dispatcher = updater.dispatcher

    # Register commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("error", simulated_error))

    # Register handler for inline buttons
    app.add_handler(CallbackQueryHandler(button_tap))

    # Process any text message that is not a command, handle photos and files
    app.add_handler(MessageHandler(~Filters.command, service))

    app.add_error_handler(error_handler)

    # Start the Bot
    # updater.start_polling(poll_interval=2, timeout=10, bootstrap_retries=2)
    app.run_polling()

    # Run the bot until you press Ctrl-C
    # updater.idle()


if __name__ == '__main__':
    main()
