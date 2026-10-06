class TaskError(Exception):
    """Base class for task use-case failures."""


class TaskNotFoundError(TaskError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"task {task_id} does not exist")
        self.task_id = task_id


class TaskTransitionError(TaskError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"invalid task transition: {current} -> {target}")
        self.current = current
        self.target = target
