import asyncio
import sqlite3
import re
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand

# --- НАСТРОЙКИ ---
API_TOKEN = '8266217370:AAEFAPTytERhMnwoxa7Rt-AkT8nxGm1km6k' 
ADMIN_ID = 1068233995 

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

KZ_REGIONS = {
    "01": "Астана", "02": "Алматы", "03": "Акмолинская обл.", "04": "Актюбинская обл.",
    "05": "Алматинская обл.", "06": "Атырауская обл.", "07": "ЗКО", "08": "Жамбылская обл.",
    "09": "Карагандинская обл.", "10": "Костанайская обл.", "11": "Кызылординская обл.",
    "12": "Мангистауская обл.", "13": "Туркестанская обл.", "14": "Павлодарская обл.",
    "15": "СКО", "16": "ВКО", "17": "Шымкент", "18": "Абайская обл.", "19": "Жетысуская обл.", 
    "20": "Улытауская обл."
}

# --- ИНИЦИАЛИЗАЦИЯ БД ---
def init_db():
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT, plate TEXT, rating INTEGER, 
        comment TEXT, photo_id TEXT, video_id TEXT, 
        latitude REAL, longitude REAL, user_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER, plate TEXT, PRIMARY KEY (user_id, plate))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS purchases (
        user_id INTEGER PRIMARY KEY, access_granted INTEGER DEFAULT 0, multi_car INTEGER DEFAULT 0)''')
    
    # Миграции колонок
    cols = [('photo_id', 'TEXT'), ('video_id', 'TEXT'), ('latitude', 'REAL'), ('longitude', 'REAL')]
    for c, t in cols:
        try: cursor.execute(f"ALTER TABLE reviews ADD COLUMN {c} {t}")
        except: pass
    try: cursor.execute("ALTER TABLE purchases ADD COLUMN multi_car INTEGER DEFAULT 0")
    except: pass
    conn.commit()
    conn.close()

class Form(StatesGroup):
    entering_plate_search = State()
    entering_plate_review = State()
    choosing_rating = State()
    writing_comment = State()
    sending_geo = State()
    sending_media = State()
    register_my_plate = State()
    payment_proof = State()

def clean_plate(plate):
    return re.sub(r'[^A-Z0-9]', '', plate.upper())

def get_region_name(plate):
    region_code = plate[-2:]
    return KZ_REGIONS.get(region_code, "Регион не определен")

def get_user_status(user_id):
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("SELECT access_granted, multi_car FROM purchases WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res if res else (0, 0)

# --- МЕНЮ КОМАНД ---
async def set_main_menu(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="search", description="Проверить номер"),
        BotCommand(command="review", description="Оставить отзыв"),
        BotCommand(command="my_cars", description="Мой гараж 🚗")
    ]
    await bot.set_my_commands(commands)

@dp.message(Command("start"))
async def start(message: types.Message):
    kb = [
        [KeyboardButton(text="🔍 Проверить номер"), KeyboardButton(text="✍️ Оставить отзыв")],
        [KeyboardButton(text="🚗 Мои авто"), KeyboardButton(text="🔔 Подписаться")]
    ]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer("🇰🇿 <b>Driver Rating KZ Pro</b>\nДобро пожаловать в систему контроля кармы водителей.", reply_markup=keyboard, parse_mode="HTML")

# --- ЛОГИКА ГАРАЖА ---
@dp.message(F.text == "🚗 Мои авто")
@dp.message(Command("my_cars"))
async def my_cars(message: types.Message):
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("SELECT plate FROM subscriptions WHERE user_id = ?", (message.from_user.id,))
    cars = cursor.fetchall()
    conn.close()
    if not cars:
        await message.answer("У вас еще нет добавленных авто.")
    else:
        text = "🚘 <b>Ваши авто:</b>\n\n" + "\n".join([f"• <code>{c[0]}</code>" for c in cars])
        await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "🔔 Подписаться")
async def sub_check(message: types.Message, state: FSMContext):
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id = ?", (message.from_user.id,))
    count = cursor.fetchone()[0]
    conn.close()
    _, multi = get_user_status(message.from_user.id)
    
    if count >= 1 and multi == 0:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💎 Купить Multi-Car (1000 ₸)", callback_data="buy_multi")]])
        await message.answer("⚠️ Бесплатно можно добавить только 1 авто. Для расширения гаража купите Multi-Car доступ.", reply_markup=kb)
    else:
        await message.answer("Введите госномер авто для отслеживания:")
        await state.set_state(Form.register_my_plate)

@dp.message(Form.register_my_plate)
async def sub_finish(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO subscriptions (user_id, plate) VALUES (?, ?)", (message.from_user.id, plate))
        conn.commit()
        await message.answer(f"✅ Готово! Вы подписаны на <b>{plate}</b>.", parse_mode="HTML")
    except: await message.answer("Этот номер уже есть в подписках.")
    finally: conn.close()
    await state.clear()

# --- ПОИСК ---
@dp.message(F.text == "🔍 Проверить номер")
@dp.message(Command("search"))
async def search_start(message: types.Message, state: FSMContext):
    await message.answer("Введите госномер:")
    await state.set_state(Form.entering_plate_search)

@dp.message(Form.entering_plate_search)
async def search_finish(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    access, _ = get_user_status(message.from_user.id)
    region = get_region_name(plate)
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("SELECT rating, comment, photo_id, video_id, latitude, longitude FROM reviews WHERE plate = ?", (plate,))
    results = cursor.fetchall()
    conn.close()

    if not results:
        await message.answer(f"По номеру {plate} ({region}) отзывов нет.")
    else:
        avg = sum(r[0] for r in results) / len(results)
        header = f"🚘 <b>{plate}</b> ({region})\n📊 Рейтинг: {'⭐'*int(round(avg))} ({avg:.1f}/5)\n💬 Отзывов: {len(results)}"
        kb_share = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📲 Поделиться", callback_data=f"share_{plate}")]])
        await message.answer(header, reply_markup=kb_share, parse_mode="HTML")
        for i, res in enumerate(results):
            if i > 0 and access == 0:
                kb_p = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔓 Открыть всё (500 ₸)", callback_data="buy_full")]])
                await message.answer(f"🔒 Скрыто еще {len(results)-1} отзывов.", reply_markup=kb_p)
                break
            cap = f"<b>Отзыв #{i+1}</b>: {'⭐'*res[0]}\n<i>«{res[1]}»</i>"
            kb_m = None
            if res[4] and res[5]:
                kb_m = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📍 На карте", url=f"http://maps.google.com/?q={res[4]},{res[5]}")]])
            if res[3]: await message.answer_video(res[3], caption=cap, reply_markup=kb_m, parse_mode="HTML")
            elif res[2]: await message.answer_photo(res[2], caption=cap, reply_markup=kb_m, parse_mode="HTML")
            else: await message.answer(cap, reply_markup=kb_m, parse_mode="HTML")
    await state.clear()

# --- ПЛАТЕЖИ И СМАРТ-ПОДТВЕРЖДЕНИЕ ---
@dp.callback_query(F.data.startswith("buy_"))
async def pay_init(callback: types.CallbackQuery, state: FSMContext):
    ptype = callback.data.split("_")[1]
    price = "500 ₸" if ptype == "full" else "1000 ₸"
    await state.update_data(ptype=ptype)
    oid = random.randint(100, 999)
    await callback.message.answer(f"💳 <b>Оплата: {ptype.upper()}</b>\nСумма: {price}\nKaspi: <code>+77770000000</code>\nID: {oid}\nПришлите чек:")
    await state.set_state(Form.payment_proof)
    await callback.answer()

@dp.message(Form.payment_proof, F.photo)
async def pay_check(message: types.Message, state: FSMContext):
    data = await state.get_data()
    pt = data.get('ptype', 'full')
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"conf_{message.from_user.id}_{pt}")]])
    await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"Чек {pt} от {message.from_user.id}", reply_markup=kb)
    await message.answer("⏳ Чек отправлен модератору.")
    await state.clear()

@dp.callback_query(F.data.startswith("conf_"))
async def pay_confirm(callback: types.CallbackQuery):
    _, uid, pt = callback.data.split("_")
    uid = int(uid)
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    if pt == "full":
        cursor.execute("INSERT OR REPLACE INTO purchases (user_id, access_granted, multi_car) VALUES (?, 1, (SELECT multi_car FROM purchases WHERE user_id=?))", (uid, uid))
        msg = "💎 <b>Полный доступ открыт!</b>\n\nВведите госномер для глубокой проверки:"
        next_state = Form.entering_plate_search
    else:
        cursor.execute("INSERT OR REPLACE INTO purchases (user_id, multi_car, access_granted) VALUES (?, 1, (SELECT access_granted FROM purchases WHERE user_id=?))", (uid, uid))
        msg = "🚀 <b>Multi-Car активирован!</b>\n\nВведите номер авто для добавления в гараж:"
        next_state = Form.register_my_plate
    conn.commit(); conn.close()
    
    # СМАРТ-ПЕРЕХОД: Активируем стейт юзеру
    user_context = dp.fsm.resolve_context(bot, uid, uid)
    await user_context.set_state(next_state)
    await bot.send_message(uid, msg, parse_mode="HTML")
    await callback.message.edit_caption(caption="✅ АКТИВИРОВАНО")
    await callback.answer()

# --- ОТЗЫВЫ (REVIEW) ---
@dp.message(F.text == "✍️ Оставить отзыв")
@dp.message(Command("review"))
async def review_cmd(message: types.Message, state: FSMContext):
    await message.answer("Введите госномер авто:")
    await state.set_state(Form.entering_plate_review)

@dp.message(Form.entering_plate_review)
async def review_plate(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    await state.update_data(plate=plate)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{i}⭐", callback_data=f"rate_{i}") for i in range(1, 6)]])
    await message.answer(f"Оцените {plate}:", reply_markup=kb)
    await state.set_state(Form.choosing_rating)

@dp.callback_query(F.data.startswith("rate_"))
async def review_rate(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(rating=int(callback.data.split("_")[1]))
    await callback.message.answer("Что произошло?")
    await state.set_state(Form.writing_comment)
    await callback.answer()

@dp.message(Form.writing_comment)
async def review_comment(message: types.Message, state: FSMContext):
    await state.update_data(comment=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Гео", request_location=True)], [KeyboardButton(text="Пропустить")]], resize_keyboard=True)
    await message.answer("Где это было?", reply_markup=kb)
    await state.set_state(Form.sending_geo)

@dp.message(Form.sending_geo)
async def review_geo(message: types.Message, state: FSMContext):
    if message.location: await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Пропустить")]], resize_keyboard=True)
    await message.answer("Пришлите фото/видео:", reply_markup=kb)
    await state.set_state(Form.sending_media)

@dp.message(Form.sending_media)
async def review_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    p_id = message.photo[-1].file_id if message.photo else None
    v_id = message.video.file_id if message.video else None
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reviews (plate, rating, comment, photo_id, video_id, latitude, longitude, user_id) VALUES (?,?,?,?,?,?,?,?)",
                   (data['plate'], data['rating'], data['comment'], p_id, v_id, data.get('lat'), data.get('lon'), message.from_user.id))
    cursor.execute("SELECT user_id FROM subscriptions WHERE plate = ?", (data['plate'],))
    subs = cursor.fetchall()
    conn.commit(); conn.close()
    for s in subs:
        try: await bot.send_message(s[0], f"❗ Новый отзыв на ваш авто {data['plate']}!")
        except: pass
    await message.answer("✅ Отзыв опубликован!", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔍 Проверить номер")]], resize_keyboard=True))
    await state.clear()

@dp.callback_query(F.data.startswith("share_"))
async def share_handler(callback: types.CallbackQuery):
    plate = callback.data.split("_")[1]
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("SELECT rating FROM reviews WHERE plate = ?", (plate,))
    ratings = cursor.fetchall()
    conn.close()
    avg = sum(r[0] for r in ratings) / len(ratings)
    me = await bot.get_me()
    text = f"🚗 <b>DRIVER CARD: {plate}</b>\n📊 Рейтинг: {'⭐'*int(round(avg))} ({avg:.1f}/5)\n\n👉 @{me.username}"
    await callback.message.answer(f"📸 <b>Сделайте скриншот:</b>\n\n{text}", parse_mode="HTML")
    await callback.answer()

async def main():
    init_db()
    await set_main_menu(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())