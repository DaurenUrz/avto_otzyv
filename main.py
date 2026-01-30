import asyncio
import sqlite3
import re
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
    # Таблица отзывов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT,
            rating INTEGER,
            comment TEXT,
            photo_id TEXT,
            user_id INTEGER
        )
    ''')
    # Таблица подписок на уведомления
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER,
            plate TEXT,
            PRIMARY KEY (user_id, plate)
        )
    ''')
    try:
        cursor.execute("ALTER TABLE reviews ADD COLUMN photo_id TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

class Form(StatesGroup):
    entering_plate_search = State()
    entering_plate_review = State()
    choosing_rating = State()
    writing_comment = State()
    sending_photo = State()
    register_my_plate = State()

def clean_plate(plate):
    return re.sub(r'[^A-Z0-9]', '', plate.upper())

@dp.message(Command("start"))
async def start(message: types.Message):
    kb = [
        [KeyboardButton(text="🔍 Проверить номер"), KeyboardButton(text="✍️ Оставить отзыв")],
        [KeyboardButton(text="🔔 Отслеживать мой номер")]
    ]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer("🇰🇿 <b>Driver Rating KZ</b>\nУзнайте, что пишут о водителях, или подпишитесь на уведомления о своем авто.", reply_markup=keyboard, parse_mode="HTML")

# --- ПОДПИСКА НА СВОЙ НОМЕР ---
@dp.message(F.text == "🔔 Отслеживать мой номер")
async def ask_my_plate(message: types.Message, state: FSMContext):
    await message.answer("Введите госномер вашего авто (напр. 777AAA01).\nМы пришлем уведомление, если кто-то оставит на вас отзыв!")
    await state.set_state(Form.register_my_plate)

@dp.message(Form.register_my_plate)
async def register_plate(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO subscriptions (user_id, plate) VALUES (?, ?)", (message.from_user.id, plate))
        conn.commit()
        await message.answer(f"✅ Готово! Теперь вы подписаны на уведомления для номера <b>{plate}</b>.", parse_mode="HTML")
    except sqlite3.IntegrityError:
        await message.answer(f"ℹ️ Вы уже подписаны на номер {plate}.")
    finally:
        conn.close()
    await state.clear()

# --- ПОИСК ---
@dp.message(F.text == "🔍 Проверить номер")
async def ask_plate_search(message: types.Message, state: FSMContext):
    await message.answer("Введите госномер авто:")
    await state.set_state(Form.entering_plate_search)

@dp.message(Form.entering_plate_search)
async def search_plate(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("SELECT rating, comment, photo_id FROM reviews WHERE plate = ?", (plate,))
    results = cursor.fetchall()
    conn.close()

    if not results:
        await message.answer(f"По номеру <b>{plate}</b> отзывов пока нет.", parse_mode="HTML")
    else:
        await message.answer(f"📊 Найдено отзывов: {len(results)}")
        for res in results:
            stars = "⭐" * res[0]
            if res[2]:
                await message.answer_photo(res[2], caption=f"{stars}\n{res[1]}", parse_mode="HTML")
            else:
                await message.answer(f"{stars}\n{res[1]}", parse_mode="HTML")
    await state.clear()

# --- ДОБАВЛЕНИЕ ОТЗЫВА И УВЕДОМЛЕНИЕ ---
@dp.message(F.text == "✍️ Оставить отзыв")
async def ask_plate_review(message: types.Message, state: FSMContext):
    await message.answer("Введите госномер автомобиля:")
    await state.set_state(Form.entering_plate_review)

@dp.message(Form.entering_plate_review)
async def process_plate_review(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    await state.update_data(plate=plate)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{i}⭐", callback_data=f"rate_{i}") for i in range(1, 6)]])
    await message.answer(f"Оцените водителя {plate}:", reply_markup=kb)
    await state.set_state(Form.choosing_rating)

@dp.callback_query(F.data.startswith("rate_"))
async def process_rating(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(rating=int(callback.data.split("_")[1]))
    await callback.message.answer("Напишите текст отзыва:")
    await state.set_state(Form.writing_comment)
    await callback.answer()

@dp.message(Form.writing_comment)
async def process_comment(message: types.Message, state: FSMContext):
    await state.update_data(comment=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Пропустить фото")]], resize_keyboard=True)
    await message.answer("Добавьте фото или пропустите:", reply_markup=kb)
    await state.set_state(Form.sending_photo)

@dp.message(Form.sending_photo)
async def process_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id if message.photo else None
    plate = data['plate']
    
    conn = sqlite3.connect('driver_rating.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reviews (plate, rating, comment, photo_id, user_id) VALUES (?, ?, ?, ?, ?)", 
                   (plate, data['rating'], data['comment'], photo_id, message.from_user.id))
    
    # Ищем подписчиков на этот номер
    cursor.execute("SELECT user_id FROM subscriptions WHERE plate = ?", (plate,))
    subscribers = cursor.fetchall()
    conn.commit()
    conn.close()

    # Рассылка уведомлений владельцам
    alert_text = f"❗ <b>Новый отзыв на ваш номер {plate}!</b>\n\n⭐ Оценка: {data['rating']}/5\n💬 Отзыв: {data['comment']}"
    for sub in subscribers:
        try:
            if photo_id:
                await bot.send_photo(sub[0], photo_id, caption=alert_text, parse_mode="HTML")
            else:
                await bot.send_message(sub[0], alert_text, parse_mode="HTML")
        except:
            pass # Если пользователь заблокировал бота

    await message.answer("✅ Отзыв опубликован. Владелец (если он в базе) получит уведомление!", 
                         reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔍 Проверить номер")], [KeyboardButton(text="✍️ Оставить отзыв")]], resize_keyboard=True))
    await state.clear()

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())