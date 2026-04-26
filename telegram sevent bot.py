"""
Life Servant Bot - Your Personal Telegram Assistant
Fixed: Natural language, weather city parsing, smart replies
"""

import logging
import json
import os
import re
import random
import feedparser  # RSS parser
import requests
from datetime import datetime, timedelta
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    filters, ContextTypes
)

# ============== CONFIG ==============
BOT_TOKEN = "8741610234:AAGLteGHXY07MiWBznQasWhYj1o1VNE2m8k"
ADMIN_IDS = [7802980094]

DATA_FILE = os.path.join(os.path.dirname(__file__), "servant_data.json")

TASK_DESC, TASK_TIME = range(2)
NOTE_TITLE, NOTE_BODY = range(2, 4)

# ============== DATA ==============
class ServantData:
    def __init__(self):
        self.data = self.load()
    
    def load(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {
            'tasks': {}, 'notes': {}, 'expenses': {}, 'habits': {},
            'reminders': [], 'mood_log': {}, 'water_log': {},
            'sleep_log': {}, 'users': set()
        }
    
    def save(self):
        save_data = self.data.copy()
        save_data['users'] = list(save_data.get('users', set()))
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False, default=str)
    
    def get_user_data(self, user_id, key):
        user_id = str(user_id)
        if user_id not in self.data[key]:
            self.data[key][user_id] = []
        return self.data[key][user_id]
    
    def add_user(self, user_id):
        if 'users' not in self.data:
            self.data['users'] = set()
        if isinstance(self.data['users'], list):
            self.data['users'] = set(self.data['users'])
        self.data['users'].add(str(user_id))
        self.save()

db = ServantData()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ============== HELPERS ==============
def get_greeting():
    hour = datetime.now().hour
    if 5 <= hour < 12: return "Good morning"
    elif 12 <= hour < 17: return "Good afternoon"
    elif 17 <= hour < 22: return "Good evening"
    else: return "Good night"

def parse_time(text):
    text = text.lower().strip()
    if text.endswith('m'): return datetime.now() + timedelta(minutes=int(text[:-1]))
    elif text.endswith('h'): return datetime.now() + timedelta(hours=int(text[:-1]))
    elif text.endswith('d'): return datetime.now() + timedelta(days=int(text[:-1]))
    elif text.endswith('s'): return datetime.now() + timedelta(seconds=int(text[:-1]))
    try:
        hour, minute = map(int, text.split(':'))
        target = datetime.now().replace(hour=hour, minute=minute, second=0)
        if target < datetime.now(): target += timedelta(days=1)
        return target
    except: return None

def extract_city(text):
    """Extract city name from natural language."""
    text = text.lower()
    
    # Patterns: "weather in X", "weather at X", "how's the weather in X", etc.
    patterns = [
        r'weather\s+(?:in|at|for)\s+([a-zA-Z\s]+)',
        r'how\'?s?\s+(?:the\s+)?weather\s+(?:in|at|for)\s+([a-zA-Z\s]+)',
        r'what\'?s?\s+(?:the\s+)?weather\s+(?:in|at|for|like\s+in)\s+([a-zA-Z\s]+)',
        r'temperature\s+(?:in|at)\s+([a-zA-Z\s]+)',
        r'forecast\s+(?:in|at|for)\s+([a-zA-Z\s]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    
    # Single word that looks like a city (capitalized or known cities)
    words = text.split()
    for word in words:
        clean = word.strip('.,!?').title()
        if len(clean) > 2 and clean not in ['The', 'How', 'What', 'Will', 'Have', 'Can', 'You', 'For', 'And', 'But', 'Not', 'Are', 'This', 'That']:
            return clean
    
    return None

def is_weather_query(text):
    """Check if text is asking about weather."""
    text = text.lower()
    weather_keywords = ['weather', 'temperature', 'forecast', 'rain', 'sunny', 'cloud', 'hot', 'cold', 'degrees', 'celsius']
    return any(kw in text for kw in weather_keywords)

def is_task_query(text):
    """Check if text is about tasks/todo."""
    text = text.lower()
    return any(kw in text for kw in ['task', 'todo', 'to do', 'need to', 'have to', 'should', 'remind me to', 'don\'t forget'])

def is_greeting(text):
    text = text.lower()
    return any(g in text for g in ['hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening', 'greetings'])

def is_thanks(text):
    text = text.lower()
    return any(t in text for t in ['thanks', 'thank you', 'ty', 'appreciate', 'grateful'])

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("� Morning News", callback_data='menu_news'),
         InlineKeyboardButton("📋 Tasks", callback_data='menu_tasks'),
         InlineKeyboardButton("📝 Notes", callback_data='menu_notes')],
        [InlineKeyboardButton("💧 Water", callback_data='menu_water'),
         InlineKeyboardButton("😴 Sleep", callback_data='menu_sleep'),
         InlineKeyboardButton("😊 Mood", callback_data='menu_mood')],
        [InlineKeyboardButton("💰 Expenses", callback_data='menu_expenses'),
         InlineKeyboardButton("✅ Habits", callback_data='menu_habits'),
         InlineKeyboardButton("🌤 Weather", callback_data='menu_weather')],
        [InlineKeyboardButton("📊 Daily Report", callback_data='menu_report'),
         InlineKeyboardButton("💬 Chat with AI", callback_data='menu_ai')],
        [InlineKeyboardButton("🌅 Morning Routine", callback_data='menu_morning'),
         InlineKeyboardButton("🌙 Evening Routine", callback_data='menu_evening')],
        [InlineKeyboardButton("❓ Help", callback_data='menu_help')]
    ])

