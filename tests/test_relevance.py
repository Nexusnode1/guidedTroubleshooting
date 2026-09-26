from app.services.plan_builder import PlanBuilder
from app.services.relevance import MIN_RELEVANCE, common_tokens, content_tokens, relevance


def test_generic_device_words_are_ignored():
    assert content_tokens("my phone screen is cracked") == {"crack"}


def test_ignored_words_are_dropped_from_content_tokens():
    assert content_tokens("my Acme phone screen is cracked", ignore={"acme"}) == {"crack"}


def test_common_tokens_are_the_words_most_articles_share():
    articles = [f"Acme help article on {topic}" for topic in ("battery", "camera", "wifi", "storage", "display")]
    assert common_tokens(articles) == {"acme", "help", "article"}


def test_common_tokens_need_a_large_enough_corpus():
    assert common_tokens(["Acme battery", "Acme camera"]) == frozenset()


def test_a_word_common_to_the_corpus_is_not_evidence_of_fit():
    article = "Acme logo appears. Check the charger for damage."
    query = "my Acme phone screen flashes extremely quickly whenever I plug in a charger"
    assert relevance(query, article) > 0.0
    assert relevance(query, article, ignore={"acme"}) == 0.0


def test_the_official_knowledge_base_supplies_the_common_words(catalog, siis_rows):
    row = next(r for r in siis_rows if r["id"] == "row_16")
    siis = row["siis_response"]
    # The vendor name appears in most official articles, so sharing it with this
    # (misaligned) article must not be what lets the query through the gate.
    assert PlanBuilder(catalog).build(row["original_query"], siis["content"], siis["title"]) is None


def test_unrelated_query_scores_zero():
    assert relevance("best pasta recipe", "Blank or black display Step 1 Check for physical damage") == 0.0


def test_a_title_word_alone_is_enough():
    score = relevance("my screen is blank", "check the charger", title="Blank or black display")
    assert score >= MIN_RELEVANCE


def test_one_shared_word_is_not_enough_for_a_long_query():
    assert relevance("alpha beta gamma delta epsilon zeta", "alpha only here") == 0.0


def test_short_query_needs_only_one_shared_word():
    assert relevance("cracked screen", "Cracked screen service options") > 0.0
