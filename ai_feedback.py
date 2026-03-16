import argparse
import json
import os
import re
from typing import List

import pymysql
import redis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI feedback utility for Redis/MySQL/User output")
    parser.add_argument("--source-ai", default="unknown", help="source AI name")
    parser.add_argument("--task-id", default=None, help="optional task id")
    parser.add_argument("--sessionid", default=None, help="optional ai chat session id")

    parser.add_argument("--redis", help="send payload to redis result list")
    parser.add_argument("--db", help="write payload into mysql feedback table")
    parser.add_argument("--ask", help="question for user (prints and stores)")

    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "127.0.0.1"))
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    parser.add_argument("--redis-db", type=int, default=int(os.getenv("REDIS_DB", "0")))
    parser.add_argument("--redis-result-key", default="ai_results")
    parser.add_argument("--redis-question-key", default="ai_questions")

    parser.add_argument("--mysql-host", default=os.getenv("MYSQL_HOST", "127.0.0.1"))
    parser.add_argument("--mysql-port", type=int, default=int(os.getenv("MYSQL_PORT", "3306")))
    parser.add_argument("--mysql-user", default=os.getenv("MYSQL_USER", "root"))
    parser.add_argument("--mysql-password", default=os.getenv("MYSQL_PASSWORD", "gj"))
    parser.add_argument("--mysql-db", default=os.getenv("MYSQL_DB", "autoai"))
    parser.add_argument("--mysql-table", default="ai_feedback")
    return parser


def make_record(args: argparse.Namespace, channel: str, payload: str) -> str:
    record = {
        "task_id": args.task_id,
        "source_ai": args.source_ai,
        "channel": channel,
        "sessionid": args.sessionid,
        "payload": payload,
    }
    return json.dumps(record, ensure_ascii=False)


def validate_identifier(value: str, field: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError(f"invalid {field}: {value}")


def push_redis(args: argparse.Namespace, key: str, channel: str, payload: str) -> None:
    client = redis.Redis(
        host=args.redis_host,
        port=args.redis_port,
        db=args.redis_db,
        decode_responses=True,
    )
    client.lpush(key, make_record(args, channel, payload))


def insert_mysql(args: argparse.Namespace, channel: str, payload: str) -> None:
    validate_identifier(args.mysql_db, "mysql_db")
    validate_identifier(args.mysql_table, "mysql_table")
    try:
        conn = pymysql.connect(
            host=args.mysql_host,
            port=args.mysql_port,
            user=args.mysql_user,
            password=args.mysql_password,
            database=args.mysql_db,
            autocommit=True,
            charset="utf8mb4",
        )
    except pymysql.err.OperationalError as exc:
        if exc.args and exc.args[0] == 1049:
            bootstrap = pymysql.connect(
                host=args.mysql_host,
                port=args.mysql_port,
                user=args.mysql_user,
                password=args.mysql_password,
                autocommit=True,
                charset="utf8mb4",
            )
            try:
                with bootstrap.cursor() as cur:
                    cur.execute(
                        f"CREATE DATABASE IF NOT EXISTS `{args.mysql_db}` "
                        "DEFAULT CHARACTER SET utf8mb4"
                    )
            finally:
                bootstrap.close()
            conn = pymysql.connect(
                host=args.mysql_host,
                port=args.mysql_port,
                user=args.mysql_user,
                password=args.mysql_password,
                database=args.mysql_db,
                autocommit=True,
                charset="utf8mb4",
            )
        else:
            raise
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {args.mysql_table} (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    task_id VARCHAR(128) NULL,
                    source_ai VARCHAR(64) NULL,
                    channel VARCHAR(32) NOT NULL,
                    sessionid VARCHAR(77) NULL,
                    payload TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) DEFAULT CHARSET=utf8mb4
                """
            )
            try:
                sql = (
                    f"INSERT INTO {args.mysql_table} (task_id, source_ai, channel, payload, sessionid) "
                    "VALUES (%s, %s, %s, %s, %s)"
                )
                cur.execute(sql, (args.task_id, args.source_ai, channel, payload, args.sessionid))
            except pymysql.err.OperationalError as exc:
                if exc.args and exc.args[0] in {1054, 1136}:
                    sql = (
                        f"INSERT INTO {args.mysql_table} (task_id, source_ai, channel, payload) "
                        "VALUES (%s, %s, %s, %s)"
                    )
                    cur.execute(sql, (args.task_id, args.source_ai, channel, payload))
                else:
                    raise
    finally:
        conn.close()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not any([args.redis, args.db, args.ask]):
        parser.error("at least one of --redis / --db / --ask is required")

    done: List[str] = []
    if args.redis:
        push_redis(args, args.redis_result_key, "redis", args.redis)
        done.append(f"redis:{args.redis_result_key}")
        print("[feedback] pushed result to redis")

    if args.db:
        insert_mysql(args, "db", args.db)
        done.append(f"mysql:{args.mysql_table}")
        print("[feedback] inserted row to mysql")

    if args.ask:
        print(f"[AI question] {args.ask}")
        push_redis(args, args.redis_question_key, "ask", args.ask)
        insert_mysql(args, "ask", args.ask)
        done.append(f"ask(redis:{args.redis_question_key}, mysql:{args.mysql_table})")

    print("[feedback] done -> " + ", ".join(done))


if __name__ == "__main__":
    main()
