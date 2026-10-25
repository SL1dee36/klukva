/**
 * KLUKVA — Client Application (Flat Minimalist Theme)
 * 1. Бэклог: отображаются исключительно задачи бэклога (вне спринта)
 * 2. Спринты: текущий активный спринт + задачи бэклога для перетаскивания в спринт
 * 3. Скрам-доска: группированные колонки, свимлейны по каждому сотруднику, как на скриншоте
 * 
 * Без теней (box-shadow) и без эмодзи.
 */

// Состояние приложения
const urlParams = new URLSearchParams(window.location.search);
const paramToken = urlParams.get("token");
if (paramToken) {
  localStorage.setItem("klukva_token", paramToken);
}

const state = {
  token: paramToken || localStorage.getItem("klukva_token") || null,
  currentUser: null,
  users: [],
  tasks: [],
  activeSprint: null,
  currentTab: urlParams.get("tab") || "backlog", // 'backlog' | 'sprints' | 'board'
  boardFilterOnlyMy: false,
  currentTaskDetail: null,
};

// ---------------- ТЕМА ОФОРМЛЕНИЯ ----------------
function initTheme() {
  const paramTheme = urlParams.get("theme");
  const saved = paramTheme || localStorage.getItem("klukva_theme") || "light";
  applyTheme(saved);
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("klukva_theme", theme);
  const text = document.getElementById("themeToggleText");
  if (text) {
    text.textContent = theme === "dark" ? "Светлая тема" : "Тёмная тема";
  }
}

initTheme();

// ---------------- УПРАВЛЕНИЕ СПРИНТОМ ----------------
async function loadActiveSprint() {
  try {
    const active = await api("/api/sprints/active");
    state.activeSprint = (active && active.id) ? active : null;
    updateSprintUI();
  } catch (err) {
    console.error("Ошибка загрузки активного спринта:", err);
  }
}

function updateSprintUI() {
  const sprintName = document.getElementById("sprintNameDisplay");
  const sprintGoal = document.getElementById("sprintGoalDisplay");
  const btnClose = document.getElementById("btnCloseSprintInTab");
  const btnCreate = document.getElementById("btnCreateSprintInTab");
  const boardSprintName = document.getElementById("boardSprintNameDisplay");

  if (state.activeSprint) {
    if (sprintName) sprintName.textContent = state.activeSprint.name;
    if (boardSprintName) boardSprintName.textContent = `${state.activeSprint.name} (Активный)`;
    if (sprintGoal) {
      if (state.activeSprint.goal) {
        sprintGoal.textContent = `Цель: ${state.activeSprint.goal}`;
        sprintGoal.style.display = "inline-block";
      } else {
        sprintGoal.style.display = "none";
      }
    }
    if (btnCreate) btnCreate.style.display = "none";
    if (btnClose) btnClose.style.display = "inline-flex";
  } else {
    if (sprintName) sprintName.textContent = "Спринт не запущен";
    if (boardSprintName) boardSprintName.textContent = "Спринт не запущен";
    if (sprintGoal) sprintGoal.style.display = "none";
    if (btnCreate) btnCreate.style.display = "inline-flex";
    if (btnClose) btnClose.style.display = "none";
  }
}

function openCreateSprintModal() {
  document.getElementById("formCreateSprint").reset();
  const input = document.getElementById("inputSprintName");
  input.value = "Спринт 1";
  document.getElementById("modalCreateSprint").style.display = "flex";
  input.focus();
}

function closeCreateSprintModal() {
  document.getElementById("modalCreateSprint").style.display = "none";
}

async function handleCreateSprintSubmit(e) {
  e.preventDefault();
  const name = document.getElementById("inputSprintName").value.trim();
  const goal = document.getElementById("inputSprintGoal").value.trim();

  try {
    const newSprint = await api("/api/sprints", {
      method: "POST",
      body: JSON.stringify({ name, goal })
    });
    closeCreateSprintModal();
    showToast(`Спринт "${newSprint.name}" успешно запущен`);
    await loadActiveSprint();
    await loadTasks();
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
}

async function handleCloseSprint() {
  if (!state.activeSprint) return;
  const sprintName = state.activeSprint.name;
  if (!confirm(`Завершить спринт "${sprintName}"?\nВыполненные задачи сохранятся в истории, а невыполненные вернутся в бэклог.`)) {
    return;
  }

  try {
    const result = await api(`/api/sprints/${state.activeSprint.id}/close`, {
      method: "POST"
    });
    showToast(`Спринт "${sprintName}" завершен. Выполнено: ${result.completed_count}, возвращено в бэклог: ${result.backlog_count}`);
    await loadActiveSprint();
    await loadTasks();
  } catch (err) {
    showToast(`Ошибка закрытия спринта: ${err.message}`);
  }
}

// ---------------- СЕТЕВЫЕ ЗАПРОСЫ (API) ----------------
async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(state.token ? { "Authorization": `Bearer ${state.token}` } : {}),
    ...(options.headers || {})
  };

  const response = await fetch(path, { ...options, headers });

  if (response.status === 401) {
    state.token = null;
    state.currentUser = null;
    localStorage.removeItem("klukva_token");
    showAuthModal();
    throw new Error("Необходима авторизация");
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `Ошибка сервера (${response.status})`);
  }

  return response.json();
}

// ---------------- УВЕДОМЛЕНИЯ (TOAST) ----------------
function showToast(message) {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 3200);
}

// ---------------- СТАТУСЫ И БЕЙДЖИ ----------------
const STATUS_CLASSES = {
  "Бэклог": "status-backlog",
  "В работе": "status-in-progress",
  "Завершено": "status-done",
  "Реализовано частично": "status-partial",
  "Не реализовано": "status-not-implemented"
};

function renderStatusBadge(status) {
  const cls = STATUS_CLASSES[status] || "status-backlog";
  return `<span class="status-pill ${cls}">${escapeHtml(status)}</span>`;
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatDate(isoStr) {
  if (!isoStr) return "";
  const d = new Date(isoStr);
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function pluralizeTasks(count) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod100 >= 11 && mod100 <= 19) return "задач";
  if (mod10 === 1) return "задача";
  if (mod10 >= 2 && mod10 <= 4) return "задачи";
  return "задач";
}

// ---------------- ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ ----------------
document.addEventListener("DOMContentLoaded", async () => {
  initTheme();
  setupEventListeners();

  if (state.token) {
    try {
      state.currentUser = await api("/api/auth/me");
      await onAuthSuccess();
    } catch (err) {
      showAuthModal();
    }
  } else {
    showAuthModal();
  }
});

