import time
import requests

from loguru import logger

from bot.sql_processor import get_task_by_status, update_task_status_by_id
from bot.task_statuses import TaskStatuses
from bot.settings import settings


def send_telegram_message(user_id: int, file: str, bot_token: str):
    """
    Sends a file as a message to a Telegram user.

    Args:
        user_id (int): Telegram user ID to send the message to.
        file (str): Path to the file to send.
        bot_token (str): Telegram bot API token.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"

    try:
        with open(file, 'rb') as f:
            response = requests.post(url, data={'chat_id': user_id}, files={'document': f})

        if response.status_code == 200:
            logger.info("Message sent successfully!")
        else:
            logger.error(f"Failed to send message: {response.status_code} - {response.text}")
    except FileNotFoundError:
        logger.error(f"File '{file}' not found.")
    except Exception as e:
        logger.exception(f"An error occurred: {e}")


def get_task() -> tuple[str | None, str | None, str | None]:
    task = get_task_by_status(TaskStatuses.DONE)
    if task:
        return task[0], task[2], task[4]
    return None, None, None


def worker():
    while True:
        task_id, user_id, result = get_task()
        if task_id and user_id and result:
            try:
                logger.info(f"Sending message for task {task_id}")
                send_telegram_message(user_id, result, settings.tg_token)
                update_task_status_by_id(task_id, TaskStatuses.SENT)
                logger.info(f"Task {task_id} done")
            except Exception as e:
                logger.error(f"Error while sending message for task {task_id}. Error: {e}")
                update_task_status_by_id(task_id, TaskStatuses.FAILED)
                continue
        else:
            logger.info("No tasks found")
            time.sleep(10)

worker()