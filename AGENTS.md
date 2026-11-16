# AGENTS.md: ApolloExplorer

## Read first

This repository targets the Apollo V4 platform. Before doing anything else,
read `ApolloKnowledgeBase/AGENTS.md` and follow it. It explains the platform,
the assumptions you must not make, and which knowledge base files to read for
your task. Paths in that file are relative to `ApolloKnowledgeBase/`.

If `ApolloKnowledgeBase/` is empty, the submodule has not been initialized.
Ask the user to run `git submodule update --init` instead of proceeding
without it.

## This repository

- **What it is:** a file transfer and remote shell tool for Apollo V4
  devices. A TCP server runs on the V4 (`Amiga/`, ApolloExplorerSrv plus
  ApolloExplorerTool); PC clients connect to it: the Qt GUI
  (`ApolloExplorerPC/`), the command line copy tool `acp` (`acp/`) and the
  remote shell `ash` (`ash/`).
- **Kind:** tool
- **Target core:** the latest core release
- **Target model:** any V4 model
- **Target OS:** ApolloOS R10, AmigaOS 3.9 and AmigaOS 3.2
- **Execution mode:** os-friendly
- **Languages:** C (Amiga server), C++ with Qt 6 (PC clients)

Only the code in `Amiga/` runs on the V4. Everything else runs on macOS,
Linux or Windows and is outside the scope of the knowledge base.

## Relevant knowledge base areas

- `ApolloKnowledgeBase/toolchain/`
- `ApolloKnowledgeBase/os/` (with `os/best-practices/` and `os/pitfalls/`)
- `ApolloKnowledgeBase/conventions/`

## Build and test

```sh
# Amiga server and tool (ApolloCrossDev, see Amiga/Makefile)
cd Amiga && make all

# PC clients
./build_macos_client.sh        # macOS
./build_linux_client.sh        # Linux
./build_windows_client.ps1     # Windows
```

Build and fix all errors and warnings before presenting code.

## Repository-specific rules

- The wire protocol is defined twice: `protocolTypes.h` (PC clients) and
  `Amiga/protocolTypes.h` (server). Keep both in sync.
- All multi-byte fields are big-endian on the wire. The server sends them
  natively; the PC clients convert with `qToBigEndian`/`qFromBigEndian`.
- The GUI has its own copy of the protocol handling
  (`ApolloExplorerPC/protocolhandler.cpp`, `aeconnection.cpp`) next to the
  one that `acp` and `ash` share (`acp/`). A protocol fix usually belongs in
  both.

## Knowledge base feedback

When you find something missing or wrong in ApolloKnowledgeBase while working
here, tell the user and offer to draft a change following
`ApolloKnowledgeBase/CONTRIBUTING.md`.

Offer a lesson when the user says the project, a release or a milestone is
done, and right away when an assumption turns out wrong. Follow
`ApolloKnowledgeBase/AGENTS.md` section 8: draft it from the lesson template,
show it to the user, and only submit it (as a pull request from the
`ApolloKnowledgeBase/` submodule) with their approval.
