# halloy-search

Grep your [Halloy](https://halloy.chat) IRC log history.

## Setup

```sh
./setup.sh
```

Requires `python3.14`.

## Usage

```sh
./halloy-search <term> [options]
```

The term is a regex, matched against rendered lines (`<nick> text`), so nicks are searchable too.

| Option | Meaning |
|---|---|
| `-i` | case-insensitive |
| `-F` | literal string, not regex |
| `-A/-B/-C N` | context lines after/before/both |
| `-b NAME` | only buffers whose name contains NAME |
| `--history-dir PATH` | override history location |
| `--no-color` | plain output |

## Examples

```sh
./halloy-search -i 'release' -C 2
./halloy-search -b '#halloy' -F 'v2025.1'
```

Made with Fable 5