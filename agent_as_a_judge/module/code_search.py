"""
DevCodeSearch: A class for searching and displaying code snippets and their metadata.
"""

import os
import io
import json
import pickle
import logging
import numpy as np
from typing import List, Dict, Any, Generator, Union
import networkx as nx
import spacy
from dotenv import load_dotenv
from pathlib import Path
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer, util
from rich.logging import RichHandler
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree
from rich.text import Text
from rich.syntax import Syntax

console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[RichHandler()],
)


class DevCodeSearch:
    def __init__(self, judge_path: str, setting: str = None):
        self.judge_path = Path(judge_path)
        self.graph_file = self.judge_path / "graph.pkl"
        self.tags_file = self.judge_path / "tags.json"
        self.structure_file = self.judge_path / "tree_structure.json"
        self.setting = setting

        self.workspace = self.load_workspace()
        self.graph = self.load_graph()
        self.tags = self.load_tags()
        self.structure = self.load_structure()
        self.tree = self.load_tree()
        self.spacy_nlp = None
        self.bm25 = None
        self.embedding_model = SentenceTransformer("/workspace-SR003.nfs2/all-MiniLM-L6-v2")
        self.code_embeddings = None

    def search(
        self, query: str, search_type: str = "embedding", **kwargs
    ) -> List[Dict[str, Any]]:

        if search_type == "accurate":
            return list(self.accurate_search(query=query, **kwargs))
        elif search_type == "fuzzy":
            return self.fuzzy_search(query=query, threshold=kwargs.get("threshold", 70))
        elif search_type == "bm25":
            return self.bm25_search(query=query, top_n=kwargs.get("top_n", 3))
        elif search_type == "embedding":
            return self.embed_search(query=query, top_n=kwargs.get("top_n", 10))
        else:
            raise ValueError(f"Unsupported search_type: {search_type}")

    @property
    def nlp(self):

        if self.spacy_nlp is None:
            self.spacy_nlp = spacy.load("en_core_web_sm")
        return self.spacy_nlp

    def load_graph(self) -> nx.MultiDiGraph:

        try:
            with open(self.graph_file, "rb") as f:
                return pickle.load(f)
        except (FileNotFoundError, EOFError) as e:
            logging.warning(f"Failed to load graph: {e}")
            return nx.MultiDiGraph()
        except Exception as e:
            logging.error(f"Unexpected error when loading graph: {e}")
            return nx.MultiDiGraph()

    def load_tags(self) -> List[Dict[str, Any]]:

        try:
            with open(self.tags_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.warning(f"Failed to load tags: {e}")
            return []

    def load_workspace(self) -> str:

        try:
            with open(self.structure_file, "r", encoding="utf-8") as f:
                structure_data = json.load(f)
                return structure_data.get("workspace", "")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.warning(f"Failed to load workspace: {e}")
            return ""

    def load_tree(self) -> str:

        def add_branch(tree: Tree, structure: Dict[str, Any]):
            for key, value in structure.items():
                if isinstance(value, dict):
                    branch = tree.add(f"{key}")
                    add_branch(branch, value)
                else:
                    file_label = (
                        f"[bold white]{key}[/bold white]"
                        if value
                        else f"[dim]{key}[/dim]"
                    )
                    tree.add(file_label)

        tree = Tree("[bold blue]Project Structure[/bold blue]")
        add_branch(tree, self.structure["tree_structure"])

        with io.StringIO() as buf:
            temp_console = Console(file=buf, record=True)
            temp_console.print(tree)
            return temp_console.export_text()

    def load_structure(self) -> Dict[str, Any]:

        try:
            with open(self.structure_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.warning(f"Failed to load structure: {e}")
            return {}

    def accurate_search(
        self, query: str = None, **kwargs: Union[str, int]
    ) -> Generator[Dict[str, Any], None, None]:

        if kwargs:
            for tag in self.tags:
                match = all(
                    value.lower() in tag.get(key, "").lower()
                    for key, value in kwargs.items()
                )
                if match:
                    yield tag
        elif query:
            for tag in self.tags:
                if any(
                    query.lower() in tag.get(field, "").lower()
                    for field in ["name", "category", "identifier", "details"]
                ):
                    yield tag

    def fuzzy_search(self, query: str, threshold: int = 70) -> List[Dict[str, Any]]:
        """Perform a fuzzy search on all tags and return results above the threshold."""
        from fuzzywuzzy import fuzz

        query = query.lower()
        results = [
            tag
            for tag in self.tags
            if max(
                fuzz.partial_ratio(query, tag.get("name", "").lower()),
                fuzz.partial_ratio(query, tag.get("details", "").lower()),
                fuzz.partial_ratio(query, tag.get("category", "").lower()),
                fuzz.partial_ratio(query, tag.get("identifier", "").lower()),
            )
            >= threshold
        ]
        return results

    def bm25_search(self, query: str, top_n: int = 10) -> List[Dict[str, Any]]:

        if not self.tags:
            logging.warning("No tags available for BM25 search.")
            return []
        if self.bm25 is None:
            self.corpus = [
                [
                    token.text.lower()
                    for token in self.nlp(
                        tag.get("name", "")
                        + " "
                        + tag.get("details", "")
                        + " "
                        + tag.get("category", "")
                        + " "
                        + tag.get("identifier", "")
                    )
                    if not token.is_stop and not token.is_punct
                ]
                for tag in self.tags
            ]
            self.bm25 = BM25Okapi([doc for doc in self.corpus])
        tokenized_query = [
            token.text.lower()
            for token in self.nlp(query)
            if not token.is_stop and not token.is_punct
        ]
        scores = self.bm25.get_scores(tokenized_query)
        top_n_indices = np.argsort(scores)[-top_n:][::-1]
        return [self.tags[i] for i in top_n_indices]

    def embed_search(self, query: str, top_n: int = 3) -> List[Dict[str, Any]]:

        if self.code_embeddings is None:
            logging.info("Generating code embeddings for the first time...")
            self.code_embeddings = self._generate_code_embeddings()

        if len(self.code_embeddings) == 0:
            logging.error("No code embeddings available for search.")
            return []

        query_embedding = self.embedding_model.encode(query, convert_to_tensor=True)
        similarities = util.pytorch_cos_sim(query_embedding, self.code_embeddings)
        actual_top_n = min(top_n, similarities.size(1))
        if actual_top_n == 0:
            logging.error("No valid embeddings found to compare with.")
            return []

        top_results = similarities.topk(actual_top_n)
        return [self.tags[i] for i in top_results.indices.tolist()[0]]

    def _generate_code_embeddings(self):

        code_texts = [tag.get("details", "") for tag in self.tags]
        return self.embedding_model.encode(code_texts, convert_to_tensor=True)

    def display(
        self,
        tag: Dict[str, Any],
        theme="monokai",
        display_type="snippet",
        context_lines=5,
    ) -> str:

        display_function = {
            "snippet": self._display_snippet,
            "file": self._display_file,
            "context": lambda tag, theme: self._display_context(
                tag, theme, context_lines
            ),
        }.get(display_type)

        with io.StringIO() as buf:
            console = Console(file=buf, width=120, record=True)
            console.print(display_function(tag, theme))
            return buf.getvalue()

    def _display_snippet(
        self, tag: Dict[str, Any], theme="monokai"
    ) -> Union[Panel, None]:

        start_line = tag["line_number"][0]
        syntax = Syntax(
            tag["details"],
            "python",
            theme=theme,
            line_numbers=True,
            start_line=start_line,
        )
        metadata = self._generate_metadata(tag)
        table = Table.grid(expand=True)
        table.add_column(justify="left")
        table.add_row(metadata)
        table.add_row(syntax)
        return Panel(
            table,
            title="[bold magenta]Code Snippet[/bold magenta]",
            border_style="bold blue",
            padding=(1, 2),
        )

    def _display_file(self, tag: Dict[str, Any], theme="monokai") -> str:

        with open(tag["fname"], "r", encoding="utf-8") as file:
            code_content = file.read()
        syntax = Syntax(code_content, "python", theme=theme, line_numbers=True)
        metadata = self._generate_metadata(tag)
        table = Table.grid(expand=True)
        table.add_column(justify="left")
        table.add_row(metadata)
        table.add_row(syntax)
        return Panel(
            table,
            title="[bold magenta]Complete File[/bold magenta]",
            border_style="bold blue",
            padding=(1, 2),
        ).renderable

    def _display_context(
        self, tag: Dict[str, Any], theme="monokai", context_lines: int = 5
    ) -> str:

        start_line = max(tag["line_number"][0] - context_lines, 1)
        end_line = tag["line_number"][1] + context_lines
        with open(tag["fname"], "r", encoding="utf-8") as file:
            code_lines = file.readlines()
        code_snippet = "".join(code_lines[start_line - 1 : end_line])
        syntax = Syntax(
            code_snippet,
            "python",
            theme=theme,
            line_numbers=True,
            start_line=start_line,
        )
        metadata = self._generate_metadata(
            tag, start_line=start_line, end_line=end_line
        )
        table = Table.grid(expand=True)
        table.add_column(justify="left")
        table.add_row(metadata)
        table.add_row(syntax)
        return Panel(
            table,
            title="[bold magenta]Code Context[/bold magenta]",
            border_style="bold blue",
            padding=(1, 2),
        ).renderable

    def _generate_metadata(
        self, tag: Dict[str, Any], start_line: int = None, end_line: int = None
    ) -> Text:

        line_info = (
            f"{tag['line_number']}"
            if start_line is None or end_line is None
            else f"{start_line}-{end_line}"
        )
        return Text.from_markup(
            f"[bold cyan]File:[/bold cyan] [bold white]{tag['fname']}[/bold white]\n"
            f"[bold cyan]Lines:[/bold cyan] [bold white]{line_info}[/bold white]\n"
            f"[bold cyan]Identifier:[/bold cyan] [bold white]{tag['identifier']}[/bold white]\n"
            f"[bold cyan]Category:[/bold cyan] [bold white]{tag['category']}[/bold white]\n"
        )

    def get_complete_code(self, file_path: str) -> str:

        try:
            with open(file_path, "r", encoding="utf-8") as file:
                return file.read()
        except FileNotFoundError:
            logging.error(f"File not found: {file_path}")
            return ""

    def get_files(self) -> Dict[str, Any]:

        return {"structure": self.structure, "tree": self.tree}

    def get_workspace(self) -> Path:

        return self.workspace

    def get_filepaths(self) -> List[str]:

        return [tag["fname"] for tag in self.tags]

    def display_tree(self, max_depth: int = None) -> None:

        def add_branch(tree: Tree, structure: Dict[str, Any], current_depth: int):
            if max_depth is not None and current_depth > max_depth:
                return
            for key, value in structure.items():
                branch = (
                    tree.add(f"{key}")
                    if isinstance(value, dict)
                    else tree.add(
                        f"[bold white]{key}[/bold white]"
                        if value
                        else f"[dim]{key}[/dim]"
                    )
                )
                if isinstance(value, dict):
                    add_branch(branch, value, current_depth + 1)

        tree = Tree("[bold blue]Project Structure[/bold blue]")
        add_branch(tree, self.structure["tree_structure"], current_depth=0)
        metadata = Text.from_markup(
            f"[bold cyan]Tree Structure File:[/bold cyan] [bold white]{self.structure_file}[/bold white]\n"
            f"[bold cyan]Workspace Path:[/bold cyan] [bold white]{self.workspace}[/bold white]\n"
            f"[bold cyan]Total Nodes:[/bold cyan] [bold white]{len(self.structure['tree_structure'])}[/bold white]\n"
        )
        table = Table.grid(expand=True)
        table.add_column(justify="left")
        table.add_row(metadata)
        table.add_row(tree)

        console.print(
            Panel(
                table,
                title="[bold magenta]Project Tree[/bold magenta]",
                border_style="bold blue",
                padding=(1, 2),
            )
        )


if __name__ == "__main__":

    load_dotenv()
    workspace_path = (
        Path(os.getenv("PROJECT_DIR"))
        / "benchmark/workspace/OpenHands/39_Drug_Response_Prediction_SVM_GDSC_ML"
    )
    judge_dir = (
        Path(os.getenv("PROJECT_DIR"))
        + "/benchmark/judgement/OpenHands/39_Drug_Response_Prediction_SVM_GDSC_ML"
    )
    judge_dir.mkdir(parents=True, exist_ok=True)
    dev_search = DevCodeSearch(judge_dir)

    query = "The FashionMnist datset is loaded in `src/data_loader.py`."
    search_results = dev_search.embed_search(query)

    string_list = [
        dev_search.display(result, display_type="context", context_lines=2)
        for result in search_results
    ]

    for string in string_list:
        print(string)
