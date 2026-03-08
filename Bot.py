import asyncio
import logging
import os
import sqlite3
import random
import string
from datetime import datetime, timedelta
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
    waiting_for_about_message = State()
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
    waiting_for_product_quantity = State()
    waiting_for_product_photo = State()
    waiting_for_product_content = State()
    waiting_for_product_type = State()  # paid или free
    waiting_for_emoji_select = State()
    waiting_for_emoji_id = State()
    waiting_for_promo_code = State()
    waiting_for_promo_discount = State()
    waiting_for_promo_expiry = State()

class UserStates(StatesGroup):
    waiting_for_product_quantity = State()
    waiting_for_payment = State()
    waiting_for_promo_code = State()

# ==================== Модели данных ====================

class Currency(Enum):
    RUB = "₽"
    USD = "$"

class ProductType(Enum):
    PAID = "paid"
    FREE = "free"

class EmojiType(str, Enum):
    MAIN_MENU = "main_menu"
    BUY = "buy"
    FREE = "free"
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
    PROMO = "promo"
    SUCCESS = "success"
    ERROR = "error"
    CART = "cart"
    BACK = "back"

# Словарь смайликов по умолчанию
DEFAULT_EMOJIS = {
    EmojiType.MAIN_MENU: "🏠",
    EmojiType.BUY: "🛒",
    EmojiType.FREE: "🎁",
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
    EmojiType.PROMO: "🎟️",
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
                    about_message TEXT NOT NULL DEFAULT 'Информация о магазине',
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
                    premium_emoji_id TEXT,
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
                    price_rub REAL NOT NULL DEFAULT 0,
                    price_usd REAL NOT NULL DEFAULT 0,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    product_type TEXT NOT NULL DEFAULT 'paid',
                    photo_file_id TEXT,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE CASCADE
                )
            ''')
            
            # Таблица бесплатных товаров (кто забрал)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS free_products_claimed (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, product_id),
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (product_id) REFERENCES products (id)
                )
            ''')
            
            # Таблица промокодов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS promocodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    discount_percent INTEGER NOT NULL,
                    max_uses INTEGER,
                    used_count INTEGER DEFAULT 0,
                    expires_at TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица использованных промокодов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS promocode_uses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    promocode_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    purchase_id INTEGER,
                    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (promocode_id) REFERENCES promocodes (id),
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (purchase_id) REFERENCES purchases (id)
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
                    quantity INTEGER NOT NULL DEFAULT 1,
                    amount_rub REAL NOT NULL,
                    amount_usd REAL NOT NULL,
                    discount_amount_rub REAL DEFAULT 0,
                    promocode_id INTEGER,
                    crypto_payment_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    referral_bonus_paid BOOLEAN DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (product_id) REFERENCES products (id),
                    FOREIGN KEY (promocode_id) REFERENCES promocodes (id)
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
                    INSERT INTO settings (id, bot_name, welcome_message, about_message, currency, admin_id, crypto_token, is_setup_complete)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    'Мой магазин',
                    'Добро пожаловать в магазин!',
                    'Информация о магазине',
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
        """Возвращает символ эмодзи"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT emoji_char FROM emojis WHERE emoji_type = ?', (emoji_type,))
            row = cursor.fetchone()
            if row:
                return row['emoji_char']
            # Если не нашли, возвращаем из словаря по умолчанию
            for key, value in DEFAULT_EMOJIS.items():
                if key.value == emoji_type:
                    return value
            return "•"
    
    def format_emoji(self, emoji_type: str) -> str:
        """Форматирует эмодзи для отображения (с поддержкой премиум)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT emoji_char, is_premium, premium_emoji_id FROM emojis WHERE emoji_type = ?', (emoji_type,))
            row = cursor.fetchone()
            if row:
                if row['is_premium'] and row['premium_emoji_id']:
                    return f'<tg-emoji emoji-id="{row["premium_emoji_id"]}">{row["emoji_char"]}</tg-emoji>'
                return row['emoji_char']
            # Если не нашли, возвращаем из словаря по умолчанию
            for key, value in DEFAULT_EMOJIS.items():
                if key.value == emoji_type:
                    return value
            return "•"
    
    def update_emoji(self, emoji_type: str, emoji_char: str, is_premium: bool = False, premium_emoji_id: str = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE emojis 
                SET emoji_char = ?, is_premium = ?, premium_emoji_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE emoji_type = ?
            ''', (emoji_char, is_premium, premium_emoji_id, emoji_type))
    
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
                if referrer and referrer['id'] != telegram_id:
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
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM users 
                WHERE referred_by = ? 
                ORDER BY registered_at DESC
            ''', (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_referral_stats(self, user_id: int) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) as count FROM users WHERE referred_by = ?', (user_id,))
            referrals_count = cursor.fetchone()['count']
            
            cursor.execute('SELECT SUM(amount_rub) as total FROM referral_payments WHERE referrer_id = ?', (user_id,))
            total_earned = cursor.fetchone()['total'] or 0
            
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
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT p.*, u.referred_by 
                FROM purchases p
                JOIN users u ON p.user_id = u.id
                WHERE p.id = ? AND p.status = 'completed' AND p.referral_bonus_paid = 0
            ''', (purchase_id,))
            
            purchase = cursor.fetchone()
            if not purchase or not purchase['referred_by']:
                return
            
            bonus_amount = purchase['amount_rub'] * REFERRAL_BONUS_PERCENT / 100
            
            cursor.execute('''
                UPDATE users 
                SET referral_earnings = referral_earnings + ?
                WHERE id = ?
            ''', (bonus_amount, purchase['referred_by']))
            
            cursor.execute('''
                INSERT INTO referral_payments (referrer_id, purchase_id, amount_rub)
                VALUES (?, ?, ?)
            ''', (purchase['referred_by'], purchase_id, bonus_amount))
            
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
                   price_rub: float, quantity: int, product_type: str, 
                   content: str, photo_file_id: Optional[str] = None) -> int:
        price_usd = round(price_rub / USDT_TO_RUB, 2) if price_rub > 0 else 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO products (category_id, name, description, price_rub, price_usd, quantity, product_type, content, photo_file_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (category_id, name, description, price_rub, price_usd, quantity, product_type, content, photo_file_id))
            return cursor.lastrowid
    
    def get_products_by_category(self, category_id: int, product_type: str = None) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if product_type:
                cursor.execute('SELECT * FROM products WHERE category_id = ? AND product_type = ? AND quantity > 0 ORDER BY name', 
                             (category_id, product_type))
            else:
                cursor.execute('SELECT * FROM products WHERE category_id = ? AND quantity > 0 ORDER BY name', (category_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_free_products(self) -> List[Dict]:
        """Получает все бесплатные товары"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM products WHERE product_type = "free" AND quantity > 0 ORDER BY name')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_product(self, product_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def has_user_claimed_free_product(self, user_id: int, product_id: int) -> bool:
        """Проверяет, забирал ли пользователь бесплатный товар"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM free_products_claimed WHERE user_id = ? AND product_id = ?', (user_id, product_id))
            return cursor.fetchone() is not None
    
    def claim_free_product(self, user_id: int, product_id: int) -> bool:
        """Отмечает, что пользователь забрал бесплатный товар"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO free_products_claimed (user_id, product_id)
                    VALUES (?, ?)
                ''', (user_id, product_id))
                
                # Уменьшаем количество
                cursor.execute('''
                    UPDATE products 
                    SET quantity = quantity - 1
                    WHERE id = ? AND quantity > 0
                ''', (product_id,))
                
                return True
            except sqlite3.IntegrityError:
                return False
    
    def update_product_quantity(self, product_id: int, quantity: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE products 
                SET quantity = quantity - ?
                WHERE id = ? AND quantity >= ?
            ''', (quantity, product_id, quantity))
            return cursor.rowcount > 0
    
    # Методы для работы с промокодами
    def generate_promo_code(self, length: int = 8) -> str:
        """Генерирует уникальный промокод"""
        chars = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(chars, k=length))
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id FROM promocodes WHERE code = ?', (code,))
                if not cursor.fetchone():
                    return code
    
    def add_promocode(self, code: str, discount_percent: int, max_uses: int = None, expires_days: int = None) -> int:
        """Добавляет новый промокод"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            expires_at = None
            if expires_days:
                expires_at = (datetime.now() + timedelta(days=expires_days)).isoformat()
            
            cursor.execute('''
                INSERT INTO promocodes (code, discount_percent, max_uses, expires_at)
                VALUES (?, ?, ?, ?)
            ''', (code, discount_percent, max_uses, expires_at))
            return cursor.lastrowid
    
    def get_all_promocodes(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM promocodes ORDER BY created_at DESC')
            return [dict(row) for row in cursor.fetchall()]
    
    def validate_promocode(self, code: str) -> Optional[Dict]:
        """Проверяет валидность промокода"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM promocodes WHERE code = ? AND is_active = 1', (code,))
            promo = cursor.fetchone()
            
            if not promo:
                return None
            
            promo = dict(promo)
            
            # Проверяем срок действия
            if promo['expires_at']:
                expires_at = datetime.fromisoformat(promo['expires_at'])
                if datetime.now() > expires_at:
                    return None
            
            # Проверяем лимит использований
            if promo['max_uses'] and promo['used_count'] >= promo['max_uses']:
                return None
            
            return promo
    
    def use_promocode(self, promocode_id: int, user_id: int, purchase_id: int = None):
        """Отмечает использование промокода"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Увеличиваем счетчик использований
            cursor.execute('''
                UPDATE promocodes 
                SET used_count = used_count + 1
                WHERE id = ?
            ''', (promocode_id,))
            
            # Записываем использование
            cursor.execute('''
                INSERT INTO promocode_uses (promocode_id, user_id, purchase_id)
                VALUES (?, ?, ?)
            ''', (promocode_id, user_id, purchase_id))
    
    def get_user_promocode_uses(self, user_id: int, promocode_id: int) -> int:
        """Получает количество использований промокода пользователем"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM promocode_uses WHERE user_id = ? AND promocode_id = ?', 
                         (user_id, promocode_id))
            return cursor.fetchone()['count']
    
    # Методы для работы с пользователями
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
    def create_purchase(self, user_id: int, product_id: int, quantity: int, 
                       amount_rub: float, amount_usd: float, crypto_payment_id: str,
                       promocode_id: int = None, discount_amount_rub: float = 0) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO purchases (user_id, product_id, quantity, amount_rub, amount_usd, 
                                      discount_amount_rub, promocode_id, crypto_payment_id, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, product_id, quantity, amount_rub, amount_usd, 
                  discount_amount_rub, promocode_id, crypto_payment_id, 'pending'))
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
                SELECT p.*, pr.name as product_name, pr.product_type
                FROM purchases p
                JOIN products pr ON p.product_id = pr.id
                WHERE p.user_id = ? AND p.status = 'completed'
                ORDER BY p.created_at DESC
            ''', (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_statistics(self) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) as count FROM users')
            users_count = cursor.fetchone()['count']
            
            cursor.execute("SELECT COUNT(*) as count FROM purchases WHERE status = 'completed'")
            purchases_count = cursor.fetchone()['count']
            
            cursor.execute("SELECT SUM(amount_rub) as total FROM purchases WHERE status = 'completed'")
            total_revenue = cursor.fetchone()['total'] or 0
            
            cursor.execute("SELECT SUM(discount_amount_rub) as total FROM purchases WHERE status = 'completed'")
            total_discounts = cursor.fetchone()['total'] or 0
            
            cursor.execute('SELECT COUNT(*) as count FROM products')
            products_count = cursor.fetchone()['count']
            
            cursor.execute('SELECT COUNT(*) as count FROM products WHERE product_type = "free"')
            free_products_count = cursor.fetchone()['count']
            
            cursor.execute('SELECT COUNT(*) as count FROM categories')
            categories_count = cursor.fetchone()['count']
            
            cursor.execute('SELECT SUM(amount_rub) as total FROM referral_payments')
            total_referral_bonuses = cursor.fetchone()['total'] or 0
            
            cursor.execute('SELECT COUNT(*) as count FROM promocodes')
            promocodes_count = cursor.fetchone()['count']
            
            return {
                'users_count': users_count,
                'purchases_count': purchases_count,
                'total_revenue': total_revenue,
                'total_discounts': total_discounts,
                'products_count': products_count,
                'free_products_count': free_products_count,
                'categories_count': categories_count,
                'total_referral_bonuses': total_referral_bonuses,
                'promocodes_count': promocodes_count
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
    free_emoji = db.get_emoji(EmojiType.FREE.value)
    stock_emoji = db.get_emoji(EmojiType.STOCK.value)
    profile_emoji = db.get_emoji(EmojiType.PROFILE.value)
    referral_emoji = db.get_emoji(EmojiType.REFERRAL.value)
    promo_emoji = db.get_emoji(EmojiType.PROMO.value)
    about_emoji = db.get_emoji(EmojiType.ABOUT.value)
    settings_emoji = db.get_emoji(EmojiType.SETTINGS.value)
    admin_emoji = db.get_emoji(EmojiType.ADMIN.value)
    
    builder.row(
        KeyboardButton(text=f"{buy_emoji} Купить товар"),
        KeyboardButton(text=f"{free_emoji} Бесплатно")
    )
    builder.row(
        KeyboardButton(text=f"{stock_emoji} Наличие товара"), 
        KeyboardButton(text=f"{profile_emoji} Профиль")
    )
    builder.row(
        KeyboardButton(text=f"{referral_emoji} Реферальная программа"),
        KeyboardButton(text=f"{promo_emoji} Промокод")
    )
    builder.row(KeyboardButton(text=f"{about_emoji} О нас"))
    
    # Кнопка настройки для первого пользователя, если настройки не завершены
    if not is_setup_complete:
        if settings.get('admin_id') is None:
            builder.row(KeyboardButton(text=f"{settings_emoji} Стать администратором"))
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
    promo_emoji = db.get_emoji(EmojiType.PROMO.value)
    settings_emoji = db.get_emoji(EmojiType.SETTINGS.value)
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    builder.row(KeyboardButton(text=f"{stats_emoji} Статистика"))
    builder.row(KeyboardButton(text=f"{newsletter_emoji} Рассылка"))
    builder.row(KeyboardButton(text=f"{category_emoji} Добавление категорий"))
    builder.row(KeyboardButton(text=f"{product_emoji} Добавление товаров"))
    builder.row(KeyboardButton(text=f"{promo_emoji} Управление промокодами"))
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

def get_product_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💰 Платный", callback_data="product_type_paid"),
        InlineKeyboardButton(text="🎁 Бесплатный", callback_data="product_type_free")
    )
    return builder.as_markup()

def get_categories_keyboard(product_type: str = None) -> InlineKeyboardMarkup:
    categories = db.get_categories()
    builder = InlineKeyboardBuilder()
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    for category in categories:
        callback_data = f"category_{category['id']}"
        if product_type:
            callback_data += f"_{product_type}"
        builder.row(InlineKeyboardButton(
            text=f"{category_emoji} {category['name']}",
            callback_data=callback_data
        ))
    
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_free_products_keyboard() -> InlineKeyboardMarkup:
    products = db.get_free_products()
    builder = InlineKeyboardBuilder()
    free_emoji = db.get_emoji(EmojiType.FREE.value)
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    for product in products:
        builder.row(InlineKeyboardButton(
            text=f"{free_emoji} {product['name']} (в наличии: {product['quantity']})",
            callback_data=f"free_product_{product['id']}"
        ))
    
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_products_keyboard(category_id: int, product_type: str = 'paid') -> InlineKeyboardMarkup:
    products = db.get_products_by_category(category_id, product_type)
    settings = db.get_settings()
    currency_symbol = Currency[settings['currency']].value
    builder = InlineKeyboardBuilder()
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    for product in products:
        if product_type == 'paid':
            price = product['price_rub'] if settings['currency'] == 'RUB' else product['price_usd']
            text = f"{product_emoji} {product['name']} - {price} {currency_symbol} (в наличии: {product['quantity']})"
        else:
            text = f"{product_emoji} {product['name']} (в наличии: {product['quantity']})"
        
        builder.row(InlineKeyboardButton(
            text=text,
            callback_data=f"product_{product['id']}_{product_type}"
        ))
    
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад к категориям", callback_data=f"back_to_categories_{product_type}"))
    return builder.as_markup()

def get_quantity_keyboard(product_id: int, max_quantity: int, product_type: str = 'paid') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    if product_type == 'paid':
        quantities = [1, 2, 3, 4, 5, 10]
        row = []
        for q in quantities:
            if q <= max_quantity:
                row.append(InlineKeyboardButton(text=str(q), callback_data=f"qty_{product_id}_{q}"))
        builder.row(*row)
        
        builder.row(InlineKeyboardButton(text="✏️ Своё количество", callback_data=f"qty_custom_{product_id}"))
    
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data=f"back_to_product_{product_id}_{product_type}"))
    
    return builder.as_markup()

