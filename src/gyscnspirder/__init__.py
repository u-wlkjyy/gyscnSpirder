import re
import base64
import hashlib
import os
from typing import Union, Tuple

from fontTools.ttLib import TTFont
from fontTools.pens.freetypePen import FreeTypePen
from fontTools.misc.transform import Offset
from PIL import Image, ImageDraw, ImageFont
from lxml import etree
import numpy as np
import ddddocr
import requests

_ddddocr = ddddocr.DdddOcr()

BASE_CACHE_PATH = "./cache/"
FONT_CACHE_PATH = BASE_CACHE_PATH + "font/"
IMAGE_CACHE_PATH = BASE_CACHE_PATH + "image/"
"""
    if cache directory is not exist, create it
"""
if not os.path.exists(BASE_CACHE_PATH):
    os.mkdir(BASE_CACHE_PATH)
if not os.path.exists(FONT_CACHE_PATH):
    os.mkdir(FONT_CACHE_PATH)
if not os.path.exists(IMAGE_CACHE_PATH):
    os.mkdir(IMAGE_CACHE_PATH)


class BlockedException(Exception):
    pass


class Spider:
    url = None
    response = None
    font_cache_name = None
    font_parse_data = None
    font_ocr_real = {}
    headers = {
        "authority": "www.gys.cn",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "cache-control": "max-age=0",
        "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Microsoft Edge";v="122"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    }

    def __init__(self, url, timeout: Union[float, Tuple[float, float], None] = None):
        self.ddddocr = _ddddocr
        self.url = url
        self.font_cache_name = hashlib.md5(url.encode()).hexdigest()
        self.font_cache_name = "{}.ttf".format(FONT_CACHE_PATH + self.font_cache_name)
        self.timeout = timeout

    def __enter__(self):
        self.get_response()
        self.get_font()
        self.font_parse()
        self.save_font_image()
        self.ocr_font()

    def __exit__(self, _type, _val, _tb):
        """
        destroy Spider instance, delete all cache files
        """
        for root, dirs, files in os.walk(IMAGE_CACHE_PATH):
            for file in files:
                fpath = os.path.join(root, file)
                if os.path.isfile(fpath):
                    os.remove(fpath)
        if os.path.isfile(self.font_cache_name):
            os.remove(self.font_cache_name)
        return

    def get_response(self):
        """
        get response from the url
        """
        response = requests.get(self.url, headers=self.headers, timeout=self.timeout)
        response.encoding = response.apparent_encoding
        self.response = response.text
        if "访问有异常" in self.response:
            raise BlockedException(
                "The website is protected by anti-spider, please try again later or use a proxy"
            )

    def get_font(self):
        """
        from html response, get the font base64 string
        """
        if os.path.exists(self.font_cache_name):
            os.remove(self.font_cache_name)

        # from the response, get the font base64 string
        font_pre = self.response.split(
            "@font-face{font-family:'icomoon';src:url('data:application/font-ttf;charset=utf-8;base64,"
        )
        font = font_pre[1].split("') format('truetype');}")

        with open(self.font_cache_name, "wb") as f:
            f.write(base64.b64decode(font[0]))

        return True

    def font_parse(self):
        """
        parse the font file, get the real character
        """
        self.font_parse_data = ImageFont.truetype(self.font_cache_name, 40)
        self.font_parse_uni = TTFont(self.font_cache_name)
        uni_map = self.font_parse_uni["cmap"].tables[0].ttFont.getBestCmap()
        self.uniMap = {hex(k): v for k, v in uni_map.items()}

    def save_font_image(self):
        """
        save the font image to the cache directory
        """
        font = self.font_parse_uni
        for k, v in self.uniMap.items():
            pen = FreeTypePen(None)
            glyph = font.getGlyphSet()[v]
            glyph.draw(pen)
            width, ascender, descender = (
                glyph.width,
                font["OS/2"].usWinAscent,
                -font["OS/2"].usWinDescent,
            )
            height = ascender - descender

            single_font_image = pen.array(
                width=width,
                height=height,
                transform=Offset(0, -descender),
                contain=False,
                evenOdd=False,
            )

            single_font_image = np.array(single_font_image) * 255

            # from black convert to white background
            single_font_image = 255 - single_font_image

            single_font_image = Image.fromarray(single_font_image)
            single_font_image = single_font_image.convert("L")
            single_font_image.save("{}{}.jpg".format(IMAGE_CACHE_PATH, k))

    def ocr_font(self):
        """
        ocr the font image, get the real character
        """
        ocr = self.ddddocr
        for k, v in self.uniMap.items():
            file = "{}{}.jpg".format(IMAGE_CACHE_PATH, k)
            with open(file, "rb") as classi:
                res = ocr.classification(classi.read())
            if res == "":
                res = "-"
            self.font_ocr_real[v] = res

    def get_phone(self):
        """
        get the phone number from the response, and convert the font character to real character
        """
        phone = re.findall(r'<span class="rrdh secret">(.*?)</span>', self.response)
        phone = phone[0]
        phone = phone.split(";")
        real_phone = ""
        for i in phone:
            if i == "":
                continue
            i = i.replace("&#x", "uni").strip()
            real_phone += self.font_ocr_real[i]
        return real_phone

    def get_information(self):
        """
        get the name, address, firm, phone from the response
        """
        try:
            tree = etree.HTML(self.response)
            name = tree.xpath('//span[@class="xqrm"]/text()')[0].strip()
            addr = tree.xpath('//dl[@class="fl-clr"]//span[@class="addr"]/text()')[0]
            firm = tree.xpath('//dl[@class="fl-clr"]//span[@class="corpname"]/text()')[
                0
            ]
            phone = self.get_phone()
            return name, addr, firm, phone
        except Exception:
            return None, None, None, None
