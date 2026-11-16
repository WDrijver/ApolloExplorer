#!/usr/bin/env python3
"""
aetest.py - protocol-level test and stress harness for the ApolloExplorer server.

Talks the ApolloExplorer wire protocol directly (no Qt client code involved), so a
failure here is a server (or network) problem, not an acp/ash/GUI problem.  The
'clients' scenario runs the real acp/ash binaries for the end-to-end view.

Usage examples:
    tests/aetest.py discover
    tests/aetest.py --host 192.168.1.50 smoke
    tests/aetest.py --host 192.168.1.50 churn --count 100 --op shell
    tests/aetest.py --host 192.168.1.50 all
    tests/aetest.py --host 192.168.1.50 fault split-header

Exit code 0 when every check passed, 1 otherwise.  Every operation is also logged
as one JSON line in --log (default tests/results/<timestamp>.jsonl).
"""

import argparse
import json
import os
import random
import socket
import statistics
import struct
import subprocess
import sys
import threading
import time
import zlib

# ---------------------------------------------------------------------------
# Protocol constants (protocolTypes.h)
# ---------------------------------------------------------------------------
MAIN_PORT = 30302
DISCOVERY_PORT = 30301
MAGIC = 0xAABBCCDD
FILE_CHUNK_SIZE = 0x8000
MAX_MESSAGE_LENGTH = 0x8800
HDR = struct.Struct(">III")  # token, type, length

PMT = dict(
    NEW_CLIENT_PORT=0x01, VERSION=0x02, GET_VERSION=0x03, SHUTDOWN_SERVER=0x04,
    ACK=0x05, CANCEL_OPERATION=0x06, FAILED=0x07, CLOSING=0x08,
    START_OF_SEND_FILE=0x10, FILE_CHUNK=0x11, CLOSE=0x12, MKDIR=0x13,
    GET_DIR_LIST=0x14, DIR_LIST=0x15, GET_FILE=0x16, PUT_FILE=0x17,
    DELETE_PATH=0x18, GET_VOLUMES=0x19, VOLUME_LIST=0x1A, RENAME_FILE=0x1B,
    FILE_CHUNK_CONF=0x1C, FILE_PUT_CONF=0x1D, PATH_DELETED=0x1E,
    DEVICE_DISCOVERY=0x20, DEVICE_ANNOUNCE=0x21, PING=0x22, PONG=0x23,
    SHELL_EXEC=0x30, SHELL_OUTPUT=0x31, SHELL_DONE=0x32,
    SHELL_COMPLETE_REQ=0x33, SHELL_COMPLETE_RSP=0x34,
)
PMT_NAME = {v: k for k, v in PMT.items()}
DET_FILE = 0xFFFFFFFD
DET_USERDIR = 0x00000002
AT_OK = 1


class ProtocolError(Exception):
    pass


def cstr(b):
    """Bytes up to the first NUL, decoded as Latin-1 (Amiga text encoding)."""
    return b.split(b"\0", 1)[0].decode("latin-1")


# ---------------------------------------------------------------------------
# Logging / results
# ---------------------------------------------------------------------------
class Recorder:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.f = open(path, "a")
        self.lock = threading.Lock()

    def log(self, **rec):
        rec.setdefault("t", round(time.time(), 3))
        with self.lock:
            self.f.write(json.dumps(rec) + "\n")
            self.f.flush()


