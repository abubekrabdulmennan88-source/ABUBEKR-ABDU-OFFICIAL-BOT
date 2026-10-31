import os
import re
import time
import html
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

# ---------- ቅንብር (Settings) ----------
TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ.get("CHANNEL", "@abubekrabdu_official")
START_DATE = os.environ["START_DATE"]  # ለምሳሌ 2026-10-19 (የመጀመሪያው ቀን)

SOURCES = ["shffaaaaa", "tratealcom"]   # ከነዚህ ቻናሎች ተርጉሞ ይለጥፋል
CHECK_EVERY = 600                       # በየ 10 ደቂቃ ይፈትሻል

TZ = timezone(timedelta(hours=3))       # የኢትዮጵያ ሰዓት (UTC+3)
DAILY_TIMES = [(7, 0), (15, 0)]         # የቀን 2 ፖስት ሰዓት (7:00 AM እና 3:00 PM)
STORY_TIME = (21, 0)                    # ታሪክ: 9:00 PM (ማታ 3:00)
MIN_WORDS = int(os.environ.get("MIN_WORDS", "0"))        # ለምሳሌ 80 ካደረግህ ከ80 ቃል በታች ያሉ አይለጠፉም
MAX_WORDS = int(os.environ.get("MAX_WORDS", "100000"))   # ለምሳሌ 120
WINDOW_MIN = 5                          # ከሰዓቱ በኋላ እስከ 5 ደቂቃ ውስጥ ይለጥፋል

API = f"https://api.telegram.org/bot{TOKEN}"

# ---------- የእስላማዊ ይዘት ማጣሪያ ----------
ISLAMIC_WORDS = [
    "الله", "رسول", "محمد", "القرآن", "قرآن", "الإسلام", "الاسلام", "إسلام",
    "الصلاة", "صلاة", "السنة", "حديث", "النبي", "ﷺ", "صلى الله", "رحمه الله",
    "دعاء", "الجنة", "النار", "الإيمان", "إيمان", "التوحيد", "فقه", "تفسير",
    "سورة", "آية", "اللهم", "سبحان", "الصحابة", "الصحابي", "عبادة", "الصيام",
    "الزكاة", "الحج", "العمرة", "التقوى", "الدين", "المسلم", "المسلمين",
]
BLOCKED_OUTPUT = ["እግዚአብሔር", "ኢየሱስ", "ክርስቶስ", "መስቀል", "ቤተ ክርስቲያን"]


def is_islamic(arabic_text):
    return any(w in arabic_text for w in ISLAMIC_WORDS)


def output_ok(amharic_text):
    return not any(b in amharic_text for b in BLOCKED_OUTPUT)


# ---------- ቴሌግራም መላክ ----------
def send(text):
    text = text.strip()
    while text:
        chunk = text[:4000]
        if len(text) > 4000:
            cut = chunk.rfind("\n")
            if cut > 1000:
                chunk = chunk[:cut]
        r = requests.post(
            f"{API}/sendMessage",
            data={"chat_id": CHANNEL, "text": chunk},
            timeout=30,
        )
        if not r.ok:
            print("send error:", r.status_code, r.text[:200])
            return False
        text = text[len(chunk):].strip()
        time.sleep(1.5)
    return True


# ---------- ትርጉም (ነፃ Google Translate) ----------
def split_text(text, limit=1500):
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit and cur:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts


def translate(text):
    out = []
    for chunk in split_text(text):
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "am", "dt": "t", "q": chunk},
            timeout=30,
        )
        r.raise_for_status()
        out.append("".join(p[0] for p in r.json()[0] if p[0]))
        time.sleep(1)
    return "".join(out).strip()