def quick_actions_keyboard():
    from telegram import ReplyKeyboardMarkup, KeyboardButton
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📰 News"), KeyboardButton("📋 Tasks")],
            [KeyboardButton("💧 Water"), KeyboardButton("😊 Mood")],
            [KeyboardButton("⏰ Remind Me"), KeyboardButton("📊 Today")],
            [KeyboardButton("💬 Chat"), KeyboardButton("❓ Help")],
        ],
        resize_keyboard=True,
        persistent=True
    )

# ============== WEATHER WITH DETAILS ==============

# ============== AI CHAT ==============

AI_PERSONALITY = """You are a loyal, witty digital servant. You speak to your master with respect but warmth. 
You are helpful, encouraging, and occasionally make light jokes. Keep responses concise (2-3 sentences max)."""

AI_RESPONSES = {
    'tired': ["Rest is important, Master. Shall I set a nap reminder?", "You've earned a break, Master. 💤"],
    'busy': ["I shall keep your tasks organized, Master.", "Focus on what matters. I'll handle the rest."],
    'sad': ["Every storm passes, Master. I'm here.", "Tomorrow brings new light, Master. 🌅"],
    'happy': ["Wonderful to hear, Master! The day is yours!", "Your joy is my command! 🎉"],
    'run': ["Great for the heart, Master! Shall I check the weather first?", "Stay hydrated, Master! 💧"],
    'food': ["Shall I suggest a healthy recipe, Master?", "A well-fed master is a happy master! 🍽️"],
    'work': ["Productivity flows when you do, Master.", "Shall I set a focused work session?"],
}

def detect_mood(text):
    text = text.lower()
    for mood, keywords in [
        ('tired', ['tired', 'exhausted', 'sleepy', 'drained']),
        ('sad', ['sad', 'upset', 'depressed', 'bad day']),
        ('happy', ['happy', 'great', 'amazing', 'awesome', 'good day']),
        ('busy', ['busy', 'swamped', 'overwhelmed', 'so much']),
        ('run', ['run', 'running', 'jog', 'exercise', 'gym']),
        ('food', ['hungry', 'food', 'eat', 'meal', 'cook']),
        ('work', ['work', 'job', 'project', 'deadline']),
    ]:
        if any(k in text for k in keywords):
            return mood
    return None

async def ai_chat_response(text, user_name="Master"):
    mood = detect_mood(text)
    if mood and mood in AI_RESPONSES:
        return random.choice(AI_RESPONSES[mood])
    
    # Default contextual responses
    defaults = [
        f"I understand, {user_name}. How may I assist further?",
        f"Noted, {user_name}. Shall I log this or set a reminder?",
        f"Understood. Your servant is always ready. ⚡",
    ]
    return random.choice(defaults)

# ============== NEWS SOURCES ==============

NEWS_SOURCES = {
    'bloomberg': {
        'name': 'Bloomberg',
        'rss': 'https://feeds.bloomberg.com/business/news.rss',
        'emoji': '📈'
    },
    'yahoo_finance': {
        'name': 'Yahoo Finance',
        'rss': 'https://finance.yahoo.com/news/rssindex',
        'emoji': '💹'
    },
    'hespress': {
        'name': 'Hespress',
        'rss': 'https://www.hespress.com/feed',
        'emoji': '🇲🇦'
    }
}

async def fetch_news(source_key, max_items=5):
    """Fetch news from RSS feed."""
    source = NEWS_SOURCES.get(source_key)
    if not source:
        return None
    
    try:
        feed = feedparser.parse(source['rss'])
        items = []
        
        for entry in feed.entries[:max_items]:
            title = entry.get('title', 'No title')
            link = entry.get('link', '')
            summary = entry.get('summary', '')[:150] + '...' if len(entry.get('summary', '')) > 150 else entry.get('summary', '')
            published = entry.get('published', '')[:16]
            
            items.append({
                'title': title,
                'link': link,
                'summary': summary,
                'date': published
            })
        
        return {
            'source_name': source['name'],
            'emoji': source['emoji'],
            'items': items
        }
    except Exception as e:
        return {'error': str(e), 'source_name': source['name'], 'emoji': source['emoji'], 'items': []}

