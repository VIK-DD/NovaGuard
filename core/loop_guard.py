"""Keep a background loop alive across a failing iteration.

discord.py treats an exception escaping a ``tasks.loop`` body as fatal: it
marks the loop failed, hands the exception to the error handler, and re-raises,
which ends the task. Nothing restarts it. One transient failure — Discord
answering 500, SQLite briefly locked, a network blip — therefore turns a
scheduled job off until somebody notices and restarts the bot.

Wrapping the body means a bad iteration costs one iteration. The next tick
still happens, and the failure is logged with its traceback instead of
vanishing.
"""

import asyncio
import functools


def keep_running(logger, what):
    """Log and absorb any failure inside a loop body, so the loop ticks again.

    ``what`` names the job in the log line, since a traceback alone rarely
    says which schedule stopped.

    Apply it *under* ``@tasks.loop`` — the decorator closest to the function
    wraps the body, and the loop must see the guarded version::

        @tasks.loop(hours=24)
        @keep_running(log, "privacy retention sweep")
        async def retention_loop(self): ...
    """

    def decorator(function):
        @functools.wraps(function)
        async def wrapper(*args, **kwargs):
            try:
                return await function(*args, **kwargs)
            except asyncio.CancelledError:
                # cog_unload cancels these. Absorbing it would leave the task
                # running through a reload, with two copies on the next load.
                raise
            except Exception:
                logger.exception("%s failed; the next run will try again", what)
                return None

        return wrapper

    return decorator
