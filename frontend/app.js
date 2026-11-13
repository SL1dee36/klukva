/**
 * KLUKVA — Client Application (Flat Minimalist Theme)
 * 1. Бэклог: отображаются исключительно задачи бэклога (вне спринта)
 * 2. Спринты: текущий активный спринт + задачи бэклога для перетаскивания в спринт
 * 3. Скрам-доска: группированные колонки, свимлейны по каждому сотруднику, как на скриншоте
 * 
 * Без теней (box-shadow) и без эмодзи.
 */

function getCookieValue(name) {
  try {
    const prefix = `${name}=`;
    const parts = document.cookie ? document.cookie.split(";") : [];
    for (const part of parts) {
      const trimmed = part.trim();
      if (trimmed.startsWith(prefix)) {
        return decodeURIComponent(trimmed.slice(prefix.length));
      }
    }
  } catch (e) {}
  return null;
}

function getStoredToken() {
  try {
    const ls = localStorage.getItem("klukva_token");
    if (ls) return ls;
  } catch (e) {}
  const ck = getCookieValue("klukva_token");
  if (ck) {
    try { localStorage.setItem("klukva_token", ck); } catch (e) {}
  }
  return ck;
}

function saveStoredToken(token) {
  if (!token) return;
  try { localStorage.setItem("klukva_token", token); } catch (e) {}
  try {
    document.cookie = `klukva_token=${encodeURIComponent(token)}; path=/; max-age=7776000; SameSite=Lax`;
  } catch (e) {}
}

function clearStoredToken() {
  try { localStorage.removeItem("klukva_token"); } catch (e) {}
  try {
    document.cookie = "klukva_token=; path=/; max-age=0; SameSite=Lax";
  } catch (e) {}
}

// Состояние приложения
const urlParams = new URLSearchParams(window.location.search);
const paramToken = urlParams.get("token");
if (paramToken) {
  saveStoredToken(paramToken);
}

const savedTab = localStorage.getItem("klukva_active_tab");
const initialTab = urlParams.get("tab") || savedTab || "backlog";

const state = {
  token: paramToken || getStoredToken() || null,
  currentUser: null,
  users: [],
  tasks: [],
  activeSprint: null,
  currentTab: initialTab, // 'backlog' | 'sprints' | 'board' | 'analytics'
  boardFilterOnlyMy: false,
  currentTaskDetail: null,
  pendingTotpChallenge: null,
  viewingProfileUsername: null,
};

// ---------------- СОХРАНЕНИЕ ПОЛОЖЕНИЯ И СОСТОЯНИЯ (TAB, SCROLL, FILTERS) ----------------
function saveStateAndPosition() {
  if (state.currentTab) {
    localStorage.setItem("klukva_active_tab", state.currentTab);
  }

  const scrolls = {
    windowX: window.scrollX || 0,
    windowY: window.scrollY || 0,
    appLayout: document.querySelector(".app-layout")?.scrollTop || 0,
    backlogTable: document.querySelector("#viewBacklog .table-scroll-wrapper")?.scrollTop || 0,
    boardWrapperX: document.querySelector(".scrum-board-wrapper")?.scrollLeft || 0,
    boardWrapperY: document.querySelector(".scrum-board-wrapper")?.scrollTop || 0,
    sprintLayout: document.querySelector("#viewSprints .sprint-layout-container")?.scrollTop || 0,
    sprintTable: document.querySelector("#sectionSprint .table-scroll-wrapper")?.scrollTop || 0,
    sprintBacklogTable: document.querySelector("#sectionBacklog .table-scroll-wrapper")?.scrollTop || 0,
  };
  try {
    sessionStorage.setItem("klukva_scroll_positions", JSON.stringify(scrolls));
  } catch (e) {}

  const filters = {
    status: document.getElementById("filterStatus")?.value || "",
    sp: document.getElementById("filterSp")?.value || "",
    assignee: document.getElementById("filterAssignee")?.value || "",
    taskType: document.getElementById("filterTaskType")?.value || "",
    cluster: document.getElementById("filterCluster")?.value || "",
    search: document.getElementById("filterSearch")?.value || "",
    onlyMy: state.boardFilterOnlyMy || false
  };
  try {
    sessionStorage.setItem("klukva_filters", JSON.stringify(filters));
  } catch (e) {}
}

const debouncedSavePosition = debounce(saveStateAndPosition, 150);

function restoreFilters() {
  try {
    const raw = sessionStorage.getItem("klukva_filters");
    if (!raw) return;
    const f = JSON.parse(raw);
    if (f.status && document.getElementById("filterStatus")) document.getElementById("filterStatus").value = f.status;
    if (f.sp && document.getElementById("filterSp")) document.getElementById("filterSp").value = f.sp;
    if (f.assignee && document.getElementById("filterAssignee")) document.getElementById("filterAssignee").value = f.assignee;
    if (f.taskType && document.getElementById("filterTaskType")) document.getElementById("filterTaskType").value = f.taskType;
    if (f.cluster && document.getElementById("filterCluster")) {
      const sel = document.getElementById("filterCluster");
      sel.dataset.pendingValue = f.cluster;
      sel.value = f.cluster;
    }
    if (f.search && document.getElementById("filterSearch")) document.getElementById("filterSearch").value = f.search;
    if (f.onlyMy) {
      state.boardFilterOnlyMy = true;
      document.getElementById("boardFilterOnlyMy")?.classList.add("active");
      document.getElementById("boardFilterAll")?.classList.remove("active");
    }
  } catch (e) {}
}

let restoreScrollTimer = null;
function restoreScrollPositions() {
  clearTimeout(restoreScrollTimer);
  restoreScrollTimer = setTimeout(() => {
    try {
      const raw = sessionStorage.getItem("klukva_scroll_positions");
      if (!raw) return;
      const s = JSON.parse(raw);
      if (s.windowX || s.windowY) {
        window.scrollTo(s.windowX || 0, s.windowY || 0);
      }
      const appLayout = document.querySelector(".app-layout");
      if (appLayout && s.appLayout) appLayout.scrollTop = s.appLayout;

      const backlogTable = document.querySelector("#viewBacklog .table-scroll-wrapper");
      if (backlogTable && s.backlogTable) backlogTable.scrollTop = s.backlogTable;

      const boardWrapper = document.querySelector(".scrum-board-wrapper");
      if (boardWrapper) {
        if (s.boardWrapperX) boardWrapper.scrollLeft = s.boardWrapperX;
        if (s.boardWrapperY) boardWrapper.scrollTop = s.boardWrapperY;
      }

      const sprintLayout = document.querySelector("#viewSprints .sprint-layout-container");
      if (sprintLayout && s.sprintLayout) sprintLayout.scrollTop = s.sprintLayout;

      const sprintTable = document.querySelector("#sectionSprint .table-scroll-wrapper");
      if (sprintTable && s.sprintTable) sprintTable.scrollTop = s.sprintTable;

      const sprintBacklogTable = document.querySelector("#sectionBacklog .table-scroll-wrapper");
      if (sprintBacklogTable && s.sprintBacklogTable) sprintBacklogTable.scrollTop = s.sprintBacklogTable;
    } catch (e) {}
  }, 30);
}

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
  let nextNum = 1;
  if (state.activeSprint) {
    const match = state.activeSprint.name.match(/\d+$/);
    if (match) nextNum = parseInt(match[0], 10) + 1;
  }
  input.value = `Спринт ${nextNum}`;
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
  if (!confirm(`Завершить спринт "${sprintName}"?\nВыполненные задачи останутся в истории спринта, а незавершенные переместятся в новый спринт.`)) {
    return;
  }

  try {
    const result = await api(`/api/sprints/${state.activeSprint.id}/close`, {
      method: "POST"
    });
    const newSprintName = result.new_sprint ? result.new_sprint.name : "";
    const movedMsg = newSprintName ? ` Перемещено в "${newSprintName}": ${result.moved_count || 0}.` : "";
    showToast(`Спринт "${sprintName}" завершен. Выполнено: ${result.completed_count || 0}.${movedMsg}`);
    await loadActiveSprint();
    await loadTasks();
  } catch (err) {
    showToast(`Ошибка закрытия спринта: ${err.message}`);
  }
}

