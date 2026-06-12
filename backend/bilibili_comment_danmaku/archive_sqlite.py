from pathlib import Path


def remove_sqlite_file_with_sidecars(path):
    path = Path(path)
    for candidate in (path, path.with_name(f"{path.name}-wal"), path.with_name(f"{path.name}-shm")):
        if candidate.exists():
            candidate.unlink()


def copy_table_query(source, target, table, where_sql, values=()):
    source_columns = {row["name"] for row in source.execute(f"PRAGMA table_info({table})").fetchall()}
    target_columns = [row["name"] for row in target.execute(f"PRAGMA table_info({table})").fetchall()]
    columns = [column for column in target_columns if column in source_columns]
    if not columns:
        return 0

    column_sql = ", ".join(columns)
    insert_placeholders = ", ".join("?" for _ in columns)
    cursor = source.execute(f"SELECT {column_sql} FROM {table} WHERE {where_sql}", values)
    count = 0
    while True:
        rows = cursor.fetchmany(1000)
        if not rows:
            break
        target.executemany(
            f"INSERT OR REPLACE INTO {table} ({column_sql}) VALUES ({insert_placeholders})",
            [tuple(row[column] for column in columns) for row in rows],
        )
        count += len(rows)
    return count
