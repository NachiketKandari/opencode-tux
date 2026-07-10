#!/usr/bin/env python3
"""
pc_preproc.py - Pro*C to C+SQLite Preprocessor

Converts Oracle Pro*C (.pc) files with EXEC SQL syntax into plain C that
compiles against SQLite3. Uses snprintf-based host variable substitution.

Design principle: any real .pc file should work as long as the Oracle SQL
is SQLite-compatible. Oracle-specific functions (DECODE, CONNECT BY, etc.)
will need manual adjustment.

Supported EXEC SQL patterns:
  INCLUDE SQLCA / INCLUDE ORACA
  BEGIN/END DECLARE SECTION (tracks array vs scalar vars)
  CONNECT :uid IDENTIFIED BY :pwd
  CREATE TABLE ... / CREATE INDEX ...
  INSERT INTO ... VALUES (:hv, ...)
  FOR :count INSERT INTO ... VALUES (:hv_arr, ..., :hv_scalar, ...)
  SELECT ... INTO :hv, ... FROM ...
  UPDATE ... SET col = :hv WHERE ...
  DECLARE c CURSOR FOR SELECT ...
  OPEN c / FETCH c INTO :hv, ... / CLOSE c
  COMMIT / ROLLBACK / COMMIT WORK RELEASE
  WHENEVER SQLERROR GOTO label / CONTINUE / DO func()
  VARCHAR declarations → C struct

Usage:
  python3 scripts/preproc.py pc/batch_ingest.pc -o build/
  python3 scripts/preproc.py pc/*.pc -o build/
"""

import re
import os
import sys
import argparse
from typing import List, Tuple, Optional, Dict, Set

# ─── Logging ────────────────────────────────────────────────────────────────

VERBOSE = False

def log(msg: str, *args):
    """Emit a preprocessing log message to stderr."""
    if VERBOSE:
        if args:
            print(f"  [preproc] {msg % args}", file=sys.stderr)
        else:
            print(f"  [preproc] {msg}", file=sys.stderr)

def warn(msg: str, *args):
    """Emit a warning to stderr (always shown)."""
    if args:
        print(f"  [preproc:WARN] {msg % args}", file=sys.stderr)
    else:
        print(f"  [preproc:WARN] {msg}", file=sys.stderr)

def error(msg: str, *args):
    """Emit an error to stderr (always shown)."""
    if args:
        print(f"  [preproc:ERROR] {msg % args}", file=sys.stderr)
    else:
        print(f"  [preproc:ERROR] {msg}", file=sys.stderr)


# ─── Host variable type inference ──────────────────────────────────────────

def infer_format_spec(var_name: str, declared_types: Dict[str, str] = None) -> str:
    """Infer a printf/sqlite format for a host variable.
    Uses declared C types first, falls back to naming conventions.
    """
    if declared_types and var_name in declared_types:
        ctype = declared_types[var_name]
        if ctype in ('int', 'short', 'long'):
            return '%d'
        if ctype in ('double', 'float'):
            return '%f'
        return '%s'

    # Fallback: naming convention heuristics
    int_patterns = ('_id', '_count', '_size', '_code', '_num', '_rows',
                    '_ingested', '_processed', 'h_total_', 'h_valid_',
                    'h_invalid_', 'h_empty_', 'h_short_', 'h_transformed_',
                    'h_error_', 'h_skip_', 'h_word_', 'h_top_',
                    'h_report_len', 'h_agg_', 'h_batch_size', 'h_post_count',
                    'total', 'row_count', 'batch_num')
    for p in int_patterns:
        if p in var_name:
            return '%d'
    return '%s'


def value_for_snprintf(var_name: str) -> str:
    """Return the snprintf argument for a host variable."""
    if var_name in ('uid', 'pwd'):
        return f'{var_name}.arr'
    return var_name


# ─── SQL Parser Helpers ─────────────────────────────────────────────────────

def parse_comma_list(text: str) -> List[str]:
    """Split comma-separated items respecting nested parentheses."""
    items = []
    depth = 0
    current = ''
    for ch in text:
        if ch == '(':
            depth += 1
            current += ch
        elif ch == ')':
            depth -= 1
            current += ch
        elif ch == ',' and depth == 0:
            items.append(current.strip())
            current = ''
        else:
            current += ch
    if current.strip():
        items.append(current.strip())
    return items


