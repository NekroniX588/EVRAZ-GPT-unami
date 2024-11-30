def get_ask_prompt(question: str, evidence: str) -> str:

    return f"""
Provided below is relevant information about the project or context:
{evidence}

Kindly respond to the following user input:
{question}

As per the guidelines, provide a comprehensive answer referencing specific elements from the provided information where applicable.
    """
