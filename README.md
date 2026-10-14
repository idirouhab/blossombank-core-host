# BLSONL1 account region

Account master, posting journal and overnight accounting routines. The bridge uses Python and SQLite; validation and calculation routines are compiled with GnuCOBOL.

Requires Python 3.11+, GnuCOBOL 3.1+ and a C toolchain.

```sh
./build.sh
./test.sh
./run.sh
```

| Setting | Default |
| --- | --- |
| `BIND` | `127.0.0.1` |
| `PORT` | `8082` |
| `HOST_DATA_DIR` | `.runtime` |
| `PYTHON` | `python3` |

`HOST` is accepted if `BIND` is absent. `DATA_DIR` is accepted if `HOST_DATA_DIR` is absent. The data directory contains the account database. Initialization runs once; restarting does not reset balances. Rebuild after changing COBOL.

`GET /health` reports the region and business-day state. Requests and operator controls are described in [online interface](docs/online-interface.md). Batch procedures, backups and day close are in [operations](docs/operations.md).

The operator endpoints do not implement authentication. Access control must be provided by the deployment environment.

The container image uses `/data` and listens on port 8082. Mount persistent storage for the database. `db/catalog/` contains catalogue source; `jcl/` contains scheduler members. The native command entry point is `python3 -m hostbridge`.

MIT license.
