import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from typing import Optional, Dict, List
from enum import Enum
from contextlib import contextmanager

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
import aiohttp
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Константы
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения")

USDT_TO_RUB = 95  # Курс: 1 USDT = 95 RUB

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== Классы состояний FSM ====================

class SetupStates(StatesGroup):
    waiting_for_bot_name = State()
    waiting_for_currency = State()
    waiting_for_admin_id = State()
    waiting_for_crypto_token = State()

class AdminStates(StatesGroup):
    waiting_for_newsletter_text = State()
    waiting_for_category_name = State()
    waiting_for_category_description = State()
    waiting_for_product_category = State()
    waiting_for_product_name = State()
    waiting_for_product_description = State()
    waiting_for_product_price = State()
    waiting_for_product_photo = State()
    waiting_for_product_content = State()

# ==================== Модели данных ====================

class Currency(Enum):
    RUB = "₽"
    USD = "$"

# ==================== Работа с базой данных ====================

class Database:
    def __init__(self, db_path='shop_bot.db'):
        self.db_path = db_path
        self.init_db()
    
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица настроек
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    bot_name TEXT NOT NULL DEFAULT 'Мой магазин',
                    currency TEXT NOT NULL DEFAULT 'RUB',
                    admin_id INTEGER,
                    crypto_token TEXT,
                    is_setup_complete BOOLEAN NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица категорий
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица товаров
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    price_rub REAL NOT NULL,
                    price_usd REAL NOT NULL,
                    photo_file_id TEXT,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE CASCADE
                )
            ''')
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT NOT NULL,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_purchases INTEGER DEFAULT 0,
                    total_spent_rub REAL DEFAULT 0
                )
            ''')
            
            # Таблица покупок
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    amount_rub REAL NOT NULL,
                    amount_usd REAL NOT NULL,
                    crypto_payment_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (product_id) REFERENCES products (id)
                )
            ''')
            
            # Создаем запись настроек, если её нет
            cursor.execute('SELECT * FROM settings WHERE id = 1')
            if not cursor.fetchone():
                cursor.execute('''
                    INSERT INTO settings (id, bot_name, currency, admin_id, crypto_token, is_setup_complete)
                    VALUES (1, ?, ?, ?, ?, ?)
                ''', (
                    'Мой магазин',
                    'RUB',
                    None,  # admin_id не задан при первом запуске
                    None,  # crypto_token не задан при первом запуске
                    0      # setup не завершен
                ))
    
    # Методы для работы с настройками
    def get_settings(self) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM settings WHERE id = 1')
            row = cursor.fetchone()
            return dict(row) if row else {}
    
    def update_settings(self, **kwargs):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            fields = []
            values = []
            for key, value in kwargs.items():
                fields.append(f"{key} = ?")
                values.append(value)
            values.append(1)  # WHERE id = 1
            cursor.execute(f'''
                UPDATE settings 
                SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', values)
    
    def complete_setup(self):
        self.update_settings(is_setup_complete=1)
    
    def is_setup_complete(self) -> bool:
        settings = self.get_settings()
        return bool(settings.get('is_setup_complete', 0))
    
    def is_admin(self, telegram_id: int) -> bool:
        """Проверяет, является ли пользователь администратором"""
        settings = self.get_settings()
        admin_id = settings.get('admin_id')
        return admin_id is not None and admin_id == telegram_id
    
    # Методы для работы с категориями
    def add_category(self, name: str, description: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO categories (name, description) VALUES (?, ?)',
                (name, description)
            )
            return cursor.lastrowid
    
    def get_categories(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM categories ORDER BY name')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_category(self, category_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM categories WHERE id = ?', (category_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    # Методы для работы с товарами
    def add_product(self, category_id: int, name: str, description: str, 
                   price_rub: float, content: str, photo_file_id: Optional[str] = None) -> int:
        price_usd = round(price_rub / USDT_TO_RUB, 2)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO products (category_id, name, description, price_rub, price_usd, content, photo_file_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (category_id, name, description, price_rub, price_usd, content, photo_file_id))
            return cursor.lastrowid
    
    def get_products_by_category(self, category_id: int) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM products WHERE category_id = ? ORDER BY name', (category_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_product(self, product_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    # Методы для работы с пользователями
    def register_user(self, telegram_id: int, username: Optional[str], first_name: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO users (telegram_id, username, first_name)
                VALUES (?, ?, ?)
            ''', (telegram_id, username, first_name))
            
            cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            row = cursor.fetchone()
            return row['id'] if row else None
    
    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_user_stats(self, user_id: int, amount_rub: float):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET total_purchases = total_purchases + 1,
                    total_spent_rub = total_spent_rub + ?
                WHERE id = ?
            ''', (amount_rub, user_id))
    
    def get_all_users(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users ORDER BY registered_at DESC')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_users_count(self) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM users')
            return cursor.fetchone()['count']
    
    # Методы для работы с покупками
    def create_purchase(self, user_id: int, product_id: int, amount_rub: float, 
                       amount_usd: float, crypto_payment_id: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO purchases (user_id, product_id, amount_rub, amount_usd, crypto_payment_id, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, product_id, amount_rub, amount_usd, crypto_payment_id, 'pending'))
            return cursor.lastrowid
    
    def complete_purchase(self, purchase_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE purchases 
                SET status = 'completed', completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (purchase_id,))
    
    def get_purchase(self, purchase_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM purchases WHERE id = ?', (purchase_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_purchases_by_user(self, user_id: int) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p.*, pr.name as product_name 
                FROM purchases p
                JOIN products pr ON p.product_id = pr.id
                WHERE p.user_id = ? AND p.status = 'completed'
                ORDER BY p.created_at DESC
            ''', (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_statistics(self) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Общее количество пользователей
            cursor.execute('SELECT COUNT(*) as count FROM users')
            users_count = cursor.fetchone()['count']
            
            # Общее количество покупок
            cursor.execute("SELECT COUNT(*) as count FROM purchases WHERE status = 'completed'")
            purchases_count = cursor.fetchone()['count']
            
            # Общий оборот
            cursor.execute("SELECT SUM(amount_rub) as total FROM purchases WHERE status = 'completed'")
            total_revenue = cursor.fetchone()['total'] or 0
            
            # Количество товаров
            cursor.execute('SELECT COUNT(*) as count FROM products')
            products_count = cursor.fetchone()['count']
            
            # Количество категорий
            cursor.execute('SELECT COUNT(*) as count FROM categories')
            categories_count = cursor.fetchone()['count']
            
            return {
                'users_count': users_count,
                'purchases_count': purchases_count,
                'total_revenue': total_revenue,
                'products_count': products_count,
                'categories_count': categories_count
            }

# Инициализация базы данных
db = Database()

# ==================== Клавиатуры ====================

def get_main_keyboard(telegram_id: int) -> ReplyKeyboardMarkup:
    """Создает главное меню в зависимости от статуса пользователя"""
    settings = db.get_settings()
    is_admin = db.is_admin(telegram_id)
    is_setup_complete = settings.get('is_setup_complete', False)
    
    builder = ReplyKeyboardBuilder()
    
    # Основные кнопки для всех
    builder.row(KeyboardButton(text="🛒 Купить товар"))
    builder.row(KeyboardButton(text="📦 Наличие товара"), KeyboardButton(text="👤 Профиль"))
    builder.row(KeyboardButton(text="ℹ О нас"))
    
    # Кнопка настройки для первого пользователя, если настройки не завершены
    if not is_setup_complete:
        # Если админ еще не назначен, первый пользователь становится кандидатом
        if settings.get('admin_id') is None:
            builder.row(KeyboardButton(text="⚙ Стать администратором"))
        # Если пользователь является админом и настройки не завершены
        elif is_admin:
            builder.row(KeyboardButton(text="⚙ Настроить бота"))
    
    # Кнопка админ-панели для админа в рабочем режиме
    if is_admin and is_setup_complete:
        builder.row(KeyboardButton(text="🔧 Админ панель"))
    
    return builder.as_markup(resize_keyboard=True)

def get_admin_panel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📊 Статистика"))
    builder.row(KeyboardButton(text="📨 Рассылка"))
    builder.row(KeyboardButton(text="📂 Добавление категорий"))
    builder.row(KeyboardButton(text="📦 Добавление товаров"))
    builder.row(KeyboardButton(text="◀ Назад в главное меню"))
    return builder.as_markup(resize_keyboard=True)

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True)

def get_currency_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🇷🇺 Рубли (₽)", callback_data="currency_rub"),
        InlineKeyboardButton(text="🇺🇸 Доллары ($)", callback_data="currency_usd")
    )
    return builder.as_markup()

def get_categories_keyboard() -> InlineKeyboardMarkup:
    categories = db.get_categories()
    builder = InlineKeyboardBuilder()
    
    for category in categories:
        builder.row(InlineKeyboardButton(
            text=category['name'],
            callback_data=f"category_{category['id']}"
        ))
    
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_products_keyboard(category_id: int) -> InlineKeyboardMarkup:
    products = db.get_products_by_category(category_id)
    settings = db.get_settings()
    currency_symbol = Currency[settings['currency']].value
    builder = InlineKeyboardBuilder()
    
    for product in products:
        price = product['price_rub'] if settings['currency'] == 'RUB' else product['price_usd']
        builder.row(InlineKeyboardButton(
            text=f"{product['name']} - {price} {currency_symbol}",
            callback_data=f"product_{product['id']}"
        ))
    
    builder.row(InlineKeyboardButton(text="◀ Назад к категориям", callback_data="back_to_categories"))
    return builder.as_markup()

def get_payment_keyboard(payment_url: str, purchase_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Оплатить", url=payment_url))
    builder.row(InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_payment_{purchase_id}"))
    builder.row(InlineKeyboardButton(text="◀ Отмена", callback_data="cancel_payment"))
    return builder.as_markup()

def get_back_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back"))
    return builder.as_markup()

# ==================== Интеграция с Crypto Bot ====================

class CryptoBotAPI:
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://pay.crypt.bot/api"
    
    async def create_invoice(self, amount_usd: float, description: str) -> Optional[Dict]:
        """Создание счета в Crypto Bot"""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Crypto-Pay-API-Token": self.token,
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "asset": "USDT",
                    "amount": str(amount_usd),
                    "description": description,
                    "paid_btn_name": "callback",
                    "paid_btn_url": "https://t.me/your_bot",  # Замените на ссылку на бота
                    "payload": "shop_payment"
                }
                
                async with session.post(
                    f"{self.base_url}/createInvoice",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('ok'):
                            return data['result']
                    return None
        except Exception as e:
            logger.error(f"Ошибка при создании инвойса Crypto Bot: {e}")
            return None
    
    async def check_invoice_status(self, invoice_id: int) -> Optional[str]:
        """Проверка статуса счета"""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Crypto-Pay-API-Token": self.token}
                
                async with session.get(
                    f"{self.base_url}/getInvoices",
                    headers=headers,
                    params={"invoice_ids": str(invoice_id)}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('ok') and data.get('result', {}).get('items'):
                            return data['result']['items'][0].get('status')
                    return None
        except Exception as e:
            logger.error(f"Ошибка при проверке статуса инвойса: {e}")
            return None

# ==================== Обработчики команд ====================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    # Регистрируем пользователя
    db.register_user(user_id, username, first_name)
    
    # Получаем настройки
    settings = db.get_settings()
    
    # Отправляем приветственное сообщение
    welcome_text = f"👋 Добро пожаловать в {settings.get('bot_name', 'магазин')}!\n\n"
    
    # Если админ еще не назначен, информируем об этом
    if settings.get('admin_id') is None:
        welcome_text += "⚡ Бот еще не настроен. Нажмите кнопку 'Стать администратором' для начала настройки."
    elif not settings.get('is_setup_complete'):
        welcome_text += "⚡ Бот находится в режиме настройки. Используйте кнопку 'Настроить бота' для продолжения."
    else:
        welcome_text += "Используйте кнопки ниже для навигации."
    
    await message.answer(
        welcome_text,
        reply_markup=get_main_keyboard(user_id)
    )

@dp.message(F.text == "⚙ Стать администратором")
async def become_admin(message: Message):
    """Первый пользователь становится администратором"""
    settings = db.get_settings()
    
    # Проверяем, не назначен ли уже администратор
    if settings.get('admin_id') is not None:
        await message.answer(
            "❌ Администратор уже назначен.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    # Назначаем текущего пользователя администратором
    db.update_settings(admin_id=message.from_user.id)
    
    await message.answer(
        "✅ Вы назначены администратором!\n\n"
        "Теперь нажмите кнопку '⚙ Настроить бота' для продолжения настройки.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(F.text == "⚙ Настроить бота")
async def setup_bot(message: Message, state: FSMContext):
    """Начало настройки бота"""
    if not db.is_admin(message.from_user.id):
        await message.answer("У вас нет прав для настройки бота.")
        return
    
    settings = db.get_settings()
    
    # Показываем меню настройки
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏ Изменить имя бота", callback_data="setup_name"))
    builder.row(InlineKeyboardButton(text="💱 Изменить валюту", callback_data="setup_currency"))
    builder.row(InlineKeyboardButton(text="🆔 Изменить admin id", callback_data="setup_admin_id"))
    builder.row(InlineKeyboardButton(text="🔑 Изменить Crypto Bot API", callback_data="setup_crypto_token"))
    
    # Показываем кнопку запуска только если все необходимые настройки заполнены
    if settings.get('admin_id') and settings.get('crypto_token'):
        builder.row(InlineKeyboardButton(text="▶ Запустить бота", callback_data="setup_complete"))
    
    await message.answer(
        "⚙ Меню настройки бота:\n\n"
        "Выберите, что хотите изменить:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("setup_"))
async def setup_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка действий в меню настройки"""
    if not db.is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав для настройки бота.")
        return
    
    action = callback.data.replace("setup_", "")
    
    if action == "name":
        await callback.message.edit_text(
            "✏ Введите новое имя бота:",
            reply_markup=get_back_keyboard()
        )
        await state.set_state(SetupStates.waiting_for_bot_name)
    
    elif action == "currency":
        await callback.message.edit_text(
            "💱 Выберите валюту по умолчанию:",
            reply_markup=get_currency_keyboard()
        )
        await state.set_state(SetupStates.waiting_for_currency)
    
    elif action == "admin_id":
        await callback.message.edit_text(
            "🆔 Введите новый admin ID (числовой ID пользователя Telegram):",
            reply_markup=get_back_keyboard()
        )
        await state.set_state(SetupStates.waiting_for_admin_id)
    
    elif action == "crypto_token":
        await callback.message.edit_text(
            "🔑 Введите новый Crypto Bot API токен:\n\n"
            "Получить можно у @CryptoBot -> Crypto Pay -> API Token",
            reply_markup=get_back_keyboard()
        )
        await state.set_state(SetupStates.waiting_for_crypto_token)
    
    elif action == "complete":
        # Завершение настройки
        db.complete_setup()
        
        await callback.message.edit_text(
            "✅ Настройка завершена! Бот запущен в рабочем режиме."
        )
        await callback.message.answer(
            "Главное меню:",
            reply_markup=get_main_keyboard(callback.from_user.id)
        )
    
    await callback.answer()

@dp.message(SetupStates.waiting_for_bot_name)
async def process_bot_name(message: Message, state: FSMContext):
    """Обработка ввода имени бота"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Настройка отменена.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    # Сохраняем имя бота
    db.update_settings(bot_name=message.text)
    
    await state.clear()
    await message.answer(
        f"✅ Имя бота изменено на: {message.text}",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.callback_query(SetupStates.waiting_for_currency, F.data.startswith("currency_"))
async def process_currency(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора валюты"""
    currency = callback.data.replace("currency_", "").upper()
    
    # Сохраняем валюту
    db.update_settings(currency=currency)
    
    await state.clear()
    await callback.message.edit_text(
        f"✅ Валюта изменена на: {'Рубли (₽)' if currency == 'RUB' else 'Доллары ($)'}"
    )
    await callback.answer()

@dp.message(SetupStates.waiting_for_admin_id)
async def process_admin_id(message: Message, state: FSMContext):
    """Обработка ввода admin ID"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Настройка отменена.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    # Проверяем, что введено число
    if not message.text.isdigit():
        await message.answer(
            "❌ Ошибка: admin ID должен быть числом. Попробуйте снова:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    admin_id = int(message.text)
    
    # Сохраняем admin ID
    db.update_settings(admin_id=admin_id)
    
    await state.clear()
    await message.answer(
        f"✅ Admin ID изменен на: {admin_id}",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(SetupStates.waiting_for_crypto_token)
async def process_crypto_token(message: Message, state: FSMContext):
    """Обработка ввода Crypto Bot токена"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Настройка отменена.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    # Простая проверка формата токена (обычно это длинная строка)
    if len(message.text) < 10:
        await message.answer(
            "❌ Ошибка: неверный формат токена. Попробуйте снова:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Сохраняем токен
    db.update_settings(crypto_token=message.text)
    
    await state.clear()
    await message.answer(
        "✅ Crypto Bot API токен сохранен.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(F.text == "🛒 Купить товар")
async def buy_product(message: Message):
    """Покупка товара - показ категорий"""
    settings = db.get_settings()
    
    # Проверяем, завершена ли настройка
    if not settings.get('is_setup_complete'):
        await message.answer(
            "❌ Магазин еще не настроен. Дождитесь завершения настройки администратором."
        )
        return
    
    categories = db.get_categories()
    
    if not categories:
        await message.answer(
            "📭 В магазине пока нет товаров."
        )
        return
    
    await message.answer(
        "Выберите категорию:",
        reply_markup=get_categories_keyboard()
    )

@dp.callback_query(F.data.startswith("category_"))
async def show_category_products(callback: CallbackQuery):
    """Показ товаров в категории"""
    category_id = int(callback.data.replace("category_", ""))
    category = db.get_category(category_id)
    products = db.get_products_by_category(category_id)
    
    if not products:
        await callback.message.edit_text(
            f"📭 В категории '{category['name']}' пока нет товаров.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    await callback.message.edit_text(
        f"📦 Категория: {category['name']}\n\n"
        f"{category['description']}\n\n"
        "Выберите товар:",
        reply_markup=get_products_keyboard(category_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("product_"))
async def show_product_details(callback: CallbackQuery):
    """Показ деталей товара и предложение оплаты"""
    product_id = int(callback.data.replace("product_", ""))
    product = db.get_product(product_id)
    settings = db.get_settings()
    
    if not product:
        await callback.message.edit_text(
            "❌ Товар не найден.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    # Формируем сообщение с деталями товара
    currency_symbol = Currency[settings['currency']].value
    price = product['price_rub'] if settings['currency'] == 'RUB' else product['price_usd']
    
    message_text = (
        f"📦 {product['name']}\n\n"
        f"{product['description']}\n\n"
        f"💰 Цена: {price} {currency_symbol}\n\n"
        "Хотите купить этот товар?"
    )
    
    # Клавиатура с кнопкой покупки
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Купить", callback_data=f"buy_{product_id}"))
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data=f"category_{product['category_id']}"))
    
    # Если есть фото, отправляем с фото
    if product['photo_file_id']:
        try:
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=product['photo_file_id'],
                caption=message_text,
                reply_markup=builder.as_markup()
            )
        except:
            await callback.message.edit_text(
                message_text,
                reply_markup=builder.as_markup()
            )
    else:
        await callback.message.edit_text(
            message_text,
            reply_markup=builder.as_markup()
        )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_"))
async def process_purchase(callback: CallbackQuery):
    """Обработка покупки - создание счета в Crypto Bot"""
    product_id = int(callback.data.replace("buy_", ""))
    product = db.get_product(product_id)
    settings = db.get_settings()
    
    if not settings.get('crypto_token'):
        await callback.message.edit_text(
            "❌ Ошибка: платежная система не настроена. Обратитесь к администратору.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    # Получаем пользователя
    user = db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        user_id = db.register_user(
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name
        )
        user = {'id': user_id}
    
    # Создаем счет в Crypto Bot
    crypto_api = CryptoBotAPI(settings['crypto_token'])
    invoice = await crypto_api.create_invoice(
        amount_usd=product['price_usd'],
        description=f"Покупка: {product['name']}"
    )
    
    if not invoice:
        await callback.message.edit_text(
            "❌ Ошибка при создании счета. Попробуйте позже.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    # Сохраняем покупку в БД
    purchase_id = db.create_purchase(
        user_id=user['id'],
        product_id=product_id,
        amount_rub=product['price_rub'],
        amount_usd=product['price_usd'],
        crypto_payment_id=str(invoice['invoice_id'])
    )
    
    # Отправляем сообщение с кнопкой оплаты
    currency_symbol = Currency[settings['currency']].value
    price = product['price_rub'] if settings['currency'] == 'RUB' else product['price_usd']
    
    await callback.message.edit_text(
        f"🧾 Счет на оплату:\n\n"
        f"Товар: {product['name']}\n"
        f"Сумма: {price} {currency_symbol} "
        f"({product['price_usd']} USDT)\n\n"
        f"Нажмите кнопку ниже для оплаты через @CryptoBot",
        reply_markup=get_payment_keyboard(invoice['pay_url'], purchase_id)
    )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: CallbackQuery):
    """Проверка статуса оплаты"""
    purchase_id = int(callback.data.replace("check_payment_", ""))
    purchase = db.get_purchase(purchase_id)
    
    if not purchase:
        await callback.message.edit_text(
            "❌ Платеж не найден.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    if purchase['status'] == 'completed':
        # Платеж уже подтвержден
        await deliver_product(callback.message, purchase)
        await callback.answer()
        return
    
    # Проверяем статус в Crypto Bot
    settings = db.get_settings()
    crypto_api = CryptoBotAPI(settings['crypto_token'])
    status = await crypto_api.check_invoice_status(int(purchase['crypto_payment_id']))
    
    if status == 'paid':
        # Платеж подтвержден
        db.complete_purchase(purchase_id)
        db.update_user_stats(purchase['user_id'], purchase['amount_rub'])
        
        await deliver_product(callback.message, purchase)
    elif status == 'active':
        await callback.message.edit_text(
            "⏳ Счет ожидает оплаты. После оплаты нажмите кнопку проверки.",
            reply_markup=get_payment_keyboard(
                f"https://t.me/CryptoBot?start={purchase['crypto_payment_id']}",
                purchase_id
            )
        )
    else:
        await callback.message.edit_text(
            "❌ Платеж не найден или истек. Попробуйте создать новый заказ.",
            reply_markup=get_back_keyboard()
        )
    
    await callback.answer()

async def deliver_product(message: types.Message, purchase: Dict):
    """Доставка товара после оплаты"""
    product = db.get_product(purchase['product_id'])
    
    if not product:
        await message.answer(
            "❌ Ошибка: товар не найден. Обратитесь к администратору."
        )
        return
    
    await message.answer(
        f"✅ Оплата получена!\n\n"
        f"🎁 Ваш товар:\n\n{product['content']}"
    )
    
    # Возвращаем в главное меню
    await message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(message.chat.id)
    )

@dp.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery):
    """Отмена платежа"""
    await callback.message.edit_text(
        "❌ Платеж отменен."
    )
    
    # Возвращаем в главное меню
    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.message(F.text == "📦 Наличие товара")
async def check_stock(message: Message):
    """Проверка наличия товаров"""
    settings = db.get_settings()
    
    # Проверяем, завершена ли настройка
    if not settings.get('is_setup_complete'):
        await message.answer(
            "❌ Магазин еще не настроен. Дождитесь завершения настройки администратором."
        )
        return
    
    products = []
    categories = db.get_categories()
    
    for category in categories:
        category_products = db.get_products_by_category(category['id'])
        if category_products:
            products.extend(category_products)
    
    if not products:
        await message.answer(
            "📭 В магазине пока нет товаров."
        )
        return
    
    currency_symbol = Currency[settings['currency']].value
    
    message_text = "📦 Наличие товаров:\n\n"
    
    for category in categories:
        category_products = db.get_products_by_category(category['id'])
        if category_products:
            message_text += f"📁 {category['name']}:\n"
            for product in category_products:
                price = product['price_rub'] if settings['currency'] == 'RUB' else product['price_usd']
                message_text += f"  • {product['name']} - {price} {currency_symbol}\n"
            message_text += "\n"
    
    await message.answer(message_text)

@dp.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    """Показ профиля пользователя"""
    user = db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        await message.answer(
            "Профиль не найден. Начните с команды /start"
        )
        return
    
    # Получаем историю покупок
    purchases = db.get_purchases_by_user(user['id'])
    
    profile_text = (
        f"👤 Ваш профиль:\n\n"
        f"🆔 ID: {user['telegram_id']}\n"
        f"📝 Имя: {user['first_name']}\n"
        f"📅 Зарегистрирован: {user['registered_at']}\n"
        f"🛍 Всего покупок: {user['total_purchases']}\n"
        f"💰 Потрачено: {user['total_spent_rub']:.2f} ₽\n\n"
    )
    
    if purchases:
        profile_text += "📋 Последние покупки:\n"
        for purchase in purchases[:5]:  # Показываем последние 5 покупок
            profile_text += f"  • {purchase['product_name']} - {purchase['amount_rub']:.2f} ₽ ({purchase['created_at']})\n"
    
    await message.answer(profile_text)

@dp.message(F.text == "ℹ О нас")
async def about(message: Message):
    """Информация о магазине"""
    settings = db.get_settings()
    currency_symbol = Currency[settings['currency']].value
    
    await message.answer(
        f"ℹ О магазине '{settings.get('bot_name')}':\n\n"
        f"💱 Валюта: {currency_symbol}\n"
        f"💳 Оплата: Crypto Bot (USDT)\n"
        f"Курс: 1 USDT = {USDT_TO_RUB} ₽\n\n"
        "По всем вопросам обращайтесь к администратору."
    )

@dp.message(F.text == "🔧 Админ панель")
async def admin_panel(message: Message):
    """Вход в админ-панель"""
    if not db.is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к админ-панели.")
        return
    
    await message.answer(
        "🔧 Админ-панель\n\nВыберите действие:",
        reply_markup=get_admin_panel_keyboard()
    )

@dp.message(F.text == "📊 Статистика")
async def show_statistics(message: Message):
    """Показ статистики"""
    if not db.is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к этой функции.")
        return
    
    stats = db.get_statistics()
    
    await message.answer(
        "📊 Статистика магазина:\n\n"
        f"👥 Пользователей: {stats['users_count']}\n"
        f"📦 Товаров: {stats['products_count']}\n"
        f"📁 Категорий: {stats['categories_count']}\n"
        f"🛍 Покупок: {stats['purchases_count']}\n"
        f"💰 Оборот: {stats['total_revenue']:.2f} ₽"
    )

@dp.message(F.text == "📨 Рассылка")
async def start_newsletter(message: Message, state: FSMContext):
    """Начало рассылки"""
    if not db.is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к этой функции.")
        return
    
    await message.answer(
        "📨 Введите текст для рассылки всем пользователям:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_newsletter_text)

@dp.message(AdminStates.waiting_for_newsletter_text)
async def process_newsletter(message: Message, state: FSMContext):
    """Обработка текста рассылки и отправка"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Рассылка отменена.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    users = db.get_all_users()
    success_count = 0
    fail_count = 0
    
    await message.answer(f"📨 Начинаю рассылку {len(users)} пользователям...")
    
    for user in users:
        try:
            await bot.send_message(
                chat_id=user['telegram_id'],
                text=f"📨 Рассылка от администратора:\n\n{message.text}"
            )
            success_count += 1
            await asyncio.sleep(0.05)  # Небольшая задержка чтобы не флудить
        except Exception as e:
            logger.error(f"Ошибка при отправке пользователю {user['telegram_id']}: {e}")
            fail_count += 1
    
    await state.clear()
    await message.answer(
        f"✅ Рассылка завершена!\n"
        f"✓ Успешно: {success_count}\n"
        f"✗ Ошибок: {fail_count}",
        reply_markup=get_admin_panel_keyboard()
    )

@dp.message(F.text == "📂 Добавление категорий")
async def add_category_start(message: Message, state: FSMContext):
    """Начало добавления категории"""
    if not db.is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к этой функции.")
        return
    
    await message.answer(
        "📂 Введите название категории:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_category_name)

@dp.message(AdminStates.waiting_for_category_name)
async def process_category_name(message: Message, state: FSMContext):
    """Обработка названия категории"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Добавление категории отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    await state.update_data(category_name=message.text)
    await message.answer(
        "Введите описание категории:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_category_description)

@dp.message(AdminStates.waiting_for_category_description)
async def process_category_description(message: Message, state: FSMContext):
    """Обработка описания категории и сохранение"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Добавление категории отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    data = await state.get_data()
    category_name = data.get('category_name')
    
    # Сохраняем категорию
    category_id = db.add_category(category_name, message.text)
    
    await state.clear()
    await message.answer(
        f"✅ Категория '{category_name}' успешно добавлена!",
        reply_markup=get_admin_panel_keyboard()
    )

@dp.message(F.text == "📦 Добавление товаров")
async def add_product_start(message: Message, state: FSMContext):
    """Начало добавления товара"""
    if not db.is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к этой функции.")
        return
    
    categories = db.get_categories()
    
    if not categories:
        await message.answer(
            "❌ Сначала добавьте хотя бы одну категорию!",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    # Показываем список категорий для выбора
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.row(InlineKeyboardButton(
            text=category['name'],
            callback_data=f"add_product_cat_{category['id']}"
        ))
    
    await message.answer(
        "Выберите категорию для товара:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.waiting_for_product_category)

@dp.callback_query(AdminStates.waiting_for_product_category, F.data.startswith("add_product_cat_"))
async def process_product_category(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора категории для товара"""
    category_id = int(callback.data.replace("add_product_cat_", ""))
    await state.update_data(product_category_id=category_id)
    
    await callback.message.edit_text(
        "Введите название товара:"
    )
    await state.set_state(AdminStates.waiting_for_product_name)
    await callback.answer()

@dp.message(AdminStates.waiting_for_product_name)
async def process_product_name(message: Message, state: FSMContext):
    """Обработка названия товара"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Добавление товара отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    await state.update_data(product_name=message.text)
    await message.answer(
        "Введите описание товара:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_product_description)

@dp.message(AdminStates.waiting_for_product_description)
async def process_product_description(message: Message, state: FSMContext):
    """Обработка описания товара"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Добавление товара отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    await state.update_data(product_description=message.text)
    await message.answer(
        f"Введите цену товара в рублях (число, например: 1000):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_product_price)

@dp.message(AdminStates.waiting_for_product_price)
async def process_product_price(message: Message, state: FSMContext):
    """Обработка цены товара"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Добавление товара отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    # Проверяем, что введено число
    try:
        price = float(message.text.replace(',', '.'))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Ошибка: введите корректное положительное число.",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(product_price=price)
    await message.answer(
        "Отправьте фото товара (необязательно, для пропуска отправьте 'пропустить'):\n"
        "Или отправьте фото:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_product_photo)

@dp.message(AdminStates.waiting_for_product_photo)
async def process_product_photo(message: Message, state: FSMContext):
    """Обработка фото товара"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Добавление товара отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    photo_file_id = None
    
    if message.text and message.text.lower() == 'пропустить':
        # Пропускаем загрузку фото
        pass
    elif message.photo:
        # Берем фото в наилучшем качестве
        photo_file_id = message.photo[-1].file_id
    else:
        await message.answer(
            "Пожалуйста, отправьте фото или напишите 'пропустить':",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(product_photo=photo_file_id)
    await message.answer(
        "Введите контент товара (ссылку, текст или файл, который получит пользователь после оплаты):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_product_content)

@dp.message(AdminStates.waiting_for_product_content)
async def process_product_content(message: Message, state: FSMContext):
    """Обработка контента товара и сохранение"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Добавление товара отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    data = await state.get_data()
    
    # Сохраняем товар
    product_id = db.add_product(
        category_id=data['product_category_id'],
        name=data['product_name'],
        description=data['product_description'],
        price_rub=data['product_price'],
        content=message.text,
        photo_file_id=data.get('product_photo')
    )
    
    await state.clear()
    await message.answer(
        f"✅ Товар '{data['product_name']}' успешно добавлен!",
        reply_markup=get_admin_panel_keyboard()
    )

@dp.message(F.text == "◀ Назад в главное меню")
async def back_to_main(message: Message):
    """Возврат в главное меню из админ-панели"""
    await message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.callback_query(F.data == "back")
async def back_callback(callback: CallbackQuery):
    """Универсальный обработчик возврата"""
    await callback.message.delete()
    await callback.message.answer(
        "Действие отменено."
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_categories")
async def back_to_categories(callback: CallbackQuery):
    """Возврат к списку категорий"""
    # Получаем ID категории из текущего сообщения
    await callback.message.delete()
    await callback.message.answer(
        "Выберите категорию:",
        reply_markup=get_categories_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_callback(callback: CallbackQuery):
    """Возврат в главное меню из inline клавиатуры"""
    await callback.message.delete()
    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.message()
async def handle_unknown(message: Message):
    """Обработка неизвестных команд"""
    await message.answer(
        "Я не понимаю эту команду. Пожалуйста, используйте кнопки меню.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

# ==================== Запуск бота ====================

async def main():
    """Основная функция запуска бота"""
    logger.info("Запуск бота...")
    
    # Проверяем настройки при запуске
    settings = db.get_settings()
    logger.info(f"Текущие настройки: admin_id={settings.get('admin_id')}, setup_complete={settings.get('is_setup_complete')}")
    
    # Запускаем бота
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
