import os
import shutil

from pathlib import Path
from zipfile import ZipFile

from bot.settings import settings

class UnsupportedFileTypeError(Exception):
    pass

def __move_file(file_path: str, destination_path: str, original_file_name: str) -> None:
    source = Path(file_path)
    destination = Path(destination_path)

    # Move the file
    shutil.move(str(source), str(destination / original_file_name))


def __create_dir(dir_name: str, path_for_dir: str) -> None:
    try:
        os.mkdir(path_for_dir)
    except FileExistsError:
        pass
    try:
        os.mkdir(path_for_dir + dir_name)
    except FileExistsError:
        pass


def __unzip_file(zip_file_path: str, destination_path: str) -> None:
    with ZipFile(zip_file_path, 'r') as archive:
        archive.extractall(destination_path)


def process_file(file_path: str, task_id: str, original_file_name: str) -> str:
    __create_dir(task_id, settings.path_to_projects)

    if file_path.endswith('.zip'):
        __unzip_file(file_path, settings.path_to_projects + task_id)
        return "archive"

    # elif file_path.split('.')[-1] in ['py', 'ts', 'cs']:  # TODO: Add filter for file types like .py, .ts and etc.
    #     __move_file(file_path, settings.path_to_projects + task_id, original_file_name)
    #     return "file"
    else:
        raise UnsupportedFileTypeError("Мы поддерживаем только форматы файлов: zip")
