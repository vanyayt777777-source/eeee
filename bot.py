import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import BOT_TOKEN, logger
from database import db
from handlers import *
from handlers.admin import register_admin_handlers
from handlers.setup import register_setup_handlers

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

async def set_commands():
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(commands)

def register_handlers():
    """Регистрация всех обработчиков"""
    
    # Команды
    dp.message.register(cmd_start, Command("start"))
    
    # Информационные кнопки
    dp.message.register(show_rules, lambda message: message.text and "Правила" in message.text)
    dp.message.register(show_delivery, lambda message: message.text and "Доставка" in message.text)
    dp.message.register(show_payment_info, lambda message: message.text and "Оплата" in message.text)
    dp.message.register(show_contacts, lambda message: message.text and "Контакты" in message.text)
    dp.message.register(about, lambda message: message.text and "О нас" in message.text)
    dp.message.register(show_profile, lambda message: message.text and "Профиль" in message.text)
    dp.message.register(referral_program, lambda message: message.text and "Реферальная программа" in message.text)
    dp.message.register(promo_code, lambda message: message.text and "Промокод" in message.text)
    dp.message.register(free_products, lambda message: message.text and "Бесплатно" in message.text)
    dp.message.register(buy_product, lambda message: message.text and "Купить товар" in message.text)
    dp.message.register(check_stock, lambda message: message.text and "Наличие товара" in message.text)
    dp.message.register(support, lambda message: message.text and "Поддержка" in message.text)
    dp.message.register(feedback, lambda message: message.text and "Отзыв" in message.text)
    dp.message.register(back_to_main, lambda message: message.text and "Назад в главное меню" in message.text)
    
    # Callback запросы для товаров
    dp.callback_query.register(show_free_product, F.data.startswith("free_product_"))
    dp.callback_query.register(confirm_free_product, F.data.startswith("free_confirm_"))
    dp.callback_query.register(show_category_products, F.data.startswith("category_"))
    dp.callback_query.register(show_product_details, F.data.startswith("product_"))
    dp.callback_query.register(process_quantity, F.data.startswith("qty_"))
    dp.callback_query.register(back_to_product, F.data.startswith("back_to_product_"))
    dp.callback_query.register(back_to_categories, F.data.startswith("back_to_categories_"))
    
    # Callback запросы для платежей
    dp.callback_query.register(apply_promo_to_purchase, F.data.startswith("apply_promo_"))
    dp.callback_query.register(check_payment, F.data.startswith("check_payment_"))
    dp.callback_query.register(cancel_payment, F.data == "cancel_payment")
    
    # Callback запросы для отзывов
    dp.callback_query.register(process_feedback_rating, F.data.startswith("rating_"))
    
    # Навигация
    dp.callback_query.register(back_callback, F.data == "back")
    dp.callback_query.register(back_to_main_callback, F.data == "back_to_main")
    dp.callback_query.register(back_to_admin_callback, F.data == "back_to_admin")
    
    # Состояния пользователя
    dp.message.register(process_promo_code, UserStates.waiting_for_promo_code)
    dp.message.register(process_custom_quantity, UserStates.waiting_for_product_quantity)
    dp.message.register(process_support_message, UserStates.waiting_for_support_message)
    dp.message.register(process_feedback_comment, UserStates.waiting_for_feedback)
    
    # Неизвестные команды
    dp.message.register(handle_unknown)
    
    # Регистрация админ-обработчиков
    register_admin_handlers(dp)
    
    # Регистрация обработчиков настройки
    register_setup_handlers(dp)

async def main():
    logger.info("Запуск бота...")
    
    settings = db.get_settings()
    logger.info(f"Текущие настройки: admin_id={settings.get('admin_id')}, setup_complete={settings.get('is_setup_complete')}")
    
    await set_commands()
    register_handlers()
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
