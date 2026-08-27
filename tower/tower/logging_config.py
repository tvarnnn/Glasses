import logging
import re

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

    `ImportError` IS THE SECOND KIND THAT CARRIES A PATH, and it was
    missed because it is not an `OSError`. CPython builds the message for
    a failed `from X import Y` by appending the module's `__file__` in
    parentheses, so a real one reads

        cannot import name 'InterpolationMode' from
        'torchvision.transforms' (C:\\Users\\<user>\\...\\__init__.py)

    which discloses the home directory and the OS username exactly as an
    OSError would. It became reachable when Scene Understanding started
    reporting why it could not be constructed; before that no import
    failure had a route to this function.

    It is reduced differently from `OSError` rather than identically,
    because the two differ in what the useful half is. An OSError's useful
    half IS the path, so nothing survives suppression. An ImportError's is
    the MODULE NAME -- "no module named 'easyocr'" tells an operator to
    install an extra, while a bare "ModuleNotFoundError" tells them
    nothing. `exc.name` is set by the import system and holds a dotted
    module name, never a path, so it is safe to keep and it is read
    instead of the message rather than out of it.

    NOT a general fix for third-party exceptions. Anything that is neither
    an OSError nor an ImportError still passes its message through, which
    is right for this repository's own exceptions and is a standing risk
    for a dependency that decides to put a path in a `RuntimeError`.
    Inverting the rule -- pass through `tower.*` types, reduce everything
    else -- was considered and NOT done here: it would also discard useful
    path-free messages like torch's own CUDA diagnostics, and it is a
    judgement about every cartridge's wire rather than a fix for a
    measured leak. Recorded so the next reader knows the hole is known.
    """
    if isinstance(exc, ImportError):
        name = getattr(exc, "name", None)
        # Guarded rather than trusted: `name` is a dotted module path in
        # every case the import system produces, but this string is going
        # on an unauthenticated wire and a caller can construct an
        # ImportError by hand with anything in it.
        if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][\w.]*", name):
            # "no module named" only for the case where that is true. A
            # plain ImportError means the module WAS found and something
            # inside it could not be reached -- a partially initialised
            # package, a missing symbol, a broken DLL -- and telling an
            # operator the module is absent sends them to install
            # something that is already installed.
            if isinstance(exc, ModuleNotFoundError):
                return f"{type(exc).__name__}: no module named {name!r}"
            return f"{type(exc).__name__}: failed to import {name!r}"
        return type(exc).__name__
    if isinstance(exc, OSError):
        return type(exc).__name__
    return f"{type(exc).__name__}: {exc}"
