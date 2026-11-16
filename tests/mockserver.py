#!/usr/bin/env python3
"""
mockserver.py - a stand-in for the ApolloExplorer Amiga server, for testing the PC
clients (acp, ash, GUI) and aetest.py without a V4.

It speaks the same wire protocol (initial connect on 30302, reconnect on a client
port, big-endian fields) and keeps files in memory.  Fault options make the
network misbehave on purpose so client bugs show up reproducibly:

    --fragment        send every message in small pieces with short pauses
    --ping-every S    send PMT_PING on every session every S seconds (the real
                      server does this after ~30 s of inactivity)
    --latency MS      wait MS milliseconds before every reply
    --close-after N   drop each session after N handled messages

Usage:
    tests/mockserver.py [--port 30302] [fault options]
"""

import argparse
import random
import socket
import struct
import threading
import time

MAGIC = 0xAABBCCDD
HDR = struct.Struct(">III")
CHUNK = 0x8000
T = dict(NEW_CLIENT_PORT=0x01, VERSION=0x02, GET_VERSION=0x03, ACK=0x05, FAILED=0x07,
         CLOSING=0x08, START_OF_SEND_FILE=0x10, FILE_CHUNK=0x11, MKDIR=0x13,
         GET_DIR_LIST=0x14, DIR_LIST=0x15, GET_FILE=0x16, PUT_FILE=0x17, DELETE_PATH=0x18,
         GET_VOLUMES=0x19, VOLUME_LIST=0x1A, FILE_CHUNK_CONF=0x1C, FILE_PUT_CONF=0x1D,
         PATH_DELETED=0x1E, PING=0x22, SHELL_EXEC=0x30, SHELL_OUTPUT=0x31, SHELL_DONE=0x32,
         SHELL_COMPLETE_REQ=0x33, SHELL_COMPLETE_RSP=0x34)

FILES = {}            # lower-case path -> (path, bytes)
DIRS = {"ram:"}       # lower-case directory paths
LOCK = threading.Lock()


def cstr(b):
    return b.split(b"\0", 1)[0].decode("latin-1")


class Conn:
    def __init__(self, sock, opts):
        self.sock = sock
        self.opts = opts
        self.wlock = threading.Lock()

    def send(self, mtype, payload=b""):
        data = HDR.pack(MAGIC, T[mtype], 12 + len(payload)) + payload
        if self.opts.latency:
            time.sleep(self.opts.latency / 1000)
        with self.wlock:
            if self.opts.fragment:
                pos = 0
                while pos < len(data):
                    n = random.randint(1, 7) if pos < 16 else random.randint(1, 4096)
                    self.sock.sendall(data[pos:pos + n])
                    pos += n
                    time.sleep(random.choice((0, 0, 0.002, 0.02)))
            else:
                self.sock.sendall(data)

    def recv_exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            c = self.sock.recv(n - len(buf))
            if not c:
                raise ConnectionError("client closed")
            buf += c
        return bytes(buf)

    def recv(self):
        token, mtype, length = HDR.unpack(self.recv_exact(12))
        if token != MAGIC:
            raise ConnectionError(f"bad token {token:08x}")
        return mtype, self.recv_exact(length - 12) if length > 12 else b""


def session(sock, opts, log):
    c = Conn(sock, opts)
    stop = threading.Event()
    if opts.ping_every:
        def pinger():
            while not stop.wait(opts.ping_every):
                try:
                    c.send("PING")
                except OSError:
                    return
        threading.Thread(target=pinger, daemon=True).start()
    cwd = "RAM:"
    handled = 0
    try:
        while True:
            mtype, body = c.recv()
            handled += 1
            if opts.close_after and handled > opts.close_after:
                log(f"closing session after {opts.close_after} messages (--close-after)")
                return
            if mtype == T["GET_VERSION"]:
                c.send("VERSION", bytes([1, 4, 3, ord("M")]))
            elif mtype == T["GET_VOLUMES"]:
                name = b"RAM Disk\0"
                entry = struct.pack(">10I", 40 + len(name), 0, 0, 0, 0, 1000, 10, 512, 0, 0) + name
                entry += b"\0" * (-len(entry) % 4)
                entry = struct.pack(">I", len(entry)) + entry[4:]
                c.send("VOLUME_LIST", struct.pack(">I", 1) + entry)
            elif mtype == T["GET_DIR_LIST"]:
                n = struct.unpack(">I", body[:4])[0]
                path = body[4:4 + n].decode("latin-1")
                c.send("DIR_LIST", dir_list(path))
            elif mtype == T["SHELL_EXEC"]:
                cmd = cstr(body)
                out, rc, cwd = shell(cmd, cwd)
                if out:
                    data = out.encode("latin-1")
                    for i in range(0, len(data), CHUNK):
                        part = data[i:i + CHUNK]
                        c.send("SHELL_OUTPUT", struct.pack(">I", len(part)) + part.ljust(CHUNK, b"\0"))
                c.send("SHELL_DONE", struct.pack(">i", rc) + cwd.encode("latin-1").ljust(256, b"\0"))
            elif mtype == T["SHELL_COMPLETE_REQ"]:
                c.send("SHELL_COMPLETE_RSP", struct.pack(">I", 1) + b"RAM:\0")
            elif mtype == T["MKDIR"]:
                with LOCK:
                    DIRS.add(cstr(body).lower().rstrip("/"))
                c.send("ACK", bytes([1, 0, 0, 0]))  # AT_OK, like Amiga/MakeDir.c
            elif mtype == T["PUT_FILE"]:
                put_file(c, cstr(body))
            elif mtype == T["GET_FILE"]:
                get_file(c, cstr(body))
            elif mtype == T["DELETE_PATH"]:
                path = cstr(body[4:])
                with LOCK:
                    ok = FILES.pop(path.lower(), None) is not None or path.lower() in DIRS
                    DIRS.discard(path.lower())
                    for k in [k for k in FILES if k.startswith(path.lower() + "/")]:
                        del FILES[k]
                c.send("PATH_DELETED", bytes([1 if ok else 0, 1, 0, 0, 0, 0, 0, 0]) + path.encode("latin-1") + b"\0")
            else:
                log(f"unhandled message type 0x{mtype:x}")
    except (ConnectionError, OSError) as e:
        log(f"session ended: {e}")
    finally:
        stop.set()
        sock.close()


