from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from database import db
from config import EmojiType, Currency

# Главное меню
def get_main_keyboard(telegram_id: int) -> ReplyKeyboardMarkup:
    settings = db.get_settings()
    is_admin = db.is_admin(telegram_id)
    is_setup_complete = settings.get('is_setup_complete', False)
    
    builder = ReplyKeyboardBuilder()
    
    buy_emoji = db.get_emoji(EmojiType.BUY.value)
    free_emoji = db.get_emoji(EmojiType.FREE.value)
    stock_emoji = db.get_emoji(EmojiType.STOCK.value)
    profile_emoji = db.get_emoji(EmojiType.PROFILE.value)
    referral_emoji = db.get_emoji(EmojiType.REFERRAL.value)
    promo_emoji = db.get_emoji(EmojiType.PROMO.value)
    about_emoji = db.get_emoji(EmojiType.ABOUT.value)
    settings_emoji = db.get_emoji(EmojiType.SETTINGS.value)
    admin_emoji = db.get_emoji(EmojiType.ADMIN.value)
    support_emoji = db.get_emoji(EmojiType.SUPPORT.value)
    feedback_emoji = db.get_emoji(EmojiType.FEEDBACK.value)
    rules_emoji = db.get_emoji(EmojiType.RULES.value)
    delivery_emoji = db.get_emoji(EmojiType.DELIVERY.value)
    contact_emoji = db.get_emoji(EmojiType.CONTACT.value)
    payment_info_emoji = db.get_emoji(EmojiType.PAYMENT_INFO.value)
    
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
    builder.row(
        KeyboardButton(text=f"{rules_emoji} Правила"),
        KeyboardButton(text=f"{delivery_emoji} Доставка")
    )
    builder.row(
        KeyboardButton(text=f"{payment_info_emoji} Оплата"),
        KeyboardButton(text=f"{contact_emoji} Контакты")
    )
    builder.row(
        KeyboardButton(text=f"{support_emoji} Поддержка"),
        KeyboardButton(text=f"{feedback_emoji} Отзыв")
    )
    builder.row(KeyboardButton(text=f"{about_emoji} О нас"))
    
    if not is_setup_complete:
        if settings.get('admin_id') is None:
            builder.row(KeyboardButton(text=f"{settings_emoji} Стать администратором"))
        elif is_admin:
            builder.row(KeyboardButton(text=f"{settings_emoji} Настроить бота"))
    
    if is_admin and is_setup_complete:
        builder.row(KeyboardButton(text=f"{admin_emoji} Админ панель"))
    
    return builder.as_markup(resize_keyboard=True)

# Админ-панель
def get_admin_panel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    
    stats_emoji = db.get_emoji(EmojiType.STATS.value)
    broadcast_emoji = db.get_emoji(EmojiType.BROADCAST.value)
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    promo_emoji = db.get_emoji(EmojiType.PROMO.value)
    settings_emoji = db.get_emoji(EmojiType.SETTINGS.value)
    support_emoji = db.get_emoji(EmojiType.SUPPORT.value)
    export_emoji = db.get_emoji(EmojiType.EXPORT.value)
    edit_emoji = db.get_emoji(EmojiType.EDIT.value)
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    free_emoji = db.get_emoji(EmojiType.FREE.value)
    
    builder.row(KeyboardButton(text=f"{stats_emoji} Статистика"))
    builder.row(KeyboardButton(text=f"{broadcast_emoji} Рассылка"))
    builder.row(
        KeyboardButton(text=f"{category_emoji} Категории"),
        KeyboardButton(text=f"{product_emoji} Товары")
    )
    builder.row(
        KeyboardButton(text=f"{promo_emoji} Промокоды"),
        KeyboardButton(text=f"{support_emoji} Поддержка")
    )
    builder.row(
        KeyboardButton(text=f"{edit_emoji} Редактировать"),
        KeyboardButton(text=f"{export_emoji} Экспорт")
    )
    builder.row(
        KeyboardButton(text=f"💰 Добавить платный товар"),
        KeyboardButton(text=f"{free_emoji} Добавить бесплатный")
    )
    builder.row(KeyboardButton(text=f"{settings_emoji} Управление эмодзи"))
    builder.row(KeyboardButton(text=f"{settings_emoji} Расширенные настройки"))
    builder.row(KeyboardButton(text=f"{back_emoji} Назад в главное меню"))
    
    return builder.as_markup(resize_keyboard=True)

# Управление категориями
def get_categories_management_keyboard() -> InlineKeyboardMarkup:
    categories = db.get_categories(only_active=False)
    builder = InlineKeyboardBuilder()
    
    for category in categories:
        status = "✅" if category['is_active'] else "❌"
        builder.row(InlineKeyboardButton(
            text=f"{status} {category['name']}",
            callback_data=f"admin_category_{category['id']}"
        ))
    
    builder.row(
        InlineKeyboardButton(text="➕ Добавить категорию", callback_data="add_category"),
        InlineKeyboardButton(text="◀ Назад", callback_data="back_to_admin")
    )
    return builder.as_markup()

