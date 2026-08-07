import sqlite3
import time
import random
import os
import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ================= CONFIG =================
BOT_TOKEN = "8857671587:AAFKa4LZVj7_H1Sjzqn1JK1S4WrCyaU8TMc"
ADMIN_ID = 7443685686
BOT_USERNAME = "Hamzzylogs01_bot"

BANK_NAME = "OPAY"
ACCOUNT_NUMBER = "9032741650"
ACCOUNT_NAME = "MUHAMMED JAMIU JAMZA"

LOW_STOCK_LIMIT = 3
REFERRAL_BONUS = 250

PRODUCTS = {
    "0 (#1000)": 1000, "30-40 (#1500)": 1500, "50-80 (#2000)": 2000,
    "90-100 (#3000)": 3000, "200 (#4000)": 4000, "300 (#5000)": 5000,
    "400 (#5500)": 5500, "500 (#6000)": 6000, "600 (#6500)": 6500,
    "700 (#7000)": 7000, "800 (#7500)": 7500, "900 (#8000)": 8000,
    "1000 (#8500)": 8500
}

# ================= DATABASE =================
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT, amount INTEGER, details TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, value INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS deposits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, sender_name TEXT, ref TEXT, amount INTEGER DEFAULT 0, status TEXT DEFAULT 'pending', decline_reason TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, issue_type TEXT, description TEXT, status TEXT DEFAULT 'open', admin_response TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
cursor.execute("CREATE TABLE IF NOT EXISTS stock (id INTEGER PRIMARY KEY AUTOINCREMENT, product_name TEXT, email TEXT, status TEXT DEFAULT 'available')")
cursor.execute("CREATE TABLE IF NOT EXISTS sales_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product_name TEXT, amount INTEGER, sale_date DATE)")
cursor.execute("CREATE TABLE IF NOT EXISTS referrals (id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER, referred_id INTEGER UNIQUE)")
cursor.execute("CREATE TABLE IF NOT EXISTS referral_earnings (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, from_user_id INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS broadcast_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, message TEXT, total_sent INTEGER, total_failed INTEGER, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
cursor.execute("CREATE TABLE IF NOT EXISTS restock_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, product_name TEXT, quantity INTEGER, restock_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
cursor.execute("CREATE TABLE IF NOT EXISTS cart (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product_name TEXT, price INTEGER, quantity INTEGER DEFAULT 1)")

conn.commit()
for k in ["revenue","orders"]:
    cursor.execute("INSERT OR IGNORE INTO stats (key,value) VALUES (?,0)", (k,))
conn.commit()

# ================= MEMORY =================
pending_approvals = {}
fraud_tracker = {}
blocked_users = set()
user_support_mode = {}
user_data = {}

# ================= HELPERS =================
def get_balance(uid):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r[0] if r else 0

def add_user(uid):
    cursor.execute("INSERT OR IGNORE INTO users (user_id,balance) VALUES (?,0)", (uid,))
    conn.commit()

def update_stat(k,v):
    cursor.execute("UPDATE stats SET value=value+? WHERE key=?", (v,k))
    conn.commit()

def get_stat(k):
    cursor.execute("SELECT value FROM stats WHERE key=?", (k,))
    r = cursor.fetchone()
    return r[0] if r else 0

def log(uid,t,amt,d):
    cursor.execute("INSERT INTO transactions (user_id,type,amount,details) VALUES (?,?,?,?)",(uid,t,amt,d))
    conn.commit()

def generate_ref():
    return f"REF-{random.randint(100000,999999)}"

def get_stock_count(product_name):
    cursor.execute("SELECT COUNT(*) FROM stock WHERE product_name=? AND status='available'", (product_name,))
    return cursor.fetchone()[0]

def get_all_stock():
    stock = {}
    for name in PRODUCTS:
        cursor.execute("SELECT COUNT(*) FROM stock WHERE product_name=? AND status='available'", (name,))
        stock[name] = cursor.fetchone()[0]
    return stock

def get_item_from_stock(product_name):
    cursor.execute("SELECT id, email FROM stock WHERE product_name=? AND status='available' LIMIT 1", (product_name,))
    return cursor.fetchone()

def mark_item_sold(item_id):
    cursor.execute("UPDATE stock SET status='sold' WHERE id=?", (item_id,))
    conn.commit()

def add_to_stock(product_name, email):
    cursor.execute("SELECT id FROM stock WHERE email=? AND status='available'", (email,))
    if cursor.fetchone(): return False
    cursor.execute("INSERT INTO stock (product_name, email) VALUES (?,?)", (product_name, email))
    conn.commit()
    return True

def add_bulk_to_stock(product_name, emails):
    added = 0
    for email in emails:
        if add_to_stock(product_name, email): added += 1
    return added

def clear_all_stock():
    cursor.execute("DELETE FROM stock"); conn.commit()

def clear_product_stock(product_name):
    cursor.execute("DELETE FROM stock WHERE product_name=?", (product_name,))
    conn.commit()

def extract_stock(product_name):
    cursor.execute("SELECT email FROM stock WHERE product_name=? AND status='available'", (product_name,))
    rows = cursor.fetchall()
    return [r[0] for r in rows]

def get_cart(user_id):
    cursor.execute("SELECT id, product_name, price, quantity FROM cart WHERE user_id=?", (user_id,))
    return cursor.fetchall()

def add_to_cart(user_id, product_name, price):
    cursor.execute("SELECT id, quantity FROM cart WHERE user_id=? AND product_name=?", (user_id, product_name))
    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE cart SET quantity=quantity+1 WHERE id=?", (row[0],))
    else:
        cursor.execute("INSERT INTO cart (user_id, product_name, price, quantity) VALUES (?,?,?,1)", (user_id, product_name, price))
    conn.commit()

def remove_from_cart(user_id, cart_id):
    cursor.execute("DELETE FROM cart WHERE id=? AND user_id=?", (cart_id, user_id))
    conn.commit()

def clear_cart(user_id):
    cursor.execute("DELETE FROM cart WHERE user_id=?", (user_id,))
    conn.commit()

def get_cart_total(user_id):
    cursor.execute("SELECT SUM(price * quantity) FROM cart WHERE user_id=?", (user_id,))
    r = cursor.fetchone()
    return r[0] if r[0] else 0

def generate_referral_link(user_id):
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

def get_items_from_stock(product_name, quantity):
    cursor.execute("SELECT id, email FROM stock WHERE product_name=? AND status='available' LIMIT ?", (product_name, quantity))
    return cursor.fetchall()

# ================= BOT INIT =================
bot = telebot.TeleBot(BOT_TOKEN)

# ================= START =================
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    add_user(user_id)
    user_support_mode.pop(user_id, None)
    user_data.pop(user_id, None)
    
    # Handle referral
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
            if referrer_id != user_id:
                cursor.execute("SELECT id FROM referrals WHERE referred_id=?", (user_id,))
                if not cursor.fetchone() and referrer_id != user_id:
                    cursor.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?,?)", (referrer_id, user_id))
                    cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (REFERRAL_BONUS, referrer_id))
                    cursor.execute("INSERT INTO referral_earnings (user_id, amount, from_user_id) VALUES (?,?,?)", (referrer_id, REFERRAL_BONUS, user_id))
                    log(referrer_id, "credit", REFERRAL_BONUS, f"referral_from_{user_id}")
                    conn.commit()
                    try: bot.send_message(referrer_id, f"🎉 New referral! +₦{REFERRAL_BONUS}")
                    except: pass
        except: pass

    cart_count = len(get_cart(user_id))
    cart_text = f" | 🛒 {cart_count} items" if cart_count > 0 else ""

    menu = [
        ["💰 Wallet", "➕ Fund Wallet"],
        ["📦 Check Stock", "🧾 My History"],
        ["💳 My Deposits", "🛒 Buy Products"],
        ["🤖 Expert Support", "📝 Report Issue"],
        ["🤝 Refer & Earn", "🛒 My Cart"],
        ["📋 Help & FAQ"]
    ]
    if user_id == ADMIN_ID: menu.append(["👑 Admin Panel"])

    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    for row in menu:
        markup.add(*row)

    bot.reply_to(message, f"🛒 **Store Bot**{cart_text}\n\n📧 Buy uncreated Gmail → Create → Recover IG\n🤝 Earn ₦{REFERRAL_BONUS}/referral!", reply_markup=markup, parse_mode='Markdown')

