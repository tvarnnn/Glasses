import logging

from tower.config import Settings


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=logging.DEBUG if settings.dev_mode else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def client_safe_reason(exc: BaseException) -> str:
    """How a failure is described to a CLIENT, as opposed to a log.

    Three cartridges put an exception's text on a wire -- World Builder's
    `lifecycle.reason`, a live session's `failure_reason`, the CV Lab's
    arm failure -- and they must, because "it failed" is not an answer a
    person can act on. `UnknownPoseConventionError` explains that a world
    declares a convention this build refuses to guess at; the CV Lab
    explains that weights are unavailable. Those sentences are the
    contract working.

    But an `OSError` describes a failure by naming the PATH it happened
    on, and these strings reach an unauthenticated socket. A missing
    world, a missing model file or a torch.hub cache miss would disclose
    the home directory, and with it the operating-system username, to
    anyone who can open `/ws`.

    So the split is by KIND, not by caller: this repository's own
    exceptions are written to be read by a person and are passed through;
    `OSError` and its subclasses are reduced to their type name. The full
    exception always goes to the log, which is server-side.

    Blanket-suppressing the message was tried first and was wrong: it
    turned "this build does not recognise that pose convention" into
    "UnknownPoseConventionError", and two tests correctly refused it.
    """
    if isinstance(exc, OSError):
        return type(exc).__name__
    return f"{type(exc).__name__}: {exc}"