async function onAuthSuccess() {
  hideAuthModal();
  updateUserHeader();
  await loadUsers();
  await loadActiveSprint();

  if (state.currentTab && state.currentTab !== "backlog") {
    switchTab(state.currentTab);
  } else {
    await loadTasks();
  }

  const path = window.location.pathname;
  const match = path.match(/\/task\/(\d+)/);
  if (match) {
    openTaskDetail(parseInt(match[1], 10));
  }
}

function updateUserHeader() {
  const profileDiv = document.getElementById("userProfile");
  const label = document.getElementById("userDisplayName");
  const avatar = document.getElementById("userAvatar");
  if (state.currentUser) {
    profileDiv.style.display = "flex";
    label.textContent = `${state.currentUser.display_name} (@${state.currentUser.username})`;
    avatar.textContent = (state.currentUser.display_name || state.currentUser.username).charAt(0).toUpperCase();
  } else {
    profileDiv.style.display = "none";
  }
}

async function loadUsers() {
  try {
    state.users = await api("/api/users");
    populateAssigneeSelects();
  } catch (err) {
    console.error("Ошибка загрузки пользователей:", err);
  }
}

function populateAssigneeSelects() {
  const selects = [
    document.getElementById("createAssignee"),
    document.getElementById("detailAssignee"),
    document.getElementById("splitAssignee"),
    document.getElementById("filterAssignee")
  ];

  selects.forEach(select => {
    if (!select) return;
    const isFilter = select.id === "filterAssignee";
    const currentValue = select.value;

    select.innerHTML = isFilter
      ? '<option value="">Все исполнители</option><option value="unassigned">Не назначен</option>'
      : '<option value="">Не назначен</option>';

    state.users.forEach(u => {
      const opt = document.createElement("option");
      opt.value = u.username;
      opt.textContent = `${u.display_name} (@${u.username})`;
      select.appendChild(opt);
    });

    if (currentValue) select.value = currentValue;
  });
}

// ---------------- ЗАГРУЗКА ЗАДАЧ ----------------
async function loadTasks() {
  try {
    const status = document.getElementById("filterStatus").value;
    const spVal = document.getElementById("filterSp").value;
    const assignee = document.getElementById("filterAssignee").value;
    const search = document.getElementById("filterSearch").value.trim();

    const params = new URLSearchParams();
    if (status) params.append("status", status);
    if (spVal) params.append("story_points", spVal);
    if (assignee) params.append("assignee", assignee);
    if (search) params.append("search", search);

    state.tasks = await api(`/api/tasks?${params.toString()}`);

    if (state.currentTab === "backlog") {
      renderPureBacklog();
    } else if (state.currentTab === "sprints") {
      renderSprintsView();
    } else if (state.currentTab === "board") {
      renderScrumBoard();
    }
  } catch (err) {
    showToast(err.message);
  }
}

// ============================================================================
// 1. ВКЛАДКА "БЭКЛОГ" (ТОЛЬКО ЗАДАЧИ БЭКЛОГА)
// ============================================================================
function renderPureBacklog() {
  const tbody = document.getElementById("pureBacklogTableBody");
  const emptyEl = document.getElementById("pureBacklogEmptyState");
  const metricsEl = document.getElementById("backlogMetrics");
  const countEl = document.getElementById("backlogCount");
  const spTotalEl = document.getElementById("backlogSpTotal");

  tbody.innerHTML = "";

  // В бэклоге отображаются только те задачи, которые не включены в спринт
  const backlogTasks = state.tasks.filter(t => !t.in_sprint);

  let totalSp = 0;
  backlogTasks.forEach(t => {
    if (t.story_points) totalSp += Number(t.story_points);

    const tr = document.createElement("tr");

    // Ключ
    const tdKey = document.createElement("td");
    tdKey.innerHTML = `<span class="task-key-link" onclick="openTaskDetail(${t.id})">${t.key}</span>`;
    tr.appendChild(tdKey);

    // Название
    const tdTitle = document.createElement("td");
    tdTitle.className = "task-title-cell";
    tdTitle.textContent = t.title;
    tdTitle.onclick = () => openTaskDetail(t.id);
    tr.appendChild(tdTitle);

    // Story Points
    const tdSp = document.createElement("td");
    tdSp.style.textAlign = "center";
    tdSp.innerHTML = (t.story_points !== null && t.story_points !== undefined)
      ? `<span class="sp-badge">${t.story_points} SP</span>`
      : '<span style="color: var(--text-dim)">—</span>';
    tr.appendChild(tdSp);

    // Исполнитель
    const tdAssignee = document.createElement("td");
    const uObj = state.users.find(u => u.username.toLowerCase() === (t.assignee || "").toLowerCase());
    tdAssignee.innerHTML = t.assignee
      ? `<span class="assignee-badge">${escapeHtml(uObj ? uObj.display_name : t.assignee)}</span>`
      : '<span class="assignee-badge unassigned">Не назначен</span>';
    tr.appendChild(tdAssignee);

    // Статус
    const tdStatus = document.createElement("td");
    tdStatus.innerHTML = renderStatusBadge(t.status);
    tr.appendChild(tdStatus);

    // Действия
    const tdAction = document.createElement("td");
    tdAction.style.textAlign = "right";

    const btnSprint = document.createElement("button");
    btnSprint.className = "btn-sprint-action";
    btnSprint.textContent = "+ В спринт";
    btnSprint.onclick = async (e) => {
      e.stopPropagation();
      await toggleSprint(t.id);
    };
    tdAction.appendChild(btnSprint);

    const btnTake = document.createElement("button");
    btnTake.className = "btn-take-task";
    btnTake.style.marginLeft = "6px";
    btnTake.textContent = "+";
    btnTake.title = "Взять на себя";
    btnTake.onclick = (e) => {
      e.stopPropagation();
      takeTask(t.id);
    };
    tdAction.appendChild(btnTake);

    tr.appendChild(tdAction);
    tbody.appendChild(tr);
  });

  emptyEl.style.display = backlogTasks.length === 0 ? "block" : "none";
  metricsEl.textContent = `${backlogTasks.length} ${pluralizeTasks(backlogTasks.length)} • ${totalSp} SP`;
  countEl.textContent = `${backlogTasks.length} ${pluralizeTasks(backlogTasks.length)}`;
  spTotalEl.textContent = `${totalSp} SP`;

  const countMobileEl = document.getElementById("backlogCountMobile");
  const spTotalMobileEl = document.getElementById("backlogSpTotalMobile");
  if (countMobileEl) countMobileEl.textContent = `${backlogTasks.length} ${pluralizeTasks(backlogTasks.length)}`;
  if (spTotalMobileEl) spTotalMobileEl.textContent = `${totalSp} SP`;

  const statusVal = document.getElementById("filterStatus")?.value;
  const spVal = document.getElementById("filterSp")?.value;
  const assigneeVal = document.getElementById("filterAssignee")?.value;
  const searchVal = document.getElementById("filterSearch")?.value?.trim();
  const filterDot = document.getElementById("filterActiveDot");
  if (filterDot) {
    filterDot.style.display = (statusVal || spVal || assigneeVal || searchVal) ? "inline" : "none";
  }
}

