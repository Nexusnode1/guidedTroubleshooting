"""Positive and deliberate-negative tests for the final validation firewall."""

from copy import deepcopy

import pytest

from app.services.plan_validator import validate_plan


CATALOG = {
    "deeplinks": [
        {
            "deeplink": "bixby://masked/catalog-screen",
            "description": "Opens the battery settings page in device Settings.",
            "message": "Open Battery Settings",
            "originalType": "onClickURL",
            "validation": {"deeplink": "bixby://masked/catalog-validation", "key": "Battery"},
        },
        {
            "deeplink": "bixby://dummy_positive",
            "description": "Generic placeholder for a Settings screen.",
            "message": "Open the relevant Settings screen",
            "originalType": "placeholder",
        },
    ]
}


def _action(*, deeplink: dict | None = None, category: str = "auto", name: str = "Battery Settings") -> dict:
    return {
        "actionName": name,
        "description": "It will improve battery performance",
        "stepGroups": [{"steps": ["Open Battery Settings."], "actionableDeeplink": deeplink}],
        "category": category,
    }


def _valid_plan() -> dict:
    return {
        "query_variations": [f"battery troubleshooting variation {i}" for i in range(8)],
        "contexts": [{
            "goal": "Follow these steps to perform this Battery Troubleshooting",
            "title": "Battery performance",
            "score": 0.95,
            "actions": [_action(deeplink={
                "deeplink": "bixby://masked/catalog-screen",
                "description": "Opens the battery settings page in device Settings.",
                "message": "Open Battery Settings",
                "originalType": "onClickURL",
            })],
        }],
    }


def _result(plan: dict):
    return validate_plan(plan, CATALOG)


def test_valid_catalog_deeplink_plan() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["actions"][0]["stepGroups"][0]["validationDeeplink"] = {
        "deeplink": "bixby://masked/catalog-validation",
        "key": "Battery",
        "resultType": "boolean",
        "condition": "equal",
        "value": "True",
    }
    result = _result(plan)
    assert result.valid is True
    assert result.errors == ()


def test_valid_manual_action_has_no_deeplink() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["actions"] = [_action(category="manual", deeplink=None, name="Contact Support")]
    assert _result(plan).valid is True


def test_valid_dummy_positive_with_self_written_text() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["actions"][0]["stepGroups"][0]["actionableDeeplink"] = {
        "deeplink": "bixby://dummy_positive",
        "description": "Opens the Storage Settings screen",
        "message": "Open the Storage screen in Settings",
        "originalType": "placeholder",
    }
    assert _result(plan).valid is True


@pytest.mark.parametrize("uri", [
    "bixby://masked/not-in-catalog",
    "bixby://masked/catalog-screen-modified",
    "https://example.com/settings",
    "http://example.com/settings",
    "[Settings](https://example.com)",
])
def test_invalid_or_external_deeplink_is_rejected(uri: str) -> None:
    plan = _valid_plan()
    link = plan["contexts"][0]["actions"][0]["stepGroups"][0]["actionableDeeplink"]
    link["deeplink"] = uri
    assert _result(plan).valid is False


def test_external_url_in_step_is_rejected() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["actions"][0]["stepGroups"][0]["steps"] = ["Open https://example.com/settings."]
    assert _result(plan).valid is False


@pytest.mark.parametrize("title", ["Battery", "Battery performance troubleshooting battery"])
def test_invalid_title_length(title: str) -> None:
    plan = _valid_plan()
    plan["contexts"][0]["title"] = title
    assert _result(plan).valid is False


def test_title_sentence_case_is_required() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["title"] = "BATTERY PERFORMANCE"
    assert _result(plan).valid is False


@pytest.mark.parametrize("title", ["Battery drain", "Network issue", "Display brightness", "eSIM setup", "5G settings"])
def test_valid_sentence_case_titles(title: str) -> None:
    plan = _valid_plan()
    plan["contexts"][0]["title"] = title
    assert _result(plan).valid is True


@pytest.mark.parametrize("title", ["Battery Drain", "Network Issue", "Display Brightness"])
def test_subsequent_title_words_must_not_be_title_cased(title: str) -> None:
    plan = _valid_plan()
    plan["contexts"][0]["title"] = title
    assert _result(plan).valid is False


def test_invalid_description_length_and_prefix() -> None:
    too_short = _valid_plan()
    too_short["contexts"][0]["actions"][0]["description"] = "It will help"
    assert _result(too_short).valid is False

    wrong_prefix = _valid_plan()
    wrong_prefix["contexts"][0]["actions"][0]["description"] = "This action improves battery performance"
    assert _result(wrong_prefix).valid is False


def test_score_outside_range_is_rejected() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["score"] = 1.1
    assert _result(plan).valid is False


def test_duplicate_query_variations_fail() -> None:
    plan = _valid_plan()
    plan["query_variations"][-1] = plan["query_variations"][0]
    assert _result(plan).valid is False


@pytest.mark.parametrize("count", [7, 11])
def test_query_variations_must_contain_8_to_10_values(count: int) -> None:
    plan = _valid_plan()
    plan["query_variations"] = [f"variation {i}" for i in range(count)]
    assert _result(plan).valid is False


def test_multiple_screens_in_one_action_are_rejected() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["actions"][0]["actionName"] = "Battery and Display Settings"
    assert _result(plan).valid is False


@pytest.mark.parametrize("wording", ["and open", "and enable", "then change"])
def test_clear_multi_action_wording_is_rejected(wording: str) -> None:
    plan = _valid_plan()
    plan["contexts"][0]["actions"][0]["description"] = f"It will open settings {wording} brightness"
    assert _result(plan).valid is False


def test_normal_conjunction_without_second_action_is_allowed() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["actions"][0]["description"] = "It will improve battery life and stability"
    plan["contexts"][0]["actions"][0]["actionName"] = "Battery care"
    assert _result(plan).valid is True


def test_critical_action_incorrectly_ordered_is_rejected() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["actions"] = [
        _action(category="critical", name="Restart Device"),
        _action(category="auto", name="Battery Settings"),
    ]
    assert _result(plan).valid is False


def test_manual_action_with_deeplink_is_rejected() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["actions"][0]["category"] = "manual"
    assert _result(plan).valid is False


def test_dummy_positive_with_wrong_word_count_is_rejected() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["actions"][0]["stepGroups"][0]["actionableDeeplink"]["deeplink"] = "bixby://dummy_positive"
    assert _result(plan).valid is False


def test_validation_deeplink_must_be_catalog_value() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["actions"][0]["stepGroups"][0]["validationDeeplink"] = {
        "deeplink": "bixby://masked/not-a-validation-uri",
        "key": "Battery",
    }
    assert _result(plan).valid is False


def test_validation_is_deterministic() -> None:
    first = _result(_valid_plan())
    second = _result(_valid_plan())
    assert first == second


@pytest.mark.parametrize("goal", ["Fix my battery", "Follow these steps to troubleshoot battery performance", "Follow these steps to perform this Troubleshooting"])
def test_goal_must_follow_official_syntax(goal: str) -> None:
    plan = _valid_plan()
    plan["contexts"][0]["goal"] = goal
    assert _result(plan).valid is False


def test_goal_configuration_form_is_accepted() -> None:
    plan = _valid_plan()
    plan["contexts"][0]["goal"] = "Follow these steps to perform this Battery Configuration"
    assert _result(plan).valid is True