# ================= ADMIN PANEL =================
@bot.message_handler(func=lambda m: m.text == "👑 Admin Panel" and m.from_user.id == ADMIN_ID)
def admin_panel(message):
    kb = [
        ["📊 Stats", "📥 Pending"],
        ["📝 Reports", "💰 Add Funds"],
        ["💸 Deduct Funds", "📈 Sales"],
        ["📦 Restock", "📢 Broadcast"],
        ["💬 Message User", "👤 View Balance"],
        ["🚫 Block/Unblock", "🗑 Clear Stock"],
        ["📤 Extract Stock", "🔄 User Menu"]
    ]
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    for row in kb:
        markup.add(*row)
    bot.reply_to(message, "👑 **ADMIN PANEL**", reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "🔄 User Menu" and m.from_user.id == ADMIN_ID)
def switch_to_user_menu(message):
    menu = [["💰 Wallet", "➕ Fund Wallet"], ["📦 Check Stock", "🧾 My History"], ["💳 My Deposits", "🛒 Buy Products"], ["🤖 Expert Support", "📝 Report Issue"], ["🤝 Refer & Earn", "🛒 My Cart"], ["📋 Help & FAQ"], ["👑 Admin Panel"]]
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    for row in menu:
        markup.add(*row)
    bot.reply_to(message, "🔄 Switched to User Menu", reply_markup=markup)

# ================= VIEW USER BALANCE (ADMIN) =================
@bot.message_handler(func=lambda m: m.text == "👤 View Balance" and m.from_user.id == ADMIN_ID)
def view_balance_start(message):
    user_data[message.from_user.id] = {"awaiting_view_balance": True}
    bot.reply_to(message, "👤 **VIEW USER BALANCE**\n\nEnter the USER ID:\n/cancel to abort", parse_mode='Markdown')

# ================= BLOCK/UNBLOCK =================
@bot.message_handler(func=lambda m: m.text == "🚫 Block/Unblock" and m.from_user.id == ADMIN_ID)
def block_unblock_menu(message):
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("🚫 Block User", callback_data="block_menu"))
    kb.row(InlineKeyboardButton("✅ Unblock User", callback_data="unblock_menu"))
    kb.row(InlineKeyboardButton("📋 View Blocked", callback_data="blocked_list"))
    bot.reply_to(message, "🚫 **BLOCK/UNBLOCK**", reply_markup=kb, parse_mode='Markdown')

# ================= WALLET / FUND =================
@bot.message_handler(func=lambda m: m.text == "💰 Wallet")
def wallet(message):
    bot.reply_to(message, f"💰 Balance: ₦{get_balance(message.from_user.id)}")

@bot.message_handler(func=lambda m: m.text == "➕ Fund Wallet")
def fund(message):
    ref = generate_ref()
    user_data[message.from_user.id] = {"fund_ref": ref, "awaiting_name": True}
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("✅ I've Made Payment", callback_data=f"pay:{ref}"))
    bot.reply_to(message, f"💳 **FUND YOUR WALLET**\n\n🏦 {BANK_NAME}\n🔢 {ACCOUNT_NUMBER}\n👤 {ACCOUNT_NAME}\n\n🆔 {ref}\n\n📝 Send SENDER NAME first.", reply_markup=kb, parse_mode='Markdown')

# ================= STOCK / HISTORY / DEPOSITS =================
@bot.message_handler(func=lambda m: m.text == "📦 Check Stock")
def user_stock(message):
    msg = "📦 **STOCK**\n\n"
    stock = get_all_stock()
    for name in PRODUCTS:
        msg += f"{'✅' if stock[name] > 0 else '❌'} {name}: {stock[name]} available\n"
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "🧾 My History")
def history(message):
    uid = message.from_user.id
    cursor.execute("SELECT type,amount,details FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
    rows = cursor.fetchall()
    if not rows:
        bot.reply_to(message, "📭 No transactions yet")
        return
    msg = "🧾 **YOUR HISTORY**\n\n"
    for t, a, d in rows:
        msg += f"{'➕' if t=='credit' else '➖'} ₦{a} - {d}\n"
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "💳 My Deposits")
def my_deposits(message):
    uid = message.from_user.id
    cursor.execute("SELECT ref, amount, status, decline_reason FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid,))
    rows = cursor.fetchall()
    if not rows:
        bot.reply_to(message, "📭 No deposits yet")
        return
    msg = "💳 **YOUR DEPOSITS**\n\n"
    for r, a, s, dr in rows:
        emoji = "✅" if s=="approved" else "⏳" if s=="pending" else "❌"
        msg += f"{emoji} {r}: {'₦'+str(a) if a else '...'} ({s})\n"
        if dr: msg += f"   📋 {dr}\n"
    bot.reply_to(message, msg, parse_mode='Markdown')

# ================= BUY PRODUCTS (BUY ONE AT A TIME) =================
@bot.message_handler(func=lambda m: m.text == "🛒 Buy Products")
def buy_products_menu(message):
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("📧 Small (0-100)", callback_data="cat_small"))
    kb.row(InlineKeyboardButton("📧 Medium (200-500)", callback_data="cat_medium"))
    kb.row(InlineKeyboardButton("📧 Large (600-1000)", callback_data="cat_large"))
    kb.row(InlineKeyboardButton("📦 All", callback_data="cat_all"))
    bot.reply_to(message, "🛒 **BUY PRODUCTS**\n\nSelect category to buy instantly or use Cart for bulk.", reply_markup=kb, parse_mode='Markdown')

# ================= CART =================
@bot.message_handler(func=lambda m: m.text == "🛒 My Cart")
def view_cart(message):
    u = message.from_user
    items = get_cart(u.id)
    if not items:
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("🛒 Browse Products", callback_data="cat_all"))
        bot.reply_to(message, "🛒 Cart empty!", reply_markup=kb)
        return
    total = get_cart_total(u.id)
    bal = get_balance(u.id)
    msg = f"🛒 **YOUR CART**\n\n"
    kb = InlineKeyboardMarkup()
    for item in items:
        cart_id, pn, pr, qty = item
        msg += f"📦 {pn}\n   Qty: {qty} × ₦{pr} = ₦{pr*qty}\n\n"
        kb.row(
            InlineKeyboardButton(f"➕ Add more", callback_data=f"qtyadd_{cart_id}"),
            InlineKeyboardButton(f"➖ Remove one", callback_data=f"qtysub_{cart_id}"),
            InlineKeyboardButton(f"❌ Remove all", callback_data=f"rmcart_{cart_id}")
        )
    msg += f"━━━━━━━━━━━━━━━\n💰 **Total: ₦{total}**\n💳 Balance: ₦{bal}\n"
    if total > 0:
        if bal >= total:
            msg += f"\n✅ You have enough funds!"
            kb.row(InlineKeyboardButton("✅ CHECKOUT NOW", callback_data="checkout"))
        else:
            msg += f"\n⚠️ Insufficient! Need ₦{total - bal} more."
    kb.row(InlineKeyboardButton("🗑 Clear Cart", callback_data="clearcart"))
    kb.row(InlineKeyboardButton("🛒 Continue Shopping", callback_data="cat_all"))
    bot.reply_to(message, msg, reply_markup=kb, parse_mode='Markdown')

