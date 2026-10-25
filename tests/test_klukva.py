"""
Comprehensive test script for Klukva backend & API
"""

import asyncio
import os
import sys
import httpx

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app
from backend.db import db, DEFAULT_DB, _lock


async def run_tests():
    # Clean database before tests
    with _lock:
        db._atomic_write(DEFAULT_DB)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        print("--- 1. Testing Registration & Login ---")
        # Register user1 (alice)
        res = await client.post("/api/auth/register", json={
            "username": "alice",
            "password": "secretpassword",
            "display_name": "Алиса Смирнова"
        })
        assert res.status_code == 200, f"Register alice failed: {res.text}"
        token_alice = res.json()["token"]

        # Register user2 (bob)
        res = await client.post("/api/auth/register", json={
            "username": "bob",
            "password": "bobpassword",
            "display_name": "Боб Ковалев"
        })
        assert res.status_code == 200, f"Register bob failed: {res.text}"
        token_bob = res.json()["token"]

        # Login alice
        res = await client.post("/api/auth/login", json={
            "username": "alice",
            "password": "secretpassword"
        })
        assert res.status_code == 200, f"Login alice failed: {res.text}"
        headers_alice = {"Authorization": f"Bearer {token_alice}"}
        headers_bob = {"Authorization": f"Bearer {token_bob}"}

        # Verify /api/auth/me
        res = await client.get("/api/auth/me", headers=headers_alice)
        assert res.status_code == 200
        assert res.json()["username"] == "alice"
        print("Users successfully created and authenticated.")

        print("--- 2. Testing Task Creation in Backlog ---")
        # Task 1: Unassigned in Backlog with 5 SP
        res = await client.post("/api/tasks", headers=headers_alice, json={
            "title": "Спроектировать архитектуру API",
            "description": "Описать эндпоинты и структуры данных для хранения в JSON",
            "story_points": 5,
            "status": "Бэклог"
        })
        assert res.status_code == 201
        task1 = res.json()
        assert task1["key"] == "KLUK-1"
        assert task1["status"] == "Бэклог"
        assert task1["story_points"] == 5

        # Task 2: Assigned to bob with 3 SP
        res = await client.post("/api/tasks", headers=headers_alice, json={
            "title": "Реализовать интерфейс очередей",
            "description": "Сделать разделение по исполнителям",
            "story_points": 3,
            "assignee": "bob",
            "status": "В работе"
        })
        assert res.status_code == 201
        task2 = res.json()
        assert task2["key"] == "KLUK-2"
        assert task2["assignee"] == "bob"

        # Task 3: Unassigned with 8 SP
        res = await client.post("/api/tasks", headers=headers_bob, json={
            "title": "Оптимизация производительности JSON",
            "description": "Проверить задержки записи",
            "story_points": 8,
            "status": "Бэклог"
        })
        assert res.status_code == 201
        task3 = res.json()
        print("Tasks created: KLUK-1, KLUK-2, KLUK-3.")

        print("--- 3. Testing Filters ---")
        # Filter by status: Бэклог
        res = await client.get("/api/tasks?status=Бэклог", headers=headers_alice)
        assert res.status_code == 200
        tasks_backlog = res.json()
        assert len(tasks_backlog) == 2
        assert all(t["status"] == "Бэклог" for t in tasks_backlog)

        # Filter by Story Points: 5
        res = await client.get("/api/tasks?story_points=5", headers=headers_alice)
        assert res.status_code == 200
        tasks_sp5 = res.json()
        assert len(tasks_sp5) == 1
        assert tasks_sp5[0]["key"] == "KLUK-1"

        # Filter by assignee: bob
        res = await client.get("/api/tasks?assignee=bob", headers=headers_alice)
        assert res.status_code == 200
        tasks_bob = res.json()
        assert len(tasks_bob) == 1
        assert tasks_bob[0]["key"] == "KLUK-2"
        print("Filters validated successfully.")

        print("--- 4. Testing 'Take Task' Action (+) ---")
        # Bob takes KLUK-1 (which was in Backlog, unassigned)
        res = await client.post(f"/api/tasks/{task1['id']}/take", headers=headers_bob)
        assert res.status_code == 200
        taken_task = res.json()
        assert taken_task["assignee"] == "bob"
        assert taken_task["status"] == "В работе"
        print("Task KLUK-1 taken by Bob: assignee=bob, status='В работе'.")

        print("--- 5. Testing Partial Implementation Split ---")
        # Change status of KLUK-1 to "Реализовано частично"
        res = await client.patch(f"/api/tasks/{task1['id']}", headers=headers_bob, json={
            "status": "Реализовано частично"
        })
        assert res.status_code == 200
        assert res.json()["status"] == "Реализовано частично"

        # Split partial: uncompleted part moved into backlog as new task
        res = await client.post(f"/api/tasks/{task1['id']}/split-partial", headers=headers_bob, json={
            "title": "[Остаток] Спроектировать архитектуру API (кеширование)",
            "description": "Нереализованная часть по кешированию",
            "story_points": 2
        })
        assert res.status_code == 200
        split_res = res.json()
        new_backlog_task = split_res["backlog_task"]
        assert new_backlog_task["status"] == "Бэклог"
        assert new_backlog_task["story_points"] == 2
        assert new_backlog_task["parent_task_id"] == task1["id"]
        print(f"Partial task split successfully! Created new task {new_backlog_task['key']} in Backlog.")

        print("--- 6. Testing Comments & Mentions ---")
        # Alice comments on KLUK-1 mentioning @bob
        res = await client.post(f"/api/tasks/{task1['id']}/comments", headers=headers_alice, json={
            "text": "Привет @bob! Проверь, пожалуйста, спецификацию перед разделением."
        })
        assert res.status_code == 201
        comment = res.json()
        assert comment["author"] == "alice"
        assert "bob" in comment["mentions"]

        # Bob gets comments for KLUK-1
        res = await client.get(f"/api/tasks/{task1['id']}/comments", headers=headers_bob)
        assert res.status_code == 200
        comments = res.json()
        assert len(comments) >= 2

        # Bob tries to edit Alice's comment -> 403 Forbidden
        res = await client.patch(f"/api/tasks/{task1['id']}/comments/{comment['id']}", headers=headers_bob, json={
            "text": "Попытка Боба изменить чужой комментарий"
        })
        assert res.status_code == 403

        # Alice edits her own comment -> 200 OK
        res = await client.patch(f"/api/tasks/{task1['id']}/comments/{comment['id']}", headers=headers_alice, json={
            "text": "Обновленный комментарий Алисы @bob!"
        })
        assert res.status_code == 200
        assert res.json()["text"] == "Обновленный комментарий Алисы @bob!"

        # Bob tries to delete Alice's comment -> 403 Forbidden
        res = await client.delete(f"/api/tasks/{task1['id']}/comments/{comment['id']}", headers=headers_bob)
        assert res.status_code == 403

        # Alice deletes her own comment -> 200 OK
        res = await client.delete(f"/api/tasks/{task1['id']}/comments/{comment['id']}", headers=headers_alice)
        assert res.status_code == 200
        assert res.json()["ok"] is True
        print("Comments edit/delete permissions verified successfully.")

        print("--- 7. Testing Sprint & Reordering ---")
        # Toggle task1 into sprint
        res = await client.post(f"/api/tasks/{task1['id']}/toggle-sprint", headers=headers_alice)
        assert res.status_code == 200
        assert res.json()["in_sprint"] is True

        # Verify task1 is in sprint
        res = await client.get("/api/tasks?in_sprint=true", headers=headers_alice)
        assert res.status_code == 200
        sprint_tasks = res.json()
        assert any(t["id"] == task1["id"] for t in sprint_tasks)

        # Reorder tasks: [task3, task2, task1]
        reorder_ids = [task3["id"], task2["id"], task1["id"]]
        res = await client.post("/api/tasks/reorder", headers=headers_alice, json={"task_ids": reorder_ids})
        assert res.status_code == 200
        assert res.json()["ok"] is True

        # Fetch tasks and verify order
        res = await client.get("/api/tasks", headers=headers_alice)
        assert res.status_code == 200
        all_ordered = res.json()
        ordered_ids_result = [t["id"] for t in all_ordered if t["id"] in reorder_ids]
        assert ordered_ids_result == reorder_ids, f"Expected {reorder_ids}, got {ordered_ids_result}"
        print("Sprint toggle and reorder verified successfully.")

        print("--- 8. Testing Sprint Lifecycle (Create & Close) ---")
        # Create active sprint
        res = await client.post("/api/sprints", headers=headers_alice, json={
            "name": "Спринт 1",
            "goal": "Запустить MVP"
        })
        assert res.status_code == 201
        sprint1 = res.json()
        assert sprint1["name"] == "Спринт 1"
        assert sprint1["status"] == "active"

        # Check active sprint
        res = await client.get("/api/sprints/active", headers=headers_alice)
        assert res.status_code == 200
        active_sprint = res.json()
        assert active_sprint["id"] == sprint1["id"]

        # Close sprint
        res = await client.post(f"/api/sprints/{sprint1['id']}/close", headers=headers_alice)
        assert res.status_code == 200
        close_res = res.json()
        assert close_res["ok"] is True
        assert close_res["new_sprint"] is not None
        assert close_res["new_sprint"]["name"] == "Спринт 2"

        # Check new active sprint is now active
        res = await client.get("/api/sprints/active", headers=headers_alice)
        assert res.status_code == 200
        new_active = res.json()
        assert new_active is not None
        assert new_active["name"] == "Спринт 2"
        assert new_active["status"] == "active"

        # Check that unfinished task1 moved into the new sprint
        res = await client.get(f"/api/tasks/{task1['id']}", headers=headers_alice)
        assert res.status_code == 200
        t1_data = res.json()
        assert t1_data["in_sprint"] is True
        assert t1_data["sprint_id"] == new_active["id"]
        print("Sprint lifecycle (close old, roll over unfinished tasks into new active sprint) verified successfully.")

        print("--- 9. Verifying JSON Database File ---")
        db_path = db.file_path
        assert os.path.exists(db_path), f"DB file does not exist at {db_path}"
        with open(db_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "KLUK-1" in content
        assert "alice" in content
        assert "bob" in content
        print(f"Database file is valid and saved at {db_path}.")

        print("\n>>> ALL TESTS PASSED SUCCESSFULLY! <<<")


if __name__ == "__main__":
    asyncio.run(run_tests())

