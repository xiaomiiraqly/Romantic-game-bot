#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import os
from typing import List, Dict, Optional
from datetime import datetime

class Database:
    def __init__(self, db_path: str = "bot.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Создаем таблицы если их нет
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_admin BOOLEAN DEFAULT FALSE,
                    is_owner BOOLEAN DEFAULT FALSE,
                    is_moderator BOOLEAN DEFAULT FALSE,
                    added_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (added_by) REFERENCES users(id)
                )
            """)
            
            # Функция для проверки существования колонки
            def column_exists(table_name: str, column_name: str) -> bool:
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = [row[1] for row in cursor.fetchall()]
                return column_name in columns
            
            # Добавляем поля если их еще нет
            if not column_exists('users', 'added_by'):
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN added_by INTEGER")
                except sqlite3.OperationalError:
                    pass
            
            # Добавляем поля для блокировки и активности
            if not column_exists('users', 'is_blocked'):
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN is_blocked BOOLEAN DEFAULT FALSE")
                except sqlite3.OperationalError:
                    pass
            
            if not column_exists('users', 'blocked_until'):
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN blocked_until TIMESTAMP")
                except sqlite3.OperationalError:
                    pass
            
            if not column_exists('users', 'blocked_by'):
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN blocked_by INTEGER")
                except sqlite3.OperationalError:
                    pass
            
            if not column_exists('users', 'block_reason'):
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN block_reason TEXT")
                except sqlite3.OperationalError:
                    pass
            
            if not column_exists('users', 'last_activity'):
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                except sqlite3.OperationalError:
                    pass
            
            if not column_exists('users', 'is_moderator'):
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN is_moderator BOOLEAN DEFAULT FALSE")
                except sqlite3.OperationalError:
                    pass
            
            if not column_exists('users', 'moderation_order'):
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN moderation_order INTEGER DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
            
            # Добавляем поля для статистики игр
            if not column_exists('users', 'games_played'):
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN games_played INTEGER DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
            
            if not column_exists('users', 'games_completed'):
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN games_completed INTEGER DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
            
            if not column_exists('users', 'tasks_completed'):
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN tasks_completed INTEGER DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    category TEXT NOT NULL,
                    gender TEXT NOT NULL,
                    game_mode TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    is_custom BOOLEAN DEFAULT FALSE,
                    created_by INTEGER,
                    is_public BOOLEAN DEFAULT FALSE,
                    moderation_status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    submitted_for_moderation_at TIMESTAMP,
                    moderation_order INTEGER DEFAULT 0
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    game_type TEXT NOT NULL,
                    game_mode TEXT NOT NULL,
                    players TEXT NOT NULL,
                    current_player_index INTEGER DEFAULT 0,
                    current_task_id TEXT,
                    game_state TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)
            
            # Добавляем поле moderation_order если его нет в таблице tasks
            if not column_exists('tasks', 'moderation_order'):
                try:
                    cursor.execute("ALTER TABLE tasks ADD COLUMN moderation_order INTEGER DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
            
            # Устанавливаем фиксированного владельца @MPR_XO
            self.set_fixed_owner()
            
            conn.commit()
    
    def set_fixed_owner(self):
        """Установить фиксированного владельца @MPR_XO"""
        # ID пользователя @MPR_XO (нужно получить реальный ID)
        # Пока используем специальный ID -1 для обозначения фиксированного владельца
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Проверяем, есть ли уже запись о владельце
            cursor.execute("SELECT id FROM users WHERE username = 'MPR_XO' AND is_owner = TRUE")
            if not cursor.fetchone():
                # Добавляем фиксированного владельца
                cursor.execute("""
                    INSERT OR REPLACE INTO users (id, username, first_name, last_name, is_owner, is_admin, is_moderator)
                    VALUES (-1, 'MPR_XO', 'MPR_XO', 'Owner', TRUE, TRUE, FALSE)
                """)
    
    def is_admin(self, user_id: int) -> bool:
        """Проверить, является ли пользователь администратором"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else False
    
    def is_owner(self, user_id: int) -> bool:
        """Проверить, является ли пользователь владельцем"""
        # Проверяем фиксированного владельца @MPR_XO
        if user_id == -1:
            return True
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_owner FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else False
    
    def is_moderator(self, user_id: int) -> bool:
        """Проверить, является ли пользователь модератором"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_moderator FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else False
    
    def get_admin_level(self, user_id: int) -> str:
        """Получить уровень администратора пользователя"""
        # Проверяем фиксированного владельца @MPR_XO
        if user_id == -1:
            return 'owner'
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_owner, is_admin, is_moderator FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            if result:
                is_owner, is_admin, is_moderator = result
                if is_owner:
                    return 'owner'
                elif is_admin:
                    return 'admin'
                elif is_moderator:
                    return 'moderator'
            return 'user'
    
    def set_admin(self, user_id: int, is_admin: bool = True, added_by: int = None) -> bool:
        """Установить права администратора пользователю"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE users SET is_admin = ?, added_by = ? WHERE id = ?
                """, (is_admin, added_by, user_id))
                conn.commit()
                return cursor.rowcount > 0
            except:
                return False
    
    def set_owner(self, user_id: int, is_owner: bool = True) -> bool:
        """Установить права владельца пользователю"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE users SET is_owner = ? WHERE id = ?
                """, (is_owner, user_id))
                conn.commit()
                return cursor.rowcount > 0
            except:
                return False
    
    def set_moderator(self, user_id: int, is_moderator: bool = True, added_by: int = None) -> bool:
        """Установить права модератора пользователю"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE users SET is_moderator = ?, added_by = ? WHERE id = ?
                """, (is_moderator, added_by, user_id))
                conn.commit()
                return cursor.rowcount > 0
            except:
                return False
    
    def add_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None):
        """Добавить пользователя в базу данных"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Проверяем, существует ли пользователь
            cursor.execute("SELECT is_owner, is_admin, is_moderator FROM users WHERE id = ?", (user_id,))
            existing_user = cursor.fetchone()
            
            if existing_user:
                # Пользователь существует - обновляем только основную информацию, сохраняя права
                is_owner, is_admin, is_moderator = existing_user
                
                # Проверяем, является ли пользователь фиксированным владельцем @MPR_XO или администратором @Virgo_E
                if username and username.lower() == 'mpr_xo':
                    is_owner = True
                    is_admin = True
                elif username and username.lower() == 'virgo_e':
                    is_owner = False
                    is_admin = True
                
                cursor.execute("""
                    UPDATE users SET username = ?, first_name = ?, last_name = ?, is_owner = ?, is_admin = ?
                    WHERE id = ?
                """, (username, first_name, last_name, is_owner, is_admin, user_id))
            else:
                # Новый пользователь - создаем с правами
                is_owner = False
                is_admin = False
                if username and username.lower() == 'mpr_xo':
                    is_owner = True
                    is_admin = True
                elif username and username.lower() == 'virgo_e':
                    is_owner = False
                    is_admin = True
                
                cursor.execute("""
                    INSERT INTO users (id, username, first_name, last_name, is_owner, is_admin, is_moderator, last_activity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (user_id, username, first_name, last_name, is_owner, is_admin, False))
            
            conn.commit()
    
    def save_game_state(self, chat_id: int, game_state: Dict, game_type: str):
        """Сохранить состояние игры"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Деактивируем предыдущие игры для этого чата
            cursor.execute("UPDATE games SET is_active = FALSE WHERE chat_id = ?", (chat_id,))
            
            # Добавляем новую игру
            import json
            cursor.execute("""
                INSERT INTO games (chat_id, game_type, game_mode, players, current_player_index, current_task_id, game_state)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                chat_id,
                game_type,
                game_state.get('game_mode', '2couples'),
                json.dumps(game_state.get('players', [])),
                game_state.get('current_player_index', 0),
                game_state.get('current_task_id'),
                json.dumps(game_state)
            ))
            conn.commit()
    
    def get_base_tasks_by_category_gender(self, category: str, gender: str) -> List[Dict]:
        """Получить базовые задания по категории и полу"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, text, category, gender, game_mode, task_type, is_custom, created_by, is_public, moderation_status
                FROM tasks 
                WHERE category = ? AND gender = ? AND task_type = 'base' AND is_public = TRUE
                ORDER BY id
            """, (category, gender))
            
            return [
                {
                    'id': row[0],
                    'text': row[1],
                    'category': row[2],
                    'gender': row[3],
                    'game_mode': row[4],
                    'task_type': row[5],
                    'is_custom': bool(row[6]),
                    'created_by': row[7],
                    'is_public': bool(row[8]),
                    'moderation_status': row[9]
                }
                for row in cursor.fetchall()
            ]
    
    def get_base_tasks_by_category_gender_and_type(self, category: str, gender: str, game_type: str) -> List[Dict]:
        """Получить базовые задания по категории, полу и типу игры"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, text, category, gender, game_mode, task_type, is_custom, created_by, is_public, moderation_status
                FROM tasks 
                WHERE category = ? AND gender = ? AND game_mode = ? AND task_type = 'base' AND is_public = TRUE
                ORDER BY id
            """, (category, gender, game_type))
            
            return [
                {
                    'id': row[0],
                    'text': row[1],
                    'category': row[2],
                    'gender': row[3],
                    'game_mode': row[4],
                    'task_type': row[5],
                    'is_custom': bool(row[6]),
                    'created_by': row[7],
                    'is_public': bool(row[8]),
                    'moderation_status': row[9]
                }
                for row in cursor.fetchall()
            ]
    
    def get_task_by_id(self, task_id: str) -> Optional[Dict]:
        """Получить задание по ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, text, category, gender, game_mode, task_type, is_custom, created_by, is_public, moderation_status
                FROM tasks 
                WHERE id = ?
            """, (task_id,))
            
            result = cursor.fetchone()
            if result:
                return {
                    'id': result[0],
                    'text': result[1],
                    'category': result[2],
                    'gender': result[3],
                    'game_mode': result[4],
                    'task_type': result[5],
                    'is_custom': bool(result[6]),
                    'created_by': result[7],
                    'is_public': bool(result[8]),
                    'moderation_status': result[9]
                }
            return None
    
    def get_tasks_by_type_and_level(self, game_type: str, category: str, gender: str, user_id: int = None) -> List[Dict]:
        """Получить задания по типу игры, категории и полу (расширенный режим)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Сначала получаем базовые задания для конкретного типа игры
            cursor.execute("""
                SELECT id, text, category, gender, game_mode, task_type, is_custom, created_by, is_public, moderation_status
                FROM tasks 
                WHERE game_mode = ? AND category = ? AND gender = ? AND task_type = 'base' AND is_public = TRUE
                ORDER BY id
            """, (game_type, category, gender))
            
            base_tasks = [
                {
                    'id': row[0],
                    'text': row[1],
                    'category': row[2],
                    'gender': row[3],
                    'game_mode': row[4],
                    'task_type': row[5],
                    'is_custom': bool(row[6]),
                    'created_by': row[7],
                    'is_public': bool(row[8]),
                    'moderation_status': row[9]
                }
                for row in cursor.fetchall()
            ]
            
            # Затем получаем пользовательские задания для конкретного типа игры
            cursor.execute("""
                SELECT id, text, category, gender, game_mode, task_type, is_custom, created_by, is_public, moderation_status
                FROM tasks 
                WHERE game_mode = ? AND category = ? AND gender = ? AND task_type = 'user_approved'
                ORDER BY 
                    CASE 
                        WHEN created_by = ? THEN 1
                        WHEN is_public = TRUE THEN 2
                        ELSE 3
                    END,
                    id
            """, (game_type, category, gender, user_id or 0))
            
            user_tasks = [
                {
                    'id': row[0],
                    'text': row[1],
                    'category': row[2],
                    'gender': row[3],
                    'game_mode': row[4],
                    'task_type': row[5],
                    'is_custom': bool(row[6]),
                    'created_by': row[7],
                    'is_public': bool(row[8]),
                    'moderation_status': row[9]
                }
                for row in cursor.fetchall()
            ]
            
            # Объединяем и возвращаем
            return base_tasks + user_tasks
    
    def get_extended_tasks_by_type(self, category: str, gender: str, game_type: str, user_id: int = None) -> List[Dict]:
        """Получить задания для расширенного режима: базовые + одобренные пользовательские для конкретного типа игры"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Получаем базовые задания для конкретного типа игры
            cursor.execute("""
                SELECT id, text, category, gender, game_mode, task_type, is_custom, created_by, is_public, moderation_status
                FROM tasks 
                WHERE game_mode = ? AND category = ? AND gender = ? AND task_type = 'base' AND is_public = TRUE
                ORDER BY id
            """, (game_type, category, gender))
            
            base_tasks = [
                {
                    'id': row[0],
                    'text': row[1],
                    'category': row[2],
                    'gender': row[3],
                    'game_mode': row[4],
                    'task_type': row[5],
                    'is_custom': bool(row[6]),
                    'created_by': row[7],
                    'is_public': bool(row[8]),
                    'moderation_status': row[9]
                }
                for row in cursor.fetchall()
            ]
            
            # Получаем пользовательские задания для конкретного типа игры
            # Включаем задания, которые:
            # 1. Одобрены модерацией (moderation_status = 'approved') - для всех пользователей
            # 2. Созданы текущим пользователем (независимо от статуса модерации)
            # 3. Исключаем отклоненные задания других пользователей
            cursor.execute("""
                SELECT id, text, category, gender, game_mode, task_type, is_custom, created_by, is_public, moderation_status
                FROM tasks 
                WHERE game_mode = ? AND category = ? AND gender = ? AND is_custom = TRUE
                AND (
                    moderation_status = 'approved' 
                    OR created_by = ?
                )
                AND NOT (moderation_status = 'rejected' AND created_by != ?)
                ORDER BY 
                    CASE 
                        WHEN created_by = ? THEN 1
                        WHEN moderation_status = 'approved' THEN 2
                        ELSE 3
                    END,
                    id
            """, (game_type, category, gender, user_id or 0, user_id or 0, user_id or 0))
            
            user_tasks = [
                {
                    'id': row[0],
                    'text': row[1],
                    'category': row[2],
                    'gender': row[3],
                    'game_mode': row[4],
                    'task_type': row[5],
                    'is_custom': bool(row[6]),
                    'created_by': row[7],
                    'is_public': bool(row[8]),
                    'moderation_status': row[9]
                }
                for row in cursor.fetchall()
            ]
            
            # Объединяем и возвращаем
            return base_tasks + user_tasks
    
    def get_tasks_by_mode_and_level(self, game_mode: str, category: str, gender: str, user_id: int = None) -> List[Dict]:
        """Получить задания по режиму игры, категории и полу (устаревший метод для обратной совместимости)"""
        # Перенаправляем на новый метод, используя game_mode как game_type
        return self.get_tasks_by_type_and_level(game_mode, category, gender, user_id)
    
    def get_pending_moderation_tasks(self, game_mode: str, category: str, gender: str) -> List[Dict]:
        """Получить задания, ожидающие модерации"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, text, category, gender, game_mode, task_type, is_custom, created_by, is_public, moderation_status, moderation_order
                FROM tasks
                WHERE game_mode = ? AND category = ? AND gender = ? AND is_custom = TRUE AND moderation_status = 'pending'
                ORDER BY moderation_order ASC, created_at ASC
            """, (game_mode, category, gender))

            return [
                {
                    'id': row[0],
                    'text': row[1],
                    'category': row[2],
                    'gender': row[3],
                    'game_mode': row[4],
                    'task_type': row[5],
                    'is_custom': bool(row[6]),
                    'created_by': row[7],
                    'is_public': bool(row[8]),
                    'moderation_status': row[9],
                    'moderation_order': row[10]
                }
                for row in cursor.fetchall()
            ]
    
    def add_base_task(self, category: str, gender: str, text: str, game_mode: str) -> str:
        """Добавить базовое задание (для администраторов)"""
        import uuid
        task_id = str(uuid.uuid4())
        
        print(f"[DEBUG] Добавление базового задания: ID={task_id}, category={category}, gender={gender}, game_mode={game_mode}")
        print(f"[DEBUG] Текст задания: {text[:50]}...")
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO tasks (id, text, category, gender, game_mode, task_type, is_custom, is_public, moderation_status)
                    VALUES (?, ?, ?, ?, ?, 'base', FALSE, TRUE, 'approved')
                """, (task_id, text, category, gender, game_mode))
                conn.commit()
                print(f"[DEBUG] Задание успешно добавлено в базу данных")
                return task_id
            except sqlite3.IntegrityError as e:
                print(f"[ERROR] Ошибка при добавлении задания: {e}")
                return None
            except Exception as e:
                print(f"[ERROR] Неожиданная ошибка при добавлении задания: {e}")
                return None
    
    def delete_base_task(self, task_id: str) -> bool:
        """Удалить базовое задание"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                conn.commit()
                return cursor.rowcount > 0
            except:
                return False
    
    def delete_custom_task(self, task_id: str, user_id: int) -> bool:
        """Удалить пользовательское задание (только автор может удалить)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                # Проверяем, что задание существует и пользователь является автором
                cursor.execute("""
                    SELECT id FROM tasks 
                    WHERE id = ? AND created_by = ? AND task_type = 'user_pending'
                """, (task_id, user_id))
                
                if not cursor.fetchone():
                    return False
                
                # Удаляем задание
                cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                conn.commit()
                return cursor.rowcount > 0
            except:
                return False
    
    def update_base_task(self, task_id: str, new_text: str, category: str, gender: str) -> bool:
        """Обновить базовое задание"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE tasks 
                    SET text = ?, category = ?, gender = ?
                    WHERE id = ?
                """, (new_text, category, gender, task_id))
                conn.commit()
                return cursor.rowcount > 0
            except:
                return False
    
    def add_custom_task(self, task_id: str, text: str, category: str, gender: str, game_mode: str, user_id: int) -> bool:
        """Добавить пользовательское задание"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO tasks (id, text, category, gender, game_mode, task_type, is_custom, created_by, is_public, moderation_status)
                    VALUES (?, ?, ?, ?, ?, 'user_pending', TRUE, ?, FALSE, 'draft')
                """, (task_id, text, category, gender, game_mode, user_id))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
    
    def submit_task_for_moderation(self, task_id: str) -> bool:
        """Отправить задание на модерацию"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Проверяем, что задание существует и является пользовательским
            cursor.execute("""
                SELECT id FROM tasks 
                WHERE id = ? AND is_custom = TRUE AND moderation_status != 'pending'
            """, (task_id,))
            
            if not cursor.fetchone():
                return False
            
            # Обновляем статус
            cursor.execute("""
                UPDATE tasks 
                SET moderation_status = 'pending', submitted_for_moderation_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (task_id,))
            
            conn.commit()
            return True
    
    def moderate_task(self, task_id: str, action: str, moderator_id: int) -> bool:
        """Модерировать задание (одобрить/отклонить)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Проверяем, что задание существует и ожидает модерации
            cursor.execute("""
                SELECT id, moderation_status FROM tasks 
                WHERE id = ? AND is_custom = TRUE AND moderation_status = 'pending'
            """, (task_id,))
            
            result = cursor.fetchone()
            if not result:
                return False
            
            # Обновляем статус
            if action == 'approve':
                cursor.execute("""
                    UPDATE tasks 
                    SET moderation_status = 'approved', is_public = TRUE, task_type = 'user_approved'
                    WHERE id = ?
                """, (task_id,))
            elif action == 'reject':
                cursor.execute("""
                    UPDATE tasks 
                    SET moderation_status = 'rejected', is_public = FALSE, task_type = 'user_pending'
                    WHERE id = ?
                """, (task_id,))
            
            conn.commit()
            return True
    
    def skip_task_for_moderation(self, task_id: str, game_mode: str, category: str, gender: str) -> bool:
        """Пропустить задание для модерации (переместить в конец очереди)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Получаем максимальный moderation_order для данного режима/категории/пола
            cursor.execute("""
                SELECT MAX(moderation_order) FROM tasks 
                WHERE game_mode = ? AND category = ? AND gender = ? AND is_custom = TRUE AND moderation_status = 'pending'
            """, (game_mode, category, gender))
            
            result = cursor.fetchone()
            max_order = result[0] if result[0] is not None else 0
            
            # Устанавливаем порядок на конец очереди
            cursor.execute("""
                UPDATE tasks 
                SET moderation_order = ?
                WHERE id = ? AND is_custom = TRUE AND moderation_status = 'pending'
            """, (max_order + 1, task_id))
            
            conn.commit()
            return True
    
    def get_pending_custom_tasks_count(self) -> int:
        """Получить общее количество нерассмотренных пользовательских заданий"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tasks WHERE task_type = 'user_pending'")
            return cursor.fetchone()[0]
    
    def get_pending_tasks_by_category(self) -> Dict[str, int]:
        """Получить количество нерассмотренных заданий по категориям"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT category, COUNT(*) as count 
                FROM tasks 
                WHERE task_type = 'user_pending' 
                GROUP BY category
                ORDER BY count DESC
            """)
            return dict(cursor.fetchall())
    
    def get_all_administrators(self) -> List[Dict]:
        """Получить всех администраторов"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.id as user_id, u.username, u.first_name, u.last_name, 
                       u.is_admin, u.is_owner, u.is_moderator, u.created_at,
                       added_by.id as added_by, added_by.username as added_by_username, 
                       added_by.first_name as added_by_first_name
                FROM users u
                LEFT JOIN users added_by ON u.added_by = added_by.id
                WHERE u.is_admin = TRUE OR u.is_owner = TRUE OR u.is_moderator = TRUE
                ORDER BY u.is_owner DESC, u.is_admin DESC, u.created_at ASC
            """)
            
            admins = []
            for row in cursor.fetchall():
                user_id, username, first_name, last_name, is_admin, is_owner, is_moderator, created_at, added_by, added_by_username, added_by_first_name = row
                
                # Определяем уровень
                if is_owner:
                    level = 'owner'
                elif is_admin:
                    level = 'admin'
                elif is_moderator:
                    level = 'moderator'
                else:
                    level = 'user'
                
                admins.append({
                    'user_id': user_id,
                    'username': username,
                    'first_name': first_name,
                    'last_name': last_name,
                    'level': level,
                    'added_by': added_by,
                    'added_by_username': added_by_username,
                    'added_by_first_name': added_by_first_name,
                    'created_at': created_at
                })
            
            return admins
    
    def block_user(self, user_id: int, blocked_by: int, reason: str = "", until: str = None) -> bool:
        """Заблокировать пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE users 
                    SET is_blocked = TRUE, blocked_by = ?, block_reason = ?, blocked_until = ?
                    WHERE id = ?
                """, (blocked_by, reason, until, user_id))
                conn.commit()
                return cursor.rowcount > 0
            except:
                return False
    
    def unblock_user(self, user_id: int) -> bool:
        """Разблокировать пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE users 
                    SET is_blocked = FALSE, blocked_by = NULL, block_reason = NULL, blocked_until = NULL
                    WHERE id = ?
                """, (user_id,))
                conn.commit()
                return cursor.rowcount > 0
            except:
                return False
    
    def update_user_activity(self, user_id: int):
        """Обновить время последней активности пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE users 
                    SET last_activity = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (user_id,))
                conn.commit()
            except:
                pass
    
    def increment_games_played(self, user_id: int):
        """Увеличить счетчик сыгранных игр"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE users 
                    SET games_played = games_played + 1
                    WHERE id = ?
                """, (user_id,))
                conn.commit()
            except:
                pass
    
    def increment_games_completed(self, user_id: int):
        """Увеличить счетчик завершенных игр"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE users 
                    SET games_completed = games_completed + 1
                    WHERE id = ?
                """, (user_id,))
                conn.commit()
            except:
                pass
    
    def increment_tasks_completed(self, user_id: int):
        """Увеличить счетчик выполненных заданий"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE users 
                    SET tasks_completed = tasks_completed + 1
                    WHERE id = ?
                """, (user_id,))
                conn.commit()
            except:
                pass
    
    def get_user_count(self) -> int:
        """Получить общее количество пользователей"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            return cursor.fetchone()[0]
    
    def get_active_users_count(self) -> int:
        """Получить количество активных пользователей за последний час"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM users 
                WHERE last_activity > datetime('now', '-1 hour')
            """)
            return cursor.fetchone()[0]
    
    def get_total_games_played(self) -> int:
        """Получить общее количество сыгранных игр"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(games_played) FROM users")
            result = cursor.fetchone()[0]
            return result if result else 0
    
    def get_total_games_completed(self) -> int:
        """Получить общее количество завершенных игр"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(games_completed) FROM users")
            result = cursor.fetchone()[0]
            return result if result else 0
    
    def get_top_users_by_tasks(self, limit: int = 5) -> List[Dict]:
        """Получить топ пользователей по выполненным заданиям"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, first_name, last_name, tasks_completed
                FROM users 
                WHERE tasks_completed > 0
                ORDER BY tasks_completed DESC 
                LIMIT ?
            """, (limit,))
            
            users = []
            for row in cursor.fetchall():
                users.append({
                    'id': row[0],
                    'username': row[1],
                    'first_name': row[2],
                    'last_name': row[3],
                    'tasks_completed': row[4]
                })
            return users
    
    def get_top_users_by_games(self, limit: int = 5) -> List[Dict]:
        """Получить топ пользователей по завершенным играм"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, first_name, last_name, games_completed
                FROM users 
                WHERE games_completed > 0
                ORDER BY games_completed DESC 
                LIMIT ?
            """, (limit,))
            
            users = []
            for row in cursor.fetchall():
                users.append({
                    'id': row[0],
                    'username': row[1],
                    'first_name': row[2],
                    'last_name': row[3],
                    'games_completed': row[4]
                })
            return users
    
    def get_tasks_statistics(self) -> Dict:
        """Получить статистику по заданиям"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Общее количество заданий
            cursor.execute("SELECT COUNT(*) FROM tasks")
            total_tasks = cursor.fetchone()[0]
            
            # Базовые задания
            cursor.execute("SELECT COUNT(*) FROM tasks WHERE is_custom = FALSE")
            base_tasks = cursor.fetchone()[0]
            
            # Пользовательские задания
            cursor.execute("SELECT COUNT(*) FROM tasks WHERE is_custom = TRUE")
            custom_tasks = cursor.fetchone()[0]
            
            # Задания по статусу модерации
            cursor.execute("SELECT moderation_status, COUNT(*) FROM tasks WHERE is_custom = TRUE GROUP BY moderation_status")
            moderation_stats = dict(cursor.fetchall())
            
            # Задания по категориям
            cursor.execute("SELECT category, COUNT(*) FROM tasks GROUP BY category")
            category_stats = dict(cursor.fetchall())
            
            # Задания по режимам игры
            cursor.execute("SELECT game_mode, COUNT(*) FROM tasks GROUP BY game_mode")
            mode_stats = dict(cursor.fetchall())
            
            return {
                'total_tasks': total_tasks,
                'base_tasks': base_tasks,
                'custom_tasks': custom_tasks,
                'moderation_stats': moderation_stats,
                'category_stats': category_stats,
                'mode_stats': mode_stats
            }
    
    def get_user_statistics(self) -> Dict:
        """Получить подробную статистику по пользователям"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Общее количество пользователей
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            
            # Пользователи по ролям
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_owner = TRUE")
            owners = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_admin = TRUE AND is_owner = FALSE")
            admins = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_moderator = TRUE AND is_admin = FALSE AND is_owner = FALSE")
            moderators = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_owner = FALSE AND is_admin = FALSE AND is_moderator = FALSE")
            regular_users = cursor.fetchone()[0]
            
            # Заблокированные пользователи
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_blocked = TRUE")
            blocked_users = cursor.fetchone()[0]
            
            # Пользователи за последние 24 часа
            cursor.execute("SELECT COUNT(*) FROM users WHERE created_at > datetime('now', '-24 hours')")
            users_last_24h = cursor.fetchone()[0]
            
            # Пользователи за последние 7 дней
            cursor.execute("SELECT COUNT(*) FROM users WHERE created_at > datetime('now', '-7 days')")
            users_last_7d = cursor.fetchone()[0]
            
            # Пользователи за последний месяц
            cursor.execute("SELECT COUNT(*) FROM users WHERE created_at > datetime('now', '-30 days')")
            users_last_30d = cursor.fetchone()[0]
            
            return {
                'total_users': total_users,
                'owners': owners,
                'admins': admins,
                'moderators': moderators,
                'regular_users': regular_users,
                'blocked_users': blocked_users,
                'users_last_24h': users_last_24h,
                'users_last_7d': users_last_7d,
                'users_last_30d': users_last_30d
            }
    
    def get_games_statistics(self) -> Dict:
        """Получить подробную статистику по играм"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Общая статистика игр
            cursor.execute("SELECT SUM(games_played) FROM users")
            total_games_played = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT SUM(games_completed) FROM users")
            total_games_completed = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT SUM(tasks_completed) FROM users")
            total_tasks_completed = cursor.fetchone()[0] or 0
            
            # Процент завершения игр
            completion_rate = (total_games_completed / total_games_played * 100) if total_games_played > 0 else 0
            
            # Средние значения
            cursor.execute("SELECT AVG(games_played) FROM users WHERE games_played > 0")
            avg_games_per_user = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT AVG(tasks_completed) FROM users WHERE tasks_completed > 0")
            avg_tasks_per_user = cursor.fetchone()[0] or 0
            
            return {
                'total_games_played': total_games_played,
                'total_games_completed': total_games_completed,
                'total_tasks_completed': total_tasks_completed,
                'completion_rate': round(completion_rate, 1),
                'avg_games_per_user': round(avg_games_per_user, 1),
                'avg_tasks_per_user': round(avg_tasks_per_user, 1)
            }
    
    def get_system_statistics(self) -> Dict:
        """Получить системную статистику"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Размер базы данных
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            tables_count = cursor.fetchone()[0]
            
            # Самые активные пользователи за последний час
            cursor.execute("""
                SELECT COUNT(*) FROM users 
                WHERE last_activity > datetime('now', '-1 hour')
            """)
            active_users_1h = cursor.fetchone()[0]
            
            # Самые активные пользователи за последние 24 часа
            cursor.execute("""
                SELECT COUNT(*) FROM users 
                WHERE last_activity > datetime('now', '-24 hours')
            """)
            active_users_24h = cursor.fetchone()[0]
            
            return {
                'tables_count': tables_count,
                'active_users_1h': active_users_1h,
                'active_users_24h': active_users_24h
            }
    
    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Получить пользователя по username"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, first_name, last_name, is_admin, is_owner, is_moderator
                FROM users WHERE username = ?
            """, (username,))
            result = cursor.fetchone()
            if result:
                return {
                    'chat_id': result[0],
                    'username': result[1],
                    'first_name': result[2],
                    'last_name': result[3],
                    'is_admin': bool(result[4]),
                    'is_owner': bool(result[5]),
                    'is_moderator': bool(result[6])
                }
            return None
    
    def add_administrator(self, user_id: int, username: str, first_name: str, level: str, added_by: int) -> bool:
        """Добавить администратора"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                if level == 'admin':
                    cursor.execute("""
                        UPDATE users SET is_admin = TRUE, is_moderator = FALSE, added_by = ? WHERE id = ?
                    """, (added_by, user_id))
                elif level == 'moderator':
                    cursor.execute("""
                        UPDATE users SET is_moderator = TRUE, is_admin = FALSE, added_by = ? WHERE id = ?
                    """, (added_by, user_id))
                else:
                    return False
                
                conn.commit()
                return cursor.rowcount > 0
            except:
                return False
    
    def get_recent_users(self, limit: int = 10) -> List[Dict]:
        """Получить последних пользователей"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, first_name, last_name, is_admin, is_owner, is_moderator, 
                       datetime(created_at, 'localtime') as created_at,
                       is_blocked, blocked_until, blocked_by, block_reason,
                       datetime(last_activity, 'localtime') as last_activity,
                       games_played, games_completed, tasks_completed
                FROM users 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (limit,))
            
            users = []
            for row in cursor.fetchall():
                users.append({
                    'id': row[0],
                    'username': row[1],
                    'first_name': row[2],
                    'last_name': row[3],
                    'is_admin': bool(row[4]),
                    'is_owner': bool(row[5]),
                    'is_moderator': bool(row[6]),
                    'created_at': row[7],
                    'is_blocked': bool(row[8]) if row[8] is not None else False,
                    'blocked_until': row[9],
                    'blocked_by': row[10],
                    'block_reason': row[11],
                    'last_activity': row[12] if row[12] else 'Неизвестно',
                    'games_played': row[13] or 0,
                    'games_completed': row[14] or 0,
                    'tasks_completed': row[15] or 0
                })
            
            return users
    
    def get_users_paginated(self, page: int = 1, per_page: int = 10) -> Dict:
        """Получить пользователей с пагинацией"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Получаем общее количество пользователей
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            
            # Вычисляем offset
            offset = (page - 1) * per_page
            
            # Получаем пользователей для текущей страницы
            cursor.execute("""
                SELECT id, username, first_name, last_name, is_admin, is_owner, is_moderator, 
                       datetime(created_at, 'localtime') as created_at,
                       is_blocked, blocked_until, blocked_by, block_reason,
                       datetime(last_activity, 'localtime') as last_activity,
                       games_played, games_completed, tasks_completed
                FROM users 
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """, (per_page, offset))
            
            users = []
            for row in cursor.fetchall():
                users.append({
                    'id': row[0],
                    'username': row[1],
                    'first_name': row[2],
                    'last_name': row[3],
                    'is_admin': bool(row[4]),
                    'is_owner': bool(row[5]),
                    'is_moderator': bool(row[6]),
                    'created_at': row[7],
                    'is_blocked': bool(row[8]) if row[8] is not None else False,
                    'blocked_until': row[9],
                    'blocked_by': row[10],
                    'block_reason': row[11],
                    'last_activity': row[12] if row[12] else 'Неизвестно',
                    'games_played': row[13] or 0,
                    'games_completed': row[14] or 0,
                    'tasks_completed': row[15] or 0
                })
            
            # Вычисляем информацию о пагинации
            total_pages = (total_users + per_page - 1) // per_page
            
            return {
                'users': users,
                'total_users': total_users,
                'current_page': page,
                'total_pages': total_pages,
                'per_page': per_page,
                'has_next': page < total_pages,
                'has_prev': page > 1
            }
    
    def search_users(self, query: str, limit: int = 20) -> List[Dict]:
        """Поиск пользователей по имени или username"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Убираем символ @ из поискового запроса для поиска по username
            clean_query = query.lstrip('@') if query.startswith('@') else query
            search_pattern = f"%{clean_query}%"
            
            cursor.execute("""
                SELECT id, username, first_name, last_name, is_admin, is_owner, is_moderator, 
                       is_blocked, blocked_until, datetime(created_at, 'localtime') as created_at,
                       datetime(last_activity, 'localtime') as last_activity
                FROM users 
                WHERE (first_name LIKE ? OR last_name LIKE ? OR username LIKE ?)
                ORDER BY last_activity DESC, created_at DESC
                LIMIT ?
            """, (search_pattern, search_pattern, search_pattern, limit))
            
            users = []
            for row in cursor.fetchall():
                users.append({
                    'id': row[0],
                    'username': row[1],
                    'first_name': row[2],
                    'last_name': row[3],
                    'is_admin': bool(row[4]),
                    'is_owner': bool(row[5]),
                    'is_moderator': bool(row[6]),
                    'is_blocked': bool(row[7]),
                    'blocked_until': row[8],
                    'created_at': row[9],
                    'last_activity': row[10]
                })
            
            return users
    
    def is_user_blocked(self, user_id: int) -> bool:
        """Проверить, заблокирован ли пользователь"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT is_blocked, blocked_until 
                FROM users 
                WHERE id = ?
            """, (user_id,))
            
            result = cursor.fetchone()
            if not result:
                return False
            
            is_blocked, blocked_until = result
            
            if not is_blocked:
                return False
            
            # Если заблокирован навсегда (blocked_until = NULL)
            if blocked_until is None:
                return True
            
            # Проверяем, не истек ли срок блокировки
            try:
                from datetime import datetime
                blocked_until_dt = datetime.fromisoformat(blocked_until.replace('Z', '+00:00'))
                return datetime.now() < blocked_until_dt
            except:
                return True  # Если ошибка парсинга даты, считаем заблокированным
    
    def block_user(self, user_id: int, days: Optional[int] = None, blocked_by: int = None, reason: str = None) -> bool:
        """Заблокировать пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            try:
                if days is None:
                    # Блокировка навсегда
                    cursor.execute("""
                        UPDATE users 
                        SET is_blocked = TRUE, blocked_until = NULL, blocked_by = ?, block_reason = ?
                        WHERE id = ?
                    """, (blocked_by, reason, user_id))
                else:
                    # Временная блокировка
                    from datetime import datetime, timedelta
                    blocked_until = datetime.now() + timedelta(days=days)
                    cursor.execute("""
                        UPDATE users 
                        SET is_blocked = TRUE, blocked_until = ?, blocked_by = ?, block_reason = ?
                        WHERE id = ?
                    """, (blocked_until.isoformat(), blocked_by, reason, user_id))
                
                conn.commit()
                return cursor.rowcount > 0
            except:
                return False
    
    def unblock_user(self, user_id: int) -> bool:
        """Разблокировать пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    UPDATE users 
                    SET is_blocked = FALSE, blocked_until = NULL, blocked_by = NULL, block_reason = NULL
                    WHERE id = ?
                """, (user_id,))
                
                conn.commit()
                return cursor.rowcount > 0
            except:
                return False
    
    def update_user_activity(self, user_id: int):
        """Обновить время последней активности пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    UPDATE users 
                    SET last_activity = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (user_id,))
                conn.commit()
            except:
                pass  # Игнорируем ошибки обновления активности
    
    def get_user_block_info(self, user_id: int) -> Optional[Dict]:
        """Получить информацию о блокировке пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT is_blocked, blocked_until, blocked_by, block_reason
                FROM users 
                WHERE id = ?
            """, (user_id,))
            
            result = cursor.fetchone()
            if not result:
                return None
            
            return {
                'is_blocked': bool(result[0]),
                'blocked_until': result[1],
                'blocked_by': result[2],
                'block_reason': result[3]
            }
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Получить пользователя по ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, first_name, last_name, is_admin, is_owner, is_moderator, 
                       is_blocked, blocked_until, block_reason, datetime(created_at, 'localtime') as created_at,
                       datetime(last_activity, 'localtime') as last_activity
                FROM users 
                WHERE id = ?
            """, (user_id,))
            
            result = cursor.fetchone()
            if not result:
                return None
            
            return {
                'id': result[0],
                'username': result[1],
                'first_name': result[2],
                'last_name': result[3],
                'is_admin': bool(result[4]),
                'is_owner': bool(result[5]),
                'is_moderator': bool(result[6]),
                'is_blocked': bool(result[7]),
                'blocked_until': result[8],
                'block_reason': result[9],
                'created_at': result[10],
                'last_activity': result[11]
            }
    
    def clear_all_tasks(self) -> bool:
        """Очистить все задания из базы данных"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM tasks")
                conn.commit()
                return True
            except Exception as e:
                return False
    
    def get_global_stats(self) -> Dict:
        """Получить глобальную статистику"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Подсчет пользователей
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_admin = TRUE OR is_owner = TRUE OR is_moderator = TRUE")
            total_admins = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_blocked = TRUE")
            total_blocked = cursor.fetchone()[0]
            
            # Подсчет заданий
            cursor.execute("SELECT COUNT(*) FROM tasks")
            total_tasks = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tasks WHERE is_custom = FALSE")
            base_tasks = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tasks WHERE is_custom = TRUE")
            custom_tasks = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tasks WHERE moderation_status = 'pending'")
            pending_moderation = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tasks WHERE moderation_status = 'approved'")
            approved_tasks = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tasks WHERE moderation_status = 'rejected'")
            rejected_tasks = cursor.fetchone()[0]
            
            # Подсчет игр
            cursor.execute("SELECT COUNT(*) FROM games")
            total_games = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM games WHERE is_active = TRUE")
            active_games = cursor.fetchone()[0]
            
            return {
                'users': {
                    'total': total_users,
                    'admins': total_admins,
                    'blocked': total_blocked,
                    'regular': total_users - total_admins
                },
                'tasks': {
                    'total': total_tasks,
                    'base': base_tasks,
                    'custom': custom_tasks,
                    'pending_moderation': pending_moderation,
                    'approved': approved_tasks,
                    'rejected': rejected_tasks
                },
                'games': {
                    'total': total_games,
                    'active': active_games,
                    'completed': total_games - active_games
                }
            }
    
    def close_connection(self):
        """Закрыть соединение с базой данных"""
        # SQLite автоматически закрывает соединения при выходе из контекста
        # Этот метод добавлен для совместимости с интерфейсом
        pass