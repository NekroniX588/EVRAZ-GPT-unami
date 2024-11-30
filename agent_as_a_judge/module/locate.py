import os
import time
import warnings
import logging
from dotenv import load_dotenv
from rich.logging import RichHandler
from agent_as_a_judge.llm.provider import LLM
from agent_as_a_judge.module.prompt.system_prompt_locate import get_system_prompt_locate
from agent_as_a_judge.module.prompt.prompt_locate import get_prompt_locate

warnings.simplefilter("ignore", category=FutureWarning)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[RichHandler()],
)


class DevLocate:
    def __init__(self):
        self.llm = self._initialize_llm()

    def _initialize_llm(self) -> LLM:
        model = os.getenv("DEFAULT_LLM")
        api_key = os.getenv("OPENAI_API_KEY")
        if not model or not api_key:
            raise ValueError(
                "DEFAULT_LLM or OPENAI_API_KEY not found in environment variables"
            )
        return LLM(model=model, api_key=api_key, base_url="http://0.0.0.0:30000/v1")

    def locate_file(self, criteria: str, workspace_info: str) -> dict:
        system_prompt = get_system_prompt_locate(language="English")
        prompt = get_prompt_locate(criteria=criteria, workspace_info=workspace_info)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        llm_stats = self._llm_inference(messages)
        file_paths = self._parse_locate(llm_stats["llm_response"].strip())

        logging.info(f"Located file paths: {file_paths}")

        return {
            "file_paths": file_paths[:5],  # Return up to 5 file paths
            "llm_stats": llm_stats,
        }

    def _parse_locate(self, response: str) -> list:
        file_paths = []
        for line in response.splitlines():
            cleaned_line = line.strip()

            if "$" in cleaned_line:
                file_paths.extend(self._extract_delimited_paths(cleaned_line))
            elif cleaned_line.startswith("/") or cleaned_line.startswith("."):
                file_paths.append(cleaned_line)

        return file_paths if file_paths else []

    def _extract_delimited_paths(self, line: str) -> list:
        return [
            path.strip()
            for path in line.split("$")
            if path.strip().startswith(("/", "."))
        ]

    def _llm_inference(self, messages: list) -> dict:
        start_time = time.time()

        response, cost, accumulated_cost = self.llm.do_completion(
            messages=messages, temperature=0.0
        )
        inference_time = time.time() - start_time

        llm_response = response.choices[0].message["content"]
        input_token = response.usage.prompt_tokens
        output_token = response.usage.completion_tokens

        return {
            "llm_response": llm_response,
            "input_tokens": input_token,
            "output_tokens": output_token,
            "cost": cost,
            # "accumulated_cost": accumulated_cost,
            "inference_time": inference_time,
        }


if __name__ == "__main__":
    load_dotenv()
    dev_locate = DevLocate()

    criteria_example = "Find the database file."
    workspace_info_example = """And the workspace information is:
/project
├── src
│   ├── db.py
│   ├── logging.py
│   ├── utils.py
└── tests
    ├── test_db.py
    └── test_logging.py"""

    try:
        result = dev_locate.locate_file(
            criteria=criteria_example, workspace_info=workspace_info_example
        )
        print(f"File paths: {result['file_paths']}")
        print(f"LLM Stats: {result['llm_stats']}")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