def get_payment_keyboard(payment_url: str, purchase_id: int, with_promo: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    payment_emoji = db.get_emoji(EmojiType.PAYMENT.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    promo_emoji = db.get_emoji(EmojiType.PROMO.value)
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    
    builder.row(InlineKeyboardButton(text=f"{payment_emoji} Оплатить", url=payment_url))
    if with_promo:
        builder.row(InlineKeyboardButton(text=f"{promo_emoji} Применить промокод", callback_data=f"apply_promo_{purchase_id}"))
    builder.row(InlineKeyboardButton(text=f"{success_emoji} Проверить оплату", callback_data=f"check_payment_{purchase_id}"))
    builder.row(InlineKeyboardButton(text=f"{error_emoji} Отмена", callback_data="cancel_payment"))
    return builder.as_markup()

def get_back_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data="back"))
    return builder.as_markup()

def get_emojis_keyboard() -> InlineKeyboardMarkup:
    emojis = db.get_all_emojis()
    builder = InlineKeyboardBuilder()
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    for i in range(0, len(emojis), 2):
        row = []
        for j in range(2):
            if i + j < len(emojis):
                emoji = emojis[i + j]
                emoji_display = emoji['emoji_char']
                if emoji['is_premium']:
                    emoji_display = "⭐"
                row.append(InlineKeyboardButton(
                    text=f"{emoji_display} {emoji['emoji_type']}",
                    callback_data=f"edit_emoji_{emoji['emoji_type']}"
                ))
        builder.row(*row)
    
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data="back_to_admin"))
    return builder.as_markup()

