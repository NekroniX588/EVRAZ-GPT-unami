import logging
from pathlib import Path
from typing import List
from rich.logging import RichHandler
from agent_as_a_judge.module.graph import DevGraph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[RichHandler()],
)


class DevStatistics:

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def count_lines_of_code(self, filepaths: List[Path]) -> (int, int):

        total_lines = 0
        total_files = 0

        for filepath in filepaths:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    total_lines += len(lines)
                    total_files += 1
            except Exception as e:
                logging.warning(f"Failed to process file {filepath}: {e}")

        return total_lines, total_files

    def calculate_statistics(self):

        if self.workspace.exists():
            logging.info(f"Processing workspace: {self.workspace.stem}")

            dev_graph = DevGraph(
                root=str(self.workspace),
                include_dirs=["src", "results", "models"],
                exclude_dirs=["__pycache__", "env"],
                exclude_files=[".DS_Store"],
            )

            code_files = dev_graph.list_code_files([self.workspace])
            all_files = dev_graph.list_all_files(self.workspace)
            lines_in_workspace, files_in_workspace = self.count_lines_of_code(code_files)
            total_files_in_workspace = len(all_files)
            total_non_code_files_in_workspace = (
                total_files_in_workspace - files_in_workspace
            )

            logging.info(f"  Total files: {total_files_in_workspace}")
            logging.info(f"  Non-code files: {total_non_code_files_in_workspace}")
            logging.info(f"  Code files: {files_in_workspace}")
            logging.info(f"  Lines of code: {lines_in_workspace}")

            return (
                total_files_in_workspace,
                total_non_code_files_in_workspace,
                files_in_workspace,
                lines_in_workspace,
            )

        else:
            logging.warning(
                f"Workspace '{self.workspace.stem}' does not exist. Skipping..."
            )
            return 0, 0, 0, 0
