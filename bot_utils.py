# https://github.com/python-telegram-bot/python-telegram-bot/discussions/2876#discussion-3831621
import logging
from datetime import datetime as dt
from io import BytesIO
import requests as rq
from telegram import InlineKeyboardMarkup, InlineKeyboardButton  # , ParseMode
from telegram.constants import ParseMode

from screen2text import DictLookup as dlp, tb_logger

results_dict = {}  # store bot recognition results

# https://www.youtube.com/watch?v=9L77QExPmI0
# TODO: Make it roll
logging.basicConfig(format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
                    filename=f'logs/{__name__}_{dt.now():%Y%m%d-%H%M%S}.log', encoding='utf-8',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)

tb_logger.name = f'{__name__}_tb_logger'
tb_logger.handlers.clear()
exception_handler = logging.FileHandler(f'logs/{__name__}_{dt.now():%Y%m%d-%H%M%S}_exception.log', encoding='utf-8')
exception_handler.setLevel(logging.ERROR)
exception_formatter = logging.Formatter('\n%(asctime)s [%(name)s] %(levelname)s: %(message)s\n%(exc_info)s')
exception_handler.setFormatter(exception_formatter)
tb_logger.addHandler(exception_handler)

START_MESSAGE = 'Hello! To start using the service, please send a tightly cropped image of a word in Thai script or ' \
                'enter lookup and the word to look up (ex.: lookup เกล้า)' \
                '\n\nCurrent experimental implementation is focused on Thai language drawing on Thai-based [Longdo ' \
                'Dictionary](https://dict.longdo.com/index.php). It is built in [Python](https://www.python.org/) ' \
                'programming language using [python-telegram-bot](https://github.com/python-telegram-bot) library and' \
                '[Tesseract-OCR](https://tesseract-ocr.github.io/tessdoc/Installation.html) in ' \
                '[pytesseract](https://pypi.org/project/pytesseract/) wrapper, as well as [NECTEC Lexitron](' \
                'https://www.nectec.or.th/innovation/innovation-software/lexitron.html) and [PyThaiNLP](' \
                'https://pythainlp.github.io/) for spelling verification, [Pillow](' \
                'https://github.com/python-pillow/Pillow/) for image processing, [requests](' \
                'https://requests.readthedocs.io) and [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) ' \
                'for web content processing, and others. Many thanks to creators and maintainers of all these ' \
                'resources!\nFeel free to [contact the developer](https://t.me/jornjat) with any inquiries.\n\n'
HINT_MESSAGE = 'Please submit a tightly cropped image of a word in Thai script, enter suggestion number if known, ' \
               'or enter a word preceded by \"lookup\" and a whitespace (ex.: lookup เกล้า) to look it up in the dictionary.' \
               '\n\n [contact the sentient being behind this bot](https://t.me/jornjat)'
MAX_LENGTH = 4096
LOOKUP_TAIL = '...\nclick the link below for more'
FAILURE = 'something went wrong.'


def send_compressed_confirmation(message, context):
    """
    Notifies user that submitted image is compressed and being pulled into the system for processing, retrying once
    in case of initial failure.
    :param message: instance attribute message of telegram.update.Update extracted from the initiating update.
    :param context: instance of telegram.ext.CallbackContext containing the running Bot as a property.
    :returns: sent message in case of success, None otherwise.
    """
    sent = dlp.retry_or_none(context.bot.send_message, 2, 1,
                             message.from_user.id,
                             'Loading compressed image from server...'
                             )
    logger.info('compressed confirmation sent successfully' if sent else FAILURE)
    return sent


def send_uncompressed_confirmation(message, context):
    """
    Notifies user that submitted image is being pulled into the system for processing with no compression,
    retrying once in case of initial failure.
    :param message: instance attribute message of telegram.update.Update extracted from the initiating update.
    :param context: instance of telegram.ext.CallbackContext containing the running Bot as a property.
    :returns: sent message in case of success, None otherwise.
    """
    sent = dlp.retry_or_none(context.bot.send_message, 2, 1,
                             message.from_user.id,
                             'Loading uncompressed image file from server...'
                             )
    logger.info('uncompressed confirmation sent successfully' if sent else FAILURE)
    return sent