// ============================================================================
// 2. ВКЛАДКА "СПРИНТЫ" (ТЕКУЩИЙ СПРИНТ + ПЕРЕТАСКИВАНИЕ ИЗ БЭКЛОГА)
// ============================================================================
let draggedRow = null;
let draggedTaskId = null;

function renderSprintsView() {
  updateSprintUI();

  const sprintTbody = document.getElementById("sprintTableBody");
  const backlogTbody = document.getElementById("backlogTableBody");
  const sprintEmpty = document.getElementById("sprintEmptyState");
  const backlogEmpty = document.getElementById("backlogEmptyState");
  const sprintStats = document.getElementById("sprintStats");
  const backlogSubStats = document.getElementById("backlogSubStats");

  sprintTbody.innerHTML = "";
  backlogTbody.innerHTML = "";

  const sprintTasks = state.tasks.filter(t => Boolean(t.in_sprint));
  const backlogTasks = state.tasks.filter(t => !t.in_sprint);

  let sprintSp = 0;
  let backlogSp = 0;

  sprintTasks.forEach(t => {
    if (t.story_points) sprintSp += Number(t.story_points);
    sprintTbody.appendChild(createDraggableTaskRow(t, true));
  });

  backlogTasks.forEach(t => {
    if (t.story_points) backlogSp += Number(t.story_points);
    backlogTbody.appendChild(createDraggableTaskRow(t, false));
  });

  sprintEmpty.style.display = sprintTasks.length === 0 ? "block" : "none";
  backlogEmpty.style.display = backlogTasks.length === 0 ? "block" : "none";

  sprintStats.textContent = `${sprintTasks.length} ${pluralizeTasks(sprintTasks.length)} • ${sprintSp} SP`;
  backlogSubStats.textContent = `${backlogTasks.length} ${pluralizeTasks(backlogTasks.length)} • ${backlogSp} SP`;

  renderPastSprintsHistory();
}

function createDraggableTaskRow(task, inSprint) {
  const tr = document.createElement("tr");
  tr.className = "draggable-row";
  tr.draggable = true;
  tr.dataset.taskId = String(task.id);
  tr.dataset.inSprint = inSprint ? "1" : "0";

  // Хэндл для перетаскивания
  const tdDrag = document.createElement("td");
  tdDrag.style.width = "32px";
  tdDrag.style.textAlign = "center";
  tdDrag.innerHTML = '<span class="drag-handle" title="Перетащить">&#8942;&#8942;</span>';
  tr.appendChild(tdDrag);

  // Ключ
  const tdKey = document.createElement("td");
  tdKey.innerHTML = `<span class="task-key-link" onclick="openTaskDetail(${task.id})">${task.key}</span>`;
  tr.appendChild(tdKey);

  // Название
  const tdTitle = document.createElement("td");
  tdTitle.className = "task-title-cell";
  tdTitle.textContent = task.title;
  tdTitle.onclick = () => openTaskDetail(task.id);
  tr.appendChild(tdTitle);

  // Story Points
  const tdSp = document.createElement("td");
  tdSp.style.textAlign = "center";
  tdSp.innerHTML = (task.story_points !== null && task.story_points !== undefined)
    ? `<span class="sp-badge">${task.story_points} SP</span>`
    : '<span style="color: var(--text-dim)">—</span>';
  tr.appendChild(tdSp);

  // Исполнитель
  const tdAssignee = document.createElement("td");
  const uObj = state.users.find(u => u.username.toLowerCase() === (task.assignee || "").toLowerCase());
  tdAssignee.innerHTML = task.assignee
    ? `<span class="assignee-badge">${escapeHtml(uObj ? uObj.display_name : task.assignee)}</span>`
    : '<span class="assignee-badge unassigned">Не назначен</span>';
  tr.appendChild(tdAssignee);

  // Статус
  const tdStatus = document.createElement("td");
  tdStatus.innerHTML = renderStatusBadge(task.status);
  tr.appendChild(tdStatus);

  // Действия
  const tdAction = document.createElement("td");
  tdAction.style.textAlign = "right";

  const btnSprint = document.createElement("button");
  btnSprint.className = `btn-sprint-action ${inSprint ? "in-sprint" : ""}`;
  btnSprint.textContent = inSprint ? "Из спринта" : "+ В спринт";
  btnSprint.onclick = async (e) => {
    e.stopPropagation();
    await toggleSprint(task.id);
  };
  tdAction.appendChild(btnSprint);

  tr.appendChild(tdAction);

  setupRowDragEvents(tr, task);
  return tr;
}

function setupRowDragEvents(tr, task) {
  tr.addEventListener("dragstart", (e) => {
    draggedRow = tr;
    draggedTaskId = task.id;
    tr.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(task.id));
  });

  tr.addEventListener("dragend", () => {
    tr.classList.remove("dragging");
    document.querySelectorAll(".tasks-table tr").forEach(r => {
      r.classList.remove("drag-over-top", "drag-over-bottom");
    });
    document.querySelectorAll(".sprint-section-box").forEach(b => b.classList.remove("drag-over"));
    draggedRow = null;
    draggedTaskId = null;
  });

  tr.addEventListener("dragover", (e) => {
    e.preventDefault();
    if (!draggedRow || draggedRow === tr) return;

    const rect = tr.getBoundingClientRect();
    if (e.clientY < rect.top + rect.height / 2) {
      tr.classList.add("drag-over-top");
      tr.classList.remove("drag-over-bottom");
    } else {
      tr.classList.add("drag-over-bottom");
      tr.classList.remove("drag-over-top");
    }
  });

  tr.addEventListener("dragleave", () => {
    tr.classList.remove("drag-over-top", "drag-over-bottom");
  });

  tr.addEventListener("drop", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!draggedRow || draggedRow === tr) return;

    const rect = tr.getBoundingClientRect();
    const isAbove = e.clientY < (rect.top + rect.height / 2);
    tr.classList.remove("drag-over-top", "drag-over-bottom");

    const targetTbody = tr.closest("tbody");
    if (isAbove) {
      targetTbody.insertBefore(draggedRow, tr);
    } else {
      targetTbody.insertBefore(draggedRow, tr.nextSibling);
    }

    const targetInSprint = targetTbody.id === "sprintTableBody";
    await handleSprintDropReorder(draggedTaskId, targetInSprint);
  });
}