// ---------------- ОБНОВЛЕНИЕ ИЗ РЕПОЗИТОРИЯ ----------------
async function handleAppUpdate() {
  const btn = document.getElementById("btnAppUpdate");
  const icon = document.getElementById("btnUpdateIcon");
  const text = document.getElementById("btnUpdateText");
  if (!btn) return;

  btn.disabled = true;
  if (icon) icon.classList.add("spinning");
  if (text) text.textContent = "Обновление...";

  try {
    const res = await api("/api/system/update", { method: "POST" });
    if (!res.ok) {
      showToast(`Ошибка обновления: ${res.error || "Неизвестная ошибка"}`);
    } else if (res.updated) {
      showToast("Программа успешно обновлена из репозитория! Перезагрузка страницы...");
      setTimeout(() => {
        window.location.reload();
      }, 1200);
      return;
    } else {
      showToast("Установлена актуальная версия. Изменений в репозитории нет.");
    }
  } catch (err) {
    showToast(`Ошибка запроса обновления: ${err.message}`);
  } finally {
    btn.disabled = false;
    if (icon) icon.classList.remove("spinning");
    if (text) text.textContent = "Обновить";
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
    clearStoredToken();
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

const TASK_TYPE_CLASSES = {
  "Задача": "",
  "Нововведение": "type-feature",
  "Ошибка": "type-bug",
  "Тестирование": "type-test",
  "Ревью": "type-review",
  "Исследование": "type-research",
  "Эпик": "type-epic",
  "Сириус": "type-sirius"
};

const CLUSTER_CLASSES = {
  "Эпик": "cluster-epic",
  "Сириус": "cluster-sirius"
};

function renderTypeBadge(taskType) {
  const t = taskType || "Задача";
  if (t === "Задача") return "";
  const cls = TASK_TYPE_CLASSES[t] || "";
  return `<span class="type-pill ${cls}">${escapeHtml(t)}</span>`;
}

function renderClusterBadge(cluster) {
  if (!cluster) return "";
  const cls = CLUSTER_CLASSES[cluster] || "";
  return `<span class="cluster-pill ${cls}">${escapeHtml(cluster)}</span>`;
}

function renderParentChip(task) {
  if (!task) return "";
  const chips = [];
  if (task.epic_id && task.epic_key) {
    const shortTitle = task.epic_title ? `: ${task.epic_title.slice(0, 22)}${task.epic_title.length > 22 ? "..." : ""}` : "";
    chips.push(`<span class="parent-chip" onclick="event.stopPropagation(); openTaskDetail(${task.epic_id})" title="Эпик: ${escapeHtml(task.epic_key)} ${escapeHtml(task.epic_title || "")}">${escapeHtml(task.epic_key)}${escapeHtml(shortTitle)}</span>`);
  }
  if (task.sirius_id && task.sirius_key) {
    const shortTitle = task.sirius_title ? `: ${task.sirius_title.slice(0, 22)}${task.sirius_title.length > 22 ? "..." : ""}` : "";
    chips.push(`<span class="parent-chip parent-chip-sirius" onclick="event.stopPropagation(); openTaskDetail(${task.sirius_id})" title="Сириус: ${escapeHtml(task.sirius_key)} ${escapeHtml(task.sirius_title || "")}">${escapeHtml(task.sirius_key)}${escapeHtml(shortTitle)}</span>`);
  }
  if (task.task_type === "Эпик" && Number(task.children_total || 0) > 0) {
    chips.push(`<span class="parent-chip" title="Задач в эпике">${task.children_done || 0}/${task.children_total} задач</span>`);
  }
  if (task.task_type === "Сириус" && (Number(task.epics_total || 0) > 0 || Number(task.children_total || 0) > 0)) {
    chips.push(`<span class="parent-chip parent-chip-sirius" title="Эпики и задачи в Сириусе">${task.epics_total || 0} эп. · ${task.children_done || 0}/${task.children_total || 0}</span>`);
  }
  if (!chips.length && task.cluster) {
    return renderClusterBadge(task.cluster);
  }
  return chips.join("");
}

function renderUserAvatarContent(userOrName, fallbackName = "U") {
  if (userOrName && typeof userOrName === "object") {
    if (userOrName.avatar_url) {
      return `<img src="${escapeHtml(userOrName.avatar_url)}" alt="">`;
    }
    const ch = (userOrName.display_name || userOrName.username || fallbackName).charAt(0).toUpperCase();
    return escapeHtml(ch);
  }
  return escapeHtml(String(userOrName || fallbackName).charAt(0).toUpperCase());
}

function hasMinRole(minRole) {
  if (state.currentUser?.is_system) return true;
  const levels = { viewer: 0, member: 1, manager: 2, admin: 3 };
  const cur = levels[state.currentUser?.role || "member"] ?? 1;
  return cur >= (levels[minRole] ?? 1);
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

  if (state.currentUser?.must_change_credentials) {
    await openProfileView(state.currentUser.username);
    return;
  }

  await loadUsers();
  restoreFilters();
  await loadActiveSprint();
  await loadNotifications();

  const targetTab = state.currentTab || "backlog";
  if (targetTab === "system" && !state.currentUser?.is_system) {
    switchTab("backlog");
  } else {
    switchTab(targetTab);
  }

  const path = window.location.pathname;
  const match = path.match(/\/task\/(\d+)/);
  if (match) {
    openTaskDetail(parseInt(match[1], 10));
  }
}

function updateUserHeader() {
  const profileDiv = document.getElementById("userProfile");
  const notifWrapper = document.getElementById("notifWrapper");
  const label = document.getElementById("userDisplayName");
  const avatar = document.getElementById("userAvatar");
  const roleBadge = document.getElementById("userRoleBadge");
  const btnCreateTask = document.getElementById("btnOpenCreateTask");
  const btnUpdate = document.getElementById("btnAppUpdate");
  const navSystem = document.getElementById("navTabSystem");

  if (state.currentUser) {
    profileDiv.style.display = "flex";
    if (notifWrapper) notifWrapper.style.display = state.currentUser.must_change_credentials ? "none" : "block";
    label.textContent = `${state.currentUser.display_name} (@${state.currentUser.username})`;
    avatar.innerHTML = renderUserAvatarContent(state.currentUser);
    if (roleBadge) {
      if (state.currentUser.is_system) {
        roleBadge.textContent = "system";
        roleBadge.className = "role-badge role-system";
      } else {
        const role = state.currentUser.role || "member";
        roleBadge.textContent = role;
        roleBadge.className = `role-badge role-${role}`;
      }
    }
    if (btnCreateTask) btnCreateTask.style.display = hasMinRole("member") ? "inline-flex" : "none";
    if (btnUpdate) btnUpdate.style.display = hasMinRole("admin") ? "inline-flex" : "none";
    if (navSystem) navSystem.style.display = state.currentUser.is_system ? "inline-flex" : "none";
  } else {
    profileDiv.style.display = "none";
    if (notifWrapper) notifWrapper.style.display = "none";
    if (navSystem) navSystem.style.display = "none";
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

async function loadHierarchyContainers() {
  try {
    const all = await api("/api/tasks");
    state.allTasksForHierarchy = all;
    state.epics = all.filter(t => t.task_type === "Эпик");
    state.siriuses = all.filter(t => t.task_type === "Сириус");
    populateHierarchySelects();
  } catch (err) {
    console.error("Ошибка загрузки иерархии:", err);
  }
}

function populateHierarchySelects() {
  const epics = state.epics || [];
  const siriuses = state.siriuses || [];

  const filterCluster = document.getElementById("filterCluster");
  if (filterCluster) {
    const desired = filterCluster.dataset.pendingValue || filterCluster.value || "";
    delete filterCluster.dataset.pendingValue;
    filterCluster.innerHTML = '<option value="">Все</option>';
    if (siriuses.length) {
      const grpS = document.createElement("optgroup");
      grpS.label = "Сириусы";
      siriuses.forEach(s => {
        const opt = document.createElement("option");
        opt.value = `sirius:${s.id}`;
        opt.textContent = `${s.key}: ${s.title}`;
        grpS.appendChild(opt);
      });
      filterCluster.appendChild(grpS);
    }
    if (epics.length) {
      const grpE = document.createElement("optgroup");
      grpE.label = "Эпики";
      epics.forEach(e => {
        const opt = document.createElement("option");
        opt.value = `epic:${e.id}`;
        opt.textContent = `${e.key}: ${e.title}`;
        grpE.appendChild(opt);
      });
      filterCluster.appendChild(grpE);
    }
    if (desired) filterCluster.value = desired;
  }

  ["createEpicId", "detailEpicId"].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = '<option value="">Без эпика</option>';
    epics.forEach(e => {
      const opt = document.createElement("option");
      opt.value = String(e.id);
      opt.textContent = `${e.key}: ${e.title}`;
      sel.appendChild(opt);
    });
    if (prev) sel.value = prev;
  });

  ["createSiriusId", "detailSiriusId"].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = '<option value="">Без Сириуса</option>';
    siriuses.forEach(s => {
      const opt = document.createElement("option");
      opt.value = String(s.id);
      opt.textContent = `${s.key}: ${s.title}`;
      sel.appendChild(opt);
    });
    if (prev) sel.value = prev;
  });
}