def send_processing_note(message, context):
    """
    Notifies user that submitted image has been successfully loaded and OCR is attempted on it,
    retrying once in case of initial failure.
    :param message: instance attribute message of telegram.update.Update extracted from the initiating update.
    :param context: instance of telegram.ext.CallbackContext containing the running Bot as a property.
    :returns: sent message in case of success, None otherwise.
    """
    sent = dlp.retry_or_none(context.bot.send_message, 2, 1,
                             message.from_user.id,
                             'File loaded. Attempting recognition...'
                             )
    logger.info('processing note sent successfully' if sent else FAILURE)
    return sent


def send_rejection_note(message, context):
    """
    Notifies user that submitted object could not be processed due to unsupported type/extension,
    retrying once in case of initial failure.
    :param message: instance attribute message of telegram.update.Update extracted from the initiating update.
    :param context: instance of telegram.ext.CallbackContext containing the running Bot as a property.
    :returns: sent message in case of success, None otherwise.
    """
    logger.info('unsupported file extension, sending rejection note...')
    sent = dlp.retry_or_none(context.bot.send_message, 2, 1,
                             message.from_user.id,
                             'File could not be accepted: unexpected type based on extension. '
                             'Currently supported formats are png and jpg.'
                             )
    logger.info(f'rejection note sent successfully to {message.from_user.full_name}' if sent else FAILURE)
    return sent


def send_failure_note(message, context):
    """
    Notifies user that requested action could not be successfully accomplished,
    retrying once in case of initial failure.
    :param message: instance attribute message of telegram.update.Update extracted from the initiating update.
    :param context: instance of telegram.ext.CallbackContext containing the running Bot as a property.
    :returns: sent message in case of success, None otherwise.
    """
    sent = dlp.retry_or_none(
        context.bot.send_message, 2, 1,
        message.from_user.id,
        'Something went wrong... Please consider trying one more time '
        'or notifying @jornjat the maintainer if the error persists.'
    )
    logger.info(f'failure note sent successfully to {message.from_user.full_name}' if sent else FAILURE)
    return sent


def do_recognize(r: rq.Response, message, context) -> list[tuple[str, float]]:
    """
    Pulls response content into PIL Image object, runs recognition and generates suggestions with
    provisional confidence rating as a list of tuples.
    :param r: response object obtained from call to the telegram API using requests library.
    :param message: instance attribute message of telegram.update.Update extracted from the initiating update.
    :param context: instance of telegram.ext.CallbackContext containing the running Bot as a property.
    :return: a list of rated suggestions as tuples or empty list in case of failure.
    """
    x = dlp()
    try:
        x.load_image(BytesIO(r.content))
    except Exception as e:
        logger.error(f"Couldn't open the image file: {e}")
        tb_logger.exception(e)
        return []
    logger.info('initiating recognition...')
    send_processing_note(message, context)
    try:
        x.threads_recognize(lang='tha', kind='line')
    except Exception as e:
        logger.error(f"recognition error: {e}")
        tb_logger.exception(e)
        return []
    x.generate_word_suggestions()
    logger.info(f'image recognition produced {len(x.suggestions)} suggestion(s)')
    return x.suggestions


def generate_choices(suggestions: list[tuple[str, float]]) -> str:
    """
    Builds a message with numbered suggested recognition results for user to choose which one to look up
    or informs them of ultimate failure to produce any.
    :param suggestions: a list of suggestion tuples returned by `do_recognize`.
    :return: text to be sent to user.
    """
    logger.info('generating choices')
    choices = 'Choose suggestion number to look up:\n' if (
        suggestions) else 'No meaningful recognition results could be produced.'
    for i in range(0, len(suggestions)):
        option = suggestions[i]
        choices += f'{i} : {option[0]} ({option[1]})\n'
    return choices


def send_choices(message, context, choices: str):
    """
    Sends the message with numbered suggested recognition results for user to choose which one to look up
    or informs them of ultimate failure to produce any.
    :param message: instance attribute message of telegram.update.Update extracted from the initiating update.
    :param context: instance of telegram.ext.CallbackContext containing the running Bot as a property.
    :param choices: text of the message to be sent.
    :returns: sent message in case of success, None otherwise.
    """
    logger.info(f'sending choices to {message.from_user.full_name}')
    sent = dlp.retry_or_none(context.bot.send_message, 2, 1,
                             message.from_user.id,
                             choices
                             )
    logger.info('choices sent successfully' if sent else FAILURE)
    return sent


