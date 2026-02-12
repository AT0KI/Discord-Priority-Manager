import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import psutil
import threading
import time
import os
import sys
import json
import copy
import logging
from logging.handlers import RotatingFileHandler
import shutil
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import pystray
from pystray import MenuItem as item

# Определяем папку для конфигурации и логов
appdata = os.getenv('APPDATA')
if not appdata:
    appdata = os.path.expanduser('~')
config_dir = Path(appdata) / 'DiscordPriorityManager'
config_dir.mkdir(parents=True, exist_ok=True)

# Настройка логирования с ротацией (лог файл в папке с конфигом)
log_file_path = config_dir / 'discord_priority_manager.log'

# Создаём логгер
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Удаляем старые обработчики если есть
if logger.handlers:
    logger.handlers.clear()

# RotatingFileHandler: максимум 5 МБ на файл, хранить 3 резервные копии
file_handler = RotatingFileHandler(
    log_file_path,
    maxBytes=5*1024*1024,  # 5 МБ
    backupCount=3,          # Хранить 3 старых файла (.log.1, .log.2, .log.3)
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# StreamHandler для вывода в консоль
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Добавляем обработчики
logger.addHandler(file_handler)
logger.addHandler(console_handler)


def get_resource_path(relative_path):
    """
    Получить абсолютный путь к ресурсу, работает как для dev, так и для PyInstaller
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller создает временную папку и сохраняет путь в _MEIPASS
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def cleanup_old_logs(max_age_days=30):
    """
    Очистить очень старые лог-файлы (старше max_age_days дней)
    Это дополнительная защита на случай накопления старых .log.X файлов
    """
    try:
        current_time = time.time()
        log_dir = config_dir

        # Ищем все файлы логов
        for file in log_dir.glob('discord_priority_manager.log*'):
            try:
                file_age_days = (current_time - file.stat().st_mtime) / 86400
                if file_age_days > max_age_days:
                    file.unlink()
                    logger.info(f"Удалён старый лог-файл: {file.name} (возраст: {int(file_age_days)} дней)")
            except Exception as e:
                logger.warning(f"Не удалось удалить старый лог {file.name}: {e}")
    except Exception as e:
        logger.error(f"Ошибка очистки старых логов: {e}")


# ВАЖНО: cleanup_old_logs() вызывается в main(), а не здесь!
# Это предотвращает выполнение при импорте модуля для тестирования


class LanguageManager:
    """Класс для управления переводами"""

    def __init__(self):
        self.current_lang = 'ru'  # По умолчанию русский
        self.translations = {}
        self.available_languages = {
            'ru': 'Русский',
            'uk': 'Українська',
            'en': 'English'
        }
        self.load_all_translations()

    def load_all_translations(self):
        """Загрузить все языковые файлы"""
        for lang_code in self.available_languages.keys():
            try:
                lang_file = get_resource_path(f'lang_{lang_code}.json')
                if os.path.exists(lang_file):
                    with open(lang_file, 'r', encoding='utf-8') as f:
                        self.translations[lang_code] = json.load(f)
                    logger.info(f"Загружен языковой файл: {lang_code}")
                else:
                    logger.warning(f"Языковой файл не найден: {lang_file}")
            except Exception as e:
                logger.error(f"Ошибка загрузки языкового файла {lang_code}: {e}")

        # Если ничего не загрузилось, создаём минимальный русский перевод
        if not self.translations:
            self.translations['ru'] = {"app_title": "Discord Priority Manager Pro"}
            logger.warning("Используются минимальные встроенные переводы")

    def set_language(self, lang_code):
        """Установить текущий язык"""
        if lang_code in self.available_languages:
            self.current_lang = lang_code
            logger.info(f"Язык изменен на: {self.available_languages[lang_code]}")
            return True
        return False

    def get(self, key, **kwargs):
        """Получить перевод по ключу с поддержкой форматирования"""
        try:
            text = self.translations.get(self.current_lang, {}).get(key, key)
            # Форматирование параметров
            if kwargs:
                text = text.format(**kwargs)
            return text
        except Exception as e:
            logger.error(f"Ошибка получения перевода для ключа '{key}': {e}")
            return key


class ConfigManager:
    """Класс для управления конфигурацией программы"""

    # Константы валидации
    MIN_INTERVAL = 0.5
    MAX_INTERVAL = 60
    VALID_LANGUAGES = ['ru', 'uk', 'en']
    DEFAULT_LANGUAGE = 'ru'

    def __init__(self):
        self.config_dir = config_dir
        self.config_file = self.config_dir / 'config.json'
        self.default_config = {
            'priority_gaming': 'IDLE',
            'priority_normal': 'BELOW_NORMAL',
            'interval': 2,
            'interval_gaming': 1,
            'language': 'ru',  # Язык интерфейса по умолчанию
            'discord_processes': [
                'discord.exe',
                'discord!.exe',
                'discordcanary.exe',
                'discordptb.exe',
                'discorddevelopment.exe'
            ],
            'game_processes': [
                'cs2.exe',
                'csgo.exe',
                'valorant.exe',
                'valorant-win64-shipping.exe',
                'leagueoflegends.exe',
                'dota2.exe',
                'overwatch.exe',
                'apex_legends.exe',
                'r5apex.exe',
                'rainbow6.exe',
                'rainbowsix.exe',
                'fortnite.exe',
                'fortniteclient-win64-shipping.exe',
                'pubg.exe',
                'tslgame.exe',
                'warzone.exe',
                'modernwarfare.exe',
                'destiny2.exe',
                'stalcraftw.exe',
                'gta5.exe',
                'rocketleague.exe'
            ]
        }

    def load(self):
        """Загрузить конфигурацию из файла"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    config = copy.deepcopy(self.default_config)

                    # Обновляем только валидные ключи
                    for key, value in loaded.items():
                        if key in config:
                            # Валидация типов
                            if isinstance(config[key], bool) and isinstance(value, bool):
                                config[key] = value
                            elif isinstance(config[key], (int, float)) and isinstance(value, (int, float)):
                                config[key] = value
                            elif isinstance(config[key], str) and isinstance(value, str):
                                config[key] = value
                            elif isinstance(config[key], list) and isinstance(value, list):
                                config[key] = value

                    # Валидация числовых значений
                    config['interval'] = max(
                        self.MIN_INTERVAL,
                        min(self.MAX_INTERVAL, config.get('interval', 2))
                    )
                    config['interval_gaming'] = max(
                        self.MIN_INTERVAL,
                        min(self.MAX_INTERVAL, config.get('interval_gaming', 1))
                    )

                    # Валидация языка
                    if config.get('language') not in self.VALID_LANGUAGES:
                        config['language'] = self.DEFAULT_LANGUAGE

                    logger.info("Конфигурация успешно загружена")
                    return config
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON конфигурации: {e}")
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации: {e}")

        return copy.deepcopy(self.default_config)

    def save(self, config):
        """Сохранить конфигурацию в файл"""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)

            # Создаем резервную копию перед сохранением
            if self.config_file.exists():
                backup_file = self.config_file.with_suffix('.json.bak')
                try:
                    shutil.copy2(self.config_file, backup_file)
                except Exception as e:
                    logger.warning(f"Не удалось создать резервную копию: {e}")

            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            logger.info("Конфигурация сохранена")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения конфигурации: {e}")
            return False


class AutostartManager:
    """Класс для управления автозагрузкой в Windows"""

    def __init__(self):
        self.key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        self.app_name = "DiscordPriorityManager"

        # Импортируем winreg один раз для Windows
        if sys.platform == 'win32':
            import winreg
            self.winreg = winreg
        else:
            self.winreg = None

    def is_enabled(self):
        """Проверить, включена ли автозагрузка"""
        if sys.platform != 'win32' or not self.winreg:
            return False

        try:
            with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER,
                                self.key_path,
                                0, self.winreg.KEY_READ) as key:
                try:
                    self.winreg.QueryValueEx(key, self.app_name)
                    return True
                except FileNotFoundError:
                    return False
        except Exception as e:
            logger.error(f"Ошибка проверки автозагрузки: {e}")
            return False

    def enable(self):
        """Включить автозагрузку"""
        if sys.platform != 'win32' or not self.winreg:
            return False, "windows_only"

        try:
            # Определяем путь к исполняемому файлу
            if getattr(sys, 'frozen', False):
                exe_path = f'"{sys.executable}"'
            else:
                python_dir = Path(sys.executable).parent
                pythonw_exe = python_dir / 'pythonw.exe'
                script_path = os.path.abspath(__file__)

                if pythonw_exe.exists():
                    exe_path = f'"{pythonw_exe}" "{script_path}"'
                else:
                    exe_path = f'"{sys.executable}" "{script_path}"'

            with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER,
                                self.key_path, 0,
                                self.winreg.KEY_SET_VALUE) as key:
                self.winreg.SetValueEx(key, self.app_name, 0, self.winreg.REG_SZ, exe_path)

            logger.info("Автозагрузка включена")
            return True, "enabled"
        except Exception as e:
            logger.error(f"Ошибка включения автозагрузки: {e}")
            return False, f"error: {str(e)}"

    def disable(self):
        """Отключить автозагрузку"""
        if sys.platform != 'win32' or not self.winreg:
            return False, "windows_only"

        try:
            with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER,
                                self.key_path, 0,
                                self.winreg.KEY_SET_VALUE) as key:
                try:
                    self.winreg.DeleteValue(key, self.app_name)
                except FileNotFoundError:
                    pass  # Ключ уже отсутствует

            logger.info("Автозагрузка отключена")
            return True, "disabled"
        except Exception as e:
            logger.error(f"Ошибка отключения автозагрузки: {e}")
            return False, f"error: {str(e)}"


