\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;

DO $$
BEGIN
    PERFORM 1
    FROM pg_namespace
    WHERE nspname = 'ag_catalog';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Apache AGE catalog schema is not available after CREATE EXTENSION age';
    END IF;
END
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_available_extensions
        WHERE name = 'age'
    ) THEN
        RAISE NOTICE 'Apache AGE extension is available.';
    ELSE
        RAISE EXCEPTION 'Apache AGE extension is not available in this PostgreSQL image.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_available_extensions
        WHERE name = 'vector'
    ) THEN
        RAISE NOTICE 'pgvector extension is available.';
    ELSE
        RAISE EXCEPTION 'pgvector extension is not available in this PostgreSQL image.';
    END IF;
END
$$;

SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'age')
ORDER BY extname;
