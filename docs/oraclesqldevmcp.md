# Verified MCP Servers for Oracle and SQLite

**Verification date:** 2026-07-10
**Methodology:** Each claim was verified against the actual source (npm registry API, Docker Hub API, Oracle documentation, GitHub repos, blog posts by Oracle PMs, and official Continue.dev documentation).

---

## Summary Table

| # | Claim / Server | Verdict | Key Discrepancies |
|---|---|---|---|
| 1 | `mcp/oracle` Docker image | **Partially Correct** | Exists but published by Docker/MCP org, NOT Oracle Corp. Author is @samscarrow. |
| 2 | Oracle SQL Developer VS Code Extension MCP | **Partially Correct** | Real, but `run-sql-asynch` not in official Oracle docs (5 tools, not 6). Command palette name varies. |
| 3 | `mcp-oracle-database` by tannerpace | **Correct** | All claims verified: npm package, node-oracledb Thin Mode, read-only. |
| 4 | `oracle-sqlplus-mcp` | **Correct** | All claims verified: real package, sqlplus backend. NOT read-only (has `execute_ddl`). |
| 5 | `@modelcontextprotocol/server-sqlite` | **Incorrect** | SQLite server is ARCHIVED. Not available on npm. Docker image `mcp/sqlite` exists but unmaintained. |
| 6 | `@achmadya-dev/mcp-sqlite-query` | **Correct** | All claims verified: node:sqlite, read-only by default. |
| 7 | `@graduenz/mcp-sqlite-server` | **Correct** | All claims verified: better-sqlite3, 4 tools + 3 resources. |
| 8 | `@hinha/libsql-mcp` | **Partially Correct** | Real package, 7 tools, but does NOT support `file://` URLs for local SQLite. |
| 9 | `@node2flow/sqlite-mcp` | **Correct** | All claims verified: local SQLite + remote Turso, 15 tools. |
| 10 | Continue.dev MCP config format | **Mostly Correct** | Format verified but standalone MCP configs go in `.continue/mcpServers/` directory with extra metadata. |

---

## Oracle MCP Servers

### 1. `mcp/oracle` Docker Image

**Verdict: Partially Correct**