function setupSprintDropZones() {
  const sprintBox = document.getElementById("sectionSprint");
  const backlogBox = document.getElementById("sectionBacklog");

  [sprintBox, backlogBox].forEach(box => {
    if (!box) return;
    const isSprintZone = box.dataset.dropZone === "sprint";
    const tbody = isSprintZone ? document.getElementById("sprintTableBody") : document.getElementById("backlogTableBody");

    box.addEventListener("dragover", (e) => {
      e.preventDefault();
      box.classList.add("drag-over");
    });

    box.addEventListener("dragleave", (e) => {
      if (!box.contains(e.relatedTarget)) box.classList.remove("drag-over");
    });

    box.addEventListener("drop", async (e) => {
      e.preventDefault();
      box.classList.remove("drag-over");
      if (!draggedRow || !draggedTaskId) return;

      if (!e.target.closest("tr.draggable-row")) {
        tbody.appendChild(draggedRow);
        await handleSprintDropReorder(draggedTaskId, isSprintZone);
      }
    });
  });
}

async function handleSprintDropReorder(taskId, targetInSprint) {
  try {
    const taskObj = state.tasks.find(t => t.id === taskId);
    if (taskObj && Boolean(taskObj.in_sprint) !== targetInSprint) {
      taskObj.in_sprint = targetInSprint;
      await api(`/api/tasks/${taskId}`, {
        method: "PATCH",
        body: JSON.stringify({ in_sprint: targetInSprint })
      });
    }

    const allRows = document.querySelectorAll(".tasks-table tbody tr.draggable-row");
    const orderedIds = Array.from(allRows)
      .map(r => parseInt(r.dataset.taskId, 10))
      .filter(id => !isNaN(id));

    if (orderedIds.length > 0) {
      await api("/api/tasks/reorder", {
        method: "POST",
        body: JSON.stringify({ task_ids: orderedIds })
      });
    }

    showToast("Порядок задач сохранен");
    await loadTasks();
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
    await loadTasks();
  }
}

async function renderPastSprintsHistory() {
  const pastList = document.getElementById("pastSprintsList");
  if (!pastList) return;

  try {
    const allSprints = await api("/api/sprints");
    const closed = allSprints.filter(s => s.status === "closed");
    pastList.innerHTML = "";

    if (closed.length === 0) {
      pastList.innerHTML = '<div style="color: var(--text-dim); font-size: 12px; padding: 10px 0;">Завершенных спринтов пока нет</div>';
      return;
    }

    closed.forEach(s => {
      const card = document.createElement("div");
      card.className = "past-sprint-card";
      card.innerHTML = `
        <div class="past-sprint-header" onclick="togglePastSprintTasks(${s.id})">
          <div class="past-sprint-left">
            <span class="status-pill status-done">Завершен</span>
            <span class="past-sprint-title">${escapeHtml(s.name)}</span>
            ${s.goal ? `<span style="font-size: 12px; color: var(--text-muted);">&mdash; ${escapeHtml(s.goal)}</span>` : ""}
          </div>
          <div class="past-sprint-right">
            <span>${formatDate(s.closed_at || s.created_at)}</span>
            <span id="pastSprintArrow-${s.id}">▼</span>
          </div>
        </div>
        <div class="past-sprint-tasks-container" id="pastSprintTasks-${s.id}" style="display: none;">
          Загрузка задач...
        </div>
      `;
      pastList.appendChild(card);
    });
  } catch (err) {
    console.error("Ошибка загрузки истории спринтов:", err);
  }
}

