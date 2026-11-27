def create(client, **data):
    payload = {"title": "Note", "text": "hello world"} | data
    r = client.post("/api/transcriptions", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_crud_lifecycle(client):
    created = create(client, title="Standup", text="आज की meeting cancel है")
    assert created["language"] == "hi-en"
    assert created["language_label"] == "Hindi + English"
    assert created["source"] == "manual"
    assert created["word_count"] == 5

    tid = created["id"]
    assert client.get(f"/api/transcriptions/{tid}").json()["title"] == "Standup"

    r = client.patch(f"/api/transcriptions/{tid}", json={"text": "The meeting is cancelled."})
    assert r.status_code == 200
    assert r.json()["language"] == "en"  # re-detected from the new text
    assert r.json()["title"] == "Standup"

    r = client.patch(f"/api/transcriptions/{tid}", json={"title": "Renamed", "language": "hi"})
    assert r.json()["title"] == "Renamed" and r.json()["language"] == "hi"

    assert client.delete(f"/api/transcriptions/{tid}").status_code == 204
    assert client.get(f"/api/transcriptions/{tid}").status_code == 404
    assert client.delete(f"/api/transcriptions/{tid}").status_code == 404


def test_list_search_filter_and_paging(client):
    create(client, title="Groceries", text="buy milk and bread")
    create(client, title="Hindi", text="मुझे दूध चाहिए")
    create(client, title="Mixed", text="mujhe milk chahiye, abhi kal nahi")
    create(client, title="100% done", text="literal percent")

    page = client.get("/api/transcriptions").json()
    assert page["total"] == 4
    assert [i["title"] for i in page["items"]][0] == "100% done"  # newest first

    assert client.get("/api/transcriptions", params={"q": "MILK"}).json()["total"] == 2
    assert client.get("/api/transcriptions", params={"q": "%"}).json()["total"] == 1  # wildcard is escaped
    assert client.get("/api/transcriptions", params={"language": "hi"}).json()["total"] == 1
    assert client.get("/api/transcriptions", params={"language": "hi-en"}).json()["items"][0]["title"] == "Mixed"

    second = client.get("/api/transcriptions", params={"limit": 3, "offset": 3}).json()
    assert len(second["items"]) == 1 and second["offset"] == 3


def test_validation_errors(client):
    assert client.post("/api/transcriptions", json={"title": "", "text": "x"}).status_code == 422
    assert client.post("/api/transcriptions", json={"title": "x", "language": "fr"}).status_code == 422
    assert client.get("/api/transcriptions", params={"limit": 0}).status_code == 422
    assert client.patch("/api/transcriptions/999", json={"title": "x"}).status_code == 404


def test_stats(client):
    create(client, title="a", text="one two three")
    create(client, title="b", text="नमस्ते दुनिया")
    s = client.get("/api/stats").json()
    assert s["total"] == 2
    assert s["total_words"] == 5
    assert s["by_language"] == {"en": 1, "hi": 1}
    assert s["by_source"] == {"manual": 2}


def test_health_reports_missing_key(client):
    h = client.get("/api/health").json()
    assert h["stt"]["provider"] == "gemini"
    assert h["stt"]["configured"] is False


def test_ui_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Vaani" in r.text