# ================= SUPPORT / REPORT / FAQ / REFER =================
@bot.message_handler(func=lambda m: m.text == "🤖 Expert Support")
def expert_support(message):
    user_support_mode[message.from_user.id] = True
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("❌ Exit Support")
    bot.reply_to(message, "🤖 **SUPPORT**\n\nAsk me anything!\nType 'exit' to leave.", reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "❌ Exit Support")
def exit_support(message):
    user_support_mode.pop(message.from_user.id, None)
    start(message)

@bot.message_handler(func=lambda m: m.text == "📝 Report Issue")
def report_issue(message):
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("📧 Gmail Taken", callback_data="report_taken"))
    kb.row(InlineKeyboardButton("📷 IG Not Linked", callback_data="report_notlinked"))
    kb.row(InlineKeyboardButton("💳 Payment", callback_data="report_payment"))
    kb.row(InlineKeyboardButton("❓ Other", callback_data="report_other"))
    bot.reply_to(message, "📝 **FILE A REPORT**\n\nSelect type:", reply_markup=kb, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📋 Help & FAQ")
def help_faq(message):
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("📋 How It Works", callback_data="faq_how"))
    kb.row(InlineKeyboardButton("💳 How to Fund", callback_data="faq_fund"))
    kb.row(InlineKeyboardButton("🛒 How to Buy", callback_data="faq_buy"))
    kb.row(InlineKeyboardButton("🛒 Using Cart", callback_data="faq_cart"))
    kb.row(InlineKeyboardButton("🔄 Replacements", callback_data="faq_replace"))
    bot.reply_to(message, "📋 **HELP & FAQ**", reply_markup=kb, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "🤝 Refer & Earn")
def refer_earn_menu(message):
    bot.reply_to(message, f"🤝 **REFER & EARN ₦{REFERRAL_BONUS}**\n\n🔗 `{generate_referral_link(message.from_user.id)}`", parse_mode='Markdown')

