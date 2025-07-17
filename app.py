import asyncio
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums.parse_mode import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from datetime import datetime

API_TOKEN = '8075865260:AAF_l3d9kwqP0stM5mEF8k_VaFXhnb62Toc'
DB_PATH = "autogifts.db"
ADMIN_IDS = [7794800788,1390498710,7677895183]  # Замени на свой Telegram ID

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# --- FSM для теста (можно расширить) ---
class AdminStates(StatesGroup):
    waiting_commission_rate = State()
    waiting_broadcast_text = State()

from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

class AutobuyStarsStates(StatesGroup):
    waiting_for_min = State()
    waiting_for_max = State()

def get_autobuy_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Включить", callback_data="autobuy_on"),
         InlineKeyboardButton(text="❌ Выключить", callback_data="autobuy_off")],
        [InlineKeyboardButton(text="⭐ Установить диапазон звёзд", callback_data="autobuy_set_stars_range")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])

@dp.callback_query(F.data == "autobuy_set_stars_range")
async def autobuy_set_stars_range(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите МИНИМАЛЬНОЕ количество звёзд для автопокупки:")
    await state.set_state(AutobuyStarsStates.waiting_for_min)
    await callback.answer()

@dp.message(AutobuyStarsStates.waiting_for_min)
async def process_autobuy_min(message: types.Message, state: FSMContext):
    try:
        min_stars = int(message.text.strip())
        await state.update_data(min_stars=min_stars)
        await message.answer("Введите МАКСИМАЛЬНОЕ количество звёзд для автопокупки:")
        await state.set_state(AutobuyStarsStates.waiting_for_max)
    except Exception:
        await message.answer("Ошибка! Введите только число.")

@dp.message(AutobuyStarsStates.waiting_for_max)
async def process_autobuy_max(message: types.Message, state: FSMContext):
    try:
        max_stars = int(message.text.strip())
        data = await state.get_data()
        min_stars = data.get("min_stars", 0)
        if max_stars < min_stars:
            await message.answer("Максимальное значение должно быть больше или равно минимальному!")
            return
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET autobuy_stars_min=?, autobuy_stars_max=? WHERE user_id=?",
                             (min_stars, max_stars, message.from_user.id))
            await db.commit()
        await message.answer(f"Диапазон звёзд для автопокупки установлен: от {min_stars} до {max_stars} ⭐")
    except Exception:
        await message.answer("Ошибка! Введите только число.")
    await state.clear()

# --- БАЗА ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0,
            total_deposit REAL DEFAULT 0,
            referrals INTEGER DEFAULT 0
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            gift_name TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS commission (
            id INTEGER PRIMARY KEY,
            rate REAL DEFAULT 5,
            enabled INTEGER DEFAULT 1,
            accumulated REAL DEFAULT 0
        )""")
        await db.execute("""
        INSERT OR IGNORE INTO commission (id, rate, enabled, accumulated)
        VALUES (1, 5, 1, 0)
        """)
        await db.commit()

def is_admin(user_id):
    return user_id in ADMIN_IDS

async def create_user(user_id, username=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        if username:
            await db.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
        await db.commit()

async def get_user_info(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT username, balance, total_deposit, referrals FROM users WHERE user_id=?", (user_id,))
        return await cursor.fetchone()

async def get_balance(user_id):
    await create_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        res = await cursor.fetchone()
        return res[0] if res else 0

async def add_deposit(user_id, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        # Комиссия
        cursor = await db.execute("SELECT rate, enabled FROM commission WHERE id=1")
        commission_data = await cursor.fetchone()
        commission_rate = commission_data[0] if commission_data else 0
        commission_enabled = commission_data[1] if commission_data else 1
        commission_value = amount * commission_rate / 100 if commission_enabled else 0
        net_amount = amount - commission_value

        await db.execute("INSERT INTO deposits (user_id, amount) VALUES (?, ?)", (user_id, amount))
        await db.execute("UPDATE users SET balance=balance+?, total_deposit=total_deposit+? WHERE user_id=?",
                         (net_amount, amount, user_id))
        await db.execute("UPDATE commission SET accumulated=accumulated+? WHERE id=1", (commission_value,))
        await db.commit()

async def get_deposit_history(user_id, limit=5):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT amount, timestamp FROM deposits WHERE user_id=? ORDER BY timestamp DESC LIMIT ?
        """, (user_id, limit))
        return await cursor.fetchall()