- **Docker Hub:** `mcp/oracle` ([hub.docker.com/mcp/server/oracle/manual](https://hub.docker.com/mcp/server/oracle/manual))
- **Published by:** Docker/MCP organization (NOT Oracle Corporation). The image is listed under the `mcp` Docker Hub namespace.
- **Author:** @samscarrow ([github.com/samscarrow/oracle-mcp-server](https://github.com/samscarrow/oracle-mcp-server))
- **License:** MIT
- **Pull count:** ~8,500+
- **Description:** "Connect to Oracle databases via MCP, providing secure read-only access with support for schema exploration"
- **Verified tools (6):**

| Tool | Description |
|---|---|
| `list_schemas` | List all schemas in the database |
| `list_tables` | List tables in a schema (with pattern matching) |
| `describe_table` | Get table structure (columns, data types, constraints) |
| `execute_query` | Execute read-only SQL queries (max rows configurable, default 1000) |
| `get_table_constraints` | Get PK, FK, unique, and check constraints |
| `get_table_indexes` | Get indexes for a specific table |

- **Transport:** stdio (via Docker `docker run -i --rm`)

**Discrepancy:** The claim stated "Oracle actually publish an official Docker image at `mcp/oracle`." Oracle Corporation does NOT publish this image. It is published under the `mcp` namespace on Docker Hub by a community author (@samscarrow), maintained by Docker Inc., and distributed as an official MCP org image. A separate Oracle-published image DOES exist at `ghcr.io/oracle/mcp/oracle-db-doc:latest` but that is for Oracle Database *documentation* (RAG), not database access.

**Configuration example for Continue.dev:**

```yaml
name: Oracle MCP
version: 0.0.1
schema: v1
mcpServers:
  - name: oracle
    command: docker
    args:
      - run
      - -i
      - --rm
      - mcp/oracle
    env:
      ORACLE_CONNECTION_STRING: host:1521/service
      ORACLE_USER: readonly_user
      ORACLE_PASSWORD: ${{ secrets.ORACLE_PASSWORD }}
```

---

### 2. Oracle SQL Developer VS Code Extension MCP

**Verdict: Partially Correct**

- **Extension:** [Oracle SQL Developer for VS Code](https://marketplace.visualstudio.com/items?itemName=Oracle.sql-developer) (v25.2.0+)
- **Source:** Oracle Corporation, official extension
- **What it does:** Ships SQLcl with a built-in MCP server that auto-registers for GitHub Copilot (Agent mode) and can be manually configured for Cline, Claude, Cursor, etc.

**Verified tools (5, per Oracle docs v25.3):**

| Tool | Description |
|---|---|
| `list-connections` | Discovers and lists all saved Oracle Database connections on your machine |
| `connect` | Establishes a connection to a specified named connection |
| `disconnect` | Terminates the current active connection |
| `run-sql` | Executes standard SQL queries and PL/SQL code blocks |
| `run-sqlcl` | Executes SQLcl-specific commands and extensions |

**Discrepancies:**

1. **`run-sql-asynch`:** The original claim listed `run-sql-asynch` as a tool. This tool is NOT present in the official Oracle 25.3 documentation ([SQLcl MCP Server Tools](https://docs.oracle.com/en/database/oracle/sql-developer-vscode/25.3/sqdnx/sqlcl-mcp-server-tools.html)). Only 5 tools are listed. Some community blogs may reference a 6th tool, but the official docs confirm only 5.

2. **"Configure Cline SQLcl MCP" command palette action:** This IS real. Oracle PM Jeff Smith documented it at [thatjeffsmith.com](https://www.thatjeffsmith.com/archive/2025/11/using-sqlcl-in-sql-developer-for-vs-code-for-mcp-with-cline/). It automatically writes the MCP config into Cline's `cline_mcp_settings.json`. However, there is also a separate command palette action "Oracle SQL Developer: Register SQLcl MCP Server" for Copilot registration. The extension has multiple command palette actions depending on the target AI agent.

3. **Version:** The claim said v25.2.0+. The latest Oracle docs reference v25.3 as of mid-2025. SQLcl 25.2 was released July 2025.

**Prerequisites:**
- VS Code 1.102+
- Oracle SQL Developer Extension v25.2+
- Java 17+
- Oracle Database 12c+ (23ai Free recommended)

**Configuration for Continue.dev:**

The extension auto-configures for GitHub Copilot automatically. For Continue (and other agents like Cline/Claude/Cursor), you need to manually add the MCP config. There are two approaches:

**Approach A: Extension-bundled Java (recommended for VS Code users)**

1. Install the Oracle SQL Developer Extension from the VS Code Marketplace
2. Set up your database connections in the extension's DB panel (the MCP server exposes saved connections via `list-connections`)
3. Open Command Palette (`Cmd+Shift+P`) and run **"Configure Cline SQLcl MCP"** — this generates the correct Java invocation with paths into the extension directory
4. Translate the generated JSON into Continue's YAML format in `config.yaml`:

```yaml
mcpServers:
  - name: SQLcl - SQL Developer
    command: /Users/<you>/.vscode/extensions/oracle.sql-developer-25.4.1-darwin-arm64/dbtools/jdk/Contents/Home/bin/java
    args:
      - "-Djava.awt.headless=true"
      - "-Djava.net.useSystemProxies=true"
      - "-Duser.language=en"
      - "-p"
      - "/Users/<you>/.vscode/extensions/oracle.sql-developer-25.4.1-darwin-arm64/dbtools/launch/:/Users/<you>/.vscode/extensions/oracle.sql-developer-25.4.1-darwin-arm64/dbtools/sqlcl/launch/"
      - "--add-modules"
      - "ALL-DEFAULT"
      - "-m"
      - "com.oracle.dbtools.launch"
      - "sql"
      - "-mcp"
      - "-tnsadmin"
      - "/Users/<you>"
```

Or as a standalone `.yaml` file in `.continue/mcpServers/oracle-sqldeveloper.yaml`:

```yaml
name: Oracle SQL Developer MCP
version: 0.0.1
schema: v1
mcpServers:
  - name: SQLcl - SQL Developer
    command: /Users/<you>/.vscode/extensions/oracle.sql-developer-25.4.1-darwin-arm64/dbtools/jdk/Contents/Home/bin/java
    args:
      - "-Djava.awt.headless=true"
      - "-Djava.net.useSystemProxies=true"
      - "-Duser.language=en"
      - "-p"
      - "/Users/<you>/.vscode/extensions/oracle.sql-developer-25.4.1-darwin-arm64/dbtools/launch/:/Users/<you>/.vscode/extensions/oracle.sql-developer-25.4.1-darwin-arm64/dbtools/sqlcl/launch/"
      - "--add-modules"
      - "ALL-DEFAULT"
      - "-m"
      - "com.oracle.dbtools.launch"
      - "sql"
      - "-mcp"
      - "-tnsadmin"
      - "/Users/<you>"
```

**Approach B: Standalone SQLcl (avoids extension-update breakage)**

If you install SQLcl directly instead of relying on the extension's bundled Java, the paths are version-independent:

```yaml
mcpServers:
  - name: SQLcl
    command: /opt/sqlcl/bin/sql
    args:
      - "-mcp"
    env:
      TNS_ADMIN: /Users/<you>/oracle/tns
```

**Important caveats:**
- Extension updates change the version string in the path (e.g. `25.4.1` → `25.5.0`), silently breaking the MCP server. You'll need to re-run "Configure Cline SQLcl MCP" and update your config after each extension update. Approach B avoids this entirely.
- Default query timeout is 60 seconds.
- MCP only works in agent mode in Continue.
- Only configure ONE Oracle MCP server at a time — don't run both the extension-based and standalone SQLcl MCP simultaneously.

---

### 3. `mcp-oracle-database` by tannerpace

**Verdict: Correct**

- **npm:** [mcp-oracle-database](https://www.npmjs.com/package/mcp-oracle-database) (v4.1.3)
- **Author:** Tanner B (tannerpace)
- **Repository:** [github.com/tannerpace/mcp-oracle-database](https://github.com/tannerpace/mcp-oracle-database)
- **License:** AGPL v3
- **Description:** "MCP server for database queries — enables AI assistants to execute read-only SQL queries against Oracle databases"

**Verified claims:**
- Uses `node-oracledb` Thin Mode (pure JavaScript, no Oracle Instant Client required) -- **CORRECT**. Confirmed by the project's PLAN.md and README.
- Read-only access -- **CORRECT**. Has `ENFORCE_READ_ONLY_QUERIES` flag (default: `true`).
- Multiple tools including schema introspection, query execution, caching, audit logging.

**Tools include:**
- Schema introspection (5 specialized discovery tools)
- `execute_query` for read-only SQL
- LRU caching with 5-minute TTL
- Query timeout protection
- Row limit enforcement

**Installation:**
```bash
npm install -g mcp-oracle-database
```

**Configuration example for Continue.dev:**

```yaml
name: Oracle MCP Server
version: 0.0.1
schema: v1
mcpServers:
  - name: oracleDatabase
    command: npx
    args:
      - -y
      - mcp-oracle-database
    env:
      ORACLE_CONNECTION_STRING: localhost:1521/XE
      ORACLE_USER: readonly_user
      ORACLE_PASSWORD: ${{ secrets.ORACLE_PASSWORD }}
      ORACLE_TIMEZONE: UTC
      ENFORCE_READ_ONLY_QUERIES: "true"
```

---

### 4. `oracle-sqlplus-mcp`

**Verdict: Correct**

- **npm:** [oracle-sqlplus-mcp](https://www.npmjs.com/package/oracle-sqlplus-mcp) (v1.0.2)
- **Author:** Not listed (no author field in package.json)
- **Repository:** None listed
- **Description:** "Oracle Database MCP Server using sqlplus"
- **Keywords:** mcp, oracle, sqlplus, database

**Verified claims:**
- Uses `sqlplus` as the backend -- **CORRECT**. No Oracle Instant Client Node.js bindings required.
- 8 tools -- **CORRECT**.

**Verified tools (8):**

| Tool | Description |
|---|---|
| `test_connection` | Test connectivity and return Oracle version |
| `list_schemas` | List all schemas with table counts |
| `list_tables` | List tables, optionally filtered by schema or name pattern |
| `describe_table` | Show columns, data types, nullable, primary keys |
| `get_table_sample` | Fetch sample rows from a table |
| `execute_query` | Run any SELECT query |
| `execute_ddl` | Run DDL/DML (INSERT, UPDATE, DELETE, CREATE, etc.) |
| `list_procedures` | List stored procedures, functions, packages |

**Discrepancy:** The claim implied this might be read-only (like the other Oracle MCP servers). It is NOT read-only -- it explicitly includes `execute_ddl` for INSERT, UPDATE, DELETE, CREATE, etc.

**Configuration example for Continue.dev:**

```yaml
name: Oracle sqlplus MCP
version: 0.0.1
schema: v1
mcpServers:
  - name: oracle-sqlplus
    command: npx
    args:
      - -y
      - oracle-sqlplus-mcp
    env:
      ORACLE_CONNECTION: username/password@host:port/servicename
```

---

## SQLite MCP Servers

### 5. `@modelcontextprotocol/server-sqlite` (Official MCP SQLite Server)

**Verdict: Incorrect (as currently stated)**

- **npm:** NOT available. `https://registry.npmjs.org/@modelcontextprotocol/server-sqlite/latest` returns "Not Found"
- **Status:** The SQLite server was part of the official `modelcontextprotocol/servers` monorepo but has been **ARCHIVED** and moved to the `servers-archived` repository.
- **Docker Hub:** `mcp/sqlite` exists as a Docker image but is a Python-based reference implementation that is no longer actively maintained.
- **Language:** Python (not TypeScript, unlike most current official MCP servers)

**What the claim got wrong:**
1. The package is NOT available on npm.
2. It is no longer maintained as part of the active MCP servers.
3. It was a Python package (`mcp-server-sqlite`, not `@modelcontextprotocol/server-sqlite` -- the `@modelcontextprotocol/server-*` convention is for TypeScript servers).

**What existed (for historical reference):**

| Tool | Description |
|---|---|
| `read_query` | Execute SELECT queries |
| `write_query` | Execute INSERT, UPDATE, DELETE |
| `create_table` | Create new tables |
| `list_tables` | List all tables |
| `describe_table` | Get schema info for a specific table |
| `append_insight` | Add business insights to a memo |

**Recommendation:** Use one of the actively maintained community alternatives (#6-9 below) instead.

---

### 6. `@achmadya-dev/mcp-sqlite-query`

**Verdict: Correct**

- **npm:** [@achmadya-dev/mcp-sqlite-query](https://www.npmjs.com/package/@achmadya-dev/mcp-sqlite-query) (v0.3.2)
- **Author:** achmadya
- **Repository:** [github.com/achmadya-dev/mcp-sqlite-query](https://github.com/achmadya-dev/mcp-sqlite-query)
- **Description:** "MCP server for SQLite to run SQL queries via stdio (read-only by default)"

**Verified claims:**
- Uses Node.js built-in `node:sqlite` -- **CORRECT**. Requires Node.js >= 22.5.0.
- Read-only by default -- **CORRECT**. Write operations require explicit environment flags.

**Verified tools (5):**

| Tool | Allowed Statements | Env Flag Required |
|---|---|---|
| `sqlite_select` | SELECT, PRAGMA, EXPLAIN | None (always on) |
| `sqlite_insert` | INSERT, REPLACE | `ALLOW_INSERT_OPERATION` |
| `sqlite_update` | UPDATE | `ALLOW_UPDATE_OPERATION` |
| `sqlite_delete` | DELETE | `ALLOW_DELETE_OPERATION` |
| `sqlite_ddl` | CREATE, ALTER, DROP, VACUUM | `ALLOW_DDL_OPERATION` |

**Security features:**
- One SQL statement per request (parser validates before execution)
- Always blocked: `XP_CMDSHELL`, `EXEC`, `EXECUTE`, `PREPARE`, `DEALLOCATE`, `ATTACH DATABASE`, `LOAD_FILE`, `INTO OUTFILE`, `COPY ... PROGRAM`
- SELECT results capped by `SQLITE_MAX_ROWS` (default: 500)

**Configuration example for Continue.dev:**

```yaml
name: SQLite MCP (achmadya)
version: 0.0.1
schema: v1
mcpServers:
  - name: sqlite-query
    command: npx
    args:
      - -y
      - "@achmadya-dev/mcp-sqlite-query"
    env:
      SQLITE_DB_PATH: /absolute/path/to/database.db
      SQLITE_MAX_ROWS: "500"
```

---

### 7. `@graduenz/mcp-sqlite-server`

**Verdict: Correct**

- **npm:** [@graduenz/mcp-sqlite-server](https://www.npmjs.com/package/@graduenz/mcp-sqlite-server) (v1.1.0)
- **Author:** Not listed (no author field)
- **Repository:** [github.com/graduenz/mcp-sqlite-server](https://github.com/graduenz/mcp-sqlite-server)
- **License:** MIT
- **Description:** "MCP server for SQLite databases using better-sqlite3"

**Verified claims:**
- Uses `better-sqlite3` -- **CORRECT**. Confirmed in README and package dependencies.
- Read-only mode -- **CORRECT**. Has `readonly` config option (default: false).

**Verified tools (4):**

| Tool | Description |
|---|---|
| `query` | Execute read-only SQL (SELECT) queries, return JSON |
| `execute` | Execute write SQL (INSERT, UPDATE, DELETE, CREATE TABLE). Disabled in read-only mode. |
| `list_tables` | List all tables and views |
| `describe_table` | Get columns, types, constraints, indexes for a table |

**Verified resources (3):**
- `sqlite://schema` -- Full DDL
- `sqlite://tables` -- Table listing
- `sqlite://tables/{name}/schema` -- Per-table schema

**Unique feature:** Uses a `.mcp-sqlite.json` project-level config file instead of environment variables for database settings. This keeps database paths out of MCP client config.

**Configuration example for Continue.dev:**

```yaml
name: SQLite MCP (graduenz)
version: 0.0.1
schema: v1
mcpServers:
  - name: sqlite-server
    command: npx
    args:
      - -y
      - "@graduenz/mcp-sqlite-server"
    cwd: /absolute/path/to/workspace
```

Then create `.mcp-sqlite.json` in the workspace root:
```json
{
  "database": "./data/batch.db",
  "readonly": false,
  "wal": true
}
```

---

### 8. `@hinha/libsql-mcp`

**Verdict: Partially Correct**

- **npm:** [@hinha/libsql-mcp](https://www.npmjs.com/package/@hinha/libsql-mcp) (v0.0.1)
- **Author:** Not listed (no author field)
- **Repository:** [github.com/hinha/libsql-client](https://github.com/hinha/libsql-client)
- **Description:** "libSQL/Turso MCP server -- full CRUD connector for AI agents"

**Verified claims:**
- Supports Turso cloud -- **CORRECT**. Supports `libsql://`, `https://`, and `wss://` URLs.
- Exposes `execute`, `batch`, `list_tables`, `describe_table`, `migrate`, `database_overview` -- **CORRECT**, plus `transaction` (7 tools total).

**Discrepancy:** The claim stated it supports "local SQLite via `file://` URLs." This is **INCORRECT**. The README only lists three supported URL schemes: `libsql://`, `https://`, and `wss://`. There is NO `file://` support documented. The server is focused on remote/libSQL-server databases only, not local SQLite files. The README explicitly positions it as a "Remote Turso & Self-hosted" tool.

**Verified tools (7):**

| Tool | Description |
|---|---|
| `execute` | Execute a single SQL statement |
| `batch` | Execute multiple SQL statements atomically |
| `transaction` | Interactive transactions with commit/rollback |
| `list_tables` | List all tables and views |
| `describe_table` | Get column schema for a table |
| `migrate` | Run database migrations sequentially |
| `database_overview` | All tables with row counts |

**Verified resources (3):**
- `turso://schema`
- `turso://tables`
- `turso://tables/{name}`

**Configuration example for Continue.dev:**

```yaml
name: Turso MCP
version: 0.0.1
schema: v1
mcpServers:
  - name: libsql
    command: npx
    args:
      - -y
      - "@hinha/libsql-mcp@latest"
    env:
      LIBSQL_URL: libsql://your-db.turso.io
      LIBSQL_AUTH_TOKEN: ${{ secrets.TURSO_AUTH_TOKEN }}
```

---

### 9. `@node2flow/sqlite-mcp`

**Verdict: Correct**

- **npm:** [@node2flow/sqlite-mcp](https://www.npmjs.com/package/@node2flow/sqlite-mcp) (v2.0.1)
- **Author:** Node2Flow (node2flow@gmail.com)
- **Repository:** [github.com/node2flow-th/sqlite-mcp-community](https://github.com/node2flow-th/sqlite-mcp-community)
- **License:** MIT
- **Description:** "MCP server for SQLite databases -- local files (better-sqlite3) or remote Turso/libSQL via URL. 15 tools for query, schema, indexes, and optimization"

**Verified claims:**
- Supports local SQLite and remote Turso -- **CORRECT**. Uses `SQLITE_DB_PATH` for local files (better-sqlite3) and `SQLITE_DB_URL` + `SQLITE_AUTH_TOKEN` for remote Turso.
- Both modes work in a single package -- **CORRECT**. Config variable priority: `SQLITE_DB_URL` > `SQLITE_DB_PATH`.

**Verified tools (15):**

| Category | Tool | Description |
|---|---|---|
| Query | `sqlite_query` | Execute SELECT query, return JSON |
| Query | `sqlite_execute` | Execute write statement |
| Query | `sqlite_run_script` | Execute multiple statements in transaction |
| Schema | `sqlite_list_tables` | List all tables with row counts |
| Schema | `sqlite_describe_table` | Get columns, types, constraints |
| Schema | `sqlite_list_indexes` | List indexes for a table |
| Schema | `sqlite_list_foreign_keys` | List foreign key constraints |
| Mgmt | `sqlite_create_table` | Create new table |
| Mgmt | `sqlite_alter_table` | Add/rename column, rename table |
| Mgmt | `sqlite_drop_table` | Drop a table |
| Index | `sqlite_create_index` | Create index on columns |
| Index | `sqlite_drop_index` | Drop an index |
| DB | `sqlite_get_info` | Database metadata |
| DB | `sqlite_vacuum` | Optimize and compact |
| DB | `sqlite_integrity_check` | Check database health |

**Additional features:**
- HTTP mode (`--http` flag) for remote access on port 3000
- Docker support with docker-compose
- Cloudflare Worker deployment for remote-only mode

**Configuration example for Continue.dev (local):**

```yaml
name: SQLite MCP (node2flow)
version: 0.0.1
schema: v1
mcpServers:
  - name: sqlite
    command: npx
    args:
      - -y
      - "@node2flow/sqlite-mcp"
    env:
      SQLITE_DB_PATH: /absolute/path/to/database.db
```

**Configuration example for Continue.dev (Turso):**

```yaml
name: Turso MCP (node2flow)
version: 0.0.1
schema: v1
mcpServers:
  - name: sqlite
    command: npx
    args:
      - -y
      - "@node2flow/sqlite-mcp"
    env:
      SQLITE_DB_URL: libsql://your-db.turso.io
      SQLITE_AUTH_TOKEN: ${{ secrets.TURSO_AUTH_TOKEN }}
```

---

## Continue.dev MCP Configuration Format (Verified)

**Verdict: Mostly Correct**

### What was verified:

**Config file name:**
- The main Continue config file IS `config.yaml` (located at project: `.continue/config.yaml` or global: `~/.continue/config.yaml`). **CORRECT.**

**MCP servers format:**
- `mcpServers` is defined as a list with `name`, `command`, `args`, `env` fields. **CORRECT.**

**Example format:**
```yaml
mcpServers:
  - name: SQLite MCP
    command: npx
    args:
      - "-y"
      - "mcp-sqlite"
      - "/path/to/database.db"
    env:
      API_KEY: ${{ secrets.MY_SECRET }}
```

**Secrets:**
- Secrets use `${{ secrets.NAME }}` syntax. **CORRECT.** Resolved from `.env` file at project root, `.continue/.env`, or `~/.continue/.env`.

### Clarifications and additional details not in the original claim:

**1. Two ways to define MCP servers:**

- **Inline** in `config.yaml` -- add `mcpServers` as a list directly.
- **Standalone files** in `.continue/mcpServers/*.yaml` (or `*.json`) -- requires additional metadata block.

**2. Standalone file format requires metadata:**
```yaml
name: Display Name
version: 0.0.1
schema: v1
mcpServers:
  - name: Server Name
    command: npx
    args: [...]
```

This is NOT mentioned in the original claim. Files in `.continue/mcpServers/` without the metadata block will not be parsed correctly.

**3. MCP only works in Agent mode** -- not in chat mode or edit mode. This is an important restriction not mentioned in the original claim.

**4. Restart required** after adding/modifying MCP config files.

**5. Transport types supported:**
- `stdio` (default) -- `command`, `args`, `env`, `cwd`, `connectionTimeout`
- `sse` -- `type: sse`, `url`, `requestOptions.headers`
- `streamable-http` -- `type: streamable-http`, `url`, `requestOptions.headers`

**6. New in 2025:** `apiKey` field for simplified Bearer token auth (PR #8120).

**7. JSON config format also supported** (PR #7956, Sept 2025). Place `.json` files in `.continue/mcpServers/`. Two formats accepted: single-server or Claude-style `mcpServers` object.

**8. `uses` field:** Can reference shared MCP server blocks via `uses: continuedev/continue-docs-mcp`.

---

## Quick-Reference: Recommended MCP Servers for This Project

Since this project uses SQLite (`data/batch.db`), these are the best fits:

| Priority | Server | Reason |
|---|---|---|
| 1 | `@node2flow/sqlite-mcp` | Most fully featured (15 tools), actively maintained, dual local/remote |
| 2 | `@graduenz/mcp-sqlite-server` | Project-level `.mcp-sqlite.json` config, clean separation of concerns |
| 3 | `@achmadya-dev/mcp-sqlite-query` | Best security model (read-only by default, per-statement-type gates) |

---

## Sources

- [mcp/oracle on Docker Hub](https://hub.docker.com/mcp/server/oracle/manual) -- verified via Docker Hub API
- [Oracle SQLcl MCP Server Tools (v25.3 docs)](https://docs.oracle.com/en/database/oracle/sql-developer-vscode/25.3/sqdnx/sqlcl-mcp-server-tools.html)
- [Jeff Smith (Oracle PM): SQLcl MCP with Cline](https://www.thatjeffsmith.com/archive/2025/11/using-sqlcl-in-sql-developer-for-vs-code-for-mcp-with-cline/)
- [Jeff Smith (Oracle PM): Options for Oracle MCP Server in VS Code](https://www.thatjeffsmith.com/archive/2026/02/options-for-our-local-oracle-database-mcp-server-in-vs-code/)
- [mcp-oracle-database on npm](https://www.npmjs.com/package/mcp-oracle-database) -- verified via npm registry API
- [mcp-oracle-database on GitHub](https://github.com/tannerpace/mcp-oracle-database)
- [oracle-sqlplus-mcp on npm](https://www.npmjs.com/package/oracle-sqlplus-mcp) -- verified via npm registry API
- [modelcontextprotocol/servers on GitHub](https://github.com/modelcontextprotocol/servers) -- verified SQLite server is archived
- [@achmadya-dev/mcp-sqlite-query on npm](https://www.npmjs.com/package/@achmadya-dev/mcp-sqlite-query) -- verified via npm registry API
- [@graduenz/mcp-sqlite-server on npm](https://www.npmjs.com/package/@graduenz/mcp-sqlite-server) -- verified via npm registry API
- [@graduenz/mcp-sqlite-server on GitHub](https://github.com/graduenz/mcp-sqlite-server)
- [@hinha/libsql-mcp on npm](https://www.npmjs.com/package/@hinha/libsql-mcp) -- verified via npm registry API
- [@hinha/libsql-mcp on GitHub](https://github.com/hinha/libsql-client)
- [@node2flow/sqlite-mcp on npm](https://www.npmjs.com/package/@node2flow/sqlite-mcp) -- verified via npm registry API
- [@node2flow/sqlite-mcp on GitHub](https://github.com/node2flow-th/sqlite-mcp-community)
- [Continue.dev MCP Configuration Guide](https://docs.continue.dev/customize/deep-dives/mcp)
- [Continue.dev Configuration Reference](https://docs.continue.dev/guides/configuring-models-rules-tools)
