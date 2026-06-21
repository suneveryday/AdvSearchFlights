use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use tauri::{AppHandle, Emitter, State};
use tauri_plugin_notification::NotificationExt;
use serde_json::Value;

type SearchTasks = Arc<Mutex<HashMap<String, Arc<Mutex<Child>>>>>;

struct TaskState {
    tasks: SearchTasks,
    queue: Arc<Mutex<SearchQueue>>,
    runtime_payload: Arc<Mutex<Value>>,
}

#[derive(Clone)]
struct SearchJob {
    task_id: String,
    payload: Value,
    source: &'static str,
    group_id: Option<String>,
}

#[derive(Default)]
struct SearchQueue {
    active: Option<SearchJob>,
    manual: VecDeque<SearchJob>,
    scheduled: VecDeque<SearchJob>,
}

impl SearchQueue {
    fn push(&mut self, job: SearchJob) -> bool {
        if job.source == "manual" {
            self.manual.push_back(job);
            true
        } else if !self.contains_group(job.group_id.as_deref()) {
            self.scheduled.push_back(job);
            true
        } else {
            false
        }
    }

    fn pop_next(&mut self) -> Option<SearchJob> {
        self.manual.pop_front().or_else(|| self.scheduled.pop_front())
    }

    fn contains_group(&self, group_id: Option<&str>) -> bool {
        let Some(group_id) = group_id else { return false; };
        self.active.as_ref().and_then(|job| job.group_id.as_deref()) == Some(group_id)
            || self.scheduled.iter().any(|job| job.group_id.as_deref() == Some(group_id))
    }

    fn remove(&mut self, task_id: &str) -> bool {
        let before = self.manual.len() + self.scheduled.len();
        self.manual.retain(|job| job.task_id != task_id);
        self.scheduled.retain(|job| job.task_id != task_id);
        before != self.manual.len() + self.scheduled.len()
    }
}

