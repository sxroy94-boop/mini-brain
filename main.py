"""mini Brain - runs on the tablet. Understands text sent by the mobile app
and replies with a JSON action. No Android-only APIs needed (no pyjnius)."""
import http.server
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

try:
    import certifi
except Exception:
    certifi = None

PORT = 5000
MODEL = "gemini-3.1-flash-lite"
GOLD = (1, 0.76, 0.2, 1)
MEMORY_DAYS = 35
SYSTEM_BASE = (
    "You are mini, a JARVIS-like voice assistant. "
    "Always address the user only as %s, never any other name or pet name. "
    "Never use romantic language. Answer in one or two short spoken sentences. "
    "Reply in the language the user used: English or Hindi. "
    "For an English reply output exactly: EN@@<text> "
    "For a Hindi reply output exactly: HI@@<Hindi in Devanagari script>@@<the same sentence in Roman letters> "
    "Write numbers as digits. No markdown, no emojis. Never use Bengali."
)

import collections

Reply = collections.namedtuple("Reply", "spoken shown")


def R(spoken, shown=None):
    return Reply(spoken, spoken if shown is None else shown)


DEVA = re.compile(r"[\u0900-\u097F]")


def has_deva(text):
    return bool(DEVA.search(text))


# ---- same address/reply tables as the mobile app (kept in sync on purpose) ----
RESP = {
    "hello": {
        "normal": ("नमस्ते {n}! कैसे हो?", "Namaste {n}! Kaise ho?"),
        "personal": ("नमस्ते {n}! आप कैसे हो?", "Namaste {n}! Aap kaise ho?"),
    },
    "kaise": {
        "normal": ("मैं ठीक हूँ! आप कैसे हो?", "Main theek hoon! Aap kaise ho?"),
        "personal": (
            "मैं ठीक हूँ, आपसे बात करके अच्छा लगा। आप कैसे हो {n}?",
            "Main theek hoon, aapse baat karke accha laga. Aap kaise ho {n}?",
        ),
    },
    "howare": {"normal": ("मैं ठीक हूँ", "Main theek hoon")},
    "thanks": {"normal": ("आपका स्वागत है {n}", "Aapka swagat hai {n}")},
    "name": {"normal": ("मेरा नाम मिनी है", "Mera naam Mini hai")},
    "gmorning": {"normal": ("गुड मॉर्निंग {n}! आप कैसे हो?", "Good morning {n}! Aap kaise ho?")},
    "love": {
        "normal": ("धन्यवाद {n}, मैं यहाँ मदद के लिए हूँ।", "Dhanyavad {n}, main yahan madad ke liye hoon."),
    },
    "sorry": {"normal": ("कोई बात नहीं {n}!", "Koi baat nahin {n}!")},
    "yes": {"normal": ("ओके {n}!", "Okay {n}!")},
    "no": {"normal": ("ठीक है {n}.", "Theek hai {n}.")},
    "ok": {"normal": ("ठीक है {n}!", "Theek hai {n}!")},
}
PATTERNS = [
    ("hello", r"hello|hi|hey|hello there|hi there|namaste|namaskar|नमस्ते"),
    ("kaise", r"(?:aap )?kaise ho|(?:aap )?kaisi ho|kese ho|kaisa hai|आप कैसे हो|कैसे हो"),
    ("howare", r"how are you|how r u|how are you doing"),
    ("thanks", r"thank you|thanks|thank u|shukriya|dhanyavad|धन्यवाद|शुक्रिया"),
    ("name", r"what(?:'s| is) your name|tumhara naam kya hai|aapka naam kya hai|तुम्हारा नाम क्या है|आपका नाम क्या है"),
    ("gmorning", r"good morning|suprabhat|सुप्रभात"),
    ("sorry", r"sorry|maaf karo|maaf kijiye|सॉरी"),
    ("yes", r"yes|haan|han|ha|हाँ|हां"),
    ("no", r"no|nahi|nahin|nope|नहीं"),
    ("ok", r"ok|okay|thik hai|theek hai|ठीक है"),
]
LOVE = r"i love you|love you|i love u|आई लव यू"
ASK_AFTER = {"hello", "kaise", "howare", "gmorning", "thanks", "yes", "no", "ok", "sorry"}
PERS_QUESTIONS = [
    R("आप कैसे हो {n}?", "Aap kaise ho {n}?"),
    R("क्या कर रहे हो?", "Kya kar rahe ho?"),
    R("आज का दिन कैसा रहा?", "Aaj ka din kaisa raha?"),
]