class Stats:
    """Collects pass/fail and latencies for one scenario."""

    def __init__(self, name):
        self.name = name
        self.ok = 0
        self.fail = 0
        self.lat = []
        self.errors = {}
        self.notes = []

    def good(self, seconds=None):
        self.ok += 1
        if seconds is not None:
            self.lat.append(seconds)

    def bad(self, err):
        self.fail += 1
        key = str(err)[:120]
        self.errors[key] = self.errors.get(key, 0) + 1

    def summary(self):
        s = f"{self.name}: {self.ok} ok, {self.fail} failed"
        if self.lat:
            lat = sorted(self.lat)
            p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))] * 1000
            s += (f"  latency ms: median {statistics.median(lat)*1000:.0f}"
                  f"  p95 {p(0.95):.0f}  max {lat[-1]*1000:.0f}")
        for e, n in sorted(self.errors.items(), key=lambda x: -x[1]):
            s += f"\n    {n}x {e}"
        for n in self.notes:
            s += f"\n    note: {n}"
        return s


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
class Session:
    """One ApolloExplorer session: initial connect, reconnect to the client port,
    version handshake.  Mirrors acp/protocolhandler.cpp."""

    def __init__(self, host, timeout=10.0, rec=None, tag=""):
        self.host = host
        self.timeout = timeout
        self.rec = rec
        self.tag = tag
        self.sock = None
        self.port = None
        self.version = None
        self.pings = 0
        self.timing = {}

    # -- low level --------------------------------------------------------
    def _recv_exact(self, n, sock=None, timeout=None):
        sock = sock or self.sock
        sock.settimeout(timeout if timeout is not None else self.timeout)
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
            except socket.timeout:
                raise ProtocolError(f"timeout after {len(buf)}/{n} bytes")
            if not chunk:
                raise ProtocolError(f"connection closed by server after {len(buf)}/{n} bytes")
            buf += chunk
        return bytes(buf)

    def recv(self, sock=None, timeout=None, skip_ping=True):
        """Return (type, body) of the next message.  PINGs are counted and skipped."""
        while True:
            token, mtype, length = HDR.unpack(self._recv_exact(12, sock, timeout))
            if token != MAGIC:
                raise ProtocolError(f"bad token 0x{token:08x}")
            if length < 12 or length > MAX_MESSAGE_LENGTH + 0x100:
                raise ProtocolError(f"bad length {length} for type 0x{mtype:x}")
            body = self._recv_exact(length - 12, sock, timeout) if length > 12 else b""
            if mtype == PMT["PING"] and skip_ping:
                self.pings += 1
                continue
            if mtype == PMT["CLOSING"]:
                raise ProtocolError(f"server closed the session: {cstr(body)!r}")
            return mtype, body

    def expect(self, want, timeout=None):
        mtype, body = self.recv(timeout=timeout)
        if mtype != PMT[want]:
            extra = f" ({cstr(body)!r})" if mtype == PMT["FAILED"] else ""
            raise ProtocolError(f"expected {want}, got {PMT_NAME.get(mtype, hex(mtype))}{extra}")
        return body

    def send(self, mtype, payload=b"", length=None):
        length = 12 + len(payload) if length is None else length
        self.sock.sendall(HDR.pack(MAGIC, PMT[mtype], length) + payload)

    # -- session ----------------------------------------------------------
    def open(self):
        t0 = time.monotonic()
        first = socket.create_connection((self.host, MAIN_PORT), timeout=self.timeout)
        t1 = time.monotonic()
        try:
            mtype, body = self.recv(sock=first)
            if mtype != PMT["NEW_CLIENT_PORT"]:
                raise ProtocolError(f"expected NEW_CLIENT_PORT, got {PMT_NAME.get(mtype, hex(mtype))}")
            self.port = struct.unpack(">H", body[:2])[0]
        finally:
            first.close()
        t2 = time.monotonic()
        # The child listens before the master sends the port, but retry a refused
        # connect briefly anyway so a slow V4 is reported as slow, not as failed.
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
                break
            except ConnectionRefusedError:
                if time.monotonic() > deadline:
                    raise ProtocolError(f"client port {self.port} refused the reconnect")
                time.sleep(0.05)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        t3 = time.monotonic()
        self.send("GET_VERSION")
        body = self.expect("VERSION")
        t4 = time.monotonic()
        self.version = f"{body[0]}.{body[1]}.{body[2]}{chr(body[3]) if body[3] else ''}"
        self.timing = dict(connect=t1 - t0, port_msg=t2 - t1, reconnect=t3 - t2,
                           version=t4 - t3, total=t4 - t0)
        return self

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # -- operations -------------------------------------------------------
    def get_version(self):
        self.send("GET_VERSION")
        b = self.expect("VERSION")
        return f"{b[0]}.{b[1]}.{b[2]}"

    def volumes(self):
        self.send("GET_VOLUMES")
        body = self.expect("VOLUME_LIST")
        count = struct.unpack(">I", body[:4])[0]
        names, off = [], 4
        for _ in range(count):
            size = struct.unpack(">I", body[off:off + 4])[0]
            names.append(cstr(body[off + 40:off + size]))
            off += size
        return names

    def dir_list(self, path):
        p = path.encode("latin-1")
        self.send("GET_DIR_LIST", struct.pack(">I", len(p)) + p + b"\0")
        mtype, body = self.recv()
        if mtype == PMT["FAILED"]:
            raise ProtocolError(f"dir list of {path!r} failed: {cstr(body)!r}")
        if mtype != PMT["DIR_LIST"]:
            raise ProtocolError(f"expected DIR_LIST, got {PMT_NAME.get(mtype, hex(mtype))}")
        count = struct.unpack(">I", body[:4])[0]
        entries, off = [], 4
        for _ in range(count):
            size, etype, fsize = struct.unpack(">III", body[off:off + 12])
            entries.append((cstr(body[off + 12:off + size]), etype, fsize))
            if size == 0:
                break
            off += size
        return entries

    def shell(self, command, timeout=None):
        """Run a command; returns (returncode, output, cwd)."""
        self.send("SHELL_EXEC", command.encode("latin-1") + b"\0")
        out = bytearray()
        while True:
            mtype, body = self.recv(timeout=timeout)
            if mtype == PMT["SHELL_OUTPUT"]:
                n = struct.unpack(">I", body[:4])[0]
                out += body[4:4 + n]
            elif mtype == PMT["SHELL_DONE"]:
                rc = struct.unpack(">i", body[:4])[0]
                return rc, out.decode("latin-1"), cstr(body[4:260])
            else:
                raise ProtocolError(f"unexpected {PMT_NAME.get(mtype, hex(mtype))} during shell command")

    def complete(self, partial):
        p = partial.encode("latin-1")[:511]
        self.send("SHELL_COMPLETE_REQ", p + b"\0" * (512 - len(p)))
        body = self.expect("SHELL_COMPLETE_RSP")
        count = struct.unpack(">I", body[:4])[0]
        return [cstr(x) for x in body[4:].split(b"\0")[:count]]

    def mkdir(self, path):
        self.send("MKDIR", path.encode("latin-1") + b"\0")
        body = self.expect("ACK")
        return body[0]

    def delete(self, path, is_dir=False):
        etype = DET_USERDIR if is_dir else DET_FILE
        self.send("DELETE_PATH", struct.pack(">I", etype) + path.encode("latin-1") + b"\0")
        while True:
            body = self.expect("PATH_DELETED")
            succeeded, completed = body[0], body[1]
            if not is_dir or completed or not succeeded:
                return bool(succeeded)

    def upload(self, path, data, window=5):
        p = path.encode("latin-1") + b"\0"
        self.send("PUT_FILE", p + b"\0" * 3)
        ack = self.expect("ACK")
        if ack[0] != AT_OK:
            raise ProtocolError(f"server refused upload of {path!r} (ack {ack[0]})")
        chunks = max(1, (len(data) + FILE_CHUNK_SIZE - 1) // FILE_CHUNK_SIZE)
        if len(data) == 0:
            chunks = 0
        self.send("START_OF_SEND_FILE", struct.pack(">II", len(data), chunks) + p)
        if chunks == 0:
            return 0
        ack = self.expect("ACK")
        if ack[0] != AT_OK:
            raise ProtocolError(f"server rejected start of upload (ack {ack[0]})")
        sent = confirmed = 0
        written = None
        while confirmed < chunks:
            while sent < chunks and sent - confirmed < window:
                part = data[sent * FILE_CHUNK_SIZE:(sent + 1) * FILE_CHUNK_SIZE]
                payload = struct.pack(">II", sent, len(part)) + part.ljust(FILE_CHUNK_SIZE, b"\0")
                self.send("FILE_CHUNK", payload)
                sent += 1
            mtype, body = self.recv()
            if mtype == PMT["FILE_CHUNK_CONF"]:
                confirmed += 1
            elif mtype == PMT["FILE_PUT_CONF"]:
                written = struct.unpack(">III", body[:12])[1]
                break
            elif mtype == PMT["ACK"]:
                raise ProtocolError(f"server aborted upload after {confirmed}/{chunks} chunks (ack {body[0]})")
            else:
                raise ProtocolError(f"unexpected {PMT_NAME.get(mtype, hex(mtype))} during upload")
        if written is None:
            body = self.expect("FILE_PUT_CONF")
            written = struct.unpack(">III", body[:12])[1]
        if written != len(data):
            raise ProtocolError(f"server wrote {written} bytes, expected {len(data)}")
        return written

    def download(self, path):
        p = path.encode("latin-1") + b"\0"
        self.send("GET_FILE", p + b"\0" * 3)
        ack = self.expect("ACK")
        if ack[0] == 0:
            raise ProtocolError(f"server refused download of {path!r}")
        body = self.expect("START_OF_SEND_FILE")
        size, chunks = struct.unpack(">II", body[:8])
        data = bytearray()
        for _ in range(chunks):
            body = self.expect("FILE_CHUNK")
            _num, n = struct.unpack(">II", body[:8])
            data += body[8:8 + n]
        if len(data) != size:
            raise ProtocolError(f"downloaded {len(data)} bytes, expected {size}")
        return bytes(data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def discover(wait=3.0):
    """Broadcast PMT_DEVICE_DISCOVERY like the GUI and collect announcements."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.bind(("", DISCOVERY_PORT))
    s.settimeout(0.2)
    found = {}
    end = time.monotonic() + wait
    next_probe = 0
    while time.monotonic() < end:
        if time.monotonic() >= next_probe:
            s.sendto(HDR.pack(MAGIC, PMT["DEVICE_DISCOVERY"], 12), ("255.255.255.255", DISCOVERY_PORT))
            next_probe = time.monotonic() + 1.0
        try:
            data, (ip, _port) = s.recvfrom(1024)
        except socket.timeout:
            continue
        if len(data) == 12 + 128:
            token, mtype, _ = HDR.unpack(data[:12])
            if token == MAGIC and mtype == PMT["DEVICE_ANNOUNCE"]:
                f = [cstr(data[12 + i * 32:12 + (i + 1) * 32]) for i in range(4)]
                found[ip] = dict(name=f[0], os=f[1], os_version=f[2], hardware=f[3])
    s.close()
    return found


def alive(host, timeout=5.0):
    """Health probe: can a fresh session do the version handshake?"""
    try:
        with Session(host, timeout=timeout) as s:
            return True, s.timing["total"]
    except Exception as e:  # noqa: BLE001 - report whatever it was
        return False, str(e)


def avail_total(sess):
    """Free memory in bytes from 'Avail TOTAL', or None."""
    try:
        rc, out, _ = sess.shell("Avail TOTAL", timeout=20)
        digits = "".join(ch for ch in out if ch.isdigit())
        return int(digits) if rc == 0 and digits else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
class Context:
    def __init__(self, args, rec):
        self.args = args
        self.host = args.host
        self.rec = rec
        self.results = []

    def run_step(self, stats, label, fn):
        t0 = time.monotonic()
        try:
            value = fn()
            dt = time.monotonic() - t0
            stats.good(dt)
            self.rec.log(scenario=stats.name, step=label, ok=True, sec=round(dt, 4))
            return value
        except Exception as e:  # noqa: BLE001
            dt = time.monotonic() - t0
            stats.bad(f"{label}: {e}")
            self.rec.log(scenario=stats.name, step=label, ok=False, sec=round(dt, 4), error=str(e))
            return None

    def finish(self, stats):
        ok, info = alive(self.host)
        if not ok:
            stats.notes.append(f"server NOT reachable afterwards: {info}")
        self.rec.log(scenario=stats.name, step="health", ok=ok, info=str(info))
        self.results.append(stats)
        print(stats.summary(), flush=True)
        return stats


def sc_smoke(ctx):
    st = Stats("smoke")
    tmp = f"RAM:aetest_{os.getpid()}"
    s = Session(ctx.host)
    if ctx.run_step(st, "connect", s.open) is None:
        return ctx.finish(st)
    st.notes.append(f"server version {s.version}, client port {s.port}, "
                    f"handshake {s.timing['total']*1000:.0f} ms")
    try:
        ctx.run_step(st, "version", s.get_version)
        ctx.run_step(st, "volumes", s.volumes)
        ctx.run_step(st, "dir RAM:", lambda: s.dir_list("RAM:"))
        ctx.run_step(st, "shell echo", lambda: _check_echo(s, "aetest"))
        ctx.run_step(st, "shell cd RAM:", lambda: _check_cd(s, "RAM:"))
        ctx.run_step(st, "complete", lambda: s.complete("RAM:"))
        ctx.run_step(st, "mkdir", lambda: _check(s.mkdir(tmp) == AT_OK, "mkdir failed"))
        data = random.Random(1).randbytes(100_000)
        ctx.run_step(st, "upload 100 KB", lambda: s.upload(f"{tmp}/f.bin", data))
        ctx.run_step(st, "download 100 KB", lambda: _check(s.download(f"{tmp}/f.bin") == data, "content differs"))
        ctx.run_step(st, "delete file", lambda: _check(s.delete(f"{tmp}/f.bin"), "delete failed"))
        ctx.run_step(st, "delete dir", lambda: s.delete(tmp, is_dir=True))
    finally:
        s.close()
    return ctx.finish(st)


def _check(cond, msg):
    if not cond:
        raise ProtocolError(msg)
    return True


def _check_echo(s, word):
    rc, out, _ = s.shell(f"Echo {word}")
    _check(rc == 0 and word in out, f"echo returned rc={rc} out={out!r}")


def _check_cd(s, path):
    rc, _out, cwd = s.shell(f"cd {path}")
    _check(rc == 0 and cwd.lower().startswith(path.lower().rstrip(":")), f"cd gave rc={rc} cwd={cwd!r}")


def sc_shell(ctx):
    """Many commands on ONE session: the long-lived ash case."""
    st = Stats("shell")
    s = Session(ctx.host)
    if ctx.run_step(st, "connect", s.open) is None:
        return ctx.finish(st)
    try:
        for i in range(ctx.args.count):
            if ctx.run_step(st, f"echo {i}", lambda: _check_echo(s, f"x{i}")) is None and ctx.args.stop:
                break
    finally:
        s.close()
    if s.pings:
        st.notes.append(f"{s.pings} PING(s) received")
    return ctx.finish(st)


def sc_churn(ctx):
    """Many SHORT sessions in a row: what scripts calling acp/ash once per file do."""
    st = Stats(f"churn ({ctx.args.op})")
    before = after = None
    if ctx.args.avail:
        with Session(ctx.host) as s:
            before = avail_total(s)
    for i in range(ctx.args.count):
        def one():
            with Session(ctx.host) as s:
                if ctx.args.op == "shell":
                    _check_echo(s, f"c{i}")
                elif ctx.args.op == "dir":
                    s.dir_list("RAM:")
                elif ctx.args.op == "cd":
                    # cd then disconnect: exercises the current-directory lock cleanup
                    _check_cd(s, "RAM:")
        if ctx.run_step(st, f"session {i}", one) is None and ctx.args.stop:
            break
        if ctx.args.gap:
            time.sleep(ctx.args.gap)
    if ctx.args.avail:
        time.sleep(1)
        try:
            with Session(ctx.host) as s:
                after = avail_total(s)
        except Exception:  # noqa: BLE001
            pass
        if before and after:
            st.notes.append(f"free memory {before:,} -> {after:,} bytes ({after - before:+,})")
    # Latency drift: compare first and last quarter.
    if len(st.lat) >= 8:
        q = len(st.lat) // 4
        a, b = statistics.median(st.lat[:q]), statistics.median(st.lat[-q:])
        st.notes.append(f"median latency first quarter {a*1000:.0f} ms, last quarter {b*1000:.0f} ms")
    return ctx.finish(st)


def sc_transfer(ctx):
    st = Stats("transfer")
    tmp = f"RAM:aetest_{os.getpid()}"
    sizes = [0, 1, FILE_CHUNK_SIZE - 1, FILE_CHUNK_SIZE, FILE_CHUNK_SIZE + 1, 1_000_000]
    if ctx.args.big:
        sizes.append(ctx.args.big)
    s = Session(ctx.host)
    if ctx.run_step(st, "connect", s.open) is None:
        return ctx.finish(st)
    try:
        s.mkdir(tmp)
        rnd = random.Random(2)
        for rep in range(ctx.args.count):
            for size in sizes:
                data = rnd.randbytes(size)
                path = f"{tmp}/t{size}.bin"
                t0 = time.monotonic()
                if ctx.run_step(st, f"upload {size}", lambda: s.upload(path, data)) is None:
                    continue
                up = time.monotonic() - t0
                t0 = time.monotonic()
                got = ctx.run_step(st, f"download {size}", lambda: s.download(path))
                down = time.monotonic() - t0
                if got is not None and got != data:
                    st.bad(f"download {size}: content differs (crc {zlib.crc32(got):08x} != {zlib.crc32(data):08x})")
                if size >= 1_000_000 and rep == 0:
                    st.notes.append(f"{size:,} bytes: up {size/up/1e6:.2f} MB/s, down {size/down/1e6:.2f} MB/s")
        s.delete(tmp, is_dir=True)
    except Exception as e:  # noqa: BLE001
        st.bad(f"transfer: {e}")
    finally:
        s.close()
    return ctx.finish(st)


def sc_concurrent(ctx):
    st = Stats(f"concurrent ({ctx.args.clients} clients)")
    lock = threading.Lock()

    def worker(n):
        local = Stats("w")
        try:
            with Session(ctx.host) as s:
                for i in range(ctx.args.count):
                    t0 = time.monotonic()
                    try:
                        _check_echo(s, f"w{n}_{i}")
                        local.good(time.monotonic() - t0)
                    except Exception as e:  # noqa: BLE001
                        local.bad(f"worker {n}: {e}")
                        break
        except Exception as e:  # noqa: BLE001
            local.bad(f"worker {n} connect: {e}")
        with lock:
            st.ok += local.ok
            st.fail += local.fail
            st.lat += local.lat
            for k, v in local.errors.items():
                st.errors[k] = st.errors.get(k, 0) + v

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(ctx.args.clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ctx.rec.log(scenario=st.name, ok=st.fail == 0, okcount=st.ok, fail=st.fail)
    return ctx.finish(st)


def sc_idle(ctx):
    """Idle past the server's inactivity ping (~30 s), then use the session."""
    st = Stats(f"idle ({ctx.args.seconds}s)")
    s = Session(ctx.host)
    if ctx.run_step(st, "connect", s.open) is None:
        return ctx.finish(st)
    try:
        time.sleep(ctx.args.seconds)
        ctx.run_step(st, "echo after idle", lambda: _check_echo(s, "awake"))
        st.notes.append(f"{s.pings} PING(s) received while idle")
    finally:
        s.close()
    return ctx.finish(st)


def sc_busy(ctx):
    """While one session runs a CPU-heavy command, another measures echo latency.
    Shell commands used to run at the client thread's priority 8, above the TCP/IP
    stack, so a busy command stalled every connection."""
    st = Stats(f"busy ({ctx.args.command!r})")
    done = threading.Event()
    heavy = {}

    def run_heavy():
        t0 = time.monotonic()
        try:
            with Session(ctx.host, timeout=ctx.args.limit) as s:
                rc, out, _ = s.shell(ctx.args.command, timeout=ctx.args.limit)
                heavy.update(rc=rc, lines=out.count("\n"))
        except Exception as e:  # noqa: BLE001
            heavy["error"] = str(e)
        heavy["sec"] = time.monotonic() - t0
        done.set()

    threading.Thread(target=run_heavy, daemon=True).start()
    time.sleep(0.5)
    probe = Session(ctx.host, timeout=30)
    if ctx.run_step(st, "connect probe", probe.open) is None:
        return ctx.finish(st)
    try:
        i = 0
        while not done.is_set():
            ctx.run_step(st, f"echo during busy {i}", lambda: _check_echo(probe, f"b{i}"))
            i += 1
            time.sleep(0.2)
    finally:
        probe.close()
    if "error" in heavy:
        st.bad(f"heavy command: {heavy['error']}")
    else:
        st.notes.append(f"heavy command took {heavy['sec']:.1f}s, rc={heavy['rc']}, {heavy['lines']} lines of output")
    return ctx.finish(st)


def sc_clients(ctx):
    """End-to-end: run the real ash/acp binaries repeatedly."""
    st = Stats("clients (ash/acp binaries)")
    ash, acp = ctx.args.ash, ctx.args.acp
    for i in range(ctx.args.count):
        if ash:
            def run_ash():
                p = subprocess.run([ash, "-t", "30", ctx.host, "Echo", f"e2e{i}"],
                                   capture_output=True, text=True, timeout=60)
                _check(p.returncode == 0 and f"e2e{i}" in p.stdout,
                       f"ash rc={p.returncode} out={p.stdout.strip()!r} err={p.stderr.strip()!r}")
            ctx.run_step(st, f"ash {i}", run_ash)
        if acp:
            def run_acp():
                local = os.path.join(os.path.dirname(ctx.rec.path), f"acp_{os.getpid()}.bin")
                with open(local, "wb") as f:
                    f.write(random.Random(i).randbytes(50_000))
                p = subprocess.run([acp, local, f"{ctx.host}:RAM:"],
                                   capture_output=True, text=True, timeout=60)
                os.unlink(local)
                _check(p.returncode == 0, f"acp rc={p.returncode} err={p.stderr.strip()[-200:]!r}")
            ctx.run_step(st, f"acp {i}", run_acp)
    return ctx.finish(st)


# --- Fault injection: these reproduce suspected server bugs. ---------------
def fault_split_header(ctx):
    """Send a message header in pieces.  The server's getMessage() gives up when the
    12 header bytes are not all there within 50 back-to-back FIONREAD polls."""
    st = Stats("fault split-header")
    for gap in (0.0, 0.01, 0.05, 0.2):
        def one():
            with Session(ctx.host) as s:
                msg = HDR.pack(MAGIC, PMT["GET_VERSION"], 12)
                s.sock.sendall(msg[:4])
                time.sleep(gap)
                s.sock.sendall(msg[4:])
                s.expect("VERSION", timeout=5)
        ctx.run_step(st, f"header split, {gap*1000:.0f} ms gap", one)
    return ctx.finish(st)


def fault_truncated_close(ctx):
    """Announce a long message, send part of it, then close.  The server's body loop
    does not handle recv() == 0 and may spin forever at task priority 8."""
    st = Stats("fault truncated-close")

    def one():
        s = Session(ctx.host).open()
        s.sock.sendall(HDR.pack(MAGIC, PMT["SHELL_EXEC"], 200) + b"Echo x")
        time.sleep(0.2)
        s.close()
    ctx.run_step(st, "truncated message + close", one)
    time.sleep(2)
    ok, info = alive(ctx.host)
    if ok:
        st.good()
    else:
        st.bad(f"server unreachable after truncated message: {info}")
    return ctx.finish(st)


FAULTS = {"split-header": fault_split_header, "truncated-close": fault_truncated_close}
DESTRUCTIVE = {"truncated-close"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("AMIGAHOST"), help="V4 address (default: $AMIGAHOST)")
    ap.add_argument("--log", help="JSON lines log file")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("discover", help="find servers on the LAN")
    sub.add_parser("smoke", help="one session, every operation once")
    p = sub.add_parser("shell", help="many commands on one session")
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--stop", action="store_true", help="stop at the first failure")
    p = sub.add_parser("churn", help="many short sessions (acp/ash once per call)")
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--op", choices=["version", "shell", "dir", "cd"], default="shell")
    p.add_argument("--gap", type=float, default=0.0, help="seconds between sessions")
    p.add_argument("--avail", action="store_true", help="measure free memory before and after")
    p.add_argument("--stop", action="store_true")
    p = sub.add_parser("transfer", help="upload/download with verification")
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--big", type=int, default=0, help="extra file size in bytes")
    p = sub.add_parser("concurrent", help="parallel sessions")
    p.add_argument("--clients", type=int, default=4)
    p.add_argument("--count", type=int, default=20)
    p = sub.add_parser("idle", help="idle past the server's inactivity ping")
    p.add_argument("--seconds", type=int, default=70)
    p = sub.add_parser("busy", help="echo latency while another session runs a heavy command")
    p.add_argument("--command", default="List SYS: ALL")
    p.add_argument("--limit", type=int, default=300, help="seconds allowed for the heavy command")
    p = sub.add_parser("clients", help="run the real ash/acp binaries")
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--ash", help="path to ash")
    p.add_argument("--acp", help="path to acp")
    p = sub.add_parser("fault", help="fault injection")
    p.add_argument("which", choices=sorted(FAULTS))
    p.add_argument("--destructive", action="store_true",
                   help="allow faults that may hang the server (needs an Amiga reboot)")
    p = sub.add_parser("all", help="smoke, shell, churn, transfer, concurrent, split-header")
    p.add_argument("--count", type=int, default=30)

    args = ap.parse_args()

    if args.cmd == "discover":
        found = discover()
        if not found:
            print("No ApolloExplorer server answered on UDP port 30301.")
            return 1
        for ip, info in found.items():
            print(f"{ip}  {info['name']}  ({info['hardware']}, {info['os']} {info['os_version']})")
        return 0

    if not args.host:
        found = discover()
        if len(found) != 1:
            ap.error("no --host given and discovery found " + (f"{len(found)} servers" if found else "no server"))
        args.host = next(iter(found))
        print(f"Using discovered server {args.host}")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    log = args.log or os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", f"{stamp}.jsonl")
    rec = Recorder(log)
    rec.log(event="start", argv=sys.argv[1:], host=args.host)
    ctx = Context(args, rec)

    ok, info = alive(args.host)
    if not ok:
        print(f"Server {args.host} is not answering before the test: {info}")
        return 1

    if args.cmd == "smoke":
        sc_smoke(ctx)
    elif args.cmd == "shell":
        sc_shell(ctx)
    elif args.cmd == "churn":
        sc_churn(ctx)
    elif args.cmd == "transfer":
        sc_transfer(ctx)
    elif args.cmd == "concurrent":
        sc_concurrent(ctx)
    elif args.cmd == "idle":
        sc_idle(ctx)
    elif args.cmd == "busy":
        sc_busy(ctx)
    elif args.cmd == "clients":
        if not (args.ash or args.acp):
            ap.error("clients needs --ash and/or --acp")
        sc_clients(ctx)
    elif args.cmd == "fault":
        if args.which in DESTRUCTIVE and not args.destructive:
            ap.error(f"'{args.which}' may hang the server; add --destructive to run it")
        FAULTS[args.which](ctx)
    elif args.cmd == "all":
        n = args.count
        args.stop, args.op, args.gap, args.avail, args.big, args.clients = False, "shell", 0.0, True, 0, 3
        sc_smoke(ctx)
        args.count = n
        sc_shell(ctx)
        sc_churn(ctx)
        args.count = 1
        sc_transfer(ctx)
        args.count = max(5, n // 3)
        sc_concurrent(ctx)
        fault_split_header(ctx)

    failed = sum(r.fail for r in ctx.results)
    rec.log(event="end", failed=failed)
    print(f"\nLog: {log}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
