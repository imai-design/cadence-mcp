const state = {
  dashboard: null,
  focusMinutes: 5,
  timerInterval: null,
  pollTimer: null,
  polling: false,
  dirty: { rhythm: false, lowBattery: false },
};

// localhost への軽量ポーリング間隔。Claude(MCP)側の変更を数秒で画面へ反映する。
const POLL_MS = 3000;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "うまく処理できませんでした。");
  return data;
}

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("error", error);
  node.classList.add("show");
  window.clearTimeout(toast.timeout);
  toast.timeout = window.setTimeout(() => node.classList.remove("show"), 3400);
}

function formatDate(value) {
  return new Intl.DateTimeFormat("ja-JP", {
    month: "long", day: "numeric", weekday: "long",
  }).format(new Date(`${value}T12:00:00`));
}

function renderDashboard(dashboard) {
  state.dashboard = dashboard;
  $("#today-label").textContent = formatDate(dashboard.date);
  $("#disclaimer").textContent = dashboard.disclaimer;

  const task = dashboard.current_task;
  $("#one-title").textContent = task ? task.title : "まだ一歩は置かれていません";
  $("#one-copy").textContent = task
    ? "ほかは隠してあります。終わらなくても、触れたところまでで大丈夫です。"
    : "浮かんだことを、小さな一歩として置けます。";
  $("#task-done").hidden = !task;

  const latest = dashboard.latest_checkin;
  $("#checkin-status").textContent = latest ? "記録済み" : "まだ";
  $("#checkin-status").classList.toggle("done", Boolean(latest));

  renderRhythm(dashboard.today_rhythm);
  renderMoodChart(dashboard.recent_checkins);
  renderNotices(dashboard.notices);
  renderContacts(dashboard.contacts, dashboard.emergency);
  renderFocus(dashboard.active_focus);
  renderLanding(dashboard);
  renderLowBattery(dashboard.low_battery);
}

function renderLanding(dashboard) {
  const parked = dashboard.parked_today || 0;
  const step = dashboard.reserved_first_step;
  const closed = dashboard.day_closed;

  $("#parked-count-label").textContent = `今日の退避: ${parked}件`;

  if (step) {
    $("#first-step-label").textContent = `予約済み: ${step}`;
  } else {
    $("#first-step-label").textContent = "まだ予約なし";
  }

  if (closed) {
    $("#landing-open-state").hidden = true;
    $("#landing-closed-state").hidden = false;
    const detail = [];
    if (parked) detail.push(`退避箱に${parked}件`);
    if (step) detail.push(`明日の入口は「${step}」`);
    $("#landing-closed-detail").textContent = detail.join(" / ") || "";
  } else {
    $("#landing-open-state").hidden = false;
    $("#landing-closed-state").hidden = true;
  }
}

function renderLowBattery(lb) {
  // 編集中（未保存）のチェック/メモは、背景更新で上書きしない
  if (!lb || state.dirty.lowBattery) return;
  const checks = { water: "#lb-water", food: "#lb-food", meds_taken: "#lb-meds" };
  for (const [key, selector] of Object.entries(checks)) {
    $(selector).checked = Boolean(lb[key]);
  }
  if (lb.dont_do) {
    $("#lb-dont-do-text").value = lb.dont_do;
  }
}

function renderRhythm(rhythm) {
  // 編集中（未保存）の時刻入力は、背景更新で上書きしない
  if (state.dirty.rhythm) return;
  const form = $("#rhythm-form");
  for (const input of form.querySelectorAll("input")) {
    input.value = rhythm?.[input.name] || "";
  }
}

function renderMoodChart(checkins) {
  const chart = $("#mood-chart");
  $("#checkin-count").textContent = `${checkins.length}日`;
  if (!checkins.length) {
    chart.innerHTML = '<p class="empty">記録がたまると、ここに7日分の波が見えます。</p>';
    return;
  }
  chart.innerHTML = checkins.map((item) => {
    const mood = item.mood ?? 0;
    const bottom = Math.max(0, Math.min(100, ((mood + 5) / 10) * 100));
    const day = new Intl.DateTimeFormat("ja-JP", { weekday: "short" })
      .format(new Date(`${item.date}T12:00:00`));
    const sleep = item.sleep_hours == null ? " " : `${item.sleep_hours}h`;
    return `<div class="mood-day">
      <div class="mood-track"><span class="mood-dot" style="bottom:${bottom}%" title="気分 ${mood}"></span></div>
      <span>${day}</span><span class="mood-sleep">${sleep}</span>
    </div>`;
  }).join("");
}

