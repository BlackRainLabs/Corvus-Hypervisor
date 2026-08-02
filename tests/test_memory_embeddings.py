"""Deterministic embedding helpers."""

from corvus.memory.embeddings import EMBEDDING_DIM, embed_text


def test_embed_text_is_deterministic():
    first = embed_text("hello semantic memory")
    second = embed_text("hello semantic memory")
    assert first == second


def test_embed_text_normalized():
    vector = embed_text("corvus hypervisor memory")
    assert len(vector) == EMBEDDING_DIM
    norm = sum(value * value for value in vector) ** 0.5
    assert 0.99 <= norm <= 1.01


def test_similar_texts_have_higher_cosine_than_unrelated():
    cat = embed_text("cat sat on mat")
    cat_query = embed_text("the cat on the mat")
    physics = embed_text("quantum physics particles")

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert dot(cat, cat_query) > dot(cat, physics)
