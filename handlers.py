import asyncio
import os
from datetime import datetime
from aiogram import F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, FSInputFile

from config import logger, USDT_TO_RUB, Currency, EmojiType
from database import db
from keyboards import *
from states import SetupStates, AdminStates, UserStates
from utils.crypto_api import CryptoBotAPI

# ==================== Обработчики команд ====================

async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    language_code = message.from_user.language_code
    
    args = message.text.split()
    referral_code = args[1] if len(args) > 1 else None
    
    db_user_id = db.register_user(user_id, username, first_name, last_name, language_code, referral_code)
    db.update_user_activity(db_user_id)
    
    settings = db.get_settings()
    
    main_emoji = db.get_emoji(EmojiType.MAIN_MENU.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    welcome_text = f"{main_emoji} {settings.get('bot_name', 'магазин')}\n\n"
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
        reply_markup=get_main_keyboard(user_id)
    )

# ==================== Информационные кнопки ====================

async def show_rules(message: Message):
    settings = db.get_settings()
    rules_emoji = db.get_emoji(EmojiType.RULES.value)
    rules_text = settings.get('rules', 'Правила еще не настроены администратором.')
    await message.answer(f"{rules_emoji} Правила магазина:\n\n{rules_text}")

async def show_delivery(message: Message):
    settings = db.get_settings()
    delivery_emoji = db.get_emoji(EmojiType.DELIVERY.value)
    delivery_text = settings.get('delivery_info', 'Информация о доставке еще не настроена администратором.')
    await message.answer(f"{delivery_emoji} Информация о доставке:\n\n{delivery_text}")

async def show_payment_info(message: Message):
    settings = db.get_settings()
    payment_emoji = db.get_emoji(EmojiType.PAYMENT_INFO.value)
    payment_text = settings.get('payment_methods', 'Способы оплаты еще не настроены администратором.')
    await message.answer(f"{payment_emoji} Способы оплаты:\n\n{payment_text}")

async def show_contacts(message: Message):
    settings = db.get_settings()
    contact_emoji = db.get_emoji(EmojiType.CONTACT.value)
    contact_text = settings.get('contact_info', 'Контактная информация еще не настроена администратором.')
    await message.answer(f"{contact_emoji} Контактная информация:\n\n{contact_text}")

async def about(message: Message):
    settings = db.get_settings()
    about_emoji_formatted = db.format_emoji(EmojiType.ABOUT.value)
    about_text = settings.get('about_message', 'Информация о магазине')
    await message.answer(
        f"{about_emoji_formatted} О магазине '{settings.get('bot_name')}':\n\n{about_text}",
        parse_mode="HTML"
    )

async def show_profile(message: Message):
    user = db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} Профиль не найден. Начните с команды /start")
        return
    
    purchases = db.get_purchases_by_user(user['id'], limit=10)
    
    profile_text = (
        f"{db.get_emoji(EmojiType.PROFILE.value)} Ваш профиль:\n\n"
        f"🆔 ID: {user['telegram_id']}\n"
        f"📝 Имя: {user['first_name']}\n"
        f"📅 Зарегистрирован: {user['registered_at']}\n"
        f"🛍 Всего покупок: {user['total_purchases']}\n"
        f"💰 Потрачено: {user['total_spent_rub']:.2f} ₽\n"
        f"🎁 Реферальных бонусов: {user['referral_earnings']:.2f} ₽\n\n"
    )
    
    if purchases:
        profile_text += "📋 Последние покупки:\n"
        for purchase in purchases:
            if purchase['product_type'] == 'free':
                profile_text += f"  • 🎁 {purchase['product_name']} - Бесплатно ({purchase['created_at']})\n"
            else:
                profile_text += f"  • {purchase['product_name']} x{purchase['quantity']} - {purchase['amount_rub']:.2f} ₽ ({purchase['created_at']})\n"
    
    await message.answer(profile_text)

# ==================== Реферальная система ====================