def get_promocodes_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Создать промокод", callback_data="create_promo"))
    builder.row(InlineKeyboardButton(text="📋 Список промокодов", callback_data="list_promos"))
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_to_admin"))
    return builder.as_markup()

# ==================== Интеграция с Crypto Bot ====================

class CryptoBotAPI:
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://pay.crypt.bot/api"
    
    async def create_invoice(self, amount_usd: float, description: str) -> Optional[Dict]:
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
    
    args = message.text.split()
    referral_code = args[1] if len(args) > 1 else None
    
    db_user_id = db.register_user(user_id, username, first_name, referral_code)
    
    settings = db.get_settings()
    
    main_emoji = db.get_emoji(EmojiType.MAIN_MENU.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    welcome_text = f"{main_emoji} *{settings.get('bot_name', 'магазин')}*\n\n"
    welcome_text += settings.get('welcome_message', 'Добро пожаловать в магазин!')
    
    if referral_code:
        referrer = db.get_user_by_referral_code(referral_code)
        if referrer and referrer['telegram_id'] != user_id:
            welcome_text += f"\n\n{success_emoji} Вы перешли по реферальной ссылке!"
    
    if settings.get('admin_id') is None:
        welcome_text += f"\n\n⚡ Бот еще не настроен. Нажмите кнопку 'Стать администратором' для начала настройки."
    elif not settings.get('is_setup_complete'):
        welcome_text += f"\n\n⚡ Бот находится в режиме настройки. Используйте кнопку 'Настроить бота' для продолжения."
    
    await message.answer(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )

@dp.message(lambda message: message.text and "Стать администратором" in message.text)
async def become_admin(message: Message):
    settings = db.get_settings()
    
    if settings.get('admin_id') is not None:
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(
            f"{error_emoji} Администратор уже назначен.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    db.update_settings(admin_id=message.from_user.id)
    
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    await message.answer(
        f"{success_emoji} Вы назначены администратором!\n\n"
        f"Теперь нажмите кнопку 'Настроить бота' для продолжения настройки.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(lambda message: message.text and "Настроить бота" in message.text)
async def setup_bot(message: Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} У вас нет прав для настройки бота.")
        return
    
    settings = db.get_settings()
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏ Изменить имя бота", callback_data="setup_name"))
    builder.row(InlineKeyboardButton(text="📝 Изменить приветствие", callback_data="setup_welcome"))
    builder.row(InlineKeyboardButton(text="ℹ Изменить 'О нас'", callback_data="setup_about"))
    builder.row(InlineKeyboardButton(text="💱 Изменить валюту", callback_data="setup_currency"))
    builder.row(InlineKeyboardButton(text="🆔 Изменить admin id", callback_data="setup_admin_id"))
    builder.row(InlineKeyboardButton(text="🔑 Изменить Crypto Bot API", callback_data="setup_crypto_token"))
    
    if settings.get('admin_id') and settings.get('crypto_token'):
        builder.row(InlineKeyboardButton(text="▶ Запустить бота", callback_data="setup_complete"))
    
    await message.answer(
        "⚙ Меню настройки бота:\n\n"
        "Выберите, что хотите изменить:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("setup_"))
async def setup_callback(callback: CallbackQuery, state: FSMContext):
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
    
    elif action == "about":
        await callback.message.edit_text(
            "ℹ Введите новый текст для раздела 'О нас':",
            reply_markup=get_back_keyboard()
        )
        await state.set_state(SetupStates.waiting_for_about_message)
    
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
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Настройка отменена.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    db.update_settings(bot_name=message.text)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Имя бота изменено на: {message.text}",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(SetupStates.waiting_for_welcome_message)
async def process_welcome_message(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Настройка отменена.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    db.update_settings(welcome_message=message.text)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Приветственное сообщение изменено!",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(SetupStates.waiting_for_about_message)
async def process_about_message(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Настройка отменена.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    db.update_settings(about_message=message.text)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Сообщение 'О нас' изменено!",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.callback_query(SetupStates.waiting_for_currency, F.data.startswith("currency_"))
async def process_currency(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.replace("currency_", "").upper()
    
    db.update_settings(currency=currency)
    
    await state.clear()
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    await callback.message.edit_text(
        f"{success_emoji} Валюта изменена на: {'Рубли (₽)' if currency == 'RUB' else 'Доллары ($)'}"
    )
    await callback.answer()

@dp.message(SetupStates.waiting_for_admin_id)
async def process_admin_id(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Настройка отменена.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    if not message.text.isdigit():
        await message.answer(
            f"{error_emoji} Ошибка: admin ID должен быть числом. Попробуйте снова:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    admin_id = int(message.text)
    
    db.update_settings(admin_id=admin_id)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Admin ID изменен на: {admin_id}",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(SetupStates.waiting_for_crypto_token)
async def process_crypto_token(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Настройка отменена.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    if len(message.text) < 10:
        await message.answer(
            f"{error_emoji} Ошибка: неверный формат токена. Попробуйте снова:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    db.update_settings(crypto_token=message.text)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Crypto Bot API токен сохранен.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(lambda message: message.text and "Реферальная программа" in message.text)
async def referral_program(message: Message):
    user = db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(
            f"{error_emoji} Профиль не найден."
        )
        return
    
    stats = db.get_referral_stats(user['id'])
    referrals = db.get_referrals(user['id'])
    
    bot_username = (await bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user['referral_code']}"
    
    referral_emoji = db.get_emoji(EmojiType.REFERRAL.value)
    
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
        for ref in referrals[:10]:
            message_text += f"• {ref['first_name']} - {ref['registered_at']}\n"
    else:
        message_text += "• Пока нет приглашенных друзей"
    
    await message.answer(
        message_text,
        parse_mode="Markdown",
        reply_markup=get_back_keyboard()
    )

@dp.message(lambda message: message.text and "Промокод" in message.text)
async def promo_code(message: Message, state: FSMContext):
    """Обработчик ввода промокода"""
    promo_emoji = db.get_emoji(EmojiType.PROMO.value)
    await message.answer(
        f"{promo_emoji} Введите промокод:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(UserStates.waiting_for_promo_code)

@dp.message(UserStates.waiting_for_promo_code)
async def process_promo_code(message: Message, state: FSMContext):
    """Обработка введенного промокода"""
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Ввод промокода отменен.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    # Проверяем промокод
    promo = db.validate_promocode(message.text.upper())
    
    if not promo:
        await message.answer(
            f"{error_emoji} Промокод недействителен или истек.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        await state.clear()
        return
    
    # Получаем пользователя
    user = db.get_user_by_telegram_id(message.from_user.id)
    
    # Проверяем, не использовал ли пользователь уже этот промокод
    uses = db.get_user_promocode_uses(user['id'], promo['id'])
    if uses > 0:
        await message.answer(
            f"{error_emoji} Вы уже использовали этот промокод.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        await state.clear()
        return
    
    await state.update_data(promo_code=promo['code'], promo_discount=promo['discount_percent'])
    
    await message.answer(
        f"{success_emoji} Промокод активирован! Скидка: {promo['discount_percent']}%\n\n"
        f"Теперь можете совершить покупку со скидкой.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )
    await state.clear()

@dp.message(lambda message: message.text and "Бесплатно" in message.text)
async def free_products(message: Message):
    """Показ бесплатных товаров"""
    settings = db.get_settings()
    
    if not settings.get('is_setup_complete'):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(
            f"{error_emoji} Магазин еще не настроен. Дождитесь завершения настройки администратором."
        )
        return
    
    products = db.get_free_products()
    
    if not products:
        free_emoji = db.get_emoji(EmojiType.FREE.value)
        await message.answer(
            f"{free_emoji} В данный момент бесплатных товаров нет."
        )
        return
    
    free_emoji = db.get_emoji(EmojiType.FREE.value)
    await message.answer(
        f"{free_emoji} *Бесплатные товары:*\n\n"
        f"Выберите товар (можно забрать только один раз):",
        parse_mode="Markdown",
        reply_markup=get_free_products_keyboard()
    )

@dp.callback_query(F.data.startswith("free_product_"))
async def get_free_product(callback: CallbackQuery):
    """Получение бесплатного товара"""
    product_id = int(callback.data.replace("free_product_", ""))
    product = db.get_product(product_id)
    user = db.get_user_by_telegram_id(callback.from_user.id)
    
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if not product or product['quantity'] <= 0:
        await callback.message.edit_text(
            f"{error_emoji} Товар закончился.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    # Проверяем, забирал ли пользователь уже этот товар
    if db.has_user_claimed_free_product(user['id'], product_id):
        await callback.message.edit_text(
            f"{error_emoji} Вы уже забрали этот товар.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    # Отмечаем, что пользователь забрал товар
    if db.claim_free_product(user['id'], product_id):
        await callback.message.delete()
        await callback.message.answer(
            f"{success_emoji} *Ваш бесплатный товар:*\n\n"
            f"{product['content']}",
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(
            f"{error_emoji} Ошибка при получении товара.",
            reply_markup=get_back_keyboard()
        )
    
    await callback.answer()

@dp.message(lambda message: message.text and "Купить товар" in message.text)
async def buy_product(message: Message):
    settings = db.get_settings()
    
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
        reply_markup=get_categories_keyboard('paid')
    )

@dp.callback_query(F.data.startswith("category_"))
async def show_category_products(callback: CallbackQuery):
    data = callback.data.split("_")
    category_id = int(data[1])
    product_type = data[2] if len(data) > 2 else 'paid'
    
    category = db.get_category(category_id)
    products = db.get_products_by_category(category_id, product_type)
    
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    
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
        f"Выберите товар:",
        parse_mode="Markdown",
        reply_markup=get_products_keyboard(category_id, product_type)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("product_"))
async def show_product_details(callback: CallbackQuery):
    data = callback.data.split("_")
    product_id = int(data[1])
    product_type = data[2] if len(data) > 2 else 'paid'
    
    product = db.get_product(product_id)
    
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    
    if not product:
        await callback.message.edit_text(
            f"{error_emoji} Товар не найден.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    if product['quantity'] <= 0:
        await callback.message.edit_text(
            f"{error_emoji} Товар временно отсутствует.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    if product_type == 'paid':
        await callback.message.edit_text(
            f"{product_emoji} *{product['name']}*\n\n"
            f"{product['description']}\n\n"
            f"💰 Цена за единицу: {product['price_rub']} ₽ ({product['price_usd']} USDT)\n"
            f"📦 В наличии: {product['quantity']} шт.\n\n"
            f"Выберите количество:",
            parse_mode="Markdown",
            reply_markup=get_quantity_keyboard(product_id, product['quantity'], product_type)
        )
    else:
        await callback.message.edit_text(
            f"{product_emoji} *{product['name']}*\n\n"
            f"{product['description']}\n\n"
            f"📦 В наличии: {product['quantity']} шт.\n\n"
            f"Это бесплатный товар. Хотите получить?",
            parse_mode="Markdown",
            reply_markup=get_quantity_keyboard(product_id, product['quantity'], product_type)
        )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("qty_"))
async def process_quantity(callback: CallbackQuery, state: FSMContext):
    data = callback.data.split("_")
    
    if data[1] == "custom":
        product_id = int(data[2])
        await state.update_data(product_id=product_id)
        await callback.message.edit_text(
            "Введите нужное количество (целое число):",
            reply_markup=get_back_keyboard()
        )
        await state.set_state(UserStates.waiting_for_product_quantity)
    elif data[1] == "back":
        product_id = int(data[2])
        await show_product_details(callback)
    else:
        product_id = int(data[1])
        quantity = int(data[2])
        await callback.message.delete()
        await create_payment(callback.message, product_id, quantity, callback.from_user.id)
    
    await callback.answer()

@dp.callback_query(F.data.startswith("back_to_product_"))
async def back_to_product(callback: CallbackQuery):
    data = callback.data.split("_")
    product_id = int(data[3])
    product_type = data[4] if len(data) > 4 else 'paid'
    
    # Воссоздаем callback для показа товара
    callback.data = f"product_{product_id}_{product_type}"
    await show_product_details(callback)

@dp.callback_query(F.data.startswith("back_to_categories_"))
async def back_to_categories(callback: CallbackQuery):
    product_type = callback.data.replace("back_to_categories_", "")
    
    await callback.message.delete()
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    await callback.message.answer(
        f"{category_emoji} Выберите категорию:",
        reply_markup=get_categories_keyboard(product_type)
    )
    await callback.answer()

@dp.message(UserStates.waiting_for_product_quantity)
async def process_custom_quantity(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Выбор количества отменен.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    try:
        quantity = int(message.text)
        data = await state.get_data()
        product_id = data.get('product_id')
        product = db.get_product(product_id)
        
        if quantity <= 0:
            raise ValueError
        if quantity > product['quantity']:
            await message.answer(
                f"{error_emoji} В наличии только {product['quantity']} шт. Введите меньшее количество:",
                reply_markup=get_cancel_keyboard()
            )
            return
        
        await state.clear()
        await create_payment(message, product_id, quantity, message.from_user.id)
        
    except ValueError:
        await message.answer(
            f"{error_emoji} Пожалуйста, введите целое положительное число:",
            reply_markup=get_cancel_keyboard()
        )

async def create_payment(message: types.Message, product_id: int, quantity: int, user_id: int):
    product = db.get_product(product_id)
    settings = db.get_settings()
    
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    payment_emoji = db.get_emoji(EmojiType.PAYMENT.value)
    
    if not settings.get('crypto_token'):
        await message.answer(
            f"{error_emoji} Ошибка: платежная система не настроена. Обратитесь к администратору."
        )
        return
    
    user = db.get_user_by_telegram_id(user_id)
    if not user:
        user_id = db.register_user(
            user_id,
            message.from_user.username,
            message.from_user.first_name
        )
        user = {'id': user_id}
    
    total_rub = product['price_rub'] * quantity
    total_usd = round(total_rub / USDT_TO_RUB, 2)
    
    # Проверяем, есть ли активный промокод в состоянии
    # В реальном приложении нужно хранить промокод в БД или состоянии
    
    crypto_api = CryptoBotAPI(settings['crypto_token'])
    invoice = await crypto_api.create_invoice(
        amount_usd=total_usd,
        description=f"Покупка: {product['name']} x{quantity}"
    )
    
    if not invoice:
        await message.answer(
            f"{error_emoji} Ошибка при создании счета. Попробуйте позже."
        )
        return
    
    if not db.update_product_quantity(product_id, quantity):
        await message.answer(
            f"{error_emoji} Товар закончился. Попробуйте выбрать другое количество."
        )
        return
    
    purchase_id = db.create_purchase(
        user_id=user['id'],
        product_id=product_id,
        quantity=quantity,
        amount_rub=total_rub,
        amount_usd=total_usd,
        crypto_payment_id=str(invoice['invoice_id'])
    )
    
    await message.answer(
        f"{payment_emoji} *Счет на оплату:*\n\n"
        f"Товар: {product['name']}\n"
        f"Количество: {quantity} шт.\n"
        f"Сумма: {total_rub} ₽ ({total_usd} USDT)\n\n"
        f"Нажмите кнопку ниже для оплаты через @CryptoBot",
        parse_mode="Markdown",
        reply_markup=get_payment_keyboard(invoice['pay_url'], purchase_id)
    )

@dp.callback_query(F.data.startswith("apply_promo_"))
async def apply_promo_to_purchase(callback: CallbackQuery, state: FSMContext):
    purchase_id = int(callback.data.replace("apply_promo_", ""))
    purchase = db.get_purchase(purchase_id)
    
    if not purchase or purchase['status'] != 'pending':
        await callback.answer("Платеж уже обработан")
        return
    
    await state.update_data(purchase_id=purchase_id)
    promo_emoji = db.get_emoji(EmojiType.PROMO.value)
    await callback.message.edit_text(
        f"{promo_emoji} Введите промокод для скидки:",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(UserStates.waiting_for_promo_code)
    await callback.answer()

@dp.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: CallbackQuery):
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
        await deliver_product(callback.message, purchase)
        await callback.answer()
        return
    
    settings = db.get_settings()
    crypto_api = CryptoBotAPI(settings['crypto_token'])
    status = await crypto_api.check_invoice_status(int(purchase['crypto_payment_id']))
    
    if status == 'paid':
        db.complete_purchase(purchase_id)
        db.update_user_stats(purchase['user_id'], purchase['amount_rub'])
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
    product = db.get_product(purchase['product_id'])
    
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    
    if not product:
        await message.answer(
            f"{error_emoji} Ошибка: товар не найден. Обратитесь к администратору."
        )
        return
    
    discount_text = ""
    if purchase['discount_amount_rub'] > 0:
        discount_text = f"Скидка: {purchase['discount_amount_rub']} ₽\n"
    
    await message.answer(
        f"{success_emoji} *Оплата получена!*\n\n"
        f"{product_emoji} *Ваш товар:*\n\n"
        f"Наименование: {product['name']}\n"
        f"Количество: {purchase['quantity']} шт.\n"
        f"{discount_text}"
        f"Сумма: {purchase['amount_rub']} ₽\n\n"
        f"*Контент:*\n{product['content']}",
        parse_mode="Markdown"
    )
    
    await message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(message.chat.id)
    )

@dp.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    await callback.message.edit_text(
        f"{error_emoji} Платеж отменен."
    )
    
    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.message(lambda message: message.text and "Наличие товара" in message.text)
async def check_stock(message: Message):
    settings = db.get_settings()
    
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
    free_emoji = db.get_emoji(EmojiType.FREE.value)
    
    message_text = f"{stock_emoji} *Наличие товаров:*\n\n"
    
    for category in categories:
        category_products = db.get_products_by_category(category['id'])
        if category_products:
            message_text += f"{category_emoji} *{category['name']}:*\n"
            for product in category_products:
                if product['product_type'] == 'paid':
                    price = product['price_rub'] if settings['currency'] == 'RUB' else product['price_usd']
                    message_text += f"  • {product['name']} - {price} {currency_symbol} (в наличии: {product['quantity']} шт.)\n"
                else:
                    message_text += f"  • {free_emoji} {product['name']} - Бесплатно (в наличии: {product['quantity']} шт.)\n"
            message_text += "\n"
    
    await message.answer(message_text, parse_mode="Markdown")

@dp.message(lambda message: message.text and "Профиль" in message.text)
async def show_profile(message: Message):
    user = db.get_user_by_telegram_id(message.from_user.id)
    
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    profile_emoji = db.get_emoji(EmojiType.PROFILE.value)
    
    if not user:
        await message.answer(
            f"{error_emoji} Профиль не найден. Начните с команды /start"
        )
        return
    
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
        for purchase in purchases[:5]:
            if purchase['product_type'] == 'free':
                profile_text += f"  • 🎁 {purchase['product_name']} - Бесплатно ({purchase['created_at']})\n"
            else:
                profile_text += f"  • {purchase['product_name']} x{purchase['quantity']} - {purchase['amount_rub']:.2f} ₽ ({purchase['created_at']})\n"
    
    await message.answer(profile_text, parse_mode="Markdown")

@dp.message(lambda message: message.text and "О нас" in message.text)
async def about(message: Message):
    settings = db.get_settings()
    currency_symbol = Currency[settings['currency']].value
    
    about_emoji_formatted = db.format_emoji(EmojiType.ABOUT.value)
    about_text = settings.get('about_message', 'Информация о магазине')
    
    await message.answer(
        f"{about_emoji_formatted} *О магазине '{settings.get('bot_name')}':*\n\n"
        f"{about_text}",
        parse_mode="HTML"
    )

@dp.message(lambda message: message.text and "Админ панель" in message.text)
async def admin_panel(message: Message):
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
    if not db.is_admin(message.from_user.id):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} У вас нет доступа к этой функции.")
        return
    
    stats = db.get_statistics()
    stats_emoji = db.get_emoji(EmojiType.STATS.value)
    
    await message.answer(
        f"{stats_emoji} *Статистика магазина:*\n\n"
        f"👥 Пользователей: {stats['users_count']}\n"
        f"📦 Всего товаров: {stats['products_count']}\n"
        f"🎁 Бесплатных товаров: {stats['free_products_count']}\n"
        f"📁 Категорий: {stats['categories_count']}\n"
        f"🛍 Покупок: {stats['purchases_count']}\n"
        f"💰 Оборот: {stats['total_revenue']:.2f} ₽\n"
        f"🏷 Сумма скидок: {stats['total_discounts']:.2f} ₽\n"
        f"🎟 Промокодов: {stats['promocodes_count']}\n"
        f"🎁 Реферальных выплат: {stats['total_referral_bonuses']:.2f} ₽",
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.text and "Управление промокодами" in message.text)
async def manage_promocodes(message: Message):
    if not db.is_admin(message.from_user.id):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} У вас нет доступа к этой функции.")
        return
    
    promo_emoji = db.get_emoji(EmojiType.PROMO.value)
    await message.answer(
        f"{promo_emoji} *Управление промокодами*\n\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=get_promocodes_keyboard()
    )

@dp.callback_query(F.data == "create_promo")
async def create_promo_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите код промокода (или отправьте 'случайный' для генерации):",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_promo_code)
    await callback.answer()

@dp.message(AdminStates.waiting_for_promo_code)
async def process_promo_code(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Создание промокода отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    if message.text.lower() == 'случайный':
        code = db.generate_promo_code()
    else:
        code = message.text.upper()
    
    await state.update_data(promo_code=code)
    await message.answer(
        f"Введите размер скидки в процентах (число от 1 до 100):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_promo_discount)

@dp.message(AdminStates.waiting_for_promo_discount)
async def process_promo_discount(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Создание промокода отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    try:
        discount = int(message.text)
        if discount < 1 or discount > 100:
            raise ValueError
    except ValueError:
        await message.answer(
            f"{error_emoji} Введите число от 1 до 100:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(promo_discount=discount)
    await message.answer(
        "Введите максимальное количество использований (или 0 для безлимита):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_promo_expiry)

@dp.message(AdminStates.waiting_for_promo_expiry)
async def process_promo_expiry(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Создание промокода отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    try:
        max_uses = int(message.text)
        if max_uses < 0:
            raise ValueError
        if max_uses == 0:
            max_uses = None
    except ValueError:
        await message.answer(
            f"{error_emoji} Введите целое неотрицательное число:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    data = await state.get_data()
    
    promo_id = db.add_promocode(
        code=data['promo_code'],
        discount_percent=data['promo_discount'],
        max_uses=max_uses
    )
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Промокод создан!\n\n"
        f"Код: {data['promo_code']}\n"
        f"Скидка: {data['promo_discount']}%\n"
        f"Макс. использований: {max_uses if max_uses else 'Безлимит'}",
        reply_markup=get_admin_panel_keyboard()
    )

@dp.callback_query(F.data == "list_promos")
async def list_promocodes(callback: CallbackQuery):
    promocodes = db.get_all_promocodes()
    promo_emoji = db.get_emoji(EmojiType.PROMO.value)
    
    if not promocodes:
        await callback.message.edit_text(
            f"{promo_emoji} Промокоды не созданы.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    text = f"{promo_emoji} *Список промокодов:*\n\n"
    
    for promo in promocodes:
        status = "✅ Активен" if promo['is_active'] else "❌ Неактивен"
        expires = f"Истекает: {promo['expires_at']}" if promo['expires_at'] else "Без срока"
        uses = f"Использовано: {promo['used_count']}/{promo['max_uses'] if promo['max_uses'] else '∞'}"
        
        text += (
            f"• *{promo['code']}*\n"
            f"  Скидка: {promo['discount_percent']}%\n"
            f"  {uses}\n"
            f"  {expires}\n"
            f"  {status}\n\n"
        )
    
    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=get_back_keyboard()
    )
    await callback.answer()

@dp.message(lambda message: message.text and "Добавление категорий" in message.text)
async def add_category_start(message: Message, state: FSMContext):
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
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Добавление категории отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    await state.update_data(category_name=message.text)
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    await message.answer(
        f"{category_emoji} Введите описание категории:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_category_description)

@dp.message(AdminStates.waiting_for_category_description)
async def process_category_description(message: Message, state: FSMContext):
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
    
    category_id = db.add_category(category_name, message.text)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Категория '{category_name}' успешно добавлена!",
        reply_markup=get_admin_panel_keyboard()
    )

@dp.message(lambda message: message.text and "Добавление товаров" in message.text)
async def add_product_start(message: Message, state: FSMContext):
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
    
    await message.answer(
        "Выберите тип товара:",
        reply_markup=get_product_type_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_product_type)

@dp.callback_query(AdminStates.waiting_for_product_type, F.data.startswith("product_type_"))
async def process_product_type(callback: CallbackQuery, state: FSMContext):
    product_type = callback.data.replace("product_type_", "")
    await state.update_data(product_type=product_type)
    
    # Показываем список категорий для выбора
    categories = db.get_categories()
    builder = InlineKeyboardBuilder()
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    for category in categories:
        builder.row(InlineKeyboardButton(
            text=f"{category_emoji} {category['name']}",
            callback_data=f"add_product_cat_{category['id']}"
        ))
    
    await callback.message.edit_text(
        "Выберите категорию для товара:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.waiting_for_product_category)
    await callback.answer()

@dp.callback_query(AdminStates.waiting_for_product_category, F.data.startswith("add_product_cat_"))
async def process_product_category(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.replace("add_product_cat_", ""))
    await state.update_data(product_category_id=category_id)
    
    await callback.message.edit_text(
        "Введите название товара:"
    )
    await state.set_state(AdminStates.waiting_for_product_name)
    await callback.answer()

@dp.message(AdminStates.waiting_for_product_name)
async def process_product_name(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Добавление товара отменено.",
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
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Добавление товара отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    await state.update_data(product_description=message.text)
    
    data = await state.get_data()
    if data.get('product_type') == 'paid':
        await message.answer(
            "Введите цену товара в рублях (число, например: 1000):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(AdminStates.waiting_for_product_price)
    else:
        # Для бесплатных товаров цена 0
        await state.update_data(product_price=0)
        await message.answer(
            "Введите количество товара в наличии (целое число):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(AdminStates.waiting_for_product_quantity)

@dp.message(AdminStates.waiting_for_product_price)
async def process_product_price(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Добавление товара отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
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
        "Введите количество товара в наличии (целое число):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_product_quantity)

@dp.message(AdminStates.waiting_for_product_quantity)
async def process_product_quantity(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Добавление товара отменено.",
            reply_markup=get_admin_panel_keyboard()
        )
        return
    
    try:
        quantity = int(message.text)
        if quantity < 0:
            raise ValueError
    except ValueError:
        await message.answer(
            f"{error_emoji} Ошибка: введите целое неотрицательное число.",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(product_quantity=quantity)
    await message.answer(
        "Отправьте фото товара (необязательно, для пропуска отправьте 'пропустить'):\n"
        "Или отправьте фото:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_product_photo)

@dp.message(AdminStates.waiting_for_product_photo)
async def process_product_photo(message: Message, state: FSMContext):
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
        pass
    elif message.photo:
        photo_file_id = message.photo[-1].file_id
    else:
        await message.answer(
            f"{error_emoji} Пожалуйста, отправьте фото или напишите 'пропустить':",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(product_photo=photo_file_id)
    await message.answer(
        "Введите контент товара (ссылку, текст или файл, который получит пользователь):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_product_content)

@dp.message(AdminStates.waiting_for_product_content)
async def process_product_content(message: Message, state: FSMContext):
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
    
    product_id = db.add_product(
        category_id=data['product_category_id'],
        name=data['product_name'],
        description=data['product_description'],
        price_rub=data['product_price'],
        quantity=data['product_quantity'],
        product_type=data['product_type'],
        content=message.text,
        photo_file_id=data.get('product_photo')
    )
    
    product_type_text = "Бесплатный" if data['product_type'] == 'free' else "Платный"
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Товар '{data['product_name']}' успешно добавлен!\n"
        f"Тип: {product_type_text}\n"
        f"Количество: {data['product_quantity']} шт.",
        reply_markup=get_admin_panel_keyboard()
    )

@dp.message(lambda message: message.text and "Управление эмодзи" in message.text)
async def manage_emojis(message: Message, state: FSMContext):
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
    emoji_type = callback.data.replace("edit_emoji_", "")
    await state.update_data(editing_emoji=emoji_type)
    
    current_emoji = db.get_emoji(emoji_type)
    
    text = (
        f"Редактирование эмодзи: *{emoji_type}*\n\n"
        f"Текущий эмодзи: {current_emoji}\n\n"
        f"Отправьте новый эмодзи в одном из форматов:\n"
        f"1️⃣ Обычный смайлик (например: 🛒)\n"
        f"2️⃣ Премиум эмодзи в формате: `⭐|123456789` (где 123456789 - ID эмодзи)\n\n"
        f"Пример для премиум: `⭐|5447410659077661506`"
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
    
    if '|' in message.text:
        parts = message.text.split('|')
        if len(parts) == 2:
            emoji_char = parts[0].strip()
            premium_emoji_id = parts[1].strip()
            is_premium = True
        else:
            await message.answer(
                f"{error_emoji} Неверный формат. Используйте: `⭐|123456789`",
                parse_mode="Markdown",
                reply_markup=get_cancel_keyboard()
            )
            return
    else:
        emoji_char = message.text
        is_premium = False
        premium_emoji_id = None
    
    db.update_emoji(emoji_type, emoji_char, is_premium, premium_emoji_id)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Эмодзи для '{emoji_type}' обновлен!",
        reply_markup=get_admin_panel_keyboard()
    )

@dp.message(lambda message: message.text and "Рассылка" in message.text)
async def start_newsletter(message: Message, state: FSMContext):
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
            await asyncio.sleep(0.05)
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

@dp.message(lambda message: message.text and "Назад в главное меню" in message.text)
async def back_to_main(message: Message):
    await message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.callback_query(F.data == "back")
async def back_callback(callback: CallbackQuery):
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    await callback.message.delete()
    await callback.message.answer(
        f"{back_emoji} Действие отменено."
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin_callback(callback: CallbackQuery):
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
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    await message.answer(
        f"{error_emoji} Я не понимаю эту команду. Пожалуйста, используйте кнопки меню.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

# ==================== Запуск бота ====================

async def main():
    logger.info("Запуск бота...")
    
    settings = db.get_settings()
    logger.info(f"Текущие настройки: admin_id={settings.get('admin_id')}, setup_complete={settings.get('is_setup_complete')}")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
