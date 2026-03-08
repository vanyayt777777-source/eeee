import asyncio
import logging
import os
import sqlite3
import random
import string
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from enum import Enum
from contextlib import contextmanager

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Константы
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения")

USDT_TO_RUB = 95

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==================== Состояния FSM ====================

class SetupStates(StatesGroup):
    waiting_for_bot_name = State()
    waiting_for_welcome_message = State()
    waiting_for_about_message = State()
    waiting_for_currency = State()
    waiting_for_admin_id = State()
    waiting_for_crypto_token = State()
    waiting_for_support_chat = State()

class AdminStates(StatesGroup):
    waiting_for_newsletter_text = State()
    waiting_for_category_name = State()
    waiting_for_category_description = State()
    waiting_for_paid_product_category = State()
    waiting_for_paid_product_name = State()
    waiting_for_paid_product_description = State()
    waiting_for_paid_product_price = State()
    waiting_for_paid_product_quantity = State()
    waiting_for_paid_product_content = State()
    waiting_for_free_product_category = State()
    waiting_for_free_product_name = State()
    waiting_for_free_product_description = State()
    waiting_for_free_product_quantity = State()
    waiting_for_free_product_content = State()
    waiting_for_promo_code = State()
    waiting_for_promo_discount = State()
    waiting_for_promo_expiry = State()

class UserStates(StatesGroup):
    waiting_for_product_quantity = State()
    waiting_for_promo_code = State()
    waiting_for_support_message = State()

# ==================== Типы ====================

class Currency(Enum):
    RUB = "₽"
    USD = "$"

