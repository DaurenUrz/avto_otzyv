import asyncio
import os
import re
import random
import asyncpg
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand

# --- НАСТРОЙКИ ---
API_TOKEN = '8266217370:AAEFAPTytERhMnwoxa7Rt-AkT8nxGm1km6k' 
ADMIN_ID = 1068233995 
DATABASE_URL = os.getenv('DATABASE_URL') 

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

# --- СОСТОЯНИЯ ---
class Form(StatesGroup):
    entering_plate_search = State()
    entering_plate_review = State()
    choosing_rating = State()
    writing_comment = State()
    sending_geo = State()
    sending_media = State()
    register_my_plate = State()
    payment_proof = State()

class AdminState(StatesGroup):
    waiting_broadcast_text = State()
    waiting_delete_plate = State()
    waiting_user_search = State()

# --- ИНИЦИАЛИЗАЦИЯ БД ---
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    # Таблица отзывов
    await conn.execute('''CREATE TABLE IF NOT EXISTS reviews (
        id SERIAL PRIMARY KEY, plate TEXT, rating INTEGER, 
        comment TEXT, photo_id TEXT, video_id TEXT, 
        latitude DOUBLE PRECISION, longitude DOUBLE PRECISION, user_id BIGINT)''')
    # Таблица подписок
    await conn.execute('''CREATE TABLE IF NOT EXISTS subscriptions (
        user_id BIGINT, plate TEXT, PRIMARY KEY (user_id, plate))''')
    # Таблица покупок
    await conn.execute('''CREATE TABLE IF NOT EXISTS purchases (
        user_id BIGINT PRIMARY KEY, access_granted INTEGER DEFAULT 0, multi_car INTEGER DEFAULT 0)''')
    # Таблица пользователей (ДЛЯ ТЕГОВ)
    await conn.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY, username TEXT, full_name TEXT, joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    await conn.close()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def clean_plate(plate):
    return re.sub(r'[^A-Z0-9]', '', plate.upper())

def get_region_name(plate):
    region_code = plate[-2:]
    return KZ_REGIONS.get(region_code, "Регион не определен")

async def get_user_status(user_id):
    conn = await asyncpg.connect(DATABASE_URL)
    res = await conn.fetchrow("SELECT access_granted, multi_car FROM purchases WHERE user_id = $1", user_id)
    await conn.close()
    return (res['access_granted'], res['multi_car']) if res else (0, 0)

async def set_main_menu(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="search", description="Проверить номер"),
        BotCommand(command="review", description="Оставить отзыв"),
        BotCommand(command="my_cars", description="Мой гараж 🚗"),
        BotCommand(command="admin", description="Админка")
    ]
    await bot.set_my_commands(commands)

# --- ОБРАБОТЧИКИ МЕНЮ ---
@dp.message(Command("start"))
async def start(message: types.Message):
    # СОХРАНЯЕМ ДАННЫЕ ПОЛЬЗОВАТЕЛЯ (ТЕГ И ИМЯ)
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('''INSERT INTO users (user_id, username, full_name) 
                          VALUES ($1, $2, $3) 
                          ON CONFLICT (user_id) DO UPDATE SET username = $2, full_name = $3''', 
                       message.from_user.id, message.from_user.username, message.from_user.full_name)
    await conn.close()

    kb = [[KeyboardButton(text="🔍 Проверить номер"), KeyboardButton(text="✍️ Оставить отзыв")],
          [KeyboardButton(text="🚗 Мои авто"), KeyboardButton(text="🔔 Подписаться")]]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer(f"🇰🇿 <b>Driver Rating KZ Pro</b>\nСалам, {message.from_user.first_name}! База данных активна.", reply_markup=keyboard, parse_mode="HTML")

# --- АДМИН-ПАНЕЛЬ (НОВАЯ ВЕРСИЯ) ---
@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin_panel(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"), InlineKeyboardButton(text="🔍 Найти юзера", callback_data="admin_find_user")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🗑 Удалить номер", callback_data="admin_del_plate")]
    ])
    await message.answer("🛠 <b>Панель управления</b>", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "admin_stats", F.from_user.id == ADMIN_ID)