#[tauri::command]
fn gui_search(payload: Value) -> Result<Value, String> {
    let cli = resolve_cli_path().ok_or_else(|| {
        "无法找到 adv-search-flights。已尝试环境变量 ADV_SEARCH_FLIGHTS_CLI、项目 .venv/bin/adv-search-flights 和系统 PATH。".to_string()
    })?;
    let mut command = Command::new(&cli);
    command
        .arg("gui-search")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    configure_child_path(&mut command, &cli);
    configure_proxy_env(&mut command, &payload);
    configure_search_env(&mut command, &payload);
    let mut child = command.spawn().map_err(|error| {
        format!(
            "无法启动 adv-search-flights gui-search：{error}；尝试的路径：{}",
            cli.display()
        )
    })?;

    {
        let mut stdin = child.stdin.take().ok_or_else(|| "无法写入 gui-search stdin".to_string())?;
        let body = serde_json::to_vec(&payload).map_err(|error| format!("无法序列化搜索参数：{error}"))?;
        stdin.write_all(&body).map_err(|error| format!("写入 gui-search stdin 失败：{error}"))?;
    }

    let output = child.wait_with_output().map_err(|error| format!("等待 gui-search 结束失败：{error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("gui-search 执行失败：{stderr}"));
    }
    serde_json::from_slice(&output.stdout).map_err(|error| format!("gui-search 返回了无法解析的 JSON：{error}"))
}

#[tauri::command]
fn start_gui_search(app: AppHandle, state: State<TaskState>, payload: Value) -> Result<String, String> {
    let task_id = next_task_id();
    let job = SearchJob { task_id: task_id.clone(), payload, source: "manual", group_id: None };
    state.queue.lock().map_err(|_| "无法锁定搜索队列".to_string())?.push(job);
    let _ = app.emit(
        "gui-search-event",
        serde_json::json!({"task_id": task_id, "event": {"type": "queued", "message": "搜索已进入本地串行队列"}}),
    );
    Ok(task_id)
}

fn spawn_search_job(app: AppHandle, tasks: SearchTasks, queue: Arc<Mutex<SearchQueue>>, job: SearchJob) -> Result<(), String> {
    let cli = resolve_cli_path().ok_or_else(|| {
        "无法找到 adv-search-flights。已尝试环境变量 ADV_SEARCH_FLIGHTS_CLI、项目 .venv/bin/adv-search-flights 和系统 PATH。".to_string()
    })?;
    let mut command = Command::new(&cli);
    command
        .arg("gui-search")
        .arg("--stream")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    configure_child_path(&mut command, &cli);
    configure_proxy_env(&mut command, &job.payload);
    configure_search_env(&mut command, &job.payload);
    let mut child = command.spawn().map_err(|error| format!("无法启动流式搜索：{error}"))?;
    let stdout = child.stdout.take().ok_or_else(|| "无法读取 gui-search stdout".to_string())?;
    let stderr = child.stderr.take().ok_or_else(|| "无法读取 gui-search stderr".to_string())?;
    {
        let mut stdin = child.stdin.take().ok_or_else(|| "无法写入 gui-search stdin".to_string())?;
        let body = serde_json::to_vec(&job.payload).map_err(|error| format!("无法序列化搜索参数：{error}"))?;
        stdin.write_all(&body).map_err(|error| format!("写入 gui-search stdin 失败：{error}"))?;
    }
    let child_ref = Arc::new(Mutex::new(child));
    tasks.lock().map_err(|_| "无法锁定搜索任务表".to_string())?.insert(job.task_id.clone(), child_ref.clone());
    let provider = job.payload
        .get("provider")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let process_message = format!("已启动本地搜索进程：provider={provider}");
    let _ = app.emit(
        "gui-search-event",
        serde_json::json!({
            "task_id": job.task_id,
            "event": {
                "type": "process_started",
                "provider": provider,
                "cli_path": cli.display().to_string(),
                "source": job.source,
                "group_id": job.group_id,
                "message": process_message
            }
        }),
    );
    let app_for_stdout = app.clone();
    let app_for_wait = app.clone();
    let task_for_stdout = job.task_id.clone();
    let task_for_wait = job.task_id.clone();
    let group_for_stdout = job.group_id.clone();
    let group_for_wait = job.group_id.clone();
    let completed = Arc::new(Mutex::new(false));
    let completed_for_stdout = completed.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines().map_while(Result::ok) {
            if let Ok(value) = serde_json::from_str::<Value>(&line) {
                if let Some(group_id) = group_for_stdout.as_deref() {
                    match value.get("type").and_then(Value::as_str) {
                        Some("retry_waiting") => { let _ = update_schedule_from_rust(group_id, "rate_limited_wait", None); }
                        Some("retry_started") => { let _ = update_schedule_from_rust(group_id, "running", None); }
                        Some("completed") => {
                            if let Ok(mut flag) = completed_for_stdout.lock() { *flag = true; }
                            let _ = update_schedule_from_rust(group_id, "succeeded", None);
                            if let Some(batch_id) = value.pointer("/envelope/history_batch_id").and_then(Value::as_str) {
                                process_price_alert(&app_for_stdout, group_id, batch_id);
                            }
                        }
                        Some("failed") => {
                            if let Ok(mut flag) = completed_for_stdout.lock() { *flag = true; }
                            let error = value.get("message").and_then(Value::as_str);
                            let _ = update_schedule_from_rust(group_id, "failed", error);
                        }
                        _ => {}
                    }
                    let _ = app_for_stdout.emit("schedule-status-event", serde_json::json!({"group_id": group_id, "event": value}));
                }
                let _ = app_for_stdout.emit("gui-search-event", serde_json::json!({"task_id": task_for_stdout, "event": value}));
            }
        }
    });
    std::thread::spawn(move || {
        let stderr_reader = BufReader::new(stderr);
        let stderr_text = stderr_reader.lines().map_while(Result::ok).collect::<Vec<_>>().join("\n");
        let status = child_ref.lock().ok().and_then(|mut child| child.wait().ok());
        if status.map(|item| !item.success()).unwrap_or(true) && !stderr_text.trim().is_empty() {
            let _ = app_for_wait.emit(
                "gui-search-event",
                serde_json::json!({"task_id": task_for_wait, "event": {"type": "failed", "message": stderr_text}}),
            );
        }
        if let Some(group_id) = group_for_wait.as_deref() {
            let was_completed = completed.lock().map(|flag| *flag).unwrap_or(false);
            if !was_completed {
                let message = if stderr_text.trim().is_empty() { "定时搜索进程异常结束" } else { stderr_text.trim() };
                let _ = update_schedule_from_rust(group_id, "failed", Some(message));
                let _ = app_for_wait.emit("schedule-status-event", serde_json::json!({"group_id": group_id, "event": {"type": "failed", "message": message}}));
            }
        }
        if let Ok(mut table) = tasks.lock() {
            table.remove(&task_for_wait);
        }
        if let Ok(mut state) = queue.lock() {
            if state.active.as_ref().map(|item| item.task_id.as_str()) == Some(task_for_wait.as_str()) {
                state.active = None;
            }
        }
    });
    Ok(())
}