# ==================== База данных ====================

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
            
            # Настройки
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    bot_name TEXT DEFAULT 'Мой магазин',
                    welcome_message TEXT DEFAULT 'Добро пожаловать в магазин!',
                    about_message TEXT DEFAULT 'Информация о магазине',
                    support_chat_id INTEGER,
                    currency TEXT DEFAULT 'RUB',
                    admin_id INTEGER,
                    crypto_token TEXT,
                    is_setup_complete INTEGER DEFAULT 0
                )
            ''')
            
            # Категории
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    is_active INTEGER DEFAULT 1
                )
            ''')
            
            # Товары
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    price_rub REAL DEFAULT 0,
                    price_usd REAL DEFAULT 0,
                    quantity INTEGER DEFAULT 0,
                    product_type TEXT DEFAULT 'paid',
                    content TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE CASCADE
                )
            ''')
            
            # Бесплатные товары (кто забрал)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS free_products_claimed (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    UNIQUE(user_id, product_id)
                )
            ''')
            
            # Промокоды
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS promocodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    discount_percent INTEGER NOT NULL,
                    max_uses INTEGER,
                    used_count INTEGER DEFAULT 0,
                    expires_at TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                )
            ''')
            
            # Пользователи
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
                    total_spent_rub REAL DEFAULT 0
                )
            ''')
            
            # Покупки
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    amount_rub REAL NOT NULL,
                    amount_usd REAL NOT NULL,
                    promocode_id INTEGER,
                    crypto_payment_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (product_id) REFERENCES products (id)
                )
            ''')
            
            # Реферальные выплаты
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS referral_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER NOT NULL,
                    purchase_id INTEGER NOT NULL,
                    amount_rub REAL NOT NULL,
                    FOREIGN KEY (referrer_id) REFERENCES users (id),
                    FOREIGN KEY (purchase_id) REFERENCES purchases (id)
                )
            ''')
            
            # Поддержка
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    status TEXT DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            # Начальные настройки
            cursor.execute('SELECT * FROM settings WHERE id = 1')
            if not cursor.fetchone():
                cursor.execute('''
                    INSERT INTO settings (id, bot_name, welcome_message, about_message, currency, is_setup_complete)
                    VALUES (1, 'Мой магазин', 'Добро пожаловать в магазин!', 'Информация о магазине', 'RUB', 0)
                ''')
    
    # Настройки
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
            values.append(1)
            cursor.execute(f'UPDATE settings SET {", ".join(fields)} WHERE id = ?', values)
    
    def is_admin(self, telegram_id: int) -> bool:
        settings = self.get_settings()
        return settings.get('admin_id') == telegram_id
    
    # Пользователи
    def generate_referral_code(self) -> str:
        chars = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(chars, k=8))
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id FROM users WHERE referral_code = ?', (code,))
                if not cursor.fetchone():
                    return code
    
    def register_user(self, telegram_id: int, username: str, first_name: str, referred_by_code: str = None) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            existing = cursor.fetchone()
            if existing:
                return existing['id']
            
            referral_code = self.generate_referral_code()
            
            referred_by = None
            if referred_by_code:
                cursor.execute('SELECT id FROM users WHERE referral_code = ?', (referred_by_code,))
                referrer = cursor.fetchone()
                if referrer:
                    referred_by = referrer['id']
            
            cursor.execute('''
                INSERT INTO users (telegram_id, username, first_name, referred_by, referral_code)
                VALUES (?, ?, ?, ?, ?)
            ''', (telegram_id, username, first_name, referred_by, referral_code))
            
            return cursor.lastrowid
    
    def get_user(self, telegram_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_referral_stats(self, user_id: int) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM users WHERE referred_by = ?', (user_id,))
            referrals = cursor.fetchone()['count']
            cursor.execute('SELECT SUM(amount_rub) as total FROM referral_payments WHERE referrer_id = ?', (user_id,))
            earnings = cursor.fetchone()['total'] or 0
            return {'count': referrals, 'earnings': earnings}
    
    def get_referrals(self, user_id: int) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT first_name, registered_at FROM users WHERE referred_by = ? ORDER BY registered_at DESC', (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def add_referral_bonus(self, purchase_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p.*, u.referred_by 
                FROM purchases p
                JOIN users u ON p.user_id = u.id
                WHERE p.id = ? AND p.status = 'completed'
            ''', (purchase_id,))
            purchase = cursor.fetchone()
            
            if purchase and purchase['referred_by']:
                bonus = purchase['amount_rub'] * 0.1
                cursor.execute('UPDATE users SET referral_earnings = referral_earnings + ? WHERE id = ?', 
                             (bonus, purchase['referred_by']))
                cursor.execute('INSERT INTO referral_payments (referrer_id, purchase_id, amount_rub) VALUES (?, ?, ?)',
                             (purchase['referred_by'], purchase_id, bonus))
    
    # Категории
    def add_category(self, name: str, description: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO categories (name, description) VALUES (?, ?)', (name, description))
            return cursor.lastrowid
    
    def get_categories(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM categories WHERE is_active = 1 ORDER BY name')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_category(self, category_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM categories WHERE id = ?', (category_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    # Товары
    def add_product(self, category_id: int, name: str, description: str, price_rub: float, 
                   quantity: int, product_type: str, content: str) -> int:
        price_usd = round(price_rub / USDT_TO_RUB, 2) if price_rub > 0 else 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO products (category_id, name, description, price_rub, price_usd, quantity, product_type, content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (category_id, name, description, price_rub, price_usd, quantity, product_type, content))
            return cursor.lastrowid
    
    def get_products(self, category_id: int, product_type: str = None) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM products WHERE category_id = ? AND is_active = 1 AND quantity > 0'
            params = [category_id]
            if product_type:
                query += ' AND product_type = ?'
                params.append(product_type)
            query += ' ORDER BY name'
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_free_products(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM products WHERE product_type = "free" AND is_active = 1 AND quantity > 0 ORDER BY name')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_product(self, product_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def has_claimed_free(self, user_id: int, product_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM free_products_claimed WHERE user_id = ? AND product_id = ?', (user_id, product_id))
            return cursor.fetchone() is not None
    
    def claim_free_product(self, user_id: int, product_id: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('INSERT INTO free_products_claimed (user_id, product_id) VALUES (?, ?)', (user_id, product_id))
                cursor.execute('UPDATE products SET quantity = quantity - 1 WHERE id = ? AND quantity > 0', (product_id,))
                return True
            except:
                return False
    
    def update_quantity(self, product_id: int, quantity: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE products SET quantity = quantity - ? WHERE id = ? AND quantity >= ?', 
                         (quantity, product_id, quantity))
            return cursor.rowcount > 0
    
    # Промокоды
    def add_promocode(self, code: str, discount: int, max_uses: int = None) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO promocodes (code, discount_percent, max_uses) VALUES (?, ?, ?)',
                         (code, discount, max_uses))
            return cursor.lastrowid
    
    def get_promocode(self, code: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM promocodes WHERE code = ? AND is_active = 1', (code,))
            promo = cursor.fetchone()
            if not promo:
                return None
            promo = dict(promo)
            if promo['max_uses'] and promo['used_count'] >= promo['max_uses']:
                return None
            if promo['expires_at'] and datetime.fromisoformat(promo['expires_at']) < datetime.now():
                return None
            return promo
    
    def use_promocode(self, promo_id: int, user_id: int, purchase_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE promocodes SET used_count = used_count + 1 WHERE id = ?', (promo_id,))
    
    # Покупки
    def create_purchase(self, user_id: int, product_id: int, quantity: int, 
                       amount_rub: float, amount_usd: float, payment_id: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO purchases (user_id, product_id, quantity, amount_rub, amount_usd, crypto_payment_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, product_id, quantity, amount_rub, amount_usd, payment_id))
            return cursor.lastrowid
    
    def complete_purchase(self, purchase_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE purchases SET status = "completed" WHERE id = ?', (purchase_id,))
            cursor.execute('''
                UPDATE users 
                SET total_purchases = total_purchases + 1, total_spent_rub = total_spent_rub + (
                    SELECT amount_rub FROM purchases WHERE id = ?
                ) WHERE id = (SELECT user_id FROM purchases WHERE id = ?)
            ''', (purchase_id, purchase_id))
    
    def get_purchase(self, purchase_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM purchases WHERE id = ?', (purchase_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_user_purchases(self, user_id: int) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p.*, pr.name as product_name, pr.product_type
                FROM purchases p
                JOIN products pr ON p.product_id = pr.id
                WHERE p.user_id = ? AND p.status = "completed"
                ORDER BY p.created_at DESC LIMIT 10
            ''', (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_users(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users')
            return [dict(row) for row in cursor.fetchall()]
    
    # Поддержка
    def create_ticket(self, user_id: int, message: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO support_tickets (user_id, message) VALUES (?, ?)', (user_id, message))
            return cursor.lastrowid
    
    # Статистика
    def get_stats(self) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM users')
            users = cursor.fetchone()['count']
            cursor.execute('SELECT COUNT(*) as count FROM purchases WHERE status = "completed"')
            purchases = cursor.fetchone()['count']
            cursor.execute('SELECT SUM(amount_rub) as total FROM purchases WHERE status = "completed"')
            revenue = cursor.fetchone()['total'] or 0
            cursor.execute('SELECT COUNT(*) as count FROM products WHERE is_active = 1')
            products = cursor.fetchone()['count']
            cursor.execute('SELECT COUNT(*) as count FROM categories WHERE is_active = 1')
            categories = cursor.fetchone()['count']
            return {
                'users': users,
                'purchases': purchases,
                'revenue': revenue,
                'products': products,
                'categories': categories
            }

# Инициализация БД
db = Database()

# ==================== Клавиатуры ====================

def main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    settings = db.get_settings()
    is_admin = db.is_admin(user_id)
    
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="🛒 Купить товар"),
        KeyboardButton(text="🎁 Бесплатно")
    )
    builder.row(
        KeyboardButton(text="📦 Наличие"),
        KeyboardButton(text="👤 Профиль")
    )
    builder.row(
        KeyboardButton(text="🔗 Рефералка"),
        KeyboardButton(text="🎟 Промокод")
    )
    builder.row(
        KeyboardButton(text="🆘 Поддержка"),
        KeyboardButton(text="ℹ О нас")
    )
    
    if not settings.get('is_setup_complete'):
        if not settings.get('admin_id'):
            builder.row(KeyboardButton(text="⚙ Стать админом"))
        elif is_admin:
            builder.row(KeyboardButton(text="⚙ Настроить"))
    
    if is_admin and settings.get('is_setup_complete'):
        builder.row(KeyboardButton(text="🔧 Админ панель"))
    
    return builder.as_markup(resize_keyboard=True)

def admin_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📊 Статистика"))
    builder.row(KeyboardButton(text="📨 Рассылка"))
    builder.row(
        KeyboardButton(text="📁 Категории"),
        KeyboardButton(text="📦 Товары")
    )
    builder.row(
        KeyboardButton(text="💰 Добавить платный"),
        KeyboardButton(text="🎁 Добавить бесплатный")
    )
    builder.row(KeyboardButton(text="🎟 Промокоды"))
    builder.row(KeyboardButton(text="◀ Назад"))
    return builder.as_markup(resize_keyboard=True)

def categories_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cat in db.get_categories():
        builder.row(InlineKeyboardButton(
            text=f"📁 {cat['name']}",
            callback_data=f"cat_{cat['id']}"
        ))
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_main"))
    return builder.as_markup()

def free_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for prod in db.get_free_products():
        builder.row(InlineKeyboardButton(
            text=f"🎁 {prod['name']} ({prod['quantity']} шт.)",
            callback_data=f"free_{prod['id']}"
        ))
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_main"))
    return builder.as_markup()

def products_keyboard(category_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for prod in db.get_products(category_id, 'paid'):
        builder.row(InlineKeyboardButton(
            text=f"💰 {prod['name']} - {prod['price_rub']} ₽ ({prod['quantity']} шт.)",
            callback_data=f"prod_{prod['id']}"
        ))
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_cats"))
    return builder.as_markup()

def quantity_keyboard(product_id: int, max_qty: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    quantities = [1, 2, 3, 5, 10]
    row = []
    for q in quantities:
        if q <= max_qty:
            row.append(InlineKeyboardButton(text=str(q), callback_data=f"qty_{product_id}_{q}"))
    if row:
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="✏️ Своё", callback_data=f"custom_{product_id}"))
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data=f"back_prod_{product_id}"))
    return builder.as_markup()