# ================= CLEAR / EXTRACT / RESTOCK / BROADCAST / MESSAGE / ADD / DEDUCT / STATS =================
@bot.message_handler(func=lambda m: m.text == "🗑 Clear Stock" and m.from_user.id == ADMIN_ID)
def clear_stock_menu(message):
    stock = get_all_stock()
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("🗑 CLEAR ALL", callback_data="clearstock_all"))
    for name, count in stock.items():
        if count > 0:
            kb.row(InlineKeyboardButton(f"🗑 {name} ({count})", callback_data=f"clearstock_{name}"))
    kb.row(InlineKeyboardButton("❌ Cancel", callback_data="clearstock_cancel"))
    bot.reply_to(message, "🗑 **CLEAR STOCK**", reply_markup=kb, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📤 Extract Stock" and m.from_user.id == ADMIN_ID)
def extract_stock_menu(message):
    stock = get_all_stock()
    kb = InlineKeyboardMarkup()
    for name, count in stock.items():
        if count > 0:
            kb.row(InlineKeyboardButton(f"📤 {name} ({count})", callback_data=f"extract_{name}"))
    kb.row(InlineKeyboardButton("📤 ALL", callback_data="extract_all"))
    bot.reply_to(message, "📤 **EXTRACT STOCK**", reply_markup=kb, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📦 Restock" and m.from_user.id == ADMIN_ID)
def restock_menu(message):
    kb = InlineKeyboardMarkup()
    stock = get_all_stock()
    for n in PRODUCTS:
        kb.row(InlineKeyboardButton(f"{n} - {stock[n]}", callback_data=f"restock_{n}"))
    kb.row(InlineKeyboardButton("🔙 Back", callback_data="back_to_admin"))
    bot.reply_to(message, "📦 **RESTOCK**", reply_markup=kb, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📢 Broadcast" and m.from_user.id == ADMIN_ID)
def broadcast_menu(message):
    user_data[message.from_user.id] = {"awaiting_broadcast": True}
    bot.reply_to(message, "📢 **BROADCAST**\n\nSend your message now. It will be sent to ALL users automatically.\n/cancel to abort", parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "💬 Message User" and m.from_user.id == ADMIN_ID)
def message_user_start(message):
    user_data[message.from_user.id] = {"awaiting_msg_user": True}
    bot.reply_to(message, "💬 **MESSAGE USER**\n\nEnter the USER ID:\n/cancel to abort", parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "💰 Add Funds" and m.from_user.id == ADMIN_ID)
def admin_addfund_start(message):
    user_data[message.from_user.id] = {"awaiting_addfund_user": True}
    bot.reply_to(message, "💰 **ADD FUNDS**\n\nEnter the USER ID:\n/cancel to abort", parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "💸 Deduct Funds" and m.from_user.id == ADMIN_ID)
def admin_deductfund_start(message):
    user_data[message.from_user.id] = {"awaiting_deduct_user": True}
    bot.reply_to(message, "💸 **DEDUCT FUNDS**\n\nEnter the USER ID:\n/cancel to abort", parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📊 Stats" and m.from_user.id == ADMIN_ID)
def stats(message):
    cursor.execute("SELECT COUNT(*) FROM users")
    u = cursor.fetchone()[0]
    bot.reply_to(message, f"📊 Users: {u}\n📦 Orders: {get_stat('orders')}\n💰 Revenue: ₦{get_stat('revenue')}")

@bot.message_handler(func=lambda m: m.text == "📥 Pending" and m.from_user.id == ADMIN_ID)
def pending_deposits(message):
    if not pending_approvals:
        bot.reply_to(message, "✅ No pending")
        return
    for uid, data in pending_approvals.items():
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("✅ Approve", callback_data=f"approve:{uid}"))
        kb.row(InlineKeyboardButton("❌ Reject", callback_data=f"reject:{uid}"))
        try:
            bot.send_photo(ADMIN_ID, data["photo_id"], caption=f"💳 {uid}\n👤 {data.get('full_name','?')}\n🏦 {data['sender_name']}\n🔢 {data['ref']}", reply_markup=kb)
        except: pass

@bot.message_handler(func=lambda m: m.text == "📝 Reports" and m.from_user.id == ADMIN_ID)
def view_reports(message):
    cursor.execute("SELECT id, user_id, issue_type, description FROM reports WHERE status='open' ORDER BY id DESC LIMIT 10")
    rows = cursor.fetchall()
    if not rows:
        bot.reply_to(message, "✅ No reports")
        return
    for rid, uid, it, desc in rows:
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("✅ Resolve", callback_data=f"resolve_{rid}"))
        kb.row(InlineKeyboardButton("💬 Reply", callback_data=f"reply_{rid}"))
        kb.row(InlineKeyboardButton("💰 Add", callback_data=f"addfund_{uid}"))
        bot.send_message(message.chat.id, f"📝 #{rid} | 👤 {uid} | 🏷 {it}\n📄 {desc[:200]}", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "📈 Sales" and m.from_user.id == ADMIN_ID)
def sales_menu(message):
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM sales_log WHERE sale_date=date('now')")
    td = cursor.fetchone()
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM sales_log WHERE sale_date>=date('now','-7 days')")
    wk = cursor.fetchone()
    bot.reply_to(message, f"📈 **SALES**\n\n📆 Today: {td[0]} orders, ₦{td[1]}\n📅 Week: {wk[0]} orders, ₦{wk[1]}\n💰 All: ₦{get_stat('revenue')}", parse_mode='Markdown')

# ================= CANCEL =================
@bot.message_handler(commands=['cancel'])
def cancel(message):
    user_data.pop(message.from_user.id, None)
    bot.reply_to(message, "❌ All operations cancelled")

# ================= TEXT HANDLER =================
@bot.message_handler(func=lambda m: True)
def handle_text(message):
    u = message.from_user
    t = message.text
    
    if user_support_mode.get(u.id):
        if t == "exit" or t == "❌ Exit Support":
            user_support_mode.pop(u.id, None)
            start(message)
            return
        # Support handler
        msg_lower = t.lower()
        if "how" in msg_lower or "work" in msg_lower:
            r = "📋 Buy uncreated Gmail → Create it → Instagram 'Forgot Password' → Reset → Own both!"
        elif "cart" in msg_lower:
            r = "🛒 Use '➕ Cart' to add items → View Cart to manage → Checkout all at once!"
        elif "create" in msg_lower or "gmail" in msg_lower:
            r = "🔧 Gmail.com → Create Account → Enter our address → Create password → Done!"
        elif "price" in msg_lower or "cost" in msg_lower:
            r = "💰 ₦1000-₦8500. Click '📦 Check Stock'."
        elif "pay" in msg_lower or "fund" in msg_lower:
            r = f"💳 Click '➕ Fund Wallet' → Transfer to {BANK_NAME} ({ACCOUNT_NUMBER}) → Send name → Upload screenshot."
        else:
            r = "🤖 Ask me anything!"
        bot.reply_to(message, r)
        return
    
    # Report description
    if user_data.get(u.id, {}).get("awaiting_report"):
        current = user_data.get(u.id, {}).get("report_desc", "")
        user_data[u.id]["report_desc"] = (current + " " + t).strip()
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("📝 SUBMIT REPORT", callback_data="report_submit"))
        bot.reply_to(message, "✅ Text added! Send more or click Submit.", reply_markup=kb)
        return
    
    # Admin modes
    if u.id == ADMIN_ID:
        # View balance
        if user_data.get(u.id, {}).get("awaiting_view_balance"):
            if t == "/cancel":
                user_data.pop(u.id, None)
                bot.reply_to(message, "❌ Cancelled")
                return
            try:
                uid = int(t)
                bal = get_balance(uid)
                try:
                    target = bot.get_chat(uid)
                    name = f"{target.full_name} (@{target.username})" if target.username else target.full_name
                except:
                    name = f"User {uid}"
                bot.reply_to(message, f"👤 **{name}**\n🆔 ID: {uid}\n💰 Balance: ₦{bal}", parse_mode='Markdown')
                user_data.pop(u.id, None)
                return
            except:
                bot.reply_to(message, "❌ Invalid ID")
                return
        
        # Block/Unblock
        if user_data.get(u.id, {}).get("awaiting_block_user"):
            if t == "/cancel":
                user_data.pop(u.id, None)
                bot.reply_to(message, "❌ Cancelled")
                return
            try:
                uid = int(t)
                if uid in blocked_users:
                    bot.reply_to(message, f"ℹ️ Already blocked.")
                    user_data.pop(u.id, None)
                    return
                blocked_users.add(uid)
                bot.reply_to(message, f"🚫 User {uid} BLOCKED!")
                try: bot.send_message(uid, "🚫 You have been blocked from submitting payment proofs.")
                except: pass
                user_data.pop(u.id, None)
                return
            except:
                bot.reply_to(message, "❌ Invalid ID")
                return
        
        if user_data.get(u.id, {}).get("awaiting_unblock_user"):
            if t == "/cancel":
                user_data.pop(u.id, None)
                bot.reply_to(message, "❌ Cancelled")
                return
            try:
                uid = int(t)
                if uid not in blocked_users:
                    bot.reply_to(message, f"ℹ️ Not blocked.")
                    user_data.pop(u.id, None)
                    return
                blocked_users.discard(uid)
                if uid in fraud_tracker: fraud_tracker[uid] = {"last": 0, "count": 0}
                bot.reply_to(message, f"✅ User {uid} UNBLOCKED!")
                try: bot.send_message(uid, "✅ You have been unblocked!")
                except: pass
                user_data.pop(u.id, None)
                return
            except:
                bot.reply_to(message, "❌ Invalid ID")
                return
        
        # Broadcast
        if user_data.get(u.id, {}).get("awaiting_broadcast"):
            if t == "/cancel":
                user_data.pop(u.id, None)
                bot.reply_to(message, "❌ Cancelled")
                return
            cursor.execute("SELECT user_id FROM users")
            users = cursor.fetchall()
            if not users:
                bot.reply_to(message, "❌ No users!")
                user_data.pop(u.id, None)
                return
            sent = 0
            failed = 0
            status_msg = bot.reply_to(message, f"📢 Broadcasting to {len(users)} users...")
            for (uid,) in users:
                try:
                    bot.send_message(uid, f"📢 {t}")
                    sent += 1
                except:
                    failed += 1
                time.sleep(0.05)
            cursor.execute("INSERT INTO broadcast_logs (admin_id, message, total_sent, total_failed) VALUES (?,?,?,?)", (u.id, t[:500], sent, failed))
            conn.commit()
            bot.edit_message_text(f"✅ Done!\n✅ Sent: {sent}\n❌ Failed: {failed}", status_msg.chat.id, status_msg.message_id)
            user_data.pop(u.id, None)
            return
        
        # Message User
        if user_data.get(u.id, {}).get("awaiting_msg_user"):
            if t == "/cancel":
                user_data.pop(u.id, None)
                bot.reply_to(message, "❌ Cancelled")
                return
            try:
                tid = int(t)
                user_data[u.id]["msg_target"] = tid
                user_data[u.id]["awaiting_msg_user"] = False
                user_data[u.id]["awaiting_msg_text"] = True
                bot.reply_to(message, f"👤 User: {tid}\n\nSend your message:\n/cancel to abort")
                return
            except:
                bot.reply_to(message, "❌ Invalid ID")
                return
        
        if user_data.get(u.id, {}).get("awaiting_msg_text"):
            if t == "/cancel":
                user_data.pop(u.id, None)
                bot.reply_to(message, "❌ Cancelled")
                return
            tid = user_data[u.id].get("msg_target")
            user_data.pop(u.id, None)
            try:
                bot.send_message(tid, f"📬 **Message from Admin:**\n\n{t}", parse_mode='Markdown')
                bot.reply_to(message, f"✅ Sent to {tid}!")
            except:
                bot.reply_to(message, f"❌ Failed to send to {tid}")
            return
        
        # Add Funds
        if user_data.get(u.id, {}).get("awaiting_addfund_user"):
            if t == "/cancel":
                user_data.pop(u.id, None)
                bot.reply_to(message, "❌ Cancelled")
                return
            try:
                tid = int(t)
                user_data[u.id]["addfund_target"] = tid
                user_data[u.id]["awaiting_addfund_user"] = False
                user_data[u.id]["awaiting_addfund_amount"] = True
                bot.reply_to(message, f"👤 User: {tid}\n💳 Balance: ₦{get_balance(tid)}\n\nEnter AMOUNT to add:\n/cancel to abort")
                return
            except:
                bot.reply_to(message, "❌ Invalid ID")
                return
        
        if user_data.get(u.id, {}).get("awaiting_addfund_amount"):
            if t == "/cancel":
                user_data.pop(u.id, None)
                bot.reply_to(message, "❌ Cancelled")
                return
            try:
                amt = int(t)
            except:
                bot.reply_to(message, "❌ Send valid number")
                return
            if amt <= 0:
                bot.reply_to(message, "❌ Positive amount")
                return
            tid = user_data[u.id].get("addfund_target")
            old_bal = get_balance(tid)
            add_user(tid)
            cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, tid))
            conn.commit()
            log(tid, "credit", amt, "admin_addfund")
            try: bot.send_message(tid, f"💰 Admin added ₦{amt}!\n💳 Balance: ₦{old_bal} → ₦{get_balance(tid)}")
            except: pass
            bot.reply_to(message, f"✅ Added ₦{amt} to user {tid}")
            user_data.pop(u.id, None)
            return
        
        # Deduct Funds
        if user_data.get(u.id, {}).get("awaiting_deduct_user"):
            if t == "/cancel":
                user_data.pop(u.id, None)
                bot.reply_to(message, "❌ Cancelled")
                return
            try:
                tid = int(t)
                bal = get_balance(tid)
                user_data[u.id]["deduct_target"] = tid
                user_data[u.id]["awaiting_deduct_user"] = False
                user_data[u.id]["awaiting_deduct_amount"] = True
                bot.reply_to(message, f"👤 User: {tid}\n💳 Balance: ₦{bal}\n\nEnter AMOUNT to deduct (max ₦{bal}):\n/cancel to abort")
                return
            except:
                bot.reply_to(message, "❌ Invalid ID")
                return
        
        if user_data.get(u.id, {}).get("awaiting_deduct_amount"):
            if t == "/cancel":
                user_data.pop(u.id, None)
                bot.reply_to(message, "❌ Cancelled")
                return
            try:
                amt = int(t)
            except:
                bot.reply_to(message, "❌ Send valid number")
                return
            if amt <= 0:
                bot.reply_to(message, "❌ Positive amount")
                return
            tid = user_data[u.id].get("deduct_target")
            old_bal = get_balance(tid)
            if old_bal < amt:
                bot.reply_to(message, f"⚠️ User only has ₦{old_bal}")
                return
            cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, tid))
            conn.commit()
            log(tid, "debit", amt, "admin_deduct")
            try: bot.send_message(tid, f"⚠️ ₦{amt} deducted\n💳 Balance: ₦{old_bal} → ₦{get_balance(tid)}")
            except: pass
            bot.reply_to(message, f"✅ Deducted ₦{amt} from user {tid}")
            user_data.pop(u.id, None)
            return
        
        # Decline reason
        if "declining_user" in user_data.get(u.id, {}):
            if t == "/cancel":
                user_data.pop(u.id, None)
                bot.reply_to(message, "❌ Cancelled")
                return
            uid = user_data[u.id].get("declining_user")
            if uid in pending_approvals:
                info = pending_approvals[uid]
                cursor.execute("UPDATE deposits SET status='rejected', decline_reason=? WHERE ref=?", (t, info.get('ref')))
                conn.commit()
                try: bot.send_message(uid, f"❌ **PAYMENT DECLINED**\n\n📋 Reason: {t}\n\nFix and try again.", parse_mode='Markdown')
                except: pass
                bot.reply_to(message, f"✅ Declined user {uid}\n📋 {t}")
                pending_approvals.pop(uid, None)
            user_data.pop(u.id, None)
            return
        
        # Reply to report
        if "replying_to" in user_data.get(u.id, {}):
            if t == "/cancel":
                user_data.pop(u.id, None)
                bot.reply_to(message, "❌ Cancelled")
                return
            rid = user_data[u.id].get("replying_to")
            cursor.execute("SELECT user_id FROM reports WHERE id=?", (rid,))
            row = cursor.fetchone()
            if row:
                try: bot.send_message(row[0], f"📬 **Admin Response (#{rid})**\n\n{t}", parse_mode='Markdown')
                except: pass
                cursor.execute("UPDATE reports SET admin_response=? WHERE id=?", (t, rid))
                conn.commit()
                bot.reply_to(message, "✅ Reply sent!")
            user_data.pop(u.id, None)
            return
        
        # Approve payment amount
        if "approving_user" in user_data.get(u.id, {}):
            try:
                amt = int(t)
            except:
                bot.reply_to(message, "❌ Send valid number")
                return
            if amt <= 0:
                bot.reply_to(message, "❌ Positive amount")
                return
            tid = user_data[u.id].get("approving_user")
            if tid not in pending_approvals:
                bot.reply_to(message, "⚠️ Already processed!")
                user_data.pop(u.id, None)
                return
            info = pending_approvals[tid]
            old_bal = get_balance(tid)
            cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, tid))
            conn.commit()
            cursor.execute("UPDATE deposits SET amount=?, status='approved' WHERE ref=?", (amt, info.get('ref')))
            conn.commit()
            new_bal = get_balance(tid)
            log(tid, "credit", amt, "deposit")
            try: bot.send_message(tid, f"✅ **PAYMENT APPROVED!**\n\n💰 Amount: ₦{amt}\n💳 Previous Balance: ₦{old_bal}\n💳 New Balance: ₦{new_bal}\n\nThank you! You can now purchase products.", parse_mode='Markdown')
            except: pass
            bot.reply_to(message, f"✅ Approved ₦{amt} for user {tid}\n👤 {info.get('full_name','?')}\n💳 Previous: ₦{old_bal}\n💳 New: ₦{new_bal}")
            pending_approvals.pop(tid, None)
            user_data.pop(u.id, None)
            return
    
    # Funding flow - sender name
    if user_data.get(u.id, {}).get("awaiting_name"):
        user_data[u.id]["sender_name"] = t
        user_data[u.id]["awaiting_name"] = False
        user_data[u.id]["awaiting_proof"] = True
        bot.reply_to(message, "📸 Now send SCREENSHOT of your payment.")
        return

