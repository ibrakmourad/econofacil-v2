"""Testes de integração dos fluxos de autenticação e LGPD."""
import pyotp

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/users/me"

USER = {
    "email": "ana@example.com",
    "full_name": "Ana Souza",
    "password": "SenhaForte123",
}


async def _register_and_login(client):
    await client.post(REGISTER, json=USER)
    resp = await client.post(
        LOGIN, json={"email": USER["email"], "password": USER["password"]}
    )
    tokens = resp.json()
    return tokens


def _auth(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_register_creates_user(client):
    resp = await client.post(REGISTER, json=USER)
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == USER["email"]
    assert data["role"] == "consumer"
    assert "password" not in data


async def test_register_duplicate_email(client):
    await client.post(REGISTER, json=USER)
    resp = await client.post(REGISTER, json=USER)
    assert resp.status_code == 409


async def test_login_returns_token_pair(client):
    tokens = await _register_and_login(client)
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["token_type"] == "bearer"


async def test_login_wrong_password(client):
    await client.post(REGISTER, json=USER)
    resp = await client.post(
        LOGIN, json={"email": USER["email"], "password": "errada"}
    )
    assert resp.status_code == 401


async def test_me_requires_auth(client):
    resp = await client.get(ME)
    assert resp.status_code == 401


async def test_me_returns_profile(client):
    tokens = await _register_and_login(client)
    resp = await client.get(ME, headers=_auth(tokens))
    assert resp.status_code == 200
    assert resp.json()["email"] == USER["email"]


async def test_refresh_rotates_token(client):
    tokens = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200
    new_tokens = resp.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    # token antigo já foi revogado
    reuse = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert reuse.status_code == 401


async def test_2fa_full_flow(client):
    tokens = await _register_and_login(client)
    headers = _auth(tokens)

    setup = await client.post("/api/v1/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    code = pyotp.TOTP(secret).now()

    enable = await client.post(
        "/api/v1/auth/2fa/enable", json={"otp_code": code}, headers=headers
    )
    assert enable.status_code == 200

    # login agora exige o código 2FA
    no_code = await client.post(
        LOGIN, json={"email": USER["email"], "password": USER["password"]}
    )
    assert no_code.status_code == 401

    with_code = await client.post(
        LOGIN,
        json={
            "email": USER["email"],
            "password": USER["password"],
            "otp_code": pyotp.TOTP(secret).now(),
        },
    )
    assert with_code.status_code == 200


async def test_lgpd_consent_and_export(client):
    tokens = await _register_and_login(client)
    headers = _auth(tokens)

    update = await client.put(
        "/api/v1/lgpd/consents",
        json={"consents": [{"purpose": "marketing", "granted": True}]},
        headers=headers,
    )
    assert update.status_code == 200
    assert any(c["purpose"] == "marketing" and c["granted"] for c in update.json())

    export = await client.get("/api/v1/lgpd/export", headers=headers)
    assert export.status_code == 200
    assert export.json()["profile"]["email"] == USER["email"]


async def test_lgpd_account_deletion_anonymizes(client):
    tokens = await _register_and_login(client)
    headers = _auth(tokens)

    delete = await client.request("DELETE", "/api/v1/lgpd/account", headers=headers)
    assert delete.status_code == 200

    # após anonimizar, o login original deixa de funcionar
    relogin = await client.post(
        LOGIN, json={"email": USER["email"], "password": USER["password"]}
    )
    assert relogin.status_code == 401
