import re
import argparse
import logging
from pathlib import Path
from dotenv import load_dotenv
import json
from datetime import datetime

from agent_as_a_judge.agent import JudgeAgent
from agent_as_a_judge.config import AgentConfig


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


def main(agent_config: AgentConfig, logger: logging.Logger):

    def extract_number_from_filename(filename: str) -> int:
        match = re.search(r"(\d+)", filename)
        return int(match.group(1)) if match else float("inf")

    instance_files = sorted(
        list(agent_config.instance_dir.glob("*.json")),
        key=lambda f: extract_number_from_filename(f.stem),
    )

    logger.info(f"Total instances found: {len(instance_files)}")

    for instance_file in instance_files:
        instance_name = instance_file.stem

        trajectory_file = None
        if agent_config.trajectory_file:
            trajectory_file = agent_config.trajectory_file / f"{instance_name}.json"

        judgment_file = agent_config.judge_dir / instance_file.name

        if judgment_file.exists():
            logger.info(
                f"Judgment for instance '{instance_name}' already exists. Skipping..."
            )
            continue

        if trajectory_file and trajectory_file.exists():
            logger.info(
                f"Processing instance: {instance_file} with trajectory: {trajectory_file}"
            )
        else:
            logger.warning(
                f"Trajectory file not found for instance: {instance_file}, processing without it"
            )
            trajectory_file = None

        workspace = agent_config.workspace_dir / instance_name

        judge_agent = JudgeAgent(
            workspace=workspace,
            instance=instance_file,
            judge_dir=agent_config.judge_dir,
            trajectory_file=trajectory_file,
            config=agent_config,
        )
        judge_agent.judge_anything()

        # Generate report for the current judgment file
        try:
            logger.info(f"Generating report for {judgment_file}")
            output_report_path = agent_config.judge_dir / f"{instance_name}_review.md"
            with open(judgment_file, "r", encoding="utf-8") as f:
                json_data = json.load(f)
            generate_markdown_report(json_data, output_report_path)
            logger.info(f"Report generated at {output_report_path}")
        except Exception as e:
            logger.error(f"Failed to generate report for {instance_file}: {e}")


def parse_arguments():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--developer_agent", type=str, required=True, help="Name of the developer agent"
    )
    parser.add_argument(
        "--setting",
        type=str,
        required=True,
        help="Setting for the JudgeAgent (e.g., gray_box, black_box)",
    )
    parser.add_argument(
        "--planning",
        type=str,
        required=True,
        choices=["planning", "comprehensive (no planning)", "efficient (no planning)"],
        help="Module to run",
    )
    parser.add_argument(
        "--benchmark_dir",
        type=str,
        required=True,
        help="Base directory for the DevAI benchmark",
    )
    parser.add_argument(
        "--include_dirs",
        nargs="+",
        default=["src", "results", "models", "data"],
        help="Directories to include in search",
    )
    parser.add_argument(
        "--exclude_dirs",
        nargs="+",
        default=[
            "__pycache__",
            "env",
            ".git",
            "venv",
            "logs",
            "output",
            "tmp",
            "temp",
            "cache",
            "data",
        ],
        help="Directories to exclude in search",
    )
    parser.add_argument(
        "--exclude_files",
        nargs="+",
        default=[".DS_Store"],
        help="Files to exclude in search",
    )
    parser.add_argument(
        "--trajectory_file",
        type=str,
        help="Path to the trajectory directory, if available",
    )

    return parser.parse_args()


if __name__ == "__main__":
    load_dotenv()

    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)
    args = parse_arguments()

    benchmark_dir = Path(args.benchmark_dir)
    instance_dir = benchmark_dir / "devai/instances"
    workspace_dir = benchmark_dir / f"workspaces/{args.developer_agent}"
    judge_dir = (
        benchmark_dir
        / f"judgment/{args.developer_agent}/agent_as_a_judge/{args.setting}"
    )
    trajectory_file = benchmark_dir / f"trajectories/{args.developer_agent}"

    agent_config = AgentConfig(
        include_dirs=args.include_dirs,
        exclude_dirs=args.exclude_dirs,
        exclude_files=args.exclude_files,
        setting=args.setting,
        planning=args.planning,
        judge_dir=judge_dir,
        workspace_dir=workspace_dir,
        instance_dir=instance_dir,
        trajectory_file=trajectory_file,
    )

    main(
        agent_config=agent_config,
        logger=logger,
    )