def dir_list(path):
    p = path.lower().rstrip("/")
    entries = []
    with LOCK:
        for k, (name, data) in FILES.items():
            parent, _, leaf = k.rpartition("/") if "/" in k else (k.split(":")[0] + ":", "", k.split(":", 1)[1])
            if parent == p:
                entries.append((name.rsplit("/", 1)[-1].split(":")[-1], 0xFFFFFFFD, len(data)))
    payload = struct.pack(">I", len(entries))
    for name, etype, size in entries:
        nb = name.encode("latin-1") + b"\0"
        nb += b"\0" * (-(12 + len(nb)) % 4)
        payload += struct.pack(">III", 12 + len(nb), etype, size) + nb
    return payload


def shell(cmd, cwd):
    word, _, arg = cmd.partition(" ")
    w = word.lower()
    if w == "echo":
        return arg + "\n", 0, cwd
    if w == "cd":
        if not arg:
            return cwd + "\n", 0, cwd
        return "", 0, arg
    if w == "wait":
        time.sleep(float(arg or 1))
        return "", 0, cwd
    if w == "avail":
        return "  1000000\n", 0, cwd
    if w == "big":
        return ("x" * 79 + "\n") * int(arg or 1000), 0, cwd
    return f"{word}: Unknown command\n", 10, cwd


def put_file(c, path):
    c.send("ACK", bytes([1, 0, 0, 0]))
    mtype, body = c.recv()
    size, chunks = struct.unpack(">II", body[:8])
    if chunks == 0:
        with LOCK:
            FILES[path.lower()] = (path, b"")
        return
    c.send("ACK", bytes([1, 0, 0, 0]))
    data = bytearray()
    for _ in range(chunks):
        mtype, body = c.recv()
        num, n = struct.unpack(">II", body[:8])
        if n == 0:
            break
        data += body[8:8 + n]
        c.send("FILE_CHUNK_CONF", struct.pack(">I", num))
    with LOCK:
        FILES[path.lower()] = (path, bytes(data))
    c.send("FILE_PUT_CONF", struct.pack(">III", chunks, len(data), 0))


def get_file(c, path):
    with LOCK:
        entry = FILES.get(path.lower())
    if entry is None:
        c.send("ACK", bytes([0, 0, 0, 0]))
        return
    data = entry[1]
    c.send("ACK", bytes([1, 0, 0, 0]))
    chunks = (len(data) + CHUNK - 1) // CHUNK
    c.send("START_OF_SEND_FILE", struct.pack(">II", len(data), chunks) + path.encode("latin-1") + b"\0")
    for i in range(chunks):
        part = data[i * CHUNK:(i + 1) * CHUNK]
        c.send("FILE_CHUNK", struct.pack(">II", i, len(part)) + part.ljust(CHUNK, b"\0"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=30302)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--fragment", action="store_true")
    ap.add_argument("--ping-every", type=float, default=0)
    ap.add_argument("--latency", type=int, default=0)
    ap.add_argument("--close-after", type=int, default=0)
    ap.add_argument("--quiet", action="store_true")
    opts = ap.parse_args()

    def log(msg):
        if not opts.quiet:
            print(time.strftime("%H:%M:%S"), msg, flush=True)

    master = socket.socket()
    master.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    master.bind((opts.bind, opts.port))
    master.listen(10)
    log(f"mock server listening on {opts.bind}:{opts.port}")
    while True:
        first, addr = master.accept()
        child = socket.socket()
        child.bind((opts.bind, 0))
        child.listen(1)
        port = child.getsockname()[1]
        Conn(first, opts).send("NEW_CLIENT_PORT", struct.pack(">H", port) + b"\0\0")
        first.close()

        def accept_child(child=child, addr=addr):
            child.settimeout(10)
            try:
                s, _ = child.accept()
            except socket.timeout:
                log(f"client {addr[0]} never reconnected")
                return
            finally:
                child.close()
            s.settimeout(None)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            log(f"session from {addr[0]} on port {port}")
            session(s, opts, log)
        threading.Thread(target=accept_child, daemon=True).start()


if __name__ == "__main__":
    main()
