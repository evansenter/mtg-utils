"""Run independent Monte Carlo replicates in worker processes.

Every replicate is seeded on its own (`seed + i`) and draws from its own
generator, so where it runs cannot change what it draws: the results come
back in submission order and are aggregated exactly as a serial loop would
aggregate them. The per-process caches in castability.py start cold in each
worker, which costs time and never correctness -- see the note there.

`jobs <= 1` is the plain loop, in this process, and is the library default:
a caller that does not ask for workers gets exactly the code path it always
had, monkeypatches included. The CLI asks for one worker per CPU.
"""
import os
from concurrent.futures import ProcessPoolExecutor


def default_jobs():
    return os.cpu_count() or 1


def pmap(fn, calls, jobs=1):
    """[fn(*args) for args in calls], across up to `jobs` processes.

    `fn` must be a module-level function and every argument picklable, since
    a spawned worker (the macOS default) re-imports the module to find it.
    """
    calls = list(calls)
    if jobs <= 1 or len(calls) <= 1:
        return [fn(*args) for args in calls]
    with ProcessPoolExecutor(max_workers=min(jobs, len(calls))) as ex:
        return list(ex.map(fn, *zip(*calls)))
