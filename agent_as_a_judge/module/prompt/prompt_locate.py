def get_prompt_locate(criteria: str, workspace_info: str) -> str:

    demonstration = """
Example:
Suppose the criteria is:
'The database functionality is implemented in `src/db.py`, and the logging system is defined in `src/logging.py`.'

And the workspace information is:
/project
├── src
│   ├── db.py
│   ├── logging.py
│   ├── utils.py
└── tests
    ├── test_db.py
    └── test_logging.py

Based on the criteria, the following paths (no more than 5) should be returned, each wrapped in dollar signs (`$`):
$/project/src/db.py$
$/project/src/logging.py$
    """

    return f"""
Provided below is the structure of the workspace:
{workspace_info}

This is the criteria related to the task:
{criteria}

Follow the format in the example below and return only the file paths that match the criteria:
{demonstration}
    """
