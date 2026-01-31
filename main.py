import asyncio
import sqlite3
import re
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# --- НАСТРОЙКИ ---
API_TOKEN = '8266217370:AAEFAPTytERhMnwoxa7Rt-AkT8nxGm1km6k' 
ADMIN_ID = 1068233995 

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Справочник регионов Казахстана
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
        user_id INTEGER PRIMARY KEY, access_granted INTEGER DEFAULT 0)''')
    
    # Миграции
    try: cursor.execute("ALTER TABLE reviews ADD COLUMN latitude REAL")
    except: pass
    try: cursor.execute("ALTER TABLE reviews ADD COLUMN longitude REAL")
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

def has_access(user_id):
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("SELECT access_granted FROM purchases WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res and res[0] == 1

# --- ОБРАБОТЧИКИ МЕНЮ ---
@dp.message(Command("start"))
async def start(message: types.Message):
    kb = [
        [KeyboardButton(text="🔍 Проверить номер"), KeyboardButton(text="✍️ Оставить отзыв")],
        [KeyboardButton(text="🔔 Отслеживать мой номер")]
    ]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer("🇰🇿 <b>Driver Rating KZ</b>\nУзнайте рейтинг водителя и место нарушения на карте.", reply_markup=keyboard, parse_mode="HTML")

# --- ПОИСК ---
@dp.message(F.text == "🔍 Проверить номер")
async def search_start(message: types.Message, state: FSMContext):
    await message.answer("Введите госномер:")
    await state.set_state(Form.entering_plate_search)

@dp.message(Form.entering_plate_search)
async def search_finish(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    user_access = has_access(message.from_user.id)
    region = get_region_name(plate)
    
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("SELECT rating, comment, photo_id, video_id, latitude, longitude FROM reviews WHERE plate = ?", (plate,))
    results = cursor.fetchall()
    conn.close()

    if not results:
        await message.answer(f"По номеру <b>{plate}</b> ({region}) отзывов нет.", parse_mode="HTML")
    else:
        # РАСЧЕТ СРЕДНЕГО РЕЙТИНГА
        total = len(results)
        avg_val = sum(res[0] for res in results) / total
        stars_overall = "⭐" * int(round(avg_val))
        
        header = (f"🚘 <b>Госномер: {plate}</b>\n📍 Регион: {region}\n"
                  f"📊 Рейтинг: {stars_overall} ({avg_val:.1f}/5)\n"
                  f"💬 Отзывов: {total}\n"
                  f"________________________")
        await message.answer(header, parse_mode="HTML")

        for i, res in enumerate(results):
            if i > 0 and not user_access:
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔓 Показать скрытые отзывы (500 ₸)", callback_data="buy_full")]])
                await message.answer(f"🔒 Скрыто еще {total-1} отзыва.", reply_markup=kb)
                break
            
            cap = f"Отзыв #{i+1}: {'⭐' * res[0]}\n<i>«{res[1]}»</i>"
            kb = None
            if res[4] and res[5]: # Ссылка на карты
                map_url = f"https://www.google.com/maps?q={res[4]},{res[5]}"
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📍 Где это было?", url=map_url)]])
            
            if res[3]: await message.answer_video(res[3], caption=cap, reply_markup=kb, parse_mode="HTML")
            elif res[2]: await message.answer_photo(res[2], caption=cap, reply_markup=kb, parse_mode="HTML")
            else: await message.answer(cap, reply_markup=kb, parse_mode="HTML")
    await state.clear()

# --- ДОБАВЛЕНИЕ ОТЗЫВА ---
@dp.message(F.text == "✍️ Оставить отзыв")
async def review_start(message: types.Message, state: FSMContext):
    await message.answer("Введите госномер:")
    await state.set_state(Form.entering_plate_review)

@dp.message(Form.entering_plate_review)
async def review_plate(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    await state.update_data(plate=plate)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{i}⭐", callback_data=f"rate_{i}") for i in range(1, 6)]])
    await message.answer(f"Оценка для {plate}:", reply_markup=kb)
    await state.set_state(Form.choosing_rating)

@dp.callback_query(F.data.startswith("rate_"))
async def review_rate(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(rating=int(callback.data.split("_")[1]))
    await callback.message.answer("Опишите, что случилось:")
    await state.set_state(Form.writing_comment)
    await callback.answer()

@dp.message(Form.writing_comment)
async def review_comment(message: types.Message, state: FSMContext):
    await state.update_data(comment=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📍 Отправить гео", request_location=True)],
        [KeyboardButton(text="Пропустить")]
    ], resize_keyboard=True)
    await message.answer("Добавьте геолокацию (кнопка снизу):", reply_markup=kb)
    await state.set_state(Form.sending_geo)

@dp.message(Form.sending_geo)
async def review_geo(message: types.Message, state: FSMContext):
    if message.location:
        await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Пропустить")]], resize_keyboard=True)
    await message.answer("Пришлите фото/видео или нажмите Пропустить:", reply_markup=kb)
    await state.set_state(Form.sending_media)

@dp.message(Form.sending_media)
async def review_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    p_id = message.photo[-1].file_id if message.photo else None
    v_id = message.video.file_id if message.video else None
    
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reviews (plate, rating, comment, photo_id, video_id, latitude, longitude, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                   (data['plate'], data['rating'], data['comment'], p_id, v_id, data.get('lat'), data.get('lon'), message.from_user.id))
    
    # Уведомление подписчикам
    cursor.execute("SELECT user_id FROM subscriptions WHERE plate = ?", (data['plate'],))
    subs = cursor.fetchall()
    conn.commit(); conn.close()
    for s in subs:
        try: await bot.send_message(s[0], f"❗ Новый отзыв на ваш авто {data['plate']}!")
        except: pass

    await message.answer("✅ Отзыв опубликован!", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔍 Проверить номер")]], resize_keyboard=True))
    await state.clear()

# --- ПЛАТЕЖИ, ПОДПИСКИ И MAIN (БЕЗ ИЗМЕНЕНИЙ) ---
@dp.callback_query(F.data == "buy_full")
async def pay_start(callback: types.CallbackQuery, state: FSMContext):
    order_id = random.randint(100, 999)
    await callback.message.answer(f"💳 <b>Оплата</b>\n500 ₸ на Kaspi: <code>+77770000000</code>\nID: {order_id}\nЖду скрин чека:", parse_mode="HTML")
    await state.set_state(Form.payment_proof)
    await callback.answer()

@dp.message(Form.payment_proof, F.photo)
async def pay_proof(message: types.Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"confirm_{message.from_user.id}")]])
    await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"Чек {message.from_user.id}", reply_markup=kb)
    await message.answer("⏳ Проверяем чек...")
    await state.clear()

@dp.callback_query(F.data.startswith("confirm_"))
async def pay_confirm(callback: types.CallbackQuery):
    uid = int(callback.data.split("_")[1])
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO purchases (user_id, access_granted) VALUES (?, 1)", (uid,))
    conn.commit(); conn.close()
    await bot.send_message(uid, "💎 Доступ открыт!")
    await callback.message.edit_caption(caption="✅ ОДОБРЕНО")

@dp.message(F.text == "🔔 Отслеживать мой номер")
async def sub_start(message: types.Message, state: FSMContext):
    await message.answer("Введите ваш госномер:")
    await state.set_state(Form.register_my_plate)

@dp.message(Form.register_my_plate)
async def sub_finish(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO subscriptions (user_id, plate) VALUES (?, ?)", (message.from_user.id, plate))
        conn.commit()
        await message.answer(f"✅ Вы будете получать уведомления о {plate}")
    except: await message.answer("Уже подписаны.")
    finally: conn.close()
    await state.clear()

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())