async def fetch_weather_detailed(city):
    """Fetch detailed weather using OpenWeatherMap free API."""
    # Using OpenWeatherMap free tier (no API key needed for basic, but better with one)
    # For demo, we'll use wttr.in detailed format which gives more info
    try:
        url = f"https://wttr.in/{city}?format=j1"
        r = requests.get(url, timeout=15)
        data = r.json()

        current = data['current_condition'][0]
        weather = data['weather'][0]
        hourly = weather['hourly']

        result = {
            'city': city.title(),
            'temp_c': current['temp_C'],
            'temp_f': current['temp_F'],
            'feels_like_c': current['FeelsLikeC'],
            'feels_like_f': current['FeelsLikeF'],
            'humidity': current['humidity'],
            'wind_kmph': current['windspeedKmph'],
            'wind_dir': current['winddir16Point'],
            'pressure': current['pressure'],
            'visibility': current['visibility'],
            'uv_index': current['uvIndex'],
            'description': current['weatherDesc'][0]['value'],
            'sunrise': weather['astronomy'][0]['sunrise'],
            'sunset': weather['astronomy'][0]['sunset'],
            'max_temp': weather['maxtempC'],
            'min_temp': weather['mintempC'],
            'hourly': []
        }

        for h in hourly[:8]:
            result['hourly'].append({
                'time': f"{int(h['time'])//100:02d}:00",
                'temp': h['tempC'],
                'feels_like': h['FeelsLikeC'],
                'description': h['weatherDesc'][0]['value'],
                'chance_of_rain': h['chanceofrain'],
                'wind': h['windspeedKmph']
            })

        return result
    except Exception:
        return None

async def send_weather(update, city):
    """Send detailed weather response."""
    city = city.strip().title()
    data = await fetch_weather_detailed(city)

    if not data:
        try:
            url = f"https://wttr.in/{city}?format=3"
            r = requests.get(url, timeout=10)
            simple = r.text.strip()
            await update.message.reply_text(
                f"🌤 *Weather in {city}:*\n\n`{simple}`\n\n"
                f"_Sorry, detailed forecast unavailable. Try again later._",
                parse_mode='Markdown'
            )
        except Exception:
            await update.message.reply_text(
                f"❌ Could not find weather for *{city}*.\n\nTry: `/weather Casablanca`",
                parse_mode='Markdown'
            )
        return

    emoji_map = {
        'sunny': '☀️', 'clear': '✨', 'partly cloudy': '⛅', 'cloudy': '☁️',
        'overcast': '☁️', 'rain': '🌧️', 'light rain': '🌦️', 'heavy rain': '⛈️',
        'snow': '❄️', 'fog': '🌫️', 'mist': '🌫️', 'thunder': '⛈️',
        'drizzle': '🌦️', 'showers': '🌧️'
    }

    desc_lower = data['description'].lower()
    emoji = '☁️'
    for key, em in emoji_map.items():
        if key in desc_lower:
            emoji = em
            break

    text = f"""
{emoji} *WEATHER IN {data['city'].upper()}*

*Now:* {data['temp_c']}°C (feels like {data['feels_like_c']}°C)
_{data['description']}_

*Today:*
🌡 High: {data['max_temp']}°C | Low: {data['min_temp']}°C
💧 Humidity: {data['humidity']}%
💨 Wind: {data['wind_kmph']} km/h {data['wind_dir']}
👁 Visibility: {data['visibility']} km
🔆 UV Index: {data['uv_index']}
🌅 Sunrise: {data['sunrise']}
🌇 Sunset: {data['sunset']}

*Next Hours:*
"""

    for h in data['hourly']:
        rain = f" 🌧{h['chance_of_rain']}%" if int(h['chance_of_rain']) > 20 else ""
        text += f"`{h['time']}` {h['temp']}°C _{h['description']}_{rain}\n"

    text += f"\n_Have a great day, Master! 🏃‍♂️_"
    await update.message.reply_text(text, parse_mode='Markdown')