async def refund_user(user_id, amount):
    await create_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        res = await cursor.fetchone()
        if not res or res[0] < amount:
            return False
        await db.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, user_id))
        await db.commit()
        return True

async def get_top_leaders(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT user_id, username, total_deposit FROM users ORDER BY total_deposit DESC LIMIT ?
        """, (limit,))
        return await cursor.fetchall()

async def buy_gift(user_id, gift_name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO gifts (user_id, gift_name) VALUES (?, ?)", (user_id, gift_name))
        await db.commit()

async def get_gift_history(user_id, limit=5):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT gift_name, timestamp FROM gifts WHERE user_id=? ORDER BY timestamp DESC LIMIT ?
        """, (user_id, limit))
        return await cursor.fetchall()

# --- КНОПКИ ---
def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Магазин подарков", callback_data="catalog")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="💰 Пополнить", callback_data="deposit")],
        [InlineKeyboardButton(text="🏆 Топ", callback_data="top"),
         InlineKeyboardButton(text="📜 История", callback_data="history")],
        [InlineKeyboardButton(text="🤝 Рефералы", callback_data="referrals"),
         InlineKeyboardButton(text="⚙️ Автопокупка", callback_data="autobuy")],
        [InlineKeyboardButton(text="💬 Поддержка", url="https://t.me/support")],
    ])

def get_profile_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Рефаунд", callback_data="refund")],
        [InlineKeyboardButton(text="🎁 Мои подарки", callback_data="my_gifts")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])

def get_deposit_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пополнить на 100₽", callback_data="deposit_100"),
         InlineKeyboardButton(text="Пополнить на 500₽", callback_data="deposit_500")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])

def get_catalog_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎉 Подарок 1 — 50₽", callback_data="gift_1")],
        [InlineKeyboardButton(text="🎉 Подарок 2 — 100₽", callback_data="gift_2")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])

def get_refund_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Рефаунд 10₽", callback_data="refund_10"),
         InlineKeyboardButton(text="Рефаунд 50₽", callback_data="refund_50")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")]
    ])



def get_gift_back_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к профилю", callback_data="profile")]
    ])

def get_admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Настроить комиссию", callback_data="admin_commission")],
        [InlineKeyboardButton(text="Вывод комиссии", callback_data="admin_commission_view")],
        [InlineKeyboardButton(text="История пополнений", callback_data="admin_deposit_history")],
        [InlineKeyboardButton(text="Топ лидеров", callback_data="admin_top_leaders")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
    ])

def get_admin_commission_menu(enabled):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сменить процент", callback_data="admin_commission_change")],
        [InlineKeyboardButton(text="Включить" if not enabled else "Выключить", callback_data="admin_commission_toggle")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
    ])

# --- HANDLERS ---

@dp.message(F.text == "/start")
async def start_command(message: types.Message):
    await create_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "🎉 <b>AutoGiftsBot</b>\n\n"
        "Добро пожаловать! Здесь ты можешь покупать подарки, следить за балансом, приглашать друзей и получать бонусы.\n"
        "Выбери действие из меню 👇",
        reply_markup=get_main_menu()
    )