def payment_keyboard(url: str, purchase_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Оплатить", url=url))
    builder.row(InlineKeyboardButton(text="✅ Проверить", callback_data=f"check_{purchase_id}"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_pay"))
    return builder.as_markup()

def back_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back"))
    return builder.as_markup()

def cancel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True)

# ==================== Crypto Bot API ====================

class CryptoBotAPI:
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://pay.crypt.bot/api"
    
    async def create_invoice(self, amount: float, description: str) -> Optional[Dict]:
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Crypto-Pay-API-Token": self.token}
                payload = {
                    "asset": "USDT",
                    "amount": str(amount),
                    "description": description,
                    "paid_btn_name": "callback",
                    "paid_btn_url": f"https://t.me/{(await bot.get_me()).username}"
                }
                async with session.post(f"{self.base_url}/createInvoice", headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('ok'):
                            return data['result']
        except Exception as e:
            logger.error(f"Ошибка создания инвойса: {e}")
        return None
    
    async def check_invoice(self, invoice_id: int) -> Optional[str]:
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Crypto-Pay-API-Token": self.token}
                async with session.get(f"{self.base_url}/getInvoices", headers=headers, 
                                     params={"invoice_ids": str(invoice_id)}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('ok') and data['result'].get('items'):
                            return data['result']['items'][0].get('status')
        except:
            pass
        return None

# ==================== Обработчики ====================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    args = message.text.split()
    ref_code = args[1] if len(args) > 1 else None
    
    db.register_user(user.id, user.username, user.first_name, ref_code)
    settings = db.get_settings()
    
    text = f"🏠 {settings['bot_name']}\n\n{settings['welcome_message']}"
    if ref_code:
        text += "\n\n✅ Вы перешли по реферальной ссылке!"
    
    await message.answer(text, reply_markup=main_keyboard(user.id))

# ==================== Настройка ====================

@dp.message(lambda m: m.text == "⚙ Стать админом")
async def become_admin(message: Message):
    if db.get_settings().get('admin_id'):
        await message.answer("❌ Админ уже есть", reply_markup=main_keyboard(message.from_user.id))
        return
    db.update_settings(admin_id=message.from_user.id)
    await message.answer("✅ Вы админ! Нажмите 'Настроить'", reply_markup=main_keyboard(message.from_user.id))

@dp.message(lambda m: m.text == "⚙ Настроить")
async def setup_menu(message: Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏ Имя", callback_data="setup_name"))
    builder.row(InlineKeyboardButton(text="📝 Приветствие", callback_data="setup_welcome"))
    builder.row(InlineKeyboardButton(text="ℹ О нас", callback_data="setup_about"))
    builder.row(InlineKeyboardButton(text="💬 Поддержка", callback_data="setup_support"))
    builder.row(InlineKeyboardButton(text="💱 Валюта", callback_data="setup_currency"))
    builder.row(InlineKeyboardButton(text="🆔 Admin ID", callback_data="setup_admin"))
    builder.row(InlineKeyboardButton(text="🔑 Crypto Token", callback_data="setup_token"))
    builder.row(InlineKeyboardButton(text="✅ Запустить", callback_data="setup_complete"))
    await message.answer("⚙ Настройка:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("setup_"))
async def setup_callback(callback: CallbackQuery, state: FSMContext):
    if not db.is_admin(callback.from_user.id):
        await callback.answer("❌ Нет прав")
        return
    
    action = callback.data.replace("setup_", "")
    messages = {
        "name": "✏ Введите имя бота:",
        "welcome": "📝 Введите приветствие:",
        "about": "ℹ Введите текст 'О нас':",
        "support": "💬 Введите ID чата поддержки (0 = отключить):",
        "admin": "🆔 Введите новый admin ID:",
        "token": "🔑 Введите Crypto Bot токен:"
    }
    
    if action in messages:
        await callback.message.edit_text(messages[action], reply_markup=back_keyboard())
        await state.set_state(getattr(SetupStates, f"waiting_for_{action}"))
    elif action == "currency":
        curr_builder = InlineKeyboardBuilder()
        curr_builder.row(
            InlineKeyboardButton(text="🇷🇺 RUB", callback_data="currency_RUB"),
            InlineKeyboardButton(text="🇺🇸 USD", callback_data="currency_USD")
        )
        await callback.message.edit_text("💱 Выберите валюту:", reply_markup=curr_builder.as_markup())
        await state.set_state(SetupStates.waiting_for_currency)
    elif action == "complete":
        db.update_settings(is_setup_complete=1)
        await callback.message.edit_text("✅ Бот запущен!")
        await callback.message.answer("Главное меню:", reply_markup=main_keyboard(callback.from_user.id))
    
    await callback.answer()

@dp.message(SetupStates.waiting_for_bot_name)
async def process_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=main_keyboard(message.from_user.id))
        return
    db.update_settings(bot_name=message.text)
    await state.clear()
    await message.answer(f"✅ Имя: {message.text}", reply_markup=main_keyboard(message.from_user.id))

@dp.message(SetupStates.waiting_for_welcome_message)
async def process_welcome(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=main_keyboard(message.from_user.id))
        return
    db.update_settings(welcome_message=message.text)
    await state.clear()
    await message.answer("✅ Приветствие изменено", reply_markup=main_keyboard(message.from_user.id))

@dp.message(SetupStates.waiting_for_about_message)
async def process_about(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=main_keyboard(message.from_user.id))
        return
    db.update_settings(about_message=message.text)
    await state.clear()
    await message.answer("✅ О нас изменено", reply_markup=main_keyboard(message.from_user.id))

@dp.message(SetupStates.waiting_for_support_chat)
async def process_support(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=main_keyboard(message.from_user.id))
        return
    try:
        chat_id = int(message.text)
        db.update_settings(support_chat_id=None if chat_id == 0 else chat_id)
        await state.clear()
        await message.answer("✅ Чат поддержки изменен", reply_markup=main_keyboard(message.from_user.id))
    except:
        await message.answer("❌ Введите число", reply_markup=cancel_keyboard())

@dp.callback_query(SetupStates.waiting_for_currency, F.data.startswith("currency_"))
async def process_currency(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.replace("currency_", "")
    db.update_settings(currency=currency)
    await state.clear()
    await callback.message.edit_text(f"✅ Валюта: {currency}")
    await callback.answer()

@dp.message(SetupStates.waiting_for_admin_id)
async def process_admin_id(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=main_keyboard(message.from_user.id))
        return
    try:
        admin_id = int(message.text)
        db.update_settings(admin_id=admin_id)
        await state.clear()
        await message.answer(f"✅ Admin ID: {admin_id}", reply_markup=main_keyboard(message.from_user.id))
    except:
        await message.answer("❌ Введите число", reply_markup=cancel_keyboard())

@dp.message(SetupStates.waiting_for_crypto_token)
async def process_token(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=main_keyboard(message.from_user.id))
        return
    db.update_settings(crypto_token=message.text)
    await state.clear()
    await message.answer("✅ Токен сохранен", reply_markup=main_keyboard(message.from_user.id))

# ==================== Пользовательские функции ====================

@dp.message(lambda m: m.text == "👤 Профиль")
async def profile(message: Message):
    user = db.get_user(message.from_user.id)
    if not user:
        return
    
    purchases = db.get_user_purchases(user['id'])
    stats = db.get_referral_stats(user['id'])
    
    text = f"👤 Профиль\n\nID: {user['telegram_id']}\nИмя: {user['first_name']}\n"
    text += f"Покупок: {user['total_purchases']}\nПотрачено: {user['total_spent_rub']:.2f} ₽\n"
    text += f"Рефералов: {stats['count']}\nЗаработано: {stats['earnings']:.2f} ₽\n\n"
    
    if purchases:
        text += "📋 Последние покупки:\n"
        for p in purchases:
            if p['product_type'] == 'free':
                text += f"• 🎁 {p['product_name']}\n"
            else:
                text += f"• {p['product_name']} x{p['quantity']} - {p['amount_rub']} ₽\n"
    
    await message.answer(text)

@dp.message(lambda m: m.text == "🔗 Рефералка")
async def referral(message: Message):
    user = db.get_user(message.from_user.id)
    if not user:
        return
    
    bot_username = (await bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={user['referral_code']}"
    stats = db.get_referral_stats(user['id'])
    referrals = db.get_referrals(user['id'])
    
    text = f"🔗 Реферальная программа\n\nПриглашайте друзей и получайте 10% от их покупок!\n\n"
    text += f"📊 Статистика:\n• Приглашено: {stats['count']}\n• Заработано: {stats['earnings']:.2f} ₽\n\n"
    text += f"🔗 Ваша ссылка:\n{link}\n\n"
    
    if referrals:
        text += "👥 Приглашенные:\n"
        for ref in referrals:
            text += f"• {ref['first_name']}\n"
    
    await message.answer(text)

@dp.message(lambda m: m.text == "🎟 Промокод")
async def promo(message: Message, state: FSMContext):
    await message.answer("🎟 Введите промокод:", reply_markup=cancel_keyboard())
    await state.set_state(UserStates.waiting_for_promo_code)

@dp.message(UserStates.waiting_for_promo_code)
async def process_promo(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=main_keyboard(message.from_user.id))
        return
    
    promo = db.get_promocode(message.text.upper())
    if promo:
        await state.update_data(promo=promo)
        await message.answer(f"✅ Промокод активирован! Скидка: {promo['discount_percent']}%", 
                           reply_markup=main_keyboard(message.from_user.id))
    else:
        await message.answer("❌ Недействителен", reply_markup=main_keyboard(message.from_user.id))
        await state.clear()

@dp.message(lambda m: m.text == "🆘 Поддержка")
async def support(message: Message, state: FSMContext):
    settings = db.get_settings()
    if not settings.get('support_chat_id'):
        await message.answer("🆘 Поддержка временно недоступна")
        return
    
    await message.answer("📝 Опишите вашу проблему:", reply_markup=cancel_keyboard())
    await state.set_state(UserStates.waiting_for_support_message)

@dp.message(UserStates.waiting_for_support_message)
async def process_support(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=main_keyboard(message.from_user.id))
        return
    
    user = db.get_user(message.from_user.id)
    ticket_id = db.create_ticket(user['id'], message.text)
    
    settings = db.get_settings()
    if settings.get('support_chat_id'):
        try:
            await bot.send_message(
                settings['support_chat_id'],
                f"🆘 Новое обращение #{ticket_id}\n\nОт: {message.from_user.full_name}\nСообщение: {message.text}"
            )
        except:
            pass
    
    await state.clear()
    await message.answer(f"✅ Обращение #{ticket_id} принято!", reply_markup=main_keyboard(message.from_user.id))

@dp.message(lambda m: m.text == "ℹ О нас")
async def about(message: Message):
    settings = db.get_settings()
    await message.answer(f"ℹ {settings['about_message']}")

@dp.message(lambda m: m.text == "📦 Наличие")
async def stock(message: Message):
    settings = db.get_settings()
    categories = db.get_categories()
    
    if not categories:
        await message.answer("❌ Товаров нет")
        return
    
    text = "📦 Наличие:\n\n"
    for cat in categories:
        products = db.get_products(cat['id'])
        if products:
            text += f"📁 {cat['name']}:\n"
            for p in products:
                price = p['price_rub'] if settings['currency'] == 'RUB' else p['price_usd']
                symbol = "₽" if settings['currency'] == 'RUB' else "$"
                text += f"  • {p['name']} - {price} {symbol} ({p['quantity']} шт.)\n"
            text += "\n"
    
    await message.answer(text)

# ==================== Бесплатные товары ====================

@dp.message(lambda m: m.text == "🎁 Бесплатно")
async def free_menu(message: Message):
    if not db.get_free_products():
        await message.answer("🎁 Сейчас бесплатных товаров нет")
        return
    await message.answer("🎁 Выберите товар:", reply_markup=free_keyboard())

@dp.callback_query(F.data.startswith("free_"))
async def free_product(callback: CallbackQuery):
    product_id = int(callback.data.replace("free_", ""))
    product = db.get_product(product_id)
    
    if not product or product['quantity'] <= 0:
        await callback.message.edit_text("❌ Товар закончился", reply_markup=back_keyboard())
        await callback.answer()
        return
    
    user = db.get_user(callback.from_user.id)
    if db.has_claimed_free(user['id'], product_id):
        await callback.message.edit_text("❌ Вы уже забрали этот товар", reply_markup=back_keyboard())
        await callback.answer()
        return
    
    await callback.message.edit_text(
        f"🎁 {product['name']}\n\n{product['description']}\n\n📦 В наличии: {product['quantity']} шт.\n\nЗабрать?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Забрать", callback_data=f"take_{product_id}")],
            [InlineKeyboardButton(text="◀ Назад", callback_data="back_free")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("take_"))
async def take_free(callback: CallbackQuery):
    product_id = int(callback.data.replace("take_", ""))
    product = db.get_product(product_id)
    user = db.get_user(callback.from_user.id)
    
    if not product or product['quantity'] <= 0:
        await callback.message.edit_text("❌ Товар закончился", reply_markup=back_keyboard())
        await callback.answer()
        return
    
    if db.claim_free_product(user['id'], product_id):
        await callback.message.delete()
        await callback.message.answer(f"✅ Ваш товар:\n\n{product['content']}", 
                                     reply_markup=main_keyboard(callback.from_user.id))
    else:
        await callback.message.edit_text("❌ Ошибка", reply_markup=back_keyboard())
    
    await callback.answer()

@dp.callback_query(F.data == "back_free")
async def back_free(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🎁 Выберите товар:", reply_markup=free_keyboard())
    await callback.answer()

# ==================== Платные товары ====================

@dp.message(lambda m: m.text == "🛒 Купить товар")
async def buy_menu(message: Message):
    categories = db.get_categories()
    if not categories:
        await message.answer("❌ Товаров нет")
        return
    await message.answer("📁 Выберите категорию:", reply_markup=categories_keyboard())

@dp.callback_query(F.data.startswith("cat_"))
async def show_products(callback: CallbackQuery):
    category_id = int(callback.data.replace("cat_", ""))
    products = db.get_products(category_id, 'paid')
    
    if not products:
        await callback.message.edit_text("❌ В этой категории нет товаров", reply_markup=back_keyboard())
        await callback.answer()
        return
    
    await callback.message.edit_text(
        f"📁 {db.get_category(category_id)['name']}\n\nВыберите товар:",
        reply_markup=products_keyboard(category_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("prod_"))
async def show_product(callback: CallbackQuery):
    product_id = int(callback.data.replace("prod_", ""))
    product = db.get_product(product_id)
    
    if not product or product['quantity'] <= 0:
        await callback.message.edit_text("❌ Товар отсутствует", reply_markup=back_keyboard())
        await callback.answer()
        return
    
    await callback.message.edit_text(
        f"💰 {product['name']}\n\n{product['description']}\n\n"
        f"Цена: {product['price_rub']} ₽ ({product['price_usd']} USDT)\n"
        f"В наличии: {product['quantity']} шт.\n\nВыберите количество:",
        reply_markup=quantity_keyboard(product_id, product['quantity'])
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("qty_"))
async def select_quantity(callback: CallbackQuery):
    _, product_id, quantity = callback.data.split("_")
    product_id, quantity = int(product_id), int(quantity)
    await callback.message.delete()
    await create_payment(callback.message, product_id, quantity, callback.from_user.id)
    await callback.answer()

@dp.callback_query(F.data.startswith("custom_"))
async def custom_quantity(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.replace("custom_", ""))
    await state.update_data(product_id=product_id)
    await callback.message.edit_text("✏️ Введите количество:", reply_markup=back_keyboard())
    await state.set_state(UserStates.waiting_for_product_quantity)
    await callback.answer()

@dp.message(UserStates.waiting_for_product_quantity)
async def process_custom_quantity(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=main_keyboard(message.from_user.id))
        return
    
    try:
        quantity = int(message.text)
        data = await state.get_data()
        product = db.get_product(data['product_id'])
        
        if not product:
            await message.answer("❌ Товар не найден", reply_markup=main_keyboard(message.from_user.id))
            await state.clear()
            return
        
        if quantity <= 0 or quantity > product['quantity']:
            await message.answer(f"❌ Введите от 1 до {product['quantity']}", reply_markup=cancel_keyboard())
            return
        
        await state.clear()
        await create_payment(message, data['product_id'], quantity, message.from_user.id)
    except:
        await message.answer("❌ Введите число", reply_markup=cancel_keyboard())

async def create_payment(message: types.Message, product_id: int, quantity: int, user_id: int):
    product = db.get_product(product_id)
    settings = db.get_settings()
    
    if not settings.get('crypto_token'):
        await message.answer("❌ Платежи не настроены")
        return
    
    total_rub = product['price_rub'] * quantity
    total_usd = round(total_rub / USDT_TO_RUB, 2)
    
    user = db.get_user(user_id)
    if not user:
        user_id = db.register_user(user_id, message.from_user.username, message.from_user.first_name)
        user = {'id': user_id}
    
    crypto = CryptoBotAPI(settings['crypto_token'])
    invoice = await crypto.create_invoice(total_usd, f"{product['name']} x{quantity}")
    
    if not invoice:
        await message.answer("❌ Ошибка создания счета")
        return
    
    if not db.update_quantity(product_id, quantity):
        await message.answer("❌ Товар закончился")
        return
    
    purchase_id = db.create_purchase(
        user['id'], product_id, quantity, total_rub, total_usd, str(invoice['invoice_id'])
    )
    
    await message.answer(
        f"💳 Счет на оплату:\n\n{product['name']} x{quantity}\nСумма: {total_rub} ₽ ({total_usd} USDT)",
        reply_markup=payment_keyboard(invoice['pay_url'], purchase_id)
    )

@dp.callback_query(F.data.startswith("check_"))
async def check_payment(callback: CallbackQuery):
    purchase_id = int(callback.data.replace("check_", ""))
    purchase = db.get_purchase(purchase_id)
    
    if not purchase:
        await callback.message.edit_text("❌ Платеж не найден", reply_markup=back_keyboard())
        await callback.answer()
        return
    
    if purchase['status'] == 'completed':
        await deliver_product(callback.message, purchase)
        await callback.answer()
        return
    
    settings = db.get_settings()
    crypto = CryptoBotAPI(settings['crypto_token'])
    status = await crypto.check_invoice(int(purchase['crypto_payment_id']))
    
    if status == 'paid':
        db.complete_purchase(purchase_id)
        db.add_referral_bonus(purchase_id)
        await deliver_product(callback.message, purchase)
    elif status == 'active':
        await callback.message.edit_text(
            "💳 Ожидает оплаты",
            reply_markup=payment_keyboard(f"https://t.me/CryptoBot?start={purchase['crypto_payment_id']}", purchase_id)
        )
    else:
        await callback.message.edit_text("❌ Платеж не найден", reply_markup=back_keyboard())
    
    await callback.answer()

async def deliver_product(message: types.Message, purchase: Dict):
    product = db.get_product(purchase['product_id'])
    await message.answer(f"✅ Оплачено!\n\n{product['content']}")
    await message.answer("Главное меню:", reply_markup=main_keyboard(message.chat.id))

@dp.callback_query(F.data == "cancel_pay")
async def cancel_payment(callback: CallbackQuery):
    await callback.message.edit_text("❌ Платеж отменен")
    await callback.message.answer("Главное меню:", reply_markup=main_keyboard(callback.from_user.id))
    await callback.answer()

@dp.callback_query(F.data == "back_cats")
async def back_to_cats(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("📁 Выберите категорию:", reply_markup=categories_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("back_prod_"))
async def back_to_prod(callback: CallbackQuery):
    product_id = int(callback.data.replace("back_prod_", ""))
    callback.data = f"prod_{product_id}"
    await show_product(callback)

# ==================== Админ-панель ====================

@dp.message(lambda m: m.text == "🔧 Админ панель")
async def admin_panel(message: Message):
    if not db.is_admin(message.from_user.id):
        return
    await message.answer("🔧 Админ панель", reply_markup=admin_keyboard())

@dp.message(lambda m: m.text == "📊 Статистика")
async def admin_stats(message: Message):
    if not db.is_admin(message.from_user.id):
        return
    stats = db.get_stats()
    await message.answer(
        f"📊 Статистика:\n\n👥 Пользователей: {stats['users']}\n"
        f"🛍 Покупок: {stats['purchases']}\n💰 Оборот: {stats['revenue']:.2f} ₽\n"
        f"📦 Товаров: {stats['products']}\n📁 Категорий: {stats['categories']}"
    )

@dp.message(lambda m: m.text == "📨 Рассылка")
async def newsletter_start(message: Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    await message.answer("📨 Введите текст рассылки:", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_newsletter_text)

@dp.message(AdminStates.waiting_for_newsletter_text)
async def newsletter_process(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    
    users = db.get_all_users()
    await message.answer(f"📨 Отправить {len(users)} пользователям?\n\n{message.text}")
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да", callback_data="newsletter_yes"),
        InlineKeyboardButton(text="❌ Нет", callback_data="newsletter_no")
    )
    await state.update_data(text=message.text)
    await message.answer("Подтвердите:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "newsletter_yes")
async def newsletter_send(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    users = db.get_all_users()
    sent = 0
    
    await callback.message.edit_text("📨 Отправка...")
    
    for user in users:
        try:
            await bot.send_message(user['telegram_id'], f"📨 Рассылка:\n\n{data['text']}")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    
    await state.clear()
    await callback.message.answer(f"✅ Отправлено: {sent}/{len(users)}", reply_markup=admin_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "newsletter_no")
async def newsletter_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отменено")
    await callback.message.answer("Админ панель:", reply_markup=admin_keyboard())
    await callback.answer()

# ==================== Категории ====================

@dp.message(lambda m: m.text == "📁 Категории")
async def manage_categories(message: Message):
    if not db.is_admin(message.from_user.id):
        return
    
    builder = InlineKeyboardBuilder()
    for cat in db.get_categories():
        builder.row(InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"edit_cat_{cat['id']}"))
    builder.row(InlineKeyboardButton(text="➕ Добавить", callback_data="add_cat"))
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_admin"))
    
    await message.answer("📁 Управление категориями:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "add_cat")
async def add_category(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📝 Введите название категории:", reply_markup=back_keyboard())
    await state.set_state(AdminStates.waiting_for_category_name)
    await callback.answer()

@dp.message(AdminStates.waiting_for_category_name)
async def process_cat_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    
    await state.update_data(name=message.text)
    await message.answer("📝 Введите описание категории:", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_category_description)

@dp.message(AdminStates.waiting_for_category_description)
async def process_cat_desc(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    
    data = await state.get_data()
    db.add_category(data['name'], message.text)
    await state.clear()
    await message.answer(f"✅ Категория '{data['name']}' добавлена", reply_markup=admin_keyboard())

# ==================== Платные товары (админ) ====================

@dp.message(lambda m: m.text == "💰 Добавить платный")
async def add_paid_start(message: Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    
    categories = db.get_categories()
    if not categories:
        await message.answer("❌ Сначала создайте категорию")
        return
    
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.row(InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"paid_cat_{cat['id']}"))
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_admin"))
    
    await message.answer("💰 Выберите категорию:", reply_markup=builder.as_markup())
    await state.set_state(AdminStates.waiting_for_paid_product_category)

@dp.callback_query(AdminStates.waiting_for_paid_product_category, F.data.startswith("paid_cat_"))
async def paid_category_selected(callback: CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.replace("paid_cat_", ""))
    await state.update_data(category_id=cat_id)
    await callback.message.edit_text("💰 Введите название товара:")
    await state.set_state(AdminStates.waiting_for_paid_product_name)
    await callback.answer()

@dp.message(AdminStates.waiting_for_paid_product_name)
async def paid_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    await state.update_data(name=message.text)
    await message.answer("💰 Введите описание:", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_paid_product_description)

@dp.message(AdminStates.waiting_for_paid_product_description)
async def paid_desc(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    await state.update_data(desc=message.text)
    await message.answer("💰 Введите цену в рублях:", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_paid_product_price)

@dp.message(AdminStates.waiting_for_paid_product_price)
async def paid_price(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    try:
        price = float(message.text)
        if price <= 0:
            raise ValueError
        await state.update_data(price=price)
        await message.answer("💰 Введите количество:", reply_markup=cancel_keyboard())
        await state.set_state(AdminStates.waiting_for_paid_product_quantity)
    except:
        await message.answer("❌ Введите положительное число", reply_markup=cancel_keyboard())

@dp.message(AdminStates.waiting_for_paid_product_quantity)
async def paid_quantity(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    try:
        quantity = int(message.text)
        if quantity < 0:
            raise ValueError
        await state.update_data(quantity=quantity)
        await message.answer("💰 Введите контент (что получит пользователь):", reply_markup=cancel_keyboard())
        await state.set_state(AdminStates.waiting_for_paid_product_content)
    except:
        await message.answer("❌ Введите целое неотрицательное число", reply_markup=cancel_keyboard())

@dp.message(AdminStates.waiting_for_paid_product_content)
async def paid_content(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    
    data = await state.get_data()
    db.add_product(data['category_id'], data['name'], data['desc'], 
                  data['price'], data['quantity'], 'paid', message.text)
    
    await state.clear()
    await message.answer(f"✅ Товар '{data['name']}' добавлен", reply_markup=admin_keyboard())

# ==================== Бесплатные товары (админ) ====================

@dp.message(lambda m: m.text == "🎁 Добавить бесплатный")
async def add_free_start(message: Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    
    categories = db.get_categories()
    if not categories:
        await message.answer("❌ Сначала создайте категорию")
        return
    
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.row(InlineKeyboardButton(text=f"📁 {cat['name']}", callback_data=f"free_cat_{cat['id']}"))
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_admin"))
    
    await message.answer("🎁 Выберите категорию:", reply_markup=builder.as_markup())
    await state.set_state(AdminStates.waiting_for_free_product_category)

@dp.callback_query(AdminStates.waiting_for_free_product_category, F.data.startswith("free_cat_"))
async def free_category_selected(callback: CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.replace("free_cat_", ""))
    await state.update_data(category_id=cat_id)
    await callback.message.edit_text("🎁 Введите название товара:")
    await state.set_state(AdminStates.waiting_for_free_product_name)
    await callback.answer()

@dp.message(AdminStates.waiting_for_free_product_name)
async def free_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    await state.update_data(name=message.text)
    await message.answer("🎁 Введите описание:", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_free_product_description)

@dp.message(AdminStates.waiting_for_free_product_description)
async def free_desc(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    await state.update_data(desc=message.text)
    await message.answer("🎁 Введите количество:", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_free_product_quantity)

@dp.message(AdminStates.waiting_for_free_product_quantity)
async def free_quantity(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    try:
        quantity = int(message.text)
        if quantity < 0:
            raise ValueError
        await state.update_data(quantity=quantity)
        await message.answer("🎁 Введите контент:", reply_markup=cancel_keyboard())
        await state.set_state(AdminStates.waiting_for_free_product_content)
    except:
        await message.answer("❌ Введите целое неотрицательное число", reply_markup=cancel_keyboard())

@dp.message(AdminStates.waiting_for_free_product_content)
async def free_content(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    
    data = await state.get_data()
    db.add_product(data['category_id'], data['name'], data['desc'], 
                  0, data['quantity'], 'free', message.text)
    
    await state.clear()
    await message.answer(f"✅ Бесплатный товар '{data['name']}' добавлен", reply_markup=admin_keyboard())

# ==================== Промокоды ====================

@dp.message(lambda m: m.text == "🎟 Промокоды")
async def promo_menu(message: Message):
    if not db.is_admin(message.from_user.id):
        return
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Создать", callback_data="create_promo"))
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_admin"))
    await message.answer("🎟 Управление промокодами:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "create_promo")
async def create_promo(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🎟 Введите код (или 'случайный'):", reply_markup=back_keyboard())
    await state.set_state(AdminStates.waiting_for_promo_code)
    await callback.answer()

@dp.message(AdminStates.waiting_for_promo_code)
async def promo_code(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    
    if message.text.lower() == 'случайный':
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    else:
        code = message.text.upper()
    
    await state.update_data(code=code)
    await message.answer("🎟 Введите скидку (%):", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_promo_discount)

@dp.message(AdminStates.waiting_for_promo_discount)
async def promo_discount(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    
    try:
        discount = int(message.text)
        if discount < 1 or discount > 100:
            raise ValueError
        await state.update_data(discount=discount)
        await message.answer("🎟 Введите лимит использований (0 = безлимит):", reply_markup=cancel_keyboard())
        await state.set_state(AdminStates.waiting_for_promo_expiry)
    except:
        await message.answer("❌ Введите число от 1 до 100", reply_markup=cancel_keyboard())

@dp.message(AdminStates.waiting_for_promo_expiry)
async def promo_expiry(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено", reply_markup=admin_keyboard())
        return
    
    try:
        max_uses = int(message.text)
        if max_uses < 0:
            raise ValueError
        max_uses = None if max_uses == 0 else max_uses
        
        data = await state.get_data()
        db.add_promocode(data['code'], data['discount'], max_uses)
        
        await state.clear()
        await message.answer(f"✅ Промокод {data['code']} создан", reply_markup=admin_keyboard())
    except:
        await message.answer("❌ Введите целое неотрицательное число", reply_markup=cancel_keyboard())

# ==================== Навигация ====================

@dp.message(lambda m: m.text == "◀ Назад")
async def back_to_admin(message: Message):
    await message.answer("🔧 Админ панель", reply_markup=admin_keyboard())

@dp.callback_query(F.data == "back_admin")
async def back_admin_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🔧 Админ панель", reply_markup=admin_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "back_main")
async def back_main_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=main_keyboard(callback.from_user.id))
    await callback.answer()

@dp.callback_query(F.data == "back")
async def back_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

@dp.message()
async def unknown(message: Message):
    await message.answer("❌ Используйте кнопки меню", reply_markup=main_keyboard(message.from_user.id))

# ==================== Запуск ====================

async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