# Управление товарами
def get_products_management_keyboard() -> InlineKeyboardMarkup:
    products = db.get_all_products(only_active=False)
    builder = InlineKeyboardBuilder()
    
    for product in products[:10]:
        status = "✅" if product['is_active'] else "❌"
        product_type = "💰" if product['product_type'] == 'paid' else "🎁"
        builder.row(InlineKeyboardButton(
            text=f"{status} {product_type} {product['name']}",
            callback_data=f"admin_product_{product['id']}"
        ))
    
    if len(products) > 10:
        builder.row(InlineKeyboardButton(text="📋 Все товары", callback_data="admin_products_all"))
    
    builder.row(
        InlineKeyboardButton(text="💰 Добавить платный", callback_data="add_paid_product_start"),
        InlineKeyboardButton(text="🎁 Добавить бесплатный", callback_data="add_free_product_start")
    )
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_to_admin"))
    return builder.as_markup()

# Категории для пользователя
def get_categories_keyboard(product_type: str = None) -> InlineKeyboardMarkup:
    categories = db.get_categories()
    builder = InlineKeyboardBuilder()
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    
    for category in categories:
        callback_data = f"category_{category['id']}"
        if product_type:
            callback_data += f"_{product_type}"
        builder.row(InlineKeyboardButton(
            text=f"{category_emoji} {category['name']}",
            callback_data=callback_data
        ))
    
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_to_main"))
    return builder.as_markup()

# Бесплатные товары
def get_free_products_keyboard() -> InlineKeyboardMarkup:
    products = db.get_free_products()
    builder = InlineKeyboardBuilder()
    free_emoji = db.get_emoji(EmojiType.FREE.value)
    
    for product in products:
        builder.row(InlineKeyboardButton(
            text=f"{free_emoji} {product['name']} (в наличии: {product['quantity']})",
            callback_data=f"free_product_{product['id']}"
        ))
    
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_to_main"))
    return builder.as_markup()

# Товары в категории
def get_products_keyboard(category_id: int, product_type: str = 'paid') -> InlineKeyboardMarkup:
    products = db.get_products_by_category(category_id, product_type)
    settings = db.get_settings()
    currency_symbol = Currency[settings['currency']].value
    builder = InlineKeyboardBuilder()
    product_emoji = db.get_emoji(EmojiType.PRODUCT.value)
    
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
    
    builder.row(InlineKeyboardButton(text="◀ Назад к категориям", callback_data=f"back_to_categories_{product_type}"))
    return builder.as_markup()

# Количество товара
def get_quantity_keyboard(product_id: int, max_quantity: int, product_type: str = 'paid') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    if product_type == 'paid':
        quantities = [1, 2, 3, 4, 5, 10]
        row = []
        for q in quantities:
            if q <= max_quantity:
                row.append(InlineKeyboardButton(text=str(q), callback_data=f"qty_{product_id}_{q}"))
        if row:
            builder.row(*row)
        
        builder.row(InlineKeyboardButton(text="✏️ Своё количество", callback_data=f"qty_custom_{product_id}"))
    else:
        builder.row(InlineKeyboardButton(text="🎁 Забрать", callback_data=f"free_confirm_{product_id}"))
    
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data=f"back_to_product_{product_id}_{product_type}"))
    
    return builder.as_markup()

# Платежная клавиатура
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

# Редактирование категории
def get_edit_category_keyboard(category_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    edit_emoji = db.get_emoji(EmojiType.EDIT.value)
    delete_emoji = db.get_emoji(EmojiType.DELETE.value)
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    builder.row(
        InlineKeyboardButton(text=f"{edit_emoji} Название", callback_data=f"edit_cat_name_{category_id}"),
        InlineKeyboardButton(text=f"{edit_emoji} Описание", callback_data=f"edit_cat_desc_{category_id}")
    )
    builder.row(
        InlineKeyboardButton(text=f"{delete_emoji} Удалить", callback_data=f"delete_cat_{category_id}"),
        InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data="admin_categories")
    )
    return builder.as_markup()

# Редактирование товара
def get_edit_product_keyboard(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    edit_emoji = db.get_emoji(EmojiType.EDIT.value)
    delete_emoji = db.get_emoji(EmojiType.DELETE.value)
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    builder.row(
        InlineKeyboardButton(text=f"{edit_emoji} Цена", callback_data=f"edit_prod_price_{product_id}"),
        InlineKeyboardButton(text=f"{edit_emoji} Количество", callback_data=f"edit_prod_qty_{product_id}")
    )
    builder.row(
        InlineKeyboardButton(text=f"{edit_emoji} Контент", callback_data=f"edit_prod_content_{product_id}"),
        InlineKeyboardButton(text=f"{delete_emoji} Удалить", callback_data=f"delete_prod_{product_id}")
    )
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data="admin_products"))
    return builder.as_markup()

