#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import uuid
import warnings
import sys
from typing import Dict, Optional

# Устанавливаем кодировку для Windows
if sys.platform == 'win32':
    import codecs
    import locale
    # Устанавливаем UTF-8 как кодировку по умолчанию
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())
    # Устанавливаем переменные окружения для кодировки
    os.environ['PYTHONIOENCODING'] = 'utf-8'
# Попытка импорта telegram модулей
try:
    # Suppress PTBUserWarning about per_message settings
    warnings.filterwarnings("ignore", category=UserWarning, module="telegram.ext")
    
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, 
        CommandHandler, 
        CallbackQueryHandler, 
        MessageHandler, 
        filters, 
        ContextTypes,
        ConversationHandler
    )
    
    from game_data import CATEGORIES, MALE_EMOJIS, FEMALE_EMOJIS, GAME_MODES, get_game_mode_info, validate_players_for_mode
    from database import Database
    
    TELEGRAM_AVAILABLE = True
except ImportError as e:
    print(f"Ошибка импорта модулей: {e}")
    print("Установите зависимости: pip install python-telegram-bot python-dotenv")
    exit(1)

# Попытка загрузить переменные окружения из .env файла
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Если dotenv не установлен, используем переменные окружения напрямую
    pass

# Настройка логирования
import logging.handlers
os.makedirs('logs', exist_ok=True)

# Настройка основного логгера

logging.basicConfig(
    level=logging.DEBUG,  # Изменено на DEBUG для полного логгирования
    format='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Вывод в консоль
        logging.FileHandler('logs/bot.log', encoding='utf-8')  # Основной лог
    ]
)

# Настройка логгера для ошибок
error_logger = logging.getLogger('bot_errors')
error_handler = logging.handlers.RotatingFileHandler(
    'logs/errors.log', 
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
error_handler.setLevel(logging.ERROR)
error_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
)
error_handler.setFormatter(error_formatter)
error_logger.addHandler(error_handler)
error_logger.setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
(WAITING_PLAYER_NAMES, 
 ADMIN_EDIT_TASK, ADMIN_ADD_TASK,
 USER_TASK_TEXT) = range(4)