@dp.callback_query(F.data == "main_menu")
async def main_menu(callback: types.CallbackQuery):
    await callback.message.answer("Главное меню 👇", reply_markup=get_main_menu())
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def profile(callback: types.CallbackQuery):
    info = await get_user_info(callback.from_user.id)
    username = info[0] or "Нет"
    balance = info[1]
    total_deposit = info[2]
    referrals = info[3]

    # Новый код:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT autobuy_enabled FROM users WHERE user_id=?", (callback.from_user.id,))
        autobuy_enabled = (await cursor.fetchone())[0]

    autobuy_status = "Включена" if autobuy_enabled else "Выключена"

    await callback.message.answer(
        f"👤 <b>Профиль</b>\n"
        f"Юзер: @{username}\n"
        f"ID: <code>{callback.from_user.id}</code>\n"
        f"Баланс: <b>{balance:.2f}₽</b>\n"
        f"Всего пополнено: <b>{total_deposit:.2f}₽</b>\n"
        f"Рефералов: <b>{referrals}</b>\n"
        f"Автопокупка: <b>{autobuy_status}</b>",
        reply_markup=get_profile_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "deposit")
async def deposit(callback: types.CallbackQuery):
    await callback.message.answer(
        "💰 <b>Пополнение баланса</b>\n"
        "Выберите сумму:",
        reply_markup=get_deposit_menu()
    )
    await callback.answer()

@dp.callback_query(F.data.in_(["deposit_100", "deposit_500"]))
async def deposit_amount(callback: types.CallbackQuery):
    amount = 100 if callback.data == "deposit_100" else 500
    await add_deposit(callback.from_user.id, amount)

    # Получаем статус автопокупки и баланс
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT autobuy_enabled, autobuy_stars_min, autobuy_stars_max, balance FROM users WHERE user_id=?",
            (callback.from_user.id,))
        autobuy_enabled, stars_min, stars_max, balance = await cursor.fetchone()

    if autobuy_enabled:
        gifts = [
            ("Подарок 1", 50, 3),
            ("Подарок 2", 100, 5),
            ("Подарок 3", 200, 8),
            # ... и т.д.
        ]
        for gift_name, price, stars in sorted(gifts, key=lambda x: x[1]):
            if not (stars_min <= stars <= stars_max):
                continue
        while balance >= price:
            await refund_user(callback.from_user.id, price)
            await buy_gift(callback.from_user.id, gift_name)
            balance -= price
            message += f"\n🎉 Автопокупка: <b>{gift_name}</b> за {price}₽ ({stars} ⭐)"

        await callback.message.answer(
            message,
            reply_markup=get_main_menu()
        )
        await callback.answer()

@dp.callback_query(F.data == "catalog")
async def catalog(callback: types.CallbackQuery):
    await callback.message.answer(
        "🎁 <b>Магазин подарков</b>\nВыбери подарок 👇",
        reply_markup=get_catalog_menu()
    )
    await callback.answer()

@dp.callback_query(F.data.in_(["gift_1", "gift_2"]))
async def buy_gift_handler(callback: types.CallbackQuery):
    gifts = {
        "gift_1": ("Подарок 1", 50),
        "gift_2": ("Подарок 2", 100)
    }
    gift_name, price = gifts[callback.data]
    balance = await get_balance(callback.from_user.id)
    if balance < price:
        await callback.message.answer(
            f"❌ Недостаточно средств! Стоимость: {price}₽, ваш баланс: {balance:.2f}₽"
        )
    else:
        await refund_user(callback.from_user.id, price)
        await buy_gift(callback.from_user.id, gift_name)
        await callback.message.answer(
            f"🎉 Покупка: <b>{gift_name}</b>\n"
            f"Чек: <code>#{datetime.now().strftime('%Y%m%d%H%M%S')}</code>\n"
            f"Спасибо за покупку!\n\n"
            f"Баланс: <b>{await get_balance(callback.from_user.id):.2f}₽</b>",
            reply_markup=get_main_menu()
        )
    await callback.answer()

