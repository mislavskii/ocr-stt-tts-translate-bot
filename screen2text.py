import asyncio
import functools
import inspect
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime as dt
from typing import Any
import pytesseract
import requests as rq
from IPython.display import HTML
from IPython.display import display
from PIL import ImageGrab, Image
from bs4 import BeautifulSoup as bs
from pythainlp import correct

pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

# logging.basicConfig(format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
#                     filename=f'logs/{__name__}.log', encoding='utf-8',
#                     level=logging.INFO)
logger = logging.getLogger(__name__)

tb_logger = logging.getLogger(f'{__name__}_tb_logger')
exception_handler = logging.FileHandler(f'logs/{__name__}_exception.log', encoding='utf-8')
exception_handler.setLevel(logging.ERROR)
exception_formatter = logging.Formatter('\n%(asctime)s [%(name)s] %(levelname)s: %(message)s\n%(exc_info)s')
exception_handler.setFormatter(exception_formatter)
tb_logger.addHandler(exception_handler)
tb_logger.propagate = False


class ClipImg2Text:
    config_codes = """  0    Orientation and script detection (OSD) only.
      1    Automatic page segmentation with OSD.
      2    Automatic page segmentation, but no OSD, or OCR.
      3    Fully automatic page segmentation, but no OSD. (Default)
      4    Assume a single column of text of variable sizes.
      5    Assume a single uniform block of vertically aligned text.
      6    Assume a single uniform block of text.
      7    Treat the image as a single text line.
      8    Treat the image as a single word.
      9    Treat the image as a single word in a circle.
     10    Treat the image as a single character.
     11    Sparse text. Find as much text as possible in no particular order.
     12    Sparse text with OSD.
     13    Raw line. Treat the image as a single text line, bypassing hacks that are Tesseract-specific."""
    config_dict = {int(entry[0]): entry[1] for entry in
                   [entry.strip().split('    ') for entry in config_codes.split('\n')]}
    corpus_path = 'resources/dictionary.db'
    # any file with Thai dictionary words one per line will do
    # (the bigger - the better, this one is 42K+ from NECTEC's Lexitron)

    @staticmethod
    def get_freqs(strings):
        """
        takes a collection of :strings: and returns a list of tuples mapping strings to their relative frequencies,
        sorted in descending order
        """
        freqs = {}
        for word in strings:
            freqs[word] = freqs.get(word, 0) + 1
        total = sum(freqs.values())
        for key, val in freqs.items():
            freqs[key] = round(val / total, 2)
        return sorted(freqs.items(), key=lambda item: item[1], reverse=True)

    def __init__(self):
        self.suggestions = []
        self.im = None
        self.bim = None
        self.out_texts = {}
        self.bims = {}
        self.validated_words = {}
        if not os.path.exists('bims'):
            os.mkdir('bims')

    def grab(self):
        self.bim = None
        im = ImageGrab.grabclipboard()
        if im:
            self.im = im  # .convert("L")
        else:
            print('Looks like there was no image to grab. Please check the clipboard contents!')
            return

    def load_image(self, path):
        self.im = Image.open(path)

    def binarize(self, skew=1.0):
        im = self.im.copy().convert("L")
        lightness = len(im.getdata()) / sum(im.getdata())  # this may result in ZeroDivisionError
        threshold = sum(im.getextrema()) / 2 * skew
        xs, ys = im.size
        for x in range(xs):
            for y in range(ys):
                if im.getpixel((x, y)) > threshold:
                    px = 255  # if lightness > 0.25 else 0
                else:
                    px = 0  # if lightness > 0.25 else 255
                im.putpixel((x, y), px)
        return im

    def fan_binarize(self):
        self.bims = {}
        for skew in range(60, 155, 5):
            bim = self.binarize(skew / 100)
            bim.save(f'bims/{skew}.png')
            self.bims[skew] = bim

    def recognize_original(self, lang='tha', config='--psm 7'):
        return pytesseract.image_to_string(self.im, config=config, lang=lang).strip()

    def fan_recognize_original(self, lang='tha'):
        for code in list(self.config_dict.keys())[3:]:
            try:
                self.out_texts[code] = self.recognize_original(lang=lang, config=f'--psm {code}')
            except Exception as e:
                # texts[code] = e.__str__()
                continue

    def recognize_bin(self, skew=1.0, lang='tha', config='--psm 7'):
        return pytesseract.image_to_string(self.binarize(skew), config=config, lang=lang).strip()

    def fan_recognize_bin(self, lang='tha'):
        for code in list(self.config_dict.keys())[3:]:
            for skew in list(range(75, 140, 5)):
                key = code * 1000 + skew
                self.out_texts[key] = self.recognize_bin(skew / 100, lang=lang, config=f'--psm {code}')

    def fan_recognize(self, lang, psm):
        """For given psm value, recognizing original image and binarized in a range of threshold skews
        from self.bims, which will have to be already prepared to avoid repeated binarization
        in concurrent recognizing"""
        self.out_texts[psm] = self.recognize_original(lang=lang, config=f'--psm {psm}')
        for skew, image in self.bims.items():
            key = psm * 1000 + skew
            self.out_texts[key] = pytesseract.image_to_string(image, lang=lang, config=f'--psm {psm}').strip()
        # print(len(self.out_texts))

    def threads_recognize(self, lang, kind=None):
        """Recognizing the image, both original and binarized, in a range of psm values as per :kind:,
        applying a range of threshold skews as defined in `fan_recognize` run in a separate thread
        for each psm value 
        """
        self.kind = kind
        self.fan_binarize()
        lang = lang
        self.out_texts.clear()
        psms = list(self.config_dict.keys())[3:]
        psms.insert(0, 1)
        if kind == 'block':
            psms = (1, 3, 4, 6, 11, 12, 13)
        if kind == 'line':
            psms = (1, 3, 7, 11, 12, 13)
        if kind == 'word':
            psms = (1, 3, 7, 8, 11, 12, 13)
        threads = [threading.Thread(target=self.fan_recognize, args=(lang, psm), name=f't_{psm}') for psm in psms]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    def validate_words(self):
        """
        checks recognition results gathered in out_texts against corpus.
        """
        self.validated_words.clear()
        try:
            conn = sqlite3.connect(self.corpus_path)
            for key, text in self.out_texts.items():
                if text and len(text) > 1:
                    cur = conn.cursor()
                    cur.execute(
                        'SELECT 1 FROM lexitron_thai WHERE instr(entry, ?) > 0 LIMIT 1', (text,)
                    )
                    exists = cur.fetchone() is not None
                    if exists:
                        self.validated_words[key] = text
                    cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"error accessing corpus: {e}")
            tb_logger.exception(e)

    def generate_word_suggestions(self):
        self.validate_words()
        self.suggestions = self.get_freqs(self.validated_words.values())
        out_text_freqs = self.get_freqs([item for item in self.out_texts.values() if item and '\n' not in item])
        if self.suggestions:
            leader = self.suggestions[0][0]
            leader_general_score = {item[0]: item[1] for item in out_text_freqs}[leader]
            mean_score = sum([item[1] for item in self.suggestions]) / len(self.suggestions)
            enrichment_floor = min(mean_score, leader_general_score)
            noise_ceiling = self.suggestions[0][1] * .04
            self.suggestions = [item for item in self.suggestions if item[1] > noise_ceiling]
        else:
            enrichment_floor = 0.01
        candidate_cap = 3
        top_texts = out_text_freqs[:candidate_cap
                    ] if len(out_text_freqs) > candidate_cap else out_text_freqs
        for candidate in top_texts:
            if candidate[0] not in [item[0] for item in self.suggestions] and candidate[1] > enrichment_floor:
                self.suggestions.append(candidate)
                corrected = correct(candidate[0])
                if corrected not in [item[0] for item in self.suggestions]:
                    self.suggestions.append((corrected, -1))
        self.suggestions.sort(key=lambda item: item[1], reverse=True)

    def generate_line_suggestions(self):  # TODO: add to the bot?
        out_text_freqs = self.get_freqs([item for item in self.out_texts.values() if item and '\n' not in item])
        out_text_freqs.sort(key=lambda item: item[1], reverse=True)
        self.suggestions = out_text_freqs[:7]

    def inspect_results(self):  # TODO: Adapt for blocks
        if not self.im:
            return
        display(self.im)
        for key, text in sorted(self.out_texts.items(), key=lambda item: item[0]):
            if key <= 13:
                if self.kind in ('word', 'line', None):
                    text = text.replace('\n', '')
                    end = ', '
                else:
                    text = '\n' * 2 + text
                    end = '\n' * 2
                print(f'{key}:', text, end=end)
        print()

        print(f"\n{self.im.getextrema()} -> {self.im.convert('L').getextrema()}")
        for skew, image in self.bims.items():
            print(f'\n{skew / 100}')
            display(image)
            for key, text in sorted(self.out_texts.items(), key=lambda item: item[0]):
                if str(key).endswith(str(skew)):
                    if self.kind in ('word', 'line', None):
                        text = text.replace('\n', '')
                        end = ', '
                    else:
                        text = '\n' * 2 + text
                        end = '\n' * 2
                    print(f'{key}:', text, end=end)
            print()


