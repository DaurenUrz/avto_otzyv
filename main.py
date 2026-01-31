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

# --- ИНИЦИАЛИЗАЦИЯ БД ---
def init_db():
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT, plate TEXT, rating INTEGER, 
        comment TEXT, photo_id TEXT, video_id TEXT, user_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER, plate TEXT, PRIMARY KEY (user_id, plate))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS purchases (
        user_id INTEGER PRIMARY KEY, access_granted INTEGER DEFAULT 0)''')
    try: cursor.execute("ALTER TABLE reviews ADD COLUMN photo_id TEXT")
    except: pass
    try: cursor.execute("ALTER TABLE reviews ADD COLUMN video_id TEXT")
    except: pass
    conn.commit()
    conn.close()

class Form(StatesGroup):
    entering_plate_search = State()
    entering_plate_review = State()
    choosing_rating = State()
    writing_comment = State()
    sending_media = State()
    register_my_plate = State()
    payment_proof = State()

def clean_plate(plate):
    return re.sub(r'[^A-Z0-9]', '', plate.upper())

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
    await message.answer("🇰🇿 <b>Driver Rating KZ</b>\nУзнайте правду о водителях или подпишитесь на уведомления о своем авто.", reply_markup=keyboard, parse_mode="HTML")

# --- ОТСЛЕЖИВАНИЕ НОМЕРА ---
@dp.message(F.text == "🔔 Отслеживать мой номер")
async def sub_start(message: types.Message, state: FSMContext):
    await message.answer("Введите госномер вашего авто (напр. 010ABC01):")
    await state.set_state(Form.register_my_plate)

@dp.message(Form.register_my_plate)
async def sub_finish(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO subscriptions (user_id, plate) VALUES (?, ?)", (message.from_user.id, plate))
        conn.commit()
        await message.answer(f"✅ Готово! Вы подписаны на уведомления для <b>{plate}</b>.", parse_mode="HTML")
    except:
        await message.answer(f"Вы уже подписаны на {plate}.")
    finally: conn.close()
    await state.clear()

# --- ПОИСК ---
@dp.message(F.text == "🔍 Проверить номер")
async def search_start(message: types.Message, state: FSMContext):
    await message.answer("Введите госномер для проверки:")
    await state.set_state(Form.entering_plate_search)

@dp.message(Form.entering_plate_search)
async def search_finish(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    user_access = has_access(message.from_user.id)
    
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("SELECT rating, comment, photo_id, video_id FROM reviews WHERE plate = ?", (plate,))
    results = cursor.fetchall()
    conn.close()

    if not results:
        await message.answer(f"По номеру {plate} отзывов нет.")
    else:
        await message.answer(f"📊 Найдено отзывов: {len(results)}")
        for i, res in enumerate(results):
            if i > 0 and not user_access:
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔓 Открыть все отзывы (500 ₸)", callback_data="buy_full")]])
                await message.answer(f"🔒 Еще {len(results)-1} отзыва скрыто. Оплатите доступ, чтобы увидеть всё.", reply_markup=kb)
                break
            
            stars = "⭐" * res[0]
            cap = f"{stars}\n{res[1]}"
            if res[3]: await message.answer_video(res[3], caption=cap)
            elif res[2]: await message.answer_photo(res[2], caption=cap)
            else: await message.answer(cap)
    await state.clear()

# --- ДОБАВЛЕНИЕ ОТЗЫВА ---
@dp.message(F.text == "✍️ Оставить отзыв")
async def review_start(message: types.Message, state: FSMContext):
    await message.answer("Введите номер автомобиля:")
    await state.set_state(Form.entering_plate_review)

@dp.message(Form.entering_plate_review)
async def review_plate(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    await state.update_data(plate=plate)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{i}⭐", callback_data=f"rate_{i}") for i in range(1, 6)]])
    await message.answer(f"Оцените водителя {plate}:", reply_markup=kb)
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
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Пропустить медиа")]], resize_keyboard=True)
    await message.answer("Добавьте фото/видео или пропустите:", reply_markup=kb)
    await state.set_state(Form.sending_media)

@dp.message(Form.sending_media)
async def review_media(message: types.Message, state: FSMContext):
    data = await state.get_data()
    p_id = message.photo[-1].file_id if message.photo else None
    v_id = message.video.file_id if message.video else None
    plate = data['plate']
    
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reviews (plate, rating, comment, photo_id, video_id, user_id) VALUES (?, ?, ?, ?, ?, ?)", 
                   (plate, data['rating'], data['comment'], p_id, v_id, message.from_user.id))
    
    cursor.execute("SELECT user_id FROM subscriptions WHERE plate = ?", (plate,))
    subs = cursor.fetchall()
    conn.commit(); conn.close()

    for s in subs:
        try: await bot.send_message(s[0], f"❗ <b>Новый отзыв на ваш авто {plate}!</b>\nПроверьте в поиске.")
        except: pass

    await message.answer("✅ Отзыв опубликован!", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔍 Проверить номер"), KeyboardButton(text="✍️ Оставить отзыв")]], resize_keyboard=True))
    await state.clear()

# --- СИСТЕМА ОПЛАТЫ (ИСПРАВЛЕНА) ---
@dp.callback_query(F.data == "buy_full")
async def pay_start(callback: types.CallbackQuery, state: FSMContext):
    order_id = random.randint(100, 999)
    # ИСПРАВЛЕНО: используем callback.message вместо message
    await callback.message.answer(f"💳 <b>Оплата доступа</b>\nПереведите <b>500 ₸</b> на Kaspi: <code>+77770000000</code>\nКомментарий: <code>ID{order_id}</code>\n\n<b>Пришлите скриншот чека сюда:</b>", parse_mode="HTML")
    await state.set_state(Form.payment_proof)
    await callback.answer()

@dp.message(Form.payment_proof, F.photo)
async def pay_proof(message: types.Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"confirm_{message.from_user.id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{message.from_user.id}")]
    ])
    await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"💰 Чек от {message.from_user.full_name} ({message.from_user.id})", reply_markup=kb)
    await message.answer("⏳ Чек отправлен модератору. Ожидайте подтверждения.")
    await state.clear()

@dp.callback_query(F.data.startswith("confirm_"))
async def pay_confirm(callback: types.CallbackQuery):
    uid = int(callback.data.split("_")[1])
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO purchases (user_id, access_granted) VALUES (?, 1)", (uid,))
    conn.commit(); conn.close()
    try:
        await bot.send_message(uid, "💎 <b>Доступ открыт!</b> Теперь вам видны все отзывы.")
    except: pass
    await callback.message.edit_caption(caption=f"{callback.message.caption}\n\n✅ ОДОБРЕНО")
    await callback.answer()

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())