class ProcessMonitor:
    """Класс для мониторинга и управления процессами Discord"""

    # Словарь преобразования имен приоритетов в классы (константа класса)
    PRIORITY_MAP = {
        "IDLE": psutil.IDLE_PRIORITY_CLASS,
        "BELOW_NORMAL": psutil.BELOW_NORMAL_PRIORITY_CLASS,
        "NORMAL": psutil.NORMAL_PRIORITY_CLASS
    }

    # Словарь преобразования классов приоритетов в ключи переводов (константа класса)
    PRIORITY_KEYS_MAP = {
        psutil.IDLE_PRIORITY_CLASS: "priority_idle",
        psutil.BELOW_NORMAL_PRIORITY_CLASS: "priority_below_normal",
        psutil.NORMAL_PRIORITY_CLASS: "priority_normal",
        psutil.ABOVE_NORMAL_PRIORITY_CLASS: "priority_above_normal",
        psutil.HIGH_PRIORITY_CLASS: "priority_high",
        psutil.REALTIME_PRIORITY_CLASS: "priority_realtime"
    }

    def __init__(self, config, lang_manager):
        self.config = config
        self.lang_manager = lang_manager
        self.tracked_processes = {}
        self.priority_corrections = 0

        # Кэшируем списки процессов в нижнем регистре для O(1) поиска
        self.game_processes_lower = set(g.lower() for g in config.get('game_processes', []))
        self.discord_names_lower = set(d.lower() for d in config.get('discord_processes', []))

        # Инициализация CPU для всех процессов в фоне
        threading.Thread(target=self._init_cpu_percent, daemon=True).start()

    def _init_cpu_percent(self):
        """Инициализация CPU процента для всех процессов в фоновом потоке"""
        try:
            for proc in psutil.process_iter(['pid']):
                try:
                    proc.cpu_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            logger.warning(f"Ошибка инициализации CPU percent: {e}")

    def update_config(self, config):
        """Обновить конфигурацию и пересоздать кэши"""
        self.config = config
        self.game_processes_lower = set(g.lower() for g in config.get('game_processes', []))
        self.discord_names_lower = set(d.lower() for d in config.get('discord_processes', []))
        logger.info("Конфигурация ProcessMonitor обновлена")

    def get_priority_class(self, priority_name):
        """Получить класс приоритета по имени"""
        return self.PRIORITY_MAP.get(priority_name, psutil.IDLE_PRIORITY_CLASS)

    def get_priority_name(self, priority_class):
        """Получить название приоритета по классу с переводом"""
        key = self.PRIORITY_KEYS_MAP.get(priority_class, "priority_unknown")
        return self.lang_manager.get(key)

    def find_all_processes_optimized(self):
        """
        ОПТИМИЗАЦИЯ: Находит игры И Discord за один проход вместо двух
        Возвращает: (discord_processes, game_detected, game_name)
        """
        discord_processes = []
        seen_pids = set()
        game_detected = False
        current_game = None

        try:
            # ОДИН проход вместо двух!
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    proc_name = proc.info['name']
                    proc_name_lower = proc_name.lower()

                    # Проверка игры (если ещё не найдена)
                    if not game_detected and proc_name_lower in self.game_processes_lower:
                        game_detected = True
                        current_game = proc_name

                    # Проверка Discord
                    if proc_name_lower in self.discord_names_lower:
                        pid = proc.info['pid']
                        if pid not in seen_pids:
                            discord_processes.append(proc)
                            seen_pids.add(pid)

                        # ВСЕГДА отслеживаем дочерние процессы
                        try:
                            for child in proc.children(recursive=True):
                                child_pid = child.pid
                                if child_pid not in seen_pids:
                                    discord_processes.append(child)
                                    seen_pids.add(child_pid)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception as e:
            logger.error(f"Ошибка поиска процессов: {e}")

        return discord_processes, game_detected, current_game

    def _create_process_info_dict(self, pid, name, priority, priority_name, cpu, memory, changed, old_priority, error):
        """Вспомогательный метод для создания словаря с информацией о процессе"""
        return {
            'pid': pid,
            'name': name,
            'priority': priority,
            'priority_name': priority_name,
            'cpu': cpu,
            'memory': memory,
            'changed': changed,
            'old_priority': old_priority,
            'error': error
        }

    def get_process_info(self, proc, target_priority):
        """Получить информацию о процессе и при необходимости скорректировать приоритет"""
        try:
            with proc.oneshot():
                pid = proc.pid
                name = proc.name()

                # Попытка получить текущий приоритет
                try:
                    current_priority = proc.nice()
                except (psutil.AccessDenied, AttributeError):
                    return self._create_process_info_dict(
                        pid=pid,
                        name=name,
                        priority=target_priority,
                        priority_name=self.lang_manager.get('priority_unknown'),
                        cpu=0.0,
                        memory=0.0,
                        changed=False,
                        old_priority=None,
                        error='ACCESS_DENIED'
                    )

                priority_name = self.get_priority_name(current_priority)

                # ОПТИМИЗАЦИЯ: Получаем CPU с интервалом, чтобы снизить нагрузку
                # Используем неблокирующий вызов с interval=None (быстрее)
                try:
                    cpu_percent = proc.cpu_percent(interval=None)
                except Exception:
                    cpu_percent = 0.0

                # Получение использования памяти
                try:
                    memory_info = proc.memory_info()
                    memory_mb = memory_info.rss / (1024 * 1024)
                except Exception:
                    memory_mb = 0.0

                changed = False
                old_priority = current_priority

                # Корректировка приоритета если необходимо (auto_correct всегда True)
                if current_priority != target_priority:
                    try:
                        proc.nice(target_priority)
                        current_priority = target_priority
                        priority_name = self.get_priority_name(current_priority)
                        changed = True
                        self.priority_corrections += 1
                        logger.info(f"Приоритет изменен: {name} (PID {pid})")
                    except psutil.AccessDenied:
                        logger.warning(f"Нет доступа к процессу: {name} (PID {pid})")
                        return self._create_process_info_dict(
                            pid=pid,
                            name=name,
                            priority=target_priority,
                            priority_name=priority_name,
                            cpu=cpu_percent,
                            memory=memory_mb,
                            changed=False,
                            old_priority=old_priority,
                            error='ACCESS_DENIED'
                        )
                    except Exception as e:
                        logger.error(f"Ошибка изменения приоритета {name}: {e}")

                return self._create_process_info_dict(
                    pid=pid,
                    name=name,
                    priority=current_priority,
                    priority_name=priority_name,
                    cpu=cpu_percent,
                    memory=memory_mb,
                    changed=changed,
                    old_priority=old_priority,
                    error=None
                )

        except (psutil.NoSuchProcess, psutil.ZombieProcess) as e:
            logger.debug(f"Процесс завершен или является зомби: {e}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении информации о процессе: {e}")
            return None

    def reset_corrections(self):
        """Сбросить счетчик исправлений"""
        self.priority_corrections = 0
        logger.info("Счетчик исправлений сброшен")


