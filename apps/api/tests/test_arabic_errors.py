"""Every error a user can see is in Arabic.

Services raise errors with English messages (they also go to the logs). The
single error envelope (app.core.errors.error_body) turns them into Arabic.
Codes never change: clients branch on the code, people read the message.
"""

import ast
import re
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core import errors
from app.core.messages_ar import FALLBACK_BY_CODE, MESSAGES_AR, to_arabic

ARABIC = re.compile(r"[؀-ۿ]")
LATIN_WORD = re.compile(r"[A-Za-z]{3,}")
APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _error_classes() -> set[str]:
    return {
        name
        for name, obj in vars(errors).items()
        if isinstance(obj, type)
        and issubclass(obj, Exception)
        and obj.__module__ == errors.__name__
    }


def _module_constants(tree: ast.Module) -> dict[str, str]:
    return {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def _raised_messages() -> set[str]:
    """Every literal message passed to an app error class, constants resolved."""
    classes = _error_classes()
    found: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = _module_constants(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) in classes):
                continue
            if not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.add(arg.value)
            elif isinstance(arg, ast.Name) and arg.id in constants:
                found.add(constants[arg.id])
    return found


def test_every_raised_message_has_an_arabic_version() -> None:
    messages = _raised_messages()
    assert len(messages) > 40  # the scan really found the raise sites

    generic = to_arabic("no-such-code", "a message nobody translated")
    missing = sorted(m for m in messages if to_arabic("no-such-code", m) == generic)
    assert not missing, f"Add Arabic for these in app/core/messages_ar.py: {missing}"


def test_translations_contain_no_english_words() -> None:
    for english, arabic in MESSAGES_AR.items():
        assert ARABIC.search(arabic), english
        assert not LATIN_WORD.search(arabic), (english, arabic)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("name cannot be null", "حقل «الاسم» مطلوب."),
        ("sale_price cannot be null", "حقل «سعر البيع» مطلوب."),
        ("transfer is not writable yet", "هذا النوع من الحركات غير متاح بعد."),
    ],
)
def test_dynamic_messages_are_translated(message: str, expected: str) -> None:
    assert to_arabic("unprocessable", message) == expected


@pytest.mark.parametrize("code", sorted(FALLBACK_BY_CODE))
def test_unknown_english_message_falls_back_to_arabic_for_its_code(code: str) -> None:
    result = to_arabic(code, "Some message nobody translated")
    assert result == FALLBACK_BY_CODE[code]
    assert ARABIC.search(result)


def test_unknown_code_still_gets_arabic() -> None:
    assert ARABIC.search(to_arabic("brand_new_code", "Something odd"))


def test_arabic_message_passes_through_unchanged() -> None:
    assert to_arabic("assistant_unavailable", "المساعد مش متاح") == "المساعد مش متاح"


# --- through the API ---------------------------------------------------------


async def test_wrong_password_message_is_arabic(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody-at-all@example.com", "password": "Wrong-Password-1"},
    )

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "unauthorized",
        "message": "البريد الإلكتروني أو كلمة المرور غير صحيحة.",
        "request_id": response.json()["error"]["request_id"],
    }


async def test_unknown_route_message_is_arabic(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"
    assert ARABIC.search(response.json()["error"]["message"])


async def test_validation_error_message_is_arabic(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/login", json={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert ARABIC.search(response.json()["error"]["message"])
