# Команда Мастер на GPT-унами

# Запуск

## Запуск LLM

В качестве ЛЛМ мы использовали кантизованную до fp8 [Qwen/Qwen2.5-Coder-32B-Instruct](/guides/content/editing-an-existing-page)

Для её запуска использова `SGLang`



## Установка библиотек для 

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