# ============== COMMANDS ==============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id)
    greeting = get_greeting()
    
    welcome = f"""
{greeting}, *Master {user.first_name}*! 🌟

I am your personal life servant. I will help you:
• Remember tasks and deadlines
• Track habits and water intake
• Log expenses and sleep
• Save notes and set reminders
• Monitor your daily mood
• Check weather anywhere

*Your wish is my command.* Choose below:
    """
    
    await update.message.reply_text(welcome, parse_mode='Markdown', reply_markup=main_menu_keyboard())
    await update.message.reply_text(
        "Or use quick actions below:",
        reply_markup=quick_actions_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 *LIFE SERVANT COMMANDS*

*Daily Management:*
`/tasks` - View tasks
`/addtask` - Add task (interactive)
`/done <number>` - Complete task

*Health & Wellness:*
`/water [amount]` - Log water (default 250ml)
`/sleep <hours>` - Log sleep
`/mood <1-10>` - Log mood
`/habits` - View habits

*Productivity:*
`/notes` - View notes
`/addnote` - Add note
`/remind <time> <text>` - Set reminder
  Examples: `/remind 10m Call mom`, `/remind 15:30 Meeting`

*Weather:*
`/weather <city>` - Get weather
  Also works naturally: "How's the weather in Alhoceima?"

*Finance:*
`/expense <amount> <category>` - Log expense
`/expenses` - View today's expenses

*Reports:*
`/today` - Daily overview
`/morning` - Morning routine
`/evening` - Evening routine
`/quote` - Motivation

*Just chat with me naturally too!* 😊
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

# ============== TASKS ==============

async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    tasks = db.get_user_data(user_id, 'tasks')
    pending = [t for t in tasks if not t.get('done')]
    
    if not pending:
        await update.message.reply_text("📭 *No pending tasks, Master!*\n\nUse /addtask to create one.", parse_mode='Markdown')
        return
    
    text = "📋 *Your Tasks:*\n\n"
    for i, t in enumerate(pending, 1):
        dl = t.get('deadline', '')
        dl_text = f" (by {dl})" if dl else ""
        text += f"`[{i}]` {t['desc']}{dl_text}\n"
    text += "\nUse `/done <number>` to complete."
    await update.message.reply_text(text, parse_mode='Markdown')

async def addtask_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 *What is the task?*\n\nDescribe what needs to be done:", parse_mode='Markdown')
    return TASK_DESC

async def addtask_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['task_desc'] = update.message.text
    await update.message.reply_text("⏰ *When is it due?*\n\nExamples: `today`, `tomorrow`, `3pm`, `none`", parse_mode='Markdown')
    return TASK_TIME

async def addtask_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    desc = context.user_data.get('task_desc', 'Untitled')
    deadline = update.message.text
    if deadline.lower() in ['none', 'no', 'skip', '']: deadline = ''
    
    task = {
        'id': len(db.data['tasks'].get(user_id, [])) + 1,
        'desc': desc, 'deadline': deadline, 'done': False,
        'created': datetime.now().isoformat()
    }
    db.get_user_data(user_id, 'tasks').append(task)
    db.save()
    
    dl_text = f" (Due: {deadline})" if deadline else ""
    await update.message.reply_text(f"✅ *Task added!*{dl_text}\n\n_{desc}_", parse_mode='Markdown')
    return ConversationHandler.END

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    tasks = db.get_user_data(user_id, 'tasks')
    pending = [t for t in tasks if not t.get('done')]
    
    if not context.args:
        if not pending:
            await update.message.reply_text("No pending tasks!")
            return
        text = "Which task is done?\n\n"
        for i, t in enumerate(pending, 1):
            text += f"`{i}`. {t['desc']}\n"
        text += "\nReply with the number."
        context.user_data['awaiting_done'] = True
        await update.message.reply_text(text, parse_mode='Markdown')
        return
    
    try:
        idx = int(context.args[0]) - 1
        if 0 <= idx < len(pending):
            pending[idx]['done'] = True
            db.save()
            await update.message.reply_text(f"🎉 *Task completed!*\n\n_{pending[idx]['desc']}_\n\nGreat work, Master!", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Invalid task number.")
    except ValueError:
        await update.message.reply_text("❌ Please provide a number.")

# ============== NOTES ==============

async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    notes = db.get_user_data(user_id, 'notes')
    if not notes:
        await update.message.reply_text("📝 *No notes yet.*\n\nUse /addnote to create one.", parse_mode='Markdown')
        return
    
    text = "📝 *Your Notes:*\n\n"
    for i, n in enumerate(notes[-5:], 1):
        date = n.get('date', '')[:10]
        text += f"*{i}. {n['title']}* ({date})\n_{n['body'][:100]}..._\n\n"
    await update.message.reply_text(text, parse_mode='Markdown')

async def addnote_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 *Note Title:*", parse_mode='Markdown')
    return NOTE_TITLE

async def addnote_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['note_title'] = update.message.text
    await update.message.reply_text("✍️ *Note Content:*", parse_mode='Markdown')
    return NOTE_BODY

async def addnote_body(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    title = context.user_data.get('note_title', 'Untitled')
    body = update.message.text
    
    db.get_user_data(user_id, 'notes').append({
        'title': title, 'body': body, 'date': datetime.now().isoformat()
    })
    db.save()
    await update.message.reply_text(f"✅ *Note saved!*\n\n*{title}*", parse_mode='Markdown')
    return ConversationHandler.END

# ============== WATER ==============

async def water(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    today = datetime.now().strftime("%Y-%m-%d")
    
    amount = 250
    if context.args:
        try: amount = int(context.args[0])
        except: pass
    
    if user_id not in db.data['water_log']:
        db.data['water_log'][user_id] = {}
    db.data['water_log'][user_id][today] = db.data['water_log'][user_id].get(today, 0) + amount
    db.save()
    
    total = db.data['water_log'][user_id][today]
    glasses = total / 250
    progress = min(100, (total / 2000) * 100)
    bar = "█" * int(progress / 10) + "░" * (10 - int(progress / 10))
    
    await update.message.reply_text(
        f"💧 *Water Logged: +{amount}ml*\n\n"
        f"Today: *{total}ml* ({glasses:.1f} glasses)\n"
        f"Progress: [{bar}] {progress:.0f}%\n"
        f"Goal: 2000ml\n\n"
        f"{'🎉 Goal reached!' if total >= 2000 else 'Keep drinking, Master! 💪'}",
        parse_mode='Markdown'
    )

# ============== SLEEP ==============

async def sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    if not context.args:
        log = db.data['sleep_log'].get(user_id, {})
        dates = sorted(log.keys(), reverse=True)[:3]
        if not dates:
            await update.message.reply_text("😴 *No sleep logged.*\n\nUse: `/sleep 7.5`", parse_mode='Markdown')
            return
        
        text = "😴 *Recent Sleep:*\n\n"
        for d in dates:
            hours = log[d]
            quality = "💤 Good" if hours >= 7 else "⚠️ Low" if hours < 6 else "😐 Okay"
            text += f"{d}: *{hours}h* {quality}\n"
        await update.message.reply_text(text, parse_mode='Markdown')
        return
    
    try:
        hours = float(context.args[0])
        today = datetime.now().strftime("%Y-%m-%d")
        if user_id not in db.data['sleep_log']:
            db.data['sleep_log'][user_id] = {}
        db.data['sleep_log'][user_id][today] = hours
        db.save()
        
        quality = "Excellent" if hours >= 8 else "Good" if hours >= 7 else "Fair" if hours >= 6 else "Poor"
        emoji = "😴" if hours >= 7 else "😪"
        await update.message.reply_text(
            f"{emoji} *Sleep Logged: {hours}h*\n\nQuality: *{quality}*\nRecommended: 7-9 hours",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("❌ Usage: `/sleep 7.5`")

# ============== MOOD ==============

async def mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    if not context.args:
        log = db.data['mood_log'].get(user_id, {})
        dates = sorted(log.keys(), reverse=True)[:7]
        if not dates:
            await update.message.reply_text("😊 *Rate your mood*\n\nUse: `/mood 8` (1-10)", parse_mode='Markdown')
            return
        
        text = "😊 *Mood History:*\n\n"
        for d in dates:
            score = log[d]
            emoji = "🤩" if score >= 9 else "😊" if score >= 7 else "😐" if score >= 5 else "😔" if score >= 3 else "😢"
            text += f"{d}: {emoji} *{score}/10*\n"
        avg = sum(log[d] for d in dates) / len(dates)
        text += f"\nAverage: *{avg:.1f}/10*"
        await update.message.reply_text(text, parse_mode='Markdown')
        return
    
    try:
        score = int(context.args[0])
        if not 1 <= score <= 10: raise ValueError
        
        today = datetime.now().strftime("%Y-%m-%d")
        if user_id not in db.data['mood_log']:
            db.data['mood_log'][user_id] = {}
        db.data['mood_log'][user_id][today] = score
        db.save()
        
        emojis = {10: "🤩", 9: "😄", 8: "😊", 7: "🙂", 6: "😐", 5: "😕", 4: "😔", 3: "😟", 2: "😢", 1: "💔"}
        msgs = {
            10: "Absolutely fantastic!", 9: "Wonderful day!", 8: "Great mood!",
            7: "Good vibes!", 6: "Steady as she goes.", 5: "Hope it gets better!",
            4: "Hang in there.", 3: "Tough day? I'm here.", 2: "Sending hugs.", 1: "Tomorrow will be better."
        }
        await update.message.reply_text(f"{emojis[score]} *Mood: {score}/10*\n\n_{msgs[score]}_", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ Rate 1-10. Example: `/mood 8`")

# ============== EXPENSES ==============

async def expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 2:
        await update.message.reply_text("💰 Usage: `/expense 50 coffee`", parse_mode='Markdown')
        return
    
    try:
        amount = float(context.args[0])
        category = ' '.join(context.args[1:]).title()
        today = datetime.now().strftime("%Y-%m-%d")
        
        db.get_user_data(user_id, 'expenses').append({
            'amount': amount, 'category': category,
            'date': today, 'time': datetime.now().strftime("%H:%M")
        })
        db.save()
        
        today_total = sum(e['amount'] for e in db.get_user_data(user_id, 'expenses') if e['date'] == today)
        await update.message.reply_text(
            f"💰 *Expense Logged*\n\nAmount: ${amount:.2f}\nCategory: {category}\nToday's Total: *${today_total:.2f}*",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("❌ Usage: `/expense 50 coffee`")

async def expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    today = datetime.now().strftime("%Y-%m-%d")
    exps = [e for e in db.get_user_data(user_id, 'expenses') if e['date'] == today]
    
    if not exps:
        await update.message.reply_text("💰 No expenses today. Great savings!")
        return
    
    text = f"💰 *Today's Expenses:*\n\n"
    total = 0
    for e in exps:
        text += f"• {e['category']}: ${e['amount']:.2f}\n"
        total += e['amount']
    text += f"\n*Total: ${total:.2f}*"
    await update.message.reply_text(text, parse_mode='Markdown')

# ============== HABITS ==============

async def habits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    habits = db.get_user_data(user_id, 'habits')
    
    if not habits:
        await update.message.reply_text("✅ No habits yet. Use `/addhabit <name>`", parse_mode='Markdown')
        return
    
    today = datetime.now().strftime("%Y-%m-%d")
    text = "✅ *Your Habits:*\n\n"
    for i, h in enumerate(habits, 1):
        done = today in h.get('completed', [])
        streak = h.get('streak', 0)
        status = "✅ Done" if done else "⬜ Not done"
        text += f"`{i}`. {h['name']}\n   {status} | 🔥 {streak} days\n\n"
    text += "Use `/checkin <number>` to mark done."
    await update.message.reply_text(text, parse_mode='Markdown')

async def addhabit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    name = ' '.join(context.args)
    if not name:
        await update.message.reply_text("❌ Usage: `/addhabit Morning meditation`")
        return
    
    db.get_user_data(user_id, 'habits').append({
        'name': name, 'created': datetime.now().isoformat(),
        'completed': [], 'streak': 0
    })
    db.save()
    await update.message.reply_text(f"✅ *Habit created!*\n\n_{name}_", parse_mode='Markdown')

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    habits = db.get_user_data(user_id, 'habits')
    
    if not context.args:
        await update.message.reply_text("❌ Usage: `/checkin 1`")
        return
    
    try:
        idx = int(context.args[0]) - 1
        if 0 <= idx < len(habits):
            today = datetime.now().strftime("%Y-%m-%d")
            h = habits[idx]
            if today in h.get('completed', []):
                await update.message.reply_text("✅ Already checked in!")
                return
            if 'completed' not in h: h['completed'] = []
            h['completed'].append(today)
            h['streak'] = len(h['completed'])
            db.save()
            await update.message.reply_text(f"🔥 *Checked in!*\n\n_{h['name']}_\nStreak: *{h['streak']} days*", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Invalid habit number.")
    except ValueError:
        await update.message.reply_text("❌ Please provide a number.")

# ============== REMINDERS ==============

async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "⏰ Usage: `/remind <when> <message>`\n\n"
            "Examples:\n• `/remind 10m Call mom`\n• `/remind 2h Take medicine`\n• `/remind 15:30 Meeting`",
            parse_mode='Markdown'
        )
        return
    
    when = context.args[0]
    message = ' '.join(context.args[1:])
    target = parse_time(when)
    
    if not target:
        await update.message.reply_text("❌ Try: `10m`, `2h`, `15:30`", parse_mode='Markdown')
        return
    
    seconds = (target - datetime.now()).total_seconds()
    if seconds <= 0:
        await update.message.reply_text("❌ Time must be in the future!")
        return
    
    context.job_queue.run_once(
        send_reminder, seconds,
        chat_id=update.effective_chat.id,
        data={'message': message, 'user_id': update.effective_user.id}
    )
    
    await update.message.reply_text(
        f"⏰ *Reminder Set*\n\nMessage: _{message}_\nTime: *{target.strftime('%I:%M %p')}*",
        parse_mode='Markdown'
    )

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(
        job.chat_id,
        f"⏰ *REMINDER, MASTER!*\n\n_{job.data['message']}_",
        parse_mode='Markdown'
    )

# ============== WEATHER COMMAND ==============

async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Weather command with city argument."""
    city = ' '.join(context.args) if context.args else None
    
    if not city:
        await update.message.reply_text(
            "🌤 *Weather Check*\n\n"
            "Usage: `/weather Alhoceima`\n"
            "Or just ask: \"How's the weather in Alhoceima?\"",
            parse_mode='Markdown'
        )
        return
    
    await send_weather(update, city)

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch morning news from all sources."""
    args = context.args
    source = args[0].lower() if args else 'all'
    
    if source == 'all':
        sources = ['bloomberg', 'yahoo_finance', 'hespress']
    elif source in NEWS_SOURCES:
        sources = [source]
    else:
        await update.message.reply_text(
            "📰 *News Sources:*\n\n"
            "`/news` - All sources\n"
            "`/news bloomberg` - Bloomberg only\n"
            "`/news yahoo_finance` - Yahoo Finance\n"
            "`/news hespress` - Hespress (Arabic)\n\n"
            "Or use the 📰 Morning News button!",
            parse_mode='Markdown'
        )
        return
    
    await update.message.reply_text("📰 *Fetching your morning news, Master...*", parse_mode='Markdown')
    
    for src in sources:
        data = await fetch_news(src, max_items=3)

        if 'error' in data:
            await update.message.reply_text(
                f"❌ Could not fetch {data['emoji']} *{data['source_name']}*",
                parse_mode='Markdown'
            )
            continue
        
        text = f"{data['emoji']} *{data['source_name']}*\n"
        text += "━" * 20 + "\n\n"
        
        for i, item in enumerate(data['items'], 1):
            title = item['title'][:80] + '...' if len(item['title']) > 80 else item['title']
            text += f"{i}. *{title}*\n"
            if item['summary']:
                text += f"   _{item['summary'][:100]}_\n"
            text += f"   [Read more]({item['link']})\n\n"
        
        await update.message.reply_text(
            text,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )

# ============== REPORTS ==============

async def today_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    today = datetime.now().strftime("%Y-%m-%d")
    
    tasks_list = db.get_user_data(user_id, 'tasks')
    pending = len([t for t in tasks_list if not t.get('done')])
    completed = len([t for t in tasks_list if t.get('done')])
    water = db.data['water_log'].get(user_id, {}).get(today, 0)
    sleep_h = db.data['sleep_log'].get(user_id, {}).get(today, 0)
    mood_s = db.data['mood_log'].get(user_id, {}).get(today, 0)
    exp_total = sum(e['amount'] for e in db.get_user_data(user_id, 'expenses') if e['date'] == today)
    habits_list = db.get_user_data(user_id, 'habits')
    habits_done = sum(1 for h in habits_list if today in h.get('completed', []))
    
    text = f"""
📊 *DAILY REPORT - {today}*

📋 *Tasks:* {completed} done, {pending} pending
💧 *Water:* {water}ml / 2000ml
😴 *Sleep:* {sleep_h}h logged
😊 *Mood:* {mood_s}/10
💰 *Spent:* ${exp_total:.2f}
✅ *Habits:* {habits_done}/{len(habits_list)} checked in

Keep going, Master! 💪
    """
    await update.message.reply_text(text.strip(), parse_mode='Markdown')

async def morning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
🌅 *MORNING ROUTINE*

Start your day right, Master:

⬜ Drink water (/water)
⬜ Stretch or exercise (5 min)
⬜ Review tasks (/tasks)
⬜ Set 3 priorities
⬜ Check habits (/habits)
⬜ Log mood (/mood 7)

*Rise and shine!* ☀️
    """
    await update.message.reply_text(text.strip(), parse_mode='Markdown')
    
    # Auto-fetch news summary
    await update.message.reply_text("📰 *Fetching your morning briefing...*", parse_mode='Markdown')
    context.args = ['all']
    await news(update, context)

async def evening(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
🌙 *EVENING ROUTINE*

Wind down, Master:

⬜ Review completed tasks
⬜ Log water for the day
⬜ Log sleep (/sleep 7)
⬜ Log mood (/mood 8)
⬜ Review expenses
⬜ Plan tomorrow

*Rest well!* 😴
    """
    await update.message.reply_text(text.strip(), parse_mode='Markdown')

async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import random
    quotes = [
        "The only way to do great work is to love what you do. — Steve Jobs",
        "Success is not final, failure is not fatal: it is the courage to continue that counts. — Churchill",
        "Believe you can and you're halfway there. — Roosevelt",
        "The future depends on what you do today. — Gandhi",
        "Don't watch the clock; do what it does. Keep going. — Sam Levenson",
        "Your time is limited, don't waste it. — Steve Jobs",
        "The best time to plant a tree was 20 years ago. The second best time is now.",
        "Everything you want is on the other side of fear. — George Addair"
    ]
    await update.message.reply_text(f"💫 *{random.choice(quotes)}*", parse_mode='Markdown')

# ============== SMART MESSAGE HANDLER ==============

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    lower = text.lower()
    user_name = update.effective_user.first_name

    # Quick action buttons
    quick_map = {
        '📰 news': '/news',
        '🌤 weather': '/weather',
        '📋 tasks': '/tasks',
        '💧 water': '/water',
        '😊 mood': '/mood',
        '⏰ remind me': '/remind',
        '📊 today': '/today',
        '💬 chat': 'chat',
        '❓ help': '/help'
    }

    if lower in quick_map:
        action = quick_map[lower]
        if action == 'chat':
            await update.message.reply_text("💬 I'm listening, Master. What's on your mind?")
            return
        if action == '/weather':
            await update.message.reply_text("🌤 Which city? Type: `Alhoceima` or use `/weather Alhoceima`", parse_mode='Markdown')
            return
        elif action == '/mood':
            await update.message.reply_text("😊 Rate your mood: `/mood 8` (1-10)", parse_mode='Markdown')
            return
        elif action == '/remind':
            await update.message.reply_text("⏰ Usage: `/remind 10m Call mom`", parse_mode='Markdown')
            return
        elif action == '/today':
            await today_report(update, context)
            return
        elif action == '/news':
            context.args = []
            await news(update, context)
            return
        elif action == '/help':
            await help_command(update, context)
            return
        elif action == '/tasks':
            await tasks(update, context)
            return
        elif action == '/water':
            await water(update, context)
            return

    # Weather
    if is_weather_query(lower):
        city = extract_city(text)
        if city:
            await send_weather(update, city)
            return
        await update.message.reply_text("🌤 Which city? Try: `/weather Alhoceima`", parse_mode='Markdown')
        return

    # Tasks
    if is_task_query(lower):
        task_words = ['need to', 'have to', 'should', 'must', 'remind me to', 'don\'t forget to']
        task_text = None
        for kw in task_words:
            if kw in lower:
                idx = lower.find(kw) + len(kw)
                task_text = text[idx:].strip()
                break
        if task_text:
            user_id = str(update.effective_user.id)
            db.get_user_data(user_id, 'tasks').append({
                'id': len(db.data['tasks'].get(user_id, [])) + 1,
                'desc': task_text, 'deadline': '', 'done': False,
                'created': datetime.now().isoformat()
            })
            db.save()
            ai_reply = await ai_chat_response(f"task: {task_text}", user_name)
            await update.message.reply_text(
                f"📝 *Task saved!*\n_{task_text}_\n\n{ai_reply}",
                parse_mode='Markdown'
            )
            return

    # Greetings
    if is_greeting(lower):
        greeting = get_greeting()
        await update.message.reply_text(
            f"{greeting}, {user_name}! 🌟\n\n{await ai_chat_response('greeting', user_name)}",
            reply_markup=main_menu_keyboard()
        )
        return

    # Thanks
    if is_thanks(lower):
        await update.message.reply_text(f"🙇 Always at your service, {user_name}!")
        return

    # AI fallback for everything else
    ai_reply = await ai_chat_response(text, user_name)
    await update.message.reply_text(
        f"{ai_reply}\n\n_Try `/help` or tap a button below._",
        reply_markup=main_menu_keyboard(),
        parse_mode='Markdown'
    )

# ============== CALLBACKS ==============

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    menus = {
        'menu_tasks': "📋 *Tasks*\n\n/tasks - View\n/addtask - Add\n/done <num> - Complete",
        'menu_notes': "📝 *Notes*\n\n/notes - View\n/addnote - Add",
        'menu_expenses': "💰 *Expenses*\n\n/expense 50 coffee\n/expenses - View today",
        'menu_water': "💧 *Water*\n\n/water - Log 250ml\n/water 500 - Custom",
        'menu_sleep': "😴 *Sleep*\n\n/sleep 7.5 - Log hours\n/sleep - View history",
        'menu_mood': "😊 *Mood*\n\n/mood 8 - Rate 1-10\n/mood - View history",
        'menu_habits': "✅ *Habits*\n\n/habits - View\n/addhabit <name>\n/checkin <num>",
        'menu_reminders': "⏰ *Reminders*\n\n/remind 10m Call mom\n/remind 15:30 Meeting",
        'menu_weather': "🌤 *Weather*\n\n/weather <city>\nOr ask naturally: \"How's weather in Alhoceima?\"",
        'menu_report': "📊 *Reports*\n\n/today - Daily overview\n/morning - Morning routine\n/evening - Evening routine",
        'menu_ai': "💬 *AI Chat*\n\nJust talk to me naturally!\n\nExamples:\n• \"I'm tired\"\n• \"Going for a run\"\n• \"I need to buy groceries\"\n• \"How's the weather in Alhoceima?\"",
        'menu_news': "📰 *Morning News*\n\n`/news` - All sources\n`/news bloomberg` - Bloomberg\n`/news yahoo_finance` - Yahoo Finance\n`/news hespress` - Hespress 🇲🇦",
        'menu_morning': "🌅 *Morning Routine*\n\nUse /morning for your checklist!",
        'menu_evening': "🌙 *Evening Routine*\n\nUse /evening to wind down!",
        'menu_help': "❓ *Help*\n\nUse /help for full command list!"
    }
    
    if query.data in menus:
        await query.edit_message_text(menus[query.data], parse_mode='Markdown')

# ============== MAIN ==============

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("tasks", tasks))
    application.add_handler(CommandHandler("done", done))
    application.add_handler(CommandHandler("notes", notes))
    application.add_handler(CommandHandler("water", water))
    application.add_handler(CommandHandler("sleep", sleep))
    application.add_handler(CommandHandler("mood", mood))
    application.add_handler(CommandHandler("expense", expense))
    application.add_handler(CommandHandler("expenses", expenses))
    application.add_handler(CommandHandler("habits", habits))
    application.add_handler(CommandHandler("addhabit", addhabit))
    application.add_handler(CommandHandler("checkin", checkin))
    application.add_handler(CommandHandler("remind", remind))
    application.add_handler(CommandHandler("weather", weather))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("today", today_report))
    application.add_handler(CommandHandler("morning", morning))
    application.add_handler(CommandHandler("evening", evening))
    application.add_handler(CommandHandler("quote", quote))
    
    # Conversations
    task_conv = ConversationHandler(
        entry_points=[CommandHandler("addtask", addtask_start)],
        states={
            TASK_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtask_desc)],
            TASK_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addtask_time)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: u.message.reply_text("Cancelled."))]
    )
    application.add_handler(task_conv)
    
    note_conv = ConversationHandler(
        entry_points=[CommandHandler("addnote", addnote_start)],
        states={
            NOTE_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addnote_title)],
            NOTE_BODY: [MessageHandler(filters.TEXT & ~filters.COMMAND, addnote_body)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: u.message.reply_text("Cancelled."))]
    )
    application.add_handler(note_conv)
    
    # Callbacks & messages
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 Life Servant Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()