window.togglePastSprintTasks = async function (sprintId) {
  const container = document.getElementById(`pastSprintTasks-${sprintId}`);
  const arrow = document.getElementById(`pastSprintArrow-${sprintId}`);
  if (!container) return;

  const isHidden = container.style.display === "none";
  container.style.display = isHidden ? "block" : "none";
  if (arrow) arrow.textContent = isHidden ? "▲" : "▼";

  if (isHidden) {
    try {
      const allTasks = await api("/api/tasks");
      const sprintDoneTasks = allTasks.filter(t => t.sprint_id === sprintId && t.status === "Завершено");
      if (sprintDoneTasks.length === 0) {
        container.innerHTML = '<div style="font-size: 12px; color: var(--text-dim);">В этом спринте нет завершенных задач.</div>';
      } else {
        container.innerHTML = `
          <div class="table-scroll-wrapper">
            <table class="tasks-table">
              <thead>
                <tr>
                  <th style="width: 100px;">Ключ</th>
                  <th>Название задачи</th>
                  <th style="width: 80px; text-align: center;">SP</th>
                  <th style="width: 150px;">Исполнитель</th>
                </tr>
              </thead>
              <tbody>
                ${sprintDoneTasks.map(t => `
                  <tr>
                    <td><span class="task-key-link" onclick="openTaskDetail(${t.id})">${t.key}</span></td>
                    <td class="task-title-cell" onclick="openTaskDetail(${t.id})">${escapeHtml(t.title)}</td>
                    <td style="text-align: center;">${t.story_points ?? "—"}</td>
                    <td>${escapeHtml(t.assignee || "—")}</td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        `;
      }
    } catch (err) {
      container.innerHTML = '<div style="color: red;">Ошибка загрузки</div>';
    }
  }
};

// ============================================================================
// 3. ВКЛАДКА "СКРАМ-ДОСКА" (ПО СКРИНШОТУ СО СВИМЛЕЙНАМИ И СТАТУСАМИ)
// ============================================================================
function renderScrumBoard() {
  const container = document.getElementById("scrumSwimlanesList");
  const counterEl = document.getElementById("boardTaskCount");
  container.innerHTML = "";

  // Если спринт запущен, берем задачи активного спринта, иначе все текущие задачи
  let boardTasks = state.activeSprint
    ? state.tasks.filter(t => Boolean(t.in_sprint))
    : state.tasks;

  // Фильтр "Только мои задачи"
  if (state.boardFilterOnlyMy && state.currentUser) {
    const myName = state.currentUser.username.toLowerCase();
    boardTasks = boardTasks.filter(t => t.assignee && t.assignee.toLowerCase() === myName);
  }

  counterEl.textContent = `${boardTasks.length} ${pluralizeTasks(boardTasks.length)}`;

  // 4 колонки с нашими статусами (без отдельного столбца "Частично")
  const STATUS_COLUMNS = [
    { key: "todo", title: "Бэклог", statuses: ["Бэклог"] },
    { key: "paused", title: "Не реализовано", statuses: ["Не реализовано"] },
    { key: "inprog", title: "В работе", statuses: ["В работе", "Реализовано частично"] },
    { key: "done", title: "Завершено", statuses: ["Завершено"] }
  ];

  // Группировка задач по исполнителям (Свимлейны)
  const assigneeMap = new Map();

  state.users.forEach(u => {
    assigneeMap.set(u.username.toLowerCase(), {
      name: u.display_name,
      username: u.username,
      tasks: []
    });
  });

  const unassignedTasks = [];

  boardTasks.forEach(t => {
    const a = (t.assignee || "").toLowerCase();
    if (a && assigneeMap.has(a)) {
      assigneeMap.get(a).tasks.push(t);
    } else if (a) {
      if (!assigneeMap.has(a)) {
        assigneeMap.set(a, { name: t.assignee, username: t.assignee, tasks: [] });
      }
      assigneeMap.get(a).tasks.push(t);
    } else {
      unassignedTasks.push(t);
    }
  });

  // Отрисовка свимлейна для каждого сотрудника
  assigneeMap.forEach((entry) => {
    renderSwimlane(container, entry.name, entry.username, entry.tasks, STATUS_COLUMNS);
  });

  // Отрисовка свимлейна для неназначенных задач
  if (unassignedTasks.length > 0) {
    renderSwimlane(container, "Не назначенные задачи", null, unassignedTasks, STATUS_COLUMNS);
  }
}

function renderSwimlane(parent, title, username, tasks, columns) {
  const lane = document.createElement("div");
  lane.className = "scrum-swimlane";
  lane.id = `swimlane-${username || "unassigned"}`;

  const header = document.createElement("div");
  header.className = "scrum-swimlane-header";
  header.innerHTML = `
    <div class="swimlane-header-content">
      <span class="swimlane-arrow">▼</span>
      <span class="swimlane-user-title">${escapeHtml(title)}</span>
      <span class="swimlane-count">${tasks.length} ${pluralizeTasks(tasks.length)}</span>
    </div>
  `;

  header.onclick = () => {
    lane.classList.toggle("collapsed");
  };

  const grid = document.createElement("div");
  grid.className = "scrum-swimlane-grid";

  // 4 ячейки под каждую колонку
  columns.forEach(col => {
    const cell = document.createElement("div");
    cell.className = "scrum-cell";
    cell.dataset.status = col.statuses[0];
    cell.dataset.assignee = username || "";

    const colTasks = tasks.filter(t => col.statuses.includes(t.status));
    colTasks.forEach(t => {
      const card = createScrumCard(t);
      cell.appendChild(card);
    });

    setupBoardCellDrop(cell);
    grid.appendChild(cell);
  });

  lane.appendChild(header);
  lane.appendChild(grid);
  parent.appendChild(lane);
}

function createScrumCard(task) {
  const card = document.createElement("div");
  card.className = "scrum-card";
  card.draggable = true;
  card.dataset.taskId = String(task.id);

  card.innerHTML = `
    <div class="scrum-card-top">
      <span class="task-key-link" onclick="openTaskDetail(${task.id})">${task.key}</span>
      ${task.story_points ? `<span class="sp-badge">${task.story_points} SP</span>` : ""}
    </div>
    <div class="scrum-card-title" onclick="openTaskDetail(${task.id})">${escapeHtml(task.title)}</div>
    <div class="scrum-card-bottom">
      <div>${renderStatusBadge(task.status)}</div>
      ${task.assignee ? `<span class="scrum-card-avatar" title="${escapeHtml(task.assignee)}">${task.assignee.charAt(0).toUpperCase()}</span>` : ""}
    </div>
  `;

  card.addEventListener("dragstart", (e) => {
    draggedTaskId = task.id;
    e.dataTransfer.setData("text/plain", String(task.id));
  });

  return card;
}

function setupBoardCellDrop(cell) {
  cell.addEventListener("dragover", (e) => {
    e.preventDefault();
    cell.classList.add("drag-over");
  });

  cell.addEventListener("dragleave", () => {
    cell.classList.remove("drag-over");
  });

  cell.addEventListener("drop", async (e) => {
    e.preventDefault();
    cell.classList.remove("drag-over");
    if (!draggedTaskId) return;

    const newStatus = cell.dataset.status;
    const newAssignee = cell.dataset.assignee || null;

    try {
      await api(`/api/tasks/${draggedTaskId}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: newStatus,
          assignee: newAssignee
        })
      });
      showToast(`Задача перенесена в "${newStatus}"`);
      await loadTasks();
    } catch (err) {
      showToast(`Ошибка: ${err.message}`);
    }
  });
}

