from pathlib import Path

from matrix_ui import _parse_mysql_from_env


def test_parse_mysql_from_legacy_env(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "mysql:\n"
        "  zzb2020.mysql.polardb.rds.aliyuncs.com 3306\n"
        "  edcarwr 数据库 pwd: Car241013@\n",
        encoding="utf-8",
    )
    cfg = _parse_mysql_from_env(env)
    assert cfg["MYSQL_HOST"] == "zzb2020.mysql.polardb.rds.aliyuncs.com"
    assert cfg["MYSQL_PORT"] == "3306"
    assert cfg["MYSQL_USER"] == "edcarwr"
    assert cfg["MYSQL_DB"] == "edcar"