# ================= PHOTO HANDLER =================
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    u = message.from_user
    if not user_data.get(u.id, {}).get("awaiting_proof"):
        return
    if u.id in blocked_users:
        bot.reply_to(message, "❌ Blocked")
        return
    now = time.time()
    if u.id not in fraud_tracker:
        fraud_tracker[u.id] = {"last": 0, "count": 0}
    d = fraud_tracker[u.id]
    if now - d["last"] < 60:
        bot.reply_to(message, "⏳ Wait 60s")
        return
    d["last"] = now
    d["count"] += 1
    if d["count"] >= 5:
        blocked_users.add(u.id)
        bot.reply_to(message, "❌ Blocked")
        return
    sn = user_data[u.id].get("sender_name", "Unknown")
    ref = user_data[u.id].get("fund_ref", generate_ref())
    try:
        cursor.execute("INSERT INTO deposits (user_id, sender_name, ref, status) VALUES (?,?,?,?)", (u.id, sn, ref, "pending"))
        conn.commit()
        pending_approvals[u.id] = {"sender_name": sn, "photo_id": message.photo[-1].file_id, "ref": ref, "username": u.username, "full_name": u.full_name}
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("✅ Approve", callback_data=f"approve:{u.id}"))
        kb.row(InlineKeyboardButton("❌ Reject", callback_data=f"reject:{u.id}"))
        bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"💳 **NEW DEPOSIT**\n\n👤 {u.full_name}\n📛 @{u.username or 'N/A'}\n🆔 {u.id}\n🏦 {sn}\n🔢 {ref}", reply_markup=kb, parse_mode='Markdown')
        bot.reply_to(message, "✅ Submitted!")
        user_data[u.id]["awaiting_proof"] = False
    except:
        user_data[u.id]["awaiting_proof"] = False

