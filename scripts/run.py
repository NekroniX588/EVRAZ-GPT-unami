import os
import re
import json
import shutil
import logging

from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from collections import Counter

from agent_as_a_judge.agent import JudgeAgent
from agent_as_a_judge.config import AgentConfig


logger = logging.getLogger(__name__)


def generate_markdown_report(json_data, output_file_path):
    project_name = json_data["name"]
    current_date = datetime.utcnow().strftime("%d.%m.%Y %H:%M:%S UTC")

    total_issues = sum(1 for stat in json_data["judge_stats"] if not stat["satisfied"])
    struct_issues = sum(
        1 for stat in json_data["judge_stats"] if stat["category"].startswith("Структура")
    )
    code_issues = sum(
        1 for stat in json_data["judge_stats"] if stat["category"].startswith("Код")
    )
    other_issues = total_issues - struct_issues - code_issues

    report = f"## Анализ проекта ```{project_name}``` от {current_date}\n"
    report += "---\n"
    report += f"Дата последнего изменения проекта : {current_date}\n\n"
    report += f"Общее количество ошибок: {total_issues}\n"
    report += f"Структурных нарушений: {struct_issues}\n"
    report += f"Нарушений в написании кода: {code_issues}\n"
    report += f"Иных нарушений (в бизнес-логике, в зависимостях и т.п.): {other_issues}\n\n"

    for idx, stat in enumerate(json_data["judge_stats"], start=1):
        if not stat["satisfied"]:
            report += f"### Нарушение {idx}\n"
            report += f"> Критерий: {stat['criteria']}\n\n"
            report += "> **Описание проблемы:**\n"
            for reason in stat["llm_stats"]["reason"]:
                report += f"> {reason}\n\n"
            report += f"**Общее время анализа:** {round(stat['total_time'], 1)} секунд\n\n"

    with open(output_file_path, "w", encoding="utf-8") as f:
        f.write(report)


def detect_language(directory):
    # Счетчик для хранения количества каждого расширения
    extensions_counter = Counter()

    # Перебор файлов в указанной папке
    for root, dirs, files in os.walk(directory):
        for file in files:
            # Получение расширения файла
            _, ext = os.path.splitext(file)
            if ext:  # Учитываем только файлы с расширением
                extensions_counter[ext.lower()] += 1

    for item in extensions_counter.most_common():
        if item[0] == '.ts':
            return 'typescript'
        if item[0] == '.cs':
            return 'csharp'
        if item[0] == '.py':
            return 'python'
    
    return 'python'


def main(input_path):

    load_dotenv()

    language = detect_language(input_path)

    benchmark_dir = Path('/home/jovyan/finogeev/bot/agent-as-a-judge/benchmark')
    instance_dir = benchmark_dir / "devai/instances"
    workspace_dir = benchmark_dir / f"workspaces/Evraz"
    judge_dir = (
        benchmark_dir
        / f"judgment/Evraz/agent_as_a_judge/gray_box"
    )
    
    if not workspace_dir.exists():
        workspace_dir.mkdir(parents=True)

    if judge_dir.exists():
        shutil.rmtree(judge_dir)
    
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir)
    
    shutil.copytree(input_path, workspace_dir / language)
    print(workspace_dir / language)

    agent_config = AgentConfig(
        include_dirs=["src", "results", "models", "data"],
        exclude_dirs=["__pycache__", "env", ".git", "venv", "logs", "output", "tmp", "temp", "cache", "data"],
        exclude_files=[".DS_Store"],
        setting='gray_box',
        planning='planning',
        judge_dir=judge_dir,
        workspace_dir=workspace_dir,
        instance_dir=instance_dir,
        trajectory_file=None,
    )

   
    instance_file = Path("/home/jovyan/finogeev/bot/agent-as-a-judge/benchmark/devai/instances") / (language + '.json')

    logger.info(f"Instance_file: {instance_file}")

    instance_name = instance_file.stem

    judgment_file = agent_config.judge_dir / instance_file.name

    workspace = agent_config.workspace_dir / instance_name

    print('workspace', workspace)

    judge_agent = JudgeAgent(
        workspace=workspace,
        instance=instance_file,
        judge_dir=agent_config.judge_dir,
        config=agent_config,
    )
    judge_agent.judge_anything()

    # Generate report for the current judgment file
    logger.info(f"Generating report for {judgment_file}")
    output_report_path = agent_config.judge_dir / f"{instance_name}_review.md"

    with open(judgment_file, "r", encoding="utf-8") as f:
        json_data = json.load(f)

    generate_markdown_report(json_data, output_report_path)
    logger.info(f"Report generated at {output_report_path}")

    return output_report_path