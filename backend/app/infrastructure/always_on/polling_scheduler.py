"""A polling loop implementing :class:`SchedulerPort`.

Chosen over APScheduler or Celery because the hard part of Always-On is not
"wake me up at 09:00" -- it is "do not run this twice, and do not lose it if the
process dies", and both of those are solved here by rows in PostgreSQL with
unique constraints and compare-and-set updates. A third-party scheduler would
bring its own job store and its own idea of single-fire, and we would then have
two sources of truth about whether an occurrence has been handled.

The consequence of polling is honest and worth stating: firing is late by up to
``interval_seconds``. Jobs are clocked to the minute, so a five-second poll is
plenty, and this buys a scheduler with no external dependency and no separate
process to operate.

Concurrency with several app processes is handled by the claim protocol in the
dispatcher, not here. Two processes running this loop is safe and merely means
each tick finds half the due jobs already claimed; the loop takes no locks
because there is nothing here worth locking.
"""

import asyncio
import contextlib
import logging

from app.domain.ports.scheduler import SchedulerPort, TickHandler


class PollingScheduler(SchedulerPort):
    """Calls a tick handler on a fixed interval until stopped."""

    def __init__(
        self,
        interval_seconds: float = 5.0,
        logger: logging.Logger | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")
        self.interval_seconds = interval_seconds
        self.logger = logger or logging.getLogger(__name__)
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, handler: TickHandler) -> None:
        """Start ticking.

        Guarded because the FastAPI lifespan can run more than once in a process
        (``uvicorn --reload``) and a second loop would double every job's
        dispatch rate.
        """
        if self.is_running:
            self.logger.warning("scheduler is already running; ignoring start()")
            return

        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(
            self._loop(handler), name="nexus-always-on-scheduler"
        )
        self.logger.info(
            "always-on scheduler started, polling every %.1fs", self.interval_seconds
        )

    async def stop(self) -> None:
        """Ask the loop to finish and wait for the in-flight tick to complete.

        Awaiting matters: abandoning a tick mid-dispatch is precisely what leaves
        an execution stuck in RUNNING for the recovery sweep to clean up on the
        next boot.
        """
        if self._task is None:
            return

        self._stopping.set()
        task = self._task
        self._task = None
        with contextlib.suppress(asyncio.CancelledError):
            # Generous, but bounded: a hung tick must not block shutdown forever.
            await asyncio.wait_for(asyncio.shield(task), timeout=self.interval_seconds * 4)
        self.logger.info("always-on scheduler stopped")

    async def _loop(self, handler: TickHandler) -> None:
        while not self._stopping.is_set():
            try:
                await handler(_now())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                # The loop survives a failing tick. A handler that raised and
                # killed the loop would stop every future job silently.
                self.logger.exception("always-on tick failed; continuing")

            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=self.interval_seconds
                )
            except TimeoutError:
                continue


def _now():
    from app.domain.entities._common import utc_now

    return utc_now()


class ManualScheduler(SchedulerPort):
    """A scheduler that only ticks when told to. For tests and one-shot runs.

    Implements the same port, so the dispatcher and every service above it are
    exercised identically in tests and in production -- the only difference is
    that nobody starts a loop.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.handler: TickHandler | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, handler: TickHandler) -> None:
        self.handler = handler
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def tick_once(self) -> None:
        """Run the handler immediately, if one was registered."""
        if self.handler is None:
            raise RuntimeError("ManualScheduler has no handler; call start() first")
        await self.handler(_now())