async def referral_program(message: Message):
    user = db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} Профиль не найден.")
        return
    
    stats = db.get_referral_stats(user['id'])
    referrals = db.get_referrals(user['id'])
    
    bot_username = (await message.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user['referral_code']}"
    
    settings = db.get_settings()
    bonus_percent = settings.get('referral_bonus_percent', 10)
    
    referral_emoji = db.get_emoji(EmojiType.REFERRAL.value)
    
    message_text = (
        f"{referral_emoji} Реферальная программа\n\n"
        f"Приглашайте друзей и получайте {bonus_percent}% от их покупок!\n\n"
        f"📊 Ваша статистика:\n"
        f"• Приглашено друзей: {stats['referrals_count']}\n"
        f"• Заработано бонусов: {stats['total_earned']:.2f} ₽\n\n"
        f"🔗 Ваша реферальная ссылка:\n"
        f"{referral_link}\n\n"
        f"👥 Ваши рефералы:\n"
    )
    
    if referrals:
        for ref in referrals[:10]:
            message_text += f"• {ref['first_name']} - {ref['registered_at']}\n"
    else:
        message_text += "• Пока нет приглашенных друзей"
    
    await message.answer(message_text, reply_markup=get_back_keyboard())

# ==================== Промокоды ====================

async def promo_code(message: Message, state: FSMContext):
    promo_emoji = db.get_emoji(EmojiType.PROMO.value)
    await message.answer(
        f"{promo_emoji} Введите промокод:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(UserStates.waiting_for_promo_code)

async def process_promo_code(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Ввод промокода отменен.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    promo = db.validate_promocode(message.text.upper())
    
    if not promo:
        await message.answer(
            f"{error_emoji} Промокод недействителен или истек.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        await state.clear()
        return
    
    user = db.get_user_by_telegram_id(message.from_user.id)
    uses = db.get_user_promocode_uses(user['id'], promo['id'])
    
    if uses > 0:
        await message.answer(
            f"{error_emoji} Вы уже использовали этот промокод.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        await state.clear()
        return
    
    await state.update_data(promo_code=promo['code'], promo_discount=promo['discount_percent'], promo_id=promo['id'])
    
    await message.answer(
        f"{success_emoji} Промокод активирован! Скидка: {promo['discount_percent']}%\n\n"
        f"Теперь можете совершить покупку со скидкой.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )
    await state.clear()

# ==================== Бесплатные товары ====================

async def free_products(message: Message):
    settings = db.get_settings()
    
    if not settings.get('is_setup_complete'):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} Магазин еще не настроен.")
        return
    
    products = db.get_free_products()
    
    if not products:
        free_emoji = db.get_emoji(EmojiType.FREE.value)
        await message.answer(f"{free_emoji} В данный момент бесплатных товаров нет.")
        return
    
    free_emoji = db.get_emoji(EmojiType.FREE.value)
    await message.answer(
        f"{free_emoji} Бесплатные товары:\n\nВыберите товар (можно забрать только один раз):",
        reply_markup=get_free_products_keyboard()
    )

async def show_free_product(callback: CallbackQuery):
    product_id = int(callback.data.replace("free_product_", ""))
    product = db.get_product(product_id)
    
    if not product or product['quantity'] <= 0:
        await callback.message.edit_text(
            f"{db.get_emoji(EmojiType.ERROR.value)} Товар закончился.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    user = db.get_user_by_telegram_id(callback.from_user.id)
    
    if db.has_user_claimed_free_product(user['id'], product_id):
        await callback.message.edit_text(
            f"{db.get_emoji(EmojiType.ERROR.value)} Вы уже забрали этот товар.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    await callback.message.edit_text(
        f"{db.get_emoji(EmojiType.PRODUCT.value)} {product['name']}\n\n"
        f"{product['description']}\n\n"
        f"📦 В наличии: {product['quantity']} шт.\n\n"
        f"Это бесплатный товар. Хотите получить?",
        reply_markup=get_quantity_keyboard(product_id, product['quantity'], 'free')
    )
    await callback.answer()

async def confirm_free_product(callback: CallbackQuery):
    product_id = int(callback.data.replace("free_confirm_", ""))
    product = db.get_product(product_id)
    user = db.get_user_by_telegram_id(callback.from_user.id)
    
    if not product or product['quantity'] <= 0:
        await callback.message.edit_text(
            f"{db.get_emoji(EmojiType.ERROR.value)} Товар закончился.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    if db.claim_free_product(user['id'], product_id):
        await callback.message.delete()
        await callback.message.answer(
            f"{db.get_emoji(EmojiType.SUCCESS.value)} Ваш бесплатный товар:\n\n{product['content']}",
            reply_markup=get_main_keyboard(callback.from_user.id)
        )
    else:
        await callback.message.edit_text(
            f"{db.get_emoji(EmojiType.ERROR.value)} Ошибка при получении товара.",
            reply_markup=get_back_keyboard()
        )
    
    await callback.answer()

# ==================== Платные товары ====================

async def buy_product(message: Message):
    settings = db.get_settings()
    
    if not settings.get('is_setup_complete'):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} Магазин еще не настроен.")
        return
    
    categories = db.get_categories()
    
    if not categories:
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} В магазине пока нет товаров.")
        return
    
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    await message.answer(
        f"{category_emoji} Выберите категорию:",
        reply_markup=get_categories_keyboard('paid')
    )

async def show_category_products(callback: CallbackQuery):
    data = callback.data.split("_")
    if len(data) < 2:
        await callback.answer("Неверный формат данных")
        return
    
    category_id = int(data[1])
    product_type = data[2] if len(data) > 2 else 'paid'
    
    category = db.get_category(category_id)
    products = db.get_products_by_category(category_id, product_type)
    
    if not products:
        await callback.message.edit_text(
            f"{db.get_emoji(EmojiType.ERROR.value)} В категории '{category['name']}' пока нет товаров.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    await callback.message.edit_text(
        f"{db.get_emoji(EmojiType.CATEGORY.value)} Категория: {category['name']}\n\n"
        f"{category['description']}\n\n"
        f"Выберите товар:",
        reply_markup=get_products_keyboard(category_id, product_type)
    )
    await callback.answer()

async def show_product_details(callback: CallbackQuery):
    data = callback.data.split("_")
    if len(data) < 2:
        await callback.answer("Неверный формат данных")
        return
    
    product_id = int(data[1])
    product_type = data[2] if len(data) > 2 else 'paid'
    
    product = db.get_product(product_id)
    
    if not product:
        await callback.message.edit_text(
            f"{db.get_emoji(EmojiType.ERROR.value)} Товар не найден.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    if product['quantity'] <= 0:
        await callback.message.edit_text(
            f"{db.get_emoji(EmojiType.ERROR.value)} Товар временно отсутствует.",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    if product_type == 'paid':
        await callback.message.edit_text(
            f"{db.get_emoji(EmojiType.PRODUCT.value)} {product['name']}\n\n"
            f"{product['description']}\n\n"
            f"💰 Цена за единицу: {product['price_rub']} ₽ ({product['price_usd']} USDT)\n"
            f"📦 В наличии: {product['quantity']} шт.\n\n"
            f"Выберите количество:",
            reply_markup=get_quantity_keyboard(product_id, product['quantity'], product_type)
        )
    else:
        await callback.message.edit_text(
            f"{db.get_emoji(EmojiType.PRODUCT.value)} {product['name']}\n\n"
            f"{product['description']}\n\n"
            f"📦 В наличии: {product['quantity']} шт.\n\n"
            f"Это бесплатный товар. Хотите получить?",
            reply_markup=get_quantity_keyboard(product_id, product['quantity'], product_type)
        )
    
    await callback.answer()

async def process_quantity(callback: CallbackQuery, state: FSMContext):
    data = callback.data.split("_")
    if len(data) < 3:
        await callback.answer("Неверный формат данных")
        return
    
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
        callback.data = f"product_{product_id}_paid"
        await show_product_details(callback)
    else:
        product_id = int(data[1])
        quantity = int(data[2])
        await callback.message.delete()
        await create_payment(callback.message, product_id, quantity, callback.from_user.id)
    
    await callback.answer()

async def back_to_product(callback: CallbackQuery):
    data = callback.data.split("_")
    if len(data) < 4:
        await callback.answer("Неверный формат данных")
        return
    
    product_id = int(data[3])
    product_type = data[4] if len(data) > 4 else 'paid'
    
    callback.data = f"product_{product_id}_{product_type}"
    await show_product_details(callback)

async def back_to_categories(callback: CallbackQuery):
    product_type = callback.data.replace("back_to_categories_", "")
    
    await callback.message.delete()
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    await callback.message.answer(
        f"{category_emoji} Выберите категорию:",
        reply_markup=get_categories_keyboard(product_type)
    )
    await callback.answer()

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
        
        if not product:
            await message.answer(
                f"{error_emoji} Товар не найден.",
                reply_markup=get_main_keyboard(message.from_user.id)
            )
            await state.clear()
            return
        
        if quantity <= 0 or quantity > product['quantity']:
            await message.answer(
                f"{error_emoji} Введите число от 1 до {product['quantity']}:",
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

# ==================== Платежи ====================

async def create_payment(message: types.Message, product_id: int, quantity: int, user_id: int):
    product = db.get_product(product_id)
    settings = db.get_settings()
    
    if not settings.get('crypto_token'):
        await message.answer(
            f"{db.get_emoji(EmojiType.ERROR.value)} Ошибка: платежная система не настроена."
        )
        return
    
    total_rub = product['price_rub'] * quantity
    min_order = settings.get('min_order_amount', 0)
    max_order = settings.get('max_order_amount', 1000000)
    
    if min_order > 0 and total_rub < min_order:
        await message.answer(
            f"{db.get_emoji(EmojiType.ERROR.value)} Минимальная сумма заказа: {min_order} ₽. Ваша сумма: {total_rub} ₽"
        )
        return
    
    if total_rub > max_order:
        await message.answer(
            f"{db.get_emoji(EmojiType.ERROR.value)} Максимальная сумма заказа: {max_order} ₽. Ваша сумма: {total_rub} ₽"
        )
        return
    
    user = db.get_user_by_telegram_id(user_id)
    if not user:
        user_id = db.register_user(
            user_id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name
        )
        user = {'id': user_id}
    
    total_usd = round(total_rub / USDT_TO_RUB, 2)
    
    crypto_api = CryptoBotAPI(settings['crypto_token'])
    invoice = await crypto_api.create_invoice(
        amount_usd=total_usd,
        description=f"Покупка: {product['name']} x{quantity}"
    )
    
    if not invoice:
        await message.answer(
            f"{db.get_emoji(EmojiType.ERROR.value)} Ошибка при создании счета. Попробуйте позже."
        )
        return
    
    if not db.update_product_quantity(product_id, quantity):
        await message.answer(
            f"{db.get_emoji(EmojiType.ERROR.value)} Товар закончился. Попробуйте выбрать другое количество."
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
        f"{db.get_emoji(EmojiType.PAYMENT.value)} Счет на оплату:\n\n"
        f"Товар: {product['name']}\n"
        f"Количество: {quantity} шт.\n"
        f"Сумма: {total_rub} ₽ ({total_usd} USDT)\n\n"
        f"Нажмите кнопку ниже для оплаты через @CryptoBot",
        reply_markup=get_payment_keyboard(invoice['pay_url'], purchase_id)
    )

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

async def check_payment(callback: CallbackQuery):
    purchase_id = int(callback.data.replace("check_payment_", ""))
    purchase = db.get_purchase(purchase_id)
    
    if not purchase:
        await callback.message.edit_text(
            f"{db.get_emoji(EmojiType.ERROR.value)} Платеж не найден.",
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
            f"{db.get_emoji(EmojiType.PAYMENT.value)} Счет ожидает оплаты.",
            reply_markup=get_payment_keyboard(
                f"https://t.me/CryptoBot?start={purchase['crypto_payment_id']}",
                purchase_id
            )
        )
    else:
        await callback.message.edit_text(
            f"{db.get_emoji(EmojiType.ERROR.value)} Платеж не найден или истек.",
            reply_markup=get_back_keyboard()
        )
    
    await callback.answer()

async def deliver_product(message: types.Message, purchase: Dict):
    product = db.get_product(purchase['product_id'])
    
    if not product:
        await message.answer(
            f"{db.get_emoji(EmojiType.ERROR.value)} Ошибка: товар не найден."
        )
        return
    
    discount_text = ""
    if purchase['discount_amount_rub'] > 0:
        discount_text = f"Скидка: {purchase['discount_amount_rub']} ₽\n"
    
    await message.answer(
        f"{db.get_emoji(EmojiType.SUCCESS.value)} Оплата получена!\n\n"
        f"{db.get_emoji(EmojiType.PRODUCT.value)} Ваш товар:\n\n"
        f"Наименование: {product['name']}\n"
        f"Количество: {purchase['quantity']} шт.\n"
        f"{discount_text}"
        f"Сумма: {purchase['amount_rub']} ₽\n\n"
        f"Контент:\n{product['content']}"
    )
    
    await message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(message.chat.id)
    )

async def cancel_payment(callback: CallbackQuery):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    await callback.message.edit_text(f"{error_emoji} Платеж отменен.")
    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

# ==================== Наличие товара ====================

async def check_stock(message: Message):
    settings = db.get_settings()
    
    if not settings.get('is_setup_complete'):
        error_emoji = db.get_emoji(EmojiType.ERROR.value)
        await message.answer(f"{error_emoji} Магазин еще не настроен.")
        return
    
    categories = db.get_categories()
    currency_symbol = Currency[settings['currency']].value
    stock_emoji = db.get_emoji(EmojiType.STOCK.value)
    category_emoji = db.get_emoji(EmojiType.CATEGORY.value)
    free_emoji = db.get_emoji(EmojiType.FREE.value)
    
    message_text = f"{stock_emoji} Наличие товаров:\n\n"
    
    for category in categories:
        category_products = db.get_products_by_category(category['id'])
        if category_products:
            message_text += f"{category_emoji} {category['name']}:\n"
            for product in category_products:
                if product['product_type'] == 'paid':
                    price = product['price_rub'] if settings['currency'] == 'RUB' else product['price_usd']
                    message_text += f"  • {product['name']} - {price} {currency_symbol} (в наличии: {product['quantity']} шт.)\n"
                else:
                    message_text += f"  • {free_emoji} {product['name']} - Бесплатно (в наличии: {product['quantity']} шт.)\n"
            message_text += "\n"
    
    await message.answer(message_text)

# ==================== Поддержка и отзывы ====================

async def support(message: Message, state: FSMContext):
    settings = db.get_settings()
    support_emoji = db.get_emoji(EmojiType.SUPPORT.value)
    
    if not settings.get('support_chat_id'):
        await message.answer(f"{support_emoji} Поддержка временно недоступна.")
        return
    
    await message.answer(
        f"{support_emoji} Опишите вашу проблему или вопрос.\n\n"
        f"Наш администратор ответит вам как можно скорее.",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(UserStates.waiting_for_support_message)

async def process_support_message(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Обращение отменено.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    user = db.get_user_by_telegram_id(message.from_user.id)
    ticket_id = db.create_support_ticket(user['id'], message.text)
    
    settings = db.get_settings()
    if settings.get('support_chat_id'):
        try:
            await message.bot.send_message(
                settings['support_chat_id'],
                f"🆘 Новое обращение #{ticket_id}\n\n"
                f"От: {message.from_user.full_name} (@{message.from_user.username})\n"
                f"ID: {message.from_user.id}\n\n"
                f"Сообщение: {message.text}"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления в поддержку: {e}")
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Ваше обращение принято! Номер тикета: #{ticket_id}\n"
        f"Мы ответим вам в ближайшее время.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

async def feedback(message: Message, state: FSMContext):
    feedback_emoji = db.get_emoji(EmojiType.FEEDBACK.value)
    
    builder = InlineKeyboardBuilder()
    for i in range(1, 6):
        builder.row(InlineKeyboardButton(text=f"{'⭐' * i}", callback_data=f"rating_{i}"))
    
    await message.answer(
        f"{feedback_emoji} Оцените нашу работу от 1 до 5 звезд:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(UserStates.waiting_for_feedback)

async def process_feedback_rating(callback: CallbackQuery, state: FSMContext):
    rating = int(callback.data.replace("rating_", ""))
    await state.update_data(feedback_rating=rating)
    
    await callback.message.edit_text(
        f"Спасибо за оценку {rating} ⭐!\n"
        f"Напишите комментарий (или отправьте 'пропустить'):"
    )
    await callback.answer()

async def process_feedback_comment(message: Message, state: FSMContext):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    success_emoji = db.get_emoji(EmojiType.SUCCESS.value)
    
    if message.text and "Отмена" in message.text:
        await state.clear()
        await message.answer(
            f"{error_emoji} Отзыв отменен.",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
        return
    
    data = await state.get_data()
    rating = data.get('feedback_rating', 5)
    comment = None if message.text.lower() == 'пропустить' else message.text
    
    user = db.get_user_by_telegram_id(message.from_user.id)
    db.add_feedback(user['id'], rating, comment)
    
    await state.clear()
    await message.answer(
        f"{success_emoji} Спасибо за ваш отзыв!",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

# ==================== Навигация ====================

async def back_to_main(message: Message):
    await message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

async def back_callback(callback: CallbackQuery):
    back_emoji = db.get_emoji(EmojiType.BACK.value)
    await callback.message.delete()
    await callback.message.answer(f"{back_emoji} Действие отменено.")
    await callback.answer()

async def back_to_main_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

async def back_to_admin_callback(callback: CallbackQuery):
    await callback.message.delete()
    admin_emoji = db.get_emoji(EmojiType.ADMIN.value)
    await callback.message.answer(
        f"{admin_emoji} Админ-панель\n\nВыберите действие:",
        reply_markup=get_admin_panel_keyboard()
    )
    await callback.answer()

async def handle_unknown(message: Message):
    error_emoji = db.get_emoji(EmojiType.ERROR.value)
    await message.answer(
        f"{error_emoji} Я не понимаю эту команду. Пожалуйста, используйте кнопки меню.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )
