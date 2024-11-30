import time
import traceback

from loguru import logger

from bot.sql_processor import get_task_by_status, update_task_result_by_id, update_task_status_by_id
from bot.task_statuses import TaskStatuses
from bot.settings import settings

from scripts.run import main

def get_task() -> str | None:
    task = get_task_by_status(TaskStatuses.READY_FOR_PROCESSING)
    if task:
        return task[0]
    return


def get_path_to_project(task_id: str) -> str:
    return settings.path_to_projects + task_id


def write_result(task_id: str, result: str) -> None:
    update_task_result_by_id(task_id, result)
    update_task_status_by_id(task_id, TaskStatuses.DONE)


def mock_work_for_task(path_to_project: str) -> str:
    print(path_to_project)
    output_path = main(path_to_project)
    print("PATH", output_path)
    return str(output_path)


def worker():
    while True:
        task_id = get_task()
        if task_id:
            path_to_project = get_path_to_project(task_id)
            logger.info(f"Processing task {task_id}")

            try:
                result = mock_work_for_task(path_to_project)  # TODO: Implement real work instead of mock
                write_result(task_id, result)
            except Exception as e:
                logger.error(f"Error while processing task {task_id}. Error: {e}. Traceback {traceback.format_exc()}")
                update_task_status_by_id(task_id, TaskStatuses.FAILED)
                continue

            logger.info(f"Task {task_id} done")
        else:
            logger.info("No tasks found")
            time.sleep(10)


worker()
