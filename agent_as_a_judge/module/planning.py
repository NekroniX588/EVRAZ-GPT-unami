import os
import re
import time
import logging
from agent_as_a_judge.llm.provider import LLM
from dotenv import load_dotenv
from rich.logging import RichHandler
from agent_as_a_judge.module.prompt.system_prompt_planning import (
    get_planning_system_prompt,
)
from agent_as_a_judge.module.prompt.prompt_planning import get_planning_prompt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[RichHandler()],
)
load_dotenv()


class Planning:
    def __init__(self):
        self.llm = LLM(
            model=os.getenv("DEFAULT_LLM"), api_key=os.getenv("OPENAI_API_KEY"), base_url="http://0.0.0.0:30000/v1"
        )

    def generate_plan(self, criteria: str) -> dict:
        system_prompt = get_planning_system_prompt("English")  #
        user_prompt = get_planning_prompt(criteria)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        start_time = time.time()
        llm_stats = self._llm_inference(messages)
        llm_stats["inference_time"] = time.time() - start_time
        actions = self.parse_plan(llm_stats["llm_response"])

        return {"actions": actions, "llm_stats": llm_stats}

    def parse_plan(self, plan: str) -> list:
        actions = []
        action_patterns = {
            "user_query": r"\[User Query\]",
            "workspace": r"\[Workspace\]",
            "locate": r"\[Locate\]",
            "read": r"\[Read\]",
            "search": r"\[Search\]",
            "history": r"\[History\]",
            "trajectory": r"\[Trajectory\]",
        }

        for line in plan.splitlines():
            for action, pattern in action_patterns.items():
                if re.search(pattern, line, re.IGNORECASE):
                    actions.append(action)
                    break

        return actions

    def _llm_inference(self, messages: list) -> dict:

        response, cost, accumulated_cost = self.llm.do_completion(
            messages=messages, temperature=0.0
        )

        llm_response = response.choices[0].message["content"]
        input_token = response.usage.prompt_tokens
        output_token = response.usage.completion_tokens

        return {
            "llm_response": llm_response,
            "input_tokens": input_token,
            "output_tokens": output_token,
            "cost": cost,
            # "accumulated_cost": accumulated_cost
        }
