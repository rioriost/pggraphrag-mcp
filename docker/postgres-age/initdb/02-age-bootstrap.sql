\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';

SET search_path = public, ag_catalog;

DO
$$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM ag_catalog.ag_graph
        WHERE name = 'pggraphrag_memory'
    ) THEN
        PERFORM ag_catalog.create_graph('pggraphrag_memory');
    END IF;
END
$$;

DO
$$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM ag_catalog.ag_label l
        JOIN ag_catalog.ag_graph g
          ON g.graphid = l.graph
        WHERE g.name = 'pggraphrag_memory'
          AND l.name = 'Document'
    ) THEN
        PERFORM *
        FROM ag_catalog.cypher(
            'pggraphrag_memory',
            $cypher$
                CREATE (:Document {bootstrap: true, created_by: 'initdb'})
            $cypher$
        ) AS (v ag_catalog.agtype);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM ag_catalog.ag_label l
        JOIN ag_catalog.ag_graph g
          ON g.graphid = l.graph
        WHERE g.name = 'pggraphrag_memory'
          AND l.name = 'Chunk'
    ) THEN
        PERFORM *
        FROM ag_catalog.cypher(
            'pggraphrag_memory',
            $cypher$
                CREATE (:Chunk {bootstrap: true, created_by: 'initdb'})
            $cypher$
        ) AS (v ag_catalog.agtype);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM ag_catalog.ag_label l
        JOIN ag_catalog.ag_graph g
          ON g.graphid = l.graph
        WHERE g.name = 'pggraphrag_memory'
          AND l.name = 'Entity'
    ) THEN
        PERFORM *
        FROM ag_catalog.cypher(
            'pggraphrag_memory',
            $cypher$
                CREATE (:Entity {bootstrap: true, created_by: 'initdb'})
            $cypher$
        ) AS (v ag_catalog.agtype);
    END IF;
END
$$;

DO
$$
BEGIN
    PERFORM *
    FROM ag_catalog.cypher(
        'pggraphrag_memory',
        $cypher$
            MATCH (n)
            WHERE coalesce(n.bootstrap, false) = true
            DETACH DELETE n
        $cypher$
    ) AS (v ag_catalog.agtype);
EXCEPTION
    WHEN undefined_function THEN
        RAISE NOTICE 'AGE cypher cleanup skipped because cypher function is unavailable.';
END
$$;
