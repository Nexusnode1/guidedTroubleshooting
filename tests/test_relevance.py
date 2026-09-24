from app.services.relevance import MIN_RELEVANCE, content_tokens, relevance


def test_generic_device_words_are_ignored():
    assert content_tokens("my Samsung Galaxy screen is cracked") == {"crack"}


def test_unrelated_query_scores_zero():
    assert relevance("best pasta recipe", "Blank or black display Step 1 Check for physical damage") == 0.0


def test_a_title_word_alone_is_enough():
    score = relevance("my screen is blank", "check the charger", title="Blank or black display")
    assert score >= MIN_RELEVANCE


def test_one_shared_word_is_not_enough_for_a_long_query():
    assert relevance("alpha beta gamma delta epsilon zeta", "alpha only here") == 0.0


def test_short_query_needs_only_one_shared_word():
    assert relevance("cracked screen", "Cracked screen service options") > 0.0
