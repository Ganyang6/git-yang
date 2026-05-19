def _run_async(coro, default=None):
    """Run an async coroutine from a sync context within FastAPI.

    When called from within the running event loop (FastAPI route handlers),
    uses asyncio.run_coroutine_threadsafe() to schedule the coroutine on the
    main loop and blocks until the result is available.

    When called from outside any event loop (CLI / test), uses asyncio.run().

    This avoids the "Future attached to a different loop" error that occurs
    when asyncio.run() creates a new loop in a thread but the Redis client's
    connection pool is bound to the original loop.

    Args:
        coro: The async coroutine to execute.
        default: Value to return on timeout (None = raise TimeoutError).

    Returns:
        The coroutine's return value, or *default* on timeout.

    Raises:
        Exception from the coroutine on failure.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        target_loop = _main_loop or loop
        future = asyncio.run_coroutine_threadsafe(coro, target_loop)
        try:
            return future.result(timeout=5.0)
        except concurrent.futures.TimeoutError:
            if default is None:
                raise TimeoutError(
                    f"Coroutine {coro.__qualname__} did not complete within 5s"
                )
            logger.warning(
                "Coroutine %s timed out after 5s, returning default",
                coro.__qualname__,
            )
            return default
    else:
        return asyncio.run(coro)