class CouplesGameBot:
    def __init__(self, token: str):
        self.token = token
        self.db = Database()
        self.user_games: Dict[int, dict] = {}  # chat_id -> game_state
        
    def is_admin(self, user) -> bool:
        """Проверка, является ли пользователь администратором"""
        if not user:
            return False
        return self.db.is_admin(user.id)
    
    def is_owner(self, user) -> bool:
        """Проверка, является ли пользователь владельцем"""
        if not user:
            return False
        
        # Проверяем фиксированного владельца @MPR_XO
        if user.username and user.username.lower() == 'mpr_xo':
            return True
            
        return self.db.is_owner(user.id)
    
    def is_moderator(self, user) -> bool:
        """Проверка, является ли пользователь модератором"""
        if not user:
            return False
        return self.db.is_moderator(user.id)
    
    def has_admin_access(self, user) -> bool:
        """Проверка, имеет ли пользователь доступ к админ-панели (владелец или администратор)"""
        if not user:
            return False
        
        # Проверяем фиксированного владельца @MPR_XO и администратора @Virgo_E
        if user.username and user.username.lower() in ['mpr_xo', 'virgo_e']:
            return True
        
        return self.db.is_owner(user.id) or self.db.is_admin(user.id)
    
    def has_moderation_access(self, user) -> bool:
        """Проверка, имеет ли пользователь доступ к модерации (все уровни администраторов)"""
        if not user:
            return False
        
        # Проверяем фиксированного владельца @MPR_XO и администратора @Virgo_E
        if user.username and user.username.lower() in ['mpr_xo', 'virgo_e']:
            return True
            
        return self.db.is_owner(user.id) or self.db.is_admin(user.id) or self.db.is_moderator(user.id)
    
    def can_manage_administrators(self, user) -> bool:
        """Проверка, может ли пользователь управлять администраторами (только владелец)"""
        if not user:
            return False
        
        # Проверяем фиксированного владельца @MPR_XO
        if user.username and user.username.lower() == 'mpr_xo':
            return True
            
        return self.db.is_owner(user.id)
    
    def ensure_owner_rights(self, user):
        """Автоматически назначает права владельца пользователю @MPR_XO и администратора @Virgo_E"""
        if user and user.username:
            username_lower = user.username.lower()
            if username_lower == 'mpr_xo':
                self.db.add_user(user.id, user.username, user.first_name, user.last_name)
                self.db.set_owner(user.id, True)
                self.db.set_admin(user.id, True)
            elif username_lower == 'virgo_e':
                self.db.add_user(user.id, user.username, user.first_name, user.last_name)
                self.db.set_admin(user.id, True)
    
    def get_category_info(self, category_key: str):
        """Безопасное получение информации о категории"""
        return next((c for c in CATEGORIES if c['key'] == category_key), None)
    
    async def safe_edit_message(self, query, text, reply_markup=None, parse_mode='Markdown'):
        """Безопасное редактирование сообщения с обработкой ошибок"""
        try:
            # Если parse_mode не указан или None, не передаем его в API
            if parse_mode is None:
                await query.edit_message_text(
                    text,
                    reply_markup=reply_markup
                )
            else:
                await query.edit_message_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
        except Exception as e:
            if "Message is not modified" in str(e):
                # Сообщение не изменилось - это нормально, игнорируем
                pass
            elif "NetworkError" in str(e) or "RemoteProtocolError" in str(e):
                # Сетевая ошибка - логируем и игнорируем
                logger.warning(f"Сетевая ошибка при редактировании сообщения: {e}")
                error_logger.warning(f"Сетевая ошибка при редактировании сообщения: {e}", exc_info=True)
            elif "Can't parse entities" in str(e):
                # Ошибка разметки - пробуем без разметки
                logger.error(f"Ошибка разметки при редактировании сообщения: {e}")
                error_logger.error(f"Ошибка разметки при редактировании сообщения: {e}", exc_info=True)
                try:
                    await query.edit_message_text(
                        text,
                        reply_markup=reply_markup
                    )
                except Exception as e2:
                    logger.error(f"Ошибка при редактировании без разметки: {e2}")
                    error_logger.error(f"Ошибка при редактировании без разметки: {e2}", exc_info=True)
                    try:
                        await query.edit_message_text("❌ Произошла ошибка. Попробуйте еще раз.")
                    except Exception as e3:
                        error_logger.error(f"Критическая ошибка при отправке сообщения об ошибке: {e3}", exc_info=True)
            else:
                # Для других ошибок пробуем отправить без разметки
                logger.error(f"Ошибка при редактировании сообщения: {e}")
                error_logger.error(f"Ошибка при редактировании сообщения: {e}", exc_info=True)
                logger.error(f"Текст сообщения: {repr(text[:200])}...")
                logger.error(f"Parse mode: {parse_mode}")
                try:
                    await query.edit_message_text(
                        text,
                        reply_markup=reply_markup
                    )
                except Exception as e3:
                    logger.error(f"Ошибка при повторной попытке редактирования: {e3}")
                    error_logger.error(f"Ошибка при повторной попытке редактирования: {e3}", exc_info=True)
                    try:
                        await query.edit_message_text("❌ Произошла ошибка. Попробуйте еще раз.")
                    except Exception as e4:
                        error_logger.error(f"Критическая ошибка при отправке сообщения об ошибке: {e4}", exc_info=True)
        
    def get_main_menu_keyboard(self, user=None):
        """Главное меню бота"""
        # Убеждаемся, что владелец @MPR_XO имеет права
        if user:
            self.ensure_owner_rights(user)
        
        keyboard = [
            [InlineKeyboardButton("🎮 Начать игру", callback_data="start_game_setup")],
            [InlineKeyboardButton("📝 Редактор заданий", callback_data="task_editor")],
            [InlineKeyboardButton("❓ Помощь", callback_data="help")],
        ]
        
        # Добавляем админ-панель для администраторов и владельцев
        if user and self.has_admin_access(user):
            keyboard.insert(-1, [InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
        
        return InlineKeyboardMarkup(keyboard)
    
    def get_back_keyboard(self, back_data="main_menu"):
        """Кнопка назад"""
        keyboard = [[InlineKeyboardButton("← Назад", callback_data=back_data)]]
        return InlineKeyboardMarkup(keyboard)
    
    def get_emoji_keyboard(self, gender: str, player_index: int, back_to="setup_players"):
        """Клавиатура для выбора эмодзи"""
        emojis = MALE_EMOJIS if gender == 'male' else FEMALE_EMOJIS
        keyboard = []
        
        # Группируем эмодзи по 5 в ряд
        for i in range(0, len(emojis), 5):
            row = []
            for emoji in emojis[i:i+5]:
                row.append(InlineKeyboardButton(
                    emoji, 
                    callback_data=f"emoji_{player_index}_{emoji}"
                ))
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("← Назад", callback_data=back_to)])
        return InlineKeyboardMarkup(keyboard)
    
    def get_category_keyboard(self, context="game", mode=None):
        """Клавиатура для выбора категории"""
        keyboard = []
        for category in CATEGORIES:
            if context == "editor" and mode:
                callback_data = f"editor_mode_category_{mode}_{category['key']}"
            else:
                callback_data = f"{context}_category_{category['key']}"
            keyboard.append([InlineKeyboardButton(
                f"{category['emoji']} {category['name']}", 
                callback_data=callback_data
            )])
        
        if context == "admin":
            back_data = "admin_panel"
        elif context == "editor" and mode:
            back_data = f"editor_mode_{mode}"
        elif context == "editor":
            back_data = "main_menu"
        else:
            back_data = "main_menu"
            
        keyboard.append([InlineKeyboardButton("← Назад", callback_data=back_data)])
        return InlineKeyboardMarkup(keyboard)
    
    def get_editor_mode_keyboard(self):
        """Клавиатура для выбора режима игры в редакторе"""
        keyboard = []
        for mode in GAME_MODES:
            keyboard.append([InlineKeyboardButton(
                f"{mode['emoji']} {mode['name']}", 
                callback_data=f"editor_mode_{mode['key']}"
            )])
        
        keyboard.append([InlineKeyboardButton("← Назад", callback_data="main_menu")])
        return InlineKeyboardMarkup(keyboard)
    
    def get_user_task_mode_keyboard(self):
        """Клавиатура для выбора режима игры при создании пользовательского задания"""
        keyboard = []
        for mode in GAME_MODES:
            keyboard.append([InlineKeyboardButton(
                f"{mode['emoji']} {mode['name']}", 
                callback_data=f"user_task_mode_{mode['key']}"
            )])
        
        keyboard.append([InlineKeyboardButton("← Назад", callback_data="main_menu")])
        return InlineKeyboardMarkup(keyboard)
    
    def get_user_task_category_keyboard(self):
        """Клавиатура для выбора категории пользовательского задания"""
        keyboard = []
        for category in CATEGORIES:
            keyboard.append([InlineKeyboardButton(
                f"{category['emoji']} {category['name']}", 
                callback_data=f"user_task_category_{category['key']}"
            )])
        
        keyboard.append([InlineKeyboardButton("← Назад", callback_data="task_editor")])
        return InlineKeyboardMarkup(keyboard)
    
    def get_user_task_gender_keyboard(self):
        """Клавиатура для выбора пола пользовательского задания"""
        keyboard = [
            [InlineKeyboardButton("👨 Мужские", callback_data="user_task_gender_male")],
            [InlineKeyboardButton("👩 Женские", callback_data="user_task_gender_female")],
            [InlineKeyboardButton("👥 Общие для обоих полов", callback_data="user_task_gender_common")]
        ]
        
        keyboard.append([InlineKeyboardButton("← Назад", callback_data="task_editor")])
        return InlineKeyboardMarkup(keyboard)
    
    def get_gender_keyboard(self, category: str, mode: str = None):
        """Клавиатура для выбора типа заданий"""
        if mode:
            callback_prefix = f"editor_mode_gender_{mode}_{category}"
            back_data = f"editor_mode_category_{mode}_{category}"
        else:
            callback_prefix = f"gender_{category}"
            back_data = "main_menu"
            
        keyboard = [
            [InlineKeyboardButton("👥 Общие", callback_data=f"{callback_prefix}_common")],
            [InlineKeyboardButton("👨 Мужские", callback_data=f"{callback_prefix}_male")],
            [InlineKeyboardButton("👩 Женские", callback_data=f"{callback_prefix}_female")],
            [InlineKeyboardButton("← Назад", callback_data=back_data)]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_game_keyboard(self, chat_id: int):
        """Клавиатура для игрового процесса"""
        game_state = self.user_games.get(chat_id, {})
        keyboard = [
            [InlineKeyboardButton("✅ Задание выполнено", callback_data="task_completed")],
            [InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_task")],
            [InlineKeyboardButton("🏠 Завершить игру", callback_data="end_game")]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        chat_id = update.effective_chat.id
        
        logger.info(f"Command /start received from user {user.username or user.first_name} (ID: {user.id}) in chat {chat_id}")
        
        # Проверяем, заблокирован ли пользователь
        if self.db.is_user_blocked(user.id):
            block_info = self.db.get_user_block_info(user.id)
            if block_info and block_info['is_blocked']:
                if block_info['blocked_until']:
                    # Временная блокировка
                    try:
                        from datetime import datetime
                        blocked_until = datetime.fromisoformat(block_info['blocked_until'].replace('Z', '+00:00'))
                        date_str = blocked_until.strftime('%d.%m.%Y %H:%M')
                        reason = f"Причина: {block_info['block_reason']}" if block_info['block_reason'] else ""
                        await update.message.reply_text(
                            f"❌ **Вы заблокированы до {date_str}**\n\n{reason}\n\n"
                            "Обратитесь к администратору для разблокировки:\n"
                            "📞 @Uzumymbec",
                            parse_mode='Markdown'
                        )
                    except:
                        await update.message.reply_text(
                            f"❌ **Вы временно заблокированы**\n\n"
                            "Обратитесь к администратору для разблокировки:\n"
                            "📞 @Uzumymbec",
                            parse_mode='Markdown'
                        )
                else:
                    # Постоянная блокировка
                    reason = f"Причина: {block_info['block_reason']}" if block_info['block_reason'] else ""
                    await update.message.reply_text(
                        f"❌ **Вы заблокированы навсегда**\n\n{reason}\n\n"
                        "Обратитесь к администратору для разблокировки:\n"
                        "📞 @Uzumymbec",
                        parse_mode='Markdown'
                    )
                return
        
        # Добавляем пользователя в базу данных
        self.db.add_user(user.id, user.username, user.first_name, user.last_name)
        
        # Обновляем активность пользователя
        self.db.update_user_activity(user.id)
        
        # Автоматически назначаем владельцем пользователя @MPR_XO
        self.ensure_owner_rights(user)
        
        welcome_text = f"""
💖 **Добро пожаловать в Игру для взрослой компании**, {user.first_name}!

🎮 **Романтическая игра для взрослых** с **тремя режимами игры**:

🔥 **2 Пары** - **классический режим** для **4 человек**
👫 **ЖМЖ** - для компании **1 девушка + 2 парня**  
👫 **МЖМ** - для компании **2 девушки + 1 парень**

📋 **Как играть:**
• **Выберите подходящий режим игры**
• Проходите **4 уровня сложности**: **Знакомство → Флирт → Прелюдия → Fire** 🔥
• **Выполняйте задания** и **лучше узнавайте друг друга**

✨ **Новые возможности:**
• **3 режима игры** с **уникальными заданиями** для каждого
• **Персональные задания** для **мужчин и женщин**
• **Быстрый старт** - **мгновенное начало игры**
• **Редактор заданий** - **добавляйте свои задания**
• **Модерация** - **проверка пользовательских заданий**
• **Автоматическое сохранение** прогресса

**Выберите действие:**
        """
        
        await update.message.reply_text(
            welcome_text, 
            reply_markup=self.get_main_menu_keyboard(update.effective_user),
            parse_mode='Markdown'
        )

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на inline кнопки"""
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        
        # Обновляем активность пользователя
        self.db.update_user_activity(user.id)
        
        # Проверяем, заблокирован ли пользователь
        if self.db.is_user_blocked(user.id):
            block_info = self.db.get_user_block_info(user.id)
            if block_info and block_info['is_blocked']:
                if block_info['blocked_until']:
                    # Временная блокировка
                    try:
                        from datetime import datetime
                        blocked_until = datetime.fromisoformat(block_info['blocked_until'].replace('Z', '+00:00'))
                        date_str = blocked_until.strftime('%d.%m.%Y %H:%M')
                        reason = f"Причина: {block_info['block_reason']}" if block_info['block_reason'] else ""
                        await self.safe_edit_message(query,
                            f"❌ **Вы заблокированы до {date_str}**\n\n{reason}\n\n"
                            "Обратитесь к администратору для разблокировки:\n"
                            "📞 @Uzumymbec",
                            parse_mode=None
                        )
                    except:
                        await self.safe_edit_message(query,
                            f"❌ **Вы временно заблокированы**\n\n"
                            "Обратитесь к администратору для разблокировки:\n"
                            "📞 @Uzumymbec",
                            parse_mode=None
                        )
                else:
                    # Постоянная блокировка
                    reason = f"Причина: {block_info['block_reason']}" if block_info['block_reason'] else ""
                    await self.safe_edit_message(query,
                        f"❌ **Вы заблокированы навсегда**\n\n{reason}\n\n"
                        "Обратитесь к администратору для разблокировки:\n"
                        "📞 @Uzumymbec",
                        parse_mode=None
                    )
                return
        
        # Автоматически назначаем владельцем пользователя @MPR_XO при любом взаимодействии
        self.ensure_owner_rights(user)
        
        # Обновляем активность пользователя
        self.db.update_user_activity(user.id)
        
        data = query.data
        chat_id = query.message.chat_id
        user_id = query.from_user.id
        username = query.from_user.username or "Unknown"
        
        logger.debug(f"Button pressed: {data} by user {username} (ID: {user_id}) in chat {chat_id}")
        
        try:
            if data == "main_menu":
                await self.show_main_menu(query)
            elif data == "start_game_setup":
                await self.start_game_setup(update, context)
            elif data.startswith("quick_start_"):
                game_type = data.split("_", 2)[2]  # Извлекаем тип игры из callback_data
                await self.quick_start_game(update, context, game_type)
            elif data == "task_editor":
                await self.show_task_editor(query)
            elif data == "help":
                await self.show_help(query)
            elif data.startswith("emoji_"):
                await self.handle_emoji_selection(query, data)
            elif data.startswith("change_emoji_"):
                await self.handle_change_emoji(query, data)
            elif data.startswith("gender_") and not data.startswith("editor_mode_gender_"):
                await self.handle_gender_selection(update, context)
            elif data.startswith("editor_mode_gender_"):
                await self.handle_gender_selection(update, context)
            elif data.startswith("editor_mode_category_"):
                logger.info(f"🔧 EDITOR: button_handler routing editor_mode_category_ to handle_editor_category - data: '{data}'")
                await self.handle_editor_category(update, context)
            elif data.startswith("editor_mode_") and not data.startswith("editor_mode_category_") and not data.startswith("editor_mode_gender_"):
                logger.info(f"🔧 EDITOR: button_handler routing editor_mode_ to handle_editor_mode_selection - data: '{data}'")
                await self.handle_editor_mode_selection(update, context)
            elif data.startswith("editor_category_"):
                await self.handle_editor_category(update, context)
            elif data.startswith("confirm_delete_") and not data.startswith("editor_"):
                await self.handle_confirm_delete(query, data)
            elif data == "admin_panel":
                await self.show_admin_panel(query)
            elif data.startswith("btask_"):
                await self.handle_admin_action(update, context, data)
            elif data.startswith("admin_") and not data.startswith("admin_add_base_"):
                await self.handle_admin_action(update, context, data)
            elif data.startswith("mod_"):
                await self.handle_admin_action(update, context, data)
            elif data == "setup_players":
                await self.setup_players(query)
            elif data == "game_type_2couples":
                await self.handle_game_type_selection(query, "2couples")
            elif data == "game_type_fmf":
                await self.handle_game_type_selection(query, "fmf")
            elif data == "game_type_mfm":
                await self.handle_game_type_selection(query, "mfm")
            elif data == "game_mode_basic":
                await self.handle_game_mode_selection(query, "basic")
            elif data == "game_mode_extended":
                await self.handle_game_mode_selection(query, "extended")
            elif data == "confirm_players":
                await self.confirm_players_and_start(query)
            elif data == "start_game":
                await self.start_game(query)
            elif data == "start_playing":
                await self.start_game(query)
            elif data == "task_completed":
                await self.handle_task_completed(query)
            elif data == "skip_task":
                await self.handle_skip_task(query)
            elif data == "end_game":
                await self.handle_end_game(query)
            elif data == "next_category":
                await self.handle_next_category(query)
            elif data == "continue_current_category":
                await self.handle_continue_current_category(query)
            elif data.startswith("submit_moderation_"):
                await self.handle_submit_moderation(update, context)
            elif data.startswith("moderate_approve_"):
                task_id = data.replace("moderate_approve_", "")
                await self.handle_moderate_task(update, context, task_id, "approve")
            elif data.startswith("moderate_reject_"):
                task_id = data.replace("moderate_reject_", "")
                logger.info(f"🔍 MODERATION: Processing moderate_reject with task_id='{task_id}'")
                await self.handle_moderate_task(update, context, task_id, "reject")
            elif data.startswith("moderate_view_"):
                task_id = data.replace("moderate_view_", "")
                await self.handle_view_task_for_moderation(update, context, task_id)
            elif data.startswith("moderate_view_all_"):
                parts = data.replace("moderate_view_all_", "").split("_")
                mode_key = parts[0]
                category_key = parts[1]
                gender = parts[2]
                await self.handle_view_all_tasks_for_moderation(update, context, mode_key, category_key, gender)
            elif data.startswith("user_task_mode_"):
                await self.handle_user_task_mode_selection(update, context)
            elif data.startswith("user_task_category_"):
                await self.handle_user_task_category_selection(update, context)
            elif data.startswith("user_task_gender_"):
                await self.handle_user_task_gender_selection(update, context)
            else:
                await self.safe_edit_message(query,"Неизвестная команда", parse_mode=None)
            
        except Exception as e:
            logger.error(f"Ошибка в button_handler: {e}")
            error_logger.error(f"Ошибка в button_handler: {e}", exc_info=True)
            
            # Обработка различных типов ошибок
            if "Message is not modified" in str(e):
                # Сообщение не изменилось - это нормально, игнорируем
                pass
            elif "NetworkError" in str(e) or "RemoteProtocolError" in str(e):
                # Сетевая ошибка - пробуем отправить сообщение об ошибке
                try:
                    await query.edit_message_text(
                        "⚠️ Временные проблемы с сетью. Попробуйте еще раз через несколько секунд.",
                        parse_mode=None
                    )
                except:
                    pass
            elif "BadRequest" in str(e) and "message is not modified" in str(e).lower():
                # Сообщение не изменилось - игнорируем
                pass
            else:
                # Другие ошибки - показываем пользователю
                try:
                    await query.edit_message_text(
                        "❌ Произошла ошибка. Попробуйте еще раз.",
                        parse_mode=None
                    )
                except Exception as e2:
                    error_logger.error(f"Ошибка при отправке сообщения об ошибке: {e2}", exc_info=True)

    async def show_main_menu(self, query):
        """Показать главное меню"""
        user = query.from_user
        
        # Автоматически назначаем владельцем пользователя @MPR_XO при любом взаимодействии
        self.ensure_owner_rights(user)
        
        text = """
💖 **Игра для пар - Главное меню**

Выберите действие:
        """
        await self.safe_edit_message(
            query,
            text, 
            reply_markup=self.get_main_menu_keyboard(query.from_user)
        )

    async def quick_start_game(self, update: Update, context: ContextTypes.DEFAULT_TYPE, game_type: str = '2couples'):
        """Быстрый старт игры с дефолтными именами"""
        query = update.callback_query
        chat_id = query.message.chat_id
        user_id = query.from_user.id
        
        # Сохраняем выбранный режим игры перед инициализацией
        saved_game_mode = None
        if chat_id in self.user_games:
            saved_game_mode = self.user_games[chat_id].get('game_mode', 'basic')
        
        logger.info(f"Quick start game in chat {chat_id} by user {user_id}, game_type: {game_type}, saved_game_mode: {saved_game_mode}")
        
        # Получаем информацию о режиме игры
        mode_info = get_game_mode_info(game_type)
        
        # Создаем игроков в зависимости от режима
        players = []
        if game_type == '2couples':
            players = [
                {'name': 'Парень1', 'gender': 'male', 'emoji': '👨🏻‍🦱'},
                {'name': 'Девушка1', 'gender': 'female', 'emoji': '👩🏻‍🦱'},
                {'name': 'Парень2', 'gender': 'male', 'emoji': '👨🏻‍🦰'},
                {'name': 'Девушка2', 'gender': 'female', 'emoji': '👩🏻‍🦰'}
            ]
        elif game_type == 'fmf':
            players = [
                {'name': 'Девушка1', 'gender': 'female', 'emoji': '👩🏻‍🦱'},
                {'name': 'Парень', 'gender': 'male', 'emoji': '👨🏻‍🦱'},
                {'name': 'Девушка2', 'gender': 'female', 'emoji': '👩🏻‍🦰'}
            ]
        elif game_type == 'mfm':
            players = [
                {'name': 'Парень1', 'gender': 'male', 'emoji': '👨🏻‍🦱'},
                {'name': 'Девушка', 'gender': 'female', 'emoji': '👩🏻‍🦱'},
                {'name': 'Парень2', 'gender': 'male', 'emoji': '👨🏻‍🦰'}
            ]
        else:
            # Fallback на режим 2 пары
            players = [
                {'name': 'Парень1', 'gender': 'male', 'emoji': '👨🏻‍🦱'},
                {'name': 'Девушка1', 'gender': 'female', 'emoji': '👩🏻‍🦱'},
                {'name': 'Парень2', 'gender': 'male', 'emoji': '👨🏻‍🦰'},
                {'name': 'Девушка2', 'gender': 'female', 'emoji': '👩🏻‍🦰'}
            ]
        
        # Инициализируем состояние игры с игроками для выбранного режима
        self.user_games[chat_id] = {
            'players': players,
            'current_player_index': 0,
            'current_category': 'acquaintance',
            'used_tasks': {
                'acquaintance': {'male': [], 'female': [], 'common': []},
                'flirt': {'male': [], 'female': [], 'common': []},
                'prelude': {'male': [], 'female': [], 'common': []},
                'fire': {'male': [], 'female': [], 'common': []}
            },
            'tasks_completed_per_category': {
                'acquaintance': 0,
                'flirt': 0,
                'prelude': 0,
                'fire': 0
            },
            'is_game_started': True,
            'setup_step': 'completed',
            'game_mode': saved_game_mode or 'basic',  # Используем сохраненный режим
            'game_type': game_type  # Сохраняем выбранный тип игры
        }
        
        # Обновляем статистику - игра началась
        self.db.increment_games_played(user_id)
        
        # Показываем информацию об игроках и начинаем игру
        players_text = f"🎮 **Игра началась!**\n\n{mode_info['emoji']} **Режим: {mode_info['name']}**\n{mode_info['description']}\n\n👥 **Игроки:**\n"
        for i, player in enumerate(self.user_games[chat_id]['players'], 1):
            players_text += f"{i}. {player['emoji']} {player['name']} ({'М' if player['gender'] == 'male' else 'Ж'})\n"
        
        players_text += "\n🎯 **Правила:**\n• Выполняйте задания по очереди\n• Пропускайте, если не готовы\n• Наслаждайтесь процессом!\n\nНажмите 'Начать игру' для получения первого задания:"
        
        keyboard = [
            [InlineKeyboardButton("🎮 Начать игру", callback_data="start_playing")],
            [InlineKeyboardButton("← Назад в меню", callback_data="main_menu")]
        ]
        
        await self.safe_edit_message(
            query,
            players_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def handle_start_game_setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик для ConversationHandler - начать настройку игры"""
        await self.start_game_setup(update, context)

    async def start_game_setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начать настройку игры"""
        query = update.callback_query
        chat_id = query.message.chat_id
        user_id = query.from_user.id
        
        logger.info(f"Starting game setup in chat {chat_id} by user {user_id}")
        
        # Инициализируем состояние игры
        self.user_games[chat_id] = {
            'players': [],
            'current_player_index': 0,
            'current_category': 'acquaintance',
            'used_tasks': {
                'acquaintance': {'male': [], 'female': [], 'common': []},
                'flirt': {'male': [], 'female': [], 'common': []},
                'prelude': {'male': [], 'female': [], 'common': []},
                'fire': {'male': [], 'female': [], 'common': []}
            },
            'tasks_completed_per_category': {
                'acquaintance': 0,
                'flirt': 0,
                'prelude': 0,
                'fire': 0
            },
            'is_game_started': False,
            'setup_step': 'game_type',
            'game_type': None,
            'game_mode': None
        }
        
        text = """
🎮 **Выберите тип игры**

**👫👫 2 пары (4 игрока)**
• Классический режим для двух пар
• Мужчина + Женщина + Мужчина + Женщина

**👩‍❤️‍👨👩 2 девушки + 1 парень (3 игрока)**
• Режим ЖМЖ
• Две девушки и один мужчина

**👨‍❤️‍👨👩 2 парня + 1 девушка (3 игрока)**
• Режим МЖМ
• Два мужчины и одна девушка

Выберите тип игры:
        """
        
        keyboard = [
            [InlineKeyboardButton("👫👫 2 пары", callback_data="game_type_2couples")],
            [InlineKeyboardButton("👩‍❤️‍👨👩 2 девушки + 1 парень", callback_data="game_type_fmf")],
            [InlineKeyboardButton("👨‍❤️‍👨👩 2 парня + 1 девушка", callback_data="game_type_mfm")],
            [InlineKeyboardButton("← Назад", callback_data="main_menu")]
        ]
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
        
        # Не устанавливаем состояние ожидания, так как теперь используем кнопки
        return ConversationHandler.END

    async def handle_game_type_selection(self, query, game_type: str):
        """Обработка выбора типа игры"""
        chat_id = query.message.chat_id
        
        # Сохраняем выбранный тип игры
        if chat_id in self.user_games:
            self.user_games[chat_id]['game_type'] = game_type
            self.user_games[chat_id]['setup_step'] = 'mode'
        
        # Получаем информацию о типе игры
        mode_info = get_game_mode_info(game_type)
        
        text = f"""
{mode_info['emoji']} **{mode_info['name']} выбран!**

{mode_info['description']}

🎮 **Выберите режим игры**

**1️⃣ Стандартный режим**
• Игра только с базовыми вопросами
• Классические проверенные задания
• Безопасный контент для всех

**2️⃣ Расширенный режим**
• Включает в себя пользовательские задания, прошедшие модерацию
• Больше разнообразия и новых идей
• Задания от сообщества

Выберите режим:
        """
        
        keyboard = [
            [InlineKeyboardButton("1️⃣ Стандартный режим", callback_data="game_mode_basic")],
            [InlineKeyboardButton("2️⃣ Расширенный режим", callback_data="game_mode_extended")],
            [InlineKeyboardButton("← Назад к выбору типа", callback_data="setup_players")]
        ]
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def handle_game_mode_selection(self, query, mode: str):
        """Обработка выбора режима игры"""
        chat_id = query.message.chat_id
        
        # Сохраняем выбранный режим
        if chat_id in self.user_games:
            self.user_games[chat_id]['game_mode'] = mode
            self.user_games[chat_id]['setup_step'] = 'names'
        
        # Получаем информацию о типе игры
        game_type = self.user_games[chat_id].get('game_type', '2couples')
        mode_info = get_game_mode_info(game_type)
        
        mode_name = "Стандартный" if mode == "basic" else "Расширенный"
        mode_emoji = "1️⃣" if mode == "basic" else "2️⃣"
        
        # Формируем текст в зависимости от типа игры
        if game_type == '2couples':
            players_text = "Введите имена 4 игроков через запятую в формате:\n`Мужчина1, Женщина1, Мужчина2, Женщина2`\n\n**Пример:**\n`Алексей, Мария, Дмитрий, Анна`"
        elif game_type == 'fmf':
            players_text = "Введите имена 3 игроков через запятую в формате:\n`Девушка1, Парень, Девушка2`\n\n**Пример:**\n`Анна, Алексей, Мария`"
        elif game_type == 'mfm':
            players_text = "Введите имена 3 игроков через запятую в формате:\n`Парень1, Девушка, Парень2`\n\n**Пример:**\n`Алексей, Анна, Дмитрий`"
        else:
            players_text = "Введите имена игроков через запятую"
        
        text = f"""
{mode_emoji} **{mode_name} режим выбран!**

{mode_info['emoji']} **{mode_info['name']}**

👥 **Настройка игроков**

{players_text}

Или нажмите кнопку ниже для быстрого старта с именами по умолчанию.
        """
        
        keyboard = [
            [InlineKeyboardButton("🚀 Быстрый старт", callback_data=f"quick_start_{game_type}")],
            [InlineKeyboardButton("← Назад к выбору режима", callback_data=f"game_type_{game_type}")]
        ]
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def handle_player_names(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ввода имен игроков"""
        chat_id = update.effective_chat.id
        text = update.message.text.strip()
        
        names = [name.strip() for name in text.split(',')]
        
        # Получаем тип игры
        game_type = self.user_games[chat_id].get('game_type', '2couples')
        mode_info = get_game_mode_info(game_type)
        expected_count = mode_info['players_count']
        
        if len(names) != expected_count:
            if game_type == '2couples':
                error_text = "❌ Ошибка! Введите точно 4 имени через запятую.\nПример: `Алекс, Мария, Дмитрий, Анна`"
            elif game_type == 'fmf':
                error_text = "❌ Ошибка! Введите точно 3 имени через запятую.\nПример: `Анна, Алексей, Мария`"
            elif game_type == 'mfm':
                error_text = "❌ Ошибка! Введите точно 3 имени через запятую.\nПример: `Алексей, Анна, Дмитрий`"
            else:
                error_text = f"❌ Ошибка! Введите точно {expected_count} имени через запятую."
            
            await update.message.reply_text(error_text, parse_mode=None)
            return WAITING_PLAYER_NAMES
        
        # Создаем игроков с дефолтными эмодзи
        players = []
        
        if game_type == '2couples':
            # Классический режим: Мужчина, Женщина, Мужчина, Женщина
            default_emojis = ['👨', '👩', '👨‍🦱', '👩‍🦱']
            for i, name in enumerate(names):
                players.append({
                    'id': f'player_{i}',
                    'name': name,
                    'gender': 'male' if i % 2 == 0 else 'female',
                    'emoji': default_emojis[i]
                })
        elif game_type == 'fmf':
            # Режим ЖМЖ: Девушка, Парень, Девушка
            default_emojis = ['👩', '👨', '👩‍🦱']
            for i, name in enumerate(names):
                players.append({
                    'id': f'player_{i}',
                    'name': name,
                    'gender': 'female' if i % 2 == 0 else 'male',
                    'emoji': default_emojis[i]
                })
        elif game_type == 'mfm':
            # Режим МЖМ: Парень, Девушка, Парень
            default_emojis = ['👨', '👩', '👨‍🦱']
            for i, name in enumerate(names):
                players.append({
                    'id': f'player_{i}',
                    'name': name,
                    'gender': 'male' if i % 2 == 0 else 'female',
                    'emoji': default_emojis[i]
                })
        
        # Валидируем распределение по полу
        is_valid, error_msg = validate_players_for_mode(players, game_type)
        if not is_valid:
            await update.message.reply_text(f"❌ Ошибка! {error_msg}", parse_mode=None)
            return WAITING_PLAYER_NAMES
        
        self.user_games[chat_id]['players'] = players
        
        await self.show_player_setup_confirmation(update, chat_id)
        return ConversationHandler.END

    async def show_player_setup_confirmation(self, update, chat_id):
        """Показать подтверждение настройки игроков"""
        players = self.user_games[chat_id]['players']
        game_type = self.user_games[chat_id].get('game_type', '2couples')
        
        mode_info = get_game_mode_info(game_type)
        
        text = f"👥 **Игроки настроены ({mode_info['name']}):**\n\n"
        
        if game_type == '2couples':
            for i, player in enumerate(players):
                couple = "первой" if i < 2 else "второй"
                gender = "мужчина" if player['gender'] == 'male' else "женщина"
                text += f"{player['emoji']} **{player['name']}** - {gender} из {couple} пары\n"
        elif game_type == 'fmf':
            for i, player in enumerate(players):
                gender = "девушка" if player['gender'] == 'female' else "парень"
                text += f"{player['emoji']} **{player['name']}** - {gender}\n"
        elif game_type == 'mfm':
            for i, player in enumerate(players):
                gender = "парень" if player['gender'] == 'male' else "девушка"
                text += f"{player['emoji']} **{player['name']}** - {gender}\n"
        
        text += "\nВы можете изменить эмодзи игроков или начать игру:"
        
        keyboard = []
        for i, player in enumerate(players):
            keyboard.append([InlineKeyboardButton(
                f"Изменить эмодзи {player['name']}", 
                callback_data=f"change_emoji_{i}"
            )])
        
        keyboard.append([InlineKeyboardButton("🎮 Начать игру!", callback_data="start_game")])
        keyboard.append([InlineKeyboardButton("← Назад", callback_data="main_menu")])
        
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def handle_change_emoji(self, query, data):
        """Обработка нажатия кнопки изменения эмодзи"""
        parts = data.split('_')
        player_index = int(parts[2])  # change_emoji_0, change_emoji_1, etc.
        
        chat_id = query.message.chat_id
        if chat_id in self.user_games:
            player = self.user_games[chat_id]['players'][player_index]
            
            text = f"Выберите новый эмодзи для игрока **{player['name']}**:"
            
            await self.safe_edit_message(query,
                text,
                reply_markup=self.get_emoji_keyboard(player['gender'], player_index, "confirm_players"),
            parse_mode=None
        )

    async def handle_emoji_selection(self, query, data):
        """Обработка выбора эмодзи"""
        parts = data.split('_')
        player_index = int(parts[1])
        emoji = parts[2]
        
        chat_id = query.message.chat_id
        
        # Проверяем, что игра существует
        if chat_id not in self.user_games:
            logger.warning(f"Game not found for chat {chat_id} in emoji selection")
            await self.safe_edit_message(query, "❌ Игра не найдена. Начните новую игру.", parse_mode=None)
            return
            
        # Проверяем, что индекс игрока корректен
        if player_index >= len(self.user_games[chat_id]['players']):
            logger.warning(f"Invalid player index {player_index} for chat {chat_id}")
            await self.safe_edit_message(query, "❌ Неверный индекс игрока.", parse_mode=None)
            return
            
        self.user_games[chat_id]['players'][player_index]['emoji'] = emoji
        
        await query.answer(f"Эмодзи изменено на {emoji}")
        await self.show_player_setup_confirmation_edit(query, chat_id)

    async def show_player_setup_confirmation_edit(self, query, chat_id):
        """Обновить сообщение с подтверждением игроков"""
        players = self.user_games[chat_id]['players']
        game_mode = self.user_games[chat_id].get('game_mode', 'basic')
        
        mode_name = "Стандартный" if game_mode == "basic" else "Расширенный"
        mode_emoji = "1️⃣" if game_mode == "basic" else "2️⃣"
        
        text = f"{mode_emoji} **Режим игры: {mode_name}**\n\n"
        text += "👥 **Игроки настроены:**\n\n"
        for i, player in enumerate(players):
            couple = "первой" if i < 2 else "второй"
            gender = "мужчина" if player['gender'] == 'male' else "женщина"
            text += f"{player['emoji']} **{player['name']}** - {gender} из {couple} пары\n"
        
        text += "\nВы можете изменить эмодзи игроков или начать игру:"
        
        keyboard = []
        for i, player in enumerate(players):
            keyboard.append([InlineKeyboardButton(
                f"Изменить эмодзи {player['name']}", 
                callback_data=f"change_emoji_{i}"
            )])
        
        keyboard.append([InlineKeyboardButton("🎮 Начать игру!", callback_data="start_game")])
        keyboard.append([InlineKeyboardButton("← Назад", callback_data="main_menu")])
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def setup_players(self, query):
        """Настройка игроков (для совместимости)"""
        # Создаем объект update из query
        from telegram import Update
        from telegram.ext import ContextTypes
        update = Update(update_id=0, callback_query=query)
        await self.start_game_setup(update, None)

    async def confirm_players_and_start(self, query):
        """Подтвердить игроков и начать игру"""
        chat_id = query.message.chat_id
        
        # Показываем экран подтверждения игроков
        await self.show_player_setup_confirmation_edit(query, chat_id)

    async def start_game(self, query):
        """Начать игру"""
        chat_id = query.message.chat_id
        
        # Проверяем, что игра существует
        if chat_id not in self.user_games:
            logger.warning(f"Game not found for chat {chat_id} in start_game")
            await self.safe_edit_message(query, "❌ Игра не найдена. Начните новую игру.", parse_mode=None)
            return
            
        self.user_games[chat_id]['is_game_started'] = True
        
        # Сохраняем состояние игры в базе данных с game_mode
        game_type = self.user_games[chat_id].get('game_type', '2couples')
        self.db.save_game_state(chat_id, self.user_games[chat_id], game_type)
        
        await self.start_game_round(query)

    async def start_game_round(self, query):
        """Начать игровой раунд"""
        chat_id = query.message.chat_id
        game_state = self.user_games[chat_id]
        
        current_player = game_state['players'][game_state['current_player_index']]
        category_info = self.get_category_info(game_state['current_category'])
        if not category_info:
            await self.safe_edit_message(query, "❌ Категория не найдена")
            return
        
        # Получаем случайное задание
        task = self.get_next_task(chat_id, query.from_user.id)
        
        if not task:
            if self.can_move_to_next_category(chat_id):
                await self.show_next_category_modal(query, chat_id)
                return
            else:
                await self.show_next_category_modal(query, chat_id)
                return
        
        game_state['current_task'] = task
        
        text = f"""
🎮 **{category_info['emoji']} {category_info['name']}**
_{category_info['description']}_

👤 **Ход игрока:** {current_player['emoji']} {current_player['name']}

📝 **Задание:**
{task['text']}

Выполните задание и нажмите кнопку ниже:
        """
        
        await self.safe_edit_message(
            query,
            text,
            reply_markup=self.get_game_keyboard(chat_id)
        )

    def get_next_task(self, chat_id: int, user_id: int = None) -> Optional[dict]:
        """Получить следующее задание"""
        game_state = self.user_games[chat_id]
        current_player = game_state['players'][game_state['current_player_index']]
        category = game_state['current_category']
        game_mode = game_state.get('game_mode', 'basic')  # Режим игры: basic/extended
        game_type = game_state.get('game_type', '2couples')  # Тип игры: 2couples/fmf/mfm
        
        logger.debug(f"Getting next task for chat {chat_id}, player {current_player['name']}, category {category}, game_mode {game_mode}, game_type {game_type}")
        
        # Получаем задания из базы данных в зависимости от режима и типа игры
        if game_mode == 'basic':
            # Базовый режим: только базовые задания (task_type = 'base') для конкретного типа игры
            all_tasks = self.db.get_base_tasks_by_category_gender_and_type(category, current_player['gender'], game_type)
            common_tasks = self.db.get_base_tasks_by_category_gender_and_type(category, 'common', game_type)
        else:
            # Расширенный режим: базовые + одобренные пользовательские задания для конкретного типа игры
            all_tasks = self.db.get_extended_tasks_by_type(category, current_player['gender'], game_type, user_id)
            common_tasks = self.db.get_extended_tasks_by_type(category, 'common', game_type, user_id)
        
        used_gender_tasks = game_state['used_tasks'][category][current_player['gender']]
        used_common_tasks = game_state['used_tasks'][category]['common']
        
        # Фильтруем неиспользованные задания
        available_tasks = [t for t in all_tasks if t['id'] not in used_gender_tasks]
        available_common = [t for t in common_tasks if t['id'] not in used_common_tasks]
        
        all_available = available_tasks + available_common
        
        if not all_available:
            return None
        
        import random
        return random.choice(all_available)

    def can_move_to_next_category(self, chat_id: int) -> bool:
        """Проверить, можно ли перейти к следующей категории"""
        game_state = self.user_games[chat_id]
        categories = ['acquaintance', 'flirt', 'prelude', 'fire']
        current_index = categories.index(game_state['current_category'])
        return current_index < len(categories) - 1

    async def handle_task_completed(self, query):
        """Обработка выполнения задания"""
        chat_id = query.message.chat_id
        
        # Проверяем, что игра существует
        if chat_id not in self.user_games:
            logger.warning(f"Game not found for chat {chat_id} in handle_task_completed")
            await self.safe_edit_message(query, "❌ Игра не найдена. Начните новую игру.", parse_mode=None)
            return
            
        game_state = self.user_games[chat_id]
        
        logger.info(f"Task completed in chat {chat_id}, category {game_state['current_category']}, player {game_state['current_player_index']}")
        
        # Отмечаем задание как использованное
        if 'current_task' not in game_state:
            logger.warning(f"No current task in game state for chat {chat_id}")
            await self.safe_edit_message(query, "❌ Текущее задание не найдено. Начните новую игру.", parse_mode=None)
            return
            
        current_task = game_state['current_task']
        if current_task['gender'] == 'common':
            game_state['used_tasks'][game_state['current_category']]['common'].append(current_task['id'])
        else:
            current_player = game_state['players'][game_state['current_player_index']]
            game_state['used_tasks'][game_state['current_category']][current_player['gender']].append(current_task['id'])
        
        # Увеличиваем счетчик выполненных заданий в текущей категории
        game_state['tasks_completed_per_category'][game_state['current_category']] += 1
        
        # Переходим к следующему игроку в зависимости от типа игры
        game_type = game_state.get('game_type', '2couples')
        if game_type == '2couples':
            players_count = 4
        else:  # fmf или mfm
            players_count = 3
        
        game_state['current_player_index'] = (game_state['current_player_index'] + 1) % players_count
        
        # Проверяем, достигли ли 20 заданий в текущей категории
        if game_state['tasks_completed_per_category'][game_state['current_category']] >= 20:
            await self.show_category_completion_modal(query, chat_id)
        else:
            await self.start_game_round(query)

    async def handle_skip_task(self, query):
        """Обработка пропуска задания"""
        await self.handle_task_completed(query)  # Логика та же

    async def show_category_completion_modal(self, query, chat_id):
        """Показать модальное окно завершения категории с предложением перехода"""
        game_state = self.user_games[chat_id]
        current_category_info = self.get_category_info(game_state['current_category'])
        if not current_category_info:
            await self.safe_edit_message(query, "❌ Текущая категория не найдена")
            return
        
        categories = ['acquaintance', 'flirt', 'prelude', 'fire']
        current_index = categories.index(game_state['current_category'])
        
        text = f"""
🎉 **Поздравляем!**

Вы выполнили 20 заданий в категории "{current_category_info['name']}"!

Что хотите сделать дальше?
        """
        
        keyboard = []
        
        # Если есть следующая категория, предлагаем перейти к ней
        if current_index < len(categories) - 1:
            next_category = categories[current_index + 1]
            next_category_info = self.get_category_info(next_category)
            if next_category_info:
                keyboard.append([InlineKeyboardButton(
                    f"▶️ Перейти к {next_category_info['emoji']} {next_category_info['name']}", 
                    callback_data="next_category"
                )])
        
        # Всегда предлагаем продолжить в текущей категории
        keyboard.append([InlineKeyboardButton(
            f"🔄 Продолжить в {current_category_info['emoji']} {current_category_info['name']}", 
            callback_data="continue_current_category"
        )])
        
        keyboard.append([InlineKeyboardButton("🏠 Завершить игру", callback_data="end_game")])
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def show_next_category_modal(self, query, chat_id):
        """Показать модальное окно перехода к следующей категории (когда все задания закончились)"""
        game_state = self.user_games[chat_id]
        current_category_info = self.get_category_info(game_state['current_category'])
        if not current_category_info:
            await self.safe_edit_message(query, "❌ Текущая категория не найдена")
            return
        
        categories = ['acquaintance', 'flirt', 'prelude', 'fire']
        current_index = categories.index(game_state['current_category'])
        
        if current_index < len(categories) - 1:
            next_category = categories[current_index + 1]
            next_category_info = self.get_category_info(next_category)
            if not next_category_info:
                await self.safe_edit_message(query, "❌ Следующая категория не найдена")
                return
            
            text = f"""
🎉 **Уровень пройден!**

Все задания категории "{current_category_info['name']}" завершены!

Переходим к следующему уровню:
{next_category_info['emoji']} **{next_category_info['name']}**
_{next_category_info['description']}_

Готовы продолжить?
            """
            
            keyboard = [
                [InlineKeyboardButton("▶️ Следующий уровень", callback_data="next_category")],
                [InlineKeyboardButton("🏠 Завершить игру", callback_data="end_game")]
            ]
        else:
            # Это последняя категория
            text = f"""
🎊 **Игра завершена!**

Поздравляем! Вы прошли все уровни романтической игры!

Надеемся, вы отлично провели время и узнали друг друга лучше! 💕

Хотите сыграть еще раз?
            """
            
            keyboard = [
                [InlineKeyboardButton("🔄 Новая игра", callback_data="start_game_setup")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def handle_next_category(self, query):
        """Переход к следующей категории"""
        chat_id = query.message.chat_id
        
        # Проверяем, что игра существует
        if chat_id not in self.user_games:
            logger.warning(f"Game not found for chat {chat_id} in handle_next_category")
            await self.safe_edit_message(query, "❌ Игра не найдена. Начните новую игру.", parse_mode=None)
            return
            
        game_state = self.user_games[chat_id]
        
        categories = ['acquaintance', 'flirt', 'prelude', 'fire']
        current_index = categories.index(game_state['current_category'])
        next_category = categories[current_index + 1]
        
        game_state['current_category'] = next_category
        game_state['used_tasks'][next_category] = {'male': [], 'female': [], 'common': []}
        game_state['tasks_completed_per_category'][next_category] = 0
        
        await self.start_game_round(query)

    async def handle_continue_current_category(self, query):
        """Продолжить игру в текущей категории"""
        chat_id = query.message.chat_id
        game_state = self.user_games[chat_id]
        
        # Просто продолжаем игру в текущей категории
        await self.start_game_round(query)


    async def handle_end_game(self, query):
        """Завершить игру"""
        chat_id = query.message.chat_id
        if chat_id in self.user_games:
            del self.user_games[chat_id]
        
        await self.show_main_menu(query)

    async def show_task_editor(self, query):
        """Показать редактор заданий"""
        text = """
📝 **Пользовательский редактор заданий**

Создавайте свои задания для игры! 

Все пользовательские задания:
• По умолчанию в расширенном режиме
• Доступны только вам до модерации
• После модерации становятся публичными

Выберите режим игры для создания задания:
        """
        
        await self.safe_edit_message(
            query,
            text,
            reply_markup=self.get_user_task_mode_keyboard()
        )

    async def handle_user_task_mode_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора режима игры для пользовательского задания"""
        query = update.callback_query
        data = query.data
        
        # Парсим callback_data: user_task_mode_MODE_KEY
        mode_key = data.replace("user_task_mode_", "")
        
        # Находим информацию о режиме
        mode_info = None
        for mode in GAME_MODES:
            if mode['key'] == mode_key:
                mode_info = mode
                break
        
        if not mode_info:
            await self.safe_edit_message(query, "❌ Режим игры не найден", parse_mode=None)
            return
        
        # Сохраняем режим в контекст
        context.user_data['user_task_mode'] = mode_key
        
        text = f"""
📝 **Создание пользовательского задания**

{mode_info['emoji']} **{mode_info['name']}**
_{mode_info['description']}_

Выберите уровень задания:
        """
        
        await self.safe_edit_message(
            query,
            text,
            reply_markup=self.get_user_task_category_keyboard()
        )

    async def handle_user_task_category_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора категории для пользовательского задания"""
        query = update.callback_query
        data = query.data
        
        # Парсим callback_data: user_task_category_CATEGORY_KEY
        category_key = data.replace("user_task_category_", "")
        
        # Находим информацию о категории
        category_info = None
        for category in CATEGORIES:
            if category['key'] == category_key:
                category_info = category
                break
        
        if not category_info:
            await self.safe_edit_message(query, "❌ Категория не найдена", parse_mode=None)
            return
        
        # Сохраняем категорию в контекст
        context.user_data['user_task_category'] = category_key
        
        text = f"""
📝 **Создание пользовательского задания**

{category_info['emoji']} **{category_info['name']}**
_{category_info['description']}_

Выберите для кого предназначено задание:
        """
        
        await self.safe_edit_message(
            query,
            text,
            reply_markup=self.get_user_task_gender_keyboard()
        )

    async def handle_user_task_gender_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора пола для пользовательского задания"""
        query = update.callback_query
        data = query.data
        
        # Парсим callback_data: user_task_gender_GENDER
        gender = data.replace("user_task_gender_", "")
        
        # Сохраняем пол в контекст
        context.user_data['user_task_gender'] = gender
        
        gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие для обоих полов'}
        
        # Получаем информацию о режиме и категории
        mode_key = context.user_data.get('user_task_mode')
        category_key = context.user_data.get('user_task_category')
        
        mode_info = None
        for mode in GAME_MODES:
            if mode['key'] == mode_key:
                mode_info = mode
                break
        
        category_info = None
        for category in CATEGORIES:
            if category['key'] == category_key:
                category_info = category
                break
        
        if not mode_info or not category_info:
            await self.safe_edit_message(query, "❌ Ошибка в данных", parse_mode=None)
            return
        
        text = f"""
📝 **Создание пользовательского задания**

🎯 **Режим:** {mode_info['emoji']} {mode_info['name']}
📂 **Уровень:** {category_info['emoji']} {category_info['name']}
👥 **Для:** {gender_names[gender]}

**Напишите текст задания:**
(от 10 до 500 символов)
        """
        
        await self.safe_edit_message(
            query,
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="task_editor")]]),
            parse_mode=None
        )
        
        return USER_TASK_TEXT

    async def handle_user_task_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ввода текста пользовательского задания"""
        task_text = update.message.text.strip()
        
        # Валидация длины
        if len(task_text) < 10:
            await update.message.reply_text(
                "❌ Задание слишком короткое. Минимум 10 символов.\n"
                "Попробуйте еще раз:"
            )
            return USER_TASK_TEXT
        
        if len(task_text) > 500:
            await update.message.reply_text(
                "❌ Задание слишком длинное. Максимум 500 символов.\n"
                "Попробуйте еще раз:"
            )
            return USER_TASK_TEXT
        
        # Получаем данные из контекста
        mode_key = context.user_data.get('user_task_mode')
        category_key = context.user_data.get('user_task_category')
        gender = context.user_data.get('user_task_gender')
        
        if not all([mode_key, category_key, gender]):
            await update.message.reply_text("❌ Ошибка в данных. Начните заново.")
            return ConversationHandler.END
        
        # Генерируем ID задания
        import uuid
        task_id = f"user_{uuid.uuid4().hex[:8]}"
        
        # Добавляем задание в базу данных
        success = self.db.add_custom_task(task_id, task_text, category_key, gender, mode_key, update.effective_user.id)
        
        if success:
            # Получаем информацию для отображения
            mode_info = None
            category_info = None
            for mode in GAME_MODES:
                if mode['key'] == mode_key:
                    mode_info = mode
                    break
            for category in CATEGORIES:
                if category['key'] == category_key:
                    category_info = category
                    break
            
            gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие для обоих полов'}
            
            message_text = (
                f"✅ **Задание создано!**\n\n"
                f"🎯 **Режим:** {mode_info['emoji']} {mode_info['name']}\n"
                f"📂 **Уровень:** {category_info['emoji']} {category_info['name']}\n"
                f"👥 **Для:** {gender_names[gender]}\n"
                f"📝 **Текст:** {task_text}\n\n"
                f"🔒 **Задание видно только вам**\n"
                f"📤 Отправьте его на модерацию, чтобы сделать доступным для всех"
            )
            
            keyboard = [
                [InlineKeyboardButton("📤 Направить на модерацию", callback_data=f"submit_moderation_{task_id}")],
                [InlineKeyboardButton("➕ Создать еще", callback_data="task_editor")],
                [InlineKeyboardButton("← Главное меню", callback_data="main_menu")]
            ]
            
            await update.message.reply_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
        else:
            await update.message.reply_text(
                "❌ Ошибка при создании задания. Попробуйте еще раз:"
            )
            return USER_TASK_TEXT
        
        return ConversationHandler.END

    async def handle_editor_mode_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора режима игры в редакторе"""
        query = update.callback_query
        data = query.data
        logger.info(f"🔧 EDITOR: handle_editor_mode_selection called with data: '{data}' by user {query.from_user.id} ({query.from_user.username})")
        
        # Парсим callback_data: editor_mode_MODE_KEY (только простые режимы, не editor_mode_category_)
        if not data.startswith("editor_mode_") or data.startswith("editor_mode_category_") or data.startswith("editor_mode_gender_"):
            logger.error(f"Invalid callback data format for mode selection: {data}")
            await self.safe_edit_message(query, "❌ Ошибка формата данных", parse_mode=None)
            return
            
        mode_key = data.replace("editor_mode_", "")
        
        # Отладочная информация
        logger.info(f"handle_editor_mode_selection: data={data}, mode_key={mode_key}")
        logger.info(f"Available modes: {[mode['key'] for mode in GAME_MODES]}")
        
        # Находим информацию о режиме
        mode_info = None
        for mode in GAME_MODES:
            if mode['key'] == mode_key:
                mode_info = mode
                break
        
        if not mode_info:
            logger.error(f"Mode not found: {mode_key}")
            await self.safe_edit_message(query, f"❌ Режим игры не найден: {mode_key}", parse_mode=None)
            return
        
        text = f"""
📝 **Редактор заданий**

Выберите тип игры для редактирования заданий:

{mode_info['emoji']} **{mode_info['name']}**
_{mode_info['description']}_

Выберите категорию для редактирования:
        """
        
        await self.safe_edit_message(
            query,
            text,
            reply_markup=self.get_category_keyboard("editor", mode_key)
        )

    async def handle_editor_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора категории в редакторе"""
        query = update.callback_query
        data = query.data
        logger.info(f"🔧 EDITOR: handle_editor_category called with data: '{data}' by user {query.from_user.id} ({query.from_user.username})")
        
        # Парсим callback_data: editor_mode_category_MODE_CATEGORY
        if data.startswith("editor_mode_category_"):
            parts = data.replace("editor_mode_category_", "").split("_")
            if len(parts) >= 2:
                mode_key = parts[0]
                category = parts[1]
            else:
                # Если формат неправильный, пытаемся извлечь из user_data
                mode_key = context.user_data.get('editor_mode')
                category = parts[0] if parts else "flirt"
        else:
            # Старый формат: editor_category_CATEGORY
            category = data.replace("editor_category_", "")
            mode_key = None
        
        category_info = self.get_category_info(category)
        if not category_info:
            await self.safe_edit_message(query, "❌ Категория не найдена")
            return
        
        if mode_key:
            text = f"""
📝 **Редактор заданий - {category_info['emoji']} {category_info['name']}**
_{category_info['description']}_

Выберите тип заданий для редактирования:
            """
            
            await self.safe_edit_message(
                query,
                text,
                reply_markup=self.get_gender_keyboard(category, mode_key)
            )
        else:
            # Старый формат для обратной совместимости
            text = f"""
📝 **Редактор заданий - {category_info['emoji']} {category_info['name']}**
_{category_info['description']}_

Выберите тип заданий для редактирования:
            """
            
            await self.safe_edit_message(
                query,
                text,
                reply_markup=self.get_gender_keyboard(category)
            )

    async def handle_gender_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора типа заданий"""
        query = update.callback_query
        data = query.data
        
        # Проверяем формат callback_data
        if data.startswith("editor_mode_gender_"):
            # Новый формат: editor_mode_gender_MODE_CATEGORY_GENDER
            parts = data.replace("editor_mode_gender_", "").split("_")
            if len(parts) >= 3:
                mode_key = parts[0]
                category = parts[1]
                gender = parts[2]
            else:
                # Если формат неправильный, пытаемся извлечь из user_data
                mode_key = context.user_data.get('editor_mode')
                category = parts[0] if len(parts) > 0 else "flirt"
                gender = parts[1] if len(parts) > 1 else None
        elif data.startswith("editor_mode_category_"):
            # Формат: editor_mode_category_MODE_CATEGORY
            # Это означает, что пользователь выбрал категорию, нужно показать выбор типа заданий
            parts = data.replace("editor_mode_category_", "").split("_")
            mode_key = parts[0] if len(parts) > 0 else context.user_data.get('editor_mode')
            category = parts[1] if len(parts) > 1 else "flirt"
            gender = None  # Нужно выбрать тип заданий
        else:
            # Старый формат: gender_CATEGORY_GENDER
            parts = data.split('_')
            category = parts[1]
            gender = parts[2]
            mode_key = None
        
        # Получаем chat_id
        chat_id = query.message.chat_id
        
        # Если gender не выбран, показываем выбор типа заданий
        if gender is None:
            category_info = self.get_category_info(category)
            if not category_info:
                await self.safe_edit_message(query, "❌ Категория не найдена")
                return
            
            text = f"""
📝 **Редактор заданий - {category_info['emoji']} {category_info['name']}**
_{category_info['description']}_

Выберите тип заданий для редактирования:
            """
            
            await self.safe_edit_message(
                query,
                text,
                reply_markup=self.get_gender_keyboard(category, mode_key)
            )
            return
        
        # Определяем режим игры
        if mode_key:
            game_type = mode_key
        else:
            # Определяем режим игры из состояния чата (для обратной совместимости)
            game_type = '2couples'  # По умолчанию
            if chat_id in self.user_games:
                game_type = self.user_games[chat_id].get('game_type', '2couples')
        
        tasks = self.db.get_tasks_by_mode_and_level(game_type, category, gender, query.from_user.id)
        
        gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие'}
        category_info = self.get_category_info(category)
        if not category_info:
            await self.safe_edit_message(query, "❌ Категория не найдена")
            return
        
        text = f"""
📝 **{category_info['emoji']} {category_info['name']} - {gender_names[gender]} задания**
_{category_info['description']}_

Всего заданий: {len(tasks)}

Выберите действие:
        """
        
        keyboard = []
        
        # Создаем кнопки в зависимости от формата
        if mode_key:
            # Новый формат с режимом игры
            keyboard.extend([
                [InlineKeyboardButton("➕ Добавить задание", callback_data=f"add_task_{mode_key}_{category}_{gender}")],
                [InlineKeyboardButton("📋 Просмотреть задания", callback_data=f"view_tasks_{mode_key}_{category}_{gender}")],
                [InlineKeyboardButton("🗑️ Удалить задание", callback_data=f"delete_task_{mode_key}_{category}_{gender}")],
                [InlineKeyboardButton("← Назад", callback_data=f"editor_mode_category_{mode_key}_{category}")]
            ])
        else:
            # Старый формат для обратной совместимости
            keyboard.extend([
                [InlineKeyboardButton("➕ Добавить задание", callback_data=f"add_task_{category}_{gender}")],
                [InlineKeyboardButton("📋 Просмотреть задания", callback_data=f"view_tasks_{category}_{gender}")],
                [InlineKeyboardButton("🗑️ Удалить задание", callback_data=f"delete_task_{category}_{gender}")],
                [InlineKeyboardButton("← Назад", callback_data=f"editor_category_{category}")]
            ])
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def show_help(self, query):
        """Показать справку"""
        text = """
💖 ИГРА ДЛЯ ПАР
Ваш персональный проводник в мир страсти и близости

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 ОБ ИГРЕ
Игра для пар — это интерактивная игра для пар, которая поможет вам:
• Раскрепоститься и лучше узнать друг друга
• Создать романтическую атмосферу
• Углубить отношения через откровенные разговоры
• Весело и страстно провести время вместе

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎮 КАК ИГРАТЬ
1️⃣ Соберитесь компанией из 4 человек (2 пары)
2️⃣ Нажмите "🎮 Начать игру"
3️⃣ Введите имена всех игроков через запятую
4️⃣ Выберите эмодзи для каждого игрока (опционально)
5️⃣ Проходите уровни, выполняя задания по очереди
6️⃣ Наслаждайтесь процессом! 😉

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 КАТЕГОРИИ ЗАДАНИЙ

💫 ЗНАКОМСТВО
темы для раскрепощения, общения, понимания "темы".
• Легкие вопросы для разминки
• Истории из детства и мечты
• Хобби, интересы и планы
• Создание доверительной атмосферы

😉 ФЛИРТ
задания с поцелуями, прикосновениями, флиртом. Поднятие "градуса" вечера
• Комплименты и игривые задания
• Романтические истории
• Идеальные свидания
• Секреты обольщения

💜 ПРЕЛЮДИЯ
Ещё более откровенные задания, в основном, для девушек. Прелюдия к сексу. Вы все уже почти голые и этот уровень заданий поможет довести дело до тела, благодаря откровенным ласкам.
• Чувственные моменты
• Создание интимной атмосферы
• Эмоциональная близость
• Откровенные фантазии

🔥 FIRE
Уже точные позы и задания для секса. На практике: после 2-3 заданий игроки забывают об игре. Откровенные задания позволят насладиться в полной мере форматом МЖМЖ
• Страстные признания
• Смелые желания
• Пик интимности
• Полное раскрепощение

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✨ ФУНКЦИОНАЛ

🎭 Персонализация
• Выбор эмодзи для каждого игрока
• Персональные имена
• Индивидуальные задания по полу

💾 Сохранение прогресса
• Автоматическое сохранение состояния игры
• Возможность продолжить с любого места
• История выполненных заданий

📝 Редактор заданий
• Добавление собственных заданий
• Предложение заданий для всех пользователей
• Модерация контента

🎯 Гибкость игры
• Возможность пропускать задания
• Досрочное завершение игры
• Переход между уровнями

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🤖 КОМАНДЫ БОТА
/start — Главное меню
/help — Эта справка

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📞 ПОДДЕРЖКА
Если у вас есть вопросы или проблемы, обращайтесь к администратору:
• @Uzumymbec — техническая поддержка и помощь

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 СОВЕТЫ
• Создайте уютную атмосферу
• Будьте открыты и честны
• Не торопитесь — наслаждайтесь процессом
• Уважайте границы друг друга

Удачной игры! 💕
        """
        
        await self.safe_edit_message(query,
            text,
            reply_markup=self.get_back_keyboard("main_menu"),
            parse_mode=None
        )

    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений"""
        user = update.effective_user
        
        # Обновляем активность пользователя
        self.db.update_user_activity(user.id)
        
        # Автоматически назначаем владельцем пользователя @MPR_XO при любом взаимодействии
        self.ensure_owner_rights(user)
        
        # Проверяем, не находимся ли мы в состоянии ожидания имен игроков
        chat_id = update.effective_chat.id
        if chat_id in self.user_games and self.user_games[chat_id].get('setup_step') == 'names':
            await self.handle_player_names(update, context)
        elif chat_id in self.user_games and self.user_games[chat_id].get('setup_step') == 'add_base_task':
            await self.handle_add_base_task_text(update, context)
        elif chat_id in self.user_games and self.user_games[chat_id].get('setup_step') == 'edit_base_task':
            await self.handle_edit_base_task_text(update, context)
        else:
            # Проверяем, является ли это командой добавления администратора
            if self.can_manage_administrators(update.effective_user):
                text = update.message.text.strip()
                if text.startswith('@') and ' ' in text:
                    parts = text.split(' ', 1)
                    username = parts[0][1:]  # Убираем @
                    level = parts[1].lower()
                    
                    if level in ['admin', 'moderator']:
                        await self.handle_add_admin_command(update, username, level)
                        return
            
            # Проверяем, является ли это поисковым запросом (для владельца и администраторов)
            if self.has_admin_access(update.effective_user):
                text = update.message.text.strip()
                # Проверяем, не команда ли это
                if not text.startswith('/') and len(text) > 1:
                    await self.handle_user_search(update, text)
                    return
            
            # Отправляем в главное меню
            await update.message.reply_text(
                "Используйте кнопки для навигации или команду /start для главного меню",
                reply_markup=self.get_main_menu_keyboard(update.effective_user)
            )




    async def handle_view_tasks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Просмотр заданий"""
        query = update.callback_query
        data = query.data
        parts = data.split('_')
        
        # Проверяем формат callback_data
        if len(parts) >= 5 and parts[0] == "view" and parts[1] == "tasks":
            if len(parts) >= 6 and parts[2] in ['2couples', 'fmf', 'mfm']:
                # Новый формат: view_tasks_MODE_CATEGORY_GENDER
                mode_key = parts[2]
                category = parts[3]
                gender = parts[4]
            else:
                # Старый формат: view_tasks_CATEGORY_GENDER
                category = parts[2]
                gender = parts[3]
                mode_key = None
        else:
            # Fallback для старых форматов
            category = parts[2] if len(parts) > 2 else ""
            gender = parts[3] if len(parts) > 3 else ""
            mode_key = None
        
        # Получаем chat_id
        chat_id = query.message.chat_id
        
        # Определяем режим игры
        if mode_key:
            game_type = mode_key
        else:
            # Определяем режим игры из состояния чата (для обратной совместимости)
            game_type = '2couples'  # По умолчанию
            if chat_id in self.user_games:
                game_type = self.user_games[chat_id].get('game_type', '2couples')
        
        tasks = self.db.get_tasks_by_mode_and_level(game_type, category, gender, query.from_user.id)
        
        gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие'}
        category_info = self.get_category_info(category)
        if not category_info:
            await self.safe_edit_message(query, "❌ Категория не найдена")
            return
        
        if not tasks:
            text = f"""
📋 **{category_info['emoji']} {category_info['name']} - {gender_names[gender]} задания**
_{category_info['description']}_

Заданий пока нет. Добавьте первое задание!
            """
        else:
            text = f"""
📋 **{category_info['emoji']} {category_info['name']} - {gender_names[gender]} задания**
_{category_info['description']}_

Всего заданий: {len(tasks)}

            """
            
            # Показываем все задания (ограничиваем до 50 для предотвращения переполнения)
            max_tasks = 50
            tasks_to_show = tasks[:max_tasks]
            
            for i, task in enumerate(tasks_to_show, 1):
                text += f"{i}. {task['text'][:100]}{'...' if len(task['text']) > 100 else ''}\n\n"
            
            if len(tasks) > max_tasks:
                text += f"... и еще {len(tasks) - max_tasks} заданий (показано {max_tasks} из {len(tasks)})"
        
        keyboard = [
            [InlineKeyboardButton("← Назад", callback_data=f"gender_{category}_{gender}")]
        ]
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def handle_delete_task_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню удаления заданий"""
        query = update.callback_query
        data = query.data
        parts = data.split('_')
        
        # Проверяем формат callback_data
        if len(parts) >= 5 and parts[0] == "delete" and parts[1] == "task":
            if len(parts) >= 6 and parts[2] in ['2couples', 'fmf', 'mfm']:
                # Новый формат: delete_task_MODE_CATEGORY_GENDER
                mode_key = parts[2]
                category = parts[3]
                gender = parts[4]
            else:
                # Старый формат: delete_task_CATEGORY_GENDER
                category = parts[2]
                gender = parts[3]
                mode_key = None
        else:
            # Fallback для старых форматов
            category = parts[2] if len(parts) > 2 else ""
            gender = parts[3] if len(parts) > 3 else ""
            mode_key = None
        
        # Получаем chat_id
        chat_id = query.message.chat_id
        
        # Определяем режим игры
        if mode_key:
            game_type = mode_key
        else:
            # Определяем режим игры из состояния чата (для обратной совместимости)
            game_type = '2couples'  # По умолчанию
            if chat_id in self.user_games:
                game_type = self.user_games[chat_id].get('game_type', '2couples')
        
        tasks = self.db.get_tasks_by_mode_and_level(game_type, category, gender, query.from_user.id)
        custom_tasks = [task for task in tasks if task.get('is_custom', False)]
        
        gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие'}
        category_info = self.get_category_info(category)
        if not category_info:
            await self.safe_edit_message(query, "❌ Категория не найдена")
            return
        
        if not custom_tasks:
            text = f"""
🗑️ **Удаление заданий**

{category_info['emoji']} {category_info['name']} - {gender_names[gender]}
_{category_info['description']}_

У вас нет пользовательских заданий для удаления.
Можно удалять только задания, которые вы добавили сами.
            """
            # Создаем кнопку "Назад" в зависимости от формата
            if mode_key:
                back_data = f"editor_mode_category_{mode_key}_{category}"
            else:
                back_data = f"editor_category_{category}"
            
            keyboard = [
                [InlineKeyboardButton("← Назад", callback_data=back_data)]
            ]
        else:
            text = f"""
🗑️ **Удаление заданий**

{category_info['emoji']} {category_info['name']} - {gender_names[gender]}
_{category_info['description']}_

Выберите задание для удаления:
            """
            
            keyboard = []
            for i, task in enumerate(custom_tasks[:5]):  # Показываем первые 5
                short_text = task['text'][:30] + '...' if len(task['text']) > 30 else task['text']
                keyboard.append([InlineKeyboardButton(
                    f"🗑️ {short_text}", 
                    callback_data=f"confirm_delete_{task['id']}"
                )])
            
            # Создаем кнопку "Назад" в зависимости от формата
            if mode_key:
                back_data = f"editor_mode_category_{mode_key}_{category}"
            else:
                back_data = f"editor_category_{category}"
            
            keyboard.append([InlineKeyboardButton("← Назад", callback_data=back_data)])
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def handle_confirm_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтверждение удаления задания"""
        query = update.callback_query
        data = query.data
        task_id = data.replace("confirm_delete_", "")
        
        # Получаем информацию о задании
        try:
            task = self.db.get_task_by_id(task_id)
        except AttributeError as e:
            logger.error(f"AttributeError in get_task_by_id: {e}")
            logger.error(f"Database object methods: {[method for method in dir(self.db) if not method.startswith('_')]}")
            raise
        if not task:
            await self.safe_edit_message(query,"❌ Задание не найдено.", parse_mode=None)
            return
        
        # Удаляем задание
        success = self.db.delete_custom_task(task_id, query.from_user.id)
        
        if success:
            await self.safe_edit_message(query,
                f"✅ Задание удалено!\n\n"
                f"Текст: {task['text'][:100]}{'...' if len(task['text']) > 100 else ''}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("← К редактору", callback_data="task_editor")]
                ]),
                parse_mode=None
            )
        else:
            await self.safe_edit_message(query,
                "❌ Ошибка при удалении задания. Возможно, вы не являетесь автором этого задания.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("← К редактору", callback_data="task_editor")]
                ]),
                parse_mode=None
            )

    async def show_admin_panel(self, query):
        """Показать админ-панель"""
        if not self.has_admin_access(query.from_user):
            await self.safe_edit_message(query,"❌ Доступ запрещен. Только для владельцев и администраторов.", parse_mode=None)
            return
        
        username = query.from_user.username or "Администратор"
        
        # Получаем уровень администратора с учетом фиксированного владельца
        if query.from_user.username and query.from_user.username.lower() == 'mpr_xo':
            admin_level = 'owner'
        else:
            admin_level = self.db.get_admin_level(query.from_user.id)
        
        # Определяем уровень доступа
        is_owner = admin_level == 'owner'
        is_admin = admin_level == 'admin'
        
        if is_owner:
            text = f"""⚙️ Админ-панель (Владелец)

Добро пожаловать, {username}!

Доступные функции:"""
            
            keyboard = [
                [InlineKeyboardButton("📝 Управление базовыми заданиями", callback_data="admin_base_tasks")],
                [InlineKeyboardButton("🔍 Модерация заданий", callback_data="admin_moderation")],
                [InlineKeyboardButton("👑 Администраторы", callback_data="admin_administrators")],
                [InlineKeyboardButton("📊 Статистика бота", callback_data="admin_stats")],
                [InlineKeyboardButton("👥 Управление пользователями", callback_data="admin_users")],
                [InlineKeyboardButton("🗑️ Очистка данных", callback_data="admin_cleanup")],
                [InlineKeyboardButton("🔄 Перезагрузить БД", callback_data="admin_reload_db")],
                [InlineKeyboardButton("← Назад", callback_data="main_menu")]
            ]
        elif is_admin:
            # Ограниченный доступ для администраторов
            text = f"""⚙️ Админ-панель (Администратор)

Добро пожаловать, {username}!

Доступные функции:"""
            
            keyboard = [
                [InlineKeyboardButton("📝 Управление базовыми заданиями", callback_data="admin_base_tasks")],
                [InlineKeyboardButton("🔍 Модерация заданий", callback_data="admin_moderation")],
                [InlineKeyboardButton("🔄 Перезагрузить БД", callback_data="admin_reload_db")],
                [InlineKeyboardButton("← Назад", callback_data="main_menu")]
            ]
        else:
            # Это не должно происходить, но на всякий случай
            await self.safe_edit_message(query,"❌ Недостаточно прав для доступа к админ-панели.", parse_mode=None)
            return
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
    
    async def show_admin_moderation(self, query):
        """Показать панель модерации заданий"""
        logger.info(f"🔍 MODERATION: show_admin_moderation called by user {query.from_user.id} ({query.from_user.username})")
        
        # Проверяем права доступа к модерации
        if not self.has_moderation_access(query.from_user):
            logger.warning(f"❌ MODERATION: Access denied for user {query.from_user.id} ({query.from_user.username})")
            await self.safe_edit_message(query,"❌ Доступ запрещен. Только для администраторов и модераторов.", parse_mode=None)
            return
        
        # Получаем статистику по модерации
        logger.info(f"🔍 MODERATION: Starting statistics calculation for user {query.from_user.id}")
        total_pending = 0
        mode_stats = []
        
        for mode in GAME_MODES:
            mode_pending = 0
            category_stats = []
            
            for category in CATEGORIES:
                category_pending = 0
                gender_stats = {'male': 0, 'female': 0, 'common': 0}
                
                for gender in ['male', 'female', 'common']:
                    pending_tasks = self.db.get_pending_moderation_tasks(mode['key'], category['key'], gender)
                    pending_count = len(pending_tasks)
                    gender_stats[gender] = pending_count
                    category_pending += pending_count
                
                if category_pending > 0:
                    category_stats.append({
                        'name': category['name'],
                        'emoji': category['emoji'],
                        'total': category_pending,
                        'male': gender_stats['male'],
                        'female': gender_stats['female'],
                        'common': gender_stats['common']
                    })
                
                mode_pending += category_pending
            
            if mode_pending > 0:
                mode_stats.append({
                    'name': mode['name'],
                    'key': mode['key'],
                    'emoji': mode['emoji'],
                    'total': mode_pending,
                    'categories': category_stats
                })
            
            total_pending += mode_pending
        
        logger.info(f"🔍 MODERATION: Statistics calculated - total_pending: {total_pending}, modes with tasks: {len(mode_stats)}")
        
        # Формируем текст
        if total_pending == 0:
            text = """🔍 **Модерация заданий**

✅ Все задания модерированы!

Нет заданий, ожидающих модерации."""
        else:
            text = f"""🔍 **Модерация заданий**

📊 **Общая статистика:**
👥 Всего заданий на модерации: **{total_pending}**

📋 **По режимам игры:**"""
            
            for mode_stat in mode_stats:
                text += f"\n\n🎯 **{mode_stat['emoji']} {mode_stat['name']}** - {mode_stat['total']} заданий"
                
                for cat_stat in mode_stat['categories']:
                    gender_parts = []
                    if cat_stat['male'] > 0:
                        gender_parts.append(f"👨 {cat_stat['male']}")
                    if cat_stat['female'] > 0:
                        gender_parts.append(f"👩 {cat_stat['female']}")
                    if cat_stat['common'] > 0:
                        gender_parts.append(f"👥 {cat_stat['common']}")
                    
                    text += f"\n   • {cat_stat['emoji']} {cat_stat['name']}: {', '.join(gender_parts)}"
        
        text += "\n\nВыберите режим игры для модерации:"
        
        
        keyboard = []
        
        for mode in GAME_MODES:
            # Добавляем индикатор количества заданий на модерации
            mode_pending = 0
            for category in CATEGORIES:
                for gender in ['male', 'female', 'common']:
                    tasks = self.db.get_tasks_by_mode_and_level(mode['key'], category['key'], gender)
                    pending_count = len([task for task in tasks if task.get('is_custom', False) and task.get('moderation_status') == 'pending'])
                    mode_pending += pending_count
            
            if mode_pending > 0:
                button_text = f"{mode['name']} ({mode_pending})"
            else:
                button_text = f"{mode['name']} ✅"
            
            keyboard.append([InlineKeyboardButton(
                button_text, 
                callback_data=f"mod_mode_{mode['key']}"
            )])
        
        keyboard.append([InlineKeyboardButton("← Назад", callback_data="admin_panel")])
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
    
    async def handle_admin_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
        """Обработка действий админ-панели"""
        query = update.callback_query
        
        # Проверяем права в зависимости от действия
        if data == "admin_base_tasks":
            # Для базовых заданий нужен доступ к админ-панели
            if not self.has_admin_access(query.from_user):
                await self.safe_edit_message(query,"❌ Доступ запрещен.", parse_mode=None)
                return
        elif data == "admin_moderation":
            # Для модерации нужен доступ к модерации
            if not self.has_moderation_access(query.from_user):
                await self.safe_edit_message(query,"❌ Доступ запрещен.", parse_mode=None)
                return
        elif data in ["admin_administrators", "admin_stats", "admin_users", "admin_cleanup"]:
            # Для управления администраторами и других функций нужны права владельца
            if not self.can_manage_administrators(query.from_user):
                await self.safe_edit_message(query,"❌ Доступ запрещен. Только для владельца.", parse_mode=None)
                return
        elif data == "admin_reload_db":
            # Для перезагрузки БД нужен доступ к админ-панели
            if not self.has_admin_access(query.from_user):
                await self.safe_edit_message(query,"❌ Доступ запрещен.", parse_mode=None)
                return
        else:
            # Для остальных действий проверяем общий доступ к админ-панели
            if not self.has_admin_access(query.from_user):
                await self.safe_edit_message(query,"❌ Доступ запрещен.", parse_mode=None)
                return
        
        if data == "admin_base_tasks":
            await self.show_admin_base_tasks(query)
        elif data == "admin_moderation":
            await self.show_admin_moderation(query)
        elif data == "admin_administrators":
            await self.show_admin_administrators(query)
        elif data == "admin_stats":
            await self.show_admin_stats(query)
        elif data == "admin_users":
            await self.show_admin_users(query)
        elif data.startswith("admin_users_page_"):
            page = int(data.split("_")[-1])
            await self.show_admin_users(query, page)
        elif data == "admin_access_management":
            await self.show_admin_access_management(query)
        elif data == "admin_search_users":
            await self.show_admin_search_users(query)
        elif data == "admin_blocked_users":
            await self.show_admin_blocked_users(query)
        elif data.startswith("admin_block_user_"):
            user_id = int(data.split("_")[-1])
            await self.show_admin_block_user_menu(query, user_id)
        elif data.startswith("admin_unblock_user_"):
            user_id = int(data.split("_")[-1])
            await self.handle_admin_unblock_user(query, user_id)
        elif data.startswith("admin_confirm_block_"):
            parts = data.split("_")
            user_id = int(parts[-2])
            days = int(parts[-1]) if parts[-1] != "forever" else None
            await self.handle_admin_confirm_block_user(query, user_id, days)
        elif data == "admin_cleanup":
            await self.show_admin_cleanup(query)
        elif data == "admin_cleanup_all_tasks":
            await self.handle_admin_cleanup_all_tasks(query)
        elif data == "admin_detailed_stats":
            await self.show_admin_detailed_stats(query)
        elif data.startswith("admin_add_admin_"):
            await self.handle_admin_add_admin(query, data)
        elif data.startswith("admin_remove_admin_"):
            await self.handle_admin_remove_admin(query, data)
        elif data.startswith("admin_change_level_"):
            await self.handle_admin_change_level(query, data)
        elif data == "admin_reload_db":
            await self.handle_admin_reload_db(query)
        elif data.startswith("admin_mode_category_gender_"):
            await self.handle_admin_mode_category_gender_selection(query, data)
        elif data.startswith("admin_mode_category_"):
            await self.handle_admin_mode_category_selection(query, data)
        elif data.startswith("admin_mode_"):
            await self.handle_admin_mode_selection(query, data)
        elif data.startswith("btask_"):
            await self.handle_base_task_action(query, data)
        elif data.startswith("skip_task_"):
            await self.handle_skip_moderation_task(query, data)
        elif data.startswith("mod_cat_"):
            await self.handle_admin_moderation_mode_category_selection(query, data)
        elif data.startswith("mod_mode_"):
            logger.info(f"🔍 MODERATION: Calling handle_admin_moderation_mode_selection for data: '{data}'")
            await self.handle_admin_moderation_mode_selection(query, data)



    async def handle_skip_moderation_task(self, query, data: str):
        """Пропустить задание в модерации"""
        try:
            task_id = data.replace("skip_task_", "")
            logger.info(f"⏭️ MODERATION: Skipping task {task_id} by admin {query.from_user.id} ({query.from_user.username})")
            
            # Получаем информацию о задании для определения режима/категории/пола
            task = self.db.get_task_by_id(task_id)
            if not task:
                await self.safe_edit_message(query,
                    "❌ Задание не найдено",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← К модерации", callback_data="admin_moderation")]]),
                    parse_mode=None
                )
                return
            
            # Перемещаем задание в конец очереди модерации
            success = self.db.skip_task_for_moderation(
                task_id, 
                task.get('game_mode'), 
                task.get('category'), 
                task.get('gender')
            )
            
            if success:
                logger.info(f"✅ MODERATION: Task {task_id} moved to end of queue")
                await self.safe_edit_message(query,
                    "⏭️ **Задание пропущено!**\n\nЗадание перемещено в конец очереди модерации.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← К модерации", callback_data="admin_moderation")]]),
                    parse_mode=None
                )
            else:
                logger.error(f"❌ MODERATION: Failed to skip task {task_id}")
                await self.safe_edit_message(query,
                    "❌ Ошибка при пропуске задания",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← К модерации", callback_data="admin_moderation")]]),
                    parse_mode=None
                )
        except Exception as e:
            logger.error(f"Error skipping task: {e}")
            error_logger.error(f"Error skipping task: {e}", exc_info=True)
            await self.safe_edit_message(query,
                f"❌ Ошибка при пропуске задания: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← К модерации", callback_data="admin_moderation")]]),
                parse_mode=None
            )

    async def show_admin_base_tasks(self, query):
        """Показать управление базовыми заданиями"""
        text = """📝 Управление базовыми заданиями

Выберите режим игры для управления заданиями:"""
        
        keyboard = []
        for mode in GAME_MODES:
            keyboard.append([InlineKeyboardButton(
                f"{mode['name']} ({mode['key']})", 
                callback_data=f"admin_mode_{mode['key']}"
            )])
        
        keyboard.append([InlineKeyboardButton("← Назад", callback_data="admin_panel")])
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def handle_admin_mode_selection(self, query, data: str):
        """Обработка выбора режима игры в админ панели"""
        mode_key = data.replace("admin_mode_", "")
        
        # Находим информацию о режиме
        mode_info = None
        for mode in GAME_MODES:
            if mode['key'] == mode_key:
                mode_info = mode
                break
        
        if not mode_info:
            await self.safe_edit_message(query, "❌ Режим игры не найден.", parse_mode=None)
            return
        
        text = f"""📝 Управление базовыми заданиями

Режим: {mode_info['name']} ({mode_info['key']})
{mode_info['description']}

Выберите категорию для управления заданиями:"""
        
        keyboard = []
        for category in CATEGORIES:
            keyboard.append([InlineKeyboardButton(
                f"{category['emoji']} {category['name']}", 
                callback_data=f"admin_mode_category_{mode_key}_{category['key']}"
            )])
        
        keyboard.append([InlineKeyboardButton("← Назад к режимам", callback_data="admin_base_tasks")])
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def handle_admin_mode_category_selection(self, query, data: str):
        """Обработка выбора категории в режиме игры"""
        logger.info(f"handle_admin_mode_category_selection called with data: {data}")
        
        # Убираем префикс и разбиваем на части
        data_without_prefix = data.replace("admin_mode_category_", "")
        parts = data_without_prefix.split('_')
        mode_key = parts[0]  # admin_mode_category_MODE_CATEGORY
        category_key = parts[1]
        
        logger.info(f"Parsing callback_data: {data}")
        logger.info(f"Mode key: '{mode_key}', Category key: '{category_key}'")
        logger.info(f"Parts: {parts}")
        
        # Находим информацию о режиме и категории
        mode_info = None
        for mode in GAME_MODES:
            if mode['key'] == mode_key:
                mode_info = mode
                break
        
        category_info = self.get_category_info(category_key)
        
        logger.debug(f"Mode info found: {mode_info is not None}")
        logger.debug(f"Category info found: {category_info is not None}")
        if mode_info:
            logger.debug(f"Mode info: {mode_info['key']} - {mode_info['name']}")
        else:
            logger.debug(f"Mode info: None")
        if category_info:
            logger.debug(f"Category info: {category_info['key']} - {category_info['name']}")
        else:
            logger.debug(f"Category info: None")
        
        if not mode_info or not category_info:
            await self.safe_edit_message(query, f"❌ Режим или категория не найдены.\nMode: {mode_key}, Category: {category_key}", parse_mode=None)
            return
        
        text = f"""📝 Управление базовыми заданиями

Режим: {mode_info['name']} ({mode_info['key']})
Категория: {category_info['name']} ({category_info['key']})

Выберите тип заданий для управления:"""
        
        keyboard = [
            [InlineKeyboardButton("👥 Общие", callback_data=f"admin_mode_category_gender_{mode_key}_{category_key}_common")],
            [InlineKeyboardButton("👨 Мужские", callback_data=f"admin_mode_category_gender_{mode_key}_{category_key}_male")],
            [InlineKeyboardButton("👩 Женские", callback_data=f"admin_mode_category_gender_{mode_key}_{category_key}_female")],
            [InlineKeyboardButton("← Назад к категориям", callback_data=f"admin_mode_{mode_key}")]
        ]
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def handle_admin_mode_category_gender_selection(self, query, data: str):
        """Обработка выбора пола в режиме и категории"""
        # Убираем префикс и разбиваем на части
        data_without_prefix = data.replace("admin_mode_category_gender_", "")
        parts = data_without_prefix.split('_')
        mode_key = parts[0]  # admin_mode_category_gender_MODE_CATEGORY_GENDER
        category_key = parts[1]
        gender = parts[2]
        
        # Находим информацию о режиме и категории
        mode_info = None
        for mode in GAME_MODES:
            if mode['key'] == mode_key:
                mode_info = mode
                break
        
        category_info = self.get_category_info(category_key)
        
        if not mode_info or not category_info:
            await self.safe_edit_message(query, "❌ Режим или категория не найдены.", parse_mode=None)
            return
        
        gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие'}
        gender_name = gender_names.get(gender, gender)
        
        # Получаем задания для данного режима, категории и пола
        tasks = self.db.get_tasks_by_mode_and_level(mode_key, category_key, gender)
        base_tasks = [task for task in tasks if not task.get('is_custom', False)]
        
        text = f"""📝 Управление базовыми заданиями

Режим: {mode_info['name']} ({mode_key})
Категория: {category_info['name']} ({category_key})
Тип: {gender_name}

Найдено заданий: {len(base_tasks)}

Выберите действие:"""
        
        keyboard = []
        
        # Показываем задания (первые 5)
        for i, task in enumerate(base_tasks[:5]):
            short_text = task['text'][:30] + '...' if len(task['text']) > 30 else task['text']
            keyboard.append([InlineKeyboardButton(
                f"✏️ {short_text}", 
                callback_data=f"btask_edit_{task['id']}"
            )])
        
        # Кнопки управления
        keyboard.extend([
            [InlineKeyboardButton("➕ Добавить задание", callback_data=f"btask_add_{mode_key}_{category_key}_{gender}")],
            [InlineKeyboardButton("🗑️ Удалить задание", callback_data=f"btask_delete_{mode_key}_{category_key}_{gender}")],
            [InlineKeyboardButton("📋 Показать все", callback_data=f"btask_view_{mode_key}_{category_key}_{gender}")],
            [InlineKeyboardButton("← Назад к типам", callback_data=f"admin_mode_category_{mode_key}_{category_key}")]
        ])
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def handle_admin_moderation_mode_selection(self, query, data: str):
        """Обработка выбора режима игры в модерации"""
        mode_key = data.replace("mod_mode_", "")
        
        logger.info(f"🔍 MODERATION: Admin selected mode '{mode_key}' by user {query.from_user.id} ({query.from_user.username})")
        logger.info(f"🔍 MODERATION: Full data string: '{data}', extracted mode_key: '{mode_key}'")
        
        try:
            logger.info(f"🔍 MODERATION: GAME_MODES available: {len(GAME_MODES)} modes")
            for i, mode in enumerate(GAME_MODES):
                logger.info(f"🔍 MODERATION: Mode {i}: key='{mode['key']}', name='{mode['name']}'")
        except Exception as e:
            logger.error(f"🔍 MODERATION: Error accessing GAME_MODES: {e}")
            error_logger.error(f"Error accessing GAME_MODES: {e}", exc_info=True)
        
        # Находим информацию о режиме
        mode_info = None
        for mode in GAME_MODES:
            if mode['key'] == mode_key:
                mode_info = mode
                break
        
        logger.info(f"🔍 MODERATION: Found mode_info: {mode_info}")
        
        if not mode_info:
            logger.error(f"🔍 MODERATION: Mode '{mode_key}' not found in GAME_MODES")
            await self.safe_edit_message(query, "❌ Режим игры не найден.", parse_mode=None)
            return
        
        text = f"""🔍 Модерация заданий

Режим: {mode_info['name']} ({mode_info['key']})
{mode_info['description']}

Выберите категорию для модерации заданий:"""
        
        keyboard = []
        for category in CATEGORIES:
            keyboard.append([InlineKeyboardButton(
                f"{category['emoji']} {category['name']}", 
                callback_data=f"mod_cat_{mode_key}_{category['key']}"
            )])
        
        keyboard.append([InlineKeyboardButton("← Назад к режимам", callback_data="admin_moderation")])
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def handle_admin_moderation_mode_category_selection(self, query, data: str):
        """Обработка выбора категории в модерации по режиму"""
        # Убираем префикс и разбиваем на части
        data_without_prefix = data.replace("mod_cat_", "")
        parts = data_without_prefix.split('_')
        mode_key = parts[0]  # admin_moderation_mode_category_MODE_CATEGORY
        category_key = parts[1]
        
        logger.info(f"📂 MODERATION: Admin selected category '{category_key}' for mode '{mode_key}' by user {query.from_user.id} ({query.from_user.username})")
        
        # Находим информацию о режиме и категории
        mode_info = None
        for mode in GAME_MODES:
            if mode['key'] == mode_key:
                mode_info = mode
                break
        
        category_info = self.get_category_info(category_key)
        
        if not mode_info or not category_info:
            await self.safe_edit_message(query, "❌ Режим или категория не найдены.", parse_mode=None)
            return
        
        # Получаем задания, ожидающие модерации для данного режима и категории
        pending_tasks = []
        for gender in ['male', 'female', 'common']:
            try:
                tasks = self.db.get_pending_moderation_tasks(mode_key, category_key, gender)
                logger.info(f"🔍 MODERATION: Found {len(tasks)} pending tasks for {mode_key}/{category_key}/{gender}")
                pending_tasks.extend(tasks)
            except Exception as e:
                logger.error(f"❌ MODERATION: Error getting pending tasks for {mode_key}/{category_key}/{gender}: {e}")
                error_logger.error(f"Error getting pending tasks for {mode_key}/{category_key}/{gender}: {e}", exc_info=True)
        
        if not pending_tasks:
            text = f"""🔍 Модерация заданий

Режим: {mode_info['name']} ({mode_key})
Категория: {category_info['name']} ({category_key})

✅ Все задания уже модерированы!

Выберите другую категорию для модерации:"""
            
            # Показываем другие категории в этом режиме
            keyboard = []
            for category in CATEGORIES:
                if category['key'] != category_key:
                    keyboard.append([InlineKeyboardButton(
                        text=f"{category['emoji']} {category['name']}",
                        callback_data=f"mod_cat_{mode_key}_{category['key']}"
                    )])
            
            keyboard.append([InlineKeyboardButton(
                text="← Назад к режимам",
                callback_data="mod_mode_" + mode_key
            )])
            
            await self.safe_edit_message(query,
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
        else:
            # Показываем первое задание для модерации
            current_task = pending_tasks[0]
            gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие'}
            gender_name = gender_names.get(current_task.get('gender', 'common'), 'общие')
            
            text = f"""🔍 **Модерация заданий**

**Режим:** {mode_info['name']} ({mode_key})
**Категория:** {category_info['name']} ({category_key})
**Пол:** {gender_name}

**Задание на модерации** (1 из {len(pending_tasks)}):

📝 **Текст задания:**
{current_task.get('text', 'Текст задания не найден')}

Выберите действие:"""
            
            keyboard = [
                [
                    InlineKeyboardButton(
                        text="✅ Одобрить",
                        callback_data=f"moderate_approve_{current_task.get('id')}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"moderate_reject_{current_task.get('id')}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⏭️ Пропустить",
                        callback_data=f"skip_task_{current_task.get('id')}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="← Назад к категориям",
                        callback_data=f"mod_mode_{mode_key}"
                    )
                ]
            ]
            
            await self.safe_edit_message(query,
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )

    async def handle_admin_moderation_mode_category_gender_selection(self, query, data: str):
        """Обработка выбора пола в модерации по режиму и категории"""
        try:
            # Убираем префикс и разбиваем на части
            data_without_prefix = data.replace("mod_gen_", "")
            parts = data_without_prefix.split('_')
            
            if len(parts) < 3:
                await self.safe_edit_message(query, "❌ Некорректные параметры выбора.", parse_mode=None)
                return
            
            mode_key = parts[0]  # admin_moderation_mode_category_gender_MODE_CATEGORY_GENDER
            category_key = parts[1]
            gender = parts[2]
            
            logger.info(f"⚧ MODERATION: Admin selected gender '{gender}' for mode '{mode_key}' category '{category_key}' by user {query.from_user.id} ({query.from_user.username})")
            
            # Валидация параметров
            if gender not in ['male', 'female', 'common']:
                await self.safe_edit_message(query, "❌ Некорректный тип заданий.", parse_mode=None)
                return
            
            # Находим информацию о режиме и категории
            mode_info = None
            for mode in GAME_MODES:
                if mode['key'] == mode_key:
                    mode_info = mode
                    break
            
            category_info = self.get_category_info(category_key)
            
            if not mode_info or not category_info:
                await self.safe_edit_message(query, "❌ Режим или категория не найдены.", parse_mode=None)
                return
            
            gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие'}
            gender_name = gender_names.get(gender, gender)
            
            # Получаем задания, ожидающие модерации для данного режима, категории и пола
            pending_tasks = self.db.get_pending_moderation_tasks(mode_key, category_key, gender)
            logger.info(f"📋 MODERATION: Found {len(pending_tasks)} pending tasks for {mode_key}/{category_key}/{gender}")
            
            if not pending_tasks:
                text = f"""🔍 Модерация заданий

Режим: {mode_info['name']} ({mode_key})
Категория: {category_info['name']} ({category_key})
Тип: {gender_name}

✅ **Нет заданий на модерации**

Все задания в этой категории уже рассмотрены."""
                
                keyboard = [
                    [InlineKeyboardButton("← Назад к типам", callback_data=f"mod_cat_{mode_key}_{category_key}")]
                ]
            else:
                text = f"""🔍 Модерация заданий

Режим: {mode_info['name']} ({mode_key})
Категория: {category_info['name']} ({category_key})
Тип: {gender_name}

Заданий на модерации: {len(pending_tasks)}

Выберите задание для модерации:"""
                
                keyboard = []
                
                # Показываем задания (первые 5)
                for i, task in enumerate(pending_tasks[:5]):
                    short_text = task['text'][:30] + '...' if len(task['text']) > 30 else task['text']
                    keyboard.append([
                        InlineKeyboardButton(f"✅ Одобрить", callback_data=f"moderate_approve_{task['id']}"),
                        InlineKeyboardButton(f"❌ Отклонить", callback_data=f"moderate_reject_{task['id']}")
                    ])
                    keyboard.append([InlineKeyboardButton(
                        f"📝 {short_text}", 
                        callback_data=f"moderate_view_{task['id']}"
                    )])
                
                if len(pending_tasks) > 5:
                    keyboard.append([InlineKeyboardButton(
                        f"📋 Показать все ({len(pending_tasks)} заданий)", 
                        callback_data=f"moderate_view_all_{mode_key}_{category_key}_{gender}"
                    )])
                
                keyboard.append([InlineKeyboardButton("← Назад к типам", callback_data=f"mod_cat_{mode_key}_{category_key}")])
            
            await self.safe_edit_message(query,
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
            
        except Exception as e:
            logger.error(f"Ошибка при выборе пола в модерации: {e}")
            error_logger.error(f"Ошибка при выборе пола в модерации: {e}", exc_info=True)
            await self.safe_edit_message(query, f"❌ Ошибка при загрузке заданий: {str(e)}", parse_mode=None)

    async def show_admin_stats(self, query):
        """Показать статистику бота"""
        # Проверяем права - только владелец может видеть статистику
        if not self.is_owner(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может просматривать статистику.", parse_mode=None)
            return
        
        try:
            # Получаем статистику из базы данных
            user_stats = self.db.get_user_statistics()
            games_stats = self.db.get_games_statistics()
            tasks_stats = self.db.get_tasks_statistics()
            system_stats = self.db.get_system_statistics()
            
            text = f"""📊 **Статистика бота**

👥 **Пользователи:** {user_stats['total_users']}
🎮 **Всего игр:** {games_stats['total_games_played']}
✅ **Выполнено заданий:** {games_stats['total_tasks_completed']}
⏭️ **Пропущено заданий:** 0

📝 **Задания:**
• Всего заданий: {tasks_stats['total_tasks']}
• Базовых заданий: {tasks_stats['base_tasks']}
• Пользовательских: {tasks_stats['custom_tasks']}
  - Одобренных: {tasks_stats['moderation_stats'].get('approved', 0)}
  - На модерации: {tasks_stats['moderation_stats'].get('pending', 0)}

🕐 **Активность:**
• Активных игр: {len(self.user_games)}
• Активных пользователей (1ч): {system_stats['active_users_1h']}
• Активных пользователей (24ч): {system_stats['active_users_24h']}

📈 **Дополнительная информация:**
• Завершено игр: {games_stats['total_games_completed']}
• Процент завершения: {games_stats['completion_rate']}%
• Среднее игр на пользователя: {games_stats['avg_games_per_user']}
• Среднее заданий на пользователя: {games_stats['avg_tasks_per_user']}"""
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            error_logger.error(f"Ошибка получения статистики: {e}", exc_info=True)
            text = f"❌ **Ошибка получения статистики:** {str(e)}"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")],
            [InlineKeyboardButton("← Назад", callback_data="admin_panel")]
        ]
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def show_admin_users(self, query, page: int = 1):
        """Показать управление пользователями"""
        # Проверяем права - только владелец может управлять пользователями
        if not self.is_owner(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может управлять пользователями.", parse_mode=None)
            return
        
        try:
            if page == 1:
                # Показываем последние 5 пользователей
                recent_users = self.db.get_recent_users(5)
                text = """👥 **Управление пользователями**

**Последние 5 пользователей:**

"""
                show_pagination = False
            else:
                # Показываем пользователей с пагинацией
                pagination_data = self.db.get_users_paginated(page, 10)
                recent_users = pagination_data['users']
                text = f"""👥 **Управление пользователями**

**Страница {page} из {pagination_data['total_pages']}**
**Всего пользователей: {pagination_data['total_users']}**

"""
                show_pagination = True
            
            if not recent_users:
                text += "Пользователи не найдены."
            else:
                for i, user in enumerate(recent_users, 1):
                    # Формируем имя пользователя
                    if user['username']:
                        display_name = f"@{user['username']}"
                    elif user['first_name']:
                        display_name = user['first_name']
                        if user['last_name']:
                            display_name += f" {user['last_name']}"
                    else:
                        display_name = f"ID{user['id']}"
                    
                    # Определяем роль пользователя
                    role = "👤 Пользователь"
                    if user['is_owner']:
                        role = "👑 Владелец"
                    elif user['is_admin']:
                        role = "⚙️ Администратор"
                    elif user['is_moderator']:
                        role = "🔍 Модератор"
                    
                    # Статус блокировки
                    status = "✅ Активен"
                    if user.get('is_blocked', False):
                        if user.get('blocked_until'):
                            try:
                                from datetime import datetime
                                blocked_until = datetime.fromisoformat(user['blocked_until'].replace('Z', '+00:00'))
                                status = f"🚫 Заблокирован до {blocked_until.strftime('%d.%m.%Y %H:%M')}"
                            except:
                                status = "🚫 Заблокирован временно"
                        else:
                            status = "🚫 Заблокирован навсегда"
                    
                    # Форматируем дату регистрации
                    created_at = user.get('created_at', 'Неизвестно')
                    if created_at and created_at != 'Неизвестно':
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            created_at = dt.strftime('%d.%m.%Y %H:%M')
                        except:
                            pass
                    
                    # Форматируем дату активности
                    last_activity = user.get('last_activity', 'Неизвестно')
                    if last_activity and last_activity != 'Неизвестно':
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                            last_activity = dt.strftime('%d.%m.%Y %H:%M')
                        except:
                            pass
                    
                    text += f"**{i}.** {display_name}\n"
                    text += f"   ID: `{user['id']}`\n"
                    text += f"   {role}\n"
                    text += f"   {status}\n"
                    text += f"   📅 Регистрация: {created_at}\n"
                    text += f"   🕐 Активность: {last_activity}\n\n"
            
        except Exception as e:
            logger.error(f"Ошибка получения данных пользователей: {e}")
            error_logger.error(f"Ошибка получения данных пользователей: {e}", exc_info=True)
            text = f"❌ **Ошибка получения данных пользователей:**\n{str(e)}"
            show_pagination = False
        
        keyboard = []
        
        # Добавляем кнопки пагинации если нужно
        if show_pagination:
            pagination_buttons = []
            if page > 1:
                pagination_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"admin_users_page_{page-1}"))
            if page < pagination_data['total_pages']:
                pagination_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"admin_users_page_{page+1}"))
            
            if pagination_buttons:
                keyboard.append(pagination_buttons)
        
        # Основные кнопки
        keyboard.extend([
            [InlineKeyboardButton("👥 Все пользователи", callback_data="admin_users_page_1")],
            [InlineKeyboardButton("🔍 Поиск пользователей", callback_data="admin_search_users")],
            [InlineKeyboardButton("🔒 Управление доступом", callback_data="admin_access_management")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin_users")],
            [InlineKeyboardButton("📊 Подробная статистика", callback_data="admin_detailed_stats")],
            [InlineKeyboardButton("← Назад", callback_data="admin_panel")]
        ])
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def show_admin_detailed_stats(self, query):
        """Показать подробную статистику пользователей"""
        # Проверяем права - только владелец может видеть подробную статистику
        if not self.is_owner(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может просматривать подробную статистику.", parse_mode=None)
            return
        
        try:
            # Получаем всю статистику
            user_stats = self.db.get_user_statistics()
            games_stats = self.db.get_games_statistics()
            tasks_stats = self.db.get_tasks_statistics()
            system_stats = self.db.get_system_statistics()
            
            # Получаем топ пользователей
            top_users_tasks = self.db.get_top_users_by_tasks(5)
            top_users_games = self.db.get_top_users_by_games(5)
            
            text = """📊 **ПОЛНАЯ СТАТИСТИКА БОТА**

**👥 ПОЛЬЗОВАТЕЛИ:**
• Всего пользователей: {total_users}
• Владельцы: {owners}
• Администраторы: {admins}
• Модераторы: {moderators}
• Обычные пользователи: {regular_users}
• Заблокированные: {blocked_users}

**⏰ АКТИВНОСТЬ:**
• Активных (1 час): {active_1h}
• Активных (24 часа): {active_24h}
• Зарегистрировано за 24ч: {users_24h}
• Зарегистрировано за 7д: {users_7d}
• Зарегистрировано за 30д: {users_30d}

**🎮 ИГРЫ:**
• Всего сыграно: {total_games_played}
• Завершено игр: {total_games_completed}
• Выполнено заданий: {total_tasks_completed}
• Процент завершения: {completion_rate}%
• Среднее игр на пользователя: {avg_games_per_user}
• Среднее заданий на пользователя: {avg_tasks_per_user}

**📝 ЗАДАНИЯ:**
• Всего заданий: {total_tasks}
• Базовых заданий: {base_tasks}
• Пользовательских: {custom_tasks}
• На модерации: {pending_tasks}
• Одобренных: {approved_tasks}
• Отклоненных: {rejected_tasks}

**📊 ЗАДАНИЯ ПО КАТЕГОРИЯМ:**
• Знакомство: {acquaintance_tasks}
• Флирт: {flirt_tasks}
• Прелюдия: {prelude_tasks}
• Огонь: {fire_tasks}

**🎯 ЗАДАНИЯ ПО РЕЖИМАМ:**
• Базовый: {basic_tasks}
• Расширенный: {extended_tasks}

**💻 СИСТЕМА:**
• Таблиц в БД: {tables_count}

""".format(
                # Пользователи
                total_users=user_stats['total_users'],
                owners=user_stats['owners'],
                admins=user_stats['admins'],
                moderators=user_stats['moderators'],
                regular_users=user_stats['regular_users'],
                blocked_users=user_stats['blocked_users'],
                
                # Активность
                active_1h=system_stats['active_users_1h'],
                active_24h=system_stats['active_users_24h'],
                users_24h=user_stats['users_last_24h'],
                users_7d=user_stats['users_last_7d'],
                users_30d=user_stats['users_last_30d'],
                
                # Игры
                total_games_played=games_stats['total_games_played'],
                total_games_completed=games_stats['total_games_completed'],
                total_tasks_completed=games_stats['total_tasks_completed'],
                completion_rate=games_stats['completion_rate'],
                avg_games_per_user=games_stats['avg_games_per_user'],
                avg_tasks_per_user=games_stats['avg_tasks_per_user'],
                
                # Задания
                total_tasks=tasks_stats['total_tasks'],
                base_tasks=tasks_stats['base_tasks'],
                custom_tasks=tasks_stats['custom_tasks'],
                pending_tasks=tasks_stats['moderation_stats'].get('pending', 0),
                approved_tasks=tasks_stats['moderation_stats'].get('approved', 0),
                rejected_tasks=tasks_stats['moderation_stats'].get('rejected', 0),
                
                # Категории
                acquaintance_tasks=tasks_stats['category_stats'].get('acquaintance', 0),
                flirt_tasks=tasks_stats['category_stats'].get('flirt', 0),
                prelude_tasks=tasks_stats['category_stats'].get('prelude', 0),
                fire_tasks=tasks_stats['category_stats'].get('fire', 0),
                
                # Режимы
                basic_tasks=tasks_stats['mode_stats'].get('basic', 0),
                extended_tasks=tasks_stats['mode_stats'].get('extended', 0),
                
                # Система
                tables_count=system_stats['tables_count']
            )
            
            # Топ по заданиям
            if top_users_tasks:
                text += "**🏆 ТОП-5 ПО ЗАДАНИЯМ:**\n"
                for i, user in enumerate(top_users_tasks, 1):
                    display_name = user['first_name'] or f"ID{user['id']}"
                    if user['username']:
                        display_name = f"@{user['username']}"
                    text += f"{i}. {display_name}: {user['tasks_completed']}\n"
                text += "\n"
            
            # Топ по играм
            if top_users_games:
                text += "**🎮 ТОП-5 ПО ИГРАМ:**\n"
                for i, user in enumerate(top_users_games, 1):
                    display_name = user['first_name'] or f"ID{user['id']}"
                    if user['username']:
                        display_name = f"@{user['username']}"
                    text += f"{i}. {display_name}: {user['games_completed']}\n"
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            error_logger.error(f"Ошибка получения статистики: {e}", exc_info=True)
            text = f"❌ **Ошибка получения статистики:**\n{str(e)}"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin_detailed_stats")],
            [InlineKeyboardButton("👥 Список пользователей", callback_data="admin_users")],
            [InlineKeyboardButton("← Назад", callback_data="admin_panel")]
        ]
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def show_admin_access_management(self, query):
        """Показать управление доступом пользователей"""
        # Проверяем права - только владелец может управлять доступом
        if not self.is_owner(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может управлять доступом пользователей.", parse_mode=None)
            return
        
        try:
            # Получаем заблокированных пользователей
            blocked_users = []
            all_users = self.db.get_recent_users(50)  # Получаем больше пользователей для выбора
            for user in all_users:
                if user.get('is_blocked', False):
                    blocked_users.append(user)
            
            # Получаем последних 10 пользователей
            recent_users = self.db.get_recent_users(10)
            
            text = """🔒 **Управление доступом пользователей**

**Последние 10 пользователей:**
"""
            
            if recent_users:
                for i, user in enumerate(recent_users, 1):
                    display_name = user['first_name'] or f"ID{user['id']}"
                    if user['username']:
                        display_name = f"@{user['username']}"
                    
                    # Определяем роль пользователя
                    role = "👤 Пользователь"
                    if user['is_owner']:
                        role = "👑 Владелец"
                    elif user['is_admin']:
                        role = "⚙️ Администратор"
                    elif user['is_moderator']:
                        role = "🔍 Модератор"
                    
                    # Статус блокировки
                    status = "✅ Активен"
                    if user.get('is_blocked', False):
                        status = "🚫 Заблокирован"
                    
                    text += f"**{i}.** {display_name}\n"
                    text += f"   ID: `{user['id']}`\n"
                    text += f"   {role} | {status}\n"
                    text += f"   📅 Регистрация: {user.get('created_at', 'Неизвестно')}\n\n"
            
            text += "\n**Заблокированные пользователи:**\n"
            
            if blocked_users:
                for i, user in enumerate(blocked_users, 1):
                    display_name = user['first_name'] or f"ID{user['id']}"
                    if user['username']:
                        display_name = f"@{user['username']}"
                    
                    text += f"**{i}.** {display_name}\n"
                    text += f"   ID: `{user['id']}`\n"
                    text += f"   Причина: {user.get('block_reason', 'Не указана')}\n\n"
            else:
                text += "Заблокированных пользователей нет.\n\n"
            
            text += "Выберите действие:"
            
        except Exception as e:
            logger.error(f"Ошибка получения данных о доступе: {e}")
            error_logger.error(f"Ошибка получения данных о доступе: {e}", exc_info=True)
            text = f"❌ **Ошибка получения данных:**\n{str(e)}"
        
        keyboard = []
        
        # Добавляем кнопки блокировки для каждого пользователя (только не владельцев)
        if recent_users:
            for user in recent_users:
                if not user['is_owner']:  # Не показываем кнопку блокировки для владельца
                    display_name = user['first_name'] or f"ID{user['id']}"
                    if user.get('is_blocked', False):
                        keyboard.append([InlineKeyboardButton("🔓 Разблокировать " + display_name, callback_data=f"admin_unblock_user_{user['id']}")])
                    else:
                        keyboard.append([InlineKeyboardButton("🚫 Заблокировать " + display_name, callback_data=f"admin_block_user_{user['id']}")])
        
        # Основные кнопки
        keyboard.extend([
            [InlineKeyboardButton("🚫 Заблокированные пользователи", callback_data="admin_blocked_users")],
            [InlineKeyboardButton("🔍 Поиск для блокировки", callback_data="admin_search_users")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin_access_management")],
            [InlineKeyboardButton("← К управлению пользователями", callback_data="admin_users")]
        ])
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def show_admin_cleanup(self, query):
        """Показать меню очистки данных"""
        # Проверяем права - только владелец может очищать данные
        if not self.is_owner(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может очищать данные.", parse_mode=None)
            return
        
        text = """🗑️ Очистка данных

⚠️ Внимание! Эти действия необратимы.

Выберите действие:"""
        
        keyboard = [
            [InlineKeyboardButton("🗑️ Очистить ВСЕ задания", callback_data="admin_cleanup_all_tasks")],
            [InlineKeyboardButton("🗑️ Очистить старые игры (30+ дней)", callback_data="admin_cleanup_games")],
            [InlineKeyboardButton("🗑️ Удалить пользовательские задания", callback_data="admin_cleanup_custom_tasks")],
            [InlineKeyboardButton("📊 Сбросить статистику", callback_data="admin_cleanup_stats")],
            [InlineKeyboardButton("← Назад", callback_data="admin_panel")]
        ]
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )

    async def handle_admin_cleanup_all_tasks(self, query):
        """Обработка очистки всех заданий"""
        # Проверяем права - только владелец может очищать все задания
        if not self.is_owner(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может очищать все задания.", parse_mode=None)
            return
        
        try:
            # Очищаем все задания
            success = self.db.clear_all_tasks()
            
            if success:
                text = """✅ **Все задания успешно удалены!**

🗑️ База заданий полностью очищена.

📝 Теперь вы можете заполнить базу заново через админ-панель:
• Добавить базовые задания
• Импортировать задания из файла
• Создать задания вручную

⚠️ **Внимание:** Это действие необратимо!"""
                
                keyboard = [
                    [InlineKeyboardButton("← Назад к очистке", callback_data="admin_cleanup")],
                    [InlineKeyboardButton("← В админ-панель", callback_data="admin_panel")]
                ]
            else:
                text = """❌ **Ошибка при очистке заданий!**

Не удалось удалить задания из базы данных.

Попробуйте еще раз или обратитесь к разработчику."""
                
                keyboard = [
                    [InlineKeyboardButton("← Назад к очистке", callback_data="admin_cleanup")]
                ]
            
            await self.safe_edit_message(
                query,
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
            
        except Exception as e:
            logger.error(f"Ошибка при очистке всех заданий: {e}")
            error_logger.error(f"Ошибка при очистке всех заданий: {e}", exc_info=True)
            
            await self.safe_edit_message(
                query,
                f"❌ **Критическая ошибка при очистке заданий!**\n\n{str(e)}",
                parse_mode=None
            )

    async def handle_admin_edit_base_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
        """Начать редактирование базового задания"""
        # Извлекаем ID задания: admin_edit_base_TASK_ID
        # Нужно взять все после "admin_edit_base_"
        prefix = "admin_edit_base_"
        if not data.startswith(prefix):
            await self.safe_edit_message(update.callback_query, "❌ Неверный формат данных.", parse_mode=None)
            return
        
        task_id = data[len(prefix):]  # Все после префикса
        
        # Получаем задание
        task = self.db.get_task_by_id(task_id)
        if not task:
            await self.safe_edit_message(update.callback_query, "❌ Задание не найдено.", parse_mode=None)
            return
        
        # Сохраняем контекст
        context.user_data['admin_edit_task_id'] = task_id
        context.user_data['admin_edit_original'] = task['text']
        
        category_info = self.get_category_info(task['category'])
        if not category_info:
            await self.safe_edit_message(update.callback_query, "❌ Категория задания не найдена", parse_mode=None)
            return
        
        gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие'}
        
        await self.safe_edit_message(
            update.callback_query,
            f"✏️ **Редактирование базового задания**\n\n"
            f"Категория: {category_info['emoji']} {category_info['name']}\n"
            f"_{category_info['description']}_\n"
            f"Тип: {gender_names[task['gender']]}\n\n"
            f"**Текущий текст:**\n{task['text']}\n\n"
            f"**Введите новый текст задания:**",
            parse_mode=None
        )
        
        return ADMIN_EDIT_TASK

    async def handle_admin_task_edit_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ввода нового текста базового задания"""
        new_text = update.message.text.strip()
        task_id = context.user_data.get('admin_edit_task_id')
        original_text = context.user_data.get('admin_edit_original')
        
        if not new_text or len(new_text) < 10:
            await update.message.reply_text(
                "❌ Текст задания слишком короткий. Минимум 10 символов.\n"
                "Попробуйте еще раз:"
            )
            return ADMIN_EDIT_TASK
        
        if len(new_text) > 500:
            await update.message.reply_text(
                "❌ Текст задания слишком длинный. Максимум 500 символов.\n"
                "Попробуйте еще раз:"
            )
            return ADMIN_EDIT_TASK
        
        # Получаем информацию о задании для обновления
        task = self.db.get_task_by_id(task_id)
        if not task:
            await update.message.reply_text("❌ Задание не найдено.")
            return ConversationHandler.END
        
        # Обновляем задание в базе данных
        success = self.db.update_base_task(task_id, new_text, task['category'], task['gender'])
        
        if success:
            keyboard = [
                [InlineKeyboardButton("← К админ-панели", callback_data="admin_panel")]
            ]
            
            await update.message.reply_text(
                f"✅ **Базовое задание обновлено!**\n\n"
                f"**Было:**\n{original_text}\n\n"
                f"**Стало:**\n{new_text}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
        else:
            await update.message.reply_text(
                "❌ Ошибка при обновлении задания."
            )
        
        return ConversationHandler.END



    def run(self):
        """Запуск бота"""
        # Создаем приложение с настройками для стабильной работы
        from telegram.request import HTTPXRequest
        
        # Создаем Request с настройками таймаутов
        request = HTTPXRequest(
            connection_pool_size=8,
            connect_timeout=30,
            read_timeout=30,
            write_timeout=30
        )
        
        application = Application.builder().token(self.token).request(request).build()
        
        # Настраиваем ConversationHandler для ввода имен игроков
        game_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.handle_start_game_setup, pattern="^start_game_setup$")],
            states={
                WAITING_PLAYER_NAMES: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_player_names)],
            },
            fallbacks=[CommandHandler("start", self.start)],
            per_message=False,
            per_chat=True,
            per_user=True
        )
        
        # Настраиваем ConversationHandler для редактора заданий
        editor_conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.handle_editor_mode_selection, pattern="^editor_mode_[^_]+$"),
                CallbackQueryHandler(self.handle_editor_category, pattern="^editor_mode_category_"),
                CallbackQueryHandler(self.handle_gender_selection, pattern="^editor_mode_gender_"),
                CallbackQueryHandler(self.handle_view_tasks, pattern="^view_tasks_"),
                CallbackQueryHandler(self.handle_delete_task_menu, pattern="^delete_task_"),
                CallbackQueryHandler(self.handle_confirm_delete, pattern="^confirm_delete_"),
                CallbackQueryHandler(self.handle_submit_moderation, pattern="^submit_moderation_"),
                CallbackQueryHandler(self.handle_user_task_mode_selection, pattern="^user_task_mode_"),
                CallbackQueryHandler(self.handle_user_task_category_selection, pattern="^user_task_category_"),
                CallbackQueryHandler(self.handle_user_task_gender_selection, pattern="^user_task_gender_")
            ],
            states={
                USER_TASK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_user_task_text_input)],
            },
            fallbacks=[CommandHandler("start", self.start)],
            per_message=False,
            per_chat=True,
            per_user=True
        )
        
        # Настраиваем ConversationHandler для админ-панели
        admin_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.handle_admin_edit_base_task_wrapper, pattern="^admin_edit_base_")],
            states={
                ADMIN_EDIT_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_admin_task_edit_input)],
            },
            fallbacks=[CommandHandler("start", self.start)],
            per_message=False,
            per_chat=True,
            per_user=True
        )
        
        # Настраиваем ConversationHandler для добавления базовых заданий
        admin_add_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.handle_admin_add_base_task_wrapper, pattern="^admin_add_base_")],
            states={
                ADMIN_ADD_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_admin_add_task_input)],
            },
            fallbacks=[CommandHandler("start", self.start)],
            per_chat=True,
            per_user=True,
            per_message=False
        )
        
        # Добавляем обработчики
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("help", self.show_help))
        application.add_handler(game_conv_handler)
        application.add_handler(editor_conv_handler)
        application.add_handler(admin_conv_handler)
        application.add_handler(admin_add_conv_handler)
        application.add_handler(CallbackQueryHandler(self.button_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_handler))
        
        # Запускаем бота с обработкой ошибок
        logger.info("Бот запущен...")
        try:
            application.run_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
                close_loop=False
            )
        except Exception as e:
            error_logger.error(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
            logger.error(f"Бот остановлен из-за ошибки: {e}")
            raise
    
    
    async def handle_admin_add_base_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
        """Начать процесс добавления базового задания"""
        logger.info(f"handle_admin_add_base_task вызван с data: {data}")
        
        # Убираем префикс и разбиваем на части
        data_without_prefix = data.replace("admin_add_base_", "")
        parts = data_without_prefix.split('_')
        
        if len(parts) != 3:
            await self.safe_edit_message(update.callback_query, "❌ Неверный формат данных", parse_mode=None)
            return ConversationHandler.END
        
        # Формат: admin_add_base_MODE_CATEGORY_GENDER
        mode_key = parts[0]
        category = parts[1]
        gender = parts[2]
        
        logger.info(f"Режим: {mode_key}, Категория: {category}, Пол: {gender}")
        
        # Сохраняем контекст в user_data
        context.user_data['admin_add_mode'] = mode_key
        context.user_data['admin_add_category'] = category
        context.user_data['admin_add_gender'] = gender
        
        gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие'}
        category_info = self.get_category_info(category)
        if not category_info:
            await self.safe_edit_message(update.callback_query, "❌ Категория не найдена", parse_mode=None)
            return ConversationHandler.END
        
        query = update.callback_query
        await self.safe_edit_message(query,
            f"➕ **Добавление базового задания**\n\n"
            f"Категория: {category_info['emoji']} {category_info['name']}\n"
            f"_{category_info['description']}_\n"
            f"Тип: {gender_names[gender]}\n\n"
            f"Введите текст нового базового задания:",
            parse_mode=None
        )
        
        return ADMIN_ADD_TASK
    
    async def handle_admin_add_task_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ввода текста нового базового задания"""
        new_text = update.message.text.strip()
        mode_key = context.user_data.get('admin_add_mode', '2couples')
        category = context.user_data.get('admin_add_category')
        gender = context.user_data.get('admin_add_gender')
        
        if not new_text or len(new_text) < 10:
            await update.message.reply_text(
                "❌ Текст задания слишком короткий. Минимум 10 символов.\n"
                "Попробуйте еще раз:"
            )
            return ADMIN_ADD_TASK
        
        if len(new_text) > 500:
            await update.message.reply_text(
                "❌ Текст задания слишком длинный. Максимум 500 символов.\n"
                "Попробуйте еще раз:"
            )
            return ADMIN_ADD_TASK
        
        # Добавляем задание в базу данных
        task_id = self.db.add_base_task(category, gender, new_text, mode_key)
        
        if task_id:
            gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие'}
            category_info = self.get_category_info(category)
            if not category_info:
                await update.message.reply_text("❌ Категория не найдена")
                return ConversationHandler.END
            
            keyboard = [
                [InlineKeyboardButton("← К управлению заданиями", callback_data=f"admin_mode_category_gender_{mode_key}_{category}_{gender}")],
                [InlineKeyboardButton("➕ Добавить ещё 1 задание", callback_data=f"admin_add_base_{mode_key}_{category}_{gender}")]
            ]
            
            await update.message.reply_text(
                f"✅ **Базовое задание добавлено!**\n\n"
                f"Категория: {category_info['emoji']} {category_info['name']}\n"
                f"_{category_info['description']}_\n"
                f"Тип: {gender_names[gender]}\n"
                f"Текст: {new_text}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
        else:
            await update.message.reply_text(
                "❌ Ошибка при добавлении задания."
            )
        
        return ConversationHandler.END
    
    

    async def handle_admin_edit_base_task_wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Wrapper для ConversationHandler - редактирование базового задания"""
        data = update.callback_query.data
        return await self.handle_admin_edit_base_task(update, context, data)
    
    async def handle_admin_add_base_task_wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Wrapper для ConversationHandler - добавление базового задания"""
        logger.info(f"handle_admin_add_base_task_wrapper вызван с data: {update.callback_query.data}")
        
        if not self.is_admin(update.callback_query.from_user):
            logger.warning(f"Попытка доступа к админ-функции от не-администратора: {update.callback_query.from_user.username}")
            await self.safe_edit_message(update.callback_query, "❌ Доступ запрещен.", parse_mode=None)
            return ConversationHandler.END
        
        data = update.callback_query.data
        return await self.handle_admin_add_base_task(update, context, data)
    
    async def handle_submit_moderation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправить задание на модерацию"""
        query = update.callback_query
        data = query.data
        
        # Извлекаем task_id из callback_data
        task_id = data.replace("submit_moderation_", "")
        
        try:
            # Валидация входных данных
            if not task_id or not (task_id.startswith('custom_') or task_id.startswith('user_')):
                await self.safe_edit_message(query, "❌ Некорректный ID задания.", parse_mode=None)
                return ConversationHandler.END
            
            # Проверяем существование задания и права пользователя
            task = self.db.get_task_by_id(task_id)
            if not task:
                await self.safe_edit_message(query, "❌ Задание не найдено.", parse_mode=None)
                return ConversationHandler.END
            
            # Проверяем, что это пользовательское задание
            if not task.get('is_custom', False):
                await self.safe_edit_message(query, "❌ Можно отправить на модерацию только пользовательские задания.", parse_mode=None)
                return ConversationHandler.END
            
            # Проверяем, что задание принадлежит пользователю
            if task.get('created_by') != query.from_user.id:
                await self.safe_edit_message(query, "❌ Вы можете отправить на модерацию только свои задания.", parse_mode=None)
                return ConversationHandler.END
            
            # Проверяем текущий статус модерации
            current_status = task.get('moderation_status', 'draft')
            if current_status == 'pending':
                await self.safe_edit_message(query, "❌ Задание уже отправлено на модерацию.", parse_mode=None)
                return ConversationHandler.END
            elif current_status == 'approved':
                await self.safe_edit_message(query, "❌ Задание уже одобрено и опубликовано.", parse_mode=None)
                return ConversationHandler.END
            elif current_status in ['draft', 'rejected']:
                # Позволяем отправить черновик или повторно отправить отклоненное задание
                pass
            
            # Отправляем задание на модерацию
            success = self.db.submit_task_for_moderation(task_id)
            
            if success:
                keyboard = [
                    [InlineKeyboardButton("← К редактору заданий", callback_data="task_editor")]
                ]
                await self.safe_edit_message(
                    query,
                    "✅ **Задание отправлено на модерацию!**\n\n"
                    "📝 Администратор рассмотрит ваше задание и примет решение о его публикации.\n"
                    "🔔 Вы получите уведомление о результате модерации.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=None
                )
                return ConversationHandler.END
            else:
                keyboard = [
                    [InlineKeyboardButton("← К редактору заданий", callback_data="task_editor")]
                ]
                await self.safe_edit_message(
                    query,
                    "❌ Ошибка при отправке задания на модерацию. Возможно, задание уже было рассмотрено или удалено.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=None
                )
                return ConversationHandler.END
                
        except Exception as e:
            logger.error(f"Ошибка при отправке на модерацию: {e}")
            error_logger.error(f"Ошибка при отправке на модерацию: {e}", exc_info=True)
            keyboard = [
                [InlineKeyboardButton("← К редактору заданий", callback_data="task_editor")]
            ]
            await self.safe_edit_message(
                query,
                f"❌ Ошибка при отправке на модерацию: {str(e)}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
        
        return ConversationHandler.END
    
    async def handle_moderate_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE, task_id: str, action: str):
        """Модерировать задание (одобрить/отклонить)"""
        query = update.callback_query
        
        # Логируем для отладки
        logger.info(f"🔍 MODERATION: handle_moderate_task called with task_id='{task_id}', action='{action}'")
        
        try:
            # Валидация входных данных
            if not task_id:
                logger.warning(f"🔍 MODERATION: Empty task_id received")
                await self.safe_edit_message(query, "❌ Некорректный ID задания.", parse_mode=None)
                return
            
            if not (task_id.startswith('custom_') or task_id.startswith('user_')):
                logger.warning(f"🔍 MODERATION: Invalid task_id format: '{task_id}' (doesn't start with custom_ or user_)")
                await self.safe_edit_message(query, "❌ Некорректный ID задания.", parse_mode=None)
                return
            
            if action not in ["approve", "reject"]:
                await self.safe_edit_message(query, "❌ Некорректное действие модерации.", parse_mode=None)
                return
            
            # Проверяем права администратора
            if not self.is_admin(query.from_user):
                await self.safe_edit_message(query, "❌ У вас нет прав для модерации заданий.", parse_mode=None)
                return
            
            # Проверяем существование задания и его статус
            task = self.db.get_task_by_id(task_id)
            if not task:
                await self.safe_edit_message(query, "❌ Задание не найдено.", parse_mode=None)
                return
            
            if not task.get('is_custom', False):
                await self.safe_edit_message(query, "❌ Можно модерировать только пользовательские задания.", parse_mode=None)
                return
            
            if task.get('moderation_status') != 'pending':
                status_text = task.get('moderation_status', 'неизвестно')
                await self.safe_edit_message(query, f"❌ Задание уже рассмотрено (статус: {status_text}).", parse_mode=None)
                return
            
            # Модерируем задание
            success = self.db.moderate_task(task_id, action, query.from_user.id)
            
            if success:
                if action == "approve":
                    action_text = "одобрено и добавлено в расширенный режим"
                    description = "Теперь задание доступно в расширенном режиме игры."
                else:
                    action_text = "отклонено"
                    description = "Задание осталось доступным только автору."
                
                keyboard = [
                    [InlineKeyboardButton("← Назад к модерации", callback_data="admin_moderation")]
                ]
                await self.safe_edit_message(
                    query,
                    f"✅ **Задание {action_text}!**\n\n"
                    f"📝 Задание {action_text} модератором {query.from_user.first_name}\n\n"
                    f"ℹ️ {description}",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=None
                )
            else:
                keyboard = [
                    [InlineKeyboardButton("← Назад к модерации", callback_data="admin_moderation")]
                ]
                await self.safe_edit_message(
                    query,
                    f"❌ Ошибка при модерации задания. Возможно, задание уже было рассмотрено или удалено.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=None
                )
                
        except Exception as e:
            logger.error(f"Ошибка при модерации задания: {e}")
            error_logger.error(f"Ошибка при модерации задания: {e}", exc_info=True)
            keyboard = [
                [InlineKeyboardButton("← Назад к модерации", callback_data="admin_moderation")]
            ]
            await self.safe_edit_message(
                query,
                f"❌ Ошибка при модерации задания: {str(e)}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )

    async def handle_view_task_for_moderation(self, update: Update, context: ContextTypes.DEFAULT_TYPE, task_id: str):
        """Просмотр задания для модерации"""
        query = update.callback_query
        
        try:
            # Валидация входных данных
            if not task_id or not (task_id.startswith('custom_') or task_id.startswith('user_')):
                await self.safe_edit_message(query, "❌ Некорректный ID задания.", parse_mode=None)
                return
            
            # Проверяем права администратора
            if not self.is_admin(query.from_user):
                await self.safe_edit_message(query, "❌ У вас нет прав для модерации заданий.", parse_mode=None)
                return
            
            # Получаем информацию о задании
            task = self.db.get_task_by_id(task_id)
            if not task:
                await self.safe_edit_message(query, "❌ Задание не найдено.", parse_mode=None)
                return
            
            # Проверяем, что это пользовательское задание
            if not task.get('is_custom', False):
                await self.safe_edit_message(query, "❌ Можно модерировать только пользовательские задания.", parse_mode=None)
                return
            
            # Получаем информацию о пользователе, создавшем задание
            user_info = self.db.get_user_by_id(task.get('created_by', 0))
            author_name = user_info.get('username', 'Неизвестный') if user_info else 'Неизвестный'
            
            # Получаем информацию о категории и режиме
            category_info = self.get_category_info(task.get('category', ''))
            category_name = category_info.get('name', 'Неизвестно') if category_info else 'Неизвестно'
            
            mode_info = None
            for mode in GAME_MODES:
                if mode['key'] == task.get('game_mode', ''):
                    mode_info = mode
                    break
            mode_name = mode_info.get('name', 'Неизвестно') if mode_info else 'Неизвестно'
            
            gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие'}
            gender_name = gender_names.get(task.get('gender', ''), 'Неизвестно')
            
            status_names = {
                'pending': 'ожидает модерации',
                'approved': 'одобрено',
                'rejected': 'отклонено'
            }
            status_name = status_names.get(task.get('moderation_status', ''), 'неизвестно')
            
            text = f"""📝 **Просмотр задания для модерации**

**Текст задания:**
{task['text']}

**Информация:**
• Категория: {category_name}
• Пол: {gender_name}
• Режим игры: {mode_name}
• Автор: @{author_name}
• Статус: {status_name}
• ID задания: {task_id}

Выберите действие:"""
            
            keyboard = []
            
            # Показываем кнопки модерации только если задание ожидает модерации
            if task.get('moderation_status') == 'pending':
                keyboard.append([
                    InlineKeyboardButton("✅ Одобрить", callback_data=f"moderate_approve_{task_id}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"moderate_reject_{task_id}")
                ])
            else:
                keyboard.append([InlineKeyboardButton("ℹ️ Задание уже рассмотрено", callback_data="noop")])
            
            keyboard.append([InlineKeyboardButton("← Назад к модерации", callback_data="admin_moderation")])
            
            await self.safe_edit_message(
                query,
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
            
        except Exception as e:
            logger.error(f"Ошибка при просмотре задания для модерации: {e}")
            error_logger.error(f"Ошибка при просмотре задания для модерации: {e}", exc_info=True)
            await self.safe_edit_message(query, f"❌ Ошибка при просмотре задания: {str(e)}", parse_mode=None)

    async def handle_view_all_tasks_for_moderation(self, update: Update, context: ContextTypes.DEFAULT_TYPE, mode_key: str, category_key: str, gender: str):
        """Просмотр всех заданий для модерации"""
        query = update.callback_query
        
        try:
            # Валидация входных данных
            if not mode_key or not category_key or not gender:
                await self.safe_edit_message(query, "❌ Некорректные параметры для просмотра заданий.", parse_mode=None)
                return
            
            if gender not in ['male', 'female', 'common']:
                await self.safe_edit_message(query, "❌ Некорректный тип заданий.", parse_mode=None)
                return
            
            # Проверяем права администратора
            if not self.is_admin(query.from_user):
                await self.safe_edit_message(query, "❌ У вас нет прав для модерации заданий.", parse_mode=None)
                return
            
            # Получаем информацию о режиме и категории
            mode_info = None
            for mode in GAME_MODES:
                if mode['key'] == mode_key:
                    mode_info = mode
                    break
            
            category_info = self.get_category_info(category_key)
            
            if not mode_info or not category_info:
                await self.safe_edit_message(query, "❌ Режим или категория не найдены.", parse_mode=None)
                return
            
            # Получаем все задания, ожидающие модерации
            tasks = self.db.get_tasks_by_mode_and_level(mode_key, category_key, gender)
            logger.info(f"🔍 MODERATION: Retrieved {len(tasks)} total tasks for moderation {mode_key}/{category_key}/{gender}")
            pending_tasks = [task for task in tasks if task.get('is_custom', False) and task.get('moderation_status') == 'pending']
            logger.info(f"📋 MODERATION: Found {len(pending_tasks)} pending tasks for moderation")
            
            gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие'}
            gender_name = gender_names.get(gender, gender)
            
            if not pending_tasks:
                text = f"""📋 **Все задания на модерации**

Режим: {mode_info['name']} ({mode_key})
Категория: {category_info['name']} ({category_key})
Тип: {gender_name}

✅ **Нет заданий на модерации**

Все задания в этой категории уже рассмотрены."""
                
                keyboard = [
                    [InlineKeyboardButton("← Назад к типам", callback_data=f"mod_cat_{mode_key}_{category_key}")]
                ]
            else:
                text = f"""📋 **Все задания на модерации**

Режим: {mode_info['name']} ({mode_key})
Категория: {category_info['name']} ({category_key})
Тип: {gender_name}

Заданий на модерации: {len(pending_tasks)}

**Список заданий:**"""
                
                keyboard = []
                
                # Показываем все задания (ограничиваем количество для предотвращения переполнения)
                max_tasks = 20  # Максимум 20 заданий для предотвращения переполнения клавиатуры
                tasks_to_show = pending_tasks[:max_tasks]
                
                for i, task in enumerate(tasks_to_show):
                    short_text = task['text'][:35] + '...' if len(task['text']) > 35 else task['text']
                    keyboard.append([
                        InlineKeyboardButton(f"✅ Одобрить", callback_data=f"moderate_approve_{task['id']}"),
                        InlineKeyboardButton(f"❌ Отклонить", callback_data=f"moderate_reject_{task['id']}")
                    ])
                    keyboard.append([InlineKeyboardButton(
                        f"📝 {short_text}", 
                        callback_data=f"moderate_view_{task['id']}"
                    )])
                
                if len(pending_tasks) > max_tasks:
                    text += f"\n\n⚠️ Показано {max_tasks} из {len(pending_tasks)} заданий"
                
                keyboard.append([InlineKeyboardButton("← Назад к типам", callback_data=f"mod_cat_{mode_key}_{category_key}")])
            
            await self.safe_edit_message(
                query,
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
            
        except Exception as e:
            logger.error(f"Ошибка при просмотре всех заданий для модерации: {e}")
            error_logger.error(f"Ошибка при просмотре всех заданий для модерации: {e}", exc_info=True)
            await self.safe_edit_message(query, f"❌ Ошибка при просмотре заданий: {str(e)}", parse_mode=None)

    async def handle_add_admin_command(self, update: Update, username: str, level: str):
        """Обработка команды добавления администратора"""
        try:
            # Ищем пользователя по username в базе данных
            user = self.db.get_user_by_username(username)
            
            if not user:
                await update.message.reply_text(
                    f"❌ **Пользователь не найден**\n\n"
                    f"Пользователь @{username} не найден в базе данных.\n"
                    f"Попросите пользователя написать боту любое сообщение (например, /start), "
                    f"а затем повторите команду добавления.",
                    parse_mode=None
                )
                return
            
            # Проверяем, не является ли пользователь уже администратором
            if self.db.is_admin(user['chat_id']):
                current_level = self.db.get_admin_level(user['chat_id'])
                await update.message.reply_text(
                    f"⚠️ **Пользователь уже администратор**\n\n"
                    f"@{username} уже является администратором с уровнем: {current_level}",
                    parse_mode=None
                )
                return
            
            # Добавляем администратора
            success = self.db.add_administrator(
                user_id=user['chat_id'],
                username=user['username'],
                first_name=user['first_name'],
                level=level,
                added_by=update.effective_user.id
            )
            
            if success:
                level_names = {
                    'admin': 'Администратор',
                    'moderator': 'Модератор'
                }
                
                await update.message.reply_text(
                    f"✅ **Администратор добавлен!**\n\n"
                    f"👤 Пользователь: @{username}\n"
                    f"📝 Имя: {user['first_name']}\n"
                    f"🔑 Уровень: {level_names.get(level, level)}\n"
                    f"➕ Добавлен: {update.effective_user.first_name}",
                    parse_mode=None
                )
            else:
                await update.message.reply_text(
                    f"❌ **Ошибка при добавлении администратора**\n\n"
                    f"Не удалось добавить @{username} в качестве администратора.",
                    parse_mode=None
                )
                
        except Exception as e:
            logger.error(f"Ошибка при обработке команды добавления администратора: {e}")
            logger.error(f"Ошибка при обработке команды добавления администратора в main.py: {e}", exc_info=True)
            await update.message.reply_text("❌ Ошибка при обработке команды.")

    # Функции для работы с администраторами
    async def show_admin_administrators(self, query):
        """Показать список администраторов"""
        # Проверяем права - только владелец может управлять администраторами
        if not self.can_manage_administrators(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может управлять администраторами.", parse_mode=None)
            return
        
        administrators = self.db.get_all_administrators()
        
        if not administrators:
            text = """👑 Управление администраторами

Нет администраторов в системе."""
            keyboard = [
                [InlineKeyboardButton("➕ Добавить администратора", callback_data="admin_add_admin_new")],
                [InlineKeyboardButton("← Назад", callback_data="admin_panel")]
            ]
        else:
            text = "👑 **Управление администраторами**\n\n"
            
            level_emojis = {
                'owner': '👑',
                'admin': '🛡️',
                'moderator': '🔧'
            }
            
            level_names = {
                'owner': 'Владелец',
                'admin': 'Администратор', 
                'moderator': 'Модератор'
            }
            
            for admin in administrators:
                level_emoji = level_emojis.get(admin['level'], '❓')
                level_name = level_names.get(admin['level'], admin['level'])
                username = admin['username'] or admin['first_name'] or f"ID{admin['user_id']}"
                
                text += f"{level_emoji} **{username}** - {level_name}\n"
                if admin['added_by_username']:
                    added_by = admin['added_by_username'] or admin['added_by_first_name'] or f"ID{admin['added_by']}"
                    text += f"   Добавлен: {added_by}\n"
                text += "\n"
            
            keyboard = []
            
            # Добавляем кнопки удаления для каждого администратора (кроме владельца)
            for admin in administrators:
                if admin['level'] != 'owner':  # Не показываем кнопку удаления для владельца
                    username = admin['username'] or admin['first_name'] or f"ID{admin['user_id']}"
                    keyboard.append([InlineKeyboardButton(f"🗑️ Удалить {username}", callback_data=f"admin_remove_admin_{admin['user_id']}")])
            
            # Добавляем основные кнопки
            keyboard.extend([
                [InlineKeyboardButton("➕ Добавить администратора", callback_data="admin_add_admin_new")],
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin_administrators")],
                [InlineKeyboardButton("← Назад", callback_data="admin_panel")]
            ])
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
    
    async def handle_admin_add_admin(self, query, data: str):
        """Обработка добавления администратора"""
        if not self.can_manage_administrators(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может добавлять администраторов.", parse_mode=None)
            return
        
        if data == "admin_add_admin_new":
            # Показываем инструкции по добавлению
            text = """➕ **Добавление администратора**

Для добавления администратора отправьте сообщение в формате:
`@username уровень`

**Доступные уровни:**
• `admin` - Администратор (управление контентом)
• `moderator` - Модератор (модерация заданий)

**Пример:**
`@username admin`"""
            
            keyboard = [
                [InlineKeyboardButton("← Назад к администраторам", callback_data="admin_administrators")]
            ]
            
            await self.safe_edit_message(query,
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
    
    async def handle_admin_remove_admin(self, query, data: str):
        """Обработка удаления администратора"""
        if not self.is_owner(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может удалять администраторов.", parse_mode=None)
            return
        
        # Извлекаем ID администратора
        user_id = int(data.split('_')[-1])
        
        # Нельзя удалить самого себя
        if user_id == query.from_user.id:
            await self.safe_edit_message(query, "❌ Нельзя удалить самого себя.", parse_mode=None)
            return
        
        success = self.db.remove_administrator(user_id)
        
        if success:
            await self.safe_edit_message(query,
                "✅ **Администратор удален!**",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("← Назад к администраторам", callback_data="admin_administrators")
                ]]),
                parse_mode=None
            )
        else:
            await self.safe_edit_message(query,
                "❌ Ошибка при удалении администратора.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("← Назад к администраторам", callback_data="admin_administrators")
                ]]),
                parse_mode=None
            )
    
    async def handle_admin_change_level(self, query, data: str):
        """Обработка изменения уровня администратора"""
        if not self.is_owner(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может изменять уровни администраторов.", parse_mode=None)
            return
        
        # Извлекаем данные: admin_change_level_USER_ID_LEVEL
        parts = data.split('_')
        user_id = int(parts[3])
        level = parts[4]
        
        # Нельзя изменить уровень самого себя
        if user_id == query.from_user.id:
            await self.safe_edit_message(query, "❌ Нельзя изменить свой собственный уровень.", parse_mode=None)
            return
        
        success = self.db.update_admin_level(user_id, level)
        
        if success:
            level_names = {
                'owner': 'Владелец',
                'admin': 'Администратор',
                'moderator': 'Модератор'
            }
            level_name = level_names.get(level, level)
            
            await self.safe_edit_message(query,
                f"✅ **Уровень изменен на {level_name}!**",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("← Назад к администраторам", callback_data="admin_administrators")
                ]]),
                parse_mode=None
            )
        else:
            await self.safe_edit_message(query,
                "❌ Ошибка при изменении уровня администратора.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("← Назад к администраторам", callback_data="admin_administrators")
                ]]),
                parse_mode=None
            )

    # ===== НОВЫЕ МЕТОДЫ ДЛЯ УПРАВЛЕНИЯ БАЗОВЫМИ ЗАДАНИЯМИ =====
    
    async def handle_base_task_action(self, query, data: str):
        """Обработка действий с базовыми заданиями"""
        logger.info(f"handle_base_task_action called with data: {data}")
        if not self.is_admin(query.from_user):
            await self.safe_edit_message(query, "❌ Доступ запрещен.", parse_mode=None)
            return
        
        if data.startswith("btask_edit_"):
            await self.handle_btask_edit(query, data)
        elif data.startswith("btask_add_"):
            await self.handle_btask_add(query, data)
        elif data.startswith("btask_delete_"):
            await self.handle_btask_delete(query, data)
        elif data.startswith("btask_view_"):
            await self.handle_btask_view(query, data)
        elif data.startswith("btask_confirm_delete_"):
            await self.handle_btask_confirm_delete(query, data)
        elif data.startswith("btask_save_"):
            await self.handle_btask_save(query, data)
        elif data.startswith("btask_reload_db_"):
            await self.handle_btask_reload_db(query, data)
        else:
            await self.safe_edit_message(query, "❌ Неизвестное действие.", parse_mode=None)
    
    async def handle_btask_edit(self, query, data: str):
        """Редактирование базового задания"""
        task_id = data.replace("btask_edit_", "")
        
        # Получаем задание
        task = self.db.get_task_by_id(task_id)
        if not task:
            await self.safe_edit_message(query, "❌ Задание не найдено.", parse_mode=None)
            return
        
        text = f"""✏️ **Редактирование задания**

**Текущий текст:**
{task['text']}

**Информация:**
• Режим: {task.get('game_mode', '2couples')}
• Категория: {task['category']}
• Пол: {task['gender']}

**Введите новый текст задания:**"""
        
        keyboard = [
            [InlineKeyboardButton("❌ Отмена", callback_data=f"btask_view_{task.get('game_mode', '2couples')}_{task['category']}_{task['gender']}")]
        ]
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        await query.answer("Отправьте новый текст задания сообщением")
        
        # Сохраняем состояние ожидания ввода текста для редактирования
        chat_id = query.message.chat_id
        self.user_games[chat_id] = {
            'setup_step': 'edit_base_task',
            'task_data': {
                'task_id': task_id,
                'mode_key': task.get('game_mode', '2couples'),
                'category_key': task['category'],
                'gender': task['gender']
            }
        }
    
    async def handle_btask_add(self, query, data: str):
        """Добавление нового базового задания"""
        # Парсим данные: btask_add_MODE_CATEGORY_GENDER
        parts = data.replace("btask_add_", "").split("_")
        if len(parts) != 3:
            await self.safe_edit_message(query, "❌ Неверный формат данных.", parse_mode=None)
            return
        
        mode_key, category_key, gender = parts
        
        # Сохраняем состояние ожидания ввода текста задания
        chat_id = query.message.chat_id
        self.user_games[chat_id] = {
            'setup_step': 'add_base_task',
            'task_data': {
                'mode_key': mode_key,
                'category_key': category_key,
                'gender': gender
            }
        }
        
        text = f"""➕ **Добавление нового задания**

**Параметры:**
• Режим: {mode_key}
• Категория: {category_key}
• Пол: {gender}

**Введите текст нового задания:**"""
        
        keyboard = [
            [InlineKeyboardButton("❌ Отмена", callback_data=f"btask_view_{mode_key}_{category_key}_{gender}")]
        ]
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        await query.answer("Отправьте текст задания сообщением")
    
    async def handle_add_base_task_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ввода текста нового базового задания"""
        chat_id = update.effective_chat.id
        text = update.message.text.strip()
        
        if not text:
            await update.message.reply_text("❌ Текст задания не может быть пустым. Попробуйте еще раз.")
            return
        
        # Получаем данные из состояния
        task_data = self.user_games[chat_id]['task_data']
        mode_key = task_data['mode_key']
        category_key = task_data['category_key']
        gender = task_data['gender']
        
        try:
            print(f"[DEBUG] Попытка добавить задание: category={category_key}, gender={gender}, game_mode={mode_key}")
            print(f"[DEBUG] Текст: {text[:50]}...")
            
            # Добавляем задание в базу данных
            task_id = self.db.add_base_task(
                category=category_key,
                gender=gender,
                text=text,
                game_mode=mode_key
            )
            
            print(f"[DEBUG] Результат добавления: task_id={task_id}")
            
            # Очищаем состояние
            del self.user_games[chat_id]
            
            # Создаем кнопки возврата и добавления еще одного задания
            keyboard = [
                [InlineKeyboardButton(
                    f"🔙 Вернуться к {category_key}/{gender}", 
                    callback_data=f"btask_view_{mode_key}_{category_key}_{gender}"
                )],
                [InlineKeyboardButton(
                    "➕ Добавить ещё 1 задание", 
                    callback_data=f"btask_add_{mode_key}_{category_key}_{gender}"
                )]
            ]
            
            # Отправляем подтверждение
            await update.message.reply_text(
                f"✅ **Задание успешно добавлено!**\n\n"
                f"**ID:** {task_id}\n"
                f"**Текст:** {text}\n"
                f"**Режим:** {mode_key}\n"
                f"**Категория:** {category_key}\n"
                f"**Пол:** {gender}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
            
        except Exception as e:
            logger.error(f"Ошибка при добавлении базового задания: {e}")
            await update.message.reply_text("❌ Произошла ошибка при добавлении задания. Попробуйте еще раз.")
    
    async def handle_edit_base_task_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ввода текста при редактировании базового задания"""
        chat_id = update.effective_chat.id
        text = update.message.text.strip()

        if not text:
            await update.message.reply_text("❌ Текст задания не может быть пустым. Попробуйте еще раз.")
            return

        # Получаем данные из состояния
        task_data = self.user_games[chat_id]['task_data']
        task_id = task_data['task_id']
        mode_key = task_data['mode_key']
        category_key = task_data['category_key']
        gender = task_data['gender']

        try:
            # Обновляем задание в базе данных
            success = self.db.update_base_task(task_id, text, category_key, gender)
            
            if not success:
                await update.message.reply_text("❌ Ошибка при обновлении задания в базе данных.")
                return

            # Очищаем состояние
            del self.user_games[chat_id]

            # Создаем кнопку возврата к категории
            keyboard = [
                [InlineKeyboardButton(
                    f"🔙 Вернуться к {category_key}/{gender}", 
                    callback_data=f"btask_view_{mode_key}_{category_key}_{gender}"
                )]
            ]

            # Отправляем подтверждение
            await update.message.reply_text(
                f"✅ **Задание успешно обновлено!**\n\n"
                f"**ID:** {task_id}\n"
                f"**Новый текст:** {text}\n"
                f"**Режим:** {mode_key}\n"
                f"**Категория:** {category_key}\n"
                f"**Пол:** {gender}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )

        except Exception as e:
            logger.error(f"Ошибка при обновлении базового задания: {e}")
            await update.message.reply_text("❌ Произошла ошибка при обновлении задания. Попробуйте еще раз.")
    
    async def handle_btask_delete(self, query, data: str):
        """Меню удаления базового задания"""
        # Парсим данные: btask_delete_MODE_CATEGORY_GENDER
        parts = data.replace("btask_delete_", "").split("_")
        if len(parts) != 3:
            await self.safe_edit_message(query, "❌ Неверный формат данных.", parse_mode=None)
            return
        
        mode_key, category_key, gender = parts
        
        # Получаем задания
        tasks = self.db.get_tasks_by_mode_and_level(mode_key, category_key, gender)
        logger.info(f"Found {len(tasks)} tasks for {mode_key}/{category_key}/{gender}")
        
        base_tasks = [task for task in tasks if not task.get('is_custom', False)]
        logger.info(f"Found {len(base_tasks)} base tasks for {mode_key}/{category_key}/{gender}")
        
        if not base_tasks:
            await self.safe_edit_message(query, "❌ Нет заданий для удаления.", parse_mode=None)
            return
        
        text = f"""🗑️ **Удаление задания**

**Параметры:**
• Режим: {mode_key}
• Категория: {category_key}
• Пол: {gender}

**Выберите задание для удаления:**"""
        
        keyboard = []
        # Показываем все задания (ограничиваем до 50 для предотвращения переполнения Telegram)
        max_tasks = 50
        tasks_to_show = base_tasks[:max_tasks]
        
        if len(base_tasks) > max_tasks:
            text += f"\n⚠️ Показано первых {max_tasks} из {len(base_tasks)} заданий.\n"
        
        for task in tasks_to_show:
            short_text = task['text'][:40] + '...' if len(task['text']) > 40 else task['text']
            keyboard.append([InlineKeyboardButton(
                f"🗑️ {short_text}",
                callback_data=f"btask_confirm_delete_{task['id']}"
            )])
        
        keyboard.append([InlineKeyboardButton("← Назад", callback_data=f"btask_view_{mode_key}_{category_key}_{gender}")])
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    
    async def handle_btask_view(self, query, data: str):
        """Просмотр всех базовых заданий"""
        # Парсим данные: btask_view_MODE_CATEGORY_GENDER
        parts = data.replace("btask_view_", "").split("_")
        if len(parts) != 3:
            await self.safe_edit_message(query, "❌ Неверный формат данных.", parse_mode=None)
            return
        
        mode_key, category_key, gender = parts
        
        # Получаем задания
        tasks = self.db.get_tasks_by_mode_and_level(mode_key, category_key, gender)
        base_tasks = [task for task in tasks if not task.get('is_custom', False)]
        
        # Находим информацию о режиме и категории
        mode_info = next((mode for mode in GAME_MODES if mode['key'] == mode_key), None)
        category_info = self.get_category_info(category_key)
        gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие'}
        gender_name = gender_names.get(gender, gender)
        
        text = f"""📋 **Все базовые задания**

**Режим:** {mode_info['name'] if mode_info else mode_key}
**Категория:** {category_info['name'] if category_info else category_key}
**Тип:** {gender_name}

**Найдено заданий:** {len(base_tasks)}

"""
        
        keyboard = []
        
        # Показываем все задания (ограничиваем до 50 для предотвращения переполнения Telegram)
        # Telegram имеет ограничение на количество кнопок в клавиатуре
        max_tasks = 50
        tasks_to_show = base_tasks[:max_tasks]
        
        if len(base_tasks) > max_tasks:
            text += f"⚠️ Показано первых {max_tasks} из {len(base_tasks)} заданий.\n\n"
        
        for i, task in enumerate(tasks_to_show):
            short_text = task['text'][:50] + '...' if len(task['text']) > 50 else task['text']
            keyboard.append([InlineKeyboardButton(
                f"✏️ {short_text}",
                callback_data=f"btask_edit_{task['id']}"
            )])
        
        # Кнопки управления
        keyboard.extend([
            [InlineKeyboardButton("➕ Добавить", callback_data=f"btask_add_{mode_key}_{category_key}_{gender}")],
            [InlineKeyboardButton("🗑️ Удалить", callback_data=f"btask_delete_{mode_key}_{category_key}_{gender}")],
            [InlineKeyboardButton("👁️ Посмотреть все задания", callback_data=f"btask_view_{mode_key}_{category_key}_{gender}")],
            [InlineKeyboardButton("← Назад к типам", callback_data=f"admin_mode_category_{mode_key}_{category_key}")]
        ])
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    
    async def handle_btask_confirm_delete(self, query, data: str):
        """Подтверждение удаления задания"""
        task_id = data.replace("btask_confirm_delete_", "")
        
        # Получаем задание
        task = self.db.get_task_by_id(task_id)
        if not task:
            await self.safe_edit_message(query, "❌ Задание не найдено.", parse_mode=None)
            return
        
        text = f"""⚠️ **Подтверждение удаления**

**Задание:**
{task['text']}

**Информация:**
• Режим: {task.get('game_mode', '2couples')}
• Категория: {task['category']}
• Пол: {task['gender']}

**Вы уверены, что хотите удалить это задание?**"""
        
        keyboard = [
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"btask_save_delete_{task_id}")],
            [InlineKeyboardButton("❌ Отмена", callback_data=f"btask_view_{task.get('game_mode', '2couples')}_{task['category']}_{task['gender']}")]
        ]
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    
    async def handle_btask_save(self, query, data: str):
        """Сохранение изменений (удаление)"""
        if data.startswith("btask_save_delete_"):
            task_id = data.replace("btask_save_delete_", "")
            
            # Получаем задание для информации
            task = self.db.get_task_by_id(task_id)
            if not task:
                await self.safe_edit_message(query, "❌ Задание не найдено.", parse_mode=None)
                return
            
            # Удаляем задание
            success = self.db.delete_base_task(task_id)
            
            if success:
                await self.safe_edit_message(query, "✅ Задание успешно удалено!", parse_mode=None)
                # Возвращаемся к списку заданий
                await self.handle_btask_view(query, f"btask_view_{task.get('game_mode', '2couples')}_{task['category']}_{task['gender']}")
            else:
                await self.safe_edit_message(query, "❌ Ошибка при удалении задания.", parse_mode=None)

    async def handle_admin_reload_db(self, query):
        """Перезагрузка базы данных из главного меню админ-панели"""
        try:
            # Закрываем текущее соединение и пересоздаём объект базы данных
            self.db.close_connection()
            self.db = Database()
            
            # Получаем общую статистику по всем заданиям
            total_base_tasks = 0
            total_custom_tasks = 0
            
            # Подсчитываем задания по режимам
            for mode in GAME_MODES:
                mode_key = mode['key']
                for category in CATEGORIES:
                    category_key = category['key']
                    for gender in ['male', 'female', 'common']:
                        tasks = self.db.get_tasks_by_mode_and_level(mode_key, category_key, gender)
                        base_tasks = [task for task in tasks if not task.get('is_custom', False)]
                        custom_tasks = [task for task in tasks if task.get('is_custom', False)]
                        total_base_tasks += len(base_tasks)
                        total_custom_tasks += len(custom_tasks)
            
            text = f"""✅ **База данных успешно перезагружена!**

🔄 **Выполненные операции:**
- Закрыто текущее соединение с БД
- Создано новое подключение к базе данных
- Загружены актуальные данные

📊 **Общая статистика:**
- Всего базовых заданий: {total_base_tasks}
- Всего пользовательских заданий: {total_custom_tasks}
- Всего заданий: {total_base_tasks + total_custom_tasks}

🗂️ **Режимы игры:**
"""
            
            # Добавляем информацию по режимам
            for mode in GAME_MODES:
                mode_tasks = 0
                for category in CATEGORIES:
                    for gender in ['male', 'female', 'common']:
                        tasks = self.db.get_tasks_by_mode_and_level(mode['key'], category['key'], gender)
                        mode_tasks += len(tasks)
                text += f"• {mode['name']}: {mode_tasks} заданий\n"
            
            text += "\n✅ База данных готова к работе!"
            
            keyboard = [
                [InlineKeyboardButton("📝 Управление заданиями", callback_data="admin_base_tasks")],
                [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
                [InlineKeyboardButton("← Назад в админ-панель", callback_data="admin_panel")]
            ]
            
            await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
            
        except Exception as e:
            logger.error(f"Ошибка при перезагрузке БД: {e}")
            await self.safe_edit_message(query, f"❌ Ошибка при перезагрузке базы данных:\n{str(e)}", parse_mode=None)

    async def handle_btask_reload_db(self, query, data: str):
        """Перезагрузка базы данных для применения изменений"""
        # Парсим данные для получения информации о режиме, категории и поле
        data_without_prefix = data.replace("btask_reload_db_", "")
        parts = data_without_prefix.split('_')
        mode_key = parts[0]
        category_key = parts[1]
        gender = parts[2]
        
        # Находим информацию о режиме и категории
        mode_info = None
        for mode in GAME_MODES:
            if mode['key'] == mode_key:
                mode_info = mode
                break
        
        category_info = self.get_category_info(category_key)
        
        if not mode_info or not category_info:
            await self.safe_edit_message(query, "❌ Режим или категория не найдены.", parse_mode=None)
            return
        
        gender_names = {'male': 'мужские', 'female': 'женские', 'common': 'общие'}
        gender_name = gender_names.get(gender, gender)
        
        # Выполняем перезагрузку базы данных
        try:
            # Закрываем текущее соединение и пересоздаём объект базы данных
            self.db.close_connection()
            self.db = Database()
            
            # Получаем актуальную информацию о заданиях
            tasks = self.db.get_tasks_by_mode_and_level(mode_key, category_key, gender)
            base_tasks = [task for task in tasks if not task.get('is_custom', False)]
            
            text = f"""✅ **База данных перезагружена!**
            
🔄 **Применённые изменения:**
- Режим: {mode_info['name']} ({mode_key})
- Категория: {category_info['name']} ({category_key})
- Тип: {gender_name}
- Найдено заданий: {len(base_tasks)}

📊 **Статистика:**
- Всего базовых заданий: {len(base_tasks)}
- Задания загружены из БД
- Соединение с БД обновлено

База данных успешно обновлена и готова к работе!"""
            
            keyboard = [
                [InlineKeyboardButton("📋 Показать все задания", callback_data=f"btask_view_{mode_key}_{category_key}_{gender}")],
                [InlineKeyboardButton("← Назад к управлению", callback_data=f"admin_mode_category_gender_{mode_key}_{category_key}_{gender}")]
            ]
            
            await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
            
        except Exception as e:
            logger.error(f"Ошибка при перезагрузке БД: {e}")
            await self.safe_edit_message(query, f"❌ Ошибка при перезагрузке базы данных:\n{str(e)}", parse_mode=None)

    async def show_admin_search_users(self, query):
        """Показать поиск пользователей"""
        # Проверяем права - владелец и администраторы могут искать пользователей
        if not self.has_admin_access(query.from_user):
            await self.safe_edit_message(query, "❌ Недостаточно прав для поиска пользователей.", parse_mode=None)
            return
        
        text = """🔍 **Поиск пользователей**

Введите имя пользователя, username или часть имени для поиска.

Примеры:
• `Иван` - найти всех пользователей с именем Иван
• `@username` - найти пользователя по username
• `Петр` - найти всех пользователей с именем Петр

Отправьте сообщение с поисковым запросом:"""
        
        keyboard = [
            [InlineKeyboardButton("← К управлению пользователями", callback_data="admin_users")],
            [InlineKeyboardButton("← К управлению доступом", callback_data="admin_access_management")]
        ]
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
    
    async def show_admin_blocked_users(self, query):
        """Показать заблокированных пользователей"""
        # Проверяем права - только владелец может видеть заблокированных пользователей
        if not self.is_owner(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может просматривать заблокированных пользователей.", parse_mode=None)
            return
        
        try:
            # Получаем всех пользователей
            all_users = self.db.get_recent_users(100)
            blocked_users = [u for u in all_users if u.get('is_blocked', False)]
            
            text = """🚫 **Заблокированные пользователи**

"""
            
            if not blocked_users:
                text += "Заблокированных пользователей нет."
            else:
                for i, user in enumerate(blocked_users, 1):
                    # Формируем имя пользователя
                    if user['username']:
                        display_name = f"@{user['username']}"
                    elif user['first_name']:
                        display_name = user['first_name']
                        if user['last_name']:
                            display_name += f" {user['last_name']}"
                    else:
                        display_name = f"ID{user['id']}"
                    
                    # Определяем тип блокировки
                    if user.get('blocked_until'):
                        try:
                            from datetime import datetime
                            blocked_until = datetime.fromisoformat(user['blocked_until'].replace('Z', '+00:00'))
                            block_info = f"до {blocked_until.strftime('%d.%m.%Y %H:%M')}"
                        except:
                            block_info = "временно"
                    else:
                        block_info = "навсегда"
                    
                    reason = user.get('block_reason', 'Не указана')
                    
                    text += f"**{i}.** {display_name}\n"
                    text += f"   ID: `{user['id']}`\n"
                    text += f"   🚫 Заблокирован: {block_info}\n"
                    text += f"   📝 Причина: {reason}\n"
                    text += f"   🔓 [Разблокировать](tg://user?id={user['id']})\n\n"
            
        except Exception as e:
            logger.error(f"Ошибка получения заблокированных пользователей: {e}")
            error_logger.error(f"Ошибка получения заблокированных пользователей: {e}", exc_info=True)
            text = f"❌ **Ошибка получения данных:**\n{str(e)}"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin_blocked_users")],
            [InlineKeyboardButton("← Назад", callback_data="admin_users")]
        ]
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
    
    async def show_admin_block_user_menu(self, query, user_id: int):
        """Показать меню блокировки пользователя"""
        # Проверяем права - только владелец может блокировать пользователей
        if not self.is_owner(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может блокировать пользователей.", parse_mode=None)
            return
        
        try:
            # Получаем информацию о пользователе
            user_info = self.db.get_user_by_id(user_id)
            if not user_info:
                await self.safe_edit_message(query, "❌ Пользователь не найден.", parse_mode=None)
                return
            
            # Формируем имя пользователя
            if user_info['username']:
                display_name = f"@{user_info['username']}"
            elif user_info['first_name']:
                display_name = user_info['first_name']
                if user_info['last_name']:
                    display_name += f" {user_info['last_name']}"
            else:
                display_name = f"ID{user_info['id']}"
            
            text = f"""🚫 **Блокировка пользователя**

**Пользователь:** {display_name}
**ID:** `{user_info['id']}`

Выберите срок блокировки:"""
            
            keyboard = [
                [InlineKeyboardButton("1 день", callback_data=f"admin_confirm_block_{user_id}_1")],
                [InlineKeyboardButton("3 дня", callback_data=f"admin_confirm_block_{user_id}_3")],
                [InlineKeyboardButton("5 дней", callback_data=f"admin_confirm_block_{user_id}_5")],
                [InlineKeyboardButton("Навсегда", callback_data=f"admin_confirm_block_{user_id}_forever")],
                [InlineKeyboardButton("← Назад", callback_data="admin_users")]
            ]
            
        except Exception as e:
            logger.error(f"Ошибка получения информации о пользователе {user_id}: {e}")
            error_logger.error(f"Ошибка получения информации о пользователе {user_id}: {e}", exc_info=True)
            text = f"❌ **Ошибка получения данных пользователя:**\n{str(e)}"
            keyboard = [[InlineKeyboardButton("← Назад", callback_data="admin_users")]]
        
        await self.safe_edit_message(query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
    
    async def handle_admin_confirm_block_user(self, query, user_id: int, days: Optional[int]):
        """Подтвердить блокировку пользователя"""
        # Проверяем права - только владелец может блокировать пользователей
        if not self.is_owner(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может блокировать пользователей.", parse_mode=None)
            return
        
        try:
            # Блокируем пользователя
            blocked_by = query.from_user.id
            reason = f"Заблокирован владельцем"
            
            if days is None:
                success = self.db.block_user(user_id, days=None, blocked_by=blocked_by, reason=reason)
                block_info = "навсегда"
            else:
                success = self.db.block_user(user_id, days=days, blocked_by=blocked_by, reason=reason)
                block_info = f"на {days} {'день' if days == 1 else 'дня' if days < 5 else 'дней'}"
            
            if success:
                await self.safe_edit_message(query,
                    f"✅ **Пользователь успешно заблокирован** {block_info}.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data="admin_users")]]),
                    parse_mode=None
                )
            else:
                await self.safe_edit_message(query,
                    "❌ **Ошибка при блокировке пользователя.**",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data="admin_users")]]),
                    parse_mode=None
                )
        
        except Exception as e:
            logger.error(f"Ошибка блокировки пользователя {user_id}: {e}")
            error_logger.error(f"Ошибка блокировки пользователя {user_id}: {e}", exc_info=True)
            await self.safe_edit_message(query,
                f"❌ **Ошибка при блокировке:**\n{str(e)}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data="admin_users")]]),
                parse_mode=None
            )
    
    async def handle_admin_unblock_user(self, query, user_id: int):
        """Разблокировать пользователя"""
        # Проверяем права - только владелец может разблокировать пользователей
        if not self.is_owner(query.from_user):
            await self.safe_edit_message(query, "❌ Только владелец может разблокировать пользователей.", parse_mode=None)
            return
        
        try:
            # Разблокируем пользователя
            success = self.db.unblock_user(user_id)
            
            if success:
                await self.safe_edit_message(query,
                    "✅ **Пользователь успешно разблокирован.**",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data="admin_blocked_users")]]),
                    parse_mode=None
                )
            else:
                await self.safe_edit_message(query,
                    "❌ **Ошибка при разблокировке пользователя.**",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data="admin_blocked_users")]]),
                    parse_mode=None
                )
        
        except Exception as e:
            logger.error(f"Ошибка разблокировки пользователя {user_id}: {e}")
            error_logger.error(f"Ошибка разблокировки пользователя {user_id}: {e}", exc_info=True)
            await self.safe_edit_message(query,
                f"❌ **Ошибка при разблокировке:**\n{str(e)}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data="admin_blocked_users")]]),
                parse_mode=None
            )
    
    async def handle_user_search(self, update: Update, search_query: str):
        """Обработчик поиска пользователей"""
        try:
            # Ищем пользователей
            users = self.db.search_users(search_query, limit=20)
            
            if not users:
                keyboard = [
                    [InlineKeyboardButton("← Назад к управлению", callback_data="admin_users")],
                    [InlineKeyboardButton("← К управлению доступом", callback_data="admin_access_management")]
                ]
                await update.message.reply_text(
                    f"🔍 **Поиск: \"{search_query}\"**\n\n"
                    "Пользователи не найдены.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=None
                )
                return
            
            text = f"""🔍 **Результаты поиска: \"{search_query}\"**

**Найдено пользователей:** {len(users)}

"""
            
            keyboard = []
            
            for i, user in enumerate(users[:10]):  # Показываем первые 10
                # Формируем имя пользователя
                if user['username']:
                    display_name = f"@{user['username']}"
                elif user['first_name']:
                    display_name = user['first_name']
                    if user['last_name']:
                        display_name += f" {user['last_name']}"
                else:
                    display_name = f"ID{user['id']}"
                
                # Определяем роль пользователя
                role = "👤 Пользователь"
                if user['is_owner']:
                    role = "👑 Владелец"
                elif user['is_admin']:
                    role = "⚙️ Администратор"
                elif user['is_moderator']:
                    role = "🔍 Модератор"
                
                # Статус блокировки
                status = "✅ Активен"
                if user.get('is_blocked', False):
                    if user.get('blocked_until'):
                        try:
                            from datetime import datetime
                            blocked_until = datetime.fromisoformat(user['blocked_until'].replace('Z', '+00:00'))
                            status = f"🚫 Заблокирован до {blocked_until.strftime('%d.%m.%Y %H:%M')}"
                        except:
                            status = "🚫 Заблокирован временно"
                    else:
                        status = "🚫 Заблокирован навсегда"
                
                # Форматируем дату активности
                last_activity = user.get('last_activity', 'Неизвестно')
                if last_activity and last_activity != 'Неизвестно':
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                        last_activity = dt.strftime('%d.%m.%Y %H:%M')
                    except:
                        pass
                
                text += f"**{i+1}.** {display_name}\n"
                text += f"   ID: `{user['id']}`\n"
                text += f"   {role}\n"
                text += f"   {status}\n"
                text += f"   📅 Активность: {last_activity}\n\n"
                
                # Добавляем кнопку блокировки/разблокировки
                if user.get('is_blocked', False):
                    keyboard.append([InlineKeyboardButton(
                        f"🔓 Разблокировать {display_name}",
                        callback_data=f"admin_unblock_user_{user['id']}"
                    )])
                else:
                    keyboard.append([InlineKeyboardButton(
                        f"🚫 Заблокировать {display_name}",
                        callback_data=f"admin_block_user_{user['id']}"
                    )])
            
            # Добавляем кнопки навигации
            keyboard.append([InlineKeyboardButton("← Назад к управлению", callback_data="admin_users")])
            keyboard.append([InlineKeyboardButton("← К управлению доступом", callback_data="admin_access_management")])
            
            await update.message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
            
        except Exception as e:
            logger.error(f"Ошибка поиска пользователей: {e}")
            error_logger.error(f"Ошибка поиска пользователей: {e}", exc_info=True)
            keyboard = [
                [InlineKeyboardButton("← Назад к управлению", callback_data="admin_users")],
                [InlineKeyboardButton("← К управлению доступом", callback_data="admin_access_management")]
            ]
            await update.message.reply_text(
                f"❌ **Ошибка при поиске:**\n{str(e)}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )


def main():
    """Главная функция"""
    try:
        token = os.getenv("BOT_TOKEN")
        if not token:
            logger.error("Не найден BOT_TOKEN в переменных окружения!")
            error_logger.error("Не найден BOT_TOKEN в переменных окружения!")
            logger.error("Создайте файл .env и добавьте туда BOT_TOKEN=your_token_here")
            return
        
        logger.info("Запуск бота...")
        bot = CouplesGameBot(token)
        bot.run()


    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        error_logger.error(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    main()