class Store:
    def __init__(self, folder):
        self.folder = folder

    def path(self, name):
        return os.path.join(self.folder, name)

    def load(self, name, default):
        try:
            with open(self.path(name), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def save(self, name, data):
        with open(self.path(name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def read_text(self, name, default=""):
        try:
            with open(self.path(name), encoding="utf-8") as f:
                return f.read().strip() or default
        except Exception:
            return default

    def write_text(self, name, value):
        with open(self.path(name), "w", encoding="utf-8") as f:
            f.write(value)


class Memory:
    FILE = "mini_mem.json"

    def __init__(self, store, clock=time.time):
        self.store = store
        self.clock = clock

    def cleanup(self):
        data = self.store.load(self.FILE, {})
        limit = self.clock() - MEMORY_DAYS * 86400
        kept = {k: v for k, v in data.items() if v.get("t", 0) >= limit}
        if len(kept) != len(data):
            self.store.save(self.FILE, kept)
        return kept

    def remember(self, key, value):
        data = self.cleanup()
        data[key] = {"v": value, "t": self.clock()}
        self.store.save(self.FILE, data)

    def recall(self, key):
        item = self.cleanup().get(key)
        return item["v"] if item else None

    def clear(self):
        self.store.save(self.FILE, {})


class Vault:
    FILE = "mini_pwd.json"

    def __init__(self, store):
        self.store = store

    def set(self, password):
        self.store.save(self.FILE, {"password": password})

    def get(self):
        return self.store.load(self.FILE, {}).get("password")


class Brain:
    """Understands one line of text. Same logic shape as the mobile app's Brain."""

    def __init__(self, store):
        self.mem = Memory(store)
        self.vault = Vault(store)
        self.mood = "normal"

    @property
    def nick(self):
        return self.mem.recall("nickname") or "Boss"

    def fmt(self, r):
        n = self.nick
        return Reply(r.spoken.replace("{n}", n), r.shown.replace("{n}", n))

    def clean(self, raw):
        s = raw.lower()
        s = re.sub(r"(?:\b(?:hey|ok|okay)\s+)?\b(?:mini|minnie)\b", " ", s)
        return re.sub(r"\s+", " ", s).strip(" ,.!?।")

    def _mood_reply(self, key):
        table = RESP[key]
        sp, sh = table.get(self.mood) or table["normal"]
        r = self.fmt(R(sp, sh))
        if key in ASK_AFTER and self.mood == "personal" and not r.shown.rstrip().endswith("?"):
            import random

            if random.random() < 0.5:
                q = self.fmt(random.choice(PERS_QUESTIONS))
                r = Reply(r.spoken + " " + q.spoken, r.shown + " " + q.shown)
        return r

    def system_prompt(self):
        base = SYSTEM_BASE % self.nick
        if self.mood == "personal":
            base += " Use a soft, caring, but respectful and non-romantic tone."
        return base

    def parse_ai(self, text):
        t = text.strip()
        if t.startswith("HI@@"):
            parts = t[4:].split("@@")
            spoken = parts[0].strip()
            shown = parts[1].strip() if len(parts) > 1 else spoken
            if has_deva(shown):
                shown = "(Hindi voice reply)"
            return R(spoken, shown)
        if t.startswith("EN@@"):
            t = t[4:].strip()
        return R(t, "(Hindi voice reply)" if has_deva(t) else t)

    def time_reply(self, lang):
        import datetime

        t = datetime.datetime.now().strftime("%I:%M %p").lstrip("0")
        if lang == "hi":
            return R("अभी समय %s है।" % t, "Abhi samay %s hai." % t)
        return R("The time is %s." % t)

    def date_reply(self, lang):
        import datetime

        d = datetime.datetime.now()
        text = "%d %s %d" % (d.day, d.strftime("%B"), d.year)
        if lang == "hi":
            return R("आज की तारीख %s है।" % text, "Aaj ki tareekh %s hai." % text)
        return R("Today is %s, %s." % (d.strftime("%A"), text))

    def weather_reply(self, lang, temp, unit, cond):
        unit_en = "Celsius" if unit == "C" else "Fahrenheit"
        t = int(temp)
        spoken_t = ("minus %d" % abs(t)) if t < 0 else str(t)
        cond = cond.strip().lower()
        if lang == "hi":
            unit_hi = "सेल्सियस" if unit == "C" else "फ़ारेनहाइट"
            return R(
                "अभी तापमान %s डिग्री %s है और मौसम %s है।" % (spoken_t, unit_hi, cond),
                "Abhi taapmaan %s degree %s hai aur mausam %s hai." % (spoken_t, unit_en, cond),
            )
        return R("It is %s degrees %s and %s." % (spoken_t, unit_en, cond))

    def route(self, raw):
        """Same 'kind, payload' shape the mobile app already knows how to dispatch."""
        raw = raw.strip()
        if not raw:
            return ("empty", None)
        full = re.sub(r"\s+", " ", raw.lower()).strip(" ,.!?।")
        low = self.clean(raw)

        if re.fullmatch(
            r"(?:(?:hey|ok|okay) )?mini (?:off|band karo|shutdown|switch off)|(?:shut ?down|power off) mini",
            full,
        ):
            return ("off", self.fmt(R("Switching off. Goodbye {n}!", "Switching off. Alvida {n}!")))

        m = re.match(r"^(?:save )?my password is (.+)$", raw, re.I) or re.match(
            r"^(?:save )?mera password (?!kya\b)(.+?)(?: hai)?$", raw, re.I
        )
        if m:
            self.vault.set(m.group(1).strip(" ."))
            return ("vault_save", R("Password saved.", "Password saved."))
        if re.fullmatch(
            r"what(?:'s| is) my password|tell me my password|mera password kya hai|मेरा पासवर्ड क्या है", low
        ):
            pw = self.vault.get()
            if not pw:
                return ("vault_get", R("You have not saved a password yet."))
            spelled = " ".join(pw)
            return ("vault_get", R("Your password is " + spelled, "Your password is ******** (spoken only)"))

        if not low:
            return ("say", self.fmt(R("जी {n}?", "Ji {n}?")))

        if re.fullmatch(r"bye|good ?bye|stop|band|band karo|band kar do|by|bey|बंद|अलविदा|alvida", low):
            return ("stop", self.fmt(R("अलविदा {n}!", "Alvida {n}!")))
        if re.fullmatch(r"good ?night|gud night|shubh ratri|शुभ रात्रि", low):
            return ("stop", self.fmt(R("Good night {n}! Sweet dreams.")))

        if re.fullmatch(r"personal (?:mode|mood) off|normal (?:mode|mood)|normal ho ja(?:o)?", low):
            self.mood = "normal"
            return ("say", R("Normal mode on."))
        if re.fullmatch(r"(?:girlfriend|gf) (?:mode|mood)(?: on| chalu)?", low):
            return ("say", self.fmt(R("I do not have a girlfriend mode, {n}. I can switch to personal mode instead.")))
        if re.fullmatch(r"personal (?:mode|mood)(?: on)?|पर्सनल मोड", low):
            self.mood = "personal"
            return ("say", self.fmt(R("ठीक है, पर्सनल मोड चालू। आप कैसे हो?", "Theek hai, personal mode on. Aap kaise ho?")))

        m = re.match(r"^(?:use|set) model\s+(\S+)$", raw.strip(" .!?"), re.I)
        if m:
            return ("model", m.group(1))

        if re.fullmatch(r"what(?:'s| is) my name|mera naam kya hai|who am i|मेरा नाम क्या है", low):
            name = self.mem.recall("name")
            if name:
                return ("say", R("आपका नाम %s है।" % name, "Aapka naam %s hai." % name))
            return ("say", R("I do not know your name yet. Say: my name is, and your name."))
        if re.fullmatch(r"forget everything|forget all|sab kuch bhool jao|sab bhool jao|सब भूल जाओ", low):
            self.mem.clear()
            return ("say", R("Done. I have forgotten everything."))
        m = re.match(r"^call me (.+)$", raw, re.I) or re.match(r"^mujhe (.+) bula(?:o|na)$", raw, re.I)
        if m:
            nick = m.group(1).strip(" .!?")
            self.mem.remember("nickname", nick)
            return ("say", R("Okay, I will call you %s." % nick))
        m = re.match(r"^my name is (.+)$", raw, re.I) or re.match(
            r"^mera naam (?!kya\b)(.+?)(?: hai)?$", raw, re.I
        )
        if m:
            name = m.group(1).strip(" .!?")
            self.mem.remember("name", name)
            return ("say", R("Nice to meet you, %s." % name))

        if re.search(LOVE, low):
            return ("say", self._mood_reply("love"))
        for key, rx in PATTERNS:
            if re.fullmatch(rx, low):
                return ("say", self._mood_reply(key))

        # hardware / phone commands - the tablet does not execute these, it only
        # recognises them; the mobile app carries them out on the phone.
        if re.fullmatch(
            r"(?:turn on|switch on) (?:the )?(?:torch|flash|flashlight)|(?:torch|flash|flashlight) on|"
            r"torch jalao|flash jalao|light jalao",
            low,
        ):
            return ("torch", True)
        if re.fullmatch(
            r"(?:turn off|switch off) (?:the )?(?:torch|flash|flashlight)|(?:torch|flash|flashlight) off|"
            r"torch bandh karo|flash bandh karo|light bandh karo",
            low,
        ):
            return ("torch", False)
        if re.fullmatch(r"volume up|increase volume|awaaz badhao|volume badhao|volume badha do", low):
            return ("volume", "up")
        if re.fullmatch(r"volume down|decrease volume|awaaz kam karo|volume kam karo", low):
            return ("volume", "down")
        if re.fullmatch(r"(?:full|max(?:imum)?) volume|volume max|volume full karo", low):
            return ("volume", "max")
        if re.fullmatch(r"mute|mute (?:the )?volume|awaaz band karo|volume band karo|silent", low):
            return ("volume", "mute")
        if re.fullmatch(r"unmute|volume on|awaaz chalu karo", low):
            return ("volume", "unmute")
        if re.fullmatch(r"(?:open )?wifi(?: settings)?|wifi kholo|wifi on karo|wifi off karo", low):
            return ("settings", "wifi")
        if re.fullmatch(
            r"(?:open )?bluetooth(?: settings)?|bluetooth kholo|bluetooth on karo|bluetooth off karo", low
        ):
            return ("settings", "bluetooth")
        if re.fullmatch(r"open settings|phone settings|settings kholo", low):
            return ("settings", "settings")
        if re.search(r"battery (?:percentage|status|level)?|battery kitni hai|kitni battery hai", low):
            return ("battery", None)
        m = re.match(
            r"^(?:send )?(?:message|sms|text)\s+(.+?)\s+(?:saying|that says|ki|likh(?:o|ke))\s+(.+)$",
            raw,
            re.I,
        ) or re.match(r"^(.+?)\s+ko\s+(?:message|sms)\s+(?:bhejo|karo)\s+(.+)$", raw, re.I)
        if m:
            return ("sms", (m.group(1).strip(), m.group(2).strip()))
        m = re.match(r"^whatsapp\s+(?:me\s+|mein\s+)?(.+)$", low)
        if m:
            name = re.sub(
                r"\s+(?:ko\s+)?(?:call|kall|message|msg|chat|text)(?:\s+\w+)?$", "", m.group(1)
            ).strip()
            return ("whatsapp", name)
        m = re.match(r"^(?:call|phone|dial)\s+(.+)$", low) or re.match(
            r"^(.+?)\s+ko\s+(?:call|phone)(?:\s+(?:karo|kro|kar do))?$", low
        )
        if m:
            return ("call", m.group(1).strip())
        m = re.match(r"^(?:open|launch|start)\s+(.+)$", low) or re.match(
            r"^(.+?)\s+(?:kholo|khol do|chalu karo)$", low
        )
        if m:
            return ("open", re.sub(r"\s+app$", "", m.group(1).strip()))

        if re.search(r"what(?:'s| is)? the time|what time is it|current time|tell me the time|^time$", low):
            return ("say", self.time_reply("en"))
        if re.search(r"time kya hai|samay kya hai|टाइम क्या है|समय क्या है|kitne baje", low):
            return ("say", self.time_reply("hi"))
        if re.search(r"what(?:'s| is)? (?:the )?date|today'?s date|what day is it|which day is it", low):
            return ("say", self.date_reply("en"))
        if re.search(r"aaj ki (?:date|tareekh|tarikh)|date kya hai|आज की (?:तारीख|डेट)", low):
            return ("say", self.date_reply("hi"))
        if re.search(r"weather|mausam|मौसम", low):
            lang = "hi" if re.search(r"mausam|kaisa|kya|मौसम|कैसा", low) else "en"
            city = ""
            m = re.search(r"weather (?:in|of|at|for) (.+)$", low)
            if m:
                city = m.group(1).strip()
            return ("weather", (lang, city))
        m = re.match(r"^(?:search|google)(?: for)?\s+(.+)$", low)
        if m:
            return ("search", m.group(1).strip())

        return ("ai", raw)


# ---------------------------------------------------------------- network helpers
def ssl_context():
    if certifi:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def call_gemini(key, model, system, contents):
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model
    body = json.dumps(
        {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 1024},
        }
    ).encode()
    req = urllib.request.Request(
        url, data=body, headers={"content-type": "application/json", "x-goog-api-key": key}
    )
    with urllib.request.urlopen(req, timeout=40, context=ssl_context()) as r:
        out = json.loads(r.read().decode())
    cands = out.get("candidates") or [{}]
    parts = (cands[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts).strip()


def fetch_weather(city):
    url = "https://wttr.in/%s?format=%%t+%%C" % urllib.parse.quote(city)
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
    with urllib.request.urlopen(req, timeout=15, context=ssl_context()) as r:
        txt = r.read().decode("utf-8", "ignore").strip()
    m = re.match(r"([+-]?\d+)\s*\S?\s*([CF])\s*(.*)", txt)
    if not m:
        raise ValueError("no weather data")
    return m.group(1).lstrip("+"), m.group(2), m.group(3) or "clear"


def fetch_instant_answer(query):
    url = "https://api.duckduckgo.com/?q=%s&format=json&no_html=1&skip_disambig=1" % urllib.parse.quote(
        query
    )
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
    with urllib.request.urlopen(req, timeout=12, context=ssl_context()) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    text = (data.get("AbstractText") or data.get("Answer") or "").strip()
    if not text:
        for t in data.get("RelatedTopics") or []:
            if isinstance(t, dict) and t.get("Text"):
                text = t["Text"].strip()
                break
    if not text:
        return None
    return " ".join(re.split(r"(?<=[.!?])\s+", text)[:2])[:400]


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# ---------------------------------------------------------------- HTTP server
def make_handler(app_ref):
    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, code, payload):
            out = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def do_GET(self):
            if self.path == "/":
                self._send(200, {"status": "mini Brain is running"})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/command":
                return self._send(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                text = (data.get("text") or "").strip()
            except Exception:
                return self._send(400, {"error": "bad request"})
            try:
                result = app_ref.handle_text(text)
            except Exception as e:
                result = {"action": "say", "spoken": "Brain error: %s" % e, "shown": "Brain error: %s" % e}
            self._send(200, result)

        def log_message(self, fmt, *args):
            pass  # keep the console quiet; the app shows its own log

    return Handler


# ---------------------------------------------------------------- App
def styled_button(text, **kw):
    return Button(text=text, background_normal="", background_color=(0.1, 0.15, 0.22, 1), color=GOLD, **kw)


def styled_input(hint, **kw):
    return TextInput(
        hint_text=hint,
        multiline=False,
        background_color=(0.06, 0.06, 0.09, 1),
        foreground_color=GOLD,
        hint_text_color=(0.5, 0.5, 0.55, 1),
        cursor_color=GOLD,
        **kw
    )


class MiniBrainApp(App):
    title = "mini Brain"

    def build(self):
        Window.clearcolor = (0.02, 0.02, 0.04, 1)
        self.store = Store(self.user_data_dir)
        self.brain = Brain(self.store)
        self.model = self.store.read_text("gemini_model.txt", MODEL)
        self.lines = []

        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        root.add_widget(
            Label(text="M I N I   B R A I N", color=GOLD, font_size="20sp", size_hint_y=None, height=dp(32))
        )
        self.status = Label(text="Starting...", color=(0.6, 0.9, 0.6, 1), font_size="16sp", size_hint_y=None, height=dp(60))
        root.add_widget(self.status)

        keyrow = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        self.key_inp = styled_input("Google Gemini API key", password=True)
        keyrow.add_widget(self.key_inp)
        keyrow.add_widget(styled_button("Save key", size_hint_x=None, width=dp(100), on_release=self.save_key))
        root.add_widget(keyrow)

        root.add_widget(styled_button("Refresh IP", size_hint_y=None, height=dp(44), on_release=self.refresh_ip))

        root.add_widget(Label(text="Recent requests", color=GOLD, size_hint_y=None, height=dp(24), font_size="13sp"))
        self.scroll = ScrollView()
        self.log = Label(size_hint_y=None, halign="left", valign="top", font_size="14sp", color=(0.8, 0.8, 0.85, 1))
        self.log.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        self.log.bind(texture_size=lambda w, s: setattr(w, "height", s[1]))
        self.scroll.add_widget(self.log)
        root.add_widget(self.scroll)

        return root

    def on_start(self):
        self.refresh_ip()
        threading.Thread(target=self.run_server, daemon=True).start()

    def refresh_ip(self, *_):
        ip = local_ip()
        self.status.text = "Server: http://%s:%d\n(mobile and tablet must be on the same Wi-Fi)" % (ip, PORT)

    def run_server(self):
        server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(self))
        server.serve_forever()

    def save_key(self, *_):
        key = self.key_inp.text.strip()
        if not key:
            return
        self.store.write_text("gemini_key.txt", key)
        self.key_inp.text = ""
        self.add_log("(API key saved on this tablet)")

    def add_log(self, line):
        self.lines = (self.lines + [line])[-8:]
        self.log.text = "\n".join(self.lines)
        Clock.schedule_once(lambda dt: setattr(self.scroll, "scroll_y", 0), 0.1)

    # ---------- called from the HTTP server thread (not the UI thread) ----------
    def handle_text(self, text):
        if not text:
            return {"action": "say", "spoken": "Ji Boss?", "shown": "Ji Boss?"}
        kind, payload = self.brain.route(text)
        Clock.schedule_once(lambda dt: self.add_log("You: %s" % text))

        if kind == "weather":
            lang, city = payload
            try:
                temp, unit, cond = fetch_weather(city)
                r = self.brain.weather_reply(lang, temp, unit, cond)
            except Exception:
                r = R("I could not get the weather right now.")
            return self._say(r)

        if kind == "ai":
            key = self.store.read_text("gemini_key.txt")
            if not key:
                return self._say(R("Paste your Gemini API key on the tablet app and tap Save key."))
            try:
                reply = call_gemini(
                    key, self.model, self.brain.system_prompt(), [{"role": "user", "parts": [{"text": text}]}]
                )
                r = self.brain.parse_ai(reply) if reply else R("I have no answer for that.")
            except urllib.error.HTTPError as e:
                msg = {
                    400: "Google rejected the request. Check the API key.",
                    403: "Google rejected the request. Check the API key.",
                    404: "Model not found on the tablet.",
                    429: "Too many requests. Wait a minute.",
                }.get(e.code, "AI error %s." % e.code)
                r = R(msg)
            except Exception as e:
                r = R("I have no internet right now: %s" % e)
            return self._say(r)

        if kind == "search":
            query = payload
            try:
                answer = fetch_instant_answer(query)
            except Exception:
                answer = None
            if answer:
                return self._say(R(answer))
            return {"action": "search", "query": query}

        if kind in ("say", "vault_save", "vault_get", "stop", "off"):
            r = payload
            action = "say" if kind in ("say", "vault_save", "vault_get") else kind
            return {"action": action, "spoken": r.spoken, "shown": r.shown}

        if kind == "model":
            self.model = payload
            self.store.write_text("gemini_model.txt", self.model)
            return self._say(R("Model set to %s." % payload))

        if kind in ("call", "open", "whatsapp"):
            return {"action": kind, "target": payload}
        if kind == "torch":
            return {"action": "torch", "on": bool(payload)}
        if kind == "volume":
            return {"action": "volume", "mode": payload}
        if kind == "settings":
            return {"action": "settings", "page": payload}
        if kind == "battery":
            return {"action": "battery"}
        if kind == "sms":
            name, msg = payload
            return {"action": "sms", "target": name, "text": msg}

        return self._say(R("Sorry, I did not understand that."))

    def _say(self, r):
        Clock.schedule_once(lambda dt: self.add_log("mini: %s" % r.shown))
        return {"action": "say", "spoken": r.spoken, "shown": r.shown}


if __name__ == "__main__":
    MiniBrainApp().run()
