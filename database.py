import sqlite3
import random
import string
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from contextlib import contextmanager
from config import USDT_TO_RUB, logger

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
                    bot_description TEXT,
                    welcome_message TEXT NOT NULL DEFAULT 'Добро пожаловать в магазин!',
                    about_message TEXT NOT NULL DEFAULT 'Информация о магазине',
                    contact_info TEXT,
                    rules TEXT,
                    delivery_info TEXT,
                    payment_methods TEXT,
                    refund_policy TEXT,
                    support_chat_id INTEGER,
                    currency TEXT NOT NULL DEFAULT 'RUB',
                    admin_id INTEGER,
                    crypto_token TEXT,
                    min_order_amount REAL DEFAULT 0,
                    max_order_amount REAL DEFAULT 1000000,
                    discount_threshold REAL DEFAULT 5000,
                    discount_percent INTEGER DEFAULT 5,
                    referral_bonus_percent INTEGER DEFAULT 10,
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
                    is_active BOOLEAN DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
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
                    is_active BOOLEAN DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE CASCADE
                )
            ''')
            
            # Таблица бесплатных товаров
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
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT NOT NULL,
                    last_name TEXT,
                    language_code TEXT,
                    referred_by INTEGER,
                    referral_code TEXT UNIQUE,
                    referral_earnings REAL DEFAULT 0,
                    is_blocked BOOLEAN DEFAULT 0,
                    last_activity TIMESTAMP,
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
            
            # Таблица обращений в поддержку
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    admin_reply TEXT,
                    status TEXT DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            # Таблица отзывов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
                    comment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            # Создаем запись настроек, если её нет
            cursor.execute('SELECT * FROM settings WHERE id = 1')
            if not cursor.fetchone():
                from config import DEFAULT_EMOJIS
                cursor.execute('''
                    INSERT INTO settings (
                        id, bot_name, bot_description, welcome_message, about_message, 
                        contact_info, rules, delivery_info, payment_methods, refund_policy,
                        currency, admin_id, crypto_token, min_order_amount, max_order_amount,
                        discount_threshold, discount_percent, referral_bonus_percent, is_setup_complete
                    )
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    'Мой магазин',
                    'Лучший магазин в Telegram',
                    'Добро пожаловать в магазин!',
                    'Информация о магазине',
                    'Контактная информация',
                    'Правила магазина',
                    'Информация о доставке',
                    'Способы оплаты',
                    'Политика возврата',
                    'RUB',
                    None,
                    None,
                    0,
                    1000000,
                    5000,
                    5,
                    10,
                    0
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
            values.append(1)
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
        settings = self.get_settings()
        admin_id = settings.get('admin_id')
        return admin_id is not None and admin_id == telegram_id
    
    # Методы для работы с эмодзи
    def get_emoji(self, emoji_type: str) -> str:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT emoji_char FROM emojis WHERE emoji_type = ?', (emoji_type,))
            row = cursor.fetchone()
            if row:
                return row['emoji_char']
            from config import DEFAULT_EMOJIS
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
    
    # Методы для пользователей
    def generate_referral_code(self, length: int = 8) -> str:
        chars = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(chars, k=length))
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id FROM users WHERE referral_code = ?', (code,))
                if not cursor.fetchone():
                    return code
    
    def register_user(self, telegram_id: int, username: Optional[str], first_name: str, 
                     last_name: Optional[str] = None, language_code: Optional[str] = None, 
                     referred_by_code: str = None) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            existing = cursor.fetchone()
            if existing:
                cursor.execute('''
                    UPDATE users 
                    SET last_activity = CURRENT_TIMESTAMP,
                        username = ?,
                        first_name = ?,
                        last_name = ?,
                        language_code = ?
                    WHERE id = ?
                ''', (username, first_name, last_name, language_code, existing['id']))
                return existing['id']
            
            referral_code = self.generate_referral_code()
            
            referred_by = None
            if referred_by_code:
                cursor.execute('SELECT id FROM users WHERE referral_code = ?', (referred_by_code,))
                referrer = cursor.fetchone()
                if referrer and referrer['id'] != telegram_id:
                    referred_by = referrer['id']
            
            cursor.execute('''
                INSERT INTO users (telegram_id, username, first_name, last_name, language_code, referred_by, referral_code, last_activity)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (telegram_id, username, first_name, last_name, language_code, referred_by, referral_code))
            
            return cursor.lastrowid
    
    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_referral_stats(self, user_id: int) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM users WHERE referred_by = ?', (user_id,))
            referrals_count = cursor.fetchone()['count']
            
            cursor.execute('SELECT SUM(amount_rub) as total FROM referral_payments WHERE referrer_id = ?', (user_id,))
            total_earned = cursor.fetchone()['total'] or 0
            
            return {
                'referrals_count': referrals_count,
                'total_earned': total_earned
            }
    
    def get_referrals(self, user_id: int) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE referred_by = ? ORDER BY registered_at DESC', (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
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
            
            settings = self.get_settings()
            bonus_percent = settings.get('referral_bonus_percent', 10)
            bonus_amount = purchase['amount_rub'] * bonus_percent / 100
            
            cursor.execute('UPDATE users SET referral_earnings = referral_earnings + ? WHERE id = ?', 
                         (bonus_amount, purchase['referred_by']))
            
            cursor.execute('INSERT INTO referral_payments (referrer_id, purchase_id, amount_rub) VALUES (?, ?, ?)',
                         (purchase['referred_by'], purchase_id, bonus_amount))
            
            cursor.execute('UPDATE purchases SET referral_bonus_paid = 1 WHERE id = ?', (purchase_id,))
    
    # Методы для категорий
    def add_category(self, name: str, description: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO categories (name, description) VALUES (?, ?)', (name, description))
            return cursor.lastrowid
    
    def update_category(self, category_id: int, name: str = None, description: str = None, is_active: bool = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            params = []
            if name:
                updates.append("name = ?")
                params.append(name)
            if description:
                updates.append("description = ?")
                params.append(description)
            if is_active is not None:
                updates.append("is_active = ?")
                params.append(1 if is_active else 0)
            
            if updates:
                params.append(category_id)
                cursor.execute(f'UPDATE categories SET {", ".join(updates)} WHERE id = ?', params)
    
    def delete_category(self, category_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM categories WHERE id = ?', (category_id,))
    
    def get_categories(self, only_active: bool = True) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if only_active:
                cursor.execute('SELECT * FROM categories WHERE is_active = 1 ORDER BY sort_order, name')
            else:
                cursor.execute('SELECT * FROM categories ORDER BY sort_order, name')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_category(self, category_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM categories WHERE id = ?', (category_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    # Методы для товаров
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
    
    def update_product(self, product_id: int, **kwargs):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            params = []
            for key, value in kwargs.items():
                if key in ['name', 'description', 'price_rub', 'quantity', 'content', 'photo_file_id', 'is_active']:
                    if key == 'price_rub':
                        updates.append("price_rub = ?")
                        updates.append("price_usd = ?")
                        params.append(value)
                        params.append(round(value / USDT_TO_RUB, 2))
                    else:
                        updates.append(f"{key} = ?")
                        params.append(value)
            
            if updates:
                params.append(product_id)
                cursor.execute(f'UPDATE products SET {", ".join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?', params)
    
    def delete_product(self, product_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM products WHERE id = ?', (product_id,))
    
    def get_product(self, product_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_products_by_category(self, category_id: int, product_type: str = None, only_active: bool = True) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM products WHERE category_id = ?'
            params = [category_id]
            
            if only_active:
                query += ' AND is_active = 1'
            if product_type:
                query += ' AND product_type = ?'
                params.append(product_type)
            
            query += ' AND quantity > 0 ORDER BY sort_order, name'
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_products(self, only_active: bool = True) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM products'
            if only_active:
                query += ' WHERE is_active = 1'
            query += ' ORDER BY category_id, sort_order, name'
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_free_products(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM products WHERE product_type = "free" AND is_active = 1 AND quantity > 0 ORDER BY sort_order, name')
            return [dict(row) for row in cursor.fetchall()]
    
    def has_user_claimed_free_product(self, user_id: int, product_id: int) -> bool:
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
            except sqlite3.IntegrityError:
                return False
    
    def update_product_quantity(self, product_id: int, quantity: int) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE products SET quantity = quantity - ? WHERE id = ? AND quantity >= ?', (quantity, product_id, quantity))
            return cursor.rowcount > 0
    
    # Методы для промокодов
    def generate_promo_code(self, length: int = 8) -> str:
        chars = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(chars, k=length))
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id FROM promocodes WHERE code = ?', (code,))
                if not cursor.fetchone():
                    return code
    
    def add_promocode(self, code: str, discount_percent: int, max_uses: int = None, expires_days: int = None) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            expires_at = None
            if expires_days:
                expires_at = (datetime.now() + timedelta(days=expires_days)).isoformat()
            
            cursor.execute('INSERT INTO promocodes (code, discount_percent, max_uses, expires_at) VALUES (?, ?, ?, ?)',
                         (code, discount_percent, max_uses, expires_at))
            return cursor.lastrowid
    
    def update_promocode(self, promocode_id: int, **kwargs):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            params = []
            for key, value in kwargs.items():
                if key in ['discount_percent', 'max_uses', 'expires_at', 'is_active']:
                    updates.append(f"{key} = ?")
                    params.append(value)
            
            if updates:
                params.append(promocode_id)
                cursor.execute(f'UPDATE promocodes SET {", ".join(updates)} WHERE id = ?', params)
    
    def get_all_promocodes(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM promocodes ORDER BY created_at DESC')
            return [dict(row) for row in cursor.fetchall()]
    
    def validate_promocode(self, code: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM promocodes WHERE code = ? AND is_active = 1', (code,))
            promo = cursor.fetchone()
            
            if not promo:
                return None
            
            promo = dict(promo)
            
            if promo['expires_at']:
                expires_at = datetime.fromisoformat(promo['expires_at'])
                if datetime.now() > expires_at:
                    return None
            
            if promo['max_uses'] and promo['used_count'] >= promo['max_uses']:
                return None
            
            return promo
    
    def use_promocode(self, promocode_id: int, user_id: int, purchase_id: int = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE promocodes SET used_count = used_count + 1 WHERE id = ?', (promocode_id,))
            cursor.execute('INSERT INTO promocode_uses (promocode_id, user_id, purchase_id) VALUES (?, ?, ?)',
                         (promocode_id, user_id, purchase_id))
    
    def get_user_promocode_uses(self, user_id: int, promocode_id: int) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM promocode_uses WHERE user_id = ? AND promocode_id = ?', 
                         (user_id, promocode_id))
            return cursor.fetchone()['count']
    
    # Методы для пользователей
    def update_user_activity(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE id = ?', (user_id,))
    
    def update_user_stats(self, user_id: int, amount_rub: float):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET total_purchases = total_purchases + 1, total_spent_rub = total_spent_rub + ? WHERE id = ?',
                         (amount_rub, user_id))
    
    def get_all_users(self, only_active: bool = True) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if only_active:
                cursor.execute('SELECT * FROM users WHERE is_blocked = 0 ORDER BY registered_at DESC')
            else:
                cursor.execute('SELECT * FROM users ORDER BY registered_at DESC')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_users_count(self) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM users')
            return cursor.fetchone()['count']
    
    def get_active_users_count(self, days: int = 7) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            cursor.execute('SELECT COUNT(*) as count FROM users WHERE last_activity > ?', (cutoff,))
            return cursor.fetchone()['count']
    
    # Методы для покупок
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
            cursor.execute('UPDATE purchases SET status = "completed", completed_at = CURRENT_TIMESTAMP WHERE id = ?', (purchase_id,))
    
    def get_purchase(self, purchase_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM purchases WHERE id = ?', (purchase_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_purchases_by_user(self, user_id: int, limit: int = None) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT p.*, pr.name as product_name, pr.product_type
                FROM purchases p
                JOIN products pr ON p.product_id = pr.id
                WHERE p.user_id = ? AND p.status = 'completed'
                ORDER BY p.created_at DESC
            '''
            if limit:
                query += f' LIMIT {limit}'
            cursor.execute(query, (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    # Статистика
    def get_statistics(self) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) as count FROM users')
            users_count = cursor.fetchone()['count']
            
            active_users_7d = self.get_active_users_count(7)
            active_users_30d = self.get_active_users_count(30)
            
            cursor.execute("SELECT COUNT(*) as count FROM purchases WHERE status = 'completed'")
            purchases_count = cursor.fetchone()['count']
            
            cursor.execute("SELECT SUM(amount_rub) as total FROM purchases WHERE status = 'completed'")
            total_revenue = cursor.fetchone()['total'] or 0
            
            cursor.execute("SELECT SUM(discount_amount_rub) as total FROM purchases WHERE status = 'completed'")
            total_discounts = cursor.fetchone()['total'] or 0
            
            cursor.execute('SELECT COUNT(*) as count FROM products WHERE is_active = 1')
            products_count = cursor.fetchone()['count']
            
            cursor.execute('SELECT COUNT(*) as count FROM products WHERE product_type = "free" AND is_active = 1')
            free_products_count = cursor.fetchone()['count']
            
            cursor.execute('SELECT COUNT(*) as count FROM categories WHERE is_active = 1')
            categories_count = cursor.fetchone()['count']
            
            avg_order = total_revenue / purchases_count if purchases_count > 0 else 0
            
            return {
                'users_count': users_count,
                'active_users_7d': active_users_7d,
                'active_users_30d': active_users_30d,
                'purchases_count': purchases_count,
                'total_revenue': total_revenue,
                'total_discounts': total_discounts,
                'avg_order': avg_order,
                'products_count': products_count,
                'free_products_count': free_products_count,
                'categories_count': categories_count
            }
    
    # Поддержка и отзывы
    def create_support_ticket(self, user_id: int, message: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO support_tickets (user_id, message) VALUES (?, ?)', (user_id, message))
            return cursor.lastrowid
    
    def add_feedback(self, user_id: int, rating: int, comment: str = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO feedback (user_id, rating, comment) VALUES (?, ?, ?)', (user_id, rating, comment))
    
    # Экспорт
    def export_products(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p.*, c.name as category_name
                FROM products p
                JOIN categories c ON p.category_id = c.id
                ORDER BY c.name, p.name
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    def export_users(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, telegram_id, username, first_name, last_name, 
                       registered_at, last_activity, total_purchases, total_spent_rub,
                       referral_earnings, is_blocked
                FROM users
                ORDER BY registered_at DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    def export_purchases(self) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p.*, u.telegram_id, u.username, pr.name as product_name
                FROM purchases p
                JOIN users u ON p.user_id = u.id
                JOIN products pr ON p.product_id = pr.id
                WHERE p.status = 'completed'
                ORDER BY p.created_at DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]