class DictLookup(ClipImg2Text):
    dic_url = 'https://dict2013.longdo.com/search/'

    @staticmethod
    async def retry_or_none(func, attempts: int, seconds: int | float, *args, **kwargs) -> Any | None:
        """
        Tries to call the supplied function repeatedly until success or exhaustion of attempts, logging error on exception.
        :param func: function to call
        :param attempts: total number of calls
        :param seconds: wait time before next call
        :param args: arguments for the called function
        :param kwargs: keyword arguments for the called function
        :return: whatever the called function should return or None in case of ultimate failure
        """
        for i in range(attempts):
            try:
                if inspect.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    # Run the sync function in a thread pool executor
                    loop = asyncio.get_running_loop()
                    wrapped_func = functools.partial(func, *args, **kwargs)
                    return await loop.run_in_executor(None, wrapped_func)
            except Exception as e:
                logger.error(f"Attempt {i+1}/{attempts} failed: {e}")
                tb_logger.exception(e)
                if i < attempts - 1:
                    logger.info('Retrying...')
                    await asyncio.sleep(seconds)
        return None

    def __init__(self):
        super().__init__()
        self.word = None
        self.soup = None

    async def lookup(self, word):
        self.soup = None
        self.word = word
        logger.info(f'Looking up {word}... ')
        response = await self.retry_or_none(rq.get, 3, 1, self.dic_url + word, timeout=15)
        if not response or response.status_code != 200:
            logger.warning("Couldn't fetch.")
            return False
        response.encoding = 'utf-8'
        self.soup = bs(response.text, features="html.parser")
        return True

    def output_html(self):
        headers = self.soup.find_all('td', attrs={'class': 'search-table-header'})
        tables = self.soup.find_all('table', attrs={'class': 'search-result-table'})
        style = '''<style>table {width: 60%;} </style>'''
        content = f'<h4>Lookup results for "<strong>{self.word}</strong>"</h4>'
        for header, table in zip(headers, tables):
            text = header.text
            if not ('Subtitles' in text or 'German-Thai:' in text or 'French-Thai:' in text):
                content += f'<h5>{header.text}</h5>\n'
                content += str(table).replace("black", "white") + '\n'

        with open('html/template.html', 'r', encoding='utf-8') as template:
            html = template.read()

        with open('html/out.html', 'w', encoding='utf-8') as out:
            out.write(html.replace('%content%', content))

        display(HTML(style + content))

    def output_markdown(self):
        if not self.soup:
            return ''
        output = []
        headers = self.soup.find_all('td', attrs={'class': 'search-table-header'})
        tables = self.soup.find_all('table', attrs={'class': 'search-result-table'})
        output.append(f'Lookup results for **{self.word}** from [Longdo Dictionary]({self.dic_url + self.word})\n')
        for header, table in sorted(
                zip(headers, tables),
                key=lambda x: ('Longdo Dictionary' in x[0].text) or ('HOPE Dictionary' in x[0].text)
        ):
            text = header.text.replace("**", "")
            if not ('Subtitles' in text):
                output.append(f'\n**{header.text}**\n\n')
                rows = table.find_all('tr')
                for row in rows:
                    output.append('- ')
                    for cell in row.find_all('td'):
                        output.append(f'{cell.text.replace("<i>", "_").replace("</i>", "_")}\n')
        return ''.join(output)

    def output_plain(self):
        output = []
        headers = self.soup.find_all('td', attrs={'class': 'search-table-header'})
        tables = self.soup.find_all('table', attrs={'class': 'search-result-table'})
        output.append(f'Lookup results for "{self.word}" from Longdo Dictionary \n{self.dic_url + self.word}\n')
        for header, table in sorted(
                zip(headers, tables),
                key=lambda x: ('Longdo Dictionary' in x[0].text) or ('HOPE Dictionary' in x[0].text)
        ):
            text = header.text
            if not ('Subtitles' in text):
                output.append(f'\n{header.text}\n\n')
                rows = table.find_all('tr')
                for row in rows:
                    output.append('- ')
                    for cell in row.find_all('td'):
                        output.append(f'{cell.text.replace("<i>", "").replace("</i>", "")}\n')
        return ''.join(output)

    def recognize_and_lookup(self, lang='tha', kind=None, output='html'):
        self.grab()
        if not self.im:
            return
        display(self.im)
        start = dt.now()
        self.threads_recognize(lang, kind)
        print(f'Done in {dt.now() - start}')
        self.generate_word_suggestions()
        if not self.suggestions:
            print('No meaningful recognition results could be obtained from the image')
            return
        top = self.suggestions[0]
        best_guess = f'The best guess is "{top[0]}" rated {top[1]}\n'
        others = 'Others:\n'
        for i in range(1, len(self.suggestions)):
            other = self.suggestions[i]
            others += f'{i} - {other[0]} ({other[1]})\t'
        word = input(
            f'''{best_guess}{others}\n
            Enter to proceed with top-rated suggestion or number for other or any desired word:'''
        )
        if not word:
            self.lookup(top[0])
        else:
            try:
                self.lookup(self.suggestions[int(word)][0])
            except:
                self.lookup(word)
        if output == 'html' and self.soup:
            self.output_html()


print('>> screen2text imported.')