@dp.callback_query(F.data == "top")
async def top(callback: types.CallbackQuery):
    top_users = await get_top_leaders()
    text = "🏆 <b>Топ пользователей:</b>\n"
    for i, (uid, username, amount) in enumerate(top_users, 1):
        name = f"@{username}" if username else f"{uid}"
        text += f"{i}. {name}: {amount}₽\n"
    await callback.message.answer(text, reply_markup=get_main_menu())
    await callback.answer()

@dp.callback_query(F.data == "history")
async def history(callback: types.CallbackQuery):
    history = await get_deposit_history(callback.from_user.id)
    text = "<b>📜 История пополнений:</b>\n"
    if history:
        for amount, timestamp in history:
            dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            text += f"+{amount}₽ ({dt.strftime('%d.%m.%Y %H:%M')})\n"
    else:
        text += "Нет пополнений."
    await callback.message.answer(text, reply_markup=get_main_menu())
    await callback.answer()

@dp.callback_query(F.data == "my_gifts")
async def my_gifts(callback: types.CallbackQuery):
    gifts = await get_gift_history(callback.from_user.id)
    text = "<b>🎁 Мои подарки:</b>\n"
    if gifts:
        for gift_name, timestamp in gifts:
            dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            text += f"• {gift_name} ({dt.strftime('%d.%m.%Y %H:%M')})\n"
    else:
        text += "Нет покупок подарков."
    await callback.message.answer(text, reply_markup=get_gift_back_menu())
    await callback.answer()

@dp.callback_query(F.data == "referrals")
async def referrals(callback: types.CallbackQuery):
    await callback.message.answer(
        "🤝 <b>Реферальная программа</b>\n"
        "Приглашай друзей и получай бонусы!\n"
        f"Ваша реферальная ссылка:\n"
        f"<code>https://t.me/{(await bot.get_me()).username}?start={callback.from_user.id}</code>",
        reply_markup=get_main_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "refund")
async def refund_menu(callback: types.CallbackQuery):
    await callback.message.answer(
        "💸 <b>Рефаунд</b>\nВыберите сумму или отправьте команду /refund сумма",
        reply_markup=get_refund_menu()
    )
    await callback.answer()

@dp.callback_query(F.data.in_(["refund_10", "refund_50"]))
async def refund_amount(callback: types.CallbackQuery):
    amount = 10 if callback.data == "refund_10" else 50
    ok = await refund_user(callback.from_user.id, amount)
    if ok:
        await callback.message.answer(f"💸 Рефаунд: -{amount}₽ возвращено вам.")
    else:
        await callback.message.answer("❌ Недостаточно средств для рефаунда.")
    await callback.answer()

@dp.message(F.text.startswith("/refund"))
async def refund_command(message: types.Message):
    try:
        amount = int(message.text.split()[1])
        ok = await refund_user(message.from_user.id, amount)
        if ok:
            await message.answer(f"💸 Рефаунд: -{amount}₽ возвращено вам.")
        else:
            await message.answer("❌ Недостаточно средств для рефаунда.")
    except Exception:
        await message.answer("Ошибка! Используйте: /refund сумма")

@dp.callback_query(F.data == "autobuy")
async def autobuy_menu(callback: types.CallbackQuery):
    await callback.message.answer(
        "⚙️ <b>Автопокупка</b>\nВключить или выключить автопокупку:",
        reply_markup=get_autobuy_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "autobuy_on")
