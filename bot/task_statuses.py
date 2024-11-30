from enum import Enum

class TaskStatuses(str, Enum):
    NEW = "new"
    READY_FOR_PROCESSING = "ready_for_processing"
    PROCESSING = "processing"
    DONE = "done"
    SENT = "sent"
    FAILED = "failed"

t = TaskStatuses.NEW
print(t)