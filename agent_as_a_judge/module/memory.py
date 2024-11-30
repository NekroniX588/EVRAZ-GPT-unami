import os
import logging
import json
from pathlib import Path


class Memory:
    def __init__(self, memory_file: Path = None):

        self.judgments = []
        self.memory_file = memory_file

    def save_to_file(self):
        if not self.memory_file:
            logging.error("No memory file provided.")
            return

        try:
            with open(self.memory_file, "w") as file:
                json.dump({"judge_stats": self.judgments}, file, indent=4)
                logging.info(
                    f"Saved {len(self.judgments)} judgments to file '{self.memory_file}'."
                )
        except Exception as e:
            logging.error(f"Failed to save judgments to file '{self.memory_file}': {e}")

    def add_judgment(self, criteria: str, satisfied: bool, reason: list):
        new_judgment = {"criteria": criteria, "satisfied": satisfied, "reason": reason}
        self.judgments.append(new_judgment)
        logging.debug(
            f"Added new judgment for criteria: '{criteria}', Satisfied: {satisfied}"
        )

    def get_historical_evidence(self) -> str:

        if not os.path.exists(self.memory_file):
            logging.error(f"File '{self.memory_file}' not found.")
            return

        with open(self.memory_file, "r") as file:
            data = json.load(file)
            self.judgments = data.get("judge_stats", [])
            logging.info(
                f"Loaded {len(self.judgments)} judgments from file '{self.memory_file}'."
            )

        if not self.judgments:
            logging.warning("No historical judgments available.")
            return "No historical judgments available."

        historical_evidence = "\n".join(
            self._format_judgment(i, judgment)
            for i, judgment in enumerate(self.judgments, 1)
        )
        logging.info(f"Retrieved {len(self.judgments)} historical judgments.")
        return historical_evidence

    @staticmethod
    def _format_judgment(index: int, judgment: dict) -> str:
        criteria = judgment.get("criteria", "No criteria available")
        satisfied = "Yes" if judgment.get("satisfied") else "No"

        llm_stats = judgment.get("llm_stats", {})
        reasons = llm_stats.get("reason", [])

        if isinstance(reasons, list):
            formatted_reasons = (
                "\n      ".join(reasons) if reasons else "No reasoning provided"
            )
        else:
            formatted_reasons = reasons if reasons else "No reasoning provided"

        output = (
            f"\n{'-'*50}"
            f"\nRequirement {index}:"
            f"\n{'-'*50}"
            f"\nCriteria   : {criteria}"
            f"\nSatisfied  : {satisfied}"
            f"\nReason     :\n      {formatted_reasons}"
            f"\n{'-'*50}\n"
        )

        return output
