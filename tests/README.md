# ApolloExplorer tests

Two tools, Python 3 standard library only:

- **`aetest.py`**: test and stress harness. It speaks the wire protocol
  directly, so a failure is a server or network problem, not a client one.
  The `clients` scenario runs the real `acp`/`ash` binaries for the
  end-to-end view.
- **`mockserver.py`**: a stand-in for the Amiga server, with fault options
  (`--fragment`, `--ping-every`, `--latency`, `--close-after`), for testing
  the PC clients and `aetest.py` without a V4.

## Against a V4

```sh
tests/aetest.py discover                      # find servers on the LAN
export AMIGAHOST=192.168.x.y                  # or pass --host
tests/aetest.py smoke                         # every operation once
tests/aetest.py all                           # smoke, shell, churn, transfer, concurrent, split-header
tests/aetest.py churn --count 100 --avail     # 100 short sessions, free memory before/after
tests/aetest.py idle --seconds 70             # past the server's 30 s inactivity ping
tests/aetest.py clients --ash path/to/ash --acp path/to/acp --count 20
tests/aetest.py fault split-header            # header sent in pieces
tests/aetest.py fault truncated-close --destructive   # may hang the server
```

Every run checks before and after that a fresh session still gets through
the handshake, and prints `server NOT reachable afterwards` when it does not.
Each operation is logged as one JSON line in `tests/results/` (not in git).

## Against the mock

```sh
tests/mockserver.py --fragment --ping-every 0.5 &
tests/aetest.py --host 127.0.0.1 all
tests/aetest.py --host 127.0.0.1 clients --ash path/to/ash --acp path/to/acp
```

The mock listens on 127.0.0.1:30302, the port the clients use, so stop the
GUI or any other local server first.
