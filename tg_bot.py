import os

from telebot import TeleBot
from tempfile import NamedTemporaryFile

from loguru import logger
from telebot.apihelper import ApiTelegramException

from bot.file_processors import process_file, UnsupportedFileTypeError
from bot.sql_processor import create_task, update_task_type_by_id, update_task_status_by_id, get_count_task_in_queue
from bot.task_statuses import TaskStatuses

from bot.settings import settings

logger.info(f"Bot started with token: {settings.tg_token}")
bot = TeleBot(settings.tg_token)


@bot.message_handler(content_types=['document'])
def handle_document(message):
    try:
        user_id = str(message.from_user.id)
        task_id = create_task(TaskStatuses.NEW, user_id)
    except Exception as e:
        logger.error(f"Error while creating task for.\nError: {e}")
        bot.reply_to(message, "Произошла ошибка при создании задачи.")
        return

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
    except ApiTelegramException as e:
        logger.error(f"Error while downloading file for user {user_id}.\nError: {e}")
        update_task_status_by_id(task_id, TaskStatuses.FAILED)
        bot.reply_to(message, "Файл должен быть меньше 20 МБ.")
        return
    except Exception as e:
        logger.error(f"Error while downloading file for user {user_id}.\nError: {e}")
        update_task_status_by_id(task_id, TaskStatuses.FAILED)
        bot.reply_to(message, "Произошла ошибка при загрузке файла.")
        return

    try:
        # Get the file extension
        file_extension = os.path.splitext(file_info.file_path)[-1]

        with NamedTemporaryFile(delete=True, suffix=file_extension) as temp_file:
            temp_file.write(downloaded_file)
            temp_file.flush()  # Ensure all data is written to disk
            temp_file_path = temp_file.name
            result_type = process_file(temp_file_path, task_id, original_file_name=message.document.file_name)
            update_task_type_by_id(task_id, result_type)
            update_task_status_by_id(task_id, TaskStatuses.READY_FOR_PROCESSING)
            position_in_queue = get_count_task_in_queue()
            bot.reply_to(message,
                         f"Ваш {result_type} был сохранён, результат придёт после обработки.\nВы {position_in_queue}-й в очереди.\nID задачи: {task_id}")
    except UnsupportedFileTypeError as e:
        logger.error(f"Unsupported file type for user {user_id}.\nError: {e}")
        update_task_status_by_id(task_id, TaskStatuses.FAILED)
        bot.reply_to(message, str(e))
    except Exception as e:
        logger.error(f"Error while processing file for user {user_id}.\nError: {e}")
        update_task_status_by_id(task_id, TaskStatuses.FAILED)
        bot.reply_to(message, "Произошла ошибка при обработке файла.")


@bot.message_handler(commands=['start'])
def start_message(message):
    bot.reply_to(message, "Привет! Я бот для проверки проектов. Отправьте мне архив для обработки.")


@bot.message_handler(func=lambda message: True)
def unknown_command(message):
    bot.reply_to(message, "Я не знаю, что делать с этим. Пожалуйста, отправьте мне файл или архив для обработки.")


if __name__ == '__main__':
    print("Bot started")
    bot.infinity_polling()
