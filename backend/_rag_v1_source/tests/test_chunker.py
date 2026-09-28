from app.services.chunker import chunker


def test_chunker_short_text():
    chunks = chunker("Bonjour. Ceci est un texte court.")
    assert len(chunks) == 1
    assert chunks[0].token_count > 0


def test_chunker_long_text_creates_multiple_chunks():
    texte = " ".join(["Cette phrase explique une procédure importante."] * 80)
    chunks = chunker(texte, taille_cible=500, chevauchement=80)
    assert len(chunks) > 1
    assert all(c.texte for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