def obtain_query(message) -> str:
    """
    Checks the incoming message text to see if it is a digit - which is then used as index to get corresponding entry
    from the list of OCR-based suggestions - or a lookup request, in which case the phrase to look up
    is obtained right from the message text.
    :param message: instance attribute message of telegram.update.Update extracted from the initiating update.
    :return: the query to look up.
    """
    query = ''
    text = message.text
    if text.isdigit():
        if message.from_user.id in results_dict.keys():
            their_results = results_dict[message.from_user.id]
            result_index = int(message.text)
            if result_index < len(their_results):
                query = their_results[result_index][0]
    if text.lower().startswith('lookup '):
        query = text.replace('lookup ', '')
    return query


async def do_lookup(message, context, query: str):
    """
    Performs lookup for the query in online dictionary, prepares resulting output and sends it to user as
    formatted markdown or plain text as a fallback option.
    :param message: instance attribute message of telegram.update.Update extracted from the initiating update.
    :param context: instance of telegram.ext.CallbackContext containing the running Bot as a property.
    :param query: a text to look up.
    :return: sent message if anything managed to get through (albeit failure note) or None in case of ultimate failure.
    """
    logger.info(f'got a text to look up, initiating lookup for {query}')
    sent = await dlp.retry_or_none(context.bot.send_message, 2, 1,
                             message.from_user.id,
                             f'looking up {query} ...'
                             )
    logger.info(f'notification sent successfully to {message.from_user.full_name}' if sent else FAILURE)
    x = dlp()
    if not x.lookup(query):
        return send_failure_note(message, context)
    output = trim_output(x.output_markdown())
    logger.info(
        f'markdown output generated ({output[:128] if len(output) > 128 else output} ...)'
        .replace('\n', ' ')
    )
    sent = await dlp.retry_or_none(context.bot.send_message, 2, 1,
                             message.from_user.id,
                             output,
                             parse_mode=ParseMode.MARKDOWN,
                             timeout=15
                             )
    logger.info(f'and sent successfully to {message.from_user.full_name}' if sent else FAILURE)
    if not sent:
        output = trim_output(x.output_plain())
        logger.info(
            f'plain output generated ({output[:128] if len(output) > 128 else output} ...)'
            .replace('\n', ' ')
        )
        sent = await dlp.retry_or_none(context.bot.send_message, 2, 1,
                                 message.from_user.id,
                                 output,
                                 timeout=15
                                 )
        logger.info(f'and sent successfully to {message.from_user.full_name}' if sent else FAILURE)
    if not sent:
        await send_failure_note(message, context)
    return sent


def trim_output(output: str) -> str:
    """
    Checks if the output text size exceeds the maximum length allowed by Telegram and, if true, trims it neatly to the
    last fitting newline, also appending an endnote informing user that more content is available at the dictionary
    webpage and encouraging them to follow the link.
    :param output: the output text.
    :return: trimmed output or unchanged if max length was not exceeded.
    """
    if len(output) > MAX_LENGTH:
        output = output[:4096 - len(LOOKUP_TAIL)]
        last_newline = output.rfind('\n')
        return output[:last_newline] + LOOKUP_TAIL
    return output


def send_hint(message, context):
    """
    In case no action could be taken based on the incoming message, sends user a hint on how to use the service,
    retrying once on initial failure.
    :param message: instance attribute message of telegram.update.Update extracted from the initiating update.
    :param context: instance of telegram.ext.CallbackContext containing the running Bot as a property.
    :returns: sent message in case of success, None otherwise.
    """
    logger.info('no meaningful action could be taken based on the message text, sending hint...')
    sent = dlp.retry_or_none(context.bot.send_message, 2, 1,
                             message.from_user.id,
                             HINT_MESSAGE,
                             parse_mode=ParseMode.MARKDOWN
                             )
    logger.info(f'hint message sent to {message.from_user.full_name}' if sent else FAILURE)
    return sent


def send_baffled(message, context):
    """
    In case incoming message cannot be parsed in any meaningful way, sends the user a request for clarification,
    retrying once on initial failure.
    :param message: instance attribute message of telegram.update.Update extracted from the initiating update.
    :param context: instance of telegram.ext.CallbackContext containing the running Bot as a property.
    :returns: sent message in case of success, None otherwise.
    """
    logger.info(f'unknown matter encountered in the message, sending baffled note...')
    sent = dlp.retry_or_none(context.bot.send_message, 2, 1,
                             message.from_user.id,
                             'What is it?'
                             )
    logger.info('sent successfully' if sent else FAILURE)
    return sent