# Редактирование промокода
def get_edit_promo_keyboard(promo_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    edit_emoji = db.get_emoji(EmojiType.EDIT.value)
    delete_emoji = db.get_emoji(EmojiType.DELETE.value)
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    builder.row(
        InlineKeyboardButton(text=f"{edit_emoji} Скидка", callback_data=f"edit_promo_discount_{promo_id}"),
        InlineKeyboardButton(text=f"{edit_emoji} Лимит", callback_data=f"edit_promo_limit_{promo_id}")
    )
    builder.row(
        InlineKeyboardButton(text=f"{delete_emoji} Деактивировать", callback_data=f"deactivate_promo_{promo_id}"),
        InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data="list_promos")
    )
    return builder.as_markup()

# Экспорт
def get_export_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📦 Товары", callback_data="export_products"),
        InlineKeyboardButton(text="👥 Пользователи", callback_data="export_users")
    )
    builder.row(
        InlineKeyboardButton(text="🛍 Покупки", callback_data="export_purchases"),
        InlineKeyboardButton(text="📊 Статистика", callback_data="export_stats")
    )
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_to_admin"))
    return builder.as_markup()

# Промокоды
def get_promocodes_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Создать", callback_data="create_promo"),
        InlineKeyboardButton(text="📋 Список", callback_data="list_promos")
    )
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_to_admin"))
    return builder.as_markup()

# Валюта
def get_currency_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🇷🇺 Рубли (₽)", callback_data="currency_rub"),
        InlineKeyboardButton(text="🇺🇸 Доллары ($)", callback_data="currency_usd")
    )
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back"))
    return builder.as_markup()

# Расширенные настройки
def get_advanced_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    settings = db.get_settings()
    
    builder.row(InlineKeyboardButton(
        text=f"📝 Описание бота: {settings.get('bot_description', 'Не задано')[:20]}...",
        callback_data="setup_bot_description"
    ))
    builder.row(InlineKeyboardButton(
        text=f"📞 Контакты: {settings.get('contact_info', 'Не задано')[:20]}...",
        callback_data="setup_contact_info"
    ))
    builder.row(InlineKeyboardButton(
        text=f"📋 Правила: {settings.get('rules', 'Не задано')[:20]}...",
        callback_data="setup_rules"
    ))
    builder.row(InlineKeyboardButton(
        text=f"🚚 Доставка: {settings.get('delivery_info', 'Не задано')[:20]}...",
        callback_data="setup_delivery_info"
    ))
    builder.row(InlineKeyboardButton(
        text=f"💳 Способы оплаты: {settings.get('payment_methods', 'Не задано')[:20]}...",
        callback_data="setup_payment_methods"
    ))
    builder.row(InlineKeyboardButton(
        text=f"↩️ Политика возврата: {settings.get('refund_policy', 'Не задано')[:20]}...",
        callback_data="setup_refund_policy"
    ))
    builder.row(InlineKeyboardButton(
        text=f"💰 Мин. сумма заказа: {settings.get('min_order_amount', 0)} ₽",
        callback_data="setup_min_order"
    ))
    builder.row(InlineKeyboardButton(
        text=f"💰 Макс. сумма заказа: {settings.get('max_order_amount', 1000000)} ₽",
        callback_data="setup_max_order"
    ))
    builder.row(InlineKeyboardButton(
        text=f"🎁 Порог скидки: {settings.get('discount_threshold', 5000)} ₽ - {settings.get('discount_percent', 5)}%",
        callback_data="setup_discount"
    ))
    builder.row(InlineKeyboardButton(
        text=f"👥 Реферальный бонус: {settings.get('referral_bonus_percent', 10)}%",
        callback_data="setup_bonus_percent"
    ))
    builder.row(InlineKeyboardButton(text="◀ Назад", callback_data="back_to_admin"))
    return builder.as_markup()

# Управление эмодзи
def get_emojis_keyboard() -> InlineKeyboardMarkup:
    from config import DEFAULT_EMOJIS
    builder = InlineKeyboardBuilder()
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    
    emoji_list = list(DEFAULT_EMOJIS.keys())
    for i in range(0, len(emoji_list), 2):
        row = []
        for j in range(2):
            if i + j < len(emoji_list):
                emoji_type = emoji_list[i + j].value
                emoji_char = DEFAULT_EMOJIS[emoji_list[i + j]]
                row.append(InlineKeyboardButton(
                    text=f"{emoji_char} {emoji_type}",
                    callback_data=f"edit_emoji_{emoji_type}"
                ))
        builder.row(*row)
    
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data="back_to_admin"))
    return builder.as_markup()

# Кнопка отмены
def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    builder.row(KeyboardButton(text=f"{error_emoji} Отмена"))
    return builder.as_markup(resize_keyboard=True)

# Кнопка назад
def get_back_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    builder.row(InlineKeyboardButton(text=f"{back_emoji} Назад", callback_data="back"))
    return builder.as_markup()