async def autobuy_on(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET autobuy_enabled=1 WHERE user_id=?", (callback.from_user.id,))
        await db.commit()
    await callback.message.answer("✅ Автопокупка <b>включена</b>!", reply_markup=get_main_menu())
    await callback.answer()

@dp.callback_query(F.data == "autobuy_off")
async def autobuy_off(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET autobuy_enabled=0 WHERE user_id=?", (callback.from_user.id,))
        await db.commit()
    await callback.message.answer("❌ Автопокупка <b>выключена</b>!", reply_markup=get_main_menu())
    await callback.answer()

# --- ADMIN ---

@dp.message(F.text == "/admin")
async def admin_menu(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    await message.answer("🛠️ <b>Админ-панель</b>", reply_markup=get_admin_menu())

@dp.callback_query(F.data == "admin_commission")
async def admin_commission(callback: types.CallbackQuery, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT rate, enabled, accumulated FROM commission WHERE id=1")
        rate, enabled, accumulated = await cursor.fetchone()
    await callback.message.answer(
        f"💸 <b>Комиссия</b>\n"
        f"Процент: <b>{rate}%</b>\n"
        f"Статус: <b>{'Включена' if enabled else 'Выключена'}</b>\n"
        f"Накоплено: <b>{accumulated:.2f}₽</b>",
        reply_markup=get_admin_commission_menu(enabled)
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_commission_change")
async def admin_commission_change(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите новый процент комиссии (например: 5):")
    await state.set_state(AdminStates.waiting_commission_rate)
    await callback.answer()

@dp.message(AdminStates.waiting_commission_rate)
async def process_commission_rate(message: types.Message, state: FSMContext):
    try:
        rate = float(message.text.strip())
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE commission SET rate=? WHERE id=1", (rate,))
            await db.commit()
        await message.answer(f"✅ Процент комиссии обновлён: <b>{rate}%</b>")
    except Exception:
        await message.answer("Ошибка! Введите только число (например: 3.5)")
    await state.clear()

@dp.callback_query(F.data == "admin_commission_toggle")
async def admin_commission_toggle(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT enabled FROM commission WHERE id=1")
        enabled = (await cursor.fetchone())[0]
        new_enabled = 0 if enabled else 1
        await db.execute("UPDATE commission SET enabled=? WHERE id=1", (new_enabled,))
        await db.commit()
    await callback.message.answer(f"{'✅ Комиссия включена.' if new_enabled else '❌ Комиссия выключена.'}")
    await callback.answer()

@dp.callback_query(F.data == "admin_commission_view")
async def admin_commission_view(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT accumulated FROM commission WHERE id=1")
        accumulated = (await cursor.fetchone())[0]
    await callback.message.answer(
        f"💰 <b>Накопленная комиссия:</b> <b>{accumulated:.2f}₽</b>"
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_deposit_history")
async def admin_deposit_history(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT user_id, amount, timestamp FROM deposits ORDER BY timestamp DESC LIMIT 20
        """)
        deposits = await cursor.fetchall()
    text = "<b>Последние пополнения:</b>\n"
    for uid, amount, timestamp in deposits:
        dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        text += f"ID: <code>{uid}</code> +{amount}₽ ({dt.strftime('%d.%m.%Y %H:%M')})\n"
    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(F.data == "admin_top_leaders")
async def admin_top_leaders(callback: types.CallbackQuery):
    top_users = await get_top_leaders(limit=10)
    text = "🏆 <b>Топ лидеров по вложениям:</b>\n"
    for i, (uid, username, amount) in enumerate(top_users, 1):
        name = f"@{username}" if username else f"{uid}"
        text += f"{i}. {name}: {amount}⭐\n"
    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Отправьте текст для рассылки:")
    await state.set_state(AdminStates.waiting_broadcast_text)
    await callback.answer()

@dp.message(AdminStates.waiting_broadcast_text)
async def process_broadcast_text(message: types.Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM users")
        users = await cursor.fetchall()
    sent, errors = 0, 0
    for (user_id,) in users:
        try:
            await bot.send_message(user_id, message.text)
            sent += 1
        except Exception:
            errors += 1
    await message.answer(f"✅ Рассылка завершена!\nУспешно: {sent}\nОшибок: {errors}")
    await state.clear()

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery):
    await callback.message.answer("🛠️ <b>Админ-панель</b>", reply_markup=get_admin_menu())
    await callback.answer()

# --- RUN ---
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