class DiscordPriorityManager:
    """Основной класс приложения"""

    # Константы размеров окон
    MAIN_WINDOW_WIDTH = 1100
    MAIN_WINDOW_HEIGHT = 950
    HELP_WINDOW_WIDTH = 700
    HELP_WINDOW_HEIGHT = 600
    GAMES_WINDOW_WIDTH = 600
    GAMES_WINDOW_HEIGHT = 500

    # Константы интервалов
    TIME_UPDATE_INTERVAL = 5  # секунд
    MAX_LOG_LINES = 500  # Максимальное количество строк в логе UI

    def __init__(self, root):
        self.root = root

        # Менеджеры
        self.config_manager = ConfigManager()
        self.config = self.config_manager.load()
        self.autostart_manager = AutostartManager()

        # Language Manager
        self.lang_manager = LanguageManager()
        self.lang_manager.set_language(self.config.get('language', 'ru'))

        self.process_monitor = ProcessMonitor(self.config, self.lang_manager)

        # Устанавливаем заголовок окна с переводом
        self.root.title(self.lang_manager.get('app_title'))

        # Получаем размеры экрана
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()

        # Вычисляем позицию для центрирования
        center_x = int((screen_width - self.MAIN_WINDOW_WIDTH) / 2)
        center_y = int((screen_height - self.MAIN_WINDOW_HEIGHT) / 2)

        # Устанавливаем размер и позицию
        self.root.geometry(f"{self.MAIN_WINDOW_WIDTH}x{self.MAIN_WINDOW_HEIGHT}+{center_x}+{center_y}")
        self.root.configure(bg='#2C2F33')
        self.root.resizable(True, True)

        # Переменные состояния
        self.monitoring_lock = threading.Lock()  # Защита от race conditions - создаем ПЕРВЫМ
        self.monitoring = False
        self.monitor_thread = None
        self.last_change_time = None
        self.last_game_state = False
        self.current_game_detected = False  # Текущее состояние обнаружения игры

        # Переменные для управления треем
        self.tray_icon = None

        # Флаг для предотвращения повторных логов об ошибке доступа
        self.access_denied_logged = False

        # Создание UI
        self.create_ui()

        # Проверка статуса автозагрузки
        self.check_autostart_status()

        # Применение настроек к UI
        self.load_settings()

        # Обработчик закрытия окна (сворачивание в трей)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_window)

        # Создание иконки трея
        self.create_tray_icon()

        logger.info("Приложение инициализировано")

    @property
    def is_monitoring(self):
        """Безопасное чтение флага мониторинга (для lambda в трее)"""
        with self.monitoring_lock:
            return self.monitoring

    def create_tray_icon_image(self, color):
        """Создать изображение иконки для трея с указанным цветом"""
        width = 64
        height = 64

        # Пытаемся загрузить PNG иконки из папки с программой
        try:
            if color == 'red':
                icon_path = get_resource_path('tray_icon_red.png')
            else:  # green
                icon_path = get_resource_path('tray_icon_green.png')

            # Проверяем существование файла
            if os.path.exists(icon_path):
                # Загружаем PNG
                image = Image.open(icon_path).convert("RGBA")

                # Масштабируем до нужного размера если необходимо
                if image.size != (width, height):
                    # Используем Image.Resampling.LANCZOS для Pillow 10+ или Image.LANCZOS для старых версий
                    try:
                        from PIL import __version__ as pil_version
                        pil_major = int(pil_version.split('.')[0])
                        if pil_major >= 10:
                            image = image.resize((width, height), Image.Resampling.LANCZOS)
                        else:
                            image = image.resize((width, height), Image.LANCZOS)
                    except (AttributeError, ValueError):
                        # Fallback для любых проблем с версией
                        image = image.resize((width, height), Image.LANCZOS)

                return image
        except Exception as e:
            logger.warning(f"Не удалось загрузить пользовательскую иконку: {e}")

        # Если иконки нет - создаём стандартную
        image = Image.new('RGBA', (width, height), color=(0, 0, 0, 0))
        dc = ImageDraw.Draw(image)

        # Рисуем круг
        margin = 2
        dc.ellipse([margin, margin, width - margin, height - margin],
                   fill=color, outline='black', width=2)

        # Добавляем букву D
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except Exception:
            try:
                font = ImageFont.truetype("segoeui.ttf", 36)
            except Exception:
                font = ImageFont.load_default()

        text = "D"
        try:
            bbox = dc.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        except Exception:
            text_width = 24
            text_height = 24

        position = ((width - text_width) // 2, (height - text_height) // 2 - 3)
        dc.text(position, text, fill='white', font=font)

        return image

    def _create_tray_menu(self):
        """Создать меню трея"""
        return pystray.Menu(
            item(self.lang_manager.get('tray_show'), self.show_window, default=True),
            item(self.lang_manager.get('tray_start'), self.start_monitoring_from_tray,
                 visible=lambda item: not self.is_monitoring),
            item(self.lang_manager.get('tray_stop'), self.stop_monitoring_from_tray,
                 visible=lambda item: self.is_monitoring),
            pystray.Menu.SEPARATOR,
            item(self.lang_manager.get('tray_exit'), self.quit_app)
        )

    def create_tray_icon(self):
        """Создать иконку в системном трее"""
        icon_image = self.create_tray_icon_image('red')
        self.tray_icon = pystray.Icon("DiscordPriorityManager", icon_image,
                                      "Discord Priority Manager", self._create_tray_menu())

    def _rebuild_tray_menu(self):
        """Пересоздать меню трея"""
        if not self.tray_icon:
            return

        try:
            self.tray_icon.menu = self._create_tray_menu()
        except Exception as e:
            logger.error(f"Ошибка пересоздания меню трея: {e}")

    def update_tray_icon_color(self, color):
        """Обновить цвет иконки в трее"""
        if not self.tray_icon:
            return

        try:
            new_image = self.create_tray_icon_image(color)
            self.tray_icon.icon = new_image
        except Exception as e:
            logger.error(f"Ошибка обновления иконки трея: {e}")

    def show_window(self):
        """Показать главное окно из трея"""
        def _show():
            try:
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
            except Exception as e:
                logger.error(f"Ошибка показа окна: {e}")

        self.root.after(0, _show)

    def hide_window(self):
        """Скрыть окно в трей"""
        try:
            self.root.withdraw()
        except Exception as e:
            logger.error(f"Ошибка сворачивания окна: {e}")

    def start_monitoring_from_tray(self):
        """Запустить мониторинг из меню трея"""
        self.root.after(0, self.start_monitoring)

    def stop_monitoring_from_tray(self):
        """Остановить мониторинг из меню трея"""
        self.root.after(0, self.stop_monitoring)

    def quit_app(self):
        """Полностью выйти из приложения"""
        # Вызываем полное закрытие (tray_icon.stop будет вызван там)
        self.root.after(0, self.on_closing)

    def on_close_window(self):
        """Обработчик нажатия X (сворачивание в трей)"""
        self.hide_window()

    def run_tray(self):
        """Запустить иконку в трее"""
        if self.tray_icon:
            try:
                self.tray_icon.run()
            except Exception as e:
                logger.error(f"Ошибка запуска трея: {e}")

    def create_ui(self):
        """Создать пользовательский интерфейс"""
        style = ttk.Style()
        style.theme_use('clam')

        # Основные цвета Discord
        bg_dark = '#2C2F33'
        bg_medium = '#23272A'
        bg_light = '#40444B'
        text_color = '#DCDDDE'
        accent_blue = '#7289DA'

        # Настройка стилей
        style.configure('Discord.TFrame', background=bg_dark)
        style.configure('Discord.TLabel',
                       background=bg_dark,
                       foreground=text_color,
                       font=('Segoe UI', 10))
        style.configure('DiscordTitle.TLabel',
                       background=bg_dark,
                       foreground=text_color,
                       font=('Segoe UI', 12, 'bold'))
        style.configure('DiscordHeader.TLabel',
                       background=bg_medium,
                       foreground=text_color,
                       font=('Segoe UI', 11, 'bold'))

        style.configure('Discord.TButton',
                       background=accent_blue,
                       foreground='white',
                       borderwidth=0,
                       focuscolor='none',
                       font=('Segoe UI', 10))
        style.map('Discord.TButton',
                 background=[('active', '#677BC4'), ('pressed', '#5B6DAE')])

        style.configure('Discord.TCheckbutton',
                       background=bg_dark,
                       foreground=text_color,
                       font=('Segoe UI', 10))
        style.map('Discord.TCheckbutton',
                 background=[('active', bg_dark)])

        style.configure('Discord.TRadiobutton',
                       background=bg_dark,
                       foreground=text_color,
                       font=('Segoe UI', 10))
        style.map('Discord.TRadiobutton',
                 background=[('active', bg_dark)])

        style.configure('Discord.Treeview',
                       background=bg_medium,
                       foreground=text_color,
                       fieldbackground=bg_medium,
                       borderwidth=0,
                       font=('Segoe UI', 9))
        style.configure('Discord.Treeview.Heading',
                       background=bg_light,
                       foreground=text_color,
                       borderwidth=0,
                       font=('Segoe UI', 10, 'bold'))
        style.map('Discord.Treeview',
                 background=[('selected', accent_blue)],
                 foreground=[('selected', 'white')])
        style.map('Discord.Treeview.Heading',
                 background=[('active', '#505458')])

        # Основной контейнер
        main_container = ttk.Frame(self.root, style='Discord.TFrame')
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Верхний заголовок
        header_frame = tk.Frame(main_container, bg='#7289DA', height=60)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        header_frame.pack_propagate(False)

        title_label = tk.Label(header_frame,
                              text=self.lang_manager.get("log_welcome"),
                              font=('Segoe UI', 16, 'bold'),
                              bg='#7289DA',
                              fg='white')
        title_label.pack(side=tk.LEFT, padx=20, pady=10)

        subtitle_label = tk.Label(header_frame,
                                 text=self.lang_manager.get("window_subtitle"),
                                 font=('Segoe UI', 10),
                                 bg='#7289DA',
                                 fg='white')
        subtitle_label.pack(side=tk.LEFT, padx=10, pady=10)

        author_label = tk.Label(header_frame,
                               text="made by ATOKI",
                               font=('Segoe UI', 9, 'italic'),
                               bg='#7289DA',
                               fg='#E3E5E8')
        author_label.pack(side=tk.RIGHT, padx=20, pady=10)

        # Левая панель (настройки)
        left_panel = ttk.Frame(main_container, style='Discord.TFrame')
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 10))

        # Игровой режим
        game_section = tk.Frame(left_panel, bg='#23272A', relief=tk.RAISED, borderwidth=1)
        game_section.pack(fill=tk.X, pady=(0, 10))

        game_header = ttk.Label(game_section,
                               text=self.lang_manager.get("game_status_section"),
                               style='DiscordHeader.TLabel')
        game_header.pack(fill=tk.X, padx=10, pady=5)

        self.game_status_frame = tk.Frame(game_section, bg='#23272A')
        self.game_status_frame.pack(fill=tk.X, padx=10, pady=5)

        self.game_status_label = ttk.Label(self.game_status_frame,
                                          text=self.lang_manager.get("game_not_detected"),
                                          style='Discord.TLabel',
                                          foreground='#99AAB5')
        self.game_status_label.pack(anchor=tk.W)

        # Приоритеты
        priority_section = tk.Frame(left_panel, bg='#23272A', relief=tk.RAISED, borderwidth=1)
        priority_section.pack(fill=tk.X, pady=(0, 10))

        priority_header = ttk.Label(priority_section,
                                   text=self.lang_manager.get("settings_section"),
                                   style='DiscordHeader.TLabel')
        priority_header.pack(fill=tk.X, padx=10, pady=5)

        gaming_label = ttk.Label(priority_section,
                                text=self.lang_manager.get("settings_gaming"),
                                style='Discord.TLabel',
                                font=('Segoe UI', 9, 'bold'))
        gaming_label.pack(anchor=tk.W, padx=10, pady=(5, 2))

        self.priority_gaming_var = tk.StringVar(value=self.config.get('priority_gaming', 'IDLE'))

        gaming_frame = ttk.Frame(priority_section, style='Discord.TFrame')
        gaming_frame.pack(fill=tk.X, padx=20, pady=(0, 5))

        ttk.Radiobutton(gaming_frame, text=self.lang_manager.get("priority_idle_desc"),
                       variable=self.priority_gaming_var, value="IDLE",
                       style='Discord.TRadiobutton').pack(anchor=tk.W, pady=2)
        ttk.Radiobutton(gaming_frame, text=self.lang_manager.get("priority_below_normal_gaming_desc"),
                       variable=self.priority_gaming_var, value="BELOW_NORMAL",
                       style='Discord.TRadiobutton').pack(anchor=tk.W, pady=2)
        ttk.Radiobutton(gaming_frame, text=self.lang_manager.get("priority_normal_gaming_desc"),
                       variable=self.priority_gaming_var, value="NORMAL",
                       style='Discord.TRadiobutton').pack(anchor=tk.W, pady=2)

        normal_label = ttk.Label(priority_section,
                                text=self.lang_manager.get("settings_normal"),
                                style='Discord.TLabel',
                                font=('Segoe UI', 9, 'bold'))
        normal_label.pack(anchor=tk.W, padx=10, pady=(10, 2))

        self.priority_normal_var = tk.StringVar(value=self.config.get('priority_normal', 'BELOW_NORMAL'))

        normal_frame = ttk.Frame(priority_section, style='Discord.TFrame')
        normal_frame.pack(fill=tk.X, padx=20, pady=(0, 10))

        ttk.Radiobutton(normal_frame, text=self.lang_manager.get("priority_idle_normal_desc"),
                       variable=self.priority_normal_var, value="IDLE",
                       style='Discord.TRadiobutton').pack(anchor=tk.W, pady=2)
        ttk.Radiobutton(normal_frame, text=self.lang_manager.get("priority_below_normal_desc"),
                       variable=self.priority_normal_var, value="BELOW_NORMAL",
                       style='Discord.TRadiobutton').pack(anchor=tk.W, pady=2)
        ttk.Radiobutton(normal_frame, text=self.lang_manager.get("priority_normal_desc"),
                       variable=self.priority_normal_var, value="NORMAL",
                       style='Discord.TRadiobutton').pack(anchor=tk.W, pady=2)

        # Настройки
        settings_section = tk.Frame(left_panel, bg='#23272A', relief=tk.RAISED, borderwidth=1)
        settings_section.pack(fill=tk.X, pady=(0, 10))

        settings_header = ttk.Label(settings_section,
                                   text=self.lang_manager.get("settings_header"),
                                   style='DiscordHeader.TLabel')
        settings_header.pack(fill=tk.X, padx=10, pady=5)

        settings_frame = ttk.Frame(settings_section, style='Discord.TFrame')
        settings_frame.pack(fill=tk.X, padx=10, pady=10)

        self.autostart_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(settings_frame,
                       text=self.lang_manager.get("settings_autostart"),
                       variable=self.autostart_var,
                       command=self.toggle_autostart,
                       style='Discord.TCheckbutton').pack(anchor=tk.W, pady=3)

        # Селектор языка
        lang_frame = tk.Frame(settings_frame, bg='#2C2F33')
        lang_frame.pack(fill=tk.X, pady=(10, 0))

        tk.Label(lang_frame, text=self.lang_manager.get("language_label"),
                bg='#2C2F33', fg='#DCDDDE',
                font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W)

        self.language_var = tk.StringVar(value=self.config.get('language', 'ru'))

        lang_buttons_frame = tk.Frame(lang_frame, bg='#2C2F33')
        lang_buttons_frame.pack(fill=tk.X, pady=(5, 0))

        for lang_code, lang_name in self.lang_manager.available_languages.items():
            ttk.Radiobutton(lang_buttons_frame, text=lang_name,
                           variable=self.language_var, value=lang_code,
                           style='Discord.TRadiobutton').pack(anchor=tk.W, pady=2)

        # Кнопка "Применить язык"
        apply_lang_btn = tk.Button(lang_buttons_frame,
                                   text=self.lang_manager.get("btn_apply_language"),
                                   command=self.on_language_change,
                                   bg='#7289DA',
                                   fg='white',
                                   font=('Segoe UI', 9, 'bold'),
                                   relief=tk.FLAT,
                                   padx=15,
                                   pady=5,
                                   cursor='hand2')
        apply_lang_btn.pack(anchor=tk.W, pady=(5, 0))

        # Кнопки управления
        control_frame = ttk.Frame(left_panel, style='Discord.TFrame')
        control_frame.pack(fill=tk.X, pady=10)

        self.start_button = tk.Button(control_frame, text=self.lang_manager.get("btn_start"),
                                     command=self.start_monitoring,
                                     bg='#43B581', fg='white',
                                     font=('Segoe UI', 11, 'bold'),
                                     relief=tk.FLAT, padx=20, pady=10,
                                     cursor='hand2')
        self.start_button.pack(fill=tk.X, pady=(0, 5))

        self.stop_button = tk.Button(control_frame, text=self.lang_manager.get("btn_stop"),
                                    command=self.stop_monitoring,
                                    bg='#F04747', fg='white',
                                    font=('Segoe UI', 11, 'bold'),
                                    relief=tk.FLAT, padx=20, pady=10,
                                    cursor='hand2',
                                    state=tk.DISABLED)
        self.stop_button.pack(fill=tk.X, pady=(0, 10))

        # Дополнительные кнопки
        extra_buttons_frame = ttk.Frame(left_panel, style='Discord.TFrame')
        extra_buttons_frame.pack(fill=tk.X)

        tk.Button(extra_buttons_frame, text=self.lang_manager.get("btn_games"),
                 command=self.open_games_manager,
                 bg='#7289DA', fg='white',
                 font=('Segoe UI', 10),
                 relief=tk.FLAT, padx=15, pady=8,
                 cursor='hand2').pack(fill=tk.X, pady=(0, 5))

        tk.Button(extra_buttons_frame, text=self.lang_manager.get("btn_help"),
                 command=self.show_help,
                 bg='#99AAB5', fg='white',
                 font=('Segoe UI', 10),
                 relief=tk.FLAT, padx=15, pady=8,
                 cursor='hand2').pack(fill=tk.X)

        # Правая панель (мониторинг)
        right_panel = ttk.Frame(main_container, style='Discord.TFrame')
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Статус мониторинга
        status_section = tk.Frame(right_panel, bg='#23272A', relief=tk.RAISED, borderwidth=1)
        status_section.pack(fill=tk.X, pady=(0, 10))

        status_header_frame = tk.Frame(status_section, bg='#40444B')
        status_header_frame.pack(fill=tk.X)

        status_header = ttk.Label(status_header_frame,
                                 text=self.lang_manager.get("status_section"),
                                 style='DiscordHeader.TLabel',
                                 background='#40444B')
        status_header.pack(side=tk.LEFT, padx=10, pady=5)

        status_indicator_frame = tk.Frame(status_section, bg='#23272A')
        status_indicator_frame.pack(fill=tk.X, padx=10, pady=10)

        self.status_indicator = tk.Canvas(status_indicator_frame,
                                         width=20, height=20,
                                         bg='#23272A', highlightthickness=0)
        self.status_indicator.pack(side=tk.LEFT, padx=(0, 10))
        self.status_circle = self.status_indicator.create_oval(4, 4, 16, 16, fill='#F04747', outline='')

        self.status_label = ttk.Label(status_indicator_frame,
                                      text=self.lang_manager.get("status_monitoring_stopped"),
                                      style='Discord.TLabel',
                                      font=('Segoe UI', 11, 'bold'))
        self.status_label.pack(side=tk.LEFT)

        # Статистика
        stats_frame = tk.Frame(status_section, bg='#23272A')
        stats_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        stats_grid = tk.Frame(stats_frame, bg='#23272A')
        stats_grid.pack(fill=tk.X)

        for i in range(4):
            stats_grid.columnconfigure(i, weight=1)

        ttk.Label(stats_grid,
                 text=self.lang_manager.get("status_processes"),
                 style='Discord.TLabel').grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.process_count_label = ttk.Label(stats_grid, text="0",
                                             style='Discord.TLabel',
                                             foreground='#43B581')
        self.process_count_label.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(stats_grid,
                 text=self.lang_manager.get("status_corrections"),
                 style='Discord.TLabel').grid(row=0, column=2, sticky=tk.W, padx=5, pady=2)
        self.corrections_label = ttk.Label(stats_grid, text="0",
                                          style='Discord.TLabel',
                                          foreground='#FAA61A')
        self.corrections_label.grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)

        ttk.Label(stats_grid,
                 text=self.lang_manager.get("status_last_change"),
                 style='Discord.TLabel').grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.last_change_label = ttk.Label(stats_grid,
                                           text=self.lang_manager.get("status_not_required"),
                                           style='Discord.TLabel',
                                           foreground='#99AAB5')
        self.last_change_label.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(stats_grid,
                 text=self.lang_manager.get("status_cpu"),
                 style='Discord.TLabel').grid(row=1, column=2, sticky=tk.W, padx=5, pady=2)
        self.total_cpu_label = ttk.Label(stats_grid, text="0.0%",
                                         style='Discord.TLabel',
                                         foreground='#7289DA')
        self.total_cpu_label.grid(row=1, column=3, sticky=tk.W, padx=5, pady=2)

        # Мониторинг процессов
        process_section = tk.Frame(right_panel, bg='#23272A', relief=tk.RAISED, borderwidth=1)
        process_section.pack(fill=tk.BOTH, expand=True, pady=0)

        process_header_frame = tk.Frame(process_section, bg='#40444B')
        process_header_frame.pack(fill=tk.X)

        process_header = ttk.Label(process_header_frame,
                                  text=self.lang_manager.get("process_monitoring_header"),
                                  style='DiscordHeader.TLabel',
                                  background='#40444B')
        process_header.pack(side=tk.LEFT, padx=10, pady=5)

        # Таблица процессов
        tree_frame = tk.Frame(process_section, bg='#23272A')
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        tree_scroll = ttk.Scrollbar(tree_frame)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        columns = (
            self.lang_manager.get("process_pid"),
            self.lang_manager.get("process_name"),
            self.lang_manager.get("process_priority"),
            self.lang_manager.get("process_cpu"),
            self.lang_manager.get("process_ram")
        )
        self.process_tree = ttk.Treeview(tree_frame,
                                        columns=columns,
                                        show='headings',
                                        yscrollcommand=tree_scroll.set,
                                        style='Discord.Treeview')

        # Настройка заголовков таблицы
        for col in columns:
            self.process_tree.heading(col, text=col)

        self.process_tree.column(self.lang_manager.get("process_pid"), width=80, anchor=tk.CENTER)
        self.process_tree.column(self.lang_manager.get("process_name"), width=200)
        self.process_tree.column(self.lang_manager.get("process_priority"), width=150)
        self.process_tree.column(self.lang_manager.get("process_cpu"), width=80, anchor=tk.CENTER)
        self.process_tree.column(self.lang_manager.get("process_ram"), width=100, anchor=tk.CENTER)

        tree_scroll.config(command=self.process_tree.yview)
        self.process_tree.pack(fill=tk.BOTH, expand=True)

        # Лог событий
        log_section = tk.Frame(right_panel, bg='#23272A', relief=tk.RAISED, borderwidth=1)
        log_section.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        log_header_frame = tk.Frame(log_section, bg='#40444B')
        log_header_frame.pack(fill=tk.X)

        log_header = ttk.Label(log_header_frame,
                              text=self.lang_manager.get("log_section"),
                              style='DiscordHeader.TLabel',
                              background='#40444B')
        log_header.pack(side=tk.LEFT, padx=10, pady=5)

        log_frame = tk.Frame(log_section, bg='#23272A')
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.log_text = scrolledtext.ScrolledText(log_frame,
                                                  height=8,
                                                  bg='#1E2124',
                                                  fg='#DCDDDE',
                                                  font=('Consolas', 9),
                                                  wrap=tk.WORD,
                                                  relief=tk.FLAT,
                                                  state='disabled')
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Настройка тегов для цветного лога
        self.log_text.tag_config('INFO', foreground='#99AAB5')
        self.log_text.tag_config('SUCCESS', foreground='#43B581')
        self.log_text.tag_config('WARNING', foreground='#FAA61A')
        self.log_text.tag_config('ERROR', foreground='#F04747')

        # Приветственное сообщение
        self.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "INFO")
        self.log(self.lang_manager.get("log_welcome"), "SUCCESS")
        self.log(self.lang_manager.get("log_subtitle"), "INFO")
        self.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "INFO")
        self.log("", "INFO")
        self.log(self.lang_manager.get("log_supported_games"), "INFO")
        game_list = self.config.get('game_processes', [])
        for game in game_list[:5]:
            self.log(f"   • {game}", "INFO")
        if len(game_list) > 5:
            self.log(self.lang_manager.get("log_and_more", count=len(game_list) - 5), "INFO")
        self.log("", "INFO")
        self.log(self.lang_manager.get("log_press_start"), "INFO")
        self.log("", "INFO")

    def log(self, message, level="INFO"):
        """Добавить сообщение в лог"""
        def _log_internal():
            try:
                # Проверка существования виджета
                if not hasattr(self, 'log_text') or not self.log_text.winfo_exists():
                    return

                timestamp = datetime.now().strftime("%H:%M:%S")
                log_message = f"[{timestamp}] {message}\n"

                # Временно разрешаем редактирование для добавления текста
                self.log_text.config(state='normal')
                self.log_text.insert(tk.END, log_message, level)
                self.log_text.see(tk.END)

                # Ограничение размера лога
                lines = int(self.log_text.index('end-1c').split('.')[0])
                if lines > self.MAX_LOG_LINES:
                    self.log_text.delete('1.0', f'{lines-self.MAX_LOG_LINES}.0')

                # Возвращаем режим только для чтения
                self.log_text.config(state='disabled')
            except (tk.TclError, AttributeError, RuntimeError):
                pass
            except Exception as e:
                logger.error(f"Ошибка записи в лог UI: {e}")

        if threading.current_thread() == threading.main_thread():
            _log_internal()
        else:
            self.update_ui_safe(_log_internal)

    def update_process_tree(self, processes_info):
        """Обновить таблицу процессов"""
        try:
            # Проверка существования виджета
            if not hasattr(self, 'process_tree') or not self.process_tree.winfo_exists():
                return

            # Очистить таблицу
            for item in self.process_tree.get_children():
                self.process_tree.delete(item)

            # Добавить процессы
            for proc_info in processes_info:
                pid = proc_info['pid']
                name = proc_info['name']
                priority = proc_info['priority_name']
                cpu = f"{proc_info['cpu']:.1f}"
                memory = f"{proc_info['memory']:.1f}"

                # Цветовое выделение
                tags = ()
                if proc_info.get('error') == 'ACCESS_DENIED':
                    tags = ('error',)
                elif proc_info.get('changed'):
                    tags = ('changed',)

                self.process_tree.insert('', tk.END,
                                        values=(pid, name, priority, cpu, memory),
                                        tags=tags)

            # Настройка тегов
            self.process_tree.tag_configure('error', foreground='#F04747')
            self.process_tree.tag_configure('changed', foreground='#FAA61A')
        except Exception as e:
            logger.error(f"Ошибка обновления таблицы процессов: {e}")

    def update_game_status(self, game_detected, game_name=None):
        """Обновить статус обнаружения игры"""
        try:
            # Проверка существования виджета
            if not hasattr(self, 'game_status_label') or not self.game_status_label.winfo_exists():
                return

            if game_detected:
                # Используем game_name или "Unknown Game" если None
                display_name = game_name if game_name else "Unknown Game"
                self.game_status_label.config(
                    text=self.lang_manager.get("game_detected", game=display_name),
                    foreground='#43B581'
                )
            else:
                self.game_status_label.config(
                    text=self.lang_manager.get("game_not_detected"),
                    foreground='#99AAB5'
                )
        except Exception as e:
            logger.error(f"Ошибка обновления статуса игры: {e}")

    def save_settings(self):
        """Сохранить настройки"""
        try:
            self.config['priority_gaming'] = self.priority_gaming_var.get()
            self.config['priority_normal'] = self.priority_normal_var.get()

            # Обновляем конфигурацию ProcessMonitor
            self.process_monitor.update_config(self.config)

            if self.config_manager.save(self.config):
                self.log(self.lang_manager.get("log_settings_saved"), "SUCCESS")
                return True
            else:
                self.log(self.lang_manager.get("log_settings_error"), "ERROR")
                return False
        except Exception as e:
            logger.error(f"Ошибка сохранения настроек: {e}")
            self.log(self.lang_manager.get("log_settings_error"), "ERROR")
            return False

    def load_settings(self):
        """Загрузить настройки в UI"""
        try:
            self.priority_gaming_var.set(self.config.get('priority_gaming', 'IDLE'))
            self.priority_normal_var.set(self.config.get('priority_normal', 'BELOW_NORMAL'))
        except Exception as e:
            logger.error(f"Ошибка загрузки настроек: {e}")

    def monitor_and_adjust_priorities(self):
        """Основная функция мониторинга и корректировки приоритетов"""
        try:
            # ОПТИМИЗАЦИЯ: Один проход вместо двух!
            # Находим Discord процессы И проверяем игры одновременно
            discord_processes, game_detected, game_name = self.process_monitor.find_all_processes_optimized()

            # Сохраняем текущее состояние игры для использования в monitor_loop
            self.current_game_detected = game_detected

            # Логирование изменения состояния игры
            if game_detected != self.last_game_state:
                if game_detected:
                    self.log(self.lang_manager.get("log_game_detected", game=game_name), "SUCCESS")
                    self.log(self.lang_manager.get("log_game_priority"), "INFO")
                else:
                    self.log(self.lang_manager.get("log_game_closed"), "INFO")
                self.last_game_state = game_detected

            # Обновить UI статус игры
            self.update_ui_safe(lambda: self.update_game_status(game_detected, game_name))

            # Определение целевого приоритета
            if game_detected:
                target_priority_name = self.config.get('priority_gaming', 'IDLE')
            else:
                target_priority_name = self.config.get('priority_normal', 'BELOW_NORMAL')

            target_priority = self.process_monitor.get_priority_class(target_priority_name)

            if not discord_processes:
                if self.process_monitor.tracked_processes:
                    self.log(self.lang_manager.get("log_discord_closed"), "WARNING")
                self.process_monitor.tracked_processes.clear()
                self.update_ui_safe(
                    lambda: self.process_count_label.config(text="0")
                )
                self.update_ui_safe(lambda: self.update_process_tree([]))
                return

            self.update_ui_safe(
                lambda: self.process_count_label.config(text=str(len(discord_processes)))
            )

            new_tracked = {}
            processes_info = []
            access_denied_count = 0
            priority_was_changed = False

            for proc in discord_processes:
                proc_info = self.process_monitor.get_process_info(proc, target_priority)

                if proc_info:
                    processes_info.append(proc_info)
                    new_tracked[proc_info['pid']] = {
                        'name': proc_info['name'],
                        'priority': target_priority
                    }

                    pid = proc_info['pid']
                    name = proc_info['name']

                    if proc_info['error'] == "ACCESS_DENIED":
                        access_denied_count += 1
                        if pid not in self.process_monitor.tracked_processes:
                            self.log(
                                self.lang_manager.get("log_no_access", name=name, pid=pid),
                                "WARNING"
                            )
                    elif proc_info['changed']:
                        priority_was_changed = True
                        old_name = self.process_monitor.get_priority_name(
                            proc_info['old_priority']
                        )
                        new_name = proc_info['priority_name']

                        # Определяем тип логирования в зависимости от состояния игры
                        log_key_prefix = "gaming" if game_detected else "normal"

                        if pid in self.process_monitor.tracked_processes:
                            self.log(
                                self.lang_manager.get(
                                    f"log_corrected_{log_key_prefix}",
                                    name=name,
                                    pid=pid
                                ),
                                "WARNING"
                            )
                            self.log(
                                self.lang_manager.get(
                                    "log_priority_change",
                                    old=old_name,
                                    new=new_name
                                ),
                                "SUCCESS"
                            )
                        else:
                            self.log(
                                self.lang_manager.get(
                                    f"log_set_{log_key_prefix}",
                                    name=name,
                                    pid=pid,
                                    priority=new_name
                                ),
                                "SUCCESS"
                            )
                    else:
                        if pid not in self.process_monitor.tracked_processes:
                            log_key = (
                                "log_detected_gaming" if game_detected
                                else "log_detected_normal"
                            )
                            self.log(
                                self.lang_manager.get(
                                    log_key,
                                    name=name,
                                    pid=pid,
                                    priority=proc_info['priority_name']
                                ),
                                "SUCCESS"
                            )

            if access_denied_count > 0 and access_denied_count == len(processes_info):
                if not self.access_denied_logged:
                    self.log(self.lang_manager.get("log_no_access_all"), "ERROR")
                    self.access_denied_logged = True
            else:
                self.access_denied_logged = False

            self.update_ui_safe(lambda: self.update_process_tree(processes_info))

            total_cpu = sum(p['cpu'] for p in processes_info)
            self.update_ui_safe(
                lambda: self.total_cpu_label.config(text=f"{total_cpu:.1f}%")
            )

            self.update_ui_safe(
                lambda: self.corrections_label.config(
                    text=str(self.process_monitor.priority_corrections)
                )
            )

            # Логирование завершенных процессов
            for pid in self.process_monitor.tracked_processes:
                if pid not in new_tracked:
                    proc_info = self.process_monitor.tracked_processes[pid]
                    self.log(self.lang_manager.get("log_process_ended", name=proc_info['name'], pid=pid), "INFO")

            self.process_monitor.tracked_processes = new_tracked

            # Обновляем время только если был изменен приоритет
            if priority_was_changed:
                self.last_change_time = datetime.now()
                try:
                    self.update_last_change_display()
                except Exception as e:
                    logger.error(f"Ошибка обновления времени изменения: {e}")

        except Exception as e:
            logger.error(f"Критическая ошибка в monitor_and_adjust_priorities: {e}", exc_info=True)
            self.log(self.lang_manager.get("log_critical_error", error=str(e)), "ERROR")

    def update_last_change_display(self):
        """Обновить отображение времени последнего изменения приоритета"""
        if not self.last_change_time:
            return

        try:
            # Проверка существования виджета
            if not hasattr(self, 'last_change_label') or not self.last_change_label.winfo_exists():
                return

            now = datetime.now()
            delta = (now - self.last_change_time).total_seconds()

            if delta < 5:
                time_str = self.lang_manager.get("time_just_now")
            elif delta < 60:
                seconds = int(delta)
                time_str = self.lang_manager.get("time_seconds", seconds=seconds)
            elif delta < 3600:
                minutes = int(delta / 60)
                if minutes == 1:
                    time_str = self.lang_manager.get("time_minute")
                else:
                    time_str = self.lang_manager.get("time_minutes", minutes=minutes)
            elif delta < 86400:
                hours = int(delta / 3600)
                if hours == 1:
                    time_str = self.lang_manager.get("time_hour")
                else:
                    time_str = self.lang_manager.get("time_hours", hours=hours)
            else:
                days = int(delta / 86400)
                if days == 1:
                    time_str = self.lang_manager.get("time_day")
                else:
                    time_str = self.lang_manager.get("time_days", days=days)

            self.update_ui_safe(lambda: self.last_change_label.config(text=time_str))
        except Exception as e:
            logger.error(f"Ошибка обновления дисплея времени изменения: {e}")

    def monitor_loop(self):
        """Основной цикл мониторинга"""
        self.log(self.lang_manager.get("log_monitoring_started"), "SUCCESS")
        self.log(self.lang_manager.get("log_auto_gaming"), "INFO")
        logger.info("Цикл мониторинга запущен")

        # Счетчик для обновления времени
        time_update_counter = 0

        while True:
            with self.monitoring_lock:
                if not self.monitoring:
                    break

            try:
                self.monitor_and_adjust_priorities()

                # Использовать разные интервалы
                if self.current_game_detected:
                    interval = self.config.get('interval_gaming', 1)
                else:
                    interval = self.config.get('interval', 2)

                # Валидация интервала
                interval = max(ConfigManager.MIN_INTERVAL, min(ConfigManager.MAX_INTERVAL, interval))

                # Обновляем отображение времени периодически
                time_update_counter += interval
                if time_update_counter >= self.TIME_UPDATE_INTERVAL:
                    self.update_last_change_display()
                    time_update_counter = 0

                time.sleep(interval)
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}", exc_info=True)
                self.log(self.lang_manager.get("log_monitoring_loop_error", error=str(e)), "ERROR")
                time.sleep(5)

        self.log(self.lang_manager.get("log_monitoring_stopped"), "INFO")
        logger.info("Цикл мониторинга остановлен")

    def start_monitoring(self):
        """Запустить мониторинг"""
        # Сохраняем настройки ДО любых проверок (избегаем deadlock)
        self.save_settings()

        # Проверяем состояние и получаем старый поток в одном lock
        old_thread = None
        with self.monitoring_lock:
            if self.monitoring:
                return
            old_thread = self.monitor_thread

        # Ждем завершения старого потока вне lock
        if old_thread and old_thread.is_alive():
            old_thread.join(timeout=2.0)

        # Устанавливаем флаги мониторинга в одном lock
        with self.monitoring_lock:
            # Повторная проверка на случай race condition
            if self.monitoring:
                return
            self.monitoring = True
            self.process_monitor.reset_corrections()
            self.last_game_state = False
            self.last_change_time = None
            self.access_denied_logged = False

        # Обновление UI
        self.update_ui_safe(lambda: self.status_indicator.itemconfig(self.status_circle, fill='#43B581'))
        self.update_ui_safe(lambda: self.status_label.config(text=self.lang_manager.get("status_monitoring_active")))
        self.update_ui_safe(lambda: self.corrections_label.config(text="0"))
        self.update_ui_safe(lambda: self.last_change_label.config(text=self.lang_manager.get("status_not_required")))

        # Обновляем иконку в трее
        self.update_tray_icon_color('green')
        self._rebuild_tray_menu()

        # Обновление кнопок
        self.update_ui_safe(lambda: self.start_button.config(state=tk.DISABLED))
        self.update_ui_safe(lambda: self.stop_button.config(state=tk.NORMAL))

        # Запуск потока мониторинга
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()

        logger.info("Мониторинг запущен")

    def stop_monitoring(self):
        """Остановить мониторинг"""
        with self.monitoring_lock:
            if not self.monitoring:
                return

            self.monitoring = False

        # Обновление UI
        self.update_ui_safe(lambda: self.status_indicator.itemconfig(self.status_circle, fill='#F04747'))
        self.update_ui_safe(lambda: self.status_label.config(text=self.lang_manager.get("status_monitoring_stopped")))
        self.update_ui_safe(lambda: self.process_count_label.config(text="0"))
        self.update_ui_safe(lambda: self.total_cpu_label.config(text="0.0%"))
        self.update_ui_safe(lambda: self.last_change_label.config(text=self.lang_manager.get("status_not_required")))

        self.update_ui_safe(lambda: self.update_process_tree([]))
        self.update_ui_safe(lambda: self.update_game_status(False))

        # Обновляем иконку в трее
        self.update_tray_icon_color('red')
        self._rebuild_tray_menu()

        # Обновление кнопок
        self.update_ui_safe(lambda: self.start_button.config(state=tk.NORMAL))
        self.update_ui_safe(lambda: self.stop_button.config(state=tk.DISABLED))

        self.process_monitor.tracked_processes.clear()
        self.last_change_time = None

        logger.info("Мониторинг остановлен")

    def update_ui_safe(self, callback):
        """Безопасное обновление UI из потока"""
        try:
            if self.root.winfo_exists():
                self.root.after(0, callback)
        except (tk.TclError, RuntimeError, AttributeError):
            pass
        except Exception as e:
            logger.error(f"Ошибка безопасного обновления UI: {e}")

    def set_window_icon(self, window):
        """Установить иконку для окна"""
        try:
            icon_path = get_resource_path('icon.ico')
            if os.path.exists(icon_path):
                window.iconbitmap(icon_path)
        except Exception as e:
            logger.debug(f"Не удалось загрузить иконку: {e}")

    def center_window(self, window, width, height):
        """Центрировать окно на экране"""
        try:
            window.update_idletasks()
            screen_width = window.winfo_screenwidth()
            screen_height = window.winfo_screenheight()
            x = (screen_width // 2) - (width // 2)
            y = (screen_height // 2) - (height // 2)
            window.geometry(f"{width}x{height}+{x}+{y}")
        except Exception as e:
            logger.error(f"Ошибка центрирования окна: {e}")

    def create_dialog_header(self, parent, title_text, height=60):
        """Создать стандартный заголовок для диалогового окна"""
        header = tk.Frame(parent, bg='#7289DA', height=height)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(header, text=title_text,
                font=('Segoe UI', 14, 'bold'),
                bg='#7289DA', fg='white').pack(pady=15)

        return header

    def show_help(self):
        """Показать окно справки"""
        help_window = tk.Toplevel(self.root)
        help_window.title(self.lang_manager.get("help_window_title"))
        help_window.geometry(f"{self.HELP_WINDOW_WIDTH}x{self.HELP_WINDOW_HEIGHT}")
        help_window.configure(bg='#2C2F33')
        help_window.resizable(False, False)

        # Устанавливаем иконку
        self.set_window_icon(help_window)

        # Заголовок
        self.create_dialog_header(help_window, self.lang_manager.get("help_window_header"))

        # Контент
        content_frame = tk.Frame(help_window, bg='#2C2F33')
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Прокручиваемый текст
        text_widget = scrolledtext.ScrolledText(content_frame,
                                                bg='#23272A',
                                                fg='#DCDDDE',
                                                font=('Segoe UI', 10),
                                                wrap=tk.WORD,
                                                relief=tk.FLAT,
                                                padx=15,
                                                pady=15)
        text_widget.pack(fill=tk.BOTH, expand=True)

        # Текст справки
        help_text = self.lang_manager.get("help_content")

        text_widget.insert('1.0', help_text)
        text_widget.config(state='disabled')  # Только чтение

        # Кнопка закрытия
        tk.Button(help_window, text=self.lang_manager.get("help_btn_close"),
                 command=help_window.destroy,
                 bg='#7289DA', fg='white',
                 font=('Segoe UI', 10, 'bold'),
                 relief=tk.FLAT, padx=30, pady=10,
                 cursor='hand2').pack(pady=(0, 20))

    def open_games_manager(self):
        """Открыть окно управления играми"""
        games_window = tk.Toplevel(self.root)
        games_window.title(self.lang_manager.get("games_window_title"))
        games_window.geometry(f"{self.GAMES_WINDOW_WIDTH}x{self.GAMES_WINDOW_HEIGHT}")
        games_window.configure(bg='#2C2F33')
        games_window.resizable(False, False)

        # Устанавливаем иконку
        self.set_window_icon(games_window)

        # Заголовок
        self.create_dialog_header(games_window, self.lang_manager.get("games_window_header"))

        # Контент
        content_frame = tk.Frame(games_window, bg='#2C2F33')
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Инструкция
        tk.Label(content_frame,
                text=self.lang_manager.get("games_list_label"),
                bg='#2C2F33', fg='#DCDDDE',
                font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W, pady=(0, 10))

        # Список игр с прокруткой
        list_frame = tk.Frame(content_frame, bg='#23272A')
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.games_listbox = tk.Listbox(list_frame,
                                        bg='#23272A',
                                        fg='#DCDDDE',
                                        font=('Segoe UI', 10),
                                        selectmode=tk.SINGLE,
                                        yscrollcommand=scrollbar.set,
                                        relief=tk.FLAT,
                                        highlightthickness=0)
        self.games_listbox.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        scrollbar.config(command=self.games_listbox.yview)

        # Загружаем текущие игры
        for game in sorted(self.config.get('game_processes', [])):
            self.games_listbox.insert(tk.END, game)

        # Кнопки управления
        buttons_frame = tk.Frame(content_frame, bg='#2C2F33')
        buttons_frame.pack(fill=tk.X, pady=(10, 0))

        # Поле ввода для новой игры
        input_frame = tk.Frame(buttons_frame, bg='#2C2F33')
        input_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(input_frame, text=self.lang_manager.get("games_process_label"),
                bg='#2C2F33', fg='#DCDDDE',
                font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(0, 10))

        self.game_entry = tk.Entry(input_frame,
                                   bg='#23272A',
                                   fg='#DCDDDE',
                                   font=('Segoe UI', 10),
                                   relief=tk.FLAT,
                                   insertbackground='#DCDDDE')
        self.game_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Подсказка
        tk.Label(input_frame, text=self.lang_manager.get("games_exe_hint"),
                bg='#2C2F33', fg='#99AAB5',
                font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(5, 0))

        # Кнопки действий
        action_frame = tk.Frame(buttons_frame, bg='#2C2F33')
        action_frame.pack(fill=tk.X)

        tk.Button(action_frame, text=self.lang_manager.get("games_btn_add"),
                 command=lambda: self.add_game(games_window),
                 bg='#43B581', fg='white',
                 font=('Segoe UI', 10),
                 relief=tk.FLAT, padx=15, pady=8,
                 cursor='hand2').pack(side=tk.LEFT, padx=(0, 5))

        tk.Button(action_frame, text=self.lang_manager.get("games_btn_remove"),
                 command=lambda: self.remove_game(games_window),
                 bg='#F04747', fg='white',
                 font=('Segoe UI', 10),
                 relief=tk.FLAT, padx=15, pady=8,
                 cursor='hand2').pack(side=tk.LEFT, padx=(0, 5))

        tk.Button(action_frame, text=self.lang_manager.get("games_btn_save"),
                 command=lambda: self.save_games(games_window),
                 bg='#7289DA', fg='white',
                 font=('Segoe UI', 10, 'bold'),
                 relief=tk.FLAT, padx=15, pady=8,
                 cursor='hand2').pack(side=tk.RIGHT)

    def add_game(self, window):
        """Добавить игру в список"""
        game_name = self.game_entry.get().strip()

        if not game_name:
            self.custom_warning_dialog(
                self.lang_manager.get("games_warning_title"),
                self.lang_manager.get("games_warning_empty"),
                parent=window
            )
            return

        # Добавляем .exe если не указано
        if not game_name.lower().endswith('.exe'):
            game_name += '.exe'

        # Проверяем дубликаты (регистронезависимо)
        current_games = list(self.games_listbox.get(0, tk.END))
        current_games_lower = [g.lower() for g in current_games]

        if game_name.lower() in current_games_lower:
            self.custom_info_dialog(
                self.lang_manager.get("games_info_title"),
                self.lang_manager.get("games_info_duplicate"),
                parent=window
            )
            return

        # Добавляем в список
        self.games_listbox.insert(tk.END, game_name)
        self.game_entry.delete(0, tk.END)

        self.custom_info_dialog(
            self.lang_manager.get("games_success_title"),
            self.lang_manager.get("games_success_added", game=game_name),
            parent=window
        )

    def remove_game(self, window):
        """Удалить выбранную игру"""
        selection = self.games_listbox.curselection()

        if not selection:
            self.custom_warning_dialog(
                self.lang_manager.get("games_warning_title"),
                self.lang_manager.get("games_warning_select"),
                parent=window
            )
            return

        game_name = self.games_listbox.get(selection[0])

        if self.custom_ask_dialog(
            self.lang_manager.get("games_confirm_title"),
            self.lang_manager.get("games_confirm_remove", game=game_name),
            parent=window
        ):
            self.games_listbox.delete(selection[0])
            self.custom_info_dialog(
                self.lang_manager.get("games_success_title"),
                self.lang_manager.get("games_success_removed"),
                parent=window
            )

    def save_games(self, window):
        """Сохранить список игр в конфигурацию"""
        # Получаем все игры из списка
        games = list(self.games_listbox.get(0, tk.END))

        if not games:
            self.custom_warning_dialog(
                self.lang_manager.get("games_warning_title"),
                self.lang_manager.get("games_warning_empty_list"),
                parent=window
            )
            return

        # Сохраняем в конфигурацию
        self.config['game_processes'] = games

        # Обновляем ProcessMonitor
        self.process_monitor.update_config(self.config)

        # Сохраняем в файл
        if self.config_manager.save(self.config):
            self.custom_info_dialog(
                self.lang_manager.get("games_success_title"),
                self.lang_manager.get("games_success_saved", count=len(games)),
                parent=window
            )
            self.log(self.lang_manager.get("log_games_updated", count=len(games)), "SUCCESS")
            window.destroy()
        else:
            self.custom_error_dialog(
                self.lang_manager.get("games_error_title"),
                self.lang_manager.get("games_error_save"),
                parent=window
            )

    def check_autostart_status(self):
        """Проверить статус автозагрузки"""
        try:
            is_enabled = self.autostart_manager.is_enabled()
            self.autostart_var.set(is_enabled)
        except Exception as e:
            logger.error(f"Ошибка проверки статуса автозагрузки: {e}")
            self.autostart_var.set(False)

    def toggle_autostart(self):
        """Переключить автозагрузку"""
        if sys.platform != 'win32':
            self.custom_info_dialog(
                self.lang_manager.get("title_info"),
                self.lang_manager.get("autostart_windows_only")
            )
            self.autostart_var.set(False)
            return

        try:
            if self.autostart_var.get():
                success, message = self.autostart_manager.enable()
                if success:
                    self.log(self.lang_manager.get("log_autostart_enabled"), "SUCCESS")
                else:
                    self.log(self.lang_manager.get("log_autostart_error", message=message), "ERROR")
                    self.check_autostart_status()
            else:
                success, message = self.autostart_manager.disable()
                if success:
                    self.log(self.lang_manager.get("log_autostart_disabled"), "SUCCESS")
                else:
                    self.log(self.lang_manager.get("log_autostart_error", message=message), "ERROR")
                    self.check_autostart_status()
        except Exception as e:
            logger.error(f"Ошибка переключения автозагрузки: {e}")
            self.log(self.lang_manager.get("log_autostart_error", message=str(e)), "ERROR")
            self.check_autostart_status()

    def on_language_change(self):
        """Обработчик смены языка"""
        new_lang = self.language_var.get()
        current_lang = self.lang_manager.current_lang

        # Проверяем, изменился ли язык
        if new_lang == current_lang:
            # Язык не изменился - ничего не делаем
            return

        # Устанавливаем новый язык
        if self.lang_manager.set_language(new_lang):
            self.config['language'] = new_lang
            self.config_manager.save(self.config)

            # Обновляем UI динамически
            self.show_language_changed_dialog(new_lang)

    def show_language_changed_dialog(self, new_lang):
        """Показать диалог об успешной смене языка и применить изменения"""
        # Размеры окна
        DIALOG_WIDTH = 500
        DIALOG_HEIGHT = 300

        # Создаём диалоговое окно
        lang_dialog = tk.Toplevel(self.root)
        lang_dialog.geometry(f"{DIALOG_WIDTH}x{DIALOG_HEIGHT}")
        lang_dialog.configure(bg='#2C2F33')
        lang_dialog.resizable(False, False)
        lang_dialog.transient(self.root)
        lang_dialog.grab_set()

        # Центрируем окно
        self.center_window(lang_dialog, DIALOG_WIDTH, DIALOG_HEIGHT)

        # Устанавливаем иконку
        self.set_window_icon(lang_dialog)

        # Тексты на разных языках
        texts = {
            'ru': {
                'title': 'Язык изменён',
                'message': 'Язык интерфейса изменён на Русский!\n\nИзменения будут применены сейчас.',
                'apply_btn': '✓ Применить изменения'
            },
            'uk': {
                'title': 'Мову змінено',
                'message': 'Мову інтерфейсу змінено на Українську!\n\nЗміни будуть застосовані зараз.',
                'apply_btn': '✓ Застосувати зміни'
            },
            'en': {
                'title': 'Language Changed',
                'message': 'Interface language changed to English!\n\nChanges will be applied now.',
                'apply_btn': '✓ Apply Changes'
            }
        }

        lang_texts = texts.get(new_lang, texts['ru'])

        # Устанавливаем заголовок окна
        lang_dialog.title(lang_texts['title'])

        # Заголовок
        header_frame = tk.Frame(lang_dialog, bg='#7289DA', height=50)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)

        tk.Label(header_frame,
                text="🌐 " + lang_texts['title'],
                font=('Segoe UI', 12, 'bold'),
                bg='#7289DA',
                fg='white').pack(pady=12)

        # Сообщение
        message_frame = tk.Frame(lang_dialog, bg='#2C2F33')
        message_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        tk.Label(message_frame,
                text=lang_texts['message'],
                font=('Segoe UI', 10),
                bg='#2C2F33',
                fg='#DCDDDE',
                justify=tk.CENTER).pack(pady=10)

        # Кнопка применения
        def apply_changes():
            lang_dialog.destroy()
            # Обновляем весь UI с новым языком
            self.refresh_ui_language()

        button_frame = tk.Frame(lang_dialog, bg='#2C2F33')
        button_frame.pack(fill=tk.X, padx=20, pady=(0, 20))

        apply_btn = tk.Button(button_frame,
                             text=lang_texts['apply_btn'],
                             command=apply_changes,
                             bg='#43B581',
                             fg='white',
                             font=('Segoe UI', 10, 'bold'),
                             relief=tk.FLAT,
                             padx=20,
                             pady=10,
                             cursor='hand2')
        apply_btn.pack(expand=True, fill=tk.X)

        # Hover эффект
        def on_enter(e):
            apply_btn.config(bg='#3CA374')

        def on_leave(e):
            apply_btn.config(bg='#43B581')

        apply_btn.bind('<Enter>', on_enter)
        apply_btn.bind('<Leave>', on_leave)

    def custom_ask_dialog(self, title, message, parent=None):
        """
        Кастомный диалог подтверждения с мультиязычными кнопками
        Возвращает True если нажата кнопка Да/Yes, False если Нет/No
        """
        result = {'answer': False}

        # Создаём диалоговое окно
        dialog = tk.Toplevel(parent if parent else self.root)
        dialog.title(title)
        dialog.geometry("450x200")
        dialog.configure(bg='#2C2F33')
        dialog.resizable(False, False)
        dialog.transient(parent if parent else self.root)
        dialog.grab_set()

        # Центрируем окно
        self.center_window(dialog, 450, 200)

        # Устанавливаем иконку
        self.set_window_icon(dialog)

        # Иконка вопроса и сообщение
        message_frame = tk.Frame(dialog, bg='#2C2F33')
        message_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Иконка
        tk.Label(message_frame, text="❓", font=('Segoe UI', 36),
                bg='#2C2F33', fg='#7289DA').pack(side=tk.LEFT, padx=(0, 15))

        # Текст сообщения
        tk.Label(message_frame, text=message,
                font=('Segoe UI', 10),
                bg='#2C2F33',
                fg='#DCDDDE',
                wraplength=350,
                justify=tk.LEFT).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Кнопки
        def on_yes():
            result['answer'] = True
            dialog.destroy()

        def on_no():
            result['answer'] = False
            dialog.destroy()

        button_frame = tk.Frame(dialog, bg='#2C2F33')
        button_frame.pack(fill=tk.X, padx=20, pady=(0, 20))

        # Кнопка "Да"
        yes_btn = tk.Button(button_frame,
                           text=self.lang_manager.get("btn_yes"),
                           command=on_yes,
                           bg='#43B581',
                           fg='white',
                           font=('Segoe UI', 10, 'bold'),
                           relief=tk.FLAT,
                           padx=30,
                           pady=8,
                           cursor='hand2')
        yes_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))

        # Кнопка "Нет"
        no_btn = tk.Button(button_frame,
                          text=self.lang_manager.get("btn_no"),
                          command=on_no,
                          bg='#F04747',
                          fg='white',
                          font=('Segoe UI', 10, 'bold'),
                          relief=tk.FLAT,
                          padx=30,
                          pady=8,
                          cursor='hand2')
        no_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))

        # Hover эффекты
        def on_enter_yes(e):
            yes_btn.config(bg='#3CA374')

        def on_leave_yes(e):
            yes_btn.config(bg='#43B581')

        def on_enter_no(e):
            no_btn.config(bg='#D13B3B')

        def on_leave_no(e):
            no_btn.config(bg='#F04747')

        yes_btn.bind('<Enter>', on_enter_yes)
        yes_btn.bind('<Leave>', on_leave_yes)
        no_btn.bind('<Enter>', on_enter_no)
        no_btn.bind('<Leave>', on_leave_no)

        # Ждём закрытия окна
        dialog.wait_window()

        return result['answer']

    def custom_info_dialog(self, title, message, parent=None):
        """
        Кастомный информационный диалог
        """
        # Создаём диалоговое окно
        dialog = tk.Toplevel(parent if parent else self.root)
        dialog.title(title)
        dialog.geometry("450x200")
        dialog.configure(bg='#2C2F33')
        dialog.resizable(False, False)
        dialog.transient(parent if parent else self.root)
        dialog.grab_set()

        # Центрируем окно
        self.center_window(dialog, 450, 200)

        # Устанавливаем иконку
        self.set_window_icon(dialog)

        # Иконка информации и сообщение
        message_frame = tk.Frame(dialog, bg='#2C2F33')
        message_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Иконка
        tk.Label(message_frame, text="ℹ️", font=('Segoe UI', 36),
                bg='#2C2F33', fg='#7289DA').pack(side=tk.LEFT, padx=(0, 15))

        # Текст сообщения
        tk.Label(message_frame, text=message,
                font=('Segoe UI', 10),
                bg='#2C2F33',
                fg='#DCDDDE',
                wraplength=350,
                justify=tk.LEFT).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Кнопка
        def on_ok():
            dialog.destroy()

        button_frame = tk.Frame(dialog, bg='#2C2F33')
        button_frame.pack(fill=tk.X, padx=20, pady=(0, 20))

        ok_btn = tk.Button(button_frame,
                          text=self.lang_manager.get("btn_ok") if hasattr(self, 'lang_manager') else "OK",
                          command=on_ok,
                          bg='#7289DA',
                          fg='white',
                          font=('Segoe UI', 10, 'bold'),
                          relief=tk.FLAT,
                          padx=30,
                          pady=8,
                          cursor='hand2')
        ok_btn.pack(expand=True, fill=tk.X)

        # Hover эффект
        def on_enter(e):
            ok_btn.config(bg='#677BC4')

        def on_leave(e):
            ok_btn.config(bg='#7289DA')

        ok_btn.bind('<Enter>', on_enter)
        ok_btn.bind('<Leave>', on_leave)

        # Ждём закрытия окна
        dialog.wait_window()

    def custom_warning_dialog(self, title, message, parent=None):
        """
        Кастомный диалог предупреждения
        """
        # Создаём диалоговое окно
        dialog = tk.Toplevel(parent if parent else self.root)
        dialog.title(title)
        dialog.geometry("450x200")
        dialog.configure(bg='#2C2F33')
        dialog.resizable(False, False)
        dialog.transient(parent if parent else self.root)
        dialog.grab_set()

        # Центрируем окно
        self.center_window(dialog, 450, 200)

        # Устанавливаем иконку
        self.set_window_icon(dialog)

        # Иконка предупреждения и сообщение
        message_frame = tk.Frame(dialog, bg='#2C2F33')
        message_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Иконка
        tk.Label(message_frame, text="⚠️", font=('Segoe UI', 36),
                bg='#2C2F33', fg='#FAA61A').pack(side=tk.LEFT, padx=(0, 15))

        # Текст сообщения
        tk.Label(message_frame, text=message,
                font=('Segoe UI', 10),
                bg='#2C2F33',
                fg='#DCDDDE',
                wraplength=350,
                justify=tk.LEFT).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Кнопка
        def on_ok():
            dialog.destroy()

        button_frame = tk.Frame(dialog, bg='#2C2F33')
        button_frame.pack(fill=tk.X, padx=20, pady=(0, 20))

        ok_btn = tk.Button(button_frame,
                          text=self.lang_manager.get("btn_ok") if hasattr(self, 'lang_manager') else "OK",
                          command=on_ok,
                          bg='#FAA61A',
                          fg='white',
                          font=('Segoe UI', 10, 'bold'),
                          relief=tk.FLAT,
                          padx=30,
                          pady=8,
                          cursor='hand2')
        ok_btn.pack(expand=True, fill=tk.X)

        # Hover эффект
        def on_enter(e):
            ok_btn.config(bg='#E09316')

        def on_leave(e):
            ok_btn.config(bg='#FAA61A')

        ok_btn.bind('<Enter>', on_enter)
        ok_btn.bind('<Leave>', on_leave)

        # Ждём закрытия окна
        dialog.wait_window()

    def custom_error_dialog(self, title, message, parent=None):
        """
        Кастомный диалог ошибки
        """
        # Создаём диалоговое окно
        dialog = tk.Toplevel(parent if parent else self.root)
        dialog.title(title)
        dialog.geometry("450x200")
        dialog.configure(bg='#2C2F33')
        dialog.resizable(False, False)
        dialog.transient(parent if parent else self.root)
        dialog.grab_set()

        # Центрируем окно
        self.center_window(dialog, 450, 200)

        # Устанавливаем иконку
        self.set_window_icon(dialog)

        # Иконка ошибки и сообщение
        message_frame = tk.Frame(dialog, bg='#2C2F33')
        message_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Иконка
        tk.Label(message_frame, text="❌", font=('Segoe UI', 36),
                bg='#2C2F33', fg='#F04747').pack(side=tk.LEFT, padx=(0, 15))

        # Текст сообщения
        tk.Label(message_frame, text=message,
                font=('Segoe UI', 10),
                bg='#2C2F33',
                fg='#DCDDDE',
                wraplength=350,
                justify=tk.LEFT).pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Кнопка
        def on_ok():
            dialog.destroy()

        button_frame = tk.Frame(dialog, bg='#2C2F33')
        button_frame.pack(fill=tk.X, padx=20, pady=(0, 20))

        ok_btn = tk.Button(button_frame,
                          text=self.lang_manager.get("btn_ok") if hasattr(self, 'lang_manager') else "OK",
                          command=on_ok,
                          bg='#F04747',
                          fg='white',
                          font=('Segoe UI', 10, 'bold'),
                          relief=tk.FLAT,
                          padx=30,
                          pady=8,
                          cursor='hand2')
        ok_btn.pack(expand=True, fill=tk.X)

        # Hover эффект
        def on_enter(e):
            ok_btn.config(bg='#D13B3B')

        def on_leave(e):
            ok_btn.config(bg='#F04747')

        ok_btn.bind('<Enter>', on_enter)
        ok_btn.bind('<Leave>', on_leave)

        # Ждём закрытия окна
        dialog.wait_window()

    def refresh_ui_language(self):
        """Обновить весь UI с новым языком без перезапуска"""
        try:
            logger.info("Обновление UI с новым языком")

            # Обновляем заголовок окна
            self.root.title(self.lang_manager.get('app_title'))

            # Проверяем активность мониторинга
            was_monitoring = False
            with self.monitoring_lock:
                was_monitoring = self.monitoring

            # Останавливаем мониторинг если активен
            if was_monitoring:
                self.stop_monitoring()

            # Сохраняем текущие значения настроек
            saved_priority_gaming = self.priority_gaming_var.get()
            saved_priority_normal = self.priority_normal_var.get()
            saved_autostart = self.autostart_var.get()
            saved_language = self.language_var.get()

            # Уничтожаем все виджеты в главном окне
            for widget in self.root.winfo_children():
                widget.destroy()

            # Пересоздаём UI заново
            self.create_ui()

            # Восстанавливаем значения настроек
            self.priority_gaming_var.set(saved_priority_gaming)
            self.priority_normal_var.set(saved_priority_normal)
            self.autostart_var.set(saved_autostart)
            self.language_var.set(saved_language)

            # Обновляем статусы
            self.update_game_status(False)

            # Добавляем сообщение о смене языка в лог
            self.log(self.lang_manager.get("log_language_changed"), "SUCCESS")

            # Перестраиваем меню трея
            self._rebuild_tray_menu()

            # Уведомление пользователя
            self.custom_info_dialog(
                self.lang_manager.get("title_info"),
                self.lang_manager.get("language_applied_success")
            )

            # Запускаем мониторинг снова если был активен
            if was_monitoring:
                self.start_monitoring()

            logger.info("UI успешно обновлён с новым языком")

        except Exception as e:
            logger.error(f"Ошибка обновления UI языка: {e}", exc_info=True)
            self.custom_error_dialog(
                "Error",
                f"Failed to update UI language: {str(e)}"
            )

    def on_closing(self):
        """Обработчик полного закрытия окна"""
        logger.info("Закрытие приложения")

        # Останавливаем мониторинг
        with self.monitoring_lock:
            if self.monitoring:
                self.monitoring = False

        # Ждём завершения потока мониторинга
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)

        # Сохраняем настройки
        try:
            self.save_settings()
        except Exception as e:
            logger.error(f"Ошибка сохранения настроек при закрытии: {e}")

        # Останавливаем иконку трея
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception as e:
                logger.error(f"Ошибка остановки иконки трея: {e}")

        # Уничтожаем окно
        try:
            self.root.quit()
            self.root.destroy()
        except Exception as e:
            logger.error(f"Ошибка уничтожения окна: {e}")

        logger.info("Приложение закрыто")