# ─── Pro*C Preprocessor ─────────────────────────────────────────────────────

class ProCPreprocessor:
    def __init__(self, source_file: str):
        self.source_file = source_file
        self.error_mode = "continue"  # "continue" | "goto" | "do"
        self.error_label: Optional[str] = None
        self.error_handler: Optional[str] = None
        self.declared_types: Dict[str, str] = {}  # var_name → C type
        self.cursors: Dict[str, str] = {}    # cursor_name → SELECT SQL text
        self.array_vars: Set[str] = set()     # variables declared as arrays
        self.in_declare = False
        self.output: List[str] = []
        self.warnings = 0
        self.unhandled = 0

    def emit(self, code: str):
        self.output.append(code)

    def preprocess(self, text: str) -> str:
        """Main entry point: convert Pro*C text to C+SQLite."""
        lines = text.split('\n')
        i = 0
        while i < len(lines):
            stripped = lines[i].lstrip()
            if stripped.startswith('EXEC SQL'):
                i = self._handle_exec_sql(lines, i)
            elif stripped.startswith('EXEC ORACLE'):
                self.emit(f'/* {lines[i].strip()} -- skipped */')
                i += 1
            else:
                transformed = self._handle_regular_line(lines[i])
                self.emit(transformed)
                i += 1

        if self.unhandled > 0:
            warn("Source '%s': %d EXEC SQL statements fell back to sqlite3_exec",
                 self.source_file, self.unhandled)

        header = self._generate_preamble()
        body = '\n'.join(self.output)
        return header + body + '\n/* End of generated code. */\n'

    def _handle_regular_line(self, line: str) -> str:
        """Process a non-EXEC line: rewrite VARCHAR, skip duplicate includes."""
        # Skip lines that include headers we provide
        stripped = line.strip()
        if re.match(r'#include\s+[<"]atmi\.h[>"]', stripped):
            return f'/* {stripped} -- provided by preproc */'
        if re.match(r'#include\s+[<"]userlog\.h[>"]', stripped):
            return f'/* {stripped} -- provided by preproc */'
        if re.match(r'#include\s+[<"]fml\.h[>"]', stripped):
            return f'/* {stripped} -- not used with SQLite */'

        # Track array declarations in declare section
        if self.in_declare:
            line_stripped = line.strip()
            # Detect numeric array: type name[size] → array (for bulk inserts)
            m = re.match(r'\s*(int|double|float|short|long)\s+(\w+)\s*\[', line)
            if m:
                self.array_vars.add(m.group(2))
                self.declared_types[m.group(2)] = m.group(1)
                log("Found array var: %s (%s[])", m.group(2), m.group(1))
                return self._rewrite_varchar(line)
            # Detect 2D char array: char name[size1][size2] → array of strings
            m = re.match(r'\s*char\s+(\w+)\s*\[[^\]]*\]\s*\[', line)
            if m:
                self.array_vars.add(m.group(1))
                self.declared_types[m.group(1)] = 'char*'
                log("Found string array var: %s (char[][])", m.group(1))
                return self._rewrite_varchar(line)
            # Detect 1D char array: char name[N] → string
            m = re.match(r'\s*char\s+(\w+)\s*\[[^\]]*\]\s*;', line)
            if m:
                self.declared_types[m.group(1)] = 'char*'
                log("Found char array var: %s (char[N])", m.group(1))
                return self._rewrite_varchar(line)
            # Detect: type name; → scalar
            m = re.match(r'\s*(int|char|double|float|short|long)\s+(\w+)\s*;', line)
            if m:
                self.declared_types[m.group(2)] = m.group(1)
                log("Found scalar var: %s (%s)", m.group(2), m.group(1))
                return self._rewrite_varchar(line)

        # Rewrite VARCHAR
        return self._rewrite_varchar(line)

    def _generate_preamble(self) -> str:
        # Derive a unique prefix from the source filename
        prefix = os.path.splitext(self.source_file)[0]
        return (
            f'/* {"="*60}\n'
            f' * GENERATED BY pc_preproc.py\n'
            f' * Source: {self.source_file}\n'
            f' * Array vars detected: {sorted(self.array_vars) if self.array_vars else "none"}\n'
            f' * Cursors declared: {sorted(self.cursors.keys()) if self.cursors else "none"}\n'
            f' * {"="*60} */\n\n'
            '#include <stdio.h>\n'
            '#include <stdlib.h>\n'
            '#include <string.h>\n'
            '#include <time.h>\n'
            '#include <sqlite3.h>\n'
            '#include "sqlca.h"\n'
            '#include "atmi.h"\n'
            '#include "userlog.h"\n'
            '\n'
            '/* Rename tpsvrinit/tpsvrdone to avoid linker conflicts.\n'
            '   In real Tuxedo, each .pc file is a separate server process. */\n'
            f'#define tpsvrinit {prefix}_svrinit\n'
            f'#define tpsvrdone  {prefix}_svrdone\n'
            '\n'
            'static sqlite3 *db = NULL;\n'
            '\n'
            '/* ── Preprocessor helper macros ── */\n'
            '#define ERR_GOTO(label) do { \\\n'
            '    if (sqlca.sqlcode < 0) { \\\n'
            '        userlog("SQL ERROR [sqlcode=%ld]: %s", \\\n'
            '                sqlca.sqlcode, sqlca.sqlerrm.sqlerrmc); \\\n'
            '        goto label; \\\n'
            '    } \\\n'
            '} while(0)\n'
            '\n'
        )

    def _rewrite_varchar(self, line: str) -> str:
        m = re.match(r'(\s*)VARCHAR\s+(\w+)\[(\d+)\]\s*;(.*)', line)
        if m:
            return f'{m.group(1)}struct {{ unsigned short len; char arr[{m.group(3)}]; }} {m.group(2)};{m.group(4)}'
        return line

    def _collect_stmt(self, lines: List[str], start: int) -> Tuple[int, str]:
        """Collect a multi-line EXEC SQL statement ending with ';'."""
        first = lines[start].strip()
        if first.startswith('EXEC SQL '):
            first = first[9:]
        else:
            first = first[8:]
        parts = [first]
        i = start
        while i < len(lines):
            if lines[i].rstrip().endswith(';'):
                break
            i += 1
            if i < len(lines):
                parts.append(lines[i].strip())
        full = ' '.join(parts).rstrip(';').strip()
        log("EXEC SQL: %s", full[:100] + ('...' if len(full) > 100 else ''))
        return i + 1, full

    def _handle_exec_sql(self, lines: List[str], idx: int) -> int:
        i, stmt = self._collect_stmt(lines, idx)
        su = stmt.upper().strip()

        if su == 'INCLUDE SQLCA':
            self.emit('/* EXEC SQL INCLUDE SQLCA -- handled by sqlca.h */')
        elif su == 'INCLUDE ORACA':
            self.emit('/* EXEC SQL INCLUDE ORACA -- not needed for SQLite */')
        elif su == 'BEGIN DECLARE SECTION':
            self.in_declare = True
            self.emit('/* EXEC SQL BEGIN DECLARE SECTION */')
        elif su == 'END DECLARE SECTION':
            self.in_declare = False
            self.emit('/* EXEC SQL END DECLARE SECTION */')
            log("Declare section complete. Array vars: %s", sorted(self.array_vars))
        elif su.startswith('WHENEVER SQLERROR'):
            self._gen_whenever(stmt)
        elif su.startswith('CONNECT'):
            self._gen_connect(stmt)
        elif su.startswith('COMMIT'):
            self._gen_commit(stmt)
        elif su.startswith('ROLLBACK'):
            self._gen_rollback(stmt)
        elif su.startswith('CREATE TABLE') or su.startswith('CREATE INDEX'):
            self._gen_exec_sql(stmt)
        elif su.startswith('INSERT'):
            self._gen_insert(stmt)
        elif su.startswith('FOR'):
            self._gen_array_insert(stmt)
        elif su.startswith('SELECT'):
            self._gen_select_into(stmt)
        elif su.startswith('UPDATE'):
            self._gen_update(stmt)
        elif su.startswith('DELETE'):
            self._gen_update(stmt)  # same pattern: hostvar subst + sqlite3_exec
        elif su.startswith('DECLARE') and ('CURSOR' in su.upper()):
            self._gen_declare_cursor(stmt)
        elif su.startswith('OPEN '):
            self._gen_open_cursor(stmt)
        elif su.startswith('FETCH '):
            self._gen_fetch(stmt)
        elif su.startswith('CLOSE '):
            self._gen_close_cursor(stmt)
        else:
            warn("Unrecognized EXEC SQL pattern, falling back to sqlite3_exec: %s",
                 stmt[:80])
            self.unhandled += 1
            self._gen_exec_sql(stmt)
        return i

    # ─── Generators ──────────────────────────────────────────────────

    def _gen_whenever(self, stmt: str):
        su = stmt.upper()
        if 'GOTO' in su:
            m = re.search(r'GOTO\s+(\w+)', stmt, re.IGNORECASE)
            if m:
                self.error_mode = 'goto'
                self.error_label = m.group(1)
                log("Set error mode: goto %s", self.error_label)
        elif 'CONTINUE' in su:
            self.error_mode = 'continue'
            self.error_label = None
            log("Set error mode: continue")
        elif 'DO' in su:
            self.error_mode = 'do'
            m = re.search(r'DO\s+(\w+\s*\([^)]*\))', stmt, re.IGNORECASE)
            if m:
                self.error_handler = m.group(1)
                log("Set error mode: call %s", self.error_handler)
        self.emit(f'/* EXEC SQL {stmt} */')

    def _error_check(self) -> str:
        if self.error_mode == 'goto' and self.error_label:
            return f'ERR_GOTO({self.error_label});'
        elif self.error_mode == 'do' and self.error_handler:
            return f'if (sqlca.sqlcode < 0) {{ {self.error_handler}; }}'
        return ''

    def _gen_connect(self, stmt: str):
        self.emit(f'/* EXEC SQL {stmt} */')
        self.emit('  {')
        self.emit('    int _rc = sqlite3_open("data/batch.db", &db);')
        self.emit('    if (_rc != SQLITE_OK) {')
        self.emit('      sqlca_set_error(_rc, sqlite3_errmsg(db));')
        self.emit('      userlog("CONNECT failed: %s", sqlca.sqlerrm.sqlerrmc);')
        self.emit('    } else {')
        self.emit('      sqlca_set_success(0);')
        self.emit('      sqlite3_exec(db, "PRAGMA journal_mode=WAL", NULL, NULL, NULL);')
        self.emit('      userlog("CONNECT: opened data/batch.db");')
        self.emit('    }')
        self.emit('  }')

    def _gen_commit(self, stmt: str):
        self.emit(f'/* EXEC SQL {stmt} */')
        self.emit('  sqlite3_exec(db, "COMMIT", NULL, NULL, NULL);')
        self.emit('  userlog("COMMIT executed");')
        if 'RELEASE' in stmt.upper():
            self.emit('  sqlite3_close(db);')
            self.emit('  db = NULL;')
            self.emit('  userlog("DB connection closed (RELEASE)");')

    def _gen_rollback(self, stmt: str):
        self.emit(f'/* EXEC SQL {stmt} */')
        self.emit('  sqlite3_exec(db, "ROLLBACK", NULL, NULL, NULL);')
        self.emit('  userlog("ROLLBACK executed");')

    def _gen_exec_sql(self, stmt: str):
        """Direct sqlite3_exec — for DDL and simple SQL without host vars."""
        escaped = stmt.replace('\\', '\\\\').replace('"', '\\"')
        self.emit(f'/* EXEC SQL {stmt} */')
        self.emit('  {')
        self.emit(f'    char *_err = NULL;')
        self.emit(f'    int _rc = sqlite3_exec(db, "{escaped}", NULL, NULL, &_err);')
        self.emit(f'    if (_rc != SQLITE_OK) {{')
        self.emit(f'      sqlca_set_error(_rc, _err ? _err : "SQL error");')
        self.emit(f'      userlog("SQL ERROR: %s", _err ? _err : "unknown");')
        self.emit(f'      if (_err) sqlite3_free(_err);')
        self.emit(f'    }} else {{')
        self.emit(f'      sqlca_set_success(sqlite3_changes(db));')
        self.emit(f'    }}')
        self.emit(f'  }}')
        ec = self._error_check()
        if ec:
            self.emit(f'  {ec}')

    def _build_sqlprintf(self, stmt: str, array_index: Optional[str] = None) -> str:
        """Build a sqlite3_mprintf call from an EXEC SQL statement.

        sqlite3_mprintf %Q handles SQL quoting automatically:
          %d → integer, %f → float, %Q → string (quoted + escaped)

        Returns C code string: 'char *_sql = sqlite3_mprintf("...", ...);'
        """
        # Strip SQL string literals so :foo inside '...' isn't matched
        cleaned = re.sub(r"'[^']*'", "''", stmt)
        hv_refs = re.findall(r':(\w+)', cleaned)
        # Escape % before passing to sqlite3_mprintf to prevent UB
        if not hv_refs:
            escaped = stmt.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')
            return f'char *_sql = sqlite3_mprintf("{escaped}");'

        fmt = stmt
        fmt_args = []  # list of (sql_format_char, c_variable_name)
        for hv in hv_refs:
            spec = infer_format_spec(hv, self.declared_types)
            arg_val = value_for_snprintf(hv)
            if array_index and hv in self.array_vars:
                arg_val = f'{hv}[_i]'
            if spec == '%s':
                sql_fmt = '%Q'
            elif spec in ('%f', '%.2f', '%lf'):
                sql_fmt = '%f'
            else:
                sql_fmt = '%d'
            # Use placeholder to protect format specifier from %→%% escaping
            placeholder = f'__HVFMT_{len(fmt_args)}__'
            fmt = fmt.replace(f':{hv}', placeholder, 1)
            fmt_args.append((sql_fmt, arg_val))

        # Escape % as %% for sqlite3_mprintf, then restore format specifiers
        escaped_fmt = fmt.replace('%', '%%')
        for i, (sql_fmt, _) in enumerate(fmt_args):
            escaped_fmt = escaped_fmt.replace(f'__HVFMT_{i}__', sql_fmt)

        escaped_fmt = escaped_fmt.replace('\\', '\\\\').replace('"', '\\"')
        args_str = ', '.join(a[1] for a in fmt_args)
        return f'char *_sql = sqlite3_mprintf("{escaped_fmt}", {args_str});'

    def _gen_insert(self, stmt: str):
        sqlprintf_call = self._build_sqlprintf(stmt)
        self.emit(f'/* EXEC SQL {stmt} */')
        self.emit('  {')
        self.emit(f'    {sqlprintf_call}')
        self.emit('    char *_err = NULL;')
        self.emit('    int _rc = sqlite3_exec(db, _sql, NULL, NULL, &_err);')
        self.emit('    sqlite3_free(_sql);')
        self.emit('    if (_rc != SQLITE_OK) {')
        self.emit('      sqlca_set_error(_rc, _err ? _err : "INSERT error");')
        self.emit('      userlog("INSERT ERROR: %s", _err ? _err : "unknown");')
        self.emit('      if (_err) sqlite3_free(_err);')
        self.emit('    } else {')
        self.emit('      sqlca_set_success(sqlite3_changes(db));')
        self.emit('    }')
        self.emit('  }')
        ec = self._error_check()
        if ec:
            self.emit(f'  {ec}')

    def _gen_array_insert(self, stmt: str):
        """FOR :count INSERT INTO ... VALUES (...) → loop with snprintf per row"""
        m = re.match(r"FOR\s+:(\w+)\s+INSERT\s+(INTO\s+.+)",
                     stmt, re.IGNORECASE | re.DOTALL)
        if not m:
            warn("FOR :count INSERT pattern not matched, using raw exec: %s", stmt[:80])
            self._gen_exec_sql(stmt)
            return

        count_var = m.group(1)
        insert_body = m.group(2)  # "INTO table (...) VALUES (...)"
        # Prepend INSERT so the SQL is valid
        insert_stmt = f"INSERT {insert_body}"

        log("Array insert: count=%s, arrays=%s", count_var, sorted(self.array_vars))

        sqlprintf_call = self._build_sqlprintf(insert_stmt, array_index='[_i]')

        self.emit(f'/* EXEC SQL {stmt} */')
        self.emit('  {')
        self.emit('    char *_err = NULL;')
        self.emit('    int _ok = 1;')
        self.emit('    sqlite3_exec(db, "BEGIN", NULL, NULL, NULL);')
        self.emit(f'    for (int _i = 0; _i < {count_var}; _i++) {{')
        self.emit(f'      {sqlprintf_call}')
        self.emit(f'      int _rc = sqlite3_exec(db, _sql, NULL, NULL, &_err);')
        self.emit(f'      sqlite3_free(_sql);')
        self.emit(f'      if (_rc != SQLITE_OK) {{')
        self.emit(f'        sqlca_set_error(_rc, _err ? _err : "batch INSERT error");')
        self.emit(f'        userlog("Batch INSERT failed at row %d: %s",')
        self.emit(f'                _i, _err ? _err : "unknown");')
        self.emit(f'        if (_err) sqlite3_free(_err);')
        self.emit(f'        _ok = 0;')
        self.emit(f'        break;')
        self.emit(f'      }}')
        self.emit(f'    }}')
        self.emit(f'    if (_ok) {{')
        self.emit(f'      sqlite3_exec(db, "COMMIT", NULL, NULL, NULL);')
        self.emit(f'      sqlca_set_success({count_var});')
        self.emit(f'      userlog("Batch INSERT: %d rows committed successfully", {count_var});')
        self.emit(f'    }} else {{')
        self.emit(f'      sqlite3_exec(db, "ROLLBACK", NULL, NULL, NULL);')
        self.emit(f'      userlog("Batch INSERT rolled back due to error");')
        self.emit(f'    }}')
        self.emit(f'  }}')
        ec = self._error_check()
        if ec:
            self.emit(f'  {ec}')

    def _gen_select_into(self, stmt: str):
        m = re.match(r"SELECT\s+(.+?)\s+INTO\s+(.+?)\s+FROM\s+(.+)",
                     stmt, re.IGNORECASE | re.DOTALL)
        if not m:
            warn("SELECT INTO pattern not matched: %s", stmt[:80])
            self._gen_exec_sql(stmt)
            return

        sel_cols_str = m.group(1)
        into_str = m.group(2)
        from_where = m.group(3)

        into_vars = [v.strip().lstrip(':') for v in parse_comma_list(into_str)]

        sqlprintf_call = self._build_sqlprintf(f"SELECT {sel_cols_str} FROM {from_where}")

        self.emit(f'/* EXEC SQL {stmt} */')
        self.emit('  {')
        self.emit(f'    {sqlprintf_call}')
        self.emit('    sqlite3_stmt *_stmt = NULL;')
        self.emit('    int _rc = sqlite3_prepare_v2(db, _sql, -1, &_stmt, NULL);')
        self.emit('    sqlite3_free(_sql);')
        self.emit('    if (_rc == SQLITE_OK) {')
        self.emit('      _rc = sqlite3_step(_stmt);')
        self.emit('      if (_rc == SQLITE_ROW) {')
        for idx, hv in enumerate(into_vars):
            spec = infer_format_spec(hv, self.declared_types)
            if spec == '%d':
                self.emit(f'        {hv} = sqlite3_column_int(_stmt, {idx});')
            elif spec in ('%f', '%.2f', '%lf'):
                self.emit(f'        {hv} = sqlite3_column_double(_stmt, {idx});')
            else:
                self.emit(f'        {{')
                self.emit(f'          const char *_t = (const char *)sqlite3_column_text(_stmt, {idx});')
                self.emit(f'          if (_t) snprintf({hv}, sizeof({hv}), "%s", _t);')
                self.emit(f'          else {hv}[0] = \'\\0\';')
                self.emit(f'        }}')
        self.emit('        sqlca_set_success(1);')
        self.emit('      } else if (_rc == SQLITE_DONE) {')
        self.emit('        sqlca_set_error(100, "NO DATA FOUND");')
        self.emit('      } else {')
        self.emit('        sqlca_set_error(_rc, sqlite3_errmsg(db));')
        self.emit('        userlog("SELECT error: %s", sqlite3_errmsg(db));')
        self.emit('      }')
        self.emit('    } else {')
        self.emit('      sqlca_set_error(_rc, sqlite3_errmsg(db));')
        self.emit('      userlog("SELECT prepare error: %s", sqlite3_errmsg(db));')
        self.emit('    }')
        self.emit('    sqlite3_finalize(_stmt);')
        self.emit('  }')
        ec = self._error_check()
        if ec:
            self.emit(f'  {ec}')
        return  # End of _gen_select_into, don't fall through

    def _gen_update(self, stmt: str):
        sqlprintf_call = self._build_sqlprintf(stmt)
        self.emit(f'/* EXEC SQL {stmt} */')
        self.emit('  {')
        self.emit(f'    {sqlprintf_call}')
        self.emit('    char *_err = NULL;')
        self.emit('    int _rc = sqlite3_exec(db, _sql, NULL, NULL, &_err);')
        self.emit('    sqlite3_free(_sql);')
        self.emit('    if (_rc != SQLITE_OK) {')
        self.emit('      sqlca_set_error(_rc, _err ? _err : "UPDATE error");')
        self.emit('      userlog("UPDATE ERROR: %s", _err ? _err : "unknown");')
        self.emit('      if (_err) sqlite3_free(_err);')
        self.emit('    } else {')
        self.emit('      sqlca_set_success(sqlite3_changes(db));')
        self.emit('    }')
        self.emit('  }')
        ec = self._error_check()
        if ec:
            self.emit(f'  {ec}')

    def _gen_declare_cursor(self, stmt: str):
        m = re.match(r"DECLARE\s+(\w+)\s+CURSOR\s+FOR\s+(SELECT\s+.+)",
                     stmt, re.IGNORECASE | re.DOTALL)
        if m:
            cursor_name = m.group(1)
            select_sql = m.group(2)
            self.cursors[cursor_name] = select_sql
            self.emit(f'/* EXEC SQL {stmt} */')
            self.emit(f'static sqlite3_stmt *{cursor_name}_stmt = NULL;')
            log("Declared cursor: %s → %s", cursor_name, select_sql[:80])
        else:
            warn("Could not parse DECLARE CURSOR: %s", stmt[:80])
            self.emit(f'/* EXEC SQL {stmt} -- unparseable */')

    def _gen_open_cursor(self, stmt: str):
        m = re.match(r"OPEN\s+(\w+)", stmt, re.IGNORECASE)
        if m and m.group(1) in self.cursors:
            cursor_name = m.group(1)
            select_sql = self.cursors[cursor_name]
            sqlprintf_call = self._build_sqlprintf(select_sql)
            self.emit(f'/* EXEC SQL {stmt} */')
            self.emit('  {')
            if sqlprintf_call:
                self.emit(f'    {sqlprintf_call}')
            else:
                escaped = select_sql.replace('\\', '\\\\').replace('"', '\\"')
                self.emit(f'    char *_sql = sqlite3_mprintf("{escaped}");')
            self.emit(f'    if ({cursor_name}_stmt) {{')
            self.emit(f'      sqlite3_finalize({cursor_name}_stmt);')
            self.emit(f'      {cursor_name}_stmt = NULL;')
            self.emit(f'    }}')
            self.emit(f'    int _rc = sqlite3_prepare_v2(db, _sql, -1, &{cursor_name}_stmt, NULL);')
            self.emit(f'    sqlite3_free(_sql);')
            self.emit(f'    if (_rc != SQLITE_OK) {{')
            self.emit(f'      sqlca_set_error(_rc, sqlite3_errmsg(db));')
            self.emit(f'      userlog("OPEN {cursor_name} failed: %s", sqlite3_errmsg(db));')
            self.emit(f'    }} else {{')
            self.emit(f'      sqlca_set_success(0);')
            self.emit(f'      userlog("OPEN {cursor_name}: cursor ready");')
            self.emit(f'    }}')
            self.emit('  }')
            ec = self._error_check()
            if ec:
                self.emit(f'  {ec}')
        else:
            name = m.group(1) if m else '?'
            warn("OPEN: cursor '%s' not found in declared cursors: %s", name,
                 sorted(self.cursors.keys()))
            self.emit(f'/* EXEC SQL {stmt} -- unknown cursor "{name}" */')

    def _gen_fetch(self, stmt: str):
        m = re.match(r"FETCH\s+(\w+)\s+INTO\s+(.+)", stmt, re.IGNORECASE)
        if not m:
            warn("Could not parse FETCH: %s", stmt[:80])
            self.emit(f'/* EXEC SQL {stmt} -- unparseable */')
            return

        cursor_name = m.group(1)
        into_vars = [v.strip().lstrip(':') for v in parse_comma_list(m.group(2))]

        self.emit(f'/* EXEC SQL {stmt} */')
        self.emit('  {')
        self.emit(f'    int _rc = sqlite3_step({cursor_name}_stmt);')
        self.emit('    if (_rc == SQLITE_ROW) {')
        for idx, hv in enumerate(into_vars):
            spec = infer_format_spec(hv, self.declared_types)
            if spec == '%d':
                self.emit(f'      {hv} = sqlite3_column_int({cursor_name}_stmt, {idx});')
            elif spec in ('%f', '%.2f', '%lf'):
                self.emit(f'      {hv} = sqlite3_column_double({cursor_name}_stmt, {idx});')
            else:
                self.emit(f'      {{')
                self.emit(f'        const char *_t = (const char *)sqlite3_column_text({cursor_name}_stmt, {idx});')
                self.emit(f'        if (_t) snprintf({hv}, sizeof({hv}), "%s", _t);')
                self.emit(f'        else {hv}[0] = \'\\0\';')
                self.emit(f'      }}')
        self.emit('      sqlca_set_success(1);')
        self.emit('    } else if (_rc == SQLITE_DONE) {')
        self.emit('      sqlca_set_error(100, "NO DATA FOUND");')
        self.emit('    } else {')
        self.emit('      sqlca_set_error(_rc, sqlite3_errmsg(db));')
        self.emit(f'      userlog("FETCH error on {cursor_name}: %s", sqlite3_errmsg(db));')
        self.emit('    }')
        self.emit('  }')
        ec = self._error_check()
        if ec:
            self.emit(f'  {ec}')

    def _gen_close_cursor(self, stmt: str):
        m = re.match(r"CLOSE\s+(\w+)", stmt, re.IGNORECASE)
        if m:
            cn = m.group(1)
            self.emit(f'/* EXEC SQL {stmt} */')
            self.emit(f'  sqlite3_finalize({cn}_stmt);')
            self.emit(f'  {cn}_stmt = NULL;')
        else:
            self.emit(f'/* EXEC SQL {stmt} */')