# ================= DOCUMENT HANDLER =================
@bot.message_handler(content_types=['document'])
def handle_document(message):
    if message.from_user.id == ADMIN_ID and user_data.get(ADMIN_ID, {}).get("awaiting_restock_file"):
        pn = user_data.get(ADMIN_ID, {}).get("restock_product")
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            content = downloaded_file.decode('utf-8', errors='ignore')
            new_emails = [l.strip() for l in content.split('\n') if l.strip() and '@' in l]
            if not new_emails:
                bot.reply_to(message, "❌ No emails")
                return
            old = get_stock_count(pn)
            added = add_bulk_to_stock(pn, new_emails)
            bot.reply_to(message, f"✅ Restocked!\n📦 {pn}\n📊 {old}→{get_stock_count(pn)} (+{added})")
        except Exception as e:
            bot.reply_to(message, f"❌ {e}")
        user_data[ADMIN_ID]["awaiting_restock_file"] = False

# ================= CALLBACK HANDLER =================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    d = call.data
    u = call.from_user
    
    if d.startswith("pay:"):
        ref = d.split(":")[1]
        user_data[u.id] = {"payment_ref": ref, "awaiting_name": True}
        bot.answer_callback_query(call.id)
        bot.edit_message_text(f"💳 REF: {ref}\n\n📝 Send SENDER NAME.", call.message.chat.id, call.message.message_id)
        return
    
    # Product category
    if d.startswith("cat_"):
        bot.answer_callback_query(call.id)
        cat = d.replace("cat_", "")
        if cat == "small":
            p = {k: v for k, v in PRODUCTS.items() if v <= 3000}
            t = "SMALL"
        elif cat == "medium":
            p = {k: v for k, v in PRODUCTS.items() if 4000 <= v <= 6000}
            t = "MEDIUM"
        elif cat == "large":
            p = {k: v for k, v in PRODUCTS.items() if v >= 6500}
            t = "LARGE"
        else:
            p = PRODUCTS
            t = "ALL"
        msg = f"**{t}**\n\n🛒 Click to BUY NOW | 🛒➕ Click to ADD TO CART\n\n"
        kb = InlineKeyboardMarkup()
        for n, pr in p.items():
            s = get_stock_count(n)
            msg += f"{'✅' if s>0 else '❌'} {n}: {s} available - ₦{pr}\n"
            if s > 0:
                kb.row(InlineKeyboardButton(f"🛒 BUY {n}", callback_data=f"buy_{n}"), InlineKeyboardButton(f"➕ Cart", callback_data=f"addcart_{n}"))
        kb.row(InlineKeyboardButton("🔙 Back to Categories", callback_data="back_to_categories"))
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode='Markdown')
        return
    
    if d == "back_to_categories":
        bot.answer_callback_query(call.id)
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("📧 Small", callback_data="cat_small"))
        kb.row(InlineKeyboardButton("📧 Medium", callback_data="cat_medium"))
        kb.row(InlineKeyboardButton("📧 Large", callback_data="cat_large"))
        kb.row(InlineKeyboardButton("📦 All", callback_data="cat_all"))
        bot.edit_message_text("🛒 **BUY PRODUCTS**", call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode='Markdown')
        return
    
    # Buy product
    if d.startswith("buy_"):
        bot.answer_callback_query(call.id)
        pn = d.replace("buy_", "")
        if pn not in PRODUCTS:
            return
        pr = PRODUCTS[pn]
        if get_stock_count(pn) == 0:
            bot.answer_callback_query(call.id, "❌ Out of stock!", show_alert=True)
            return
        bal = get_balance(u.id)
        if bal < pr:
            bot.answer_callback_query(call.id, f"❌ Insufficient funds! Need ₦{pr}, you have ₦{bal}", show_alert=True)
            return
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("✅ Confirm Purchase", callback_data=f"confirm_{pn}"))
        kb.row(InlineKeyboardButton("❌ Cancel", callback_data="back_to_categories"))
        bot.edit_message_text(f"🛒 **CONFIRM**\n\n📦 {pn}\n💰 Price: ₦{pr}\n💳 Balance: ₦{bal}\n💳 After: ₦{bal-pr}", call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode='Markdown')
        return
    
    # Confirm purchase
    if d.startswith("confirm_"):
        bot.answer_callback_query(call.id)
        pn = d.replace("confirm_", "")
        if pn not in PRODUCTS:
            return
        pr = PRODUCTS[pn]
        if get_balance(u.id) < pr:
            bot.answer_callback_query(call.id, "❌ Insufficient!", show_alert=True)
            return
        item = get_item_from_stock(pn)
        if not item:
            bot.answer_callback_query(call.id, "❌ Out of stock!", show_alert=True)
            return
        item_id, email = item
        mark_item_sold(item_id)
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (pr, u.id))
        conn.commit()
        update_stat("revenue", pr)
        update_stat("orders", 1)
        log(u.id, "purchase", pr, pn)
        bot.edit_message_text(f"✅ **PURCHASED!**\n\n📦 {pn}\n💰 ₦{pr}\n📧 `{email}`\n\n💳 Balance: ₦{get_balance(u.id)}", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        return
    
    # Cart operations
    if d.startswith("addcart_"):
        bot.answer_callback_query(call.id)
        pn = d.replace("addcart_", "")
        if pn not in PRODUCTS:
            return
        pr = PRODUCTS[pn]
        if get_stock_count(pn) == 0:
            bot.answer_callback_query(call.id, "❌ Out of stock!", show_alert=True)
            return
        add_to_cart(u.id, pn, pr)
        cart_count = len(get_cart(u.id))
        cart_total = get_cart_total(u.id)
        bot.answer_callback_query(call.id, f"✅ Added! 🛒 {cart_count} items | ₦{cart_total}", show_alert=True)
        return
    
    if d.startswith("rmcart_"):
        bot.answer_callback_query(call.id)
        remove_from_cart(u.id, int(d.replace("rmcart_", "")))
        # Refresh cart view
        view_cart(call.message)
        return
    
    if d.startswith("qtyadd_"):
        bot.answer_callback_query(call.id)
        cursor.execute("UPDATE cart SET quantity=quantity+1 WHERE id=? AND user_id=?", (int(d.replace("qtyadd_", "")), u.id))
        conn.commit()
        view_cart(call.message)
        return
    
    if d.startswith("qtysub_"):
        bot.answer_callback_query(call.id)
        cid = int(d.replace("qtysub_", ""))
        cursor.execute("SELECT quantity FROM cart WHERE id=? AND user_id=?", (cid, u.id))
        row = cursor.fetchone()
        if row and row[0] > 1:
            cursor.execute("UPDATE cart SET quantity=quantity-1 WHERE id=?", (cid,))
            conn.commit()
        else:
            remove_from_cart(u.id, cid)
        view_cart(call.message)
        return
    
    if d == "clearcart":
        bot.answer_callback_query(call.id)
        clear_cart(u.id)
        bot.edit_message_text("🛒 Cart cleared!", call.message.chat.id, call.message.message_id)
        return
    
    if d == "checkout":
        bot.answer_callback_query(call.id)
        items = get_cart(u.id)
        if not items:
            bot.answer_callback_query(call.id, "Cart empty!", show_alert=True)
            return
        total = get_cart_total(u.id)
        if get_balance(u.id) < total:
            bot.answer_callback_query(call.id, f"❌ Need ₦{total}!", show_alert=True)
            return
        for item in items:
            if get_stock_count(item[1]) < item[3]:
                bot.edit_message_text(f"❌ Not enough stock for {item[1]}!", call.message.chat.id, call.message.message_id)
                return
        delivered = []
        total_spent = 0
        for item in items:
            for stock_item in get_items_from_stock(item[1], item[3]):
                mark_item_sold(stock_item[0])
                delivered.append(f"📦 {item[1]}: {stock_item[1]}")
                total_spent += item[2]
                update_stat("revenue", item[2])
                update_stat("orders", 1)
                log(u.id, "purchase", item[2], item[1])
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (total_spent, u.id))
        conn.commit()
        clear_cart(u.id)
        bot.edit_message_text("✅ **ORDER COMPLETE!**\n\n" + "\n".join(delivered) + f"\n\n💰 Total: ₦{total_spent}\n💳 Remaining: ₦{get_balance(u.id)}", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        return
    
    # Block/Unblock menu
    if d in ["block_menu", "unblock_menu", "blocked_list"]:
        bot.answer_callback_query(call.id)
        if d == "block_menu":
            user_data[u.id] = {"awaiting_block_user": True}
            bot.edit_message_text("🚫 Enter User ID to block:\n/cancel", call.message.chat.id, call.message.message_id)
        elif d == "unblock_menu":
            user_data[u.id] = {"awaiting_unblock_user": True}
            bot.edit_message_text("✅ Enter User ID to unblock:\n/cancel", call.message.chat.id, call.message.message_id)
        elif d == "blocked_list":
            if not blocked_users:
                bot.edit_message_text("✅ No blocked users!", call.message.chat.id, call.message.message_id)
            else:
                msg = "🚫 **BLOCKED**\n\n"
                for uid in blocked_users:
                    msg += f"🆔 {uid}\n"
                bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        return
    
    # Clear stock
    if d.startswith("clearstock_"):
        bot.answer_callback_query(call.id)
        if u.id != ADMIN_ID: return
        if d == "clearstock_all":
            clear_all_stock()
            bot.edit_message_text("✅ All stock deleted!", call.message.chat.id, call.message.message_id)
        elif d == "clearstock_cancel":
            bot.edit_message_text("❌ Cancelled.", call.message.chat.id, call.message.message_id)
        elif d.startswith("clearstock_"):
            pn = d.replace("clearstock_", "")
            if pn in PRODUCTS:
                count = get_stock_count(pn)
                clear_product_stock(pn)
                bot.edit_message_text(f"✅ {pn} cleared! ({count} items)", call.message.chat.id, call.message.message_id)
        return
    
    # Extract stock
    if d.startswith("extract_"):
        bot.answer_callback_query(call.id)
        if u.id != ADMIN_ID: return
        if d == "extract_all":
            all_emails = []
            for name in PRODUCTS:
                all_emails.extend(extract_stock(name))
            if not all_emails:
                bot.edit_message_text("❌ No stock!", call.message.chat.id, call.message.message_id)
                return
            content = "\n".join(all_emails)
            with open("all_stock.txt", "w") as f: f.write(content)
            with open("all_stock.txt", "rb") as f: bot.send_document(ADMIN_ID, f, caption=f"📤 All Stock\n📦 {len(all_emails)} items")
            os.remove("all_stock.txt")
            bot.edit_message_text(f"✅ Exported {len(all_emails)} items!", call.message.chat.id, call.message.message_id)
        elif d.startswith("extract_"):
            pn = d.replace("extract_", "")
            if pn in PRODUCTS:
                emails = extract_stock(pn)
                if not emails:
                    bot.edit_message_text("❌ No stock!", call.message.chat.id, call.message.message_id)
                    return
                content = "\n".join(emails)
                filename = f"{pn.replace(' ','_').replace('(','').replace(')','')}.txt"
                with open(filename, "w") as f: f.write(content)
                with open(filename, "rb") as f: bot.send_document(ADMIN_ID, f, caption=f"📤 {pn}\n📦 {len(emails)} items")
                os.remove(filename)
                bot.edit_message_text(f"✅ Exported {pn}: {len(emails)} items!", call.message.chat.id, call.message.message_id)
        return
    
    # Restock
    if d.startswith("restock_"):
        bot.answer_callback_query(call.id)
        if u.id != ADMIN_ID: return
        if d == "back_to_admin":
            admin_panel(call.message)
            return
        pn = d.replace("restock_", "")
        if pn in PRODUCTS:
            user_data[u.id] = {"awaiting_restock_file": True, "restock_product": pn}
            bot.edit_message_text(f"📦 RESTOCK: {pn}\n\nSend .txt file.\n/cancel", call.message.chat.id, call.message.message_id)
        return
    
    # FAQ
    if d.startswith("faq_"):
        bot.answer_callback_query(call.id)
        faq = d.replace("faq_", "")
        faqs = {
            "how": "📋 Buy uncreated Gmail → Create it → Instagram 'Forgot Password' → Enter Gmail → Reset password → Own both!",
            "fund": f"💳 Transfer to {BANK_NAME} ({ACCOUNT_NUMBER}) - {ACCOUNT_NAME} → Send name → Upload screenshot → Wait approval",
            "buy": "🛒 Fund wallet → Buy Products → Click BUY to purchase instantly → Confirm → Get email!",
            "cart": "🛒 Click ➕ Cart to add items → View Cart to manage → Adjust quantities → Checkout all at once!",
            "replace": "🔄 Replacement if Gmail taken or IG not linked. Report within 1 hour."
        }
        if faq in faqs:
            kb = InlineKeyboardMarkup()
            kb.row(InlineKeyboardButton("🔙 Back", callback_data="back_to_faq"))
            bot.edit_message_text(faqs[faq], call.message.chat.id, call.message.message_id, reply_markup=kb)
        return
    
    if d == "back_to_faq":
        bot.answer_callback_query(call.id)
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("📋 How", callback_data="faq_how"))
        kb.row(InlineKeyboardButton("💳 Fund", callback_data="faq_fund"))
        kb.row(InlineKeyboardButton("🛒 Buy", callback_data="faq_buy"))
        kb.row(InlineKeyboardButton("🛒 Cart", callback_data="faq_cart"))
        kb.row(InlineKeyboardButton("🔄 Replace", callback_data="faq_replace"))
        bot.edit_message_text("📋 **HELP & FAQ**", call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode='Markdown')
        return
    
    # Report
    if d.startswith("report_"):
        bot.answer_callback_query(call.id)
        if d in ["report_submit", "report_cancel"]:
            if d == "report_submit":
                desc = user_data.get(u.id, {}).get("report_desc", "").strip()
                it = user_data.get(u.id, {}).get("report_type", "other")
                if not desc:
                    bot.answer_callback_query(call.id, "Send description first!", show_alert=True)
                    return
                issue_names = {"taken": "📧 Gmail Already Taken", "notlinked": "📷 Instagram Not Linked", "payment": "💳 Payment Issue", "other": "❓ Other Issue"}
                cursor.execute("INSERT INTO reports (user_id, issue_type, description) VALUES (?,?,?)", (u.id, it, desc[:500]))
                conn.commit()
                rid = cursor.lastrowid
                try:
                    kb = InlineKeyboardMarkup()
                    kb.row(InlineKeyboardButton("✅ Resolve", callback_data=f"resolve_{rid}"))
                    kb.row(InlineKeyboardButton("💬 Reply", callback_data=f"reply_{rid}"))
                    kb.row(InlineKeyboardButton("💰 Add Funds", callback_data=f"addfund_{u.id}"))
                    bot.send_message(ADMIN_ID, f"📝 **NEW REPORT #{rid}**\n\n👤 {u.full_name}\n📛 @{u.username or 'N/A'}\n🆔 {u.id}\n🏷 {issue_names.get(it, it)}\n📄 {desc[:800]}", reply_markup=kb, parse_mode='Markdown')
                except: pass
                user_data.pop(u.id, None)
                bot.edit_message_text(f"✅ **Report #{rid} Submitted!**", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
            else:
                user_data.pop(u.id, None)
                bot.edit_message_text("❌ Report cancelled.", call.message.chat.id, call.message.message_id)
        else:
            it = d.replace("report_", "")
            user_data[u.id] = {"report_type": it, "awaiting_report": True, "report_desc": ""}
            prompts = {"taken": "📧 Gmail Already Taken", "notlinked": "📷 Instagram Not Linked", "payment": "💳 Payment Issue", "other": "❓ Other Issue"}
            kb = InlineKeyboardMarkup()
            kb.row(InlineKeyboardButton("📝 SUBMIT REPORT", callback_data="report_submit"))
            kb.row(InlineKeyboardButton("❌ Cancel", callback_data="report_cancel"))
            bot.edit_message_text(f"📝 **{prompts.get(it)}**\n\nSend description then click Submit.", call.message.chat.id, call.message.message_id, reply_markup=kb, parse_mode='Markdown')
        return
    
    # Resolve/Reply to report
    if d.startswith("resolve_"):
        bot.answer_callback_query(call.id)
        if u.id != ADMIN_ID: return
        rid = int(d.replace("resolve_", ""))
        cursor.execute("UPDATE reports SET status='resolved' WHERE id=?", (rid,))
        conn.commit()
        cursor.execute("SELECT user_id FROM reports WHERE id=?", (rid,))
        row = cursor.fetchone()
        if row:
            try: bot.send_message(row[0], f"✅ Your report #{rid} has been resolved!")
            except: pass
        bot.edit_message_text(f"✅ Report #{rid} resolved.", call.message.chat.id, call.message.message_id)
        return
    
    if d.startswith("reply_"):
        bot.answer_callback_query(call.id)
        if u.id != ADMIN_ID: return
        rid = int(d.replace("reply_", ""))
        user_data[u.id] = {"replying_to": rid}
        bot.send_message(ADMIN_ID, "💬 Send your reply:\n/cancel to abort.")
        return
    
    if d.startswith("addfund_"):
        bot.answer_callback_query(call.id)
        if u.id != ADMIN_ID: return
        uid = int(d.replace("addfund_", ""))
        user_data[u.id] = {"approving_user": uid}
        bot.send_message(ADMIN_ID, f"💰 Amount for user {uid}:")
        return
    
    # Approve/Reject deposit
    if d.startswith("approve:"):
        bot.answer_callback_query(call.id)
        if u.id != ADMIN_ID: return
        uid = int(d.replace("approve:", ""))
        if uid not in pending_approvals:
            bot.edit_message_text("⚠️ Already processed!", call.message.chat.id, call.message.message_id)
            return
        user_data[u.id] = {"approving_user": uid}
        bot.send_message(ADMIN_ID, f"💰 **APPROVE**\n\n🆔 {uid}\n\nReply with amount (e.g., 5000):", parse_mode='Markdown')
        return
    
    if d.startswith("reject:"):
        bot.answer_callback_query(call.id)
        if u.id != ADMIN_ID: return
        uid = int(d.replace("reject:", ""))
        if uid not in pending_approvals:
            bot.edit_message_text("❌ No longer pending", call.message.chat.id, call.message.message_id)
            return
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("❌ Fake", callback_data=f"decline:{uid}:fake"))
        kb.row(InlineKeyboardButton("❌ Wrong Amount", callback_data=f"decline:{uid}:wrong"))
        kb.row(InlineKeyboardButton("❌ Duplicate", callback_data=f"decline:{uid}:duplicate"))
        kb.row(InlineKeyboardButton("❌ Unclear", callback_data=f"decline:{uid}:unclear"))
        kb.row(InlineKeyboardButton("✏️ Custom", callback_data=f"decline:{uid}:custom"))
        bot.send_message(ADMIN_ID, f"❌ **DECLINE**\n\n🆔 {uid}\n\nSelect:", reply_markup=kb, parse_mode='Markdown')
        bot.edit_message_text("⏳ Select reason...", call.message.chat.id, call.message.message_id)
        return
    
    # Decline with reason
    if "decline" in d:
        bot.answer_callback_query(call.id)
        if u.id != ADMIN_ID: return
        parts = d.split(":")
        uid = int(parts[1])
        rt = parts[2] if len(parts) > 2 else "custom"
        reasons = {
            "fake": "Payment proof appears fake.",
            "wrong": "Amount doesn't match.",
            "duplicate": "Proof used before.",
            "unclear": "Screenshot unclear."
        }
        reason = reasons.get(rt)
        if reason:
            if uid in pending_approvals:
                info = pending_approvals[uid]
                cursor.execute("UPDATE deposits SET status='rejected', decline_reason=? WHERE ref=?", (reason, info.get('ref')))
                conn.commit()
                try: bot.send_message(uid, f"❌ **PAYMENT DECLINED**\n\n📋 {reason}\n\nFix and try again.", parse_mode='Markdown')
                except: pass
                bot.send_message(ADMIN_ID, f"✅ Declined {uid}: {reason}")
                pending_approvals.pop(uid, None)
                try: bot.edit_message_text("❌ Declined", call.message.chat.id, call.message.message_id)
                except: pass
        else:
            user_data[u.id] = {"declining_user": uid}
            bot.send_message(ADMIN_ID, f"✏️ Custom reason for {uid}:")
        return

# ================= RUN =================
print("="*50)
print("✅ BOT RUNNING (TeleBot)!")
print("🛒 BUY = Instant purchase | ➕ Cart = Add to cart")
print("💰 Approval shows Previous & New balance")
print("👤 /balance [id] - View user balance")
print("="*50)
bot.infinity_polling()