#[tauri::command]
fn cancel_gui_search(state: State<TaskState>, task_id: String) -> Result<(), String> {
    if state.queue.lock().map_err(|_| "无法锁定搜索队列".to_string())?.remove(&task_id) {
        return Ok(());
    }
    let task = state.tasks.lock().map_err(|_| "无法锁定搜索任务表".to_string())?.remove(&task_id);
    if let Some(child) = task {
        child.lock().map_err(|_| "无法锁定搜索任务".to_string())?.kill().map_err(|error| format!("取消搜索失败：{error}"))?;
    }
    Ok(())
}

#[tauri::command]
fn network_check(payload: Value) -> Result<Value, String> {
    let cli = resolve_cli_path().ok_or_else(|| "无法找到 adv-search-flights。".to_string())?;
    let provider = payload.get("provider").and_then(Value::as_str).unwrap_or("fli");
    let mut command = Command::new(&cli);
    command.arg("network-check").arg("--provider").arg(provider).arg("--format").arg("json").stdout(Stdio::piped()).stderr(Stdio::piped());
    configure_child_path(&mut command, &cli);
    configure_proxy_env(&mut command, &payload);
    let output = command.output().map_err(|error| format!("network-check 执行失败：{error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("network-check 执行失败：{stderr}"));
    }
    serde_json::from_slice(&output.stdout).map_err(|error| format!("network-check 返回了无法解析的 JSON：{error}"))
}

#[tauri::command]
fn history_list(limit: Option<u32>) -> Result<Value, String> {
    let cli = resolve_cli_path().ok_or_else(|| "无法找到 adv-search-flights。".to_string())?;
    let mut command = Command::new(&cli);
    command
        .arg("history-list")
        .arg("--format")
        .arg("json")
        .arg("--limit")
        .arg(limit.unwrap_or(50).to_string())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    configure_child_path(&mut command, &cli);
    let output = command.output().map_err(|error| format!("history-list 执行失败：{error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("history-list 执行失败：{stderr}"));
    }
    serde_json::from_slice(&output.stdout).map_err(|error| format!("history-list 返回了无法解析的 JSON：{error}"))
}

#[tauri::command]
fn history_get(batch_id: String) -> Result<Value, String> {
    let cli = resolve_cli_path().ok_or_else(|| "无法找到 adv-search-flights。".to_string())?;
    let mut command = Command::new(&cli);
    command
        .arg("history-get")
        .arg(batch_id)
        .arg("--format")
        .arg("json")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    configure_child_path(&mut command, &cli);
    let output = command.output().map_err(|error| format!("history-get 执行失败：{error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("history-get 执行失败：{stderr}"));
    }
    serde_json::from_slice(&output.stdout).map_err(|error| format!("history-get 返回了无法解析的 JSON：{error}"))
}

#[tauri::command]
fn history_group_list(limit: Option<u32>) -> Result<Value, String> {
    run_history_command(
        "history-group-list",
        &["--format".to_string(), "json".to_string(), "--limit".to_string(), limit.unwrap_or(100).to_string()],
    )
}

#[tauri::command]
fn history_group_get(group_id: String) -> Result<Value, String> {
    run_history_command("history-group-get", &[group_id, "--format".to_string(), "json".to_string()])
}

#[tauri::command]
fn history_group_results(group_id: String, batch_id: Option<String>, filters: Value) -> Result<Value, String> {
    let mut args = vec![group_id];
    if let Some(value) = batch_id {
        args.push("--batch-id".to_string());
        args.push(value);
    }
    args.push("--filters".to_string());
    args.push(serde_json::to_string(&filters).map_err(|error| format!("无法序列化历史筛选：{error}"))?);
    args.push("--format".to_string());
    args.push("json".to_string());
    run_history_command("history-group-results", &args)
}

#[tauri::command]
fn history_group_delete(group_id: String) -> Result<Value, String> {
    run_history_command("history-group-delete", &[group_id, "--format".to_string(), "json".to_string()])
}

#[tauri::command]
fn history_schedule_list() -> Result<Value, String> {
    run_history_command("history-schedule-list", &["--format".to_string(), "json".to_string()])
}

#[tauri::command]
fn history_schedule_toggle(group_id: String, enabled: bool) -> Result<Value, String> {
    run_history_command(
        "history-schedule-toggle",
        &[group_id, "--enabled".to_string(), enabled.to_string(), "--format".to_string(), "json".to_string()],
    )
}

#[tauri::command]
fn history_schedule_configure(
    app: AppHandle,
    state: State<TaskState>,
    group_id: String,
    interval_hours: u32,
    notification_enabled: bool,
    price_threshold: Option<u32>,
) -> Result<Value, String> {
    let mut args = vec![
        group_id.clone(),
        "--enabled".to_string(), "true".to_string(),
        "--interval-hours".to_string(), interval_hours.to_string(),
        "--notification-enabled".to_string(), notification_enabled.to_string(),
    ];
    if let Some(threshold) = price_threshold {
        args.push("--price-threshold".to_string());
        args.push(threshold.to_string());
    }
    args.push("--format".to_string());
    args.push("json".to_string());
    let mut response = run_history_command("history-schedule-toggle", &args)?;
    let schedule = response.get("item").cloned().ok_or_else(|| "定时搜索配置缺少返回数据".to_string())?;
    let mut queued = false;
    if schedule.get("status").and_then(Value::as_str) != Some("paused_expired") {
        if let Some(query) = schedule.get("query") {
            let mut payload = query.clone();
            let runtime = state.runtime_payload.lock().map_err(|_| "无法锁定调度器运行设置".to_string())?;
            merge_scheduler_runtime(&mut payload, Some(&runtime));
            drop(runtime);
            let job = SearchJob {
                task_id: format!("schedule-{}-{}", group_id, next_task_id()),
                payload,
                source: "scheduled",
                group_id: Some(group_id.clone()),
            };
            queued = state.queue.lock().map_err(|_| "无法锁定搜索队列".to_string())?.push(job);
            if queued {
                let _ = update_schedule_from_rust(&group_id, "queued", None);
                let _ = app.emit(
                    "schedule-status-event",
                    serde_json::json!({"group_id": group_id, "event": {"type": "queued", "message": "定时设置已保存，立即搜索已进入队列"}}),
                );
            }
        }
    }
    if let Some(object) = response.as_object_mut() {
        object.insert("immediate_queued".to_string(), Value::Bool(queued));
    }
    Ok(response)
}

#[tauri::command]
fn history_schedule_claim_due() -> Result<Value, String> {
    run_history_command("history-schedule-claim-due", &["--format".to_string(), "json".to_string()])
}

#[tauri::command]
fn history_schedule_update(group_id: String, status: String, error: Option<String>) -> Result<Value, String> {
    let mut args = vec![group_id, "--status".to_string(), status];
    if let Some(message) = error {
        args.push("--error".to_string());
        args.push(message);
    }
    args.push("--format".to_string());
    args.push("json".to_string());
    run_history_command("history-schedule-update", &args)
}

#[tauri::command]
fn alert_permission_status(app: AppHandle, request_reminders: bool) -> Result<Value, String> {
    let desktop = app.notification().request_permission()
        .map(|state| format!("{state:?}").to_lowercase())
        .unwrap_or_else(|_| "error".to_string());
    let (reminders, reminders_message) = if request_reminders {
        match run_osascript("tell application \"Reminders\" to get name of default list") {
            Ok(_) => ("granted", None),
            Err(error) => ("denied", Some(error)),
        }
    } else {
        ("unchecked", None)
    };
    Ok(serde_json::json!({
        "desktop": desktop,
        "reminders": reminders,
        "reminders_message": reminders_message,
    }))
}

#[tauri::command]
fn app_settings_get() -> Result<Value, String> {
    run_history_command("app-settings-get", &["--format".to_string(), "json".to_string()])
}

#[tauri::command]
fn app_settings_update(
    rate_limit_retry_minutes: Option<u32>,
    analytics_consent: Option<String>,
) -> Result<Value, String> {
    let mut args = Vec::new();
    if let Some(minutes) = rate_limit_retry_minutes {
        args.extend(["--rate-limit-retry-minutes".to_string(), minutes.to_string()]);
    }
    if let Some(consent) = analytics_consent {
        args.extend(["--analytics-consent".to_string(), consent]);
    }
    args.extend(["--format".to_string(), "json".to_string()]);
    run_history_command("app-settings-update", &args)
}

#[tauri::command]
fn configure_scheduler(state: State<TaskState>, payload: Value) -> Result<(), String> {
    *state.runtime_payload.lock().map_err(|_| "无法锁定调度器运行设置".to_string())? = payload;
    Ok(())
}

fn update_schedule_from_rust(group_id: &str, status: &str, error: Option<&str>) -> Result<Value, String> {
    let mut args = vec![group_id.to_string(), "--status".to_string(), status.to_string()];
    if let Some(message) = error {
        args.push("--error".to_string());
        args.push(message.to_string());
    }
    args.push("--format".to_string());
    args.push("json".to_string());
    run_history_command("history-schedule-update", &args)
}

fn process_price_alert(app: &AppHandle, group_id: &str, batch_id: &str) {
    let response = run_history_command(
        "history-schedule-evaluate-alert",
        &[group_id.to_string(), batch_id.to_string(), "--format".to_string(), "json".to_string()],
    );
    let item = match response.ok().and_then(|value| value.get("item").cloned()) {
        Some(value) if value.get("should_notify").and_then(Value::as_bool) == Some(true) => value,
        _ => return,
    };
    let price = item.get("price").and_then(Value::as_u64).unwrap_or(0);
    if price == 0 { return; }
    if item.pointer("/channels/desktop").and_then(Value::as_bool) == Some(true) {
        match send_desktop_notification(app, &item) {
            Ok(()) => {
                let _ = record_alert_delivery(group_id, "desktop", price);
                record_diagnostic("notification.sent", serde_json::json!({"group_id": group_id, "price": price}));
                let _ = app.emit("schedule-status-event", serde_json::json!({"group_id": group_id, "event": {"type": "notification_sent", "channel": "desktop"}}));
            }
            Err(error) => {
                record_diagnostic("notification.failed", serde_json::json!({"group_id": group_id, "error": error}));
                let _ = app.emit("schedule-status-event", serde_json::json!({"group_id": group_id, "event": {"type": "notification_failed", "channel": "desktop", "message": error}}));
            }
        }
    }
    if item.pointer("/channels/reminders").and_then(Value::as_bool) == Some(true) {
        match upsert_apple_reminder(&item) {
            Ok(action) => {
                let _ = record_alert_delivery(group_id, "reminders", price);
                record_diagnostic(&format!("reminder.{action}"), serde_json::json!({"group_id": group_id, "price": price}));
                let _ = app.emit("schedule-status-event", serde_json::json!({"group_id": group_id, "event": {"type": "notification_sent", "channel": "reminders"}}));
            }
            Err(error) => {
                record_diagnostic("reminder.failed", serde_json::json!({"group_id": group_id, "error": error}));
                let _ = app.emit("schedule-status-event", serde_json::json!({"group_id": group_id, "event": {"type": "notification_failed", "channel": "reminders", "message": error}}));
            }
        }
    }
}

fn send_desktop_notification(app: &AppHandle, alert: &Value) -> Result<(), String> {
    let route = alert.get("title").and_then(Value::as_str).unwrap_or("航班搜索");
    let price = alert.get("price").and_then(Value::as_u64).unwrap_or(0);
    let threshold = alert.get("threshold").and_then(Value::as_u64).unwrap_or(0);
    app.notification().builder()
        .title("机票价格达到提醒条件")
        .body(format!("{route}：最低 ¥{price}，低于阈值 ¥{threshold}"))
        .show()
        .map_err(|error| format!("桌面通知发送失败：{error}"))
}

fn upsert_apple_reminder(alert: &Value) -> Result<String, String> {
    run_osascript(&build_reminder_script(alert))
}

fn build_reminder_script(alert: &Value) -> String {
    let group_id = alert.get("group_id").and_then(Value::as_str).unwrap_or("unknown");
    let route = alert.get("title").and_then(Value::as_str).unwrap_or("航班搜索");
    let price = alert.get("price").and_then(Value::as_u64).unwrap_or(0);
    let threshold = alert.get("threshold").and_then(Value::as_u64).unwrap_or(0);
    let outbound = alert.pointer("/purchase_links/outbound/url").and_then(Value::as_str).unwrap_or("");
    let inbound = alert.pointer("/purchase_links/inbound/url").and_then(Value::as_str).unwrap_or("");
    let marker = format!("[Farello:{group_id}]");
    let legacy_marker = format!("[AdvSearchFlights:{group_id}]");
    let reminder_name = format!("{route} ¥{price}");
    let reminder_body = format!("{marker} | 阈值 ¥{threshold} | 去程 {outbound} | 回程 {inbound}");
    format!(
        "tell application \"Reminders\"\n\
         if exists list \"Farello\" then\n\
           set targetList to list \"Farello\"\n\
         else if exists list \"AdvSearchFlights\" then\n\
           set targetList to list \"AdvSearchFlights\"\n\
           set name of targetList to \"Farello\"\n\
         else\n\
           set targetList to make new list with properties {{name:\"Farello\"}}\n\
         end if\n\
         set markerText to \"{}\"\n\
         set legacyMarkerText to \"{}\"\n\
         set targetReminder to missing value\n\
         set operationKind to \"updated\"\n\
         repeat with candidateReminder in reminders of targetList\n\
           try\n\
             if completed of candidateReminder is false and (body of candidateReminder contains markerText or body of candidateReminder contains legacyMarkerText) then\n\
               set targetReminder to candidateReminder\n\
               exit repeat\n\
             end if\n\
           end try\n\
         end repeat\n\
         if targetReminder is missing value then\n\
           set targetReminder to make new reminder at end of reminders of targetList\n\
           set operationKind to \"created\"\n\
         end if\n\
         set name of targetReminder to \"{}\"\n\
         set body of targetReminder to \"{}\"\n\
         set due date of targetReminder to current date\n\
         return operationKind\n\
         end tell",
        applescript_string(&marker), applescript_string(&legacy_marker), applescript_string(&reminder_name), applescript_string(&reminder_body),
    )
}

fn applescript_string(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"").replace(['\n', '\r'], " ")
}

fn run_osascript(script: &str) -> Result<String, String> {
    let output = Command::new("/usr/bin/osascript")
        .arg("-e").arg(script)
        .output()
        .map_err(|error| format!("无法运行 Apple Reminders：{error}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn record_alert_delivery(group_id: &str, channel: &str, price: u64) -> Result<Value, String> {
    run_history_command(
        "history-schedule-record-alert",
        &[
            group_id.to_string(), "--channel".to_string(), channel.to_string(),
            "--price".to_string(), price.to_string(), "--format".to_string(), "json".to_string(),
        ],
    )
}

fn record_diagnostic(event: &str, fields: Value) {
    let _ = run_history_command(
        "diagnostics-event",
        &[event.to_string(), "--fields".to_string(), fields.to_string()],
    );
}

fn start_background_workers(app: AppHandle, tasks: SearchTasks, queue: Arc<Mutex<SearchQueue>>, runtime_payload: Arc<Mutex<Value>>) {
    let dispatcher_app = app.clone();
    let dispatcher_tasks = tasks.clone();
    let dispatcher_queue = queue.clone();
    std::thread::spawn(move || loop {
        let next = {
            let mut state = match dispatcher_queue.lock() {
                Ok(value) => value,
                Err(_) => {
                    std::thread::sleep(Duration::from_millis(250));
                    continue;
                }
            };
            if state.active.is_some() {
                None
            } else {
                let job = state.pop_next();
                if let Some(ref item) = job {
                    state.active = Some(item.clone());
                }
                job
            }
        };
        if let Some(job) = next {
            if let Some(group_id) = job.group_id.as_deref() {
                let _ = update_schedule_from_rust(group_id, "running", None);
            }
            if let Err(error) = spawn_search_job(dispatcher_app.clone(), dispatcher_tasks.clone(), dispatcher_queue.clone(), job.clone()) {
                if let Some(group_id) = job.group_id.as_deref() {
                    let _ = update_schedule_from_rust(group_id, "failed", Some(&error));
                    let _ = dispatcher_app.emit("schedule-status-event", serde_json::json!({"group_id": group_id, "event": {"type": "failed", "message": error}}));
                }
                if job.group_id.is_none() {
                    let _ = dispatcher_app.emit("gui-search-event", serde_json::json!({"task_id": job.task_id, "event": {"type": "failed", "message": error}}));
                }
                if let Ok(mut state) = dispatcher_queue.lock() {
                    state.active = None;
                }
            }
        }
        std::thread::sleep(Duration::from_millis(250));
    });

    let scheduler_app = app.clone();
    std::thread::spawn(move || {
        let _ = run_history_command("history-schedule-reset-runtime", &["--format".to_string(), "json".to_string()]);
        loop {
            if let Ok(response) = run_history_command("history-schedule-claim-due", &["--format".to_string(), "json".to_string()]) {
                if let Some(item) = response.get("item").filter(|value| !value.is_null()) {
                    if let (Some(group_id), Some(query)) = (item.get("group_id").and_then(Value::as_str), item.get("query")) {
                        let mut payload = query.clone();
                        merge_scheduler_runtime(&mut payload, runtime_payload.lock().ok().as_deref());
                        let job = SearchJob {
                            task_id: format!("schedule-{}-{}", group_id, next_task_id()),
                            payload,
                            source: "scheduled",
                            group_id: Some(group_id.to_string()),
                        };
                        if let Ok(mut state) = queue.lock() {
                            state.push(job.clone());
                        }
                        let _ = scheduler_app.emit(
                            "schedule-status-event",
                            serde_json::json!({"group_id": group_id, "event": {"type": "queued", "message": "定时自动搜索已进入队列"}}),
                        );
                    }
                }
            }
            std::thread::sleep(Duration::from_secs(30));
        }
    });
}

fn merge_scheduler_runtime(payload: &mut Value, runtime: Option<&Value>) {
    let Some(target) = payload.as_object_mut() else { return; };
    target.insert("output_format".to_string(), Value::String("json".to_string()));
    target.insert("no_cooldown".to_string(), Value::Bool(false));
    target.insert("cooldown_seconds".to_string(), Value::from(2));
    target.insert("retry_waits".to_string(), serde_json::json!([3, 8, 15]));
    target.insert("fli_timeout_seconds".to_string(), Value::from(45));
    target.insert("gui_timeout_seconds".to_string(), Value::from(360));
    target.insert("max_concurrent_searches".to_string(), Value::from(1));
    let Some(source) = runtime.and_then(Value::as_object) else { return; };
    for key in [
        "proxy", "cooldown_seconds", "retry_waits",
        "fli_timeout_seconds", "gui_timeout_seconds",
        "max_concurrent_searches",
    ] {
        if let Some(value) = source.get(key) {
            target.insert(key.to_string(), value.clone());
        }
    }
}

fn run_history_command(name: &str, args: &[String]) -> Result<Value, String> {
    let cli = resolve_cli_path().ok_or_else(|| "无法找到 adv-search-flights。".to_string())?;
    let mut command = Command::new(&cli);
    command.arg(name).args(args).stdout(Stdio::piped()).stderr(Stdio::piped());
    configure_child_path(&mut command, &cli);
    let output = command.output().map_err(|error| format!("{name} 执行失败：{error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("{name} 执行失败：{stderr}"));
    }
    serde_json::from_slice(&output.stdout).map_err(|error| format!("{name} 返回了无法解析的 JSON：{error}"))
}

#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    if !is_allowed_external_url(&url) {
        return Err("只允许打开 Google Flights 链接".to_string());
    }

    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg(&url)
            .spawn()
            .map_err(|error| format!("无法打开默认浏览器：{error}"))?;
        return Ok(());
    }

    #[cfg(not(target_os = "macos"))]
    {
        let _ = url;
        Err("当前版本只支持 macOS 默认浏览器打开".to_string())
    }
}

fn is_allowed_external_url(url: &str) -> bool {
    url.starts_with("https://www.google.com/travel/flights?")
        || url.starts_with("https://www.google.com/travel/flights/booking?")
}

fn next_task_id() -> String {
    let millis = SystemTime::now().duration_since(UNIX_EPOCH).map(|item| item.as_millis()).unwrap_or(0);
    format!("search-{millis}")
}

fn resolve_cli_path() -> Option<PathBuf> {
    if let Ok(value) = std::env::var("ADV_SEARCH_FLIGHTS_CLI") {
        let path = PathBuf::from(value);
        if path.exists() {
            return Some(path);
        }
    }

    if let Ok(current_exe) = std::env::current_exe() {
        let bundled_cli = bundled_cli_path(&current_exe);
        if bundled_cli.exists() {
            return Some(bundled_cli);
        }
    }

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_venv_cli = manifest_dir
        .parent()
        .and_then(Path::parent)
        .map(|repo| repo.join(".venv").join("bin").join("adv-search-flights"));
    if let Some(path) = repo_venv_cli {
        if path.exists() {
            return Some(path);
        }
    }

    Some(PathBuf::from("adv-search-flights"))
}

fn bundled_cli_path(current_exe: &Path) -> PathBuf {
    current_exe
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("farello-backend")
}

fn configure_child_path(command: &mut Command, cli: &Path) {
    if let Some(parent) = cli.parent().filter(|path| !path.as_os_str().is_empty()) {
        let current_path = std::env::var("PATH").unwrap_or_default();
        let next_path = if current_path.is_empty() {
            parent.display().to_string()
        } else {
            format!("{}:{current_path}", parent.display())
        };
        command.env("PATH", next_path);
    }
}

fn configure_proxy_env(command: &mut Command, payload: &Value) {
    let Some(proxy) = payload.get("proxy").and_then(Value::as_object) else {
        return;
    };
    for key in [
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ] {
        if let Some(value) = proxy
            .get(key)
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
        {
            command.env(key, value);
        }
    }
}

fn configure_search_env(command: &mut Command, payload: &Value) {
    if let Some(value) = payload
        .get("fli_timeout_seconds")
        .and_then(Value::as_i64)
        .filter(|value| *value > 0)
    {
        command.env("FLI_TIMEOUT_SECONDS", value.to_string());
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let tasks = Arc::new(Mutex::new(HashMap::new()));
    let queue = Arc::new(Mutex::new(SearchQueue::default()));
    let runtime_payload = Arc::new(Mutex::new(Value::Object(Default::default())));
    let worker_tasks = tasks.clone();
    let worker_queue = queue.clone();
    let worker_runtime = runtime_payload.clone();
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .manage(TaskState { tasks, queue, runtime_payload })
        .setup(move |app| {
            start_background_workers(app.handle().clone(), worker_tasks.clone(), worker_queue.clone(), worker_runtime.clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            gui_search,
            start_gui_search,
            cancel_gui_search,
            network_check,
            history_list,
            history_get,
            history_group_list,
            history_group_get,
            history_group_results,
            history_group_delete,
            history_schedule_list,
            history_schedule_toggle,
            history_schedule_configure,
            history_schedule_claim_due,
            history_schedule_update,
            alert_permission_status,
            app_settings_get,
            app_settings_update,
            configure_scheduler,
            open_external_url
        ])
        .run(tauri::generate_context!())
        .expect("error while running Farello desktop app");
}

#[cfg(test)]
mod tests {
    use super::*;

    fn job(id: &str, source: &'static str, group_id: Option<&str>) -> SearchJob {
        SearchJob {
            task_id: id.to_string(),
            payload: serde_json::json!({}),
            source,
            group_id: group_id.map(str::to_string),
        }
    }

    #[test]
    fn manual_jobs_run_before_queued_schedules_and_schedule_groups_are_deduplicated() {
        let mut queue = SearchQueue::default();
        queue.push(job("scheduled-a", "scheduled", Some("group-a")));
        queue.push(job("scheduled-a-duplicate", "scheduled", Some("group-a")));
        queue.push(job("manual-a", "manual", None));

        assert_eq!(queue.scheduled.len(), 1);
        assert_eq!(queue.pop_next().map(|item| item.task_id), Some("manual-a".to_string()));
        assert_eq!(queue.pop_next().map(|item| item.task_id), Some("scheduled-a".to_string()));
    }

    #[test]
    fn applescript_values_escape_quotes_backslashes_and_newlines() {
        assert_eq!(applescript_string("A \\\"quoted\\\"\nroute"), "A \\\\\\\"quoted\\\\\\\" route");
    }

    #[test]
    fn reminder_script_reuses_the_dedicated_list_and_group_marker() {
        let alert = serde_json::json!({
            "group_id": "group-1",
            "title": "上海 → 墨尔本",
            "price": 7000,
            "threshold": 7500,
            "purchase_links": {
                "outbound": {"url": "https://example.com/outbound"},
                "inbound": {"url": "https://example.com/inbound"}
            }
        });
        let script = build_reminder_script(&alert);
        assert!(script.contains("list \"Farello\""));
        assert!(script.contains("set name of targetList to \"Farello\""));
        assert!(script.contains("[Farello:group-1]"));
        assert!(script.contains("[AdvSearchFlights:group-1]"));
        assert!(script.contains("completed of candidateReminder is false"));
        assert!(script.contains("set operationKind to \"created\""));
        assert!(script.contains("https://example.com/outbound"));
        assert!(script.contains("https://example.com/inbound"));
    }

    #[test]
    fn bundled_cli_is_resolved_next_to_the_app_executable() {
        let current_exe = Path::new("/Applications/Farello.app/Contents/MacOS/farello-desktop");
        assert_eq!(
            bundled_cli_path(current_exe),
            PathBuf::from("/Applications/Farello.app/Contents/MacOS/farello-backend")
        );
    }
}