function renderNotices(notices) {
  const node = $("#notices");
  if (!notices.length) {
    node.innerHTML = '<p class="empty">今は特別な気づきはありません。</p>';
    return;
  }
  node.innerHTML = notices.map((notice) =>
    `<p class="notice">${escapeHtml(notice.message)}</p>`
  ).join("");
}

function renderContacts(contacts, emergency) {
  const links = contacts.map((contact) => `
    <a class="contact" href="tel:${contact.contact.replaceAll("-", "")}">
      <strong>${escapeHtml(contact.name)}</strong>
      <span>${escapeHtml(contact.contact)}</span>
      <small>${escapeHtml(contact.hours)} / ${escapeHtml(contact.note)}</small>
    </a>`).join("");
  $("#contacts").innerHTML = links + `
    <a class="contact emergency" href="tel:${emergency.contact}">
      <strong>${escapeHtml(emergency.name)}</strong>
      <span>${escapeHtml(emergency.contact)}</span>
      <small>${escapeHtml(emergency.note)}</small>
    </a>`;
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

function renderFocus(active) {
  window.clearInterval(state.timerInterval);
  state.timerInterval = null;
  if (!active) {
    $("#duration-pills").hidden = false;
    $("#focus-toggle").textContent = `${state.focusMinutes}分だけ始める`;
    $("#timer-copy").textContent = "時間が来たら、途中でも閉じて大丈夫です。";
    $("#timer").textContent = `${String(state.focusMinutes).padStart(2, "0")}:00`;
    return;
  }
  $("#duration-pills").hidden = true;
  $("#focus-toggle").textContent = "ここで閉じる";
  $("#timer-copy").textContent = "この1コマだけ。ほかのことは今は見なくて大丈夫です。";

  const tick = () => {
    const started = new Date(active.started_ts).getTime();
    const end = started + active.duration_min * 60 * 1000;
    const seconds = Math.max(0, Math.ceil((end - Date.now()) / 1000));
    $("#timer").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
    if (seconds <= 0) {
      window.clearInterval(state.timerInterval);
      $("#timer-copy").textContent = "時間です。ここで閉じても、少し続けても大丈夫です。";
    }
  };
  tick();
  state.timerInterval = window.setInterval(tick, 1000);
}

async function refresh() {
  try {
    renderDashboard(await api("/api/dashboard"));
  } catch (error) {
    toast(error.message, true);
  }
}

// 背景の自動更新。打ちかけを消さないため、入力フォーカス中・ダイアログ表示中・
// 非表示タブ・前回がまだ処理中のときは何もしない。失敗は黙って見送る
// （数秒ごとにエラー通知を出さないため）。
async function softRefresh() {
  if (state.polling || document.hidden) return;
  if (document.querySelector("dialog[open]")) return;
  const el = document.activeElement;
  if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT")) return;
  state.polling = true;
  try {
    renderDashboard(await api("/api/dashboard"));
  } catch (error) {
    // 背景更新の失敗は通知しない
  } finally {
    state.polling = false;
  }
}

$("#mood").addEventListener("input", (event) => {
  $("#mood-output").textContent = Number(event.target.value) > 0
    ? `+${event.target.value}` : event.target.value;
});

$("#checkin-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const sleep = $("#sleep-hours").value;
  const energy = $("#energy").value;
  try {
    const data = await api("/api/checkin", {
      method: "POST",
      body: JSON.stringify({
        mood: Number($("#mood").value),
        sleep_hours: sleep === "" ? null : Number(sleep),
        energy: energy === "" ? null : Number(energy),
        meds_taken: $("#meds-taken").checked ? true : null,
        note: $("#note").value,
      }),
    });
    renderDashboard(data.dashboard);
    if (data.needs_support) {
      $("#support-dialog").showModal();
      toast("記録しました。いまは人につながることを優先してください。");
    } else if (data.needs_medical_redirect) {
      toast("記録しました。薬や診断の判断は主治医に相談してください。");
    } else {
      toast("今日の波を記録しました。");
    }
  } catch (error) {
    toast(error.message, true);
  }
});

$("#task-add-open").addEventListener("click", () => {
  $("#task-form").hidden = !$("#task-form").hidden;
  if (!$("#task-form").hidden) $("#task-title").focus();
});

