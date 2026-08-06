from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import Product, utc_now_iso

_TITLE_NOISE = frozenset({
    "de", "da", "do", "em", "para", "com", "sem", "no", "na", "os", "as", "um", "uma",
    "e", "o", "a", "ao", "dos", "das", "nos", "nas", "pelo", "pela", "por", "que", "se",
    "preto", "preta", "branco", "branca", "azul", "rosa", "vermelho", "vermelha",
    "verde", "amarelo", "amarela", "cinza", "dourado", "dourada", "prata", "laranja",
    "roxo", "roxa", "lilas", "bege", "marrom",
})
_NOISE_RE = re.compile(r'[^a-z0-9\s]')
# Threshold Jaccard: >= 60% das palavras em comum = mesmo produto/família
_SIMILARITY_THRESHOLD = 0.60


def _title_tokens(title: str) -> frozenset[str]:
    """Retorna conjunto de tokens relevantes do título (sem stopwords, mín. 3 chars)."""
    text = _NOISE_RE.sub(' ', title.lower())
    return frozenset(w for w in text.split() if w not in _TITLE_NOISE and len(w) >= 3)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def are_titles_similar(title_a: str, title_b: str, threshold: float = _SIMILARITY_THRESHOLD) -> bool:
    """Retorna True se os dois títulos parecem ser o mesmo produto (variação de cor/sabor/tamanho)."""
    return _jaccard(_title_tokens(title_a), _title_tokens(title_b)) >= threshold


def _normalize_title(title: str) -> str:
    text = _NOISE_RE.sub(' ', title.lower())
    words = [w for w in text.split() if w not in _TITLE_NOISE and len(w) >= 3]
    return " ".join(words[:7])


def _dedup_by_title(products: list[Product], limit: int) -> list[Product]:
    """Remove produtos similares (Jaccard >= threshold), mantendo o de melhor score/preço."""
    kept: list[Product] = []
    kept_tokens: list[frozenset[str]] = []
    for p in products:
        toks = _title_tokens(p.title)
        duplicate_idx = -1
        for i, kt in enumerate(kept_tokens):
            if _jaccard(toks, kt) >= _SIMILARITY_THRESHOLD:
                duplicate_idx = i
                break
        if duplicate_idx == -1:
            kept.append(p)
            kept_tokens.append(toks)
        else:
            # Mantém o de melhor score; se igual, o mais barato
            incumbent = kept[duplicate_idx]
            if p.score > incumbent.score or (p.score == incumbent.score and p.price > 0 and (incumbent.price <= 0 or p.price < incumbent.price)):
                kept[duplicate_idx] = p
                kept_tokens[duplicate_idx] = toks
        if len(kept) >= limit * 3:  # para não processar toda a lista
            break
    return kept[:limit]


def _hours_ago_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(microsecond=0).isoformat()


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

    def source_freshness(self) -> dict[str, str]:
        """Quando cada fonte trouxe produto pela ultima vez."""
        with self.session() as conn:
            rows = conn.execute("select source, max(last_seen) from products group by source").fetchall()
        return {row[0]: row[1] for row in rows}

    def stale_sources(self, expected: list[str], *, hours: int) -> list[tuple[str, str]]:
        """Fontes que pararam de trazer produtos.

        Devolve (fonte, ultima_vez) — com ``"nunca"`` quando a fonte nunca
        entregou nada. Serve para flagrar credencial expirada ou API bloqueada,
        que hoje falham em silencio porque `mine --allow-errors` engole o erro.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(microsecond=0).isoformat()
        freshness = self.source_freshness()
        stale: list[tuple[str, str]] = []
        for source in expected:
            last_seen = freshness.get(source)
            if last_seen is None:
                stale.append((source, "nunca"))
            elif last_seen < cutoff:
                stale.append((source, last_seen))
        return stale

    def purge_products_older_than(self, *, days: int, dry_run: bool = False) -> dict[str, int]:
        """Remove produtos cujo ultimo avistamento e anterior ao corte.

        Oferta velha e link morto: preco desatualizado, produto fora de estoque.
        Remove tambem posts e eventos ligados a esses produtos, para nao deixar
        linhas orfas apontando para ids que nao existem mais.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
        with self.session() as conn:
            ids = [row[0] for row in conn.execute("select id from products where last_seen < ?", (cutoff,))]
            if not ids:
                return {"products": 0, "posts": 0, "events": 0}

            placeholders = ",".join("?" * len(ids))
            posts = conn.execute(f"select count(*) from posts where product_id in ({placeholders})", ids).fetchone()[0]
            events = conn.execute(f"select count(*) from events where product_id in ({placeholders})", ids).fetchone()[0]

            if not dry_run:
                conn.execute(f"delete from posts where product_id in ({placeholders})", ids)
                conn.execute(f"delete from events where product_id in ({placeholders})", ids)
                conn.execute(f"delete from products where id in ({placeholders})", ids)

        return {"products": len(ids), "posts": posts, "events": events}

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

        fetch_limit = max(limit * 10, 50)
        query = f"""
            select * from products
            where {' and '.join(clauses)}
            order by score desc, last_seen desc
            limit ?
        """
        params.append(fetch_limit)
        with self.session() as conn:
            rows = conn.execute(query, params).fetchall()
        products = [self._row_to_product(row) for row in rows]
        return _dedup_by_title(products, limit)

    def list_repost_candidates(self, *, limit: int, min_score: float, cooldown_minutes: int) -> list[Product]:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max(cooldown_minutes, 1))).replace(
            microsecond=0
        ).isoformat()
        fetch_limit = max(limit * 10, 50)
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
                (min_score, cutoff, fetch_limit),
            ).fetchall()
        products = [self._row_to_product(row) for row in rows]
        return _dedup_by_title(products, limit)

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

    def recently_published_titles(self, *, hours: int = 48) -> list[str]:
        """Retorna títulos de produtos publicados com sucesso nas últimas N horas."""
        cutoff = _hours_ago_iso(hours)
        with self.session() as conn:
            rows = conn.execute(
                """
                select distinct p.title
                from products p
                join posts po on po.product_id = p.id
                where po.status = 'sent' and po.posted_at >= ?
                order by po.posted_at desc
                limit 300
                """,
                (cutoff,),
            ).fetchall()
        return [str(row["title"]) for row in rows if row["title"]]

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

    def stats_by_source(self) -> list[dict[str, Any]]:
        """Cliques agrupados por source do produto."""
        with self.session() as conn:
            rows = conn.execute(
                """
                select
                    json_extract(e.metadata_json, '$.source') as source,
                    count(*) as clicks
                from events e
                where e.event_type = 'click'
                  and json_extract(e.metadata_json, '$.source') is not null
                group by source
                order by clicks desc
                """
            ).fetchall()
        return [{"source": row["source"], "clicks": int(row["clicks"])} for row in rows]

    def stats_by_category(self) -> list[dict[str, Any]]:
        """Cliques agrupados por categoria do produto."""
        with self.session() as conn:
            rows = conn.execute(
                """
                select
                    json_extract(e.metadata_json, '$.category') as category,
                    count(*) as clicks
                from events e
                where e.event_type = 'click'
                  and json_extract(e.metadata_json, '$.category') is not null
                  and json_extract(e.metadata_json, '$.category') != ''
                group by category
                order by clicks desc
                limit 20
                """
            ).fetchall()
        return [{"category": row["category"], "clicks": int(row["clicks"])} for row in rows]

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