// ---------------- ЗАГРУЗКА ЗАДАЧ ----------------
async function loadTasks() {
  try {
    await loadHierarchyContainers();
    const status = document.getElementById("filterStatus").value;
    const spVal = document.getElementById("filterSp").value;
    const assignee = document.getElementById("filterAssignee").value;
    const taskType = document.getElementById("filterTaskType")?.value || "";
    const cluster = document.getElementById("filterCluster")?.value || "";
    const search = document.getElementById("filterSearch").value.trim();

    const params = new URLSearchParams();
    if (status) params.append("status", status);
    if (spVal) params.append("story_points", spVal);
    if (assignee) params.append("assignee", assignee);
    if (taskType) params.append("task_type", taskType);
    if (cluster.startsWith("epic:")) {
      params.append("epic_id", cluster.slice(5));
    } else if (cluster.startsWith("sirius:")) {
      params.append("sirius_id", cluster.slice(7));
    } else if (cluster) {
      params.append("cluster", cluster);
    }
    if (search) params.append("search", search);

    state.tasks = await api(`/api/tasks?${params.toString()}`);

    if (state.currentTab === "backlog") {
      renderPureBacklog();
    } else if (state.currentTab === "sprints") {
      renderSprintsView();
    } else if (state.currentTab === "board") {
      renderScrumBoard();
    } else if (state.currentTab === "analytics") {
      loadAnalytics();
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

  const statusFilter = document.getElementById("filterStatus")?.value;

  // В бэклоге отображаются только задачи бэклога:
  // 1. Задачи, не включенные в активный спринт (!t.in_sprint)
  // 2. Задачи, завершенные в рамках спринтов, остаются в истории спринта и НЕ попадают в бэклог
  // 3. Завершенные задачи по умолчанию скрыты в бэклоге (если фильтр статуса не выбран явно как "Завершено")
  const backlogTasks = state.tasks.filter(t => {
    if (t.in_sprint) return false;
    if (t.sprint_id && t.status === "Завершено") return false;
    if (!statusFilter && t.status === "Завершено") return false;
    return true;
  });

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
    tdTitle.innerHTML = `${renderTypeBadge(t.task_type)}${renderParentChip(t)}<span>${escapeHtml(t.title)}</span>${renderLinkIndicators(t)}`;
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
  const typeVal = document.getElementById("filterTaskType")?.value;
  const clusterVal = document.getElementById("filterCluster")?.value;
  const searchVal = document.getElementById("filterSearch")?.value?.trim();
  const filterDot = document.getElementById("filterActiveDot");
  if (filterDot) {
    filterDot.style.display = (statusVal || spVal || assigneeVal || typeVal || clusterVal || searchVal) ? "inline" : "none";
  }

  restoreScrollPositions();
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
  // В секцию бэклога спринтов (для добавления в спринт) попадают только незавершенные задачи вне спринта
  const backlogTasks = state.tasks.filter(t => !t.in_sprint && t.status !== "Завершено" && !t.sprint_id);

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
  restoreScrollPositions();
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
  tdTitle.innerHTML = `${renderTypeBadge(task.task_type)}${renderParentChip(task)}<span>${escapeHtml(task.title)}</span>${renderLinkIndicators(task)}`;
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

  restoreScrollPositions();
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

  const uObj = task.assignee
    ? state.users.find(u => u.username.toLowerCase() === task.assignee.toLowerCase())
    : null;
  const avatarHtml = task.assignee
    ? `<span class="scrum-card-avatar" title="${escapeHtml(task.assignee)}">${renderUserAvatarContent(uObj || task.assignee)}</span>`
    : "";

  card.innerHTML = `
    <div class="scrum-card-top">
      <span class="task-key-link" onclick="openTaskDetail(${task.id})">${task.key}</span>
      ${task.story_points ? `<span class="sp-badge">${task.story_points} SP</span>` : ""}
    </div>
    <div class="scrum-card-title" onclick="openTaskDetail(${task.id})">${renderTypeBadge(task.task_type)}${renderParentChip(task)}${escapeHtml(task.title)}${renderLinkIndicators(task)}</div>
    <div class="scrum-card-bottom">
      <div>${renderStatusBadge(task.status)}</div>
      ${avatarHtml}
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
    if (!state.allTasksForHierarchy) await loadHierarchyContainers();
    const task = await api(`/api/tasks/${taskId}`);
    state.currentTaskDetail = task;

    document.getElementById("detailTaskKey").textContent = task.key;
    const typeSlot = document.getElementById("detailTypeBadgeSlot");
    const clusterSlot = document.getElementById("detailClusterBadgeSlot");
    if (typeSlot) typeSlot.innerHTML = renderTypeBadge(task.task_type);
    if (clusterSlot) clusterSlot.innerHTML = renderParentChip(task);
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
    if (document.getElementById("detailTaskType")) document.getElementById("detailTaskType").value = task.task_type || "Задача";
    populateHierarchySelects();
    if (document.getElementById("detailEpicId")) document.getElementById("detailEpicId").value = task.epic_id ? String(task.epic_id) : "";
    if (document.getElementById("detailSiriusId")) document.getElementById("detailSiriusId").value = task.sirius_id ? String(task.sirius_id) : "";
    syncDetailHierarchyFields(task.task_type || "Задача");
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
    renderHierarchyChildren(task);
    renderComments(task.comments || []);
    resetLinkForm();
    loadLinks(taskId);
    loadAttachments(taskId);

    document.getElementById("fullpageTaskDetail").style.display = "flex";
    window.history.pushState({ page: "task", id: taskId }, "", `/task/${taskId}`);
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
}

function syncDetailHierarchyFields(taskType) {
  const epicField = document.getElementById("detailEpicField");
  const siriusField = document.getElementById("detailSiriusField");
  if (!epicField || !siriusField) return;
  if (taskType === "Сириус") {
    epicField.style.display = "none";
    siriusField.style.display = "none";
  } else if (taskType === "Эпик") {
    epicField.style.display = "none";
    siriusField.style.display = "block";
  } else {
    epicField.style.display = "block";
    siriusField.style.display = "none";
  }
}

function renderHierarchyChildren(task) {
  const sec = document.getElementById("hierarchyChildrenSection");
  const titleEl = document.getElementById("hierarchyChildrenTitle");
  const sumEl = document.getElementById("hierarchyChildrenSummary");
  const barEl = document.getElementById("hierarchyProgressBar");
  const listEl = document.getElementById("hierarchyChildrenList");
  const attachForm = document.getElementById("hierarchyAttachForm");
  if (!sec || !listEl) return;
  if (attachForm) attachForm.style.display = "none";

  const tType = task.task_type || "Задача";
  if (tType !== "Эпик" && tType !== "Сириус") {
    sec.style.display = "none";
    return;
  }

  sec.style.display = "block";
  listEl.innerHTML = "";

  if (tType === "Эпик") {
    const items = task.epic_tasks || [];
    const total = items.length;
    const done = items.filter(c => c.status === "Завершено").length;
    const pct = total ? Math.round((done / total) * 100) : 0;
    const totalSp = items.reduce((acc, c) => acc + Number(c.story_points || 0), 0);
    titleEl.textContent = "Задачи в Эпике";
    sumEl.textContent = `${done}/${total} завершено (${pct}%) · ${totalSp} SP`;
    if (barEl) barEl.style.width = `${pct}%`;
    if (!items.length) {
      listEl.innerHTML = '<div class="links-empty">В этом Эпике пока нет задач</div>';
      return;
    }
    items.forEach(c => {
      const row = document.createElement("div");
      row.className = "hierarchy-child-row";
      row.innerHTML = `
        <div class="hierarchy-child-left">
          <span class="task-key-link">${escapeHtml(c.key)}</span>
          ${renderTypeBadge(c.task_type)}
          <span class="hierarchy-child-title">${escapeHtml(c.title)}</span>
        </div>
        <div class="hierarchy-child-right">
          ${c.story_points !== null && c.story_points !== undefined ? `<span class="sp-badge">${c.story_points} SP</span>` : ""}
          ${renderStatusBadge(c.status)}
          <button type="button" class="btn-icon btn-detach-child" title="Убрать из Эпика">&times;</button>
        </div>
      `;
      row.querySelector(".task-key-link").onclick = () => openTaskDetail(c.id);
      row.querySelector(".hierarchy-child-title").onclick = () => openTaskDetail(c.id);
      row.querySelector(".btn-detach-child").onclick = () => detachChildFromContainer(c.id, "epic");
      listEl.appendChild(row);
    });
  } else {
    const epics = task.sirius_epics || [];
    const nestedTotal = Number(task.children_total || 0);
    const nestedDone = Number(task.children_done || 0);
    const pct = nestedTotal ? Math.round((nestedDone / nestedTotal) * 100) : 0;
    titleEl.textContent = "Эпики в Сириусе";
    sumEl.textContent = `${epics.length} эп. · ${nestedDone}/${nestedTotal} задач (${pct}%)`;
    if (barEl) barEl.style.width = `${pct}%`;
    if (!epics.length) {
      listEl.innerHTML = '<div class="links-empty">В этом Сириусе пока нет Эпиков</div>';
      return;
    }
    epics.forEach(ep => {
      const row = document.createElement("div");
      row.className = "hierarchy-child-row";
      row.innerHTML = `
        <div class="hierarchy-child-left">
          <span class="task-key-link">${escapeHtml(ep.key)}</span>
          ${renderTypeBadge(ep.task_type)}
          <span class="hierarchy-child-title">${escapeHtml(ep.title)}</span>
        </div>
        <div class="hierarchy-child-right">
          <span class="parent-chip">${ep.children_done || 0}/${ep.children_total || 0} задач</span>
          ${renderStatusBadge(ep.status)}
          <button type="button" class="btn-icon btn-detach-child" title="Убрать из Сириуса">&times;</button>
        </div>
      `;
      row.querySelector(".task-key-link").onclick = () => openTaskDetail(ep.id);
      row.querySelector(".hierarchy-child-title").onclick = () => openTaskDetail(ep.id);
      row.querySelector(".btn-detach-child").onclick = () => detachChildFromContainer(ep.id, "sirius");
      listEl.appendChild(row);
    });
  }
}

async function detachChildFromContainer(childId, kind) {
  if (!state.currentTaskDetail) return;
  try {
    const body = kind === "epic" ? { epic_id: null } : { sirius_id: null };
    await api(`/api/tasks/${childId}`, { method: "PATCH", body: JSON.stringify(body) });
    await loadTasks();
    await openTaskDetail(state.currentTaskDetail.id);
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
}

function openHierarchyAttachForm() {
  if (!state.currentTaskDetail) return;
  const form = document.getElementById("hierarchyAttachForm");
  const sel = document.getElementById("hierarchyAttachSelect");
  if (!form || !sel) return;
  const parent = state.currentTaskDetail;
  const all = state.allTasksForHierarchy || [];
  let candidates = [];
  if (parent.task_type === "Эпик") {
    candidates = all.filter(t => t.task_type !== "Эпик" && t.task_type !== "Сириус" && t.epic_id !== parent.id);
  } else if (parent.task_type === "Сириус") {
    candidates = all.filter(t => t.task_type === "Эпик" && t.sirius_id !== parent.id);
  }
  sel.innerHTML = candidates.length
    ? candidates.map(c => `<option value="${c.id}">${escapeHtml(c.key)} — ${escapeHtml(c.title)}</option>`).join("")
    : '<option value="">Нет доступных объектов</option>';
  form.style.display = "flex";
}

async function confirmHierarchyAttach() {
  if (!state.currentTaskDetail) return;
  const childId = parseInt(document.getElementById("hierarchyAttachSelect")?.value || "", 10);
  if (!childId) {
    showToast("Выберите объект");
    return;
  }
  const parent = state.currentTaskDetail;
  const body = parent.task_type === "Эпик" ? { epic_id: parent.id } : { sirius_id: parent.id };
  try {
    await api(`/api/tasks/${childId}`, { method: "PATCH", body: JSON.stringify(body) });
    document.getElementById("hierarchyAttachForm").style.display = "none";
    await loadTasks();
    await openTaskDetail(parent.id);
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
}

// ---------------- СВЯЗИ ЗАДАЧ ----------------
function renderLinkIndicators(task) {
  let html = "";
  if (task.is_blocked) html += '<span class="blocked-indicator" title="Есть незавершённый блокер">Заблокирована</span>';
  if (task.links_count) html += `<span class="link-indicator" title="Связей: ${task.links_count}">&#128279; ${task.links_count}</span>`;
  return html;
}

const LINK_GROUP_ORDER = ["Заблокирована", "Блокирует", "Родитель для", "Подзадача", "Связана с"];

async function loadLinks(taskId) {
  const container = document.getElementById("linksList");
  try {
    const links = await api(`/api/tasks/${taskId}/links`);
    if (!state.currentTaskDetail || state.currentTaskDetail.id !== taskId) return;
    state.currentTaskDetail.links = links;
    if (!links.length) {
      container.innerHTML = '<div class="links-empty">Связей нет</div>';
      return;
    }
    container.innerHTML = "";
    LINK_GROUP_ORDER.forEach(label => {
      const group = links.filter(l => l.label === label);
      if (!group.length) return;
      const lbl = document.createElement("div");
      lbl.className = "link-group-label";
      lbl.textContent = label;
      container.appendChild(lbl);
      group.forEach(l => {
        const row = document.createElement("div");
        row.className = "link-row";
        const o = l.other_task;
        row.innerHTML = `
          <span class="task-key-link">${escapeHtml(o.key)}</span>
          <span class="link-title">${escapeHtml(o.title)}</span>
          ${renderStatusBadge(o.status)}
          <button type="button" class="link-remove" title="Удалить связь">&#10005;</button>`;
        row.querySelector(".task-key-link").onclick = () => openTaskDetail(o.id);
        row.querySelector(".link-title").onclick = () => openTaskDetail(o.id);
        row.querySelector(".link-remove").onclick = () => removeLink(l.id);
        container.appendChild(row);
      });
    });
  } catch (err) {
    container.innerHTML = `<div class="links-empty">Ошибка: ${escapeHtml(err.message)}</div>`;
  }
}

function resetLinkForm() {
  document.getElementById("linkAddForm").style.display = "none";
  document.getElementById("linkSearchInput").value = "";
  document.getElementById("linkSearchResults").innerHTML = "";
}

async function searchLinkTargets() {
  const q = document.getElementById("linkSearchInput").value.trim();
  const box = document.getElementById("linkSearchResults");
  if (!q || !state.currentTaskDetail) { box.innerHTML = ""; return; }
  try {
    const tasks = await api(`/api/tasks?search=${encodeURIComponent(q)}`);
    const curId = state.currentTaskDetail.id;
    box.innerHTML = "";
    tasks.filter(t => t.id !== curId).slice(0, 15).forEach(t => {
      const item = document.createElement("div");
      item.className = "link-search-item";
      item.innerHTML = `<b>${escapeHtml(t.key)}</b> ${escapeHtml(t.title)}`;
      item.onclick = () => addLink(t.id);
      box.appendChild(item);
    });
    if (!box.children.length) box.innerHTML = '<div class="link-search-item links-empty">Ничего не найдено</div>';
  } catch (err) {
    box.innerHTML = "";
  }
}

async function addLink(targetId) {
  const taskId = state.currentTaskDetail.id;
  const [type, direction] = document.getElementById("linkTypeSelect").value.split(":");
  try {
    await api(`/api/tasks/${taskId}/links`, {
      method: "POST",
      body: JSON.stringify({ type, target_id: targetId, direction })
    });
    showToast("Связь добавлена");
    resetLinkForm();
    await refreshAfterLinkChange(taskId);
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
}

async function removeLink(linkId) {
  const taskId = state.currentTaskDetail.id;
  if (!confirm("Удалить связь?")) return;
  try {
    await api(`/api/tasks/${taskId}/links/${linkId}`, { method: "DELETE" });
    showToast("Связь удалена");
    await refreshAfterLinkChange(taskId);
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
}

async function refreshAfterLinkChange(taskId) {
  await loadLinks(taskId);
  const comments = await api(`/api/tasks/${taskId}/comments`);
  state.currentTaskDetail.comments = comments;
  renderComments(comments);
  loadTasks();
}

// ---------------- ВЛОЖЕНИЯ (ФАЙЛЫ) ----------------
const MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024;

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

function attachmentUrl(taskId, att, download = false) {
  const q = new URLSearchParams({ token: state.token || "" });
  if (download) q.set("download", "true");
  return `/api/tasks/${taskId}/attachments/${att.id}/file?${q}`;
}

function attachmentKind(att) {
  const ct = att.content_type || "";
  if (ct.startsWith("image/")) return "image";
  if (ct.startsWith("video/")) return "video";
  if (ct.startsWith("audio/")) return "audio";
  if (ct === "application/pdf") return "pdf";
  return "other";
}

async function loadAttachments(taskId) {
  const container = document.getElementById("attachmentsList");
  closeAttachmentPreview();
  try {
    const atts = await api(`/api/tasks/${taskId}/attachments`);
    if (!state.currentTaskDetail || state.currentTaskDetail.id !== taskId) return;
    if (!atts.length) {
      container.innerHTML = '<div class="links-empty">Файлов нет</div>';
      return;
    }
    container.innerHTML = "";
    atts.forEach(att => {
      const kind = attachmentKind(att);
      const item = document.createElement("div");
      item.className = "attachment-item";
      const thumb = kind === "image"
        ? `<img src="${attachmentUrl(taskId, att)}" alt="" loading="lazy">`
        : `<span class="attachment-icon">${{ video: "&#9654;", audio: "&#9835;", pdf: "PDF" }[kind] || "&#128196;"}</span>`;
      item.innerHTML = `
        <div class="attachment-thumb" title="Просмотр">${thumb}</div>
        <div class="attachment-info">
          <div class="attachment-name" title="${escapeHtml(att.filename)}">${escapeHtml(att.filename)}</div>
          <div class="attachment-meta">${formatFileSize(att.size)} · @${escapeHtml(att.uploaded_by)} · ${formatDate(att.created_at)}</div>
        </div>
        <div class="attachment-actions">
          <a class="attachment-btn" href="${attachmentUrl(taskId, att, true)}" download title="Скачать">&#11015;</a>
          <button type="button" class="attachment-btn attachment-del" title="Удалить">&#10005;</button>
        </div>`;
      const open = () => openAttachmentPreview(taskId, att);
      item.querySelector(".attachment-thumb").onclick = open;
      item.querySelector(".attachment-name").onclick = open;
      item.querySelector(".attachment-del").onclick = () => removeAttachment(taskId, att);
      container.appendChild(item);
    });
  } catch (err) {
    container.innerHTML = `<div class="links-empty">Ошибка: ${escapeHtml(err.message)}</div>`;
  }
}

function openAttachmentPreview(taskId, att) {
  const box = document.getElementById("attachmentPreview");
  const kind = attachmentKind(att);
  const url = attachmentUrl(taskId, att);
  let body;
  if (kind === "image") body = `<img src="${url}" alt="">`;
  else if (kind === "video") body = `<video src="${url}" controls autoplay></video>`;
  else if (kind === "audio") body = `<audio src="${url}" controls autoplay></audio>`;
  else if (kind === "pdf" || (att.content_type || "").startsWith("text/")) body = `<iframe src="${url}"></iframe>`;
  else body = `<div class="links-empty">Предпросмотр недоступен. <a href="${attachmentUrl(taskId, att, true)}" download>Скачать файл</a></div>`;
  box.innerHTML = `
    <div class="attachment-preview-header">
      <span>${escapeHtml(att.filename)}</span>
      <span>
        <a class="attachment-btn" href="${attachmentUrl(taskId, att, true)}" download title="Скачать">&#11015;</a>
        <button type="button" class="attachment-btn" id="btnClosePreview" title="Закрыть">&#10005;</button>
      </span>
    </div>
    <div class="attachment-preview-body">${body}</div>`;
  box.style.display = "block";
  box.querySelector("#btnClosePreview").onclick = closeAttachmentPreview;
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function closeAttachmentPreview() {
  const box = document.getElementById("attachmentPreview");
  if (!box) return;
  box.innerHTML = "";
  box.style.display = "none";
}

async function uploadAttachments(files) {
  if (!state.currentTaskDetail || !files.length) return;
  const taskId = state.currentTaskDetail.id;
  let uploaded = 0;
  for (const file of files) {
    if (file.size > MAX_ATTACHMENT_SIZE) {
      showToast(`«${file.name}» отклонён: больше 20 МБ`);
      continue;
    }
    if (file.size === 0) {
      showToast(`«${file.name}» отклонён: пустой файл`);
      continue;
    }
    try {
      showToast(`Загрузка «${file.name}»...`);
      await api(`/api/tasks/${taskId}/attachments?filename=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file
      });
      uploaded++;
    } catch (err) {
      showToast(`Ошибка загрузки «${file.name}»: ${err.message}`);
    }
  }
  if (uploaded) {
    showToast(uploaded === 1 ? "Файл загружен" : `Загружено файлов: ${uploaded}`);
    await refreshAfterAttachmentChange(taskId);
  }
}

async function removeAttachment(taskId, att) {
  if (!confirm(`Удалить файл «${att.filename}»?`)) return;
  try {
    await api(`/api/tasks/${taskId}/attachments/${att.id}`, { method: "DELETE" });
    showToast("Файл удалён");
    await refreshAfterAttachmentChange(taskId);
  } catch (err) {
    showToast(`Ошибка: ${err.message}`);
  }
}

async function refreshAfterAttachmentChange(taskId) {
  await loadAttachments(taskId);
  const comments = await api(`/api/tasks/${taskId}/comments`);
  if (state.currentTaskDetail && state.currentTaskDetail.id === taskId) {
    state.currentTaskDetail.comments = comments;
    renderComments(comments);
  }
}

function setupAttachmentListeners() {
  const input = document.getElementById("attachmentInput");
  document.getElementById("btnAddAttachment").addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const files = Array.from(input.files);
    input.value = "";
    await uploadAttachments(files);
  });
  const section = document.getElementById("attachmentsSection");
  ["dragenter", "dragover"].forEach(ev => section.addEventListener(ev, e => {
    if (!e.dataTransfer || !Array.from(e.dataTransfer.types).includes("Files")) return;
    e.preventDefault();
    section.classList.add("drag-over");
  }));
  ["dragleave", "drop"].forEach(ev => section.addEventListener(ev, e => {
    if (ev === "dragleave" && section.contains(e.relatedTarget)) return;
    section.classList.remove("drag-over");
  }));
  section.addEventListener("drop", e => {
    if (!e.dataTransfer || !e.dataTransfer.files.length) return;
    e.preventDefault();
    uploadAttachments(Array.from(e.dataTransfer.files));
  });
}

function setupLinkListeners() {
  document.getElementById("btnAddLink").addEventListener("click", () => {
    const form = document.getElementById("linkAddForm");
    form.style.display = form.style.display === "none" ? "flex" : "none";
    if (form.style.display === "flex") document.getElementById("linkSearchInput").focus();
  });
  document.getElementById("btnCancelLink").addEventListener("click", resetLinkForm);
  document.getElementById("linkSearchInput").addEventListener("input", debounce(searchLinkTargets, 250));
}

function closeTaskDetail() {
  document.getElementById("fullpageTaskDetail").style.display = "none";
  state.currentTaskDetail = null;
  const currentUrl = new URL(window.location.origin + "/");
  if (state.currentTab) {
    currentUrl.searchParams.set("tab", state.currentTab);
  }
  window.history.pushState({ tab: state.currentTab }, "", currentUrl.toString());
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
  const task_type = document.getElementById("detailTaskType")?.value || "Задача";
  syncDetailHierarchyFields(task_type);
  const epicRaw = document.getElementById("detailEpicId")?.value || "";
  const siriusRaw = document.getElementById("detailSiriusId")?.value || "";
  const epic_id = (task_type !== "Эпик" && task_type !== "Сириус" && epicRaw) ? parseInt(epicRaw, 10) : null;
  const sirius_id = (task_type === "Эпик" && siriusRaw) ? parseInt(siriusRaw, 10) : null;

  const indicator = document.getElementById("saveStatusIndicator");

  try {
    const updated = await api(`/api/tasks/${state.currentTaskDetail.id}`, {
      method: "PATCH",
      body: JSON.stringify({ story_points, assignee, status, in_sprint, task_type, epic_id, sirius_id })
    });
    const refreshed = await api(`/api/tasks/${updated.id}`);
    state.currentTaskDetail = refreshed;
    document.getElementById("detailStatusBadgeSlot").innerHTML = renderStatusBadge(refreshed.status);
    const typeSlot = document.getElementById("detailTypeBadgeSlot");
    const clusterSlot = document.getElementById("detailClusterBadgeSlot");
    if (typeSlot) typeSlot.innerHTML = renderTypeBadge(refreshed.task_type);
    if (clusterSlot) clusterSlot.innerHTML = renderParentChip(refreshed);
    renderHierarchyChildren(refreshed);
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
function syncCreateHierarchyFields() {
  const t = document.getElementById("createTaskType")?.value || "Задача";
  const epicGroup = document.getElementById("createEpicGroup");
  const siriusGroup = document.getElementById("createSiriusGroup");
  if (!epicGroup || !siriusGroup) return;
  if (t === "Сириус") {
    epicGroup.style.display = "none";
    siriusGroup.style.display = "none";
  } else if (t === "Эпик") {
    epicGroup.style.display = "none";
    siriusGroup.style.display = "block";
  } else {
    epicGroup.style.display = "block";
    siriusGroup.style.display = "none";
  }
}

async function openCreateTaskView(prefill = null) {
  const opts = (prefill && !(prefill instanceof Event)) ? prefill : {};
  document.getElementById("formCreateTask").reset();
  if (!state.allTasksForHierarchy) await loadHierarchyContainers();
  populateHierarchySelects();
  if (opts.task_type && document.getElementById("createTaskType")) {
    document.getElementById("createTaskType").value = opts.task_type;
  }
  if (opts.epic_id && document.getElementById("createEpicId")) {
    document.getElementById("createEpicId").value = String(opts.epic_id);
  }
  if (opts.sirius_id && document.getElementById("createSiriusId")) {
    document.getElementById("createSiriusId").value = String(opts.sirius_id);
  }
  syncCreateHierarchyFields();
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
  const task_type = document.getElementById("createTaskType")?.value || "Задача";
  const epicRaw = document.getElementById("createEpicId")?.value || "";
  const siriusRaw = document.getElementById("createSiriusId")?.value || "";
  const epic_id = (task_type !== "Эпик" && task_type !== "Сириус" && epicRaw) ? parseInt(epicRaw, 10) : null;
  const sirius_id = (task_type === "Эпик" && siriusRaw) ? parseInt(siriusRaw, 10) : null;

  try {
    const task = await api("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ title, description, story_points, assignee, in_sprint, task_type, epic_id, sirius_id, status: "Бэклог" })
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
  document.getElementById("formAuth").style.display = "block";
  const totpForm = document.getElementById("formAuthTotp");
  if (totpForm) totpForm.style.display = "none";
  state.pendingTotpChallenge = null;
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
  const trustDevice = Boolean(document.getElementById("authTrustDevice")?.checked);
  const errorMsg = document.getElementById("authErrorMsg");
  errorMsg.style.display = "none";

  try {
    const result = isLoginMode
      ? await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password, trust_device: trustDevice }) })
      : await api("/api/auth/register", { method: "POST", body: JSON.stringify({ username, password, display_name: displayName || username, trust_device: trustDevice }) });

    if (result.requires_totp) {
      state.pendingTotpChallenge = result.challenge_token;
      document.getElementById("formAuth").style.display = "none";
      const totpForm = document.getElementById("formAuthTotp");
      totpForm.style.display = "block";
      document.getElementById("authTotpErrorMsg").style.display = "none";
      document.getElementById("authTotpCode").value = "";
      document.getElementById("authTotpCode").focus();
      return;
    }

    state.token = result.token;
    state.currentUser = result.user;
    saveStoredToken(result.token);
    document.getElementById("formAuth").reset();
    await onAuthSuccess();
    showToast(`Добро пожаловать, ${result.user.display_name}!`);
  } catch (err) {
    errorMsg.textContent = err.message;
    errorMsg.style.display = "block";
  }
}

async function handleTotpLoginSubmit(e) {
  e.preventDefault();
  const code = document.getElementById("authTotpCode").value.trim();
  const trustDevice = Boolean(document.getElementById("authTrustDevice")?.checked);
  const errEl = document.getElementById("authTotpErrorMsg");
  errEl.style.display = "none";
  try {
    const result = await api("/api/auth/login/totp", {
      method: "POST",
      body: JSON.stringify({
        challenge_token: state.pendingTotpChallenge,
        code,
        trust_device: trustDevice
      })
    });
    state.token = result.token;
    state.currentUser = result.user;
    saveStoredToken(result.token);
    state.pendingTotpChallenge = null;
    document.getElementById("formAuth").reset();
    document.getElementById("formAuthTotp").reset();
    await onAuthSuccess();
    showToast(`Добро пожаловать, ${result.user.display_name}!`);
  } catch (err) {
    errEl.textContent = err.message;
    errEl.style.display = "block";
  }
}

async function handleLogout() {
  if (confirm("Выйти из учетной записи?")) {
    try {
      await api("/api/auth/logout?revoke_device=true", { method: "POST" });
    } catch (e) {}
    state.token = null;
    state.currentUser = null;
    clearStoredToken();
    location.reload();
  }
}

// ---------------- ОБРАБОТЧИКИ СОБЫТИЙ ----------------
function setupEventListeners() {
  setupLinkListeners();
  setupAttachmentListeners();
  // Навигация по вкладкам
  document.getElementById("tabBacklog").addEventListener("click", () => switchTab("backlog"));
  document.getElementById("tabSprints").addEventListener("click", () => switchTab("sprints"));
  document.getElementById("tabBoard").addEventListener("click", () => switchTab("board"));
  document.getElementById("tabAnalytics")?.addEventListener("click", () => switchTab("analytics"));
  document.getElementById("navTabSystem")?.addEventListener("click", () => switchTab("system"));
  document.getElementById("btnRefreshAnalytics")?.addEventListener("click", loadAnalytics);

  setupNotificationListeners();
  setupProfileListeners();
  setupSystemListeners();

  // Быстрые фильтры скрам-доски
  document.getElementById("boardFilterOnlyMy").addEventListener("click", () => {
    state.boardFilterOnlyMy = true;
    document.getElementById("boardFilterOnlyMy").classList.add("active");
    document.getElementById("boardFilterAll").classList.remove("active");
    debouncedSavePosition();
    renderScrumBoard();
  });

  document.getElementById("boardFilterAll").addEventListener("click", () => {
    state.boardFilterOnlyMy = false;
    document.getElementById("boardFilterAll").classList.add("active");
    document.getElementById("boardFilterOnlyMy").classList.remove("active");
    debouncedSavePosition();
    renderScrumBoard();
  });

  // Модальное окно создания спринта
  document.getElementById("btnCreateSprintInTab").addEventListener("click", openCreateSprintModal);
  document.getElementById("btnCloseSprintInTab").addEventListener("click", handleCloseSprint);
  document.getElementById("btnCancelSprintModal").addEventListener("click", closeCreateSprintModal);
  document.getElementById("btnCancelSprintModal2").addEventListener("click", closeCreateSprintModal);
  document.getElementById("formCreateSprint").addEventListener("submit", handleCreateSprintSubmit);

  // Фильтры списка задач
  document.getElementById("filterStatus").addEventListener("change", () => { debouncedSavePosition(); loadTasks(); });
  document.getElementById("filterSp").addEventListener("input", debounce(() => { debouncedSavePosition(); loadTasks(); }, 300));
  document.getElementById("filterAssignee").addEventListener("change", () => { debouncedSavePosition(); loadTasks(); });
  document.getElementById("filterTaskType")?.addEventListener("change", () => { debouncedSavePosition(); loadTasks(); });
  document.getElementById("filterCluster")?.addEventListener("change", () => { debouncedSavePosition(); loadTasks(); });
  document.getElementById("filterSearch").addEventListener("input", debounce(() => { debouncedSavePosition(); loadTasks(); }, 300));
  document.getElementById("btnResetFilters").addEventListener("click", () => {
    document.getElementById("filterStatus").value = "";
    document.getElementById("filterSp").value = "";
    document.getElementById("filterAssignee").value = "";
    if (document.getElementById("filterTaskType")) document.getElementById("filterTaskType").value = "";
    if (document.getElementById("filterCluster")) document.getElementById("filterCluster").value = "";
    document.getElementById("filterSearch").value = "";
    try { sessionStorage.removeItem("klukva_filters"); } catch (e) {}
    loadTasks();
  });

  // Кнопка обновления из репозитория
  const btnAppUpdate = document.getElementById("btnAppUpdate");
  if (btnAppUpdate) {
    btnAppUpdate.addEventListener("click", handleAppUpdate);
  }

  // Сохранение положения при прокрутке и перед выгрузкой страницы
  window.addEventListener("scroll", debouncedSavePosition, { passive: true });
  window.addEventListener("beforeunload", saveStateAndPosition);
  window.addEventListener("pagehide", saveStateAndPosition);

  // Слушатели скролла на ключевых прокручиваемых контейнерах
  [
    document.querySelector(".app-layout"),
    document.querySelector("#viewBacklog .table-scroll-wrapper"),
    document.querySelector("#viewSprints .sprint-layout-container"),
    document.querySelector("#sectionSprint .table-scroll-wrapper"),
    document.querySelector("#sectionBacklog .table-scroll-wrapper"),
    document.querySelector(".scrum-board-wrapper")
  ].forEach(el => {
    if (el) el.addEventListener("scroll", debouncedSavePosition, { passive: true });
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
  document.getElementById("createTaskType")?.addEventListener("change", syncCreateHierarchyFields);
  document.getElementById("formCreateTask").addEventListener("submit", handleCreateTaskSubmit);

  // Детали задачи
  document.getElementById("btnBackFromDetail").addEventListener("click", closeTaskDetail);
  document.getElementById("btnSaveTask").addEventListener("click", saveTaskDetails);
  document.getElementById("detailStatus").addEventListener("change", () => {
    updatePartialSplitBoxVisibility();
    saveTaskDetails();
  });
  document.getElementById("detailTaskType")?.addEventListener("change", saveTaskDetails);
  document.getElementById("detailEpicId")?.addEventListener("change", saveTaskDetails);
  document.getElementById("detailSiriusId")?.addEventListener("change", saveTaskDetails);
  document.getElementById("btnAttachChildOpen")?.addEventListener("click", openHierarchyAttachForm);
  document.getElementById("btnCancelAttachChild")?.addEventListener("click", () => {
    const f = document.getElementById("hierarchyAttachForm");
    if (f) f.style.display = "none";
  });
  document.getElementById("btnConfirmAttachChild")?.addEventListener("click", confirmHierarchyAttach);
  document.getElementById("btnCreateChildInContainer")?.addEventListener("click", () => {
    const cur = state.currentTaskDetail;
    if (!cur) return;
    if (cur.task_type === "Эпик") {
      openCreateTaskView({ task_type: "Задача", epic_id: cur.id });
    } else if (cur.task_type === "Сириус") {
      openCreateTaskView({ task_type: "Эпик", sirius_id: cur.id });
    }
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
  document.getElementById("formAuthTotp")?.addEventListener("submit", handleTotpLoginSubmit);
  document.getElementById("btnBackToPassword")?.addEventListener("click", () => {
    document.getElementById("formAuthTotp").style.display = "none";
    document.getElementById("formAuth").style.display = "block";
    state.pendingTotpChallenge = null;
  });
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
      closeProfileView();
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
      document.getElementById("fullpageProfile").style.display = "none";
      const targetTab = (e.state && e.state.tab) || urlParams.get("tab") || localStorage.getItem("klukva_active_tab") || "backlog";
      if (targetTab !== state.currentTab) {
        switchTab(targetTab, false);
      }
    }
  });
}

function switchTab(tab, updateUrl = true) {
  state.currentTab = tab;
  localStorage.setItem("klukva_active_tab", tab);
  debouncedSavePosition();

  if (updateUrl) {
    try {
      const currentUrl = new URL(window.location.href);
      if (!currentUrl.pathname.startsWith("/task/")) {
        currentUrl.searchParams.set("tab", tab);
        window.history.replaceState({ tab }, "", currentUrl.toString());
      }
    } catch (e) {}
  }

  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });

  document.getElementById("viewBacklog").classList.toggle("active", tab === "backlog");
  document.getElementById("viewSprints").classList.toggle("active", tab === "sprints");
  document.getElementById("viewBoard").classList.toggle("active", tab === "board");
  document.getElementById("viewAnalytics")?.classList.toggle("active", tab === "analytics");
  document.getElementById("viewSystem")?.classList.toggle("active", tab === "system");

  if (tab === "analytics") {
    loadAnalytics();
  } else if (tab === "system") {
    loadSystemPanel();
  } else {
    loadTasks();
  }
}

function debounce(func, wait) {
  let timeout;
  return function (...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}

// ============================================================================
// УВЕДОМЛЕНИЯ (ПЛАШКА В ШАПКЕ)
// ============================================================================
let notifPollTimer = null;

async function loadNotifications() {
  if (!state.token) return;
  try {
    const data = await api("/api/notifications");
    renderNotifications(data);
    if (!notifPollTimer) {
      notifPollTimer = setInterval(loadNotifications, 30000);
    }
  } catch (e) {}
}

function renderNotifications(data) {
  const badge = document.getElementById("notifBadge");
  const list = document.getElementById("notifList");
  if (!badge || !list) return;

  const unread = data.unread_count || 0;
  badge.textContent = unread > 99 ? "99+" : String(unread);
  badge.style.display = unread > 0 ? "inline-flex" : "none";

  const items = data.items || [];
  if (!items.length) {
    list.innerHTML = '<div class="links-empty" style="padding: 16px; text-align: center;">Уведомлений пока нет</div>';
    return;
  }
  list.innerHTML = "";
  items.forEach(n => {
    const el = document.createElement("div");
    el.className = `notif-item ${n.read ? "" : "unread"}`;
    el.innerHTML = `
      <div class="notif-item-title">${escapeHtml(n.title)}</div>
      <div class="notif-item-msg">${escapeHtml(n.message)}</div>
      <div class="notif-item-time">${formatDate(n.created_at)}</div>
    `;
    el.onclick = async () => {
      if (!n.read) {
        try {
          await api(`/api/notifications/${n.id}/read`, { method: "POST" });
          n.read = true;
          loadNotifications();
        } catch (e) {}
      }
      document.getElementById("notifDropdown").style.display = "none";
      if (n.task_id) openTaskDetail(n.task_id);
    };
    list.appendChild(el);
  });
}

function setupNotificationListeners() {
  const btn = document.getElementById("btnNotifications");
  const dropdown = document.getElementById("notifDropdown");
  if (!btn || !dropdown) return;

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = dropdown.style.display === "flex";
    dropdown.style.display = isOpen ? "none" : "flex";
    if (!isOpen) loadNotifications();
  });

  document.getElementById("btnMarkAllRead")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    try {
      await api("/api/notifications/read-all", { method: "POST" });
      await loadNotifications();
    } catch (err) {
      showToast(err.message);
    }
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#notifWrapper")) {
      dropdown.style.display = "none";
    }
  });
}

// ============================================================================
// ЛИЧНЫЙ КАБИНЕТ ПОЛЬЗОВАТЕЛЯ (ПРОФИЛЬ, АКТИВНОСТЬ, TOTP, УСТРОЙСТВА, PAT/MCP, РОЛИ)
// ============================================================================
async function openProfileView(username = null) {
  if (!state.currentUser) return;
  const targetUsername = username || state.currentUser.username;
  state.viewingProfileUsername = targetUsername;
  const isOwn = targetUsername.toLowerCase() === state.currentUser.username.toLowerCase();
  const mustForce = isOwn && !!state.currentUser.must_change_credentials;

  const fullpageEl = document.getElementById("fullpageProfile");
  const backBtn = document.getElementById("btnBackFromProfile");
  const headerRight = fullpageEl?.querySelector(".fullpage-header-right");
  const forcedCard = document.getElementById("cardForcedCredentials");
  const stdCards = document.getElementById("profStandardCards");

  // Populate user selector
  const sel = document.getElementById("profileUserSelect");
  if (sel) {
    sel.innerHTML = "";
    const userList = state.users.length ? state.users : [state.currentUser];
    userList.forEach(u => {
      const opt = document.createElement("option");
      opt.value = u.username;
      opt.textContent = `${u.display_name} (@${u.username})`;
      sel.appendChild(opt);
    });
    sel.value = targetUsername;
  }

  fullpageEl.style.display = "flex";
  document.getElementById("profilePageTitle").textContent = mustForce
    ? "Обязательная смена логина и пароля"
    : (isOwn ? "Личный кабинет" : `Профиль @${targetUsername}`);
  if (backBtn) backBtn.style.display = mustForce ? "none" : "inline-flex";
  if (headerRight) headerRight.style.display = mustForce ? "none" : "flex";
  if (forcedCard) forcedCard.style.display = mustForce ? "block" : "none";
  if (stdCards) stdCards.style.display = mustForce ? "none" : "grid";

  document.getElementById("profAvatarActions").style.display = (isOwn && !mustForce) ? "flex" : "none";
  document.getElementById("profBtnTabActivity").style.display = mustForce ? "none" : "inline-block";
  document.getElementById("profBtnTabSecurity").style.display = isOwn ? "inline-block" : "none";
  document.getElementById("profBtnTabTokens").style.display = (isOwn && !mustForce) ? "inline-block" : "none";
  document.getElementById("profBtnTabRoles").style.display = (isOwn && !mustForce && hasMinRole("admin")) ? "inline-block" : "none";
  document.getElementById("profTotpStatusItem").style.display = isOwn ? "block" : "none";

  if (mustForce) {
    switchProfileSubtab("security");
  } else if (!isOwn) {
    switchProfileSubtab("activity");
  }

  try {
    const data = isOwn
      ? await api("/api/profile")
      : await api(`/api/users/${encodeURIComponent(targetUsername)}/profile`);

    const u = data.user;
    document.getElementById("profAvatarLg").innerHTML = renderUserAvatarContent(u);
    document.getElementById("profDisplayName").textContent = u.display_name;
    document.getElementById("profUsername").textContent = `@${u.username}`;
    const rBadge = document.getElementById("profRoleBadge");
    if (u.is_system) {
      rBadge.textContent = "system";
      rBadge.className = "role-badge role-system";
    } else {
      rBadge.textContent = u.role || "member";
      rBadge.className = `role-badge role-${u.role || "member"}`;
    }

    document.getElementById("profLastLogin").textContent = u.last_login_at ? formatDate(u.last_login_at) : "Нет данных";
    document.getElementById("profLoginCount").textContent = String(u.login_count ?? 0);
    document.getElementById("profCreatedAt").textContent = u.created_at ? formatDate(u.created_at) : "—";

    renderProfileActivity(data.activity);

    if (isOwn) {
      state.currentUser = { ...state.currentUser, ...u };
      updateUserHeader();
      document.getElementById("btnRemoveAvatar").style.display = u.avatar_url ? "inline-flex" : "none";
      document.getElementById("inputProfDisplayName").value = u.display_name || "";
      document.getElementById("profTotpStatus").textContent = u.totp_enabled ? "Включена" : "Выключена";
      document.getElementById("totpDisabledBox").style.display = u.totp_enabled ? "none" : "block";
      document.getElementById("totpEnabledBox").style.display = u.totp_enabled ? "block" : "none";
      document.getElementById("totpSetupBox").style.display = "none";

      renderTrustedDevices(data.trusted_devices || []);
      renderPatTokens(data.pat_tokens || []);
      renderMcpConfig();
      if (!mustForce && hasMinRole("admin") && state.users.length) renderRolesManagement();
    }
  } catch (err) {
    showToast(`Ошибка загрузки профиля: ${err.message}`);
  }
}

function closeProfileView() {
  if (state.currentUser?.must_change_credentials) {
    showToast("Необходимо сначала изменить логин и пароль по умолчанию");
    return;
  }
  const el = document.getElementById("fullpageProfile");
  if (el) el.style.display = "none";
}

function switchProfileSubtab(tabName) {
  if (state.currentUser?.must_change_credentials && tabName !== "security") {
    tabName = "security";
  }
  document.querySelectorAll(".profile-subtab").forEach(b => {
    if (b.dataset.proftab) {
      b.classList.toggle("active", b.dataset.proftab === tabName);
    }
  });
  const map = {
    activity: "profPanelActivity",
    security: "profPanelSecurity",
    tokens: "profPanelTokens",
    roles: "profPanelRoles"
  };
  Object.entries(map).forEach(([k, id]) => {
    document.getElementById(id)?.classList.toggle("active", k === tabName);
  });
}

function renderProfileActivity(activity) {
  const statsEl = document.getElementById("profActivityStats");
  const feedEl = document.getElementById("profActivityFeed");
  const s = activity?.stats || {};
  statsEl.innerHTML = `
    <div class="kpi-card"><div class="kpi-label">Назначено задач</div><div class="kpi-val">${s.assigned_total ?? 0}</div></div>
    <div class="kpi-card"><div class="kpi-label">В работе</div><div class="kpi-val">${s.in_progress_total ?? 0}</div></div>
    <div class="kpi-card"><div class="kpi-label">Завершено</div><div class="kpi-val">${s.completed_total ?? 0}</div></div>
    <div class="kpi-card"><div class="kpi-label">Выполнено SP</div><div class="kpi-val">${s.completed_sp ?? 0}</div></div>
    <div class="kpi-card"><div class="kpi-label">Создано задач</div><div class="kpi-val">${s.created_total ?? 0}</div></div>
  `;

  const items = activity?.items || [];
  if (!items.length) {
    feedEl.innerHTML = '<div class="links-empty" style="padding: 12px 0;">Активность пока отсутствует</div>';
    return;
  }
  feedEl.innerHTML = "";
  items.forEach(a => {
    const row = document.createElement("div");
    row.className = "activity-row";
    const taskPart = a.task_id
      ? `<span class="task-key-link" data-tid="${a.task_id}">${escapeHtml(a.task_key || `KLUK-${a.task_id}`)}</span> <b>${escapeHtml(a.task_title || "")}</b> — `
      : "";
    row.innerHTML = `
      <div>${taskPart}<span>${escapeHtml(a.details || a.action)}</span></div>
      <div class="activity-time">${formatDate(a.created_at)}</div>
    `;
    const link = row.querySelector(".task-key-link");
    if (link) {
      link.onclick = () => {
        closeProfileView();
        openTaskDetail(a.task_id);
      };
    }
    feedEl.appendChild(row);
  });
}

function renderTrustedDevices(devices) {
  const container = document.getElementById("trustedDevicesList");
  if (!devices.length) {
    container.innerHTML = '<div class="links-empty">Нет сохранённых доверенных устройств</div>';
    return;
  }
  container.innerHTML = "";
  devices.forEach(d => {
    const row = document.createElement("div");
    row.className = "device-row";
    row.innerHTML = `
      <div>
        <div><b>${escapeHtml(d.name || "Устройство")}</b> ${d.is_current ? '<span class="status-pill status-done" style="font-size:10px;">Текущее</span>' : ""}</div>
        <div class="device-meta">IP: ${escapeHtml(d.ip || "—")} · Вход: ${formatDate(d.created_at)} · Активность: ${formatDate(d.last_used_at)}</div>
      </div>
      <button type="button" class="btn btn-secondary btn-sm">Отозвать</button>
    `;
    row.querySelector("button").onclick = async () => {
      if (!confirm("Отозвать доверенное устройство? Авторизация на нём будет сброшена.")) return;
      try {
        await api(`/api/profile/trusted-devices/${encodeURIComponent(d.id)}`, { method: "DELETE" });
        showToast("Устройство отозвано");
        openProfileView(state.currentUser.username);
      } catch (err) {
        showToast(err.message);
      }
    };
    container.appendChild(row);
  });
}

function renderPatTokens(pats) {
  const container = document.getElementById("patTokensList");
  if (!pats.length) {
    container.innerHTML = '<div class="links-empty">Персональные токены пока не созданы</div>';
    return;
  }
  container.innerHTML = "";
  pats.forEach(p => {
    const row = document.createElement("div");
    row.className = "pat-row";
    row.innerHTML = `
      <div>
        <div><b>${escapeHtml(p.name)}</b> <code>${escapeHtml(p.prefix)}...</code></div>
        <div class="pat-meta">Создан: ${formatDate(p.created_at)} · Использован: ${p.last_used_at ? formatDate(p.last_used_at) : "никогда"} · Истекает: ${p.expires_at ? formatDate(p.expires_at) : "бессрочно"}</div>
      </div>
      <button type="button" class="btn btn-secondary btn-sm">Удалить</button>
    `;
    row.querySelector("button").onclick = async () => {
      if (!confirm(`Удалить токен «${p.name}»?`)) return;
      try {
        await api(`/api/profile/tokens/${encodeURIComponent(p.id)}`, { method: "DELETE" });
        showToast("Токен удалён");
        openProfileView(state.currentUser.username);
      } catch (err) {
        showToast(err.message);
      }
    };
    container.appendChild(row);
  });
}

function renderMcpConfig() {
  const el = document.getElementById("mcpConfigCode");
  if (!el) return;
  const cfg = {
    mcpServers: {
      klukva: {
        url: `${window.location.origin}/mcp`,
        headers: {
          Authorization: "Bearer <ВАШ_PAT_ТОКЕН>"
        }
      }
    }
  };
  el.textContent = JSON.stringify(cfg, null, 2);
}

function renderRolesManagement() {
  const wrap = document.getElementById("rolesTableWrap");
  if (!wrap) return;
  const roles = ["admin", "manager", "member", "viewer"];
  wrap.innerHTML = `
    <div class="table-scroll-wrapper">
      <table class="tasks-table">
        <thead><tr><th>Пользователь</th><th>Логин</th><th>Последний вход</th><th>Роль</th></tr></thead>
        <tbody id="rolesTableBody"></tbody>
      </table>
    </div>
  `;
  const tbody = document.getElementById("rolesTableBody");
  state.users.forEach(u => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(u.display_name)} ${u.is_system ? '<span class="role-badge role-system">system</span>' : ""}</td>
      <td>@${escapeHtml(u.username)}</td>
      <td>${u.last_login_at ? formatDate(u.last_login_at) : "—"}</td>
      <td>
        ${u.is_system
          ? "<b>admin (system)</b>"
          : `<select class="form-control select-sm" style="max-width: 150px;">${roles.map(r => `<option value="${r}" ${(u.role || "member") === r ? "selected" : ""}>${r}</option>`).join("")}</select>`
        }
      </td>
    `;
    const select = tr.querySelector("select");
    if (select) {
      select.onchange = async () => {
        try {
          const updated = await api(`/api/users/${u.id}/role`, {
            method: "PATCH",
            body: JSON.stringify({ role: select.value })
          });
          u.role = updated.role;
          showToast(`Роль @${u.username}: ${updated.role}`);
        } catch (err) {
          showToast(`Ошибка: ${err.message}`);
          select.value = u.role || "member";
        }
      };
    }
    tbody.appendChild(tr);
  });
}

function setupProfileListeners() {
  document.getElementById("btnOpenOwnProfile")?.addEventListener("click", () => openProfileView());
  document.getElementById("btnBackFromProfile")?.addEventListener("click", closeProfileView);
  document.getElementById("profileUserSelect")?.addEventListener("change", (e) => openProfileView(e.target.value));

  document.querySelectorAll(".profile-subtab[data-proftab]").forEach(btn => {
    btn.addEventListener("click", () => switchProfileSubtab(btn.dataset.proftab));
  });

  // Forced Credentials Change (system user first login)
  document.getElementById("formChangeCredentials")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errEl = document.getElementById("credChangeError");
    if (errEl) errEl.style.display = "none";

    const current_password = document.getElementById("inputCredCurrentPw").value;
    const new_username = document.getElementById("inputCredNewUsername").value.trim();
    const new_password = document.getElementById("inputCredNewPassword").value;
    const confirm_password = document.getElementById("inputCredConfirmPassword").value;

    const showErr = (msg) => {
      if (errEl) {
        errEl.textContent = msg;
        errEl.style.display = "block";
      } else {
        showToast(msg);
      }
    };

    if (new_username.toLowerCase() === "admin") {
      return showErr("Новый логин должен отличаться от 'admin'");
    }
    if (new_password !== confirm_password) {
      return showErr("Пароли не совпадают");
    }
    if (new_password.toLowerCase() === "admin") {
      return showErr("Новый пароль не может быть 'admin'");
    }

    try {
      const res = await api("/api/profile/credentials", {
        method: "POST",
        body: JSON.stringify({ current_password, new_username, new_password })
      });
      state.token = res.token;
      saveStoredToken(res.token);
      state.currentUser = res.user;
      document.getElementById("formChangeCredentials").reset();
      showToast("Логин и пароль успешно изменены");
      closeProfileView();
      await onAuthSuccess();
    } catch (err) {
      showErr(err.message);
    }
  });

  // Avatar upload / remove
  const avInput = document.getElementById("avatarFileInput");
  document.getElementById("btnUploadAvatar")?.addEventListener("click", () => avInput?.click());
  avInput?.addEventListener("change", async () => {
    const file = avInput.files[0];
    avInput.value = "";
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      showToast("Аватар больше 5 МБ");
      return;
    }
    try {
      await api(`/api/profile/avatar?filename=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: { "Content-Type": file.type || "image/png" },
        body: file
      });
      showToast("Аватар обновлён");
      await loadUsers();
      openProfileView(state.currentUser.username);
    } catch (err) {
      showToast(`Ошибка: ${err.message}`);
    }
  });
  document.getElementById("btnRemoveAvatar")?.addEventListener("click", async () => {
    try {
      await api("/api/profile/avatar", { method: "DELETE" });
      showToast("Аватар удалён");
      await loadUsers();
      openProfileView(state.currentUser.username);
    } catch (err) {
      showToast(err.message);
    }
  });

  // Edit ФИО
  document.getElementById("formProfileName")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const display_name = document.getElementById("inputProfDisplayName").value.trim();
    if (!display_name) return;
    try {
      await api("/api/profile", { method: "PATCH", body: JSON.stringify({ display_name }) });
      showToast("ФИО обновлено");
      await loadUsers();
      openProfileView(state.currentUser.username);
    } catch (err) {
      showToast(err.message);
    }
  });

  // Change Password
  document.getElementById("formProfilePassword")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const current_password = document.getElementById("inputCurPassword").value;
    const new_password = document.getElementById("inputNewPassword").value;
    try {
      await api("/api/profile/password", {
        method: "POST",
        body: JSON.stringify({ current_password, new_password })
      });
      document.getElementById("formProfilePassword").reset();
      showToast("Пароль успешно изменён");
    } catch (err) {
      showToast(err.message);
    }
  });

  // TOTP Setup & Enable & Disable
  document.getElementById("btnStartTotpSetup")?.addEventListener("click", async () => {
    try {
      const res = await api("/api/profile/totp/setup", { method: "POST" });
      document.getElementById("totpQrWrap").innerHTML = res.qr_svg;
      document.getElementById("totpSecretText").textContent = res.secret;
      document.getElementById("totpSetupBox").style.display = "block";
    } catch (err) {
      showToast(err.message);
    }
  });
  document.getElementById("formEnableTotp")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const code = document.getElementById("inputEnableTotpCode").value.trim();
    try {
      await api("/api/profile/totp/enable", { method: "POST", body: JSON.stringify({ code }) });
      document.getElementById("formEnableTotp").reset();
      showToast("2FA (TOTP) включена");
      openProfileView(state.currentUser.username);
    } catch (err) {
      showToast(err.message);
    }
  });
  document.getElementById("formDisableTotp")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const val = document.getElementById("inputDisableTotpPw").value.trim();
    const payload = /^\d{6}$/.test(val) ? { code: val } : { password: val };
    try {
      await api("/api/profile/totp/disable", { method: "POST", body: JSON.stringify(payload) });
      document.getElementById("formDisableTotp").reset();
      showToast("2FA (TOTP) отключена");
      openProfileView(state.currentUser.username);
    } catch (err) {
      showToast(err.message);
    }
  });

  // PAT tokens
  document.getElementById("formCreatePat")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("inputPatName").value.trim();
    const expires_days = parseInt(document.getElementById("inputPatDays").value, 10);
    try {
      const res = await api("/api/profile/tokens", {
        method: "POST",
        body: JSON.stringify({ name, expires_days })
      });
      document.getElementById("formCreatePat").reset();
      document.getElementById("newPatValue").textContent = res.token;
      document.getElementById("newPatRevealBox").style.display = "block";
      showToast("Токен создан");
      const pats = await api("/api/profile/tokens");
      renderPatTokens(pats);
    } catch (err) {
      showToast(err.message);
    }
  });
  document.getElementById("btnCopyNewPat")?.addEventListener("click", () => {
    navigator.clipboard?.writeText(document.getElementById("newPatValue").textContent);
    showToast("Токен скопирован");
  });
  document.getElementById("btnCopyMcpConfig")?.addEventListener("click", () => {
    navigator.clipboard?.writeText(document.getElementById("mcpConfigCode").textContent);
    showToast("Конфиг MCP скопирован");
  });
}

// ============================================================================
// АНАЛИТИКА И ГРАФИКИ
// ============================================================================
async function loadAnalytics() {
  const kpiGrid = document.getElementById("analyticsKpiGrid");
  const chartsGrid = document.getElementById("analyticsChartsGrid");
  if (!kpiGrid || !chartsGrid) return;
  try {
    const data = await api("/api/analytics");
    const s = data.summary || {};
    kpiGrid.innerHTML = `
      <div class="kpi-card"><div class="kpi-label">Всего задач</div><div class="kpi-val">${s.total_tasks ?? 0}</div></div>
      <div class="kpi-card"><div class="kpi-label">В работе</div><div class="kpi-val">${s.in_progress_tasks ?? 0}</div></div>
      <div class="kpi-card"><div class="kpi-label">Завершено</div><div class="kpi-val">${s.done_tasks ?? 0}</div></div>
      <div class="kpi-card"><div class="kpi-label">В бэклоге</div><div class="kpi-val">${s.backlog_tasks ?? 0}</div></div>
      <div class="kpi-card"><div class="kpi-label">Story Points (Всего)</div><div class="kpi-val">${s.total_sp ?? 0}</div></div>
      <div class="kpi-card"><div class="kpi-label">Story Points (Готово)</div><div class="kpi-val">${s.done_sp ?? 0}</div></div>
    `;

    const statusColors = {
      "Бэклог": "#94a3b8",
      "В работе": "#2563eb",
      "Завершено": "#059669",
      "Не реализовано": "#dc2626",
      "Реализовано частично": "#d97706"
    };
    const typeColors = {
      "Задача": "#64748b",
      "Нововведение": "#16a34a",
      "Ошибка": "#dc2626",
      "Тестирование": "#ca8a04",
      "Ревью": "#9333ea",
      "Исследование": "#2563eb",
      "Эпик": "#be123c",
      "Сириус": "#0284c7"
    };

    chartsGrid.innerHTML = [
      renderBarChartCard("Задачи по статусам", data.by_status || [], statusColors),
      renderBarChartCard("Типы задач и контейнеры", data.by_type || [], typeColors),
      renderAssigneeChartCard(data.by_assignee || []),
      renderHierarchyAnalyticsCard("Прогресс по Сириусам", data.siriuses || [], "sirius"),
      renderHierarchyAnalyticsCard("Прогресс по Эпикам", data.epics || [], "epic"),
      renderSprintVelocityCard(data.sprints || []),
      renderTimelineChartCard(data.timeline || [])
    ].join("");
  } catch (err) {
    chartsGrid.innerHTML = `<div class="links-empty">Ошибка загрузки аналитики: ${escapeHtml(err.message)}</div>`;
  }
}

function renderHierarchyAnalyticsCard(title, items, kind) {
  if (!items || !items.length) {
    const emptyLabel = kind === "sirius" ? "Сириусов пока нет" : "Эпиков пока нет";
    return `<div class="chart-card"><div class="chart-card-title">${escapeHtml(title)}</div><div class="links-empty">${emptyLabel}</div></div>`;
  }
  const color = kind === "sirius" ? "#0284c7" : "#be123c";
  const rows = items.map(item => {
    const total = Number(item.total_tasks || 0);
    const done = Number(item.done_tasks || 0);
    const pct = total ? Math.round((done / total) * 100) : 0;
    const extra = kind === "sirius"
      ? `${item.epics_count || 0} эп. · ${done}/${total} задач`
      : `${done}/${total} задач${item.sirius_key ? ` · ${escapeHtml(item.sirius_key)}` : ""}`;
    return `
      <div class="analytics-progress-row">
        <div class="analytics-progress-head">
          <span class="analytics-progress-title" onclick="openTaskDetail(${item.id})">${escapeHtml(item.key)} — ${escapeHtml(item.title)}</span>
          <span class="analytics-progress-meta">${extra} (${pct}%)</span>
        </div>
        <div class="chart-bar-track"><div class="chart-bar-fill" style="width:${pct}%;background:${color};"></div></div>
      </div>
    `;
  }).join("");
  return `<div class="chart-card"><div class="chart-card-title">${escapeHtml(title)}</div>${rows}</div>`;
}

function renderBarChartCard(title, items, colors = {}) {
  const maxVal = Math.max(1, ...items.map(i => i.count));
  const rows = items.map(i => {
    const pct = Math.round((i.count / maxVal) * 100);
    const col = colors[i.label] || "var(--accent)";
    return `
      <div class="chart-bar-row">
        <div class="chart-bar-label" title="${escapeHtml(i.label)}">${escapeHtml(i.label)}</div>
        <div class="chart-bar-track"><div class="chart-bar-fill" style="width:${pct}%;background:${col};"></div></div>
        <div class="chart-bar-val">${i.count}</div>
      </div>
    `;
  }).join("");
  return `<div class="chart-card"><div class="chart-card-title">${escapeHtml(title)}</div>${rows}</div>`;
}

function renderAssigneeChartCard(assignees) {
  if (!assignees.length) return `<div class="chart-card"><div class="chart-card-title">Нагрузка по исполнителям</div><div class="links-empty">Нет данных</div></div>`;
  const maxTotal = Math.max(1, ...assignees.map(a => a.total));
  const rows = assignees.slice(0, 12).map(a => {
    const pct = Math.round((a.total / maxTotal) * 100);
    const donePct = Math.round((a.done / maxTotal) * 100);
    return `
      <div class="chart-bar-row">
        <div class="chart-bar-label" title="${escapeHtml(a.display_name)}">${escapeHtml(a.display_name)}</div>
        <div class="chart-bar-track" style="position:relative;">
          <div class="chart-bar-fill" style="width:${pct}%;background:#93c5fd;"></div>
          <div class="chart-bar-fill" style="width:${donePct}%;background:#059669;position:absolute;top:0;left:0;"></div>
        </div>
        <div class="chart-bar-val">${a.done}/${a.total}</div>
      </div>
    `;
  }).join("");
  return `
    <div class="chart-card">
      <div class="chart-card-title">Нагрузка по исполнителям (готово / всего)</div>
      ${rows}
      <div class="chart-legend">
        <span class="chart-legend-item"><span class="chart-legend-dot" style="background:#059669;"></span>Завершено</span>
        <span class="chart-legend-item"><span class="chart-legend-dot" style="background:#93c5fd;"></span>Всего</span>
      </div>
    </div>
  `;
}

function renderSprintVelocityCard(sprints) {
  if (!sprints.length) return `<div class="chart-card"><div class="chart-card-title">Velocity по спринтам (SP)</div><div class="links-empty">Спринты ещё не созданы</div></div>`;
  const list = sprints.slice(-8);
  const w = 460, h = 180, padL = 34, padB = 28, padT = 16;
  const maxSp = Math.max(1, ...list.map(s => Math.max(s.total_sp, s.done_sp)));
  const groupW = (w - padL - 10) / list.length;
  const barW = Math.max(8, Math.min(22, groupW * 0.34));
  const bars = list.map((s, idx) => {
    const x0 = padL + idx * groupW + groupW * 0.15;
    const hTot = ((s.total_sp / maxSp) * (h - padB - padT));
    const hDone = ((s.done_sp / maxSp) * (h - padB - padT));
    const yTot = h - padB - hTot;
    const yDone = h - padB - hDone;
    return `
      <rect x="${x0}" y="${yTot}" width="${barW}" height="${hTot}" fill="#93c5fd"><title>${escapeHtml(s.name)}: Всего ${s.total_sp} SP</title></rect>
      <rect x="${x0 + barW + 3}" y="${yDone}" width="${barW}" height="${hDone}" fill="#059669"><title>${escapeHtml(s.name)}: Готово ${s.done_sp} SP</title></rect>
      <text x="${x0 + barW}" y="${h - 10}" font-size="10" fill="currentColor" text-anchor="middle">${escapeHtml(s.name.slice(0, 10))}</text>
    `;
  }).join("");
  return `
    <div class="chart-card">
      <div class="chart-card-title">Velocity по спринтам (SP)</div>
      <div class="chart-svg-wrap">
        <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" style="color: var(--text-muted);">
          <line x1="${padL}" y1="${padT}" x2="${padL}" y2="${h - padB}" stroke="var(--border-default)"/>
          <line x1="${padL}" y1="${h - padB}" x2="${w - 8}" y2="${h - padB}" stroke="var(--border-default)"/>
          <text x="${padL - 4}" y="${padT + 8}" font-size="10" fill="currentColor" text-anchor="end">${maxSp}</text>
          <text x="${padL - 4}" y="${h - padB}" font-size="10" fill="currentColor" text-anchor="end">0</text>
          ${bars}
        </svg>
      </div>
      <div class="chart-legend">
        <span class="chart-legend-item"><span class="chart-legend-dot" style="background:#93c5fd;"></span>Всего SP</span>
        <span class="chart-legend-item"><span class="chart-legend-dot" style="background:#059669;"></span>Выполнено SP</span>
      </div>
    </div>
  `;
}

function renderTimelineChartCard(timeline) {
  if (!timeline.length) return `<div class="chart-card chart-card-full"><div class="chart-card-title">Динамика за 14 дней</div><div class="links-empty">Нет данных</div></div>`;
  const w = 960, h = 190, padL = 32, padR = 16, padT = 16, padB = 28;
  const maxV = Math.max(1, ...timeline.map(d => Math.max(d.created, d.completed)));
  const stepX = (w - padL - padR) / Math.max(1, timeline.length - 1);
  const pts = (key) => timeline.map((d, i) => {
    const x = padL + i * stepX;
    const y = h - padB - (d[key] / maxV) * (h - padB - padT);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const labels = timeline.filter((_, i) => i % 2 === 0 || i === timeline.length - 1).map(d => {
    const idx = timeline.indexOf(d);
    const x = padL + idx * stepX;
    return `<text x="${x.toFixed(1)}" y="${h - 10}" font-size="10" fill="currentColor" text-anchor="middle">${escapeHtml(d.label)}</text>`;
  }).join("");
  return `
    <div class="chart-card chart-card-full">
      <div class="chart-card-title">Активность за 14 дней (создано / завершено)</div>
      <div class="chart-svg-wrap">
        <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" style="color: var(--text-muted);">
          <line x1="${padL}" y1="${padT}" x2="${padL}" y2="${h - padB}" stroke="var(--border-default)"/>
          <line x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}" stroke="var(--border-default)"/>
          <text x="${padL - 4}" y="${padT + 8}" font-size="10" fill="currentColor" text-anchor="end">${maxV}</text>
          <text x="${padL - 4}" y="${h - padB}" font-size="10" fill="currentColor" text-anchor="end">0</text>
          <polyline fill="none" stroke="#2563eb" stroke-width="2" points="${pts("created")}"/>
          <polyline fill="none" stroke="#059669" stroke-width="2" points="${pts("completed")}"/>
          ${labels}
        </svg>
      </div>
      <div class="chart-legend">
        <span class="chart-legend-item"><span class="chart-legend-dot" style="background:#2563eb;"></span>Создано</span>
        <span class="chart-legend-item"><span class="chart-legend-dot" style="background:#059669;"></span>Завершено</span>
      </div>
    </div>
  `;
}

// ============================================================================
// СИСТЕМНАЯ ПАНЕЛЬ (АУДИТ, ВСЕ ФАЙЛЫ, ПОЛЬЗОВАТЕЛИ И БЭКАП БД)
// ============================================================================
let activeSystemTab = "audit";

function formatFileSize(bytes) {
  const b = Number(bytes || 0);
  if (b < 1024) return `${b} Б`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} КБ`;
  return `${(b / (1024 * 1024)).toFixed(2)} МБ`;
}

function setupSystemListeners() {
  document.querySelectorAll(".profile-subtab[data-systab]").forEach(btn => {
    btn.addEventListener("click", () => {
      activeSystemTab = btn.dataset.systab;
      document.querySelectorAll(".profile-subtab[data-systab]").forEach(b => {
        b.classList.toggle("active", b.dataset.systab === activeSystemTab);
      });
      document.getElementById("sysPanelAudit")?.classList.toggle("active", activeSystemTab === "audit");
      document.getElementById("sysPanelFiles")?.classList.toggle("active", activeSystemTab === "files");
      document.getElementById("sysPanelUsers")?.classList.toggle("active", activeSystemTab === "users");
      loadSystemPanel();
    });
  });

  document.getElementById("btnSysRefresh")?.addEventListener("click", loadSystemPanel);
  document.getElementById("sysAuditUser")?.addEventListener("change", loadSystemAudit);
  document.getElementById("sysAuditAction")?.addEventListener("change", loadSystemAudit);
  document.getElementById("sysAuditSearch")?.addEventListener("input", debounce(loadSystemAudit, 200));

  document.getElementById("btnSysExportDb")?.addEventListener("click", async () => {
    try {
      const resp = await fetch("/api/system/db-export", {
        headers: state.token ? { "Authorization": `Bearer ${state.token}` } : {}
      });
      if (!resp.ok) throw new Error(`Ошибка (${resp.status})`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `klukva_db_backup_${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast("Резервная копия БД загружена");
    } catch (err) {
      showToast(err.message);
    }
  });
}

async function loadSystemPanel() {
  if (!state.currentUser?.is_system) return;
  if (activeSystemTab === "audit") {
    await loadSystemAudit();
  } else if (activeSystemTab === "files") {
    await loadSystemFiles();
  } else if (activeSystemTab === "users") {
    await loadSystemUsers();
  }
}

async function loadSystemAudit() {
  const summaryEl = document.getElementById("sysAuditSummary");
  const feedEl = document.getElementById("sysAuditFeed");
  const userSel = document.getElementById("sysAuditUser");
  const actionSel = document.getElementById("sysAuditAction");
  if (!feedEl) return;

  if (userSel && userSel.options.length <= 1 && state.users.length) {
    state.users.forEach(u => {
      const opt = document.createElement("option");
      opt.value = u.username;
      opt.textContent = `${u.display_name} (@${u.username})`;
      userSel.appendChild(opt);
    });
  }

  const params = new URLSearchParams();
  if (userSel?.value) params.append("username", userSel.value);
  if (actionSel?.value) params.append("action", actionSel.value);
  const q = document.getElementById("sysAuditSearch")?.value.trim();
  if (q) params.append("search", q);

  try {
    const data = await api(`/api/system/audit?${params.toString()}`);
    if (summaryEl) {
      summaryEl.innerHTML = `
        <div class="kpi-card"><div class="kpi-label">Всего событий в журнале</div><div class="kpi-val">${data.total ?? 0}</div></div>
        <div class="kpi-card"><div class="kpi-label">Событий сегодня</div><div class="kpi-val">${data.today_count ?? 0}</div></div>
        <div class="kpi-card"><div class="kpi-label">Показано по фильтру</div><div class="kpi-val">${data.filtered_total ?? 0}</div></div>
      `;
    }
    if (actionSel && (data.actions || []).length) {
      const prev = actionSel.value;
      actionSel.innerHTML = '<option value="">Все типы событий</option>' +
        data.actions.map(a => `<option value="${escapeHtml(a)}">${escapeHtml(a)}</option>`).join("");
      actionSel.value = prev;
    }

    const items = data.items || [];
    if (!items.length) {
      feedEl.innerHTML = '<div class="links-empty" style="padding: 16px;">Записи по фильтру не найдены</div>';
      return;
    }
    feedEl.innerHTML = "";
    items.forEach(a => {
      const row = document.createElement("div");
      row.className = "activity-row";
      const taskPart = a.task_id
        ? `<span class="task-key-link" data-tid="${a.task_id}">${escapeHtml(a.task_key || `KLUK-${a.task_id}`)}</span> `
        : "";
      row.innerHTML = `
        <div>
          <span class="action-tag">${escapeHtml(a.action)}</span>
          <b>@${escapeHtml(a.username || "system")}</b>
          ${taskPart}
          <span>${escapeHtml(a.details || a.task_title || "")}</span>
        </div>
        <div class="activity-time">${formatDate(a.created_at)}</div>
      `;
      const link = row.querySelector(".task-key-link");
      if (link) {
        link.onclick = () => openTaskDetail(a.task_id);
      }
      feedEl.appendChild(row);
    });
  } catch (err) {
    feedEl.innerHTML = `<div class="links-empty" style="padding: 16px;">Ошибка: ${escapeHtml(err.message)}</div>`;
  }
}

async function loadSystemFiles() {
  const sumEl = document.getElementById("sysFilesSummary");
  const attWrap = document.getElementById("sysAttachmentsWrap");
  const avWrap = document.getElementById("sysAvatarsWrap");
  if (!attWrap || !avWrap) return;

  try {
    const data = await api("/api/system/files");
    if (sumEl) {
      sumEl.innerHTML = `
        <div class="kpi-card"><div class="kpi-label">Всего файлов</div><div class="kpi-val">${data.total_files ?? 0}</div></div>
        <div class="kpi-card"><div class="kpi-label">Вложений задач</div><div class="kpi-val">${(data.attachments || []).length}</div></div>
        <div class="kpi-card"><div class="kpi-label">Аватаров</div><div class="kpi-val">${(data.avatars || []).length}</div></div>
        <div class="kpi-card"><div class="kpi-label">Общий объём</div><div class="kpi-val">${formatFileSize(data.total_size)}</div></div>
      `;
    }

    const atts = data.attachments || [];
    if (!atts.length) {
      attWrap.innerHTML = '<div class="links-empty">Вложений пока нет</div>';
    } else {
      attWrap.innerHTML = `
        <div class="table-scroll-wrapper">
          <table class="tasks-table">
            <thead><tr><th>Файл</th><th>Задача</th><th>Размер</th><th>Автор</th><th>Загружен</th><th>Действия</th></tr></thead>
            <tbody id="sysAttsBody"></tbody>
          </table>
        </div>
      `;
      const tbody = document.getElementById("sysAttsBody");
      atts.forEach(a => {
        const tr = document.createElement("tr");
        const tokenParam = encodeURIComponent(state.token || "");
        const openUrl = `${a.file_url}?token=${tokenParam}`;
        const dlUrl = `${a.file_url}?download=true&token=${tokenParam}`;
        tr.innerHTML = `
          <td><a href="${openUrl}" target="_blank" rel="noopener">${escapeHtml(a.filename)}</a></td>
          <td>${a.task_key ? `<span class="task-key-link" data-tid="${a.task_id}">${escapeHtml(a.task_key)}</span>` : "—"}</td>
          <td>${formatFileSize(a.size)}</td>
          <td>@${escapeHtml(a.uploaded_by || "—")}</td>
          <td>${formatDate(a.created_at)}</td>
          <td style="white-space: nowrap;">
            <a href="${dlUrl}" class="btn btn-secondary btn-sm">Скачать</a>
            <button type="button" class="btn btn-secondary btn-sm sys-del-att">Удалить</button>
          </td>
        `;
        tr.querySelector(".task-key-link")?.addEventListener("click", () => openTaskDetail(a.task_id));
        tr.querySelector(".sys-del-att")?.addEventListener("click", async () => {
          if (!confirm(`Удалить файл «${a.filename}»?`)) return;
          try {
            await api(`/api/tasks/${a.task_id}/attachments/${a.id}`, { method: "DELETE" });
            showToast("Файл удалён");
            loadSystemFiles();
          } catch (err) {
            showToast(err.message);
          }
        });
        tbody.appendChild(tr);
      });
    }

    const avatars = data.avatars || [];
    if (!avatars.length) {
      avWrap.innerHTML = '<div class="links-empty">Загруженных аватаров нет</div>';
    } else {
      avWrap.innerHTML = `<div class="sys-avatars-grid">${avatars.map(av => `
        <div class="sys-avatar-card">
          <img src="${escapeHtml(av.file_url)}" alt="">
          <div>
            <div><b>${escapeHtml(av.display_name)}</b></div>
            <div class="pat-meta">@${escapeHtml(av.username)} · ${formatFileSize(av.size)}</div>
          </div>
        </div>
      `).join("")}</div>`;
    }
  } catch (err) {
    attWrap.innerHTML = `<div class="links-empty">Ошибка: ${escapeHtml(err.message)}</div>`;
  }
}

async function loadSystemUsers() {
  const wrap = document.getElementById("sysUsersWrap");
  if (!wrap) return;
  try {
    const users = await api("/api/system/users");
    const roles = ["admin", "manager", "member", "viewer"];
    wrap.innerHTML = `
      <div class="table-scroll-wrapper">
        <table class="tasks-table">
          <thead><tr><th>Пользователь</th><th>Логин</th><th>Роль</th><th>2FA</th><th>Устройства</th><th>PAT</th><th>Входы</th><th>Действия</th></tr></thead>
          <tbody id="sysUsersBody"></tbody>
        </table>
      </div>
    `;
    const tbody = document.getElementById("sysUsersBody");
    users.forEach(u => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(u.display_name)} ${u.is_system ? '<span class="role-badge role-system">system</span>' : ""}</td>
        <td>@${escapeHtml(u.username)}</td>
        <td>
          ${u.is_system
            ? "<b>admin (system)</b>"
            : `<select class="form-control select-sm sys-role-sel" style="max-width: 120px;">${roles.map(r => `<option value="${r}" ${u.role === r ? "selected" : ""}>${r}</option>`).join("")}</select>`
          }
        </td>
        <td>${u.totp_enabled ? "Включена" : "Нет"}</td>
        <td>${u.trusted_devices_count ?? 0}</td>
        <td>${u.pat_count ?? 0}</td>
        <td>${u.login_count ?? 0}</td>
        <td style="white-space: nowrap;">
          ${u.totp_enabled ? '<button type="button" class="btn btn-secondary btn-sm sys-reset-totp">Сбросить 2FA</button>' : ""}
          ${(u.trusted_devices_count > 0) ? '<button type="button" class="btn btn-secondary btn-sm sys-clear-devs">Сбросить сессии</button>' : ""}
        </td>
      `;
      const sel = tr.querySelector(".sys-role-sel");
      if (sel) {
        sel.onchange = async () => {
          try {
            await api(`/api/users/${u.id}/role`, { method: "PATCH", body: JSON.stringify({ role: sel.value }) });
            showToast(`Роль @${u.username}: ${sel.value}`);
            await loadUsers();
          } catch (err) {
            showToast(err.message);
            sel.value = u.role;
          }
        };
      }
      tr.querySelector(".sys-reset-totp")?.addEventListener("click", async () => {
        if (!confirm(`Отключить 2FA для @${u.username}?`)) return;
        await api(`/api/system/users/${u.id}/reset-totp`, { method: "POST" });
        showToast("2FA отключена");
        loadSystemUsers();
      });
      tr.querySelector(".sys-clear-devs")?.addEventListener("click", async () => {
        if (!confirm(`Сбросить все доверенные устройства @${u.username}?`)) return;
        await api(`/api/system/users/${u.id}/devices`, { method: "DELETE" });
        showToast("Устройства сброшены");
        loadSystemUsers();
      });
      tbody.appendChild(tr);
    });
  } catch (err) {
    wrap.innerHTML = `<div class="links-empty">Ошибка: ${escapeHtml(err.message)}</div>`;
  }
}