// ---------------- ОБЩИЕ ОПЕРАЦИИ С ЗАДАЧАМИ ----------------
async function takeTask(taskId) {
  try {
    const updated = await api(`/api/tasks/${taskId}/take`, { method: "POST" });
    showToast(`Задача ${updated.key} взята вами в работу`);
    await loadTasks();
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
}

async function toggleSprint(taskId) {
  const task = state.tasks.find(t => t.id === taskId);
  if (task && !task.in_sprint && !state.activeSprint) {
    if (confirm("Активный спринт пока не создан. Создать спринт прямо сейчас?")) {
      openCreateSprintModal();
      return;
    }
  }

  try {
    const updated = await api(`/api/tasks/${taskId}/toggle-sprint`, { method: "POST" });
    showToast(updated.in_sprint ? `Задача ${updated.key} добавлена в спринт` : `Задача ${updated.key} перемещена в бэклог`);
    await loadTasks();
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
}

// ---------------- ПОЛНОЭКРАННЫЙ ПРОСМОТР ЗАДАЧИ ----------------
async function openTaskDetail(taskId) {
  try {
    const task = await api(`/api/tasks/${taskId}`);
    state.currentTaskDetail = task;

    document.getElementById("detailTaskKey").textContent = task.key;
    document.getElementById("detailStatusBadgeSlot").innerHTML = renderStatusBadge(task.status);
    document.getElementById("displayTitle").textContent = task.title;
    document.getElementById("inputEditTitle").value = task.title;
    document.getElementById("viewTitleBlock").style.display = "flex";
    document.getElementById("editTitleBlock").style.display = "none";

    if (task.description && task.description.trim()) {
      document.getElementById("displayDesc").textContent = task.description;
    } else {
      document.getElementById("displayDesc").innerHTML = '<span class="empty-desc-hint">Нажмите "Редактировать", чтобы добавить описание...</span>';
    }
    document.getElementById("inputEditDesc").value = task.description || "";
    document.getElementById("viewDescBlock").style.display = "flex";
    document.getElementById("editDescBlock").style.display = "none";

    document.getElementById("detailStatus").value = task.status;
    document.getElementById("detailAssignee").value = task.assignee || "";
    document.getElementById("detailSp").value = task.story_points ?? "";
    document.getElementById("detailInSprint").value = task.in_sprint ? "1" : "0";

    const creatorUser = state.users.find(u => u.username.toLowerCase() === (task.created_by || "").toLowerCase());
    document.getElementById("detailCreatedBy").textContent = creatorUser ? `${creatorUser.display_name} (@${task.created_by})` : (task.created_by || "—");
    document.getElementById("detailCreatedAt").textContent = formatDate(task.created_at);

    const startedEl = document.getElementById("detailStartedAt");
    if (task.started_at) {
      startedEl.textContent = formatDate(task.started_at);
    } else {
      startedEl.innerHTML = '<span class="status-pill status-backlog" style="font-size: 10px;">Не начата</span>';
    }
    document.getElementById("detailUpdatedAt").textContent = formatDate(task.updated_at);

    const isAssignedToMe = task.assignee && state.currentUser && task.assignee.toLowerCase() === state.currentUser.username.toLowerCase();
    document.getElementById("btnDetailTakeTask").style.display = isAssignedToMe ? "none" : "inline-flex";

    updatePartialSplitBoxVisibility();
    renderComments(task.comments || []);

    document.getElementById("fullpageTaskDetail").style.display = "flex";
    window.history.pushState({ page: "task", id: taskId }, "", `/task/${taskId}`);
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
}

function closeTaskDetail() {
  document.getElementById("fullpageTaskDetail").style.display = "none";
  state.currentTaskDetail = null;
  window.history.pushState({}, "", "/");
  loadTasks();
}

function updatePartialSplitBoxVisibility() {
  const status = document.getElementById("detailStatus").value;
  const box = document.getElementById("partialSplitBox");
  box.style.display = status === "Реализовано частично" ? "flex" : "none";
}

async function saveTaskDetails() {
  if (!state.currentTaskDetail) return;

  const spVal = document.getElementById("detailSp").value;
  const story_points = spVal !== "" ? parseFloat(spVal) : null;
  const assignee = document.getElementById("detailAssignee").value || null;
  const status = document.getElementById("detailStatus").value;
  const in_sprint = document.getElementById("detailInSprint").value === "1";

  const indicator = document.getElementById("saveStatusIndicator");

  try {
    const updated = await api(`/api/tasks/${state.currentTaskDetail.id}`, {
      method: "PATCH",
      body: JSON.stringify({ story_points, assignee, status, in_sprint })
    });
    state.currentTaskDetail = { ...state.currentTaskDetail, ...updated };
    document.getElementById("detailStatusBadgeSlot").innerHTML = renderStatusBadge(updated.status);
    indicator.textContent = "Сохранено";
    setTimeout(() => { indicator.textContent = ""; }, 2000);
    updatePartialSplitBoxVisibility();
    await loadTasks();
  } catch (err) {
    showToast(`Ошибка сохранения: ${err.message}`);
  }
}

// ---------------- КОММЕНТАРИИ И УПОМИНАНИЯ ----------------
function renderComments(comments) {
  const container = document.getElementById("commentsList");
  container.innerHTML = "";

  if (!comments || comments.length === 0) {
    container.innerHTML = '<div style="color: var(--text-dim); padding: 12px 0;">Комментариев пока нет</div>';
    return;
  }

  comments.forEach(c => {
    const item = document.createElement("div");
    item.className = "comment-item";

    const userObj = state.users.find(u => u.username.toLowerCase() === c.author.toLowerCase());
    const authorName = userObj ? userObj.display_name : c.author;

    let formattedText = escapeHtml(c.text);
    if (c.mentions && c.mentions.length > 0) {
      c.mentions.forEach(m => {
        formattedText = formattedText.replace(new RegExp(`@${m}\\b`, "gi"), `<span class="mention-tag">@${escapeHtml(m)}</span>`);
      });
    }

    const isMyComment = state.currentUser && c.author.toLowerCase() === state.currentUser.username.toLowerCase();
    item.innerHTML = `
      <div class="comment-meta">
        <div>
          <span class="comment-author">${escapeHtml(authorName)} (@${escapeHtml(c.author)})</span>
          <span class="comment-time">${formatDate(c.created_at)}</span>
        </div>
        ${isMyComment ? `
          <div class="comment-actions">
            <button type="button" class="comment-action-btn danger" onclick="deleteComment(${c.id})">Удалить</button>
          </div>
        ` : ""}
      </div>
      <div class="comment-text">${formattedText}</div>
    `;
    container.appendChild(item);
  });
}

async function submitComment() {
  if (!state.currentTaskDetail) return;
  const input = document.getElementById("inputCommentText");
  const text = input.value.trim();
  if (!text) return;

  try {
    await api(`/api/tasks/${state.currentTaskDetail.id}/comments`, {
      method: "POST",
      body: JSON.stringify({ text })
    });
    input.value = "";
    const comments = await api(`/api/tasks/${state.currentTaskDetail.id}/comments`);
    state.currentTaskDetail.comments = comments;
    renderComments(comments);
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
}

window.deleteComment = async function (commentId) {
  if (!state.currentTaskDetail) return;
  if (!confirm("Удалить этот комментарий?")) return;

  try {
    await api(`/api/tasks/${state.currentTaskDetail.id}/comments/${commentId}`, { method: "DELETE" });
    const comments = await api(`/api/tasks/${state.currentTaskDetail.id}/comments`);
    state.currentTaskDetail.comments = comments;
    renderComments(comments);
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
};

function setupMentionAutocomplete() {
  const textarea = document.getElementById("inputCommentText");
  const popup = document.getElementById("mentionAutocomplete");
  if (!textarea || !popup) return;

  textarea.addEventListener("keyup", () => {
    const val = textarea.value;
    const cursorPos = textarea.selectionStart;
    const textBefore = val.slice(0, cursorPos);
    const atMatch = textBefore.match(/@([a-zA-Z0-9_\-]*)$/);

    if (atMatch) {
      const query = atMatch[1].toLowerCase();
      const filtered = state.users.filter(u =>
        u.username.toLowerCase().includes(query) ||
        u.display_name.toLowerCase().includes(query)
      );

      if (filtered.length > 0) {
        popup.innerHTML = "";
        filtered.forEach(u => {
          const div = document.createElement("div");
          div.className = "mention-user-item";
          div.textContent = `${u.display_name} (@${u.username})`;
          div.onmousedown = (ev) => {
            ev.preventDefault();
            insertMention(u.username, atMatch.index, cursorPos);
          };
          popup.appendChild(div);
        });
        popup.style.display = "block";
        return;
      }
    }
    popup.style.display = "none";
  });

  textarea.addEventListener("blur", () => {
    setTimeout(() => { popup.style.display = "none"; }, 200);
  });
}

function insertMention(username, atIndex, cursorPos) {
  const textarea = document.getElementById("inputCommentText");
  const val = textarea.value;
  const before = val.slice(0, atIndex);
  const after = val.slice(cursorPos);
  textarea.value = `${before}@${username} ${after}`;
  textarea.focus();
  const newPos = atIndex + username.length + 2;
  textarea.setSelectionRange(newPos, newPos);
  document.getElementById("mentionAutocomplete").style.display = "none";
}

// ---------------- СОЗДАНИЕ НОВОЙ ЗАДАЧИ ----------------
function openCreateTaskView() {
  document.getElementById("formCreateTask").reset();
  document.getElementById("fullpageCreateTask").style.display = "flex";
}

function closeCreateTaskView() {
  document.getElementById("fullpageCreateTask").style.display = "none";
}

async function handleCreateTaskSubmit(e) {
  e.preventDefault();
  const title = document.getElementById("createTitle").value.trim();
  const description = document.getElementById("createDescription").value.trim();
  const spVal = document.getElementById("createSp").value;
  const story_points = spVal !== "" ? parseFloat(spVal) : null;
  const assignee = document.getElementById("createAssignee").value || null;
  const in_sprint = document.getElementById("createSprint").value === "1";

  try {
    const task = await api("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ title, description, story_points, assignee, in_sprint, status: "Бэклог" })
    });
    closeCreateTaskView();
    showToast(`Создана задача ${task.key}`);
    await loadTasks();
    openTaskDetail(task.id);
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
}

// ---------------- ВЫНЕСЕНИЕ ЧАСТИ В БЭКЛОГ ----------------
function openSplitPartialModal() {
  if (!state.currentTaskDetail) return;
  document.getElementById("splitTitle").value = `[Остаток] ${state.currentTaskDetail.title}`;
  document.getElementById("splitDescription").value = `Нереализованная часть задачи ${state.currentTaskDetail.key}:\n${state.currentTaskDetail.description || ""}`;
  document.getElementById("splitSp").value = "";
  document.getElementById("splitAssignee").value = "";
  document.getElementById("fullpageSplitTask").style.display = "flex";
}

function closeSplitPartialModal() {
  document.getElementById("fullpageSplitTask").style.display = "none";
}

async function handleSplitTaskSubmit(e) {
  e.preventDefault();
  if (!state.currentTaskDetail) return;

  const title = document.getElementById("splitTitle").value.trim();
  const description = document.getElementById("splitDescription").value.trim();
  const spVal = document.getElementById("splitSp").value;
  const story_points = spVal !== "" ? parseFloat(spVal) : null;
  const assignee = document.getElementById("splitAssignee").value || null;

  try {
    const result = await api(`/api/tasks/${state.currentTaskDetail.id}/split-partial`, {
      method: "POST",
      body: JSON.stringify({ title, description, story_points, assignee })
    });
    closeSplitPartialModal();
    showToast(`Создана задача в бэклоге: ${result.backlog_task.key}`);
    await loadTasks();
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
}

// ---------------- АВТОРИЗАЦИЯ ----------------
let isLoginMode = true;

function showAuthModal() {
  document.getElementById("modalAuth").style.display = "flex";
  document.getElementById("authErrorMsg").style.display = "none";
}

function hideAuthModal() {
  document.getElementById("modalAuth").style.display = "none";
}

function setAuthMode(login) {
  isLoginMode = login;
  document.getElementById("authTabLogin").classList.toggle("active", login);
  document.getElementById("authTabRegister").classList.toggle("active", !login);
  document.getElementById("groupDisplayName").style.display = login ? "none" : "flex";
  document.getElementById("btnAuthSubmit").textContent = login ? "Войти" : "Зарегистрироваться";
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  const username = document.getElementById("authUsername").value.trim();
  const password = document.getElementById("authPassword").value;
  const displayName = document.getElementById("authDisplayName").value.trim();
  const errorMsg = document.getElementById("authErrorMsg");
  errorMsg.style.display = "none";

  try {
    const result = isLoginMode
      ? await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) })
      : await api("/api/auth/register", { method: "POST", body: JSON.stringify({ username, password, display_name: displayName || username }) });

    state.token = result.token;
    state.currentUser = result.user;
    localStorage.setItem("klukva_token", result.token);
    document.getElementById("formAuth").reset();
    await onAuthSuccess();
    showToast(`Добро пожаловать, ${result.user.display_name}!`);
  } catch (err) {
    errorMsg.textContent = err.message;
    errorMsg.style.display = "block";
  }
}

function handleLogout() {
  if (confirm("Выйти из учетной записи?")) {
    state.token = null;
    state.currentUser = null;
    localStorage.removeItem("klukva_token");
    location.reload();
  }
}

// ---------------- ОБРАБОТЧИКИ СОБЫТИЙ ----------------
function setupEventListeners() {
  // Навигация по вкладкам
  document.getElementById("tabBacklog").addEventListener("click", () => switchTab("backlog"));
  document.getElementById("tabSprints").addEventListener("click", () => switchTab("sprints"));
  document.getElementById("tabBoard").addEventListener("click", () => switchTab("board"));

  // Быстрые фильтры скрам-доски
  document.getElementById("boardFilterOnlyMy").addEventListener("click", () => {
    state.boardFilterOnlyMy = true;
    document.getElementById("boardFilterOnlyMy").classList.add("active");
    document.getElementById("boardFilterAll").classList.remove("active");
    renderScrumBoard();
  });

  document.getElementById("boardFilterAll").addEventListener("click", () => {
    state.boardFilterOnlyMy = false;
    document.getElementById("boardFilterAll").classList.add("active");
    document.getElementById("boardFilterOnlyMy").classList.remove("active");
    renderScrumBoard();
  });

  // Модальное окно создания спринта
  document.getElementById("btnCreateSprintInTab").addEventListener("click", openCreateSprintModal);
  document.getElementById("btnCloseSprintInTab").addEventListener("click", handleCloseSprint);
  document.getElementById("btnCancelSprintModal").addEventListener("click", closeCreateSprintModal);
  document.getElementById("btnCancelSprintModal2").addEventListener("click", closeCreateSprintModal);
  document.getElementById("formCreateSprint").addEventListener("submit", handleCreateSprintSubmit);

  // Фильтры списка задач
  document.getElementById("filterStatus").addEventListener("change", loadTasks);
  document.getElementById("filterSp").addEventListener("input", debounce(loadTasks, 300));
  document.getElementById("filterAssignee").addEventListener("change", loadTasks);
  document.getElementById("filterSearch").addEventListener("input", debounce(loadTasks, 300));
  document.getElementById("btnResetFilters").addEventListener("click", () => {
    document.getElementById("filterStatus").value = "";
    document.getElementById("filterSp").value = "";
    document.getElementById("filterAssignee").value = "";
    document.getElementById("filterSearch").value = "";
    loadTasks();
  });

  // Переключение мобильной панели фильтров
  const btnToggleFilters = document.getElementById("btnToggleFilters");
  const backlogToolbar = document.getElementById("backlogToolbar");
  if (btnToggleFilters && backlogToolbar) {
    btnToggleFilters.addEventListener("click", () => {
      backlogToolbar.classList.toggle("filters-open");
      const isOpen = backlogToolbar.classList.contains("filters-open");
      const textEl = document.getElementById("btnToggleFiltersText");
      if (textEl) {
        textEl.textContent = isOpen ? "Скрыть фильтры" : "Фильтры и поиск";
      }
    });
  }

  // Создание задачи
  document.getElementById("btnOpenCreateTask").addEventListener("click", openCreateTaskView);
  document.getElementById("btnBackFromCreate").addEventListener("click", closeCreateTaskView);
  document.getElementById("btnCancelCreate").addEventListener("click", closeCreateTaskView);
  document.getElementById("formCreateTask").addEventListener("submit", handleCreateTaskSubmit);

  // Детали задачи
  document.getElementById("btnBackFromDetail").addEventListener("click", closeTaskDetail);
  document.getElementById("btnSaveTask").addEventListener("click", saveTaskDetails);
  document.getElementById("detailStatus").addEventListener("change", () => {
    updatePartialSplitBoxVisibility();
    saveTaskDetails();
  });
  document.getElementById("detailAssignee").addEventListener("change", saveTaskDetails);
  document.getElementById("detailInSprint").addEventListener("change", saveTaskDetails);
  document.getElementById("btnDetailTakeTask").addEventListener("click", async () => {
    if (state.currentTaskDetail) await takeTask(state.currentTaskDetail.id);
  });

  // Инлайн-редактирование заголовка
  const startEditTitle = () => {
    document.getElementById("viewTitleBlock").style.display = "none";
    document.getElementById("editTitleBlock").style.display = "block";
    document.getElementById("inputEditTitle").focus();
  };
  document.getElementById("btnStartEditTitle").addEventListener("click", startEditTitle);
  document.getElementById("viewTitleBlock").addEventListener("click", (e) => {
    if (e.target.closest("#btnStartEditTitle")) return;
    startEditTitle();
  });
  document.getElementById("btnCancelInlineTitle").addEventListener("click", () => {
    document.getElementById("editTitleBlock").style.display = "none";
    document.getElementById("viewTitleBlock").style.display = "flex";
  });
  document.getElementById("btnSaveInlineTitle").addEventListener("click", async () => {
    const title = document.getElementById("inputEditTitle").value.trim();
    if (!title || !state.currentTaskDetail) return;
    await api(`/api/tasks/${state.currentTaskDetail.id}`, { method: "PATCH", body: JSON.stringify({ title }) });
    state.currentTaskDetail.title = title;
    document.getElementById("displayTitle").textContent = title;
    document.getElementById("editTitleBlock").style.display = "none";
    document.getElementById("viewTitleBlock").style.display = "flex";
    await loadTasks();
  });

  // Инлайн-редактирование описания
  const startEditDesc = () => {
    document.getElementById("viewDescBlock").style.display = "none";
    document.getElementById("editDescBlock").style.display = "block";
    document.getElementById("inputEditDesc").focus();
  };
  document.getElementById("btnStartEditDesc").addEventListener("click", startEditDesc);
  document.getElementById("viewDescBlock").addEventListener("click", (e) => {
    if (e.target.closest("#btnStartEditDesc")) return;
    startEditDesc();
  });
  document.getElementById("btnCancelInlineDesc").addEventListener("click", () => {
    document.getElementById("editDescBlock").style.display = "none";
    document.getElementById("viewDescBlock").style.display = "flex";
  });
  document.getElementById("btnSaveInlineDesc").addEventListener("click", async () => {
    const desc = document.getElementById("inputEditDesc").value.trim();
    if (!state.currentTaskDetail) return;
    await api(`/api/tasks/${state.currentTaskDetail.id}`, { method: "PATCH", body: JSON.stringify({ description: desc }) });
    state.currentTaskDetail.description = desc;
    document.getElementById("displayDesc").textContent = desc || "Описание не указано";
    document.getElementById("editDescBlock").style.display = "none";
    document.getElementById("viewDescBlock").style.display = "flex";
    await loadTasks();
  });

  // Частичная реализация
  document.getElementById("btnOpenSplitModal").addEventListener("click", openSplitPartialModal);
  document.getElementById("btnBackFromSplit").addEventListener("click", closeSplitPartialModal);
  document.getElementById("btnCancelSplit").addEventListener("click", closeSplitPartialModal);
  document.getElementById("formSplitTask").addEventListener("submit", handleSplitTaskSubmit);

  // Комментарии
  document.getElementById("btnSubmitComment").addEventListener("click", submitComment);
  setupMentionAutocomplete();

  // Авторизация
  document.getElementById("authTabLogin").addEventListener("click", () => setAuthMode(true));
  document.getElementById("authTabRegister").addEventListener("click", () => setAuthMode(false));
  document.getElementById("formAuth").addEventListener("submit", handleAuthSubmit);
  document.getElementById("btnLogout").addEventListener("click", handleLogout);

  // Переключение темы
  document.getElementById("btnThemeToggle").addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "light";
    applyTheme(current === "dark" ? "light" : "dark");
  });

  // Drag-and-Drop зоны спринта и бэклога
  setupSprintDropZones();

  // Закрытие окон по клавише Escape
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeTaskDetail();
      closeCreateTaskView();
      closeSplitPartialModal();
      closeCreateSprintModal();
    }
  });

  // Обработка истории браузера
  window.addEventListener("popstate", (e) => {
    if (e.state && e.state.page === "task" && e.state.id) {
      openTaskDetail(e.state.id);
    } else {
      document.getElementById("fullpageTaskDetail").style.display = "none";
      document.getElementById("fullpageCreateTask").style.display = "none";
      document.getElementById("fullpageSplitTask").style.display = "none";
    }
  });
}

function switchTab(tab) {
  state.currentTab = tab;
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });

  document.getElementById("viewBacklog").classList.toggle("active", tab === "backlog");
  document.getElementById("viewSprints").classList.toggle("active", tab === "sprints");
  document.getElementById("viewBoard").classList.toggle("active", tab === "board");

  loadTasks();
}

function debounce(func, wait) {
  let timeout;
  return function (...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}