async def admin_stats_handler(callback: types.CallbackQuery):
    conn = await asyncpg.connect(DATABASE_URL)
    u_count = await conn.fetchval("SELECT COUNT(*) FROM users")
    revs = await conn.fetchval("SELECT COUNT(*) FROM reviews")
    sales = await conn.fetchval("SELECT COUNT(*) FROM purchases WHERE access_granted = 1 OR multi_car = 1")
    await conn.close()
    await callback.message.answer(f"📊 <b>Цифры:</b>\n\n👥 Юзеров в базе: {u_count}\n📝 Отзывов: {revs}\n💰 Оплат: {sales}", parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_find_user", F.from_user.id == ADMIN_ID)
async def admin_find_user_init(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите @username или ID пользователя:")
    await state.set_state(AdminState.waiting_user_search)
    await callback.answer()

@dp.message(AdminState.waiting_user_search)
async def perform_user_search(message: types.Message, state: FSMContext):
    search_query = message.text.replace("@", "").strip()
    conn = await asyncpg.connect(DATABASE_URL)
    if search_query.isdigit():
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", int(search_query))
    else:
        user = await conn.fetchrow("SELECT * FROM users WHERE username ILIKE $1", search_query)
    await conn.close()

    if user:
        text = (f"👤 <b>Найден пользователь:</b>\n\n"
                f"ID: <code>{user['user_id']}</code>\n"
                f"Тег: @{user['username'] if user['username'] else 'нет'}\n"
                f"Имя: {user['full_name']}\n"
                f"Дата входа: {user['joined_at'].strftime('%d.%m.%Y')}")
        await message.answer(text, parse_mode="HTML")
    else:
        await message.answer("❌ Пользователь не найден в базе.")
    await state.clear()

@dp.message(AdminState.waiting_broadcast_text)
async def perform_broadcast(message: types.Message, state: FSMContext):
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("SELECT user_id FROM users")
    await conn.close()
    success = 0
    for row in rows:
        try:
            await bot.send_message(row['user_id'], message.text)
            success += 1
            await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"✅ Рассылка завершена!\nПолучили: {success} чел.")
    await state.clear()

# --- ПЛАТЕЖИ С ТЕГАМИ В АДМИНКЕ ---
@dp.message(Form.payment_proof, F.photo)
async def pay_check(message: types.Message, state: FSMContext):
    data = await state.get_data()
    pt = data.get('ptype', 'full')
    user_tag = f"@{message.from_user.username}" if message.from_user.username else "нет тега"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"conf_{message.from_user.id}_{pt}")]])
    
    caption = (f"💳 <b>Новый чек!</b>\n\n"
               f"Тип: {pt.upper()}\n"
               f"От: {message.from_user.full_name} ({user_tag})\n"
               f"ID: <code>{message.from_user.id}</code>")
    
    await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption, reply_markup=kb, parse_mode="HTML")
    await message.answer("⏳ Чек принят. Ожидайте подтверждения.")
    await state.clear()