$("#task-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = await api("/api/task", {
      method: "POST",
      body: JSON.stringify({ title: $("#task-title").value }),
    });
    $("#task-title").value = "";
    $("#task-form").hidden = true;
    renderDashboard(data.dashboard);
    toast(data.message);
  } catch (error) {
    toast(error.message, true);
  }
});

$("#task-done").addEventListener("click", async () => {
  try {
    const data = await api("/api/task/complete", {
      method: "POST",
      body: JSON.stringify({ task_id: state.dashboard.current_task?.id }),
    });
    renderDashboard(data.dashboard);
    toast(data.message);
  } catch (error) {
    toast(error.message, true);
  }
});

$("#rhythm-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.target).entries());
  try {
    const data = await api("/api/rhythm", { method: "POST", body: JSON.stringify(payload) });
    state.dirty.rhythm = false;
    renderDashboard(data.dashboard);
    toast("覚えている時刻を残しました。");
  } catch (error) {
    toast(error.message, true);
  }
});

$("#duration-pills").addEventListener("click", (event) => {
  const button = event.target.closest("[data-minutes]");
  if (!button) return;
  state.focusMinutes = Number(button.dataset.minutes);
  $$("#duration-pills button").forEach((node) => node.classList.toggle("active", node === button));
  renderFocus(null);
});

$("#focus-toggle").addEventListener("click", async () => {
  try {
    const active = state.dashboard.active_focus;
    const data = await api(active ? "/api/focus/end" : "/api/focus/start", {
      method: "POST",
      body: JSON.stringify(active
        ? { session_id: active.id, result_note: "タイムボックスを閉じた" }
        : { duration_min: state.focusMinutes }),
    });
    renderDashboard(data.dashboard);
    toast(active ? "この1コマを前進として残しました。" : `${state.focusMinutes}分を始めました。`);
  } catch (error) {
    toast(error.message, true);
  }
});

$("#support-open").addEventListener("click", () => $("#support-dialog").showModal());
$("#support-close").addEventListener("click", () => $("#support-dialog").close());

$("#idea-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("#idea-text").value.trim();
  if (!text) return;
  try {
    const data = await api("/api/idea", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    $("#idea-text").value = "";
    renderDashboard(data.dashboard);
    toast("退避箱に入れました。消えません。");
  } catch (error) {
    toast(error.message, true);
  }
});

$("#first-step-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const step = $("#first-step-text").value.trim();
  if (!step) return;
  try {
    const data = await api("/api/first-step", {
      method: "POST",
      body: JSON.stringify({ step }),
    });
    $("#first-step-text").value = "";
    renderDashboard(data.dashboard);
    toast("明日の入口を予約しました。");
  } catch (error) {
    toast(error.message, true);
  }
});

$("#wind-down-close").addEventListener("click", async () => {
  try {
    const data = await api("/api/wind-down", {
      method: "POST",
      body: JSON.stringify({ close: true }),
    });
    renderDashboard(data.dashboard);
    toast("今日はここまで。おやすみなさい。");
  } catch (error) {
    toast(error.message, true);
  }
});

$("#low-battery-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    water: $("#lb-water").checked,
    food: $("#lb-food").checked,
    meds_taken: $("#lb-meds").checked,
    dont_do: $("#lb-dont-do-text").value.trim() || null,
  };
  try {
    const data = await api("/api/low-battery", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.dirty.lowBattery = false;
    renderDashboard(data.dashboard);
    const choices = data.result.choices || [];
    const choicesEl = $("#lb-choices");
    if (choices.length) {
      $("#lb-choices-label").textContent = choices.join(" / ");
      choicesEl.hidden = false;
    } else {
      choicesEl.hidden = true;
    }
    toast("記録しました。今日は維持だけで十分です。");
  } catch (error) {
    toast(error.message, true);
  }
});

// 編集中フラグ。入力が始まったら背景更新で上書きしない（保存時に解除）
$("#rhythm-form").addEventListener("input", () => { state.dirty.rhythm = true; });
$("#low-battery-form").addEventListener("input", () => { state.dirty.lowBattery = true; });

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

// タブに戻ってきたら即更新。以降は数秒ごとに静かに同期。
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) softRefresh();
});
state.pollTimer = window.setInterval(softRefresh, POLL_MS);

refresh();
