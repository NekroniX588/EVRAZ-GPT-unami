def get_text_retrieve_prompt(criteria: str, long_context: str) -> str:

    return f"""
        Below is a log of actions, steps, and file operations:
        {long_context}

        Summarize concise evidence directly related to the following criteria:
        {criteria}

        Focus on the last one or two mentions of relevant files or actions. Since I can check the files locally, omit file existence and content details. Provide a brief analysis of the latest status of relevant files or functions. Exclude irrelevant information.
        """
