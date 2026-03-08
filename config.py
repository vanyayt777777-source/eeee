import os
import logging
from enum import Enum
from dotenv import load_dotenv

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
    SUPPORT = "support"
    FEEDBACK = "feedback"
    EDIT = "edit"
    DELETE = "delete"
    EXPORT = "export"
    BROADCAST = "broadcast"
    RULES = "rules"
    DELIVERY = "delivery"
    CONTACT = "contact"
    PAYMENT_INFO = "payment_info"

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
    EmojiType.BACK: "◀",
    EmojiType.SUPPORT: "🆘",
    EmojiType.FEEDBACK: "💬",
    EmojiType.EDIT: "✏️",
    EmojiType.DELETE: "🗑️",
    EmojiType.EXPORT: "📤",
    EmojiType.BROADCAST: "📢",
    EmojiType.RULES: "📋",
    EmojiType.DELIVERY: "🚚",
    EmojiType.CONTACT: "📞",
    EmojiType.PAYMENT_INFO: "💳"
}

# Класс для расширенных настроек
class BotSettings:
    def __init__(self):
        self.bot_name = "Мой магазин"
        self.bot_description = "Лучший магазин в Telegram"
        self.welcome_message = "Добро пожаловать в магазин!"
        self.about_message = "Информация о магазине"
        self.contact_info = "Контактная информация"
        self.rules = "Правила магазина"
        self.delivery_info = "Информация о доставке"
        self.payment_methods = "Способы оплаты"
        self.refund_policy = "Политика возврата"
        self.currency = "RUB"
        self.admin_id = None
        self.support_chat_id = None
        self.crypto_token = None
        self.min_order_amount = 0
        self.max_order_amount = 1000000
        self.discount_threshold = 5000
        self.discount_percent = 5
        self.referral_bonus_percent = 10
        self.is_setup_complete = False
