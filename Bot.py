import asyncio
import logging
import os
import sqlite3
import random
import string
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from enum import Enum
from contextlib import contextmanager

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
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
REFERRAL_BONUS_PERCENT = 10  # 10% реферальных

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== Классы состояний FSM ====================

class SetupStates(StatesGroup):
    waiting_for_bot_name = State()
    waiting_for_welcome_message = State()
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
    waiting_for_emoji_select = State()
    waiting_for_emoji_id = State()

class ReferralStates(StatesGroup):
    waiting_for_referral_link = State()

# ==================== Модели данных ====================

class Currency(Enum):
    RUB = "₽"
    USD = "$"

class EmojiType(str, Enum):
    MAIN_MENU = "main_menu"
    BUY = "buy"
    STOCK = "stock"
    PROFILE = "profile"
    ABOUT = "about"
    ADMIN = "admin"
    SETTINGS = "settings"
    STATS = "stats"
    NEWSLETTER = "newsletter"
    CATEGORY = "category"
    PRODUCT = "product"
    PAYMENT = "payment"
    REFERRAL = "referral"
    SUCCESS = "success"
    ERROR = "error"
    CART = "cart"
    BACK = "back"

# Словарь смайликов по умолчанию
DEFAULT_EMOJIS = {
    EmojiType.MAIN_MENU: "🏠",
    EmojiType.BUY: "🛒",
    EmojiType.STOCK: "📦",
    EmojiType.PROFILE: "👤",
    EmojiType.ABOUT: "ℹ",
    EmojiType.ADMIN: "🔧",
    EmojiType.SETTINGS: "⚙",
    EmojiType.STATS: "📊",
    EmojiType.NEWSLETTER: "📨",
    EmojiType.CATEGORY: "📁",
    EmojiType.PRODUCT: "📦",
    EmojiType.PAYMENT: "💳",
    EmojiType.REFERRAL: "🔗",
    EmojiType.SUCCESS: "✅",
    EmojiType.ERROR: "❌",
    EmojiType.CART: "🛍",
    EmojiType.BACK: "◀"
}

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
                    welcome_message TEXT NOT NULL DEFAULT 'Добро пожаловать в магазин!',
                    currency TEXT NOT NULL DEFAULT 'RUB',
                    admin_id INTEGER,
                    crypto_token TEXT,
                    is_setup_complete BOOLEAN NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица эмодзи
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS emojis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    emoji_type TEXT UNIQUE NOT NULL,
                    emoji_char TEXT NOT NULL,
                    is_premium BOOLEAN DEFAULT 0,
                    custom_emoji_id TEXT,
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
                    referred_by INTEGER,
                    referral_code TEXT UNIQUE,
                    referral_earnings REAL DEFAULT 0,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_purchases INTEGER DEFAULT 0,
                    total_spent_rub REAL DEFAULT 0,
                    FOREIGN KEY (referred_by) REFERENCES users (id)
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
                    referral_bonus_paid BOOLEAN DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (product_id) REFERENCES products (id)
                )
            ''')
            
            # Таблица реферальных выплат
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS referral_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER NOT NULL,
                    purchase_id INTEGER NOT NULL,
                    amount_rub REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (referrer_id) REFERENCES users (id),
                    FOREIGN KEY (purchase_id) REFERENCES purchases (id)
                )
            ''')
            
            # Создаем запись настроек, если её нет
            cursor.execute('SELECT * FROM settings WHERE id = 1')
            if not cursor.fetchone():
                cursor.execute('''
                    INSERT INTO settings (id, bot_name, welcome_message, currency, admin_id, crypto_token, is_setup_complete)
                    VALUES (1, ?, ?, ?, ?, ?, ?)
                ''', (
                    'Мой магазин',
                    'Добро пожаловать в магазин!',
                    'RUB',
                    None,
                    None,
                    0
                ))
            
            # Заполняем таблицу эмодзи значениями по умолчанию
            for emoji_type, emoji_char in DEFAULT_EMOJIS.items():
                cursor.execute('''
                    INSERT OR IGNORE INTO emojis (emoji_type, emoji_char)
                    VALUES (?, ?)
                ''', (emoji_type.value, emoji_char))
    
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
    
    # Методы для работы с эмодзи
    def get_all_emojis(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM emojis ORDER BY emoji_type')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_emoji(self, emoji_type: str) -> str:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT emoji_char, is_premium, custom_emoji_id FROM emojis WHERE emoji_type = ?', (emoji_type,))
            row = cursor.fetchone()
            if row:
                return row['emoji_char']
            # Если не нашли, возвращаем из словаря по умолчанию
            for key, value in DEFAULT_EMOJIS.items():
                if key.value == emoji_type:
                    return value
            return "•"
    
    def get_emoji_display(self, emoji_type: str) -> str:
        """Возвращает эмодзи для отображения (с поддержкой премиум)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT emoji_char, is_premium, custom_emoji_id FROM emojis WHERE emoji_type = ?', (emoji_type,))
            row = cursor.fetchone()
            if row:
                if row['is_premium'] and row['custom_emoji_id']:
                    return f"<emoji id={row['custom_emoji_id']}>{row['emoji_char']}</emoji>"
                return row['emoji_char']
            # Если не нашли, возвращаем из словаря по умолчанию
            for key, value in DEFAULT_EMOJIS.items():
                if key.value == emoji_type:
                    return value
            return "•"
    
    def update_emoji(self, emoji_type: str, emoji_char: str, is_premium: bool = False, custom_emoji_id: str = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE emojis 
                SET emoji_char = ?, is_premium = ?, custom_emoji_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE emoji_type = ?
            ''', (emoji_char, is_premium, custom_emoji_id, emoji_type))
    
    # Методы для работы с реферальной системой
    def generate_referral_code(self, length: int = 8) -> str:
        """Генерирует уникальный реферальный код"""
        chars = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(chars, k=length))
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id FROM users WHERE referral_code = ?', (code,))
                if not cursor.fetchone():
                    return code
    
    def register_user(self, telegram_id: int, username: Optional[str], first_name: str, referred_by_code: str = None) -> int:
        """Регистрация пользователя с реферальным кодом"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Проверяем, существует ли уже пользователь
            cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            existing = cursor.fetchone()
            if existing:
                return existing['id']
            
            # Генерируем реферальный код
            referral_code = self.generate_referral_code()
            
            # Находим реферера, если есть код
            referred_by = None
            if referred_by_code:
                cursor.execute('SELECT id FROM users WHERE referral_code = ?', (referred_by_code,))
                referrer = cursor.fetchone()
                if referrer and referrer['id'] != telegram_id:  # Не даем ссылаться на самого себя
                    referred_by = referrer['id']
            
            # Регистрируем пользователя
            cursor.execute('''
                INSERT INTO users (telegram_id, username, first_name, referred_by, referral_code)
                VALUES (?, ?, ?, ?, ?)
            ''', (telegram_id, username, first_name, referred_by, referral_code))
            
            return cursor.lastrowid
    
    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_user_by_referral_code(self, code: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE referral_code = ?', (code,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_referrals(self, user_id: int) -> List[Dict]:
        """Получает список рефералов пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM users 
                WHERE referred_by = ? 
                ORDER BY registered_at DESC
            ''', (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_referral_stats(self, user_id: int) -> Dict:
        """Получает статистику по рефералам"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Количество рефералов
            cursor.execute('SELECT COUNT(*) as count FROM users WHERE referred_by = ?', (user_id,))
            referrals_count = cursor.fetchone()['count']
            
            # Сумма заработанных бонусов
            cursor.execute('SELECT SUM(amount_rub) as total FROM referral_payments WHERE referrer_id = ?', (user_id,))
            total_earned = cursor.fetchone()['total'] or 0
            
            # Сумма покупок рефералов
            cursor.execute('''
                SELECT SUM(p.amount_rub) as total 
                FROM purchases p
                JOIN users u ON p.user_id = u.id
                WHERE u.referred_by = ? AND p.status = 'completed'
            ''', (user_id,))
            referrals_spent = cursor.fetchone()['total'] or 0
            
            return {
                'referrals_count': referrals_count,
                'total_earned': total_earned,
                'referrals_spent': referrals_spent
            }
    
    def process_referral_bonus(self, purchase_id: int):
        """Начисление реферального бонуса"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Получаем информацию о покупке
            cursor.execute('''
                SELECT p.*, u.referred_by 
                FROM purchases p
                JOIN users u ON p.user_id = u.id
                WHERE p.id = ? AND p.status = 'completed' AND p.referral_bonus_paid = 0
            ''', (purchase_id,))
            
            purchase = cursor.fetchone()
            if not purchase or not purchase['referred_by']:
                return
            
            # Рассчитываем бонус
            bonus_amount = purchase['amount_rub'] * REFERRAL_BONUS_PERCENT / 100
            
            # Начисляем бонус рефереру
            cursor.execute('''
                UPDATE users 
                SET referral_earnings = referral_earnings + ?
                WHERE id = ?
            ''', (bonus_amount, purchase['referred_by']))
            
            # Записываем выплату
            cursor.execute('''
                INSERT INTO referral_payments (referrer_id, purchase_id, amount_rub)
                VALUES (?, ?, ?)
            ''', (purchase['referred_by'], purchase_id, bonus_amount))
            
            # Отмечаем, что бонус выплачен
            cursor.execute('''
                UPDATE purchases 
                SET referral_bonus_paid = 1
                WHERE id = ?
            ''', (purchase_id,))
    
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
            
            # Сумма реферальных выплат
            cursor.execute('SELECT SUM(amount_rub) as total FROM referral_payments')
            total_referral_bonuses = cursor.fetchone()['total'] or 0
            
            return {
                'users_count': users_count,
                'purchases_count': purchases_count,
                'total_revenue': total_revenue,
                'products_count': products_count,
                'categories_count': categories_count,
                'total_referral_bonuses': total_referral_bonuses
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
    buy_emoji = db.get_emoji(EmojiType.BUY.value)
    stock_emoji = db.get_emoji(EmojiType.STOCK.value)
    profile_emoji = db.get_emoji(EmojiType.PROFILE.value)
    referral_emoji = db.get_emoji(EmojiType.REFERRAL.value)
    about_emoji = db.get_emoji(EmojiType.ABOUT.value)
    settings_emoji = db.get_emoji(EmojiType.SETTINGS.value)
    admin_emoji = db.get_emoji(EmojiType.ADMIN.value)
    
    builder.row(KeyboardButton(text=f"{buy_emoji} Купить товар"))
    builder.row(
        KeyboardButton(text=f"{stock_emoji} Наличие товара"), 
        KeyboardButton(text=f"{profile_emoji} Профиль")
    )
    builder.row(
        KeyboardButton(text=f"{referral_emoji} Реферальная программа"),
        KeyboardButton(text=f"{about_emoji} О нас")
    )
    
    # Кнопка настройки для первого пользователя, если настройки не завершены
    if not is_setup_complete:
        # Если админ еще не назначен, первый пользователь становится кандидатом
        if settings.get('admin_id') is None:
            builder.row(KeyboardButton(text=f"{settings_emoji} Стать администратором"))
        # Если пользователь является админом и настройки не завершены
        elif is_admin:
            builder.row(KeyboardButton(text=f"{settings_emoji} Настроить бота"))
    
    # Кнопка админ-панели для админа в рабочем режиме
    if is_admin and is_setup_complete:
        builder.row(KeyboardButton(text=f"{admin_emoji} Админ панель"))
    
    return builder.as_markup(resize_keyboard=True)

def get_admin_panel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    
    stats_emoji = db.get_emoji(EmojiType.STATS.value)
    newsletter_emoji = db.get_emoji(EmojiType.NEWSLETTER.value)
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    settings_emoji = db.get_emoji(EmojiType.SETTINGS.value)
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    builder.row(KeyboardButton(text=f"{stats_emoji} Статистика"))
    builder.row(KeyboardButton(text=f"{newsletter_emoji} Рассылка"))
    builder.row(KeyboardButton(text=f"{category_emoji} Добавление категорий"))
    builder.row(KeyboardButton(text=f"{product_emoji} Добавление товаров"))
    builder.row(KeyboardButton(text=f"{settings_emoji} Управление эмодзи"))
    builder.row(KeyboardButton(text=f"{back_emoji} Назад в главное меню"))
    return builder.as_markup(resize_keyboard=True)

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    builder.row(KeyboardButton(text=f"{error_emoji} Отмена"))
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
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    for category in categories:
        builder.row(InlineKeyboardButton(
            text=f"{category_emoji} {category['name']}",
            callback_data=f"category_{category['id']}"
        ))
    
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_products_keyboard(category_id: int) -> InlineKeyboardMarkup:
    products = db.get_products_by_category(category_id)
    settings = db.get_settings()
    currency_symbol = Currency[settings['currency']].value
    builder = InlineKeyboardBuilder()
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    for product in products:
        price = product['price_rub'] if settings['currency'] == 'RUB' else product['price_usd']
        builder.row(InlineKeyboardButton(
            text=f"{product_emoji} {product['name']} - {price} {currency_symbol}",
            callback_data=f"product_{product['id']}"
        ))
    
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад к категориям", callback_data="back_to_categories"))
    return builder.as_markup()

def get_payment_keyboard(payment_url: str, purchase_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    payment_emoji = db.get_emoji(EmojiType.PAYMENT.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    
    builder.row(InlineKeyboardButton(text=f"{payment_emoji} Оплатить", url=payment_url))
    builder.row(InlineKeyboardButton(text=f"{success_emoji} Проверить оплату", callback_data=f"check_payment_{purchase_id}"))
    builder.row(InlineKeyboardButton(text=f"{error_emoji} Отмена", callback_data="cancel_payment"))
    return builder.as_markup()

def get_back_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data="back"))
    return builder.as_markup()

def get_emojis_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора эмодзи для изменения"""
    emojis = db.get_all_emojis()
    builder = InlineKeyboardBuilder()
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    # Группируем эмодзи по 2 в ряд для компактности
    for i in range(0, len(emojis), 2):
        row = []
        for j in range(2):
            if i + j < len(emojis):
                emoji = emojis[i + j]
                emoji_display = emoji['emoji_char']
                row.append(InlineKeyboardButton(
                    text=f"{emoji_display} {emoji['emoji_type']}",
                    callback_data=f"edit_emoji_{emoji['emoji_type']}"
                ))
        builder.row(*row)
    
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data="back_to_admin"))
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
                    "paid_btn_url": f"https://t.me/{(await bot.get_me()).username}",
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
                            logger.info(f"Инвойс создан: {data['result']}")
                            return data['result']
                    else:
                        logger.error(f"Ошибка Crypto Bot API: {response.status} - {await response.text()}")
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
                            status = data['result']['items'][0].get('status')
                            logger.info(f"Статус инвойса {invoice_id}: {status}")
                            return status
                    return None
        except Exception as e:
            logger.error(f"Ошибка при проверке статуса инвойса: {e}")
            return None