# ─── Entry point ────────────────────────────────────────────────────────────

def preprocess_file(input_path: str, output_path: str) -> bool:
    """Preprocess a single .pc file. Returns True on success."""
    log("Processing: %s", input_path)

    try:
        with open(input_path, 'r') as f:
            source = f.read()
    except IOError as e:
        error("Cannot read %s: %s", input_path, e)
        return False

    proc = ProCPreprocessor(os.path.basename(input_path))
    result = proc.preprocess(source)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(result)

    print(f"  [OK] {input_path} → {output_path}", file=sys.stderr)
    if proc.warnings > 0:
        print(f"       {proc.warnings} warning(s), {proc.unhandled} unhandled statement(s)",
              file=sys.stderr)
    return True


def main():
    global VERBOSE
    parser = argparse.ArgumentParser(description="Pro*C to C+SQLite preprocessor")
    parser.add_argument('input', nargs='+', help='.pc input files')
    parser.add_argument('-o', '--output', default='build', help='Output directory')
    parser.add_argument('--single', help='Single output file (first input only)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    args = parser.parse_args()

    VERBOSE = args.verbose

    print(f"pc_preproc: processing {len(args.input)} file(s)...", file=sys.stderr)

    ok = 0
    fail = 0
    for f in args.input:
        if args.single:
            out = args.single
        else:
            basename = os.path.splitext(os.path.basename(f))[0]
            out = os.path.join(args.output, basename + '.c')
        if preprocess_file(f, out):
            ok += 1
        else:
            fail += 1

    print(f"\npc_preproc: {ok} succeeded, {fail} failed → {args.output}/",
          file=sys.stderr)

    return 1 if fail > 0 else 0


if __name__ == '__main__':
    sys.exit(main())
