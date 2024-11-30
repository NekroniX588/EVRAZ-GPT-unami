def get_system_prompt_locate(language="English"):

    if language == "English":
        return """
You are an advanced AI system specializing in understanding project structures and determining file locations based on provided criteria.
Your task is to locate specific files in the workspace based on the user's criteria and workspace information.
        """
    else:
        raise NotImplementedError(f"The language '{language}' is not supported.")