def main():
    """Точка входа в приложение"""
    # Очищаем старые логи при запуске приложения
    cleanup_old_logs(max_age_days=30)

    try:
        root = tk.Tk()

        # Загрузка иконки
        try:
            png_path = get_resource_path('icon.png')
            ico_path = get_resource_path('icon.ico')
            
            # Приоритет PNG для качества в таскбаре
            if os.path.exists(png_path):
                icon_photo = tk.PhotoImage(file=png_path)
                root.iconphoto(True, icon_photo)
                root._icon_photo = icon_photo  # Сохраняем ссылку от сборщика мусора
                logger.info("Иконка загружена из PNG")
            elif os.path.exists(ico_path):
                # Конвертируем ICO в PhotoImage для качественного отображения
                ico_img = Image.open(ico_path)
                ico_img.thumbnail((32, 32), Image.Resampling.LANCZOS)
                
                # Сохраняем во временный PNG буфер
                import io
                png_buffer = io.BytesIO()
                ico_img.save(png_buffer, format='PNG')
                png_buffer.seek(0)
                
                icon_photo = tk.PhotoImage(data=png_buffer.read())
                root.iconphoto(True, icon_photo)
                root._icon_photo = icon_photo  # Сохраняем ссылку от сборщика мусора
                logger.info("Иконка загружена из ICO")
        except Exception as e:
            logger.warning(f"Не удалось загрузить иконку: {e}")

        app = DiscordPriorityManager(root)

        # Запускаем иконку трея в отдельном потоке
        tray_thread = threading.Thread(target=app.run_tray, daemon=True)
        tray_thread.start()

        logger.info("Главный цикл приложения запущен")
        root.mainloop()

    except Exception as e:
        logger.critical(f"Критическая ошибка запуска приложения: {e}", exc_info=True)

        # Пытаемся определить язык из конфига
        try:
            config_manager = ConfigManager()
            config = config_manager.load()
            lang = config.get('language', 'ru')
        except Exception:
            lang = 'ru'

        # Сообщения на разных языках
        error_messages = {
            'ru': ("Критическая ошибка", f"Не удалось запустить приложение:\n{str(e)}"),
            'uk': ("Критична помилка", f"Не вдалося запустити програму:\n{str(e)}"),
            'en': ("Critical Error", f"Failed to start application:\n{str(e)}")
        }

        title, message = error_messages.get(lang, error_messages['ru'])
        
        # Создаём простое окно ошибки для критической ошибки запуска
        error_root = tk.Tk()
        error_root.withdraw()
        
        # Используем стандартный messagebox, так как наш класс не инициализирован
        messagebox.showerror(title, message)
        sys.exit(1)


if __name__ == "__main__":
    main()
