from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import Product, utc_now_iso


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.session() as conn:
            conn.executescript(
                """
                create table if not exists products (
                    id integer primary key autoincrement,
                    source text not null,
                    external_id text not null,
                    title text not null,
                    price real not null,
                    original_price real,
                    currency text not null,
                    permalink text not null,
                    affiliate_url text not null,
                    image_url text,
                    category text,
                    score real not null default 0,
                    rating real,
                    sold_quantity integer,
                    free_shipping integer not null default 0,
                    metadata_json text not null default '{}',
                    first_seen text not null,
                    last_seen text not null,
                    published_count integer not null default 0,
                    unique(source, external_id)
                );

                create table if not exists posts (
                    id integer primary key autoincrement,
                    product_id integer not null,
                    channel text not null,
                    status text not null,
                    message text not null,
                    response text,
                    posted_at text not null,
                    foreign key(product_id) references products(id)
                );

                create table if not exists events (
                    id integer primary key autoincrement,
                    product_id integer not null,
                    event_type text not null,
                    channel text,
                    value real not null default 1,
                    metadata_json text not null default '{}',
                    created_at text not null,
                    foreign key(product_id) references products(id)
                );
                """
            )

    def upsert_product(self, product: Product) -> int:
        now = utc_now_iso()
        metadata_json = json.dumps(product.metadata, ensure_ascii=False, sort_keys=True)
        with self.session() as conn:
            conn.execute(
                """
                insert into products (
                    source, external_id, title, price, original_price, currency,
                    permalink, affiliate_url, image_url, category, score, rating,
                    sold_quantity, free_shipping, metadata_json, first_seen, last_seen
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(source, external_id) do update set
                    title = excluded.title,
                    price = excluded.price,
                    original_price = excluded.original_price,
                    currency = excluded.currency,
                    permalink = excluded.permalink,
                    affiliate_url = excluded.affiliate_url,
                    image_url = excluded.image_url,
                    category = excluded.category,
                    score = excluded.score,
                    rating = excluded.rating,
                    sold_quantity = excluded.sold_quantity,
                    free_shipping = excluded.free_shipping,
                    metadata_json = excluded.metadata_json,
                    last_seen = excluded.last_seen
                """,
                (
                    product.source,
                    product.external_id,
                    product.title,
                    product.price,
                    product.original_price,
                    product.currency,
                    product.permalink,
                    product.affiliate_url,
                    product.image_url,
                    product.category,
                    product.score,
                    product.rating,
                    product.sold_quantity,
                    int(product.free_shipping),
                    metadata_json,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "select id from products where source = ? and external_id = ?",
                (product.source, product.external_id),
            ).fetchone()
            return int(row["id"])

    def list_candidates(
        self,
        *,
        limit: int,
        min_score: float = 0.0,
        unpublished_only: bool = True,
    ) -> list[Product]:
        clauses = ["score >= ?"]
        params: list[Any] = [min_score]
        if unpublished_only:
            clauses.append("published_count = 0")

        query = f"""
            select * from products
            where {' and '.join(clauses)}
            order by score desc, last_seen desc
            limit ?
        """
        params.append(limit)
        with self.session() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_product(row) for row in rows]

    def list_repost_candidates(self, *, limit: int, min_score: float, cooldown_minutes: int) -> list[Product]:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max(cooldown_minutes, 1))).replace(
            microsecond=0
        ).isoformat()
        with self.session() as conn:
            rows = conn.execute(
                """
                select p.*, max(posts.posted_at) as last_posted_at
                from products p
                left join posts on posts.product_id = p.id and posts.status = 'sent'
                where p.score >= ?
                group by p.id
                having last_posted_at is null or last_posted_at <= ?
                order by
                    case when last_posted_at is null then 0 else 1 end,
                    last_posted_at asc,
                    p.score desc,
                    p.last_seen desc
                limit ?
                """,
                (min_score, cutoff, limit),
            ).fetchall()
        return [self._row_to_product(row) for row in rows]

    def list_products_for_store(self, *, limit: int = 120, require_image: bool = False) -> list[Product]:
        clauses = []
        if require_image:
            clauses.append("image_url is not null and trim(image_url) != ''")
        where = f"where {' and '.join(clauses)}" if clauses else ""
        with self.session() as conn:
            rows = conn.execute(
                f"""
                select * from products
                {where}
                order by published_count desc, score desc, last_seen desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_product(row) for row in rows]

    def get_product(self, product_id: int) -> Product | None:
        with self.session() as conn:
            row = conn.execute("select * from products where id = ?", (product_id,)).fetchone()
        return self._row_to_product(row) if row else None

    def add_post(self, product_id: int, channel: str, status: str, message: str, response: str = "") -> None:
        now = utc_now_iso()
        with self.session() as conn:
            conn.execute(
                """
                insert into posts (product_id, channel, status, message, response, posted_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (product_id, channel, status, message, response, now),
            )
            if status == "sent":
                conn.execute(
                    "update products set published_count = published_count + 1 where id = ?",
                    (product_id,),
                )

    def record_event(
        self,
        product_id: int,
        event_type: str,
        *,
        channel: str = "",
        value: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.session() as conn:
            conn.execute(
                """
                insert into events (product_id, event_type, channel, value, metadata_json, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    event_type,
                    channel,
                    value,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    utc_now_iso(),
                ),
            )

    def category_boosts(self) -> dict[str, float]:
        with self.session() as conn:
            rows = conn.execute(
                """
                select p.category,
                       sum(case e.event_type
                           when 'sale' then 8
                           when 'click' then 2
                           else 1
                       end * e.value) as points
                from events e
                join products p on p.id = e.product_id
                where p.category is not null and p.category != ''
                group by p.category
                """
            ).fetchall()
        return {row["category"]: float(row["points"] or 0) for row in rows}

    def stats(self) -> dict[str, Any]:
        with self.session() as conn:
            product_count = conn.execute("select count(*) as n from products").fetchone()["n"]
            posted_count = conn.execute("select count(*) as n from posts where status = 'sent'").fetchone()["n"]
            click_count = conn.execute("select count(*) as n from events where event_type = 'click'").fetchone()["n"]
            sale_count = conn.execute("select count(*) as n from events where event_type = 'sale'").fetchone()["n"]
            top_rows = conn.execute(
                """
                select source, title, price, score, published_count
                from products
                order by score desc
                limit 5
                """
            ).fetchall()
        return {
            "products": product_count,
            "posts_sent": posted_count,
            "clicks": click_count,
            "sales": sale_count,
            "top_products": [dict(row) for row in top_rows],
        }

    def _row_to_product(self, row: sqlite3.Row) -> Product:
        metadata = json.loads(row["metadata_json"] or "{}")
        return Product(
            id=int(row["id"]),
            source=row["source"],
            external_id=row["external_id"],
            title=row["title"],
            price=float(row["price"]),
            original_price=float(row["original_price"]) if row["original_price"] is not None else None,
            currency=row["currency"],
            permalink=row["permalink"],
            affiliate_url=row["affiliate_url"],
            image_url=row["image_url"] or "",
            category=row["category"] or "",
            score=float(row["score"]),
            rating=float(row["rating"]) if row["rating"] is not None else None,
            sold_quantity=int(row["sold_quantity"]) if row["sold_quantity"] is not None else None,
            free_shipping=bool(row["free_shipping"]),
            captured_at=row["last_seen"],
            metadata=metadata,
        )