# --- ВСЯ ОСТАЛЬНАЯ ЛОГИКА (БЕЗ ИЗМЕНЕНИЙ) ---
@dp.callback_query(F.data == "admin_broadcast", F.from_user.id == ADMIN_ID)
async def admin_broadcast_init(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите текст рассылки:")
    await state.set_state(AdminState.waiting_broadcast_text)
    await callback.answer()

@dp.callback_query(F.data == "admin_del_plate", F.from_user.id == ADMIN_ID)
async def admin_del_init(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите номер для удаления:")
    await state.set_state(AdminState.waiting_delete_plate)
    await callback.answer()

@dp.message(AdminState.waiting_delete_plate)
async def perform_delete(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("DELETE FROM reviews WHERE plate = $1", plate)
    await conn.close()
    await message.answer(f"🗑 {plate} очищен.")
    await state.clear()

@dp.message(F.text == "🔍 Проверить номер")
@dp.message(Command("search"))
async def search_start(message: types.Message, state: FSMContext):
    await message.answer("Введите госномер:")
    await state.set_state(Form.entering_plate_search)

@dp.message(Form.entering_plate_search)
async def search_finish(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    access, _ = await get_user_status(message.from_user.id)
    region = get_region_name(plate)
    conn = await asyncpg.connect(DATABASE_URL)
    results = await conn.fetch("SELECT rating, comment, photo_id, video_id, latitude, longitude FROM reviews WHERE plate = $1", plate)
    await conn.close()
    if not results:
        await message.answer(f"По номеру {plate} ({region}) отзывов нет.")
    else:
        avg = sum(r['rating'] for r in results) / len(results)
        header = f"🚘 <b>{plate}</b> ({region})\n📊 Рейтинг: {'⭐'*int(round(avg))} ({avg:.1f}/5)\n💬 Отзывов: {len(results)}"
        kb_share = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📲 Поделиться", callback_data=f"share_{plate}")]])
        await message.answer(header, reply_markup=kb_share, parse_mode="HTML")
        for i, res in enumerate(results):
            if i > 0 and access == 0:
                kb_p = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔓 Открыть всё (500 ₸)", callback_data="buy_full")]])
                await message.answer(f"🔒 Скрыто еще {len(results)-1} отзывов.", reply_markup=kb_p)
                break
            cap = f"<b>Отзыв #{i+1}</b>: {'⭐'*res['rating']}\n<i>{res['comment']}</i>"
            kb_m = None
            if res['latitude']:
                kb_m = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📍 На карте", url=f"https://www.google.com/maps?q={res['latitude']},{res['longitude']}")]])
            if res['video_id']: await message.answer_video(res['video_id'], caption=cap, reply_markup=kb_m, parse_mode="HTML")
            elif res['photo_id']: await message.answer_photo(res['photo_id'], caption=cap, reply_markup=kb_m, parse_mode="HTML")
            else: await message.answer(cap, reply_markup=kb_m, parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data.startswith("buy_"))
async def pay_init(callback: types.CallbackQuery, state: FSMContext):
    ptype = callback.data.split("_")[1]
    await state.update_data(ptype=ptype)
    price = "500 ₸" if ptype == "full" else "1000 ₸"
    await callback.message.answer(f"💳 Оплата {ptype.upper()} ({price})\nKaspi: <code>+77770000000</code>\nПришлите фото чека:")
    await state.set_state(Form.payment_proof)
    await callback.answer()

@dp.callback_query(F.data.startswith("conf_"))
async def pay_confirm(callback: types.CallbackQuery):
    _, uid, pt = callback.data.split("_")
    uid = int(uid)
    conn = await asyncpg.connect(DATABASE_URL)
    if pt == "full":
        await conn.execute("INSERT INTO purchases (user_id, access_granted) VALUES ($1, 1) ON CONFLICT (user_id) DO UPDATE SET access_granted = 1", uid)
        msg = "💎 Доступ открыт! Введите номер для проверки:"
        next_state = Form.entering_plate_search
    else:
        await conn.execute("INSERT INTO purchases (user_id, multi_car) VALUES ($1, 1) ON CONFLICT (user_id) DO UPDATE SET multi_car = 1", uid)
        msg = "🚀 Multi-Car активен! Введите номер для гаража:"
        next_state = Form.register_my_plate
    await conn.close()
    u_state = dp.fsm.resolve_context(bot, uid, uid)
    await u_state.set_state(next_state)
    await bot.send_message(uid, msg, parse_mode="HTML")
    await callback.message.edit_caption(caption="✅ ПОДТВЕРЖДЕНО")

@dp.message(F.text == "✍️ Оставить отзыв")
async def review_start(message: types.Message, state: FSMContext):
    await message.answer("Введите госномер:")
    await state.set_state(Form.entering_plate_review)

@dp.message(Form.entering_plate_review)
async def review_plate(message: types.Message, state: FSMContext):
    await state.update_data(plate=clean_plate(message.text))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{i}⭐", callback_data=f"rate_{i}") for i in range(1, 6)]])
    await message.answer("Оценка:", reply_markup=kb)
    await state.set_state(Form.choosing_rating)

@dp.callback_query(F.data.startswith("rate_"))
async def review_rate(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(rating=int(callback.data.split("_")[1]))
    await callback.message.answer("Комментарий:")
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
    await message.answer("Фото/видео или 'Пропустить':", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Пропустить")]], resize_keyboard=True))
    await state.set_state(Form.sending_media)

@dp.message(Form.sending_media)
async def review_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    p_id = message.photo[-1].file_id if message.photo else None
    v_id = message.video.file_id if message.video else None
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("INSERT INTO reviews (plate, rating, comment, photo_id, video_id, latitude, longitude, user_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                       data['plate'], data['rating'], data['comment'], p_id, v_id, data.get('lat'), data.get('lon'), message.from_user.id)
    subs = await conn.fetch("SELECT user_id FROM subscriptions WHERE plate = $1", data['plate'])
    await conn.close()
    for s in subs:
        try: await bot.send_message(s['user_id'], f"❗ Новый отзыв на ваш авто {data['plate']}!")
        except: pass
    await message.answer("✅ Опубликовано!", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔍 Проверить номер")]], resize_keyboard=True))
    await state.clear()

@dp.message(F.text == "🚗 Мои авто")
async def my_cars(message: types.Message):
    conn = await asyncpg.connect(DATABASE_URL)
    cars = await conn.fetch("SELECT plate FROM subscriptions WHERE user_id = $1", message.from_user.id)
    await conn.close()
    if not cars: await message.answer("Гараж пуст.")
    else: await message.answer("🚘 <b>Ваши авто:</b>\n\n" + "\n".join([f"• <code>{c['plate']}</code>" for c in cars]), parse_mode="HTML")

@dp.message(F.text == "🔔 Подписаться")
async def sub_check(message: types.Message, state: FSMContext):
    conn = await asyncpg.connect(DATABASE_URL)
    count = await conn.fetchval("SELECT COUNT(*) FROM subscriptions WHERE user_id = $1", message.from_user.id)
    await conn.close()
    _, multi = await get_user_status(message.from_user.id)
    if count >= 1 and multi == 0:
        await message.answer("⚠️ Лимит: 1 авто. Купите Multi-Car.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💎 Купить", callback_data="buy_multi")]]))
    else:
        await message.answer("Введите госномер:")
        await state.set_state(Form.register_my_plate)

@dp.message(Form.register_my_plate)
async def sub_finish(message: types.Message, state: FSMContext):
    plate = clean_plate(message.text)
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("INSERT INTO subscriptions (user_id, plate) VALUES ($1, $2)", message.from_user.id, plate)
        await message.answer(f"✅ Подписаны на {plate}.")
    except: await message.answer("Уже есть в гараже.")
    finally: await conn.close()
    await state.clear()

@dp.callback_query(F.data.startswith("share_"))
async def share_handler(callback: types.CallbackQuery):
    plate = callback.data.split("_")[1]
    conn = await asyncpg.connect(DATABASE_URL)
    ratings = await conn.fetch("SELECT rating FROM reviews WHERE plate = $1", plate)
    await conn.close()
    if not ratings: return await callback.answer("Нет отзывов")
    avg = sum(r['rating'] for r in ratings) / len(ratings)
    text = f"🚗 <b>DRIVER CARD: {plate}</b>\n📊 Рейтинг: {'⭐'*int(round(avg))} ({avg:.1f}/5)\n\n👉 @{(await bot.get_me()).username}"
    await callback.message.answer(f"📸 Сделайте скриншот:\n\n{text}", parse_mode="HTML")
    await callback.answer()

async def main():
    await init_db()
    await set_main_menu(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())