import sqlite3

from uuid import uuid4
from typing import Optional, Tuple

from bot.settings import settings
from bot.task_statuses import TaskStatuses


def __create_connection() -> sqlite3.Connection:
    return sqlite3.connect(settings.database_name)


def __generate_id() -> str:
    return str(uuid4())


# Create table if it doesn't exist
def __create_table() -> None:
    with __create_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            user_id TEXT NOT NULL,
            type TEXT,
            result TEXT
        )
        """)
        conn.commit()


__create_table()


# Insert a row into the table
def create_task(row_status: str, user_id: str) -> str:
    row_id = __generate_id()
    with __create_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
            INSERT INTO tasks (id, status, user_id)
            VALUES (?, ?, ?)
            """, (row_id, row_status, user_id))
            conn.commit()
            print("Row inserted successfully.")
            return row_id
        except sqlite3.IntegrityError:
            print("Error: Row with this ID already exists.")


# Get one row with a specific status
def get_task_by_status(status: str) -> Optional[Tuple[str, str, str, str, str]]:
    with __create_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM tasks
        WHERE status = ?
        LIMIT 1
        """, (status,))
        row = cursor.fetchone()
        return row  # Returns a tuple (id, status, user_id, type, result) or None


# Update row status by ID
def update_task_status_by_id(row_id: str, new_status: str) -> None:
    with __create_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE tasks
        SET status = ?
        WHERE id = ?
        """, (new_status, row_id))
        conn.commit()
        if cursor.rowcount > 0:
            print("Row updated successfully.")
        else:
            print("Error: No row found with the given ID.")


def update_task_type_by_id(row_id: str, new_type: str) -> None:
    with __create_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE tasks
        SET type = ?
        WHERE id = ?
        """, (new_type, row_id))
        conn.commit()
        if cursor.rowcount > 0:
            print("Row updated successfully.")
        else:
            print("Error: No row found with the given ID.")


def update_task_result_by_id(row_id: str, new_result: str) -> None:
    with __create_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE tasks
        SET result = ?
        WHERE id = ?
        """, (new_result, row_id))
        conn.commit()
        if cursor.rowcount > 0:
            print("Row updated successfully.")
        else:
            print("Error: No row found with the given ID.")


def get_count_task_in_queue() -> int:
    with __create_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE status in (?, ?, ?)
        """, (TaskStatuses.READY_FOR_PROCESSING, TaskStatuses.PROCESSING, TaskStatuses.NEW))
        row = cursor.fetchone()
        return row[0]


# # Example usage
# if __name__ == "__main__":
#     create_table()  # Ensure the table exists
#
#     # Insert example rows
#     insert_row("1", "type1", "active", "user123")
#     insert_row("2", "type2", "inactive", "user456")
#
#     # Get a row by status
#     print("Row with status 'active':", get_row_by_status("active"))
#
#     # Update row status
#     update_status_by_id("1", "inactive")
#     print("Row after update:", get_row_by_status("inactive"))
