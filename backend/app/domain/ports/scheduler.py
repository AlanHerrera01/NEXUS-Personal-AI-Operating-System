"""When the system is allowed to wake up and look for work.

The split here is deliberate and is the reason this is a two-method port rather
than a scheduler abstraction carrying business logic:

* **"is this job due?"** is a domain question answered by
  ``ScheduledJob.is_due`` and ``ScheduledJobRepository.list_due``.
* **"when do we next look?"** is an infrastructure question: a poll loop, a
  timer wheel, or a queue push.

Putting the second question behind a port keeps the first one honest. A
scheduler adapter cannot silently skip a due job or invent an extra firing,
because all it can do is call the handler at a time of its choosing and let the
domain decide what happens. It also means a ``FakeScheduler`` in tests can drive
the dispatcher synchronously and assert on exactly the jobs that fired.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeAlias

#: Called on every tick with the current time. The handler is responsible for
#: its own error containment: a tick handler that raises must not kill the loop.
TickHandler: TypeAlias = Callable[[datetime], Awaitable[None]]


class SchedulerPort(ABC):
    """Drives periodic wake-ups for the Always-On dispatcher."""

    @abstractmethod
    def start(self, handler: TickHandler) -> None:
        """Begin ticking. Calling this twice must be a no-op, not a second loop.

        The FastAPI lifespan calls this once per process. A duplicate loop would
        double every job's dispatch rate, and the in-process guard here is the
        only thing preventing that when ``uvicorn --reload`` or two workers run
        on the same host.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop ticking and wait for an in-flight tick to finish.

        Shutdown must be awaited. Dropping a tick mid-dispatch is what leaves
        executions stranded in RUNNING, which the recovery sweep then has to
        clean up on the next boot.
        """

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """True between a successful ``start`` and the next ``stop``."""