# ==================== Обработчики команд ====================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start с поддержкой реферальных ссылок"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    # Проверяем, есть ли реферальный код в команде
    args = message.text.split()
    referral_code = args[1] if len(args) > 1 else None
    
    # Регистрируем пользователя
    db_user_id = db.register_user(user_id, username, first_name, referral_code)
    
    # Получаем настройки
    settings = db.get_settings()
    
    # Получаем эмодзи
    main_emoji = db.get_emoji(EmojiType.MAIN_MENU.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    # Отправляем приветственное сообщение
    welcome_text = f"{main_emoji} Добро пожаловать в {settings.get('bot_name', 'магазин')}!\n\n"
    welcome_text += settings.get('welcome_message', 'Добро пожаловать в магазин!')
    
    # Если пользователь был приглашен по реферальной ссылке
    if referral_code:
        referrer = db.get_user_by_referral_code(referral_code)
        if referrer and referrer['telegram_id'] != user_id:
            welcome_text += f"\n\n{success_emoji} Вы перешли по реферальной ссылке!"
    
    # Если админ еще не назначен, информируем об этом
    if settings.get('admin_id') is None:
        welcome_text += f"\n\n⚡ Бот еще не настроен. Нажмите кнопку 'Стать администратором' для начала настройки."
    elif not settings.get('is_setup_complete'):
        welcome_text += f"\n\n⚡ Бот находится в режиме настройки. Используйте кнопку 'Настроить бота' для продолжения."
    
    await message.answer(
        welcome_text,
        reply_markup=get_main_keyboard(user_id)
    )

@dp.message(lambda message: message.text and "Стать администратором" in message.text)
async def become_admin(message: Message):
    """Первый пользователь становится администратором"""
    settings = db.get_settings()
    
    # Проверяем, не назначен ли уже администратор
    if settings.get('admin_id') is not None:
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(
            f"{error_emoji} Администратор уже назначен.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    # Назначаем текущего пользователя администратором
    db.update_settings(admin_id=message.from_user.id)
    
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    await message.answer(
        f"{success_emoji} Вы назначены администратором!\n\n"
        f"Теперь нажмите кнопку 'Настроить бота' для продолжения настройки.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(lambda message: message.text and "Настроить бота" in message.text)
async def setup_bot(message: Message, state: FSMContext):
    """Начало настройки бота"""
    if not db.is_admin(message.from_user.id):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} У вас нет прав для настройки бота.")
        return
    
    settings = db.get_settings()
    
    # Показываем меню настройки
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏ Изменить имя бота", callback_data="setup_name"))
    builder.row(InlineKeyboardButton(text="📝 Изменить приветствие", callback_data="setup_welcome"))
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
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await callback.answer(f"{error_emoji} У вас нет прав для настройки бота.")
        return
    
    action = callback.data.replace("setup_", "")
    
    if action == "name":
        await callback.message.edit_text(
            "✏ Введите новое имя бота:",
            reply_markup=get_back_keyboard()
        )
        await state.set_state(SetupStates.waiting_for_bot_name)
    
    elif action == "welcome":
        await callback.message.edit_text(
            "📝 Введите новое приветственное сообщение:",
            reply_markup=get_back_keyboard()
        )
        await state.set_state(SetupStates.waiting_for_welcome_message)
    
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
        
        success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
        await callback.message.edit_text(
            f"{success_emoji} Настройка завершена! Бот запущен в рабочем режиме."
        )
        await callback.message.answer(
            "Главное меню:",
            reply_markup=get_main_keyboard(callback.from_user.id)
        )
    
    await callback.answer()

@dp.message(SetupStates.waiting_for_bot_name)
async def process_bot_name(message: Message, state: FSMContext):
    """Обработка ввода имени бота"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Настройка отменена.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    # Сохраняем имя бота
    db.update_settings(bot_name=message.text)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Имя бота изменено на: {message.text}",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(SetupStates.waiting_for_welcome_message)
async def process_welcome_message(message: Message, state: FSMContext):
    """Обработка ввода приветственного сообщения"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Настройка отменена.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    # Сохраняем приветственное сообщение
    db.update_settings(welcome_message=message.text)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Приветственное сообщение изменено!",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.callback_query(SetupStates.waiting_for_currency, F.data.startswith("currency_"))
async def process_currency(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора валюты"""
    currency = callback.data.replace("currency_", "").upper()
    
    # Сохраняем валюту
    db.update_settings(currency=currency)
    
    await state.clear()
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    await callback.message.edit_text(
        f"{success_emoji} Валюта изменена на: {'Рубли (₽)' if currency == 'RUB' else 'Доллары ($)'}"
    )
    await callback.answer()

@dp.message(SetupStates.waiting_for_admin_id)
async def process_admin_id(message: Message, state: FSMContext):
    """Обработка ввода admin ID"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Настройка отменена.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    # Проверяем, что введено число
    if not message.text.isdigit():
        await message.answer(
            f"{error_emoji} Ошибка: admin ID должен быть числом. Попробуйте снова:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    admin_id = int(message.text)
    
    # Сохраняем admin ID
    db.update_settings(admin_id=admin_id)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Admin ID изменен на: {admin_id}",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(SetupStates.waiting_for_crypto_token)
async def process_crypto_token(message: Message, state: FSMContext):
    """Обработка ввода Crypto Bot токена"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Настройка отменена.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    # Простая проверка формата токена (обычно это длинная строка)
    if len(message.text) < 10:
        await message.answer(
            f"{error_emoji} Ошибка: неверный формат токена. Попробуйте снова:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Сохраняем токен
    db.update_settings(crypto_token=message.text)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Crypto Bot API токен сохранен.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(lambda message: message.text and "Реферальная программа" in message.text)
async def referral_program(message: Message):
    """Показ информации о реферальной программе"""
    user = db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(
            f"{error_emoji} Профиль не найден."
        )
        return
    
    # Получаем статистику
    stats = db.get_referral_stats(user['id'])
    referrals = db.get_referrals(user['id'])
    
    # Создаем реферальную ссылку
    bot_username = (await bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user['referral_code']}"
    
    # Получаем эмодзи
    referral_emoji = db.get_emoji(EmojiType.REFERRAL.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    # Формируем сообщение
    message_text = (
        f"{referral_emoji} *Реферальная программа*\n\n"
        f"Приглашайте друзей и получайте {REFERRAL_BONUS_PERCENT}% от их покупок!\n\n"
        f"📊 *Ваша статистика:*\n"
        f"• Приглашено друзей: {stats['referrals_count']}\n"
        f"• Заработано бонусов: {stats['total_earned']:.2f} ₽\n"
        f"• Сумма покупок рефералов: {stats['referrals_spent']:.2f} ₽\n\n"
        f"🔗 *Ваша реферальная ссылка:*\n"
        f"`{referral_link}`\n\n"
        f"👥 *Ваши рефералы:*\n"
    )
    
    if referrals:
        for ref in referrals[:10]:  # Показываем последние 10
            message_text += f"• {ref['first_name']} - {ref['registered_at']}\n"
    else:
        message_text += "• Пока нет приглашенных друзей"
    
    await message.answer(
        message_text,
        parse_mode="Markdown",
        reply_markup=get_back_keyboard()
    )

@dp.message(lambda message: message.text and "Купить товар" in message.text)
async def buy_product(message: Message):
    """Покупка товара - показ категорий"""
    settings = db.get_settings()
    
    # Проверяем, завершена ли настройка
    if not settings.get('is_setup_complete'):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(
            f"{error_emoji} Магазин еще не настроен. Дождитесь завершения настройки администратором."
        )
        return
    
    categories = db.get_categories()
    
    if not categories:
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(
            f"{error_emoji} В магазине пока нет товаров."
        )
        return
    
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    await message.answer(
        f"{category_emoji} Выберите категорию:",
        reply_markup=get_categories_keyboard()
    )

@dp.callback_query(F.data.startswith("category_"))
async def show_category_products(callback: CallbackQuery):
    """Показ товаров в категории"""
    category_id = int(callback.data.replace("category_", ""))
    category = db.get_category(category_id)
    products = db.get_products_by_category(category_id)
    
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    
    if not products:
        await callback.message.edit_text(
            f"{error_emoji} В категории '{category['name']}' пока нет товаров.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    await callback.message.edit_text(
        f"{category_emoji} *Категория: {category['name']}*\n\n"
        f"{category['description']}\n\n"
        f"{product_emoji} Выберите товар:",
        parse_mode="Markdown",
        reply_markup=get_products_keyboard(category_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("product_"))
async def show_product_details(callback: CallbackQuery):
    """Показ деталей товара и предложение оплаты"""
    product_id = int(callback.data.replace("product_", ""))
    product = db.get_product(product_id)
    settings = db.get_settings()
    
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    payment_emoji = db.get_emoji(EmojiType.PAYMENT.value)
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    if not product:
        await callback.message.edit_text(
            f"{error_emoji} Товар не найден.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    # Формируем сообщение с деталями товара
    currency_symbol = Currency[settings['currency']].value
    price = product['price_rub'] if settings['currency'] == 'RUB' else product['price_usd']
    
    message_text = (
        f"{product_emoji} *{product['name']}*\n\n"
        f"{product['description']}\n\n"
        f"💰 *Цена:* {price} {currency_symbol}\n\n"
        f"Хотите купить этот товар?"
    )
    
    # Клавиатура с кнопкой покупки
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"{payment_emoji} Купить", callback_data=f"buy_{product_id}"))
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data=f"category_{product['category_id']}"))
    
    # Если есть фото, отправляем с фото
    if product['photo_file_id']:
        try:
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=product['photo_file_id'],
                caption=message_text,
                parse_mode="Markdown",
                reply_markup=builder.as_markup()
            )
        except:
            await callback.message.edit_text(
                message_text,
                parse_mode="Markdown",
                reply_markup=builder.as_markup()
            )
    else:
        await callback.message.edit_text(
            message_text,
            parse_mode="Markdown",
            reply_markup=builder.as_markup()
        )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_"))
async def process_purchase(callback: CallbackQuery):
    """Обработка покупки - создание счета в Crypto Bot"""
    product_id = int(callback.data.replace("buy_", ""))
    product = db.get_product(product_id)
    settings = db.get_settings()
    
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    payment_emoji = db.get_emoji(EmojiType.PAYMENT.value)
    
    if not settings.get('crypto_token'):
        await callback.message.edit_text(
            f"{error_emoji} Ошибка: платежная система не настроена. Обратитесь к администратору.",
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
            f"{error_emoji} Ошибка при создании счета. Попробуйте позже.",
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
        f"{payment_emoji} *Счет на оплату:*\n\n"
        f"Товар: {product['name']}\n"
        f"Сумма: {price} {currency_symbol} "
        f"({product['price_usd']} USDT)\n\n"
        f"Нажмите кнопку ниже для оплаты через @CryptoBot",
        parse_mode="Markdown",
        reply_markup=get_payment_keyboard(invoice['pay_url'], purchase_id)
    )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: CallbackQuery):
    """Проверка статуса оплаты"""
    purchase_id = int(callback.data.replace("check_payment_", ""))
    purchase = db.get_purchase(purchase_id)
    
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    payment_emoji = db.get_emoji(EmojiType.PAYMENT.value)
    
    if not purchase:
        await callback.message.edit_text(
            f"{error_emoji} Платеж не найден.",
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
        
        # Начисляем реферальный бонус
        db.process_referral_bonus(purchase_id)
        
        await deliver_product(callback.message, purchase)
    elif status == 'active':
        await callback.message.edit_text(
            f"{payment_emoji} Счет ожидает оплаты. После оплаты нажмите кнопку проверки.",
            reply_markup=get_payment_keyboard(
                f"https://t.me/CryptoBot?start={purchase['crypto_payment_id']}",
                purchase_id
            )
        )
    else:
        await callback.message.edit_text(
            f"{error_emoji} Платеж не найден или истек. Попробуйте создать новый заказ.",
            reply_markup=get_back_keyboard()
        )
    
    await callback.answer()

async def deliver_product(message: types.Message, purchase: Dict):
    """Доставка товара после оплаты"""
    product = db.get_product(purchase['product_id'])
    
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    
    if not product:
        await message.answer(
            f"{error_emoji} Ошибка: товар не найден. Обратитесь к администратору."
        )
        return
    
    await message.answer(
        f"{success_emoji} *Оплата получена!*\n\n"
        f"{product_emoji} *Ваш товар:*\n\n{product['content']}",
        parse_mode="Markdown"
    )
    
    # Возвращаем в главное меню
    await message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(message.chat.id)
    )

@dp.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery):
    """Отмена платежа"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    await callback.message.edit_text(
        f"{error_emoji} Платеж отменен."
    )
    
    # Возвращаем в главное меню
    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.message(lambda message: message.text and "Наличие товара" in message.text)
async def check_stock(message: Message):
    """Проверка наличия товаров"""
    settings = db.get_settings()
    
    # Проверяем, завершена ли настройка
    if not settings.get('is_setup_complete'):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(
            f"{error_emoji} Магазин еще не настроен. Дождитесь завершения настройки администратором."
        )
        return
    
    products = []
    categories = db.get_categories()
    
    for category in categories:
        category_products = db.get_products_by_category(category['id'])
        if category_products:
            products.extend(category_products)
    
    if not products:
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(
            f"{error_emoji} В магазине пока нет товаров."
        )
        return
    
    currency_symbol = Currency[settings['currency']].value
    stock_emoji = db.get_emoji(EmojiType.STOCK.value)
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    
    message_text = f"{stock_emoji} *Наличие товаров:*\n\n"
    
    for category in categories:
        category_products = db.get_products_by_category(category['id'])
        if category_products:
            message_text += f"{category_emoji} *{category['name']}:*\n"
            for product in category_products:
                price = product['price_rub'] if settings['currency'] == 'RUB' else product['price_usd']
                message_text += f"  • {product['name']} - {price} {currency_symbol}\n"
            message_text += "\n"
    
    await message.answer(message_text, parse_mode="Markdown")

@dp.message(lambda message: message.text and "Профиль" in message.text)
async def show_profile(message: Message):
    """Показ профиля пользователя"""
    user = db.get_user_by_telegram_id(message.from_user.id)
    
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    profile_emoji = db.get_emoji(EmojiType.PROFILE.value)
    
    if not user:
        await message.answer(
            f"{error_emoji} Профиль не найден. Начните с команды /start"
        )
        return
    
    # Получаем историю покупок
    purchases = db.get_purchases_by_user(user['id'])
    
    profile_text = (
        f"{profile_emoji} *Ваш профиль:*\n\n"
        f"🆔 ID: {user['telegram_id']}\n"
        f"📝 Имя: {user['first_name']}\n"
        f"📅 Зарегистрирован: {user['registered_at']}\n"
        f"🛍 Всего покупок: {user['total_purchases']}\n"
        f"💰 Потрачено: {user['total_spent_rub']:.2f} ₽\n"
        f"🎁 Реферальных бонусов: {user['referral_earnings']:.2f} ₽\n\n"
    )
    
    if purchases:
        profile_text += "📋 *Последние покупки:*\n"
        for purchase in purchases[:5]:  # Показываем последние 5 покупок
            profile_text += f"  • {purchase['product_name']} - {purchase['amount_rub']:.2f} ₽ ({purchase['created_at']})\n"
    
    await message.answer(profile_text, parse_mode="Markdown")

@dp.message(lambda message: message.text and "О нас" in message.text)
async def about(message: Message):
    """Информация о магазине"""
    settings = db.get_settings()
    currency_symbol = Currency[settings['currency']].value
    about_emoji = db.get_emoji(EmojiType.ABOUT.value)
    
    await message.answer(
        f"{about_emoji} *О магазине '{settings.get('bot_name')}':*\n\n"
        f"💱 Валюта: {currency_symbol}\n"
        f"💳 Оплата: Crypto Bot (USDT)\n"
        f"Курс: 1 USDT = {USDT_TO_RUB} ₽\n"
        f"🎁 Реферальная программа: {REFERRAL_BONUS_PERCENT}% с покупок рефералов\n\n"
        "По всем вопросам обращайтесь к администратору.",
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text and "Админ панель" in message.text)
async def admin_panel(message: Message):
    """Вход в админ-панель"""
    if not db.is_admin(message.from_user.id):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} У вас нет доступа к админ-панели.")
        return
    
    admin_emoji = db.get_emoji(EmojiType.ADMIN.value)
    await message.answer(
        f"{admin_emoji} *Админ-панель*\n\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=get_admin_panel_keyboard()
    )

@dp.message(lambda message: message.text and "Статистика" in message.text)
async def show_statistics(message: Message):
    """Показ статистики"""
    if not db.is_admin(message.from_user.id):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} У вас нет доступа к этой функции.")
        return
    
    stats = db.get_statistics()
    stats_emoji = db.get_emoji(EmojiType.STATS.value)
    
    await message.answer(
        f"{stats_emoji} *Статистика магазина:*\n\n"
        f"👥 Пользователей: {stats['users_count']}\n"
        f"📦 Товаров: {stats['products_count']}\n"
        f"📁 Категорий: {stats['categories_count']}\n"
        f"🛍 Покупок: {stats['purchases_count']}\n"
        f"💰 Оборот: {stats['total_revenue']:.2f} ₽\n"
        f"🎁 Реферальных выплат: {stats['total_referral_bonuses']:.2f} ₽",
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text and "Рассылка" in message.text)
async def start_newsletter(message: Message, state: FSMContext):
    """Начало рассылки"""
    if not db.is_admin(message.from_user.id):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} У вас нет доступа к этой функции.")
        return
    
    newsletter_emoji = db.get_emoji(EmojiType.NEWSLETTER.value)
    await message.answer(
        f"{newsletter_emoji} Введите текст для рассылки всем пользователям:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_newsletter_text)

@dp.message(AdminStates.waiting_for_newsletter_text)
async def process_newsletter(message: Message, state: FSMContext):
    """Обработка текста рассылки и отправка"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    newsletter_emoji = db.get_emoji(EmojiType.NEWSLETTER.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Рассылка отменена.",
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
                text=f"{newsletter_emoji} *Рассылка от администратора:*\n\n{message.text}",
                parse_mode="Markdown"
            )
            success_count += 1
            await asyncio.sleep(0.05)  # Небольшая задержка чтобы не флудить
        except Exception as e:
            logger.error(f"Ошибка при отправке пользователю {user['telegram_id']}: {e}")
            fail_count += 1
    
    await state.clear()
    await message.answer(
        f"{success_emoji} *Рассылка завершена!*\n"
        f"✓ Успешно: {success_count}\n"
        f"✗ Ошибок: {fail_count}",
        parse_mode="Markdown",
        reply_markup=get_admin_panel_keyboard()
    )

@dp.message(lambda message: message.text and "Добавление категорий" in message.text)
async def add_category_start(message: Message, state: FSMContext):
    """Начало добавления категории"""
    if not db.is_admin(message.from_user.id):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} У вас нет доступа к этой функции.")
        return
    
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    await message.answer(
        f"{category_emoji} Введите название категории:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_category_name)

@dp.message(AdminStates.waiting_for_category_name)
async def process_category_name(message: Message, state: FSMContext):
    """Обработка названия категории"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Добавление категории отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    await state.update_data(category_name=message.text)
    await message.answer(
        f"{category_emoji} Введите описание категории:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_category_description)

@dp.message(AdminStates.waiting_for_category_description)
async def process_category_description(message: Message, state: FSMContext):
    """Обработка описания категории и сохранение"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Добавление категории отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    data = await state.get_data()
    category_name = data.get('category_name')
    
    # Сохраняем категорию
    category_id = db.add_category(category_name, message.text)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Категория '{category_name}' успешно добавлена!",
        reply_markup=get_admin_panel_keyboard()
    )

@dp.message(lambda message: message.text and "Добавление товаров" in message.text)
async def add_product_start(message: Message, state: FSMContext):
    """Начало добавления товара"""
    if not db.is_admin(message.from_user.id):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} У вас нет доступа к этой функции.")
        return
    
    categories = db.get_categories()
    
    if not categories:
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(
            f"{error_emoji} Сначала добавьте хотя бы одну категорию!",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    # Показываем список категорий для выбора
    builder = InlineKeyboardBuilder()
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    for category in categories:
        builder.row(InlineKeyboardButton(
            text=f"{category_emoji} {category['name']}",
            callback_data=f"add_product_cat_{category['id']}"
        ))
    
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    await message.answer(
        f"{product_emoji} Выберите категорию для товара:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.waiting_for_product_category)

@dp.callback_query(AdminStates.waiting_for_product_category, F.data.startswith("add_product_cat_"))
async def process_product_category(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора категории для товара"""
    category_id = int(callback.data.replace("add_product_cat_", ""))
    await state.update_data(product_category_id=category_id)
    
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    await callback.message.edit_text(
        f"{product_emoji} Введите название товара:"
    )
    await state.set_state(AdminStates.waiting_for_product_name)
    await callback.answer()

@dp.message(AdminStates.waiting_for_product_name)
async def process_product_name(message: Message, state: FSMContext):
    """Обработка названия товара"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Добавление товара отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    await state.update_data(product_name=message.text)
    await message.answer(
        f"{product_emoji} Введите описание товара:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_product_description)

@dp.message(AdminStates.waiting_for_product_description)
async def process_product_description(message: Message, state: FSMContext):
    """Обработка описания товара"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Добавление товара отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    await state.update_data(product_description=message.text)
    await message.answer(
        f"{product_emoji} Введите цену товара в рублях (число, например: 1000):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_product_price)

@dp.message(AdminStates.waiting_for_product_price)
async def process_product_price(message: Message, state: FSMContext):
    """Обработка цены товара"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Добавление товара отменено.",
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
            f"{error_emoji} Ошибка: введите корректное положительное число.",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(product_price=price)
    await message.answer(
        f"{product_emoji} Отправьте фото товара (необязательно, для пропуска отправьте 'пропустить'):\n"
        "Или отправьте фото:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_product_photo)

@dp.message(AdminStates.waiting_for_product_photo)
async def process_product_photo(message: Message, state: FSMContext):
    """Обработка фото товара"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Добавление товара отменено.",
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
            f"{error_emoji} Пожалуйста, отправьте фото или напишите 'пропустить':",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(product_photo=photo_file_id)
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    await message.answer(
        f"{product_emoji} Введите контент товара (ссылку, текст или файл, который получит пользователь после оплаты):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_product_content)

@dp.message(AdminStates.waiting_for_product_content)
async def process_product_content(message: Message, state: FSMContext):
    """Обработка контента товара и сохранение"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Добавление товара отменено.",
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
        f"{success_emoji} Товар '{data['product_name']}' успешно добавлен!",
        reply_markup=get_admin_panel_keyboard()
    )

@dp.message(lambda message: message.text and "Управление эмодзи" in message.text)
async def manage_emojis(message: Message, state: FSMContext):
    """Управление эмодзи"""
    if not db.is_admin(message.from_user.id):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} У вас нет доступа к этой функции.")
        return
    
    emojis = db.get_all_emojis()
    
    settings_emoji = db.get_emoji(EmojiType.SETTINGS.value)
    text = f"{settings_emoji} *Управление эмодзи*\n\n"
    text += "Выберите эмодзи для изменения:\n\n"
    
    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=get_emojis_keyboard()
    )

@dp.callback_query(F.data.startswith("edit_emoji_"))
async def edit_emoji(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования эмодзи"""
    emoji_type = callback.data.replace("edit_emoji_", "")
    await state.update_data(editing_emoji=emoji_type)
    
    current_emoji = db.get_emoji(emoji_type)
    
    text = (
        f"Редактирование эмодзи: *{emoji_type}*\n\n"
        f"Текущий эмодзи: {current_emoji}\n\n"
        f"Отправьте новый эмодзи (обычный смайлик) или "
        f"ID премиум эмодзи в формате: `premium:123456789`"
    )
    
    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_emoji_id)
    await callback.answer()

@dp.message(AdminStates.waiting_for_emoji_id)
async def process_emoji_id(message: Message, state: FSMContext):
    """Обработка нового эмодзи"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Редактирование отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    data = await state.get_data()
    emoji_type = data.get('editing_emoji')
    
    # Проверяем, премиум ли эмодзи
    if message.text.startswith('premium:'):
        # Премиум эмодзи
        custom_emoji_id = message.text.replace('premium:', '')
        # Используем сам эмодзи как символ-заполнитель
        emoji_char = "⭐"
        is_premium = True
    else:
        # Обычный эмодзи
        emoji_char = message.text
        is_premium = False
        custom_emoji_id = None
    
    # Обновляем эмодзи в БД
    db.update_emoji(emoji_type, emoji_char, is_premium, custom_emoji_id)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Эмодзи для '{emoji_type}' обновлен!",
        reply_markup=get_admin_panel_keyboard()
    )

@dp.message(lambda message: message.text and "Назад в главное меню" in message.text)
async def back_to_main(message: Message):
    """Возврат в главное меню из админ-панели"""
    await message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.callback_query(F.data == "back")
async def back_callback(callback: CallbackQuery):
    """Универсальный обработчик возврата"""
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    await callback.message.delete()
    await callback.message.answer(
        f"{back_emoji} Действие отменено."
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_categories")
async def back_to_categories(callback: CallbackQuery):
    """Возврат к списку категорий"""
    await callback.message.delete()
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    await callback.message.answer(
        f"{category_emoji} Выберите категорию:",
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

@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin_callback(callback: CallbackQuery):
    """Возврат в админ-панель"""
    await callback.message.delete()
    admin_emoji = db.get_emoji(EmojiType.ADMIN.value)
    await callback.message.answer(
        f"{admin_emoji} *Админ-панель*\n\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=get_admin_panel_keyboard()
    )
    await callback.answer()

@dp.message()
async def handle_unknown(message: Message):
    """Обработка неизвестных команд"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    await message.answer(
        f"{error_emoji} Я не понимаю эту команду. Пожалуйста, используйте кнопки меню.",
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
