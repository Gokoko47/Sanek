"""Private Android/Termux setup and single-instance launcher for the Business service."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import dataclasses
import fcntl
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from business import bot

KEYS = {'TELEGRAM_BOT_TOKEN', 'TELEGRAM_OWNER_ID', 'OPENAI_API_KEY', 'OPENAI_MODEL', 'REPLY_STYLE',
        'STATE_PATH', 'MAX_REPLIES_PER_HOUR', 'CHAT_COOLDOWN_SECONDS', 'MANUAL_PAUSE_SECONDS'}


@dataclasses.dataclass(frozen=True)
class Paths:
    config: Path
    data: Path

    @classmethod
    def default(cls) -> 'Paths':
        return cls(Path.home() / '.config/pakostnik-business/config.json',
                   Path.home() / '.local/share/pakostnik-business')


def private_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def read_config(paths: Paths) -> dict[str, str]:
    if not paths.config.exists():
        return {}
    if paths.config.stat().st_mode & 0o077:
        raise ValueError('Права файла настроек должны быть 600. Повторите setup после исправления прав.')
    try:
        values = json.loads(paths.config.read_text())
    except (ValueError, OSError):
        raise ValueError('Не удалось прочитать локальные настройки. Содержимое файла не выводится.') from None
    if not isinstance(values, dict) or any(k not in KEYS or not isinstance(v, str) for k, v in values.items()):
        raise ValueError('Неверный формат локальных настроек.')
    return values


def write_config(paths: Paths, values: dict[str, str]):
    bot.Config.env(values)
    private_dir(paths.config.parent)
    private_dir(paths.data)
    descriptor, name = tempfile.mkstemp(prefix='.config-', dir=paths.config.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            json.dump(values, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, paths.config)
        paths.config.chmod(0o600)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def single_instance(paths: Paths):
    private_dir(paths.data)
    with (paths.data / 'phone.lock').open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Бот уже работает в другом окне. Остановите его Ctrl+C перед настройкой или повторным запуском.') from None
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


@contextmanager
def wake_lock():
    command = shutil.which('termux-wake-lock')
    acquired = False
    try:
        if command:
            acquired = subprocess.run([command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0
        yield acquired
    finally:
        unlock = shutil.which('termux-wake-unlock')
        if acquired and unlock:
            subprocess.run([unlock], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def setup(paths: Paths, prompt=input, secret=getpass.getpass, output=print):
    with single_instance(paths):
        values = read_config(paths)
        output('Локальная настройка Pakostnik Business. Секреты вводятся скрыто.')
        output('Первый запуск: оставьте ID=0, запустите бота и отправьте ему /id в Telegram.')
        previous_token = values.get('TELEGRAM_BOT_TOKEN', '')
        token = secret('Токен BotFather' + (' [Enter — оставить]: ' if previous_token else ': ')).strip() or previous_token
        previous_id = values.get('TELEGRAM_OWNER_ID', '0')
        owner = prompt(f'Ваш числовой Telegram ID [Enter — {previous_id}]: ').strip() or previous_id
        if not owner.isdecimal() or int(owner) < 0:
            raise ValueError('ID должен быть целым неотрицательным числом.')
        key = values.get('OPENAI_API_KEY', '')
        if int(owner):
            key = secret('Ключ OpenAI API' + (' [Enter — оставить]: ' if key else ': ')).strip() or key
        style = prompt('Манера общения [Enter — оставить короткий разговорный стиль]: ').strip()
        values.update({'TELEGRAM_BOT_TOKEN': token, 'TELEGRAM_OWNER_ID': str(int(owner)), 'OPENAI_API_KEY': key,
                       'OPENAI_MODEL': values.get('OPENAI_MODEL', 'gpt-4.1-mini'),
                       'REPLY_STYLE': style or values.get('REPLY_STYLE', bot.DEFAULT_STYLE),
                       'STATE_PATH': str(paths.data / 'state.sqlite3')})
        write_config(paths, values)
        output('Сохранено в закрытых данных Termux. Значения секретов не выводятся.')
        output('Запуск: python -m business.phone run')
        if not int(owner):
            output('После /id: остановите процесс Ctrl+C, повторите setup и укажите ID и ключ ИИ.')


def run(paths: Paths, serve=None, output=print):
    with single_instance(paths):
        values = read_config(paths)
        if not values:
            raise ValueError('Сначала выполните: python -m business.phone setup')
        values['STATE_PATH'] = str(paths.data / 'state.sqlite3')
        config = bot.Config.env(values)
        output('Запуск: ' + ('только настройка /id' if config.owner_id == 0 else 'Business-автоответы для настроенного владельца'))
        output('Остановка: Ctrl+C; завершение долгого запроса может занять около минуты.')
        with wake_lock():
            (serve or bot.main)(values)


def forget(paths: Paths, prompt=input, output=print):
    with single_instance(paths):
        if prompt('Удалить сохранённые локальные токены? Напишите да: ').strip().lower() != 'да':
            output('Отменено.')
            return
        paths.config.unlink(missing_ok=True)
        output('Локальный файл токенов удалён. Перепривязку/отзыв токена выполняйте в BotFather; образцы стиля остались в файле состояния.')


def main():
    parser = argparse.ArgumentParser(description='Pakostnik Business на Android/Termux')
    parser.add_argument('command', choices=['setup', 'run', 'paths', 'forget'])
    args = parser.parse_args()
    paths = Paths.default()
    try:
        if args.command == 'setup':
            setup(paths)
        elif args.command == 'run':
            run(paths)
        elif args.command == 'forget':
            forget(paths)
        else:
            print('Настройки:', paths.config)
            print('Данные:', paths.data)
    except KeyboardInterrupt:
        print('\nНастройка отменена.')
        raise SystemExit(130) from None
    except (ValueError, OSError):
        print('Не удалось выполнить команду. Проверьте токены/ID, права локальных файлов и отсутствие второго запущенного экземпляра. Для первого запуска используйте setup.')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
