# Команда Мастер на GPT-унами

# Запуск

## Установка библиотек

```
conda create -n aaaj_evraz python=3.11
conda activate aaaj_evraz
pip install poetry
poetry install
```

## Запуск бота
Далее в 3-х терминалах нужно запустить 3 скрипта:

- Запуск телеграмм бота на получение сообщений `python tg_bot.py`
- Запуск процесса обработки полученных сообщений `python review_worker.py`
- Запуск процесса отправки результатам в телеграм `python sender_worker.py`

