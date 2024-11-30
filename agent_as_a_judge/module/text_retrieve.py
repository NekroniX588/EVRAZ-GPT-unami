import os
import io
import json
import logging
import time
from typing import List, Dict, Any, Union
import spacy
from pathlib import Path
from rapidfuzz import fuzz
from rank_bm25 import BM25Okapi
import numpy as np
from sentence_transformers import SentenceTransformer, util
from agent_as_a_judge.llm.provider import LLM
from agent_as_a_judge.module.prompt.system_prompt_retrieve import (
    get_retrieve_system_prompt,
)
from agent_as_a_judge.module.prompt.prompt_retrieve import get_text_retrieve_prompt
from agent_as_a_judge.utils import truncate_string
from rich.logging import RichHandler
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

# Setup logging
console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[RichHandler()],
)


class DevTextRetrieve:
    def __init__(self, trajectory_file: str):
        self.trajectory_file = Path(trajectory_file)
        self.raw_trajectory_data = self.load_trajectory_data()
        self.text_data = self.process_trajectory_data()
        self.spacy_nlp = None
        self.bm25 = None
        self.embedding_model = SentenceTransformer("/workspace-SR003.nfs2/all-MiniLM-L6-v2")
        self.text_embeddings = None
        self.llm = LLM(
            model=os.getenv("DEFAULT_LLM"), api_key=os.getenv("OPENAI_API_KEY"), base_url="http://0.0.0.0:30000/v1"
        )

    @property
    def _spacy(self):
        if self.spacy_nlp is None:
            self.spacy_nlp = spacy.load("en_core_web_sm")
        return self.spacy_nlp

    def load_trajectory_data(self) -> List[Dict[str, Any]]:

        try:
            with open(self.trajectory_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.warning(f"Failed to load trajectory data: {e}")
            return []

    def process_trajectory_data(self) -> List[Dict[str, Any]]:

        processed_data = []

        for entry in self.raw_trajectory_data:
            content_parts = []

            # Extract relevant fields and truncate if necessary
            step = entry.get("step")
            if step is not None:
                content_parts.append(f"Step: {step}")

            user_message = entry.get("user_message", "")
            if user_message:
                truncated_message = truncate_string(
                    user_message,
                    model=os.getenv("DEFAULT_LLM"),
                    max_tokens=300,
                    drop_mode="middle",
                )
                content_parts.append(f"User Message: {truncated_message}")

            agent_info = entry.get("agent", {})
            agent_name = agent_info.get("agent_name", "Default")
            action = truncate_string(
                agent_info.get("action", ""),
                model=os.getenv("DEFAULT_LLM"),
                max_tokens=50,
                drop_mode="middle",
            )
            thought = truncate_string(
                agent_info.get("thought", ""),
                model=os.getenv("DEFAULT_LLM"),
                max_tokens=100,
                drop_mode="middle",
            )
            content_parts.append(f"Agent Name: {agent_name}")
            content_parts.append(f"Action: {action}")
            content_parts.append(f"Thought: {thought}")

            environment = entry.get("environment", "")
            if environment:
                truncated_environment = truncate_string(
                    environment,
                    model=os.getenv("DEFAULT_LLM"),
                    max_tokens=100,
                    drop_mode="middle",
                )
                content_parts.append(f"Environment: {truncated_environment}")

            # Create processed entry
            processed_entry = {
                "content": "\n".join(content_parts),
                "title": f"Step {step}" if step is not None else "Untitled",
                "source": "Trajectory Data",
            }
            processed_data.append(processed_entry)

        return processed_data

    def search(
        self, query: str, search_type: str = "embedding", **kwargs
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:

        if search_type == "accurate":
            return self.accurate_search(query=query, **kwargs)
        elif search_type == "fuzzy":
            return self.fuzzy_search(query=query, threshold=kwargs.get("threshold", 70))
        elif search_type == "bm25":
            return self.bm25_search(query=query, top_n=kwargs.get("top_n", 5))
        elif search_type == "embedding":
            return self.embedding_search(query=query, top_n=kwargs.get("top_n", 10))
        elif search_type == "llm_summary":
            return self.llm_summary(criteria=query)
        else:
            raise ValueError(f"Unsupported search_type: {search_type}")

    def accurate_search(self, query: str = None, **kwargs) -> List[Dict[str, Any]]:

        results = []
        for text_entry in self.text_data:
            if kwargs:
                match = all(
                    value.lower() in text_entry.get(key, "").lower()
                    for key, value in kwargs.items()
                )
                if match:
                    results.append(text_entry)
            elif query:
                if query.lower() in text_entry.get("content", "").lower():
                    results.append(text_entry)
        return results

    def fuzzy_search(self, query: str, threshold: int = 70) -> List[Dict[str, Any]]:

        return [
            entry
            for entry in self.text_data
            if fuzz.partial_ratio(query.lower(), entry.get("content", "").lower())
            >= threshold
        ]

    def bm25_search(self, query: str, top_n: int = 5) -> List[Dict[str, Any]]:

        if not self.text_data:
            logging.warning("No text data available for BM25 search.")
            return []

        if self.bm25 is None:
            self.corpus = [
                [
                    token.text.lower()
                    for token in self._spacy(entry.get("content", ""))
                    if not token.is_stop and not token.is_punct
                ]
                for entry in self.text_data
            ]
            self.bm25 = BM25Okapi(self.corpus)

        tokenized_query = [
            token.text.lower()
            for token in self._spacy(query)
            if not token.is_stop and not token.is_punct
        ]
        scores = self.bm25.get_scores(tokenized_query)
        top_n_indices = np.argsort(scores)[::-1][:top_n]
        return [self.text_data[i] for i in top_n_indices]

    def embedding_search(self, query: str, top_n: int = 5) -> List[Dict[str, Any]]:

        if self.text_embeddings is None:
            self.text_embeddings = self._generate_text_embeddings()

        query_embedding = self.embedding_model.encode(query, convert_to_tensor=True)
        similarities = util.pytorch_cos_sim(query_embedding, self.text_embeddings)[0]
        top_n_indices = similarities.topk(k=top_n)[1]
        return [self.text_data[i] for i in top_n_indices]

    def _generate_text_embeddings(self):

        texts_content = [entry.get("content", "") for entry in self.text_data]
        return self.embedding_model.encode(texts_content, convert_to_tensor=True)

    def llm_summary(self, criteria: str) -> Dict[str, Any]:

        llm_stats = self.summary(criteria, self.text_data)
        llm_stats["trajectory_analysis"] = self.display_summary(llm_stats)
        return llm_stats

    def summary(self, criteria: str, json_data: List[Dict[str, Any]]) -> Dict[str, Any]:

        combined_text = "\n".join([item.get("content", "") for item in json_data])
        combined_text = truncate_string(
            combined_text,
            model=os.getenv("DEFAULT_LLM"),
            max_tokens=10000,
            drop_mode="head",
        )

        system_prompt = get_retrieve_system_prompt(language="English")
        prompt = get_text_retrieve_prompt(criteria=criteria, long_context=combined_text)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        return self.llm._llm_inference(messages)

    def _llm_inference(self, messages: list) -> Dict[str, Any]:

        start_time = time.time()
        response, cost, accumulated_cost = self.llm.do_completion(
            messages=messages, max_tokens=300, temperature=0.0
        )
        inference_time = time.time() - start_time

        return {
            "llm_response": response.choices[0].message["content"],
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "cost": cost,
            # "accumulated_cost": accumulated_cost,
            "inference_time": inference_time,
        }

    def display(self, text_entries: List[Dict[str, Any]]) -> str:

        output_str = ""
        for entry in text_entries:
            table = Table.grid(expand=True)
            table.add_column(justify="left")
            table.add_row(self._generate_metadata(entry))
            table.add_row(Text(entry.get("content", "")))

            panel = Panel(
                table,
                title="[bold magenta]Text Block[/bold magenta]",
                border_style="bold blue",
                title_align="left",
                padding=(1, 2),
            )

            with io.StringIO() as buf:
                temp_console = Console(file=buf, width=80, record=True)
                temp_console.print(panel)
                output_str += buf.getvalue()

        return output_str

    def display_summary(self, llm_stats: Dict[str, Any]) -> str:

        summary = llm_stats.get("llm_response", "")
        notice = "The following environment feedback is provided for reference only and does not serve as decisive evidence."
        panel = Panel(
            Text(notice + "\n\n" + summary),
            title="[bold magenta]Relevant Steps in Trajectory[/bold magenta]",
            border_style="bold blue",
            title_align="left",
            padding=(1, 2),
        )

        with io.StringIO() as buf:
            temp_console = Console(file=buf, width=80, record=True)
            temp_console.print(panel)
            return buf.getvalue()

    def _generate_metadata(self, text_entry: Dict[str, Any]) -> Text:

        source = text_entry.get("source", "Unknown")
        title = text_entry.get("title", "Untitled")
        return Text.from_markup(
            f"[bold cyan]Title:[/bold cyan] [bold white]{title}[/bold white]\n[bold cyan]Source:[/bold cyan] [bold white]{source}[/bold white]\n"
        )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    trajectory_file = (
        Path(os.getenv("PROJECT_DIR"))
        + "/benchmark/trajectories/OpenHands/39_Drug_Response_Prediction_SVM_GDSC_ML.json"
    )
    dev_text_search = DevTextRetrieve(trajectory_file)

    # Criteria for LLM summary
    criteria = "Explain how the data preprocessing is implemented in the project."
    llm_stats = dev_text_search.search(query=criteria, search_type="llm_summary")
    summary_output = dev_text_search.display_summary(llm_stats)
    print(summary_output)