# ---------- ከህዝብ ቻናል ፖስት ማምጣት ----------
def fetch_posts(channel):
    r = requests.get(
        f"https://t.me/s/{channel}",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    r.raise_for_status()
    posts = []
    for chunk in r.text.split("tgme_widget_message_wrap")[1:]:
        m_id = re.search(r'data-post="[^/]+/(\d+)"', chunk)
        m_tx = re.search(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            chunk,
            re.S,
        )
        if not m_id or not m_tx:
            continue
        raw = re.sub(r"<br\s*/?>", "\n", m_tx.group(1))
        raw = re.sub(r"<[^>]+>", "", raw)
        posts.append((int(m_id.group(1)), html.unescape(raw).strip()))
    return posts


last_seen = {}


def translator_loop():
    while True:
        for ch in SOURCES:
            try:
                posts = fetch_posts(ch)
                if ch not in last_seen:
                    # የመጀመሪያ ጊዜ: የድሮ ፖስቶችን አይለጥፍም፣ ከአሁን በኋላ ያሉትን ብቻ
                    last_seen[ch] = max([p[0] for p in posts], default=0)
                    print(f"{ch}: baseline {last_seen[ch]}")
                    continue
                new = sorted(p for p in posts if p[0] > last_seen[ch])
                for pid, text in new:
                    last_seen[ch] = max(last_seen[ch], pid)
                    if len(text) < 30 or not is_islamic(text):
                        continue
                    am = translate(text)
                    if am and output_ok(am):
                        send(am)
            except Exception as e:
                print("translator error:", ch, e)
        time.sleep(CHECK_EVERY)


# ---------- የተዘጋጁ ፖስቶች (posts.txt እና story.txt) ----------
def load_blocks(path):
    try:
        with open(path, encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if not l.startswith("#")]
    except FileNotFoundError:
        return []
    blocks = re.split(r"\n\s*====+\s*\n", "\n".join(lines))
    return [b.strip() for b in blocks if b.strip()]


LINK_LINE = re.compile(r"^\W*(https?://)?t\.me/\S*\W*$")
SEP_LINE = re.compile(r"^\s*[—–]{3,}\S*\s*$|^\s*={4,}\s*$|^\s*💕{3}\s*$")


def load_daily(path):
    """posts.txt: ከቴሌግራም ቻናል በቀጥታ copy የተደረገ ጽሑፍም ይቀበላል።
    በ t.me ሊንክ መስመር፣ በ ==== ወይም በ ——— መስመር ፖስቶችን ይለያል፤ ሊንኮችን ያስወግዳል።"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return []
    blocks, cur = [], []

    def flush():
        text = "\n".join(cur).strip()
        cur.clear()
        if not text:
            return
        parts = [text]
        if len(text) > 1200 and "\n---\n" not in text:
            parts, buf = [], ""
            for para in text.split("\n\n"):
                if buf and len(buf) + len(para) > 800:
                    parts.append(buf.strip())
                    buf = ""
                buf += para + "\n\n"
            if buf.strip():
                parts.append(buf.strip())
        for p in parts:
            if MIN_WORDS <= len(p.split()) <= MAX_WORDS:
                blocks.append(p)

    for line in raw.splitlines():
        if line.startswith("#"):
            continue
        if LINK_LINE.match(line) or SEP_LINE.match(line):
            flush()
            continue
        cur.append(line)
    flush()
    return blocks


def prepare_daily(text):
    """አማርኛ ብቻ ይለጥፋል።
    አረብኛ + --- + አማርኛ ከተጻፈ አማርኛውን ብቻ ይወስዳል፤
    አረብኛ ብቻ ከሆነ ራሱ ተርጉሞ አማርኛውን ብቻ ይለጥፋል።"""
    if "\n---\n" in text:
        return text.split("\n---\n", 1)[1].strip()
    # አማርኛ ፊደል ካለው አስቀድሞ አማርኛ ነው
    if re.search(r"[\u1200-\u137F]", text):
        return text
    try:
        am = translate(text)
        if am and output_ok(am):
            return am
    except Exception as e:
        print("daily translate error:", e)
    return None


DECO = "✿°•┈┈┈••ৡ❀ৡ•┈┈┈•°✿"
DECO_RE = re.compile(r"✿°•┈+••ৡ❀ৡ•┈+•°✿")


def load_story(path):
    """story.txt: ከቴሌግራም በቀጥታ copy የተደረገ ታሪክ ይቀበላል (በ ✿°•┈┈┈••ৡ❀ৡ•┈┈┈•°✿ መስመር የተከበበ)።
    እያንዳንዱ ክፍል አንድ ፖስት ይሆናል። ያለዚህ ምልክት ከሆነ በ ==== መስመር ይለያል።"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = "\n".join(l for l in f.read().splitlines() if not l.startswith("#"))
    except FileNotFoundError:
        return []
    if DECO_RE.search(raw):
        parts = [p.strip() for p in DECO_RE.split(raw)]
        return [f"{DECO}\n{p}\n{DECO}" for p in parts if p]
    return load_blocks(path)


def scheduler_loop():
    start = datetime.strptime(START_DATE, "%Y-%m-%d").date()
    done = set()
    while True:
        try:
            now = datetime.now(TZ)
            day = (now.date() - start).days
            if day >= 0:
                posts = load_daily("posts.txt")
                story = load_story("story.txt")
                slots = [(f"p{i}", t) for i, t in enumerate(DAILY_TIMES)]
                slots.append(("story", STORY_TIME))
                for name, (h, m) in slots:
                    key = (now.date(), name)
                    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    late = (now - target).total_seconds()
                    if key in done or not (0 <= late < WINDOW_MIN * 60):
                        continue
                    done.add(key)
                    if name == "story":
                        if day < len(story):
                            send(story[day])
                    else:
                        idx = day * len(DAILY_TIMES) + int(name[1:])
                        if idx < len(posts):
                            msg = prepare_daily(posts[idx])
                            if msg:
                                send(msg)
        except Exception as e:
            print("scheduler error:", e)
        time.sleep(30)


# ---------- Render እንዳይተኛ ትንሽ ሰርቨር ----------
class Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def main():
    threading.Thread(target=translator_loop, daemon=True).start()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), Ping).serve_forever()


if __name__ == "__